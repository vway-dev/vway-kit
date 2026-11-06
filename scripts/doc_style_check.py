#!/usr/bin/env python3
"""산문 게이트: 문서·코드 주석의 문체를 기계로 검사(읽기 전용).

**무엇을 재는가**: [doc-style.md](../rules/doc-style.md) 가 금지한 것 중 **기계가 판정할 수
있는 절반**만 봄 — 변경 이력 서술·커밋 sha·플랜 문서 포인터·군더더기·서술형 종결·과길이.
"한 사실 한 곳"이나 "근거는 유지" 같은 나머지 절반은 사람이 판정하고 여기서 안 다룸.

**무엇을 안 재는가**: 재작성이 내용을 흘렸는지는 [doc_invariants.py](doc_invariants.py) 몫.
둘은 축이 다름 — 이쪽은 "어떻게 썼는가", 저쪽은 "쓰기 전후로 같은 사실이 남았는가".

**두 팔이 같은 범위를 읽음**: 커밋 게이트(`vdev_gate_check.doc_style_gate`)는 변경 파일만
훑고 **경고만** 하고, 판정은 CI(`doc-style.yml`, `--lint-config`) 몫. 범위는 양쪽 다
:func:`in_scope` 하나로 읽음 — 리더가 둘이면 소비자가 쓴 `exclude` 가 한쪽에만 걸림.

사용:
    python3 doc_style_check.py --lint <경로...>   # 지목한 파일
    python3 doc_style_check.py --lint-config      # vdev-config.doc_style 범위 전체(CI)
    [--root <저장소>]

종료 코드: 0 = error 없음(warning 은 포함될 수 있음) · 1 = error 있음.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys
import tokenize
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

try:  # 직접 실행(형제 import) — 호스트 사본은 단일 파일로 놓임
    from _vway_paths import config_path, force_utf8_io, host_root
except ImportError:  # 패키지 import(테스트/개발)
    from scripts._vway_paths import config_path, force_utf8_io, host_root

# CommonMark 의 0~3칸이 아니라 **아무 들여쓰기나** 엶. 목록 항목 안의 펜스는 그보다 깊게
# 들어가고, 그 본문을 산문으로 읽으면 코드가 위반이 됨. 들여쓰기를 잡아 두는 이유는 그것이
# **무엇이 닫는지**도 정하기 때문(_closes 참고).
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
URL = re.compile(r"https?://[^\s)>\]]+")
INLINE_CODE = re.compile(r"`[^`]+`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
# 글자와 숫자를 **둘 다** 가진 7자 이상 16진수 = 커밋 sha. 영어 낱말은 숫자가 없고
# (`deadbeef`), 날짜·바이트 수는 글자가 없다(`20240115`).
SHA = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b")
# UUID 의 각 묶음은 SHA 가 sha 로 읽는 16진수 런이라 기본 마스크가 UUID 통째를 지움.
UUID = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
# 파일명 뒤에 붙은 줄 번호. 확장자 허용목록이 곧 규칙임 — 없으면 `12:30`·
# `localhost:8000`·YAML 의 `key: 3` 이 전부 앵커로 읽힘. 콜론 뒤 공백이 두 읽기를 가름:
# 공백이 없으면 뒤에 무엇이 오든 앵커이고, 있으면 숫자 뒤에 낱말이 안 올 때만 앵커임 —
# 그래서 릴리스 노트의 `CHANGELOG.md: 12 entries landed` 는 문장 그대로 남음. 숫자는
# 선행 0 을 빼고 여섯 자리에서 끊음: 진짜 줄 번호는 둘 다 아니지만 YAML 의 int 강제는
# 그럼 — `src/a.py: 0123456` 은 123456행 포인터가 아니라 int 42798 을 적은 것.
#
# 파일명은 **읽지 않음**. 상류는 경로를 별표로 먼저 먹는데(`[\w.-/\\]*`), 그 별표의 먹이인
# `.` 이 곧 뒤따르는 앵커라 `.` 만 이어진 줄에서 시작 위치마다 런 전체를 되짚음 — 성능 계약이
# 금지하는 모양이고(훅 타임아웃 = 조용히 건너뛴 판정), `\w` 가 한글까지 먹어 한국어 산문에서도
# 같은 값을 냄. 확장자 앞 글자는 고정폭 lookbehind 로 확인하므로 판정은 같고 걸음은 선형임.
# 달라지는 것은 보고되는 조각뿐 — 경로 전체가 아니라 확장자부터 실림.
ANCHOR = re.compile(
    r"(?<=[\w\-])\."
    r"(?:py|sh|bash|md|ya?ml|json|toml|ts|tsx|js|jsx|mjs|cjs|go|rs|java|rb|kt|swift|dart|"
    r"c|h|cc|cpp|hpp|cs|php|sql|html|css|scss|vue|svelte|tf|xml|ini|cfg)"
    r"\s*:(?:[1-9]\d{0,5}(?!\d)"
    r"|[ \t]+[1-9]\d{0,5}(?!\d)(?![ \t]*[^\W\d_]))",
    re.IGNORECASE,
)

MAX_LINE = 100

# TYPE_CHECKING 아래라 아무것도 평가되지 않음: 모듈 최상위 `=` 오른쪽의 별칭은 import 시점에
# **평가되고**, `tuple[...]` 는 python 3.9 이상을 요구함. 게이트의 런타임 하한은 3.8
# (check-deps.sh)이고, 여기서 난 TypeError 는 vdev_gate_check.py 를 함께 죽임 — 그건
# FAIL-OPEN 이라 미분류 커밋이 그대로 통과함.
if TYPE_CHECKING:
    Finding = tuple[str, int, str, str]  # (심각도, 줄 번호, 규칙 코드, 메시지)


# ---------- 산문 추출 ----------


def _closes(opener: re.Match, candidate: re.Match) -> bool:
    """`candidate` 가 `opener` 가 연 블록을 닫는가.

    같은 문자, 길이는 여는 것 이상, info 문자열 없음 — 그리고 여는 것보다 더 들여쓰지 않을 것.
    마지막 조건이 "아무 들여쓰기나 엶"과 짝임: 블록 **안**의 더 깊은 ``` 은 내용이고, 그걸
    닫는 것으로 읽으면 내용이 산문으로 새는 동시에 펜스가 안 닫힌 채 남아 그 아래 문서 전체를
    삼킴(진짜 위반이 그 안에 숨음). CommonMark 가 허용하는 3칸 여유는 남김.
    """
    return (
        candidate.group(2)[0] == opener.group(2)[0]
        and len(candidate.group(2)) >= len(opener.group(2))
        and not candidate.group(3).strip()
        and len(candidate.group(1)) <= len(opener.group(1)) + 3
    )


# 모드마다 무엇을 지우는지, 그리고 `lint_text` 가 줄마다 만들 마스크 목록. 거기서 한 번 더
# 철자되므로 한쪽에만 있는 모드는 게이트가 읽는 첫 산문 줄에서 KeyError 를 냄.
MASK_PATTERNS = {
    "default": (INLINE_CODE, LINK_TARGET, URL, UUID),
    "links": (INLINE_CODE, URL),
    "code": (LINK_TARGET, URL),
}


def _mask(line: str, mode: str = "default") -> str:
    """산문 규칙이 절대 읽으면 안 되는 구간을 공백으로 채움 — 코드·URL·링크 목적지·UUID.

    길이를 보존해야 LONG 이 같은 답을 냄. `keep_link_targets` 는 PLAN 하나를 위한 것:
    백틱에 싸인 `docs/superpowers/plans/` 는 금지 패턴을 **이름 대는** 것이고, 거기로 가는
    링크는 규칙이 금지하는 그 포인터 **자체**다.
    """
    for pattern in MASK_PATTERNS[mode]:
        line = pattern.sub(lambda m: " " * len(m.group(0)), line)
    return line


def markdown_prose(text: str) -> list[tuple[int, str]]:
    """번호 붙은 산문 줄. 펜스 블록과 front matter 는 뺀다(마스킹은 규칙별로 따로)."""
    lines = (text[1:] if text.startswith("\ufeff") else text).split("\n")
    out: list[tuple[int, str]] = []
    opener = None
    start = 0
    if lines and lines[0].strip() == "---":  # YAML front matter
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    for i in range(start, len(lines)):
        line = lines[i]
        m = FENCE.match(line)
        if opener is not None:
            if m and _closes(opener, m):
                opener = None
            continue
        if m:
            opener = m
            continue
        out.append((i + 1, line))
    return out


def python_prose(text: str) -> list[tuple[int, str]]:
    """번호 붙은 산문 줄 — `#` 주석과 모든 독스트링.

    주석과 독스트링을 각각 다른 파서로 읽음: tokenize 는 주석을 주지만 어떤 문자열이
    독스트링인지 모르고, ast 는 그 반대. 파싱 실패는 조용히 건너뜀 — 문법이 깨진 파일은
    문체 위반이 아니라 다른 도구의 일.
    """
    out: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and not tok.string.startswith("# type:"):
                out.append((tok.start[0], tok.string.lstrip("#").strip()))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return sorted(out)
    nodes = [tree] + [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for node in nodes:
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        base = node.body[0].lineno  # 독스트링 표현식 자신
        for offset, line in enumerate(doc.split("\n")):
            out.append((base + offset, line))
    return sorted(out)


def shell_prose(text: str) -> list[tuple[int, str]]:
    """번호 붙은 산문 줄 — `#` 주석에서 shebang 과 도구 지시자를 뺀 것."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped.startswith("#") or stripped.startswith("#!"):
            continue
        body = stripped.lstrip("#").strip()
        if body.startswith(("shellcheck ", "noqa", "-*-")):
            continue
        out.append((i, body))
    return out


