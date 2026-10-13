"""이 저장소의 마크다운 소비자들이 쓰는 GitHub 앵커 규칙.

자기 모듈인 이유는 진입점 셋 — `harness_scaffold.validate_plan` 은 생성 시점 플랜의
링크를, `srs_check` 는 사람이 손으로 고친 SRS 를, `alm_docs.scan` 은 그 SRS 의 앵커를
줄 번호와 함께 봄. 호스트는 이것들을 평평한 형제 파일로 받으므로, 공유 헬퍼는 거기
복사되지 않는 `harness_scaffold` 없이도 import 가능해야 함.
여기 태그 패턴을 고칠 때 소비자가 셋인 것이 값을 냄 — 좁히는 변경은 앵커 **정의** 스캔과
링크 **조회** 양쪽에 걸리고, 두 쪽의 입력이 다름(문서 전체 vs 앵커 한 줄).
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import unquote

# 한 패턴이 아니라 두 단계: `<a\s(?:[^>]*\s)?id=` 는 `[^>]*` 와 `\s` 가 겹쳐 긴 태그에서
# 이차가 됨. `data-id=` 를 밖에 두는 것은 `(?:^|\s)` 경계.
# 태그 본문이 `<` 도 못 넘는 이유는 겹침이 아니라 **시작 자리**임 — `[^>]*` 만으로는 `>` 가
# 없는 구간에서 `<a ` 하나하나가 남은 본문을 훑어 입력이 배가할 때마다 네 배로 자람.
# 셋 중 계수는 제일 작음 — `>` 를 요구해 실패가 빨리 나지만 시작 자리마다 다시 훑는 것은
# 같음. 초 단위 수치를 안 적는 이유는 그것이 기계·부하에 매달려 두 번 틀렸던 것 — 자라는
# 차수와 셋의 대소만 적고, 재는 것은 `tests/md_anchors/test_linearity.py` 의 시간 가드임.
# 태그 본문에 `<` 가 못 오므로 정상 입력에서 결과가 같고, 깨진 입력에서는 남의 태그 id 를
# 안 세는 쪽으로 좁아짐.
_A_TAG_RE = re.compile(r"<a\s[^<>]*>", re.IGNORECASE)
_ID_ATTR_RE = re.compile(r"(?:^|\s)id\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
# 닫는 `#` 런은 파이썬이 뗌. `\s*#*\s*$` 로 두면 공백 런 하나를 두 갈래로 가르는 동안
# lazy `(.+?)` 가 그 위로 다시 자람 — 세제곱, 2.4KB 헤딩 줄에 18초. `[ \t]` 는 `\s` 가
# 개행을 넘는 것도 막되, 그 좁힘이 밑줄 꼬리와 빈 줄 판정 둘 다에서 CRLF 의 `\r` 까지
# 막으므로 그 둘만 되돌림(Invariant 2 — 플랜 content 는 디스크와 달리 개행이
# 정규화되지 않은 채 들어옴).
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+)$", re.MULTILINE)
_SETEXT_RE = re.compile(
    r"^(?![ \t]*\r?$)(?![ \t]{0,3}#)(.+)\n[ \t]{0,3}(?:=+|-+)[ \t]*\r?$", re.MULTILINE
)
_MD_INLINE_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# 렌더러가 지우는 것 = 제대로 된 태그·주석뿐. 느슨한 `<[^>]+>` 는 GitHub 가 남기는
# `Map<K,V>`·`2 < 3` 까지 먹음. 속성 자리가 `<` 를 못 넘는 근거는 `_A_TAG_RE` 와 같되 계수는
# 셋 중 제일 큼 — 좁히기 전 이 패턴이 제일 오래 걸림.
_HTML_TAG_RE = re.compile(r"<!--.*?-->|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>", re.DOTALL)
# 완결된 엔티티만: `html.unescape` 는 CommonMark 가 리터럴로 두는 `&amp`·`&copy` 도 디코드함.
_HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
_SLUG_DROP_RE = re.compile(r"[^\w\s-]", re.UNICODE)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")


def _strip_frontmatter(text: str) -> str:
    """frontmatter 블록을 제거한 본문만 반환(링크 스캔이 메타데이터를 건드리지 않게)."""
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    return text[m.end() :] if m else text


def _strip_code(text: str) -> str:
    """코드 펜스·인라인 코드를 제거(링크 스캔이 코드 예시를 dead-link 로 오탐하지 않게)."""
    return _INLINE_CODE_RE.sub("", _CODE_FENCE_RE.sub("", text))


def _slugify(text: str) -> str:
    """`github-slugger` 가 내는 GitHub 헤딩 슬러그.

    규칙이 갈리는 지점 셋: `_` 는 살고, 공백은 구두점 제거 **뒤에** 각자 `-` 가 되며
    (`## Step 1 — Classify` -> `step-1--classify`), re.UNICODE 의 `\\w` 가 한글을 남김.
    """
    text = _MD_INLINE_LINK_RE.sub(r"\1", text)
    # GitHub 이 슬러그하는 것은 렌더된 텍스트. 태그가 먼저 — 먼저 디코드하면 `&lt;script&gt;`
    # 가 태그 모양이 되어 뒤이은 제거가 먹어 버림.
    text = _HTML_ENTITY_RE.sub(lambda m: unescape(m.group(0)), _HTML_TAG_RE.sub("", text))
    return _SLUG_DROP_RE.sub("", text.strip().lower()).replace(" ", "-")


def _has_anchor(text: str, frag: str) -> bool:
    """`frag` 가 `text` 의 명시 <a id> 나 헤딩을 가리키면 True.

    헤딩은 순서대로 걸음: GitHub 은 반복 슬러그에 `-1`·`-2` 를 붙임. 두 조회 모두에서
    front matter 와 코드 펜스는 걷어냄 — 어느 쪽도 렌더되지 않음. 인라인 코드 스팬은 남김
    (GitHub 은 렌더된 텍스트를 슬러그함).
    """
    body = _CODE_FENCE_RE.sub("", _strip_frontmatter(text))
    # GitHub 에서 복사한 앵커는 퍼센트 인코딩으로 옴.
    wanted = {frag.lower(), unquote(frag).lower()}
    explicit = (a for tag in _A_TAG_RE.findall(body) for a in _ID_ATTR_RE.findall(tag))
    if wanted & {a.lower() for a in explicit}:
        return True
    seen: dict[str, int] = {}
    for heading in _HEADING_RE.findall(body) + _SETEXT_RE.findall(body):
        # 패턴이 더는 먹지 않는 ATX 닫는 런.
        base = _slugify(heading.rstrip().rstrip("#").rstrip())
        nth = seen.get(base, 0)
        seen[base] = nth + 1
        if (base if nth == 0 else f"{base}-{nth}") in wanted:
            return True
    return False


# 저작 예시가 사는 자리 둘. `_HTML_TAG_RE` 를 쓰지 않는 이유는 그쪽이 진짜 `<a>` 태그까지
# 벗겨 내어 앵커 **정의** 스캔에 못 쓰이는 것.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# `[^<>]*` 뒤에 오는 것이 `\b` 라 `_A_TAG_RE` 가 피하는 겹침(`[^>]*` + `\s`)이 없음 — 한
# 패턴으로 둠. `>` 만이 아니라 `<` 도 막는 이유는 `_A_TAG_RE` 와 같은 시작-자리 이차성임 —
# 계수는 셋 중 가운데.
_ANCHOR_ID_RE = re.compile(r'<a\s[^<>]*\bid\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def mask_examples(text: str) -> str:
    """코드 펜스·HTML 주석을 같은 길이의 공백으로 덮음.

    제외 대상은 `srs_check._strip_examples` 와 같고, 다른 점은 **줄 번호와 열의 보존** —
    앵커가 몇째 줄인지 보고해야 하는 소비자(`alm_docs`)의 몫. 개행은 그대로 두어 줄 수가
    안 바뀜. 펜스를 먼저 덮는 순서도 그쪽과 같음 — 펜스 안의 주석은 이미 예시임.
    """

    def blank(m: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in m.group(0))

    return _HTML_COMMENT_RE.sub(blank, _CODE_FENCE_RE.sub(blank, text))