def prose_of(path: Path, text: str) -> list[tuple[int, str]]:
    if path.suffix == ".md":
        return markdown_prose(text)
    if path.suffix == ".py":
        return python_prose(text)
    if path.suffix in (".sh", ".bash"):
        return shell_prose(text)
    return []


# ---------- 문체 규칙 ----------

# 줄의 텍스트 앞에 사람이 두는 것 전부 — 목록 불릿, 인용 부호, 헤딩·주석의 `#`, 서수,
# 강조. `^\s*` 는 그중 아무것도 못 먹으므로, 줄머리에 앵커된 규칙은 그것들을 텍스트로
# 읽고 바로 뒤의 라벨이나 키를 놓침.
_HEAD_MARKER = re.compile(r"^[ \t]*(?:[-+]\s|>\s?|#+\s?|\d+[.)]\s|\*{1,2}|_{1,2})")


def _strip_head(line: str) -> str:
    """그 표식들과 앞의 들여쓰기를 걷어낸 줄의 텍스트.

    두 규칙이 한 헬퍼를 씀: META 의 필드 라벨과 TRAP 의 박스 키가 둘 다 무엇이 줄머리인지를
    정하는데, 한쪽에 다르게 읽히는 줄머리가 바로 **바로 다음 줄에 있는 키**를 없다고
    보고하게 만드는 것."""
    while True:
        shorter = _HEAD_MARKER.sub("", line, count=1)
        if shorter == line:
            return line.lstrip()
        line = shorter


# 한글 서술형 종결. 상류의 `[가-힣]다` 를 그대로 쓰면 vway-kit 실측에서 **오탐이 위반보다
# 많음** — 합쇼체 285건과 조사 11건이 걸림. 그래서 앞 글자로 셋을 뺌:
#   `니다` — 합쇼체. [doc-style.md](../rules/doc-style.md) 규칙 1 이 사용자 대상 매뉴얼
#            (README·USAGE)의 합쇼체를 명시 예외로 두므로 규칙상 위반이 아님.
#   `마다`·`보다` — 조사(`파일마다`·`예상보다`). 종결이 아니라 낱말의 일부.
#   `과다`·`쩌다`·`람다` — 명사·부사의 끝(`과다 매칭`·`어쩌다 키가 없으면`·`람다 함수`).
# 뒤의 셋은 **재서** 넣은 목록이지 추론한 것이 아님(앞의 둘은 이 트리에서, `람다` 는
# 리뷰가 구성해 확인한 오탐). `[가-힣]다` 가 종결인지 낱말의 일부인지는 사전 없이 못
# 가르므로, `-다` 로 끝나는 명사가 새로 드러나면 그때 재서 여기 더함.
# `아니다` 는 `니다` 로 끝나지만 합쇼체가 아니라 서술형 종결이라 갈래를 따로 세워 되살림.
#
# 끝을 **따라오는 문자**로 확인하는 이유는 둘. 하나는 `한다면`·`없다는` 같은 연결형을
# 빼는 것이고(금지 대상은 종결이지 어간이 아님), 다른 하나는 줄 끝·마침표만 보면 문장이
# `—`·`)` 로 이어지는 줄을 통째로 놓치기 때문(실측: 마침표·줄끝만 볼 때 97건, 이
# 집합으로 134건 — 늘어난 37건 중 35건이 진짜 종결이고 나머지 둘이 위의 `과다`·`쩌다`).
# 이 집합은 `tests/skill_docs` 가 쓰던 닫힌 종결 목록과 같은 계약이고 그것의 상위집합이라,
# 그쪽이 이 함수에 위임해도 잃는 판정이 없음.
# 미탐은 제외 집합의 값임 — 그 글자로 **끝나는 진짜 종결**은 함께 빠짐: `결과다`·
# `효과다`·`후보다`·`엄마다`(`~이다` 축약), 사전형 `바라보다`, `아니다` 외 `니다` 형.
# 오탐 285건과 바꾼 값이고, 방향은 안전한 쪽임(놓친 위반은 사람이 잡지만 오탐은 CI 를
# 영구히 막고 고칠 방법이 없음). 후행 문자 집합 밖도 미탐 — `질문한다(` 처럼 여는
# 괄호가 뒤에 오면 안 잡힘.
# 콜론도 후행 문자임 — 열거를 여는 문장이 `처리한다:` 로 끝나는 자리가 저장소에 34건
# 있었고 전부 진짜 종결이었음(오탐 0). 뒤따르는 것이 목록이라 마침표가 안 서는 모양임.
KOREAN_ENDING = re.compile(r"(?:아니다|(?![마보니과쩌람]다)[가-힣]다)(?=[\s.,)*·\]:]|$)")

BANNED = (
    (
        "HIST",
        "error",
        re.compile(
            r"\b(previously|formerly|historically|back then|"
            r"at the time|for months|turned out|has since)\b"
            # `used to` 는 서술이고 `is used to` 는 "use" 의 수동태.
            r"|(?<!is )(?<!are )(?<!was )(?<!were )(?<!be )(?<!been )(?<!being )\bused to\b"
            r"|이전에는|예전에|원래는|였다가|바뀌었",
            re.IGNORECASE,
        ),
        "변경 이력 서술 — 지금 힘을 가진 사실만 적음",
    ),
    (
        "SHA",
        "error",
        SHA,
        "산문 속 커밋 sha — squash 머지가 이걸 못 닿는 것으로 만듦",
    ),
    (
        "PLAN",
        "error",
        re.compile(r"docs/superpowers/(plans|specs)/|^\s*[-*]\s*\[[ xX]\]\s"),
        "구현 계획 잔재 — 출하되는 산문은 포인터가 아니라 사실을 실음",
    ),
    (
        "FILLER",
        "error",
        re.compile(
            r"\b(just|really|basically|actually|simply|essentially|obviously|"
            r"in order to|make sure to|be sure to|needless to say|"
            r"it is worth noting|keep in mind|of course)\b"
            # 접속사는 문장을 이을 때만 군더더기 — `however small` 은 양보, `However,` 는 군더더기.
            r"|\b(however|furthermore|moreover|additionally|in addition)\s*,",
            re.IGNORECASE,
        ),
        "군더더기 — 지워도 문장이 뜻을 지킴",
    ),
    (
        "ENDING",
        "error",
        KOREAN_ENDING,
        "서술형 종결 — 명사형으로 끝냄",
    ),
    (
        "CLAIM",
        "warning",
        re.compile(
            # 헤지된 크기만. 맨 숫자는 추측인 만큼이나 자주 측정값이거나 경계값이고, 그 둘을
            # 가르는 패턴은 없음 — 그 반쪽은 rules/doc-style.md 가 적은 판정이라 여기서 못 함.
            #
            # 숫자 런은 **앞이 막힌 상한**으로 읽음. `[0-9.]+` 를 앵커(`%`·`배`) 뒤에 두면
            # `search` 가 시작 위치마다 런 전체를 다시 훑어 2차가 됨 — 실측으로 32KB 19.8초,
            # 96KB 171.6초(배가마다 4배). 훅 타임아웃은 조용히 건너뛴 판정이라 이 파일의
            # 다른 규칙과 같은 선형 계약을 짐(test_every_banned_pattern_stays_linear).
            r"\b(approximately|roughly)\b"
            r"|(?<![0-9.])[0-9.]{1,12}\s{0,4}[%x]\s{0,4}(faster|slower|cheaper|larger|smaller)\b"
            # `약` 은 뒤에 숫자가 오고 **앞에 한글이 없어야** 함. 한국어엔 낱말 경계가 없고
            # 숫자만으론 가드가 못 됨 — 계약·요약·절약이 그 음절로 끝나 `계약 3건` 이 헤지로
            # 읽힘.
            r"|(?<![가-힣])약\s*[0-9]|대략"
            # 르불규칙(빠르다→빨라)이 제일 흔한 활용이라 어간만 보면 통째로 미탐.
            r"|(?<![0-9.])[0-9.]{1,12}\s{0,4}배\s{0,4}[빠빨느]",
            re.IGNORECASE,
        ),
        "아무도 안 잰 크기 — 방향을 적거나, 수치라면 조건과 함께",
    ),
    (
        "ANCHOR",
        "error",
        ANCHOR,
        "줄 번호 앵커 — 파일명만 적을 것. 위에 한 줄만 끼어도 그 숫자는 거짓이 됨",
    ),
    (
        "META",
        "error",
        re.compile(
            # `@author` 류는 어디에 있든, 필드 **라벨**은 줄머리에서만 — `_strip_head` 가
            # 불릿·인용 부호·강조를 이미 걷어낸 자리이고, 마크다운이 변경 메타데이터를
            # 적는 모양이 그것들임.
            #
            # 라벨만으로는 못 정함. `Created`·`Modified`·`History` 는 평범한 낱말이고,
            # 필드와 정의를 가르는 것은 **값**임: 필드는 날짜·버전·이름·식별자를 싣고,
            # 정의는 절을 싣는데 영어는 기능어(`the`·`is`·`from`·`per`…) 없이 절을 못 만듦.
            # 그래서 값 안에서 그런 낱말을 찾으면 절로 읽음 — 콜론 뒤 공백 유무와 무관하고
            # (`Modified:files…` 도 마찬가지), 첫 글자의 대소문자로는 절대 안 정함.
            #
            # 관사도 기능어이지만 `author` 에서만 빼고, 뒤에 낱말이 올 때만 셈. 이름 필드에는
            # 관사가 구해 줄 절이 없으므로 `An Nguyen`·`A Smith` 는 거기서 이름으로 남음.
            # 다른 필드에서는 관사 **뒤의 낱말**이 판정 전부임: 이니셜은 마침표를 달고
            # (`Created: A. Smith`), 잘린 값은 아무것도 안 달음(`History: a`).
            r"@(author|since|date)\b"
            r"|^author\s*:(?![*_]*\s*.*\b(?:the|is|are|was|were|be|been|being|will|now|"
            r"per|from|of|to|in|on|at|and|or)\b)"
            r"|^(created|modified|updated|last updated|revision|history|changelog)"
            r"\s*:(?![*_]*\s*.*\b(?:the|is|are|was|were|be|been|being|will|now|"
            r"per|from|of|to|in|on|at|and|or|(?:an|a)(?=\s+\S))\b)"
            r"|^(작성자|작성일|수정일|변경\s*이력|수정\s*이력)\s*[:：]",
            re.IGNORECASE,
        ),
        "변경 메타데이터 — 이력도 날짜도 이름도 git 이 쥐고 있음",
    ),
)

# 규칙마다 어느 span 을 읽는지. 안 적힌 것은 기본 마스크(:func:`_mask` 참고).
MASK_MODE = {"PLAN": "links", "ANCHOR": "code"}
# 줄의 **텍스트**에 맞추는 규칙 — 줄머리 원본이 아니라. PLAN 은 절대 여기 들면 안 됨:
# `_strip_head` 가 걷어내는 불릿이 PLAN 이 잡는 체크리스트 항목의 일부임.
HEAD_ANCHORED = frozenset({"META"})

# 번역하지 않는 리터럴 — 이 규칙이 **파싱하는 대상**이지 판정하는 산문이 아님. 키는 각자
# 자기 줄의 머리에서 `_strip_head` 뒤에 맞춤: 키가 마커와 같은 줄에 서는 일은 없고,
# 줄머리로 제한해야 문장 중간의 "the Trigger: field" 가 남의 박스를 채우지 못함.
TRAP_MARKER = re.compile(r"CRITICAL TRAP\s*:")
# 앞의 백틱은 선택 — 마커가 박스를 실재하게 만든 뒤라면 인라인 코드로 꾸민 키
# (`` `Trigger:` 인 호스트``)도 여전히 키임. 그것을 보이게 두는 마스크는 :func:`_trap_findings`.
TRAP_KEYS = (
    ("Trigger:", re.compile(r"`?Trigger\s*:")),
    ("Symptom:", re.compile(r"`?Symptom\s*:")),
)


def _blocks(entries: list) -> list:
    """빈 줄 없이 이어진 산문 줄의 덩어리. 각 항목은 ``(줄번호, raw, ...)`` 로 시작하고,
    그 둘 뒤에 호출자가 무엇을 싣든(:func:`_trap_findings` 용 마스크 변종) 여기서는 안 읽음.

    빈 줄이 덩어리를 끊고, 줄 번호의 공백도 끊음: 주석 하나와 그다음 주석은 두 박스이고,
    하나로 읽으면 마커가 아래 것의 키를 빌려 씀. 빈 줄 판정은 **raw** 로만 — 인라인 코드
    스팬 하나뿐인 줄은 마스크하면 공백이 되고, 거기서 끊으면 박스가 반으로 갈려 그 아래
    키들이 없다고 보고됨."""
    out: list = []
    for entry in entries:
        lineno, raw = entry[0], entry[1]
        if not raw.strip():
            continue
        if out and lineno == out[-1][-1][0] + 1:
            out[-1].append(entry)
        else:
            out.append([entry])
    return out


def _trap_findings(entries: list) -> list:
    """한 줄로는 못 답하는 유일한 규칙 — 박스는 세 줄이거나 박스가 아님.

    덩어리가 바깥 단위이지만 박스 둘이 끊기지 않은 주석 하나를 나눠 가질 수 있음(빈 줄도
    번호 공백도 없이 이어진 ``CRITICAL TRAP`` 두 줄). 그래서 덩어리 안에서 마커는 자기부터
    **다음** 마커(없으면 덩어리 끝)까지를 소유하고 그 범위에서만 키를 찾음 — 마커가 뒤 박스의
    키를 빌리지 못하고, 보고되는 줄도 덩어리 첫 줄이 아니라 자기 마커의 줄임.

    마커는 기본 마스크로 읽으므로 백틱 안에서 이름을 대는 것은 다른 규칙과 똑같이 면제됨 —
    ``CRITICAL TRAP:`` 을 인용만 한 문서는 박스가 아님. 키는 대신 `code` 마스크로 읽음:
    마커를 찾은 시점에 박스는 이미 실재하므로 인라인 코드로 꾸민 키도 인용이 아니라 키임.
    둘 다 :func:`_strip_head` 를 지나므로 불릿이나 주석 기호 뒤의 키도 있는 그대로 읽힘."""
    findings = []
    for block in _blocks(entries):
        marker_idxs = [i for i, entry in enumerate(block) if TRAP_MARKER.search(entry[2])]
        for pos, start in enumerate(marker_idxs):
            end = marker_idxs[pos + 1] if pos + 1 < len(marker_idxs) else len(block)
            owned = block[start:end]
            marker = owned[0][0]
            heads = [_strip_head(entry[3]) for entry in owned]
            missing = [
                name
                for name, pattern in TRAP_KEYS
                if not any(pattern.match(head) for head in heads)
            ]
            if missing:
                message = f"CRITICAL TRAP 박스에 {' 와 '.join(missing)} 가 없음"
                findings.append(("error", marker, "TRAP", message))
    return findings


# 규칙이 **명시적으로 허용하는** 꼴을 기계로 — rules/doc-style.md 「누군가 잰 수치, 그것을
# 낸 조건과 함께」. 이 트리의 성능 주석은 실측 곡선을 줄에 적은 뒤 `배수마다 약 4배` 로
# 요약하므로, 그 줄까지 세면 영구히 켜진 경고가 됨 — 그리고 영구히 켜진 경고는 신호가 아니라
# 사람이 건너뛰는 법을 배우는 잡음임. 근거는 **같은 줄**에만 있어야 함: 다른 줄의 측정을
# 끌어오면 파일 하나가 통째로 면제됨.
#
# 두 토큰 다 경계로 막음. `n` 은 왼쪽만 열려 있어도 `len=3`·`plan=3`·`column=1` 이 면제를
# 얻고, `measured` 는 경계가 없으면 `unmeasured` 가 자기를 지목한 규칙에서 스스로 빠짐.
#
# 부정은 못 봄 — `roughly a third (not measured)` 도 조용해짐. 줄 단위 토큰 검사의 한계이고,
# 이 파일이 처음부터 "기계가 판정할 수 있는 절반" 만 맡는 것과 같은 선임.
SILENCED_BY_ITS_CONDITIONS = {
    "CLAIM": re.compile(r"실측|\bmeasured\b|(?<![A-Za-z0-9_])n\s*=\s*[0-9]")
}


def _with_path(line: str, m: re.Match) -> str:
    """매치 왼쪽에 붙은 경로 글자까지 되짚은 조각 — **보고 전용**.

    판정은 lookbehind 가 이미 끝냄. 확장자부터 자른 조각(`.py:58`)은 한 줄에 앵커가 둘일 때
    어느 파일인지 못 가리므로 보고에만 경로를 되살림. 정규식이 아니라 인덱스를 되짚는 이유는
    끝에 고정된 별표가 시작 위치마다 다시 훑어 2차가 되기 때문이고, 이 걸음은 매치가 있을
    때만 돎."""
    i = m.start()
    while i > 0 and (line[i - 1].isalnum() or line[i - 1] in "._-/" + chr(92)):
        i -= 1
    return line[i : m.end()]


def lint_text(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    entries: list[tuple[int, str, str, str]] = []
    for lineno, raw in prose_of(path, text):
        masked = {mode: _mask(raw, mode) for mode in MASK_PATTERNS}
        entries.append((lineno, raw, masked["default"], masked["code"]))
        if not raw.strip():
            continue
        line = masked["default"]
        for code, severity, pattern, message in BANNED:
            excuse = SILENCED_BY_ITS_CONDITIONS.get(code)
            if excuse is not None and excuse.search(line):
                continue
            target = masked[MASK_MODE.get(code, "default")]
            m = pattern.search(_strip_head(target) if code in HEAD_ANCHORED else target)
            if m:
                piece = _with_path(target, m) if code == "ANCHOR" else m.group(0)
                hit = piece.strip() or line.strip()
                findings.append((severity, lineno, code, f"{message} — {hit!r}"))
        # 표는 넘김: 칸 수가 길이를 정하므로 접을 수 없고, 접으면 표가 아니게 됨.
        if len(line) > MAX_LINE and "|" not in line:
            findings.append(
                ("warning", lineno, "LONG", f"산문 한 줄이 {len(line)}자 (상한 {MAX_LINE})")
            )
    findings.extend(_trap_findings(entries))
    return findings


def lint_paths(paths: list[Path]) -> list[tuple[Path, list[Finding]]]:
    out = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings = lint_text(path, text)
        if findings:
            out.append((path, findings))
    return out


# ---------- 범위 ----------

# 규율의 적용 줄([doc-style.md](../rules/doc-style.md) 맨 위)이 주석·독스트링을 산문에 넣으므로
# 기본값도 거기까지 감 — `.md` 에서 멈추면 문서만 규율을 받고 코드 주석은 안 받음. 확장자 집합은
# `prose_of` 가 읽을 줄 아는 것과 같게 둠: 추출기가 아는데 기본값이 안 고르면 조용한 구멍.
# 적용 줄이 말하는 나머지(에이전트 지시문·커밋 본문·다른 언어 주석)는 읽을 방법이 없어 못 닿음.
DEFAULT_GLOBS = ("**/*.md", "**/*.py", "**/*.sh", "**/*.bash")
# 디렉터리 **이름**, 깊이 무관. 벤더링된 트리는 이 저장소의 산문이 아니고, 소비자가 쓴 `paths`
# 가 무엇이든 이건 지킴 — glob 으로 하면 `**/node_modules/**` 를 하나하나 적어야 닿음.
# 가상환경·도구 환경이 여기 있는 이유: 그 안의 서드파티 `.py` 는 실측으로 위반을 내는데(예:
# `site-packages/yaml` 의 `FILLER`) 소비자가 고칠 편집이 없음 — 범위에 들면 CI 가 영구히 붉고
# 그때부터 이 잡은 통째로 무시됨. `.venv` 만 막으면 `venv` 라 이름 붙인 흔한 배치가 새어 듦.
# 여기 없는 이유가 있는 이름들: `build`·`dist`·`env`·`target` 은 손으로 쓴 소스일 수도 있어
# 되돌릴 수 없는 이 집합이 아니라 편집 가능한 `exclude` 몫(vdev-config.example.yaml 이 지목).
NEVER_LINTED = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "site-packages",
        ".tox",
        ".nox",
        "vendor",
        "third_party",
    }
)
# GitHub 의 이슈·PR 템플릿 — 파일 이름과 디렉터리 이름으로, 대소문자·깊이 무관. 템플릿의
# 체크리스트는 기여자가 채우는 양식 자체라 PLAN 이 영구히 막고 고칠 편집이 없음. `exclude` 가
# 아니라 여기 두는 이유: 호스트 소유 설정이라 기본값이 늘어도 기존 호스트에 안 닿음.
GITHUB_FORM_FILES = frozenset({"pull_request_template.md", "issue_template.md"})
GITHUB_FORM_DIRS = frozenset({"pull_request_template", "issue_template"})


def _segment_re(seg: str) -> str:
    """glob 한 세그먼트의 정규식 소스. `*` 와 `?` 는 세그먼트 안에 머묾."""
    out = []
    i = 0
    while i < len(seg):
        char = seg[i]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = seg.find("]", i + 1)
            if end == -1:
                out.append(re.escape(char))
            else:
                # 클래스 안의 백슬래시·`[` 는 이스케이프해서 정규식에 닿아야 함 — 맨 `[` 는
                # 합법이지만 중첩 집합 경고를 냄.
                body = seg[i + 1 : end].replace("\\", "\\\\").replace("[", "\\[")
                body = ("^" + body[1:]) if body.startswith("!") else body
                out.append("[" + body + "]")
                i = end
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


@lru_cache(maxsize=512)
def _glob_re(pattern: str) -> re.Pattern:
    """`paths`/`exclude` glob 을 저장소 상대 posix 경로용 정규식으로 컴파일.

    `*`/`?` 는 `/` 에서 멈추고, 세그먼트 통째인 `**` 는 디렉터리를 **0개 포함해** 몇 겹이든
    이음(그래서 `docs/**/*.md` 가 `docs/a.md` 도 덮음). 끝에 온 `**` 는 서브트리 전체.

    이 모듈에서 glob 을 읽는 곳은 여기 하나 — :func:`config_paths` 도 트리를 걸으며 같은
    질문을 던지지 `Path.glob` 에 패턴을 넘기지 않음. 리더가 둘이면 훅과 CI 가 소비자의
    `paths` 를 두고 서로 다른 답을 냄. `Path.glob` 은 애초에 둘째 리더가 될 수도 없음:
    끝의 `**` 가 무엇을 뜻하는지가 3.13 전후로 갈리고, Windows 에서는 대소문자를 안 가리는데
    Linux 러너에서는 가림.

    컴파일 안 되는 패턴은 `ValueError` — CLI 는 그걸 종료 코드로, 훅은 fail-open 으로
    바꿈. 파싱 안 되는 설정과 같은 취급.
    """
    parts = pattern.split("/")
    out = []
    for at, seg in enumerate(parts):
        if seg == "**":
            out.append(".*" if at == len(parts) - 1 else "(?:[^/]+/)*")
        else:
            out.append(_segment_re(seg) + ("/" if at < len(parts) - 1 else ""))
    try:
        return re.compile("".join(out) + r"\Z")
    except re.error as exc:
        raise ValueError(f"doc_style glob {pattern!r} 을 쓸 수 없음: {exc}")


def _match(rel: str, pattern: str) -> bool:
    """저장소 상대 posix 경로 `rel` 이 `paths`/`exclude` glob 에 걸리는가."""
    return bool(_glob_re(pattern).match(rel))


# YAML 이 못 읽은 파일에 대해 답해야 할 물음 하나 — 이 저장소가 켜 달라고 했는가 — 를 위한
# `doc_style` 블록의 겉모습. 따옴표는 YAML 에서 선택이고 키를 바꾸지 않으므로, `"doc_style":` 로
# 적은 저장소도 똑같이 요청한 것. 놓치면 raise 가 막으려던 침묵을 바로 그 저장소가 받음.
_OPTED_IN_RE = re.compile(r"^[ \t]*['\"]?doc_style['\"]?[ \t]*:", re.M)


def scope_rules(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """vdev-config 의 `doc_style` 블록에서 (paths, exclude). 없거나 꺼져 있으면 None.

    설정 부재는 한 번도 켠 적 없는 저장소의 정상 상태라 오류가 아니라 "검사할 것 없음"으로
    읽음 — 그래야 CI 가 두 번째 가드 없이 초록. **있고, 깨졌고, `doc_style` 키를 가진** 설정은
    반대: "꺼짐"으로 읽으면 오타 하나가 레이어 3 을 아무 붉은 잡 없이 내림. 그 키 **없이** 깨진
    설정은 부재로 읽음 — 켠 적 없는 저장소가 doc-style 소유도 아닌 파일의 오타로 붉은 빌드를
    받지 않음. raise 하되
    `SystemExit` 이 아닌 평범한 `ValueError` — 훅의 `except Exception` 이 그걸 잡아
    FAIL-OPEN(Invariant #1) 하고, 종료 코드가 되는 자리는 CLI 뿐.
    """
    try:
        text = config_path(root).read_text(encoding="utf-8")
    except OSError:
        return None
    import yaml

    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        # 켜 달라고 한 저장소에만 raise. 파싱 안 되는 파일은 `doc_style` 블록이 있는지 말하지
        # 못하므로 원문에 물음 — 없으면 켠 적이 없는 것이고, 있으면 위 근거가 그대로 섬.
        if not _OPTED_IN_RE.search(text):
            return None
        # 붉은 이유가 문체가 아니라 설정임을 말함 — 잡 이름이 doc-style 이라 문체로 읽히기 쉽고,
        # `enable: false` 인 저장소에도 이 실패가 커밋 게이트가 미분류 커밋을 통과시키는 중이라는
        # 유일한 신호임.
        raise ValueError(
            "vdev-config.yaml 이 YAML 로 안 읽힘 — 문체 위반이 아님. 이 설정이 깨진 동안 커밋"
            " 게이트는 미분류 커밋도 막지 못함(FAIL-OPEN). doc-style 을 껐어도 설정부터 고칠 것:"
            f" {exc}"
        )
    cfg = data.get("doc_style") if isinstance(data, dict) else None
    if not isinstance(cfg, dict) or not cfg.get("enable"):
        return None
    return _globs(cfg, "paths", DEFAULT_GLOBS), _globs(cfg, "exclude", ())


def _globs(cfg: dict, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """`cfg[key]` 를 glob 튜플로. 모양이 틀리면 `ValueError` — 조용히 좁히지 않음.

    문자열 하나(`paths: "**/*.md"`)는 특히 위험함. `tuple()` 이 그걸 **글자 단위**로 쪼개
    범위가 말없이 엉뚱해지고, 두 팔 모두 오류 없이 그 범위를 따름 — CI 가 초록인 채로
    검사 대상이 사라짐. 리스트 아닌 값(`exclude: 5`)도 여기서 잡아야 `in_scope` 의
    `except ValueError` 에 걸림(안 잡으면 훅에선 raw TypeError 로 FAIL-OPEN, CI 에선
    문서화된 메시지 대신 트레이스백).
    """
    value = cfg.get(key)
    if value is None or value == []:
        return default
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"doc_style.{key} 는 문자열 리스트여야 함(받은 값: {value!r})")
    return tuple(value)


def in_scope(root: Path, paths: list[Path], fail_open: bool = True) -> list[Path]:
    """`paths` 중 설정이 범위에 넣는 것들. 설정이 없거나 꺼져 있으면 [].

    게이트의 두 팔이 범위를 여기서 읽음. 그래서 CI 를 보고 쓴 `paths`/`exclude` 를 훅이
    무시할 수 없고, 훅이 CI 가 보지도 않을 파일을 두고 경고할 수도 없음. 둘을 가르는 것은
    `fail_open` 하나 — 파싱 안 되는 설정·glob 은 커밋 게이트에선 "범위 없음"이고
    (Invariant #1), 붉은 잡이 목적인 CLI 에선 raise.
    """
    try:
        rules = scope_rules(root)
        if rules is None:
            return []
        globs, excluded = rules
        for pattern in tuple(globs) + tuple(excluded):
            _glob_re(pattern)  # 경로를 판정하기 **전에** 모든 패턴을 컴파일해 봄
    except ValueError:
        if fail_open:
            return []
        raise
    return _filter(root, paths, globs, excluded)


# 블록이 꺼졌거나 없는 저장소의 리뷰 범위 제외 — `vdev-config.example.yaml` 의 기본 `exclude` 와
# 같은 셋. 둘 다 어떤 편집으로도 못 통과하는 파일이라 리뷰가 고칠 것이 없음.
REVIEW_EXCLUDES = ("**/CHANGELOG.md", "docs/superpowers/**", ".superpowers/**")


def review_scope(root: Path, paths: list[Path]) -> list[Path]:
    """`paths` 중 산문 리뷰가 덮는 것 — 설정의 범위, 또는 `doc_style` 이 꺼졌거나 없거나 못
    읽히면 기본 범위. 규율은 린트 게이트가 도는지와 무관하게 출하 `.md` 와 코드 주석을 묶음."""
    try:
        rules = scope_rules(root)
        if rules is not None:
            for pattern in rules[0] + rules[1]:
                _glob_re(pattern)
    except ValueError:
        rules = None
    globs, excluded = rules if rules is not None else (DEFAULT_GLOBS, REVIEW_EXCLUDES)
    return _filter(root, paths, globs, excluded)


def _is_github_form(rel: Path) -> bool:
    if rel.name.lower() in GITHUB_FORM_FILES:
        return True
    return any(part.lower() in GITHUB_FORM_DIRS for part in rel.parts[:-1])


def _filter(root: Path, paths: list[Path], globs, excluded) -> list[Path]:
    root_resolved = root.resolve()
    out = []
    for path in paths:
        try:
            rel = path.resolve().relative_to(root_resolved)
        except (ValueError, OSError):
            continue
        if not NEVER_LINTED.isdisjoint(rel.parts) or _is_github_form(rel):
            continue
        posix = rel.as_posix()
        if any(_match(posix, rule) for rule in excluded):
            continue
        if any(_match(posix, glob) for glob in globs):
            out.append(path)
    return out


def config_paths(root: Path) -> list[Path]:
    """`doc_style` 블록이 범위에 넣는 저장소의 모든 파일 — CI 쪽 팔.

    트리를 걸어 모든 파일을 훅과 같은 :func:`in_scope` 에 넘김. 대신 glob 을 `Path.glob`
    에 넘기면 두 팔이 갈림(:func:`_glob_re` 참고). 깨진 설정·glob 이 종료 코드가 되는
    자리가 여기 — 붉은 것이 목적.
    """
    try:
        if scope_rules(root) is None:
            return []
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in NEVER_LINTED]
            found += [Path(dirpath) / name for name in filenames]
        return sorted(in_scope(root, found, fail_open=False))
    except ValueError as exc:
        raise SystemExit(str(exc))


# ---------- 보고 ----------


def report(items: list[tuple[Path, list[Finding]]], root: Path) -> int:
    """찾은 것을 stderr 로 내고 **error 개수**를 돌려줌(warning 은 종료 코드에 안 실림)."""
    errors = 0
    for path, findings in items:
        try:
            name = path.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            name = str(path)
        for severity, lineno, code, message in findings:
            errors += severity == "error"
            where = f"{name}:{lineno}" if lineno else name
            print(f"{where}: {severity.upper()} {code}: {message}", file=sys.stderr)
    return errors


def main(argv: list[str] | None = None) -> int:
    force_utf8_io()  # Invariant #2 — 어떤 print 보다 먼저
    parser = argparse.ArgumentParser(
        prog="doc_style_check.py", description="산문 문체 검사(읽기 전용)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--lint", nargs="*", metavar="PATH", help="지목한 파일만 검사")
    mode.add_argument(
        "--lint-config", action="store_true", help="vdev-config.doc_style 범위 전체(CI)"
    )
    mode.add_argument(
        "--scope", nargs="*", metavar="PATH", help="리뷰 범위로 좁힌 경로를 루트 상대로 출력"
    )
    parser.add_argument("--root", default=None, help="저장소 루트(기본: 호스트 루트 자동 탐지)")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else host_root()
    if args.scope is not None:
        for path in review_scope(root, [Path(p) for p in args.scope]):
            print(path.resolve().relative_to(root.resolve()).as_posix())
        return 0
    paths = config_paths(root) if args.lint_config else [Path(p) for p in (args.lint or [])]
    return 1 if report(lint_paths(paths), root) else 0


if __name__ == "__main__":
    sys.exit(main())
