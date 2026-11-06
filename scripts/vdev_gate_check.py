"""vdev-config 기반 게이트 검사 헬퍼.

호스트 저장소 경로는 CLAUDE_PROJECT_DIR 환경변수로만 접근하며,
내부 오류 시 게이트를 막지 않음 (fail-open).
"""

from __future__ import annotations

import bisect
import contextlib
import functools
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# 호스트 루트 해석·인코딩 방어·게이트 계약 상수(차단 exit code·런타임 게이트 키·티어
# 라벨)는 공용 SSOT(_vway_paths)에서 가져옴(중복 정의 금지 — rule-dry-constants).
# vdev_gate_check 는 호스트로 복사돼 직접 실행되거나(형제 import) 테스트에서 패키지로
# import 됨 — _vway_paths 모듈 docstring 의 양립 관용구 참조.
try:
    from _vway_paths import (
        _PATH_TOKEN,
        BLOCK_EXIT_CODE,
        CHECK_TIMINGS,
        CONFIG_DIR,
        OPAQUE_CH,
        RELEASE_TIER,
        RUNTIME_GATES,
        STAGING_TIER,
        TIERS_FILENAME,
        GitSubcommand,
        _blank_redirections,
        _git_common_dir,
        _list_elements,
        _short_bundle_takes_next,
        _spelled_with_quotes,
        call_operands,
        commit_tree_unresolved,
        config_path,
        dash_c_value,
        force_utf8_io,
        git_invocations,
        git_subcommand_re,
        host_root,
        is_invocation,
        mask_literals,
        operand_end,
        operand_words,
        reparse_depth,
        runs_among_operands,
        unquote_path,
        vdev_dir,
        working_root,
    )
except ImportError:
    from scripts._vway_paths import (
        _PATH_TOKEN,
        BLOCK_EXIT_CODE,
        CHECK_TIMINGS,
        CONFIG_DIR,
        OPAQUE_CH,
        RELEASE_TIER,
        RUNTIME_GATES,
        STAGING_TIER,
        TIERS_FILENAME,
        GitSubcommand,
        _blank_redirections,
        _git_common_dir,
        _list_elements,
        _short_bundle_takes_next,
        _spelled_with_quotes,
        call_operands,
        commit_tree_unresolved,
        config_path,
        dash_c_value,
        force_utf8_io,
        git_invocations,
        git_subcommand_re,
        host_root,
        is_invocation,
        mask_literals,
        operand_end,
        operand_words,
        reparse_depth,
        runs_among_operands,
        unquote_path,
        vdev_dir,
        working_root,
    )

# wiki 런타임 게이트도 같은 형제-vs-패키지 관용구를 쓰되 **3번째 분기**가 있음 — 이 형제는
# 진짜로 선택적이기 때문. 플러그인 스크립트는 호스트로 *한 파일씩* 복사되므로
# (_vway_paths 모듈 docstring 참조) wiki_graph.py 없이 vdev_gate_check.py 만 가진 호스트가
# 성립함. 가드 없는 import 는 그런 호스트에서 이 파일 전체를 import 불가로 만들어 tier·
# 마커 게이트까지 함께 죽이고 강제를 조용히 꺼버림. None → wiki_gate 가 통과할 뿐,
# 나머지는 그대로. 순환 아님: wiki_graph 는 _vway_paths 만 import 함.
try:
    from wiki_graph import cmd_verify  # 직접 실행(형제)
except ImportError:
    try:
        from scripts.wiki_graph import cmd_verify  # 패키지(테스트/개발)
    except ImportError:
        cmd_verify = None

# doc-style 런타임 게이트. 선택적인 이유는 같음 — doc_style_check.py 없이 이 파일만 가진
# 호스트가 성립함. None → 게이트가 아무것도 보고하지 않을 뿐.
# `except ImportError` 가 아니라 `except Exception` 인 이유: 형제가 import 중에 무엇이든
# 던지면(호스트 python 이 못 읽는 문법, 잘못된 모듈 수준 표현식) **이 모듈까지** 함께
# 죽음. 아예 안 도는 vdev_gate_check.py 는 게이트가 조용히 꺼진 것이고, 거기엔 미분류
# 커밋 fail-closed 차단도 포함됨.
try:
    from doc_style_check import in_scope, lint_paths  # 직접 실행(형제)
except Exception:
    try:
        from scripts.doc_style_check import in_scope, lint_paths  # 패키지(테스트/개발)
    except Exception:
        in_scope = lint_paths = None


def load_lifecycle_branches(config_path: Path) -> dict[str, str]:
    """vdev-config.yaml의 branches 섹션을 읽어 {브랜치명: 티어} 매핑을 반환.

    - staging 키 → "staging" 티어
    - production 키 → "release" 티어
    - 파일이 없거나 파싱 오류 시 {} 반환 (fail-open)
    """
    if not config_path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    branches = data.get("branches") or {}
    out: dict[str, str] = {}
    if staging := branches.get("staging"):
        out[str(staging)] = STAGING_TIER
    if production := branches.get("production"):
        out[str(production)] = RELEASE_TIER
    return out


def required_gates(tiers_path: Path, tier: str) -> list[str] | None:
    """vdev-tiers.yaml에서 특정 tier의 gates 목록을 반환.

    - tier가 없으면 None 반환
    - 파일이 없거나 파싱 오류 시 None 반환 (fail-open)
    """
    if not tiers_path.is_file():
        return None
    try:
        import yaml

        data = yaml.safe_load(tiers_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    node = (data.get("tiers") or {}).get(tier)
    return list(node.get("gates", [])) if node else None


def load_merge_strategy(tiers_path: Path) -> list[dict]:
    """vdev-tiers.yaml 의 merge_strategy 규칙 리스트를 반환.

    파일 부재·파싱 실패·키 부재·리스트가 아님은 모두 [] (FAIL-OPEN — Invariant #1).
    키를 통째로 지우면 검사가 꺼짐.
    """
    if not tiers_path.is_file():
        return []
    try:
        import yaml

        data = yaml.safe_load(tiers_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    rules = data.get("merge_strategy")
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict)]


# 명령이 실제로 내는 `git … merge` 호출. 문자열의 첫 ` merge` 가 아님 — 커밋 쪽 문법을
# 공유하는 것이 요점. 따옴표 인자·heredoc 본문 안의 낱말은 텍스트이고, 거기서 자르면
# 피연산자 영역이 문자열 중간에서 시작하거나(shlex 가 터져 전략 판정이 아예 안 돎) 머리가
# 잘려 다른 워크트리를 지목하는 `-C` 를 잃음. 온전한 단어 종결 규칙이라
# `git merge-base`/`git merge-file` 은 오탐하지 않음.
# 커밋 쪽은 자기 정규식을 두지 않음 — `is_invocation` 이 이 명령이 무엇인지에 대한
# 유일한 권위이고, 여기 사본을 두면 두 벌이 되어 서로 다르게 틀림(실제로 그랬음).
_MERGE_RE = git_subcommand_re("merge")


def _merge_match(command: str) -> _MergeCall | None:
    """이 명령이 **판정 대상으로 삼는** 첫 머지 — 소스를 지목하는 `git merge` 또는 브랜치를
    대는 `git pull`.

    앵커는 판정(`_judged`)과 **한 기준**이어야 함. 여기서 소스 없는 머지
    (`--abort`·`--continue`)까지 세면 그것이 머리를 앞당겨, 뒤에 선 진짜 switch 가
    "merge 앞"에서 밀려남 — `_switch_targets` 가 그 switch 를 못 보고 `_target_from_command` 가
    None 이 되어, 호출측이 switch 폴백을 건너뛰고 낡은 훅 시점 HEAD 로 심사.
    `git merge --abort && git switch dev && git merge feature/x` 에서 러너 exit 2 → 0,
    `git merge --abort && git switch dev && git merge stage` 는 반대로 없는 flow 로
    오차단(실측). 소스 없는 머지는 판정 대상이 아니므로 머리도 아님.
    """
    if not command:
        return None
    first = next(iter(_judged(command, mask_literals(command))), None)
    return first.call if first else None


# 다음 토큰을 인자로 소비하는 플래그. 건너뛰지 않으면 `-m "msg"` 의 메시지가
# 소스 브랜치 자리로 샘.
# `-S`/`--gpg-sign` 은 의도적으로 **없음**: git 은 keyid 를 붙여서 받으므로
# (`-Skeyid`, `--gpg-sign=keyid`) 별도 토큰이 아니고, 여기 넣으면
# `git merge -S feature/x` 의 소스 브랜치를 삼켜 서명 머지에서 검사가 조용히 꺼짐.
_MERGE_FLAGS_WITH_ARG = frozenset(
    {
        "-m",
        "--message",
        "-F",
        "--file",
        "-s",
        "--strategy",
        "-X",
        "--strategy-option",
        # 안 건너뛰면 그 이름이 소스 자리를 먹어 규칙이 매칭되지 않음 —
        # `git merge --into-name dev feature/x` 가 dev 를 소스로 읽힘(실측: 러너 exit 0,
        # 실제 git 은 머지함).
        "--into-name",
        "--cleanup",
    }
)
# 다음 낱말을 값으로 받는 긴 옵션 — git 은 이것도 축약을 받으므로(`--strategy-o theirs`)
# 정확한 철자만 건너뛰면 값이 소스 자리를 먹음.
_LONG_WITH_ARG = (
    "--message",
    "--file",
    "--strategy",
    "--strategy-option",
    "--into-name",
    "--cleanup",
)
# 규칙이 이름 대는 옵션 중 서로를 덮어쓰는 묶음 — git 은 묶음마다 **나중에 선** 것을 택함.
_SQUASH_FLAGS = ("--squash", "--no-squash")
_FF_FLAGS = ("--ff", "--no-ff", "--ff-only")
_PAIRED = _SQUASH_FLAGS + _FF_FLAGS
# `git merge` 의 짧은 옵션 중 값을 받는 글자. 묶음(`-qm msg`)에서 이 글자가 끝에 서면 다음
# 낱말이 그 값임 — 안 건너뛰면 값이 소스 자리를 먹어 규칙이 매칭되지 않음(실측:
# `git merge -qm msg --no-ff fix/x` 러너 exit 0, 실제 git 은 머지 커밋). `-S` 는 키를 붙여서만
# 받으므로 나머지를 가짐.
_MERGE_SHORT_WITH_ARG = "msXF"

# 머지 경로가 읽는 서브커맨드 넷 — 그룹 2 가 어느 것인지 알려 줌. 하나씩 걸면 낱말 단위
# 읽기(`_spelled_with_quotes`)가 명령마다 세 번 돎. 브랜치를 대는 `git pull` 은 fetch 뒤 그
# 브랜치를 머지하므로 `git merge` 와 같은 판정을 받음.
# merge 앞에 오는 `git switch` / `git checkout` **호출**(같은 명령 안)이 그 머지의 target.
# merge-strategy 의 "Merging feature/* → integration" 은 3단계 블록
# (`git switch <integration>` → `git pull --ff-only` → `git merge --squash feature/<name>`)이고
# Claude Code 는 이를 한 번의 Bash 호출로 보냄. 그래서 훅 시점 HEAD 는 아직 **소스** 브랜치라
# 어떤 규칙도 매칭되지 않음 — 정책이 문서화한 바로 그 관용구가 게이트를 우회함.
# 피연산자는 의도적으로 이 패턴에 넣지 않음: 피연산자를 읽을 수 없어도 호출 자체는 *보여야*
# 함(읽을 수 없는 호출 하나가 체인 전체를 무효화 — _target_from_command 참조).
# `git\s+` 가 전역 옵션 영역을 앵커하므로 명령 다른 곳의 `checkout` 유사 단어로는 매칭이
# 시작되지 않음.
# 호출 문법은 commit·merge 와 **하나를 공유함**. 자기 철자를 따로 쓰면 두 벌이 서로 다르게
# 틀림 — 상류에서는 그 철자가 경로 붙은 `git` 을 안 받아, `/usr/bin/git switch dev &&
# git merge X` 가 target 을 잃고 훅 시점 HEAD 로 심사됐음.
_MERGE_PATH_RE = git_subcommand_re("(merge|pull|switch|checkout)")


def _merge_dash_c(
    command: str, merge: _MergeCall | None = None, masked: str | None = None
) -> str | None:
    """**이 머지**가 든 `-C <dir>`. 디렉터리를 안 지목하면 None. 기본은 판정 대상 머지.

    `-C` 가 디렉터리인 것은 그 merge 호출 자신의 전역 옵션일 때뿐: 체인 앞쪽의 무관한
    `-C`(`grep -C 3`, `gcc -C`, …)나 주석·메시지에 적힌 `-C` 를 채택하면 merge 게이트가
    엉뚱한 트리로 판정돼 통째로 꺼짐. 같은 이유로 **다른 머지**의 `-C` 도 이 머지 것이
    아님 — 그래서 호출측이 머지를 지목함.
    """
    if masked is None:
        masked = mask_literals(command)
    if merge is None:
        merge = _merge_match(command)
    if not merge:
        return None
    return dash_c_value(command, masked, merge.opts[0], merge.opts[1])


# merge 앞의 `cd <dir>` — _vway_paths._CD_PREFIX_RE 의 merge 경로 전용 변종. 구분자 집합은
# 이제 같지만(양쪽 다 `&&`·`;`·개행) **앵커가 다름**: 커밋 쪽은 명령 선두에 고정하고,
# 이쪽은 merge 앞 어디에 선 `cd` 든 잡음. 위험 극성이 반대라 그럼 — 커밋 쪽 매치는 ROOT 를
# 재지정하므로 넓히면 새로 차단하지만, 이쪽 매치는 fail-open 으로만 감.
# `cd <wt>` 뒤에 **개행**이 오면(다중 줄 Bash 호출의 실제 모양) cd 가 아예
# 없는 것으로 읽혀, merge 가 이쪽 root 기준으로 판정되고 일어나지도 않는 flow 를 지목하는
# false block 이 남. 선두 `(?:^|[;&|\n\r])` 경계로 앵커해 명령 선두가 아닌 `cd`
# (`git fetch && cd <wt> && …`)도 잡되(merge 앞 영역에서만 찾고),
# 경로 중간의 `abcd` 같은 우연 매칭은 배제.
# 공용 정규식을 넓혀서 고치지 **않는** 것은 의도적 — 두 경로는 위험 방향이 반대. 여기서
# 매칭은 언제나 FAIL-OPEN 으로만 이어지지만(Invariant #1 — _points_elsewhere → exit 0),
# 저쪽에서 같은 매칭은 status/diff/tier마커/모듈lint 를 위해 ROOT 를 다른 worktree 로 옮김.
# worktree 재지정 불변식은 그 경로가 보수적이기를(불확실하면 main, 새로 차단하지 않기)
# 요구함. 하나의 문법이 두 방향을 다 감당할 수 없으므로 merge 경로가 자기 구분자를 따로 둠.
_MERGE_CD_PREFIX_RE = re.compile(rf"(?:^|(?<=[;&|\n\r]))\s*cd\s+(?:{_PATH_TOKEN})\s*(?:&&|[;\n\r])")


def _merge_cd_prefix(command: str, masked: str, end: int) -> str | None:
    """`command[:end]` 안 선행 `cd <dir> &&` 들이 옮겨 간 디렉터리. 없으면 None.

    자리는 **마스크**에서 찾고 경로는 그 span 의 **원본**에서 읽음 — 주석·메시지·heredoc
    본문에 적힌 `cd` 를 채택하면 일어나지도 않는 이동을 근거로 merge 게이트가 FAIL-OPEN
    함. 경로 토큰과 뒤 구분자는 한 정규식이 함께 봐야 함: 따로 보면 `cd <경로>;` 에서
    토큰이 `;` 를 삼킨 뒤 되감지 못해 감지가 통째로 사라짐(실측).
    `cd` 는 **전부** 이어 읽음: `cd sub && cd deeper && git -C ../.. merge X` 는 root 에서
    돎. 앞 경계를 lookbehind 로 두는 것은 앞 `cd` 의 `&&` 가 뒤 `cd` 의 경계이기 때문.
    """
    ends, paths = _cd_chain(command, masked)
    i = bisect.bisect_right(ends, end)
    return paths[i - 1] if i else None


# 이어 붙인 `cd` 경로의 깊이 상한. 넘으면 이름을 댈 수 없는 디렉터리로 봄 — `cd sub/d` 를
# 반복하면 경로가 머지마다 깊어지고, 판정이 머지마다 그 경로를 파일시스템에 물으면
# `머지 × 깊이` 라 2차임(실측: 16KB 21초, 배가마다 약 4배).
_CD_DEPTH_CAP = 32
# 이름을 댈 수 없는 `cd` 결과(`cd -` 의 첫 이전 자리, 깊이 상한 초과) — 저쪽으로 판정.
_UNKNOWN_CD = "\0"


def _host_path(path: str) -> str:
    """Git Bash 의 드라이브 철자(`/c/Work`)를 Windows 경로(`c:/Work`)로. Windows 의 Claude
    Code Bash 는 이 철자를 흔히 쓰는데, 그대로 이으면 `C:\\c\\Work` 가 되어 같은 저장소를
    다른 디렉터리로 읽음(실측: `cd /c/<repo> && git merge dev` 가 판정을 비켜 감)."""
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(?=/|$)", path)
        if m:
            return f"{m.group(1)}:/{path[2:].lstrip('/')}"
    return path


@functools.lru_cache(maxsize=4)
def _cd_chain(command: str, masked: str) -> tuple[list[int], list[str]]:
    """명령의 `cd` 들이 끝나는 자리와 그때까지 이어 붙인 경로 — 명령마다 한 번만 훑음.
    머지마다 처음부터 다시 훑으면 `머지 × 길이` 라 2차임(실측: `git merge --squash f/x` 를
    `&&` 로 이은 100KB 에서 3초, 200KB 11초). 경로는 셸의 논리적 `cd` 처럼 글자로만 접고
    (`normpath`), `cd -` 는 바로 앞 자리로 돌아감."""
    ends: list[int] = []
    paths: list[str] = []
    cur = "."  # root
    prev: str | None = None  # 첫 `cd -` 의 이전 자리는 훅 밖의 OLDPWD — 이름 못 댐
    for m in _MERGE_CD_PREFIX_RE.finditer(masked):
        part = unquote_path(command[m.start(1) : m.end(1)])
        if part == "-":
            cur, prev = (prev if prev is not None else _UNKNOWN_CD), cur
        elif cur == _UNKNOWN_CD and not os.path.isabs(_host_path(part)):
            prev = cur
        else:
            prev, cur = cur, os.path.normpath(os.path.join(cur, _host_path(part)))
            if len(Path(cur).parts) > _CD_DEPTH_CAP:
                cur = _UNKNOWN_CD
        paths.append(cur)
        ends.append(m.end())
    return ends, paths


def parse_merge_command(command: str) -> tuple[set[str], str | None]:
    """소스를 지목하는 **첫** `git merge` 에서 (플래그, 소스 브랜치)를 뽑음.

    판정 경로는 `_judged` 로 전부를 봄 — 이쪽은 "이 명령에 머지가 있는가" 한 가지만 묻는
    호출측을 위한 단수 API.

    `merge` 서브커맨드 **뒤쪽만** 파싱하므로 `git -C <dir> merge X` 가 -C 인자를 소스로
    오인하지 않음(Windows 백슬래시 경로도 shlex 에 도달하지 않음).
    merge 가 아니거나 소스 피연산자가 없거나 파싱 실패면 (set(), None) —
    FAIL-OPEN(Invariant #1).
    """
    if not command:
        return set(), None
    merges = parse_merge_commands(command)
    return merges[0] if merges else (set(), None)


def parse_merge_commands(command: str) -> list[tuple[set[str], str]]:
    """소스를 지목하는 `git merge` **전부**를, 나타난 순서대로.

    전부인 이유: 소스를 지목하지 않는 머지(`--abort`·`--continue`)나 정책이 허용하는 머지
    하나가 앞에 서면 그 뒤가 통째로 미판정으로 남음(실측) — 그리고 전략 판정은 이 게이트가
    fail-open 하면 안 되는 셋 중 하나.
    """
    if not command:
        return []
    return [(j.flags, j.source) for j in _merges_with_a_source(command, mask_literals(command))]


def parse_pull_commands(command: str) -> list[tuple[set[str], str]]:
    """브랜치를 대는 `git pull` 이 target 에 들이는 브랜치 **전부** — (플래그, 소스).

    그런 pull 은 fetch 뒤 그 브랜치를 `git merge` 와 같은 플래그로 머지함: `git pull origin
    feature/x` 는 `--squash` 를 요구하는 행을 그대로 비켜 갔음(실측: 러너 exit 0). rebase 하는
    pull 도 그 브랜치를 들임 — target 이 소스 위로 올라가거나 fast-forward 됨(실측) — 그래서
    빼지 않고, 머지 커밋이 없으므로 머지 플래그 없음으로 읽음(`_pull_flags`).
    """
    if not command:
        return []
    return [(j.flags, j.source) for j in _pulls_with_a_source(command, mask_literals(command))]


def _carries(flags: set[str], flag: str) -> bool:
    """이 머지가 `flag` 를 든 것으로 읽히는가.

    `_PAIRED` 의 옵션은 `_merge_operands` 가 이미 git 처럼 풀어 둔 이름이라 정확히 비교함 —
    접두로 세면 `--ff` 가 `--ff-only` 로 읽힘. 그 밖의 낱말은 git 이 받는 **축약**까지 셈:
    git 의 모호성 표를 여기서 다시 만들 수는 없으므로 접두면 그 플래그로 봄. 모호해서
    git 이 거절할 철자(`--no`)까지 세지만, 그쪽은 머지가 아예 안 일어나므로 비용이 없음.
    """
    return any(f == flag or (f not in _PAIRED and len(f) > 2 and flag.startswith(f)) for f in flags)


def _resolve(name: str, choices: tuple[str, ...]) -> str | None:
    """긴 옵션 `name` 이 `choices` 중 무엇을 철자하는가 — 그대로이거나 축약. 아니면 None.

    git 은 긴 옵션의 모호하지 않은 접두를 받음: `git merge --no-f fix/x` 는 실제 git 에서
    `--no-ff` 로 해석돼 머지 커밋을 만듦(실측). 정확한 문자열만 보면 그 한 글자로 forbid
    규칙이 통째로 비켜 감 — 전략 판정은 fail-open 하면 안 되는 셋 중 하나. git 이 받는
    접두는 이 중 하나만 뜻할 수 있음(같은 접두를 가진 옵션이 둘이면 git 이 거절함). 거절되는
    접두는 머지를 안 돌리므로 어느 쪽으로 읽어도 막을 머지가 없음.
    """
    if name in choices:
        return name
    if len(name) <= 2 or not name.startswith("--"):
        return None
    hits = [c for c in choices if c.startswith(name)]
    return hits[0] if len(hits) == 1 else None


def _config_bool(val: str) -> bool | None:
    """설정값을 git 이 불리언으로 읽듯 — 공백을 안 다듬고, 대소문자는 접고, 정수는 값으로.
    git 이 불리언으로 안 받을 값은 None.

    빈 값은 **false**: `git -c merge.ff= merge fix/x` 는 실제 git 에서 머지 커밋을 만듦(실측).
    true 인 것은 `=` 가 아예 없는 `-c <key>` 뿐이고, 그건 `_config_values` 가 `true` 로 넘김.
    """
    if val in ("false", "no", "off", ""):
        return False
    if val in ("true", "yes", "on"):
        return True
    if re.fullmatch(r"[+-]?\d+", val):
        return int(val) != 0
    return None


def _config_values(global_opts: list[str], key: str) -> list[str]:
    """git 전역 옵션의 `-c <key>=<값>` 이 세우는 값들, 나타난 순서대로. 키는 대소문자를
    가리지 않고 값은 git 처럼 다듬지 않음. 맨 `-c <key>` 는 true."""
    values = []
    for flag, value in zip(global_opts, global_opts[1:]):
        if flag != "-c":
            continue
        name, eq, val = value.partition("=")
        if name.lower() == key:
            values.append(val.lower() if eq else "true")
    return values


def _config_ff(global_opts: list[str], keys: tuple[str, ...]) -> str | None:
    """`-c <key>=…` 가 세우는 fast-forward 모드를 그것이 대신하는 플래그로. `keys` 의 뒤
    키가 앞 키를 이김 — pull 에서 `pull.ff` 가 `merge.ff` 를 이기듯.

    명령줄의 config 는 명령 문자열에 있으므로 Exception 3 이 읽을 수 있음:
    `git -c merge.ff=false merge fix/x` 는 실제 git 에서 머지 커밋을 만듦(실측) —
    안 읽으면 `--no-ff` 를 금하는 행이 조용히 비켜 감. 저장소 config 는 읽지 않음.
    """
    mode = None
    for key in keys:
        for val in _config_values(global_opts, key):
            setting = _config_bool(val)
            if val == "only":
                mode = "--ff-only"
            elif setting is not None:
                mode = "--ff" if setting else "--no-ff"
    return mode


def _merge_operands(
    tokens: list[str],
    global_opts: list[str] | None = None,
    ff_keys: tuple[str, ...] = ("merge.ff",),
    takes_values: bool = True,
    prefix: list[str] | tuple[str, ...] = (),
    late_ff_keys: tuple[str, ...] = (),
) -> tuple[set[str], str | None]:
    """머지 하나의 뒤에 선 낱말들에서 (플래그, 소스) — 플래그는 git 이 읽듯 읽음.

    축약은 그것이 철자하는 옵션이고, `_SQUASH_FLAGS`·`_FF_FLAGS` 는 묶음마다 **나중에 선**
    것이 이김: `git merge --squash --no-squash feature/x` 는 실제 git 에서 평범한 머지를
    만듦(실측: 부모 1개). 명령줄 `-c merge.ff` 는 어떤 플래그도 정하지 않은 모드를 대신함.
    `takes_values=False` 는 값을 호출측이 이미 걷어 낸 플래그 낱말을 읽음.
    `prefix` 는 `branch.<target>.mergeoptions` 의 낱말 — git 은 그것을 config 다음, 명령줄
    앞에 따로 파싱하므로 같은 자리에서 읽고, 그 안의 `--` 에서 멈춤(실측: `-- --no-ff` 는
    fast-forward). 그 안의 맨 낱말은 소스가 아님. `late_ff_keys` 는 prefix 뒤·명령줄 앞에
    서는 config — pull 의 `pull.ff` 는 pull 이 자식 머지에 넘기는 **플래그**라
    mergeoptions 를 이김(실측: `-c pull.ff=false -c branch.dev.mergeoptions=--ff` 는 머지
    커밋).
    """
    flags: set[str] = set()
    source: str | None = None
    squash: str | None = None
    ff = _config_ff(global_opts or [], ff_keys)
    if "--" in prefix:
        prefix = prefix[: list(prefix).index("--")]
    late_ff = _config_ff(global_opts or [], late_ff_keys) if late_ff_keys else None
    skip_next = False
    for n, tok in enumerate([*prefix, *tokens]):
        if n == len(prefix) and late_ff:
            ff = late_ff
        if skip_next:
            skip_next = False
            continue
        if n < len(prefix) and not tok.startswith("-"):
            continue
        if tok.startswith("-"):
            name = tok.split("=", 1)[0]
            if takes_values and (
                tok in _MERGE_FLAGS_WITH_ARG
                or ("=" not in tok and _resolve(name, _LONG_WITH_ARG))
                or (
                    not tok.startswith("--")
                    and _short_bundle_takes_next(tok, _MERGE_SHORT_WITH_ARG, "S")
                )
            ):
                skip_next = True
                continue
            # 두 묶음을 **합친** 표로 풂 — `--no` 는 `--no-squash`·`--no-ff` 둘 다의 접두라
            # git 이 거절하고, 여기서도 풀리지 않은 낱말로 남아 `_carries` 가 축약으로 셈.
            resolved = _resolve(name, _PAIRED)
            if resolved in _SQUASH_FLAGS:
                squash = resolved
            elif resolved in _FF_FLAGS:
                ff = resolved
            else:
                flags.add(name)
            continue
        if source is None:
            source = tok
    if late_ff and not tokens:
        ff = late_ff
    flags.update(f for f in (squash, ff) if f)
    return flags, source


# `git pull` 에서 다음 낱말을 값으로 받는 옵션(fetch 쪽 포함). `-j`/`--jobs` 는 붙여서만
# 받음. 짧은 것은 묶음을 열면 그 나머지가 값임.
_PULL_SHORT_WITH_ARG = "sXo"
_PULL_LONG_WITH_ARG = (
    "--strategy",
    "--strategy-option",
    "--server-option",
    "--depth",
    "--deepen",
    "--shallow-since",
    "--shallow-exclude",
    "--upload-pack",
    "--negotiation-tip",
    "--refmap",
    "--cleanup",
)


def _rebase_setting(tok: str) -> bool | None:
    """`git pull` 옵션 하나가 rebase 를 켜는가(True)·끄는가(False). 그 밖의 옵션은 None.

    짧은 묶음은 글자마다 읽음: 묶음 어디든 `-r` 이 있으면 rebase 이고 그 뒤 나머지가 모드임
    — 단 값을 받는 옵션이 먼저 서면 나머지는 그 값임(`-Sr` 의 r 은 서명 키). 붙은 값은
    `_config_bool` 이 읽으므로 `--rebase=` 처럼 빈 값은 rebase 를 끔(실측: 실제 git 이 머지함).
    """
    if not tok.startswith("--"):
        for i, letter in enumerate(tok[1:], 1):
            # `-S`·`-j` 는 값을 붙여서 받으므로 나머지를 가짐
            if letter in _PULL_SHORT_WITH_ARG or letter in "Sj":
                return None
            if letter == "r":
                rest = tok[i + 1 :].lower()
                return not rest or _config_bool(rest) is not False
        return None
    name, eq, val = tok.partition("=")
    resolved = _resolve(name, ("--rebase", "--no-rebase"))
    if resolved == "--rebase":
        return not eq or _config_bool(val.lower()) is not False
    if resolved == "--no-rebase":
        return False
    return None


def _takes_pull_value(tok: str) -> bool:
    """이 `git pull` 옵션 낱말이 다음 낱말을 값으로 받는가."""
    if tok.startswith("--"):
        return "=" not in tok and _resolve(tok, _PULL_LONG_WITH_ARG) is not None
    return _short_bundle_takes_next(tok, _PULL_SHORT_WITH_ARG, "Sjr")


class _PullWords(NamedTuple):
    """`git pull` 하나를 읽은 것. rebase 여부는 둘로 나눠 둠 — 명령줄 플래그가 정했으면
    `flag_rebase`, 명령줄 `-c pull.rebase` 가 정했으면 `cmd_rebase`. 저장소 config 는 읽지
    않음(Exception 3 은 명령만으로 정함)."""

    flags: set[str]
    sources: list[str]
    flag_rebase: bool | None
    cmd_rebase: bool | None


def _pull_operands(
    tokens: list[str], global_opts: list[str], prefix: list[str] | tuple[str, ...] = ()
) -> _PullWords:
    """`git pull` 하나의 낱말들에서 머지 플래그·이름으로 머지하는 브랜치들·rebase 여부.

    브랜치를 안 댄 pull 은 명령이 철자하지 않는 upstream 을 머지하므로 브랜치가 없음.
    rebase 는 git 의 순서대로 정해짐: 명령줄 플래그 > `branch.<target>.rebase` >
    `pull.rebase`. 가운데 것은 target 을 알아야 하므로 `_pull_flags` 가 마저 정함.
    `prefix` 는 `_merge_operands` 와 같음.
    """
    cmd_rebase: bool | None = None
    for val in _config_values(global_opts, "pull.rebase"):
        cmd_rebase = _config_bool(val) is not False
    flag_rebase: bool | None = None
    flag_words: list[str] = []
    positional: list[str] = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            if _takes_pull_value(tok):
                skip_next = True
            elif (setting := _rebase_setting(tok)) is not None:
                flag_rebase = setting
            else:
                flag_words.append(tok)
            continue
        positional.append(tok)
    flags, _ = _merge_operands(
        flag_words,
        global_opts,
        takes_values=False,
        prefix=prefix,
        late_ff_keys=("pull.ff",),
    )
    # 첫 위치 인자는 원격, 나머지는 refspec — 머지하는 것은 `:` 앞의 원천.
    sources = [spec.lstrip("+").split(":", 1)[0] for spec in positional[1:]]
    return _PullWords(flags, [s for s in sources if s], flag_rebase, cmd_rebase)


# `_switch_targets` 가 "앞에 읽을 수 없는 switch 가 있음"을 None(switch 없음)과 가르는 표지.
_UNREADABLE = object()


def _switch_targets(command: str, masked: str, merges: list[_MergeCall]) -> list[object]:
    """머지마다 그 머지 **앞**의 `git switch`/`git checkout` 들이 정하는 target — 나타난
    순서대로 한 번 훑음.

    범위를 각 머지 머리까지로 묶는 것이 계약의 일부. 뒤에 붙은 switch 는 그 머지의 target 이
    아닌데, 그걸 '불명확한 switch 가 있다'로 세면 그 머지가 판정에서 빠짐 —
    `git merge X && git switch dev` 한 줄로 merge 전략 게이트가 꺼짐(Invariant #1 예외 3).
    마스크 위에서 찾는 것도 같은 이유: 주석에 적힌·메시지에 인용된·heredoc 본문에 든
    `git switch` 는 텍스트임. 인용이 쪼갠 철자(`git sw''itch main`)는 머지와 같은 읽기
    (`_merge_calls`)로 셈 — 빼면 target 을 낡은 HEAD 로 읽어 main 으로의 머지가 판정을
    비켜 감(실측: 러너 exit 0).

    값은 브랜치 이름, switch 가 없으면 None, 앞에 읽을 수 없는 switch 가 하나라도 있으면
    `_UNREADABLE`. 머지마다 앞 switch 전부를 다시 읽으면 `머지 × switch` 라 2차임(실측:
    switch+merge 를 `&&` 로 이은 50KB 5.2초, 100KB 22초).

    switch 가 머지에 듦은 그 **피연산자가 머지 앞에서 끝날 때** — 시작이 아님. 피연산자가
    머지를 품은 switch(`git switch -c $(git merge x)`)는 그 머지 **뒤**에 돎: 셸은 인자를
    확장한 뒤에야 그것을 받는 명령을 돌림. 그런 switch 의 피연산자는 치환 한 덩어리를 담아
    이름을 못 댐. 그래서 switch 를 피연산자 끝 순으로 한 번 훑음.
    """
    moves = []
    for sw in _live_calls(command, masked)["switch"]:
        words, end = _call_operands(command, masked, sw, limit=2)
        moves.append((end, sw.head, _switch_operand(words)))
    moves.sort()
    out: list[object] = [None] * len(merges)
    void, latest = False, None
    i = 0
    for n in sorted(range(len(merges)), key=lambda n: merges[n].head):
        while i < len(moves) and moves[i][0] <= merges[n].head:
            _end, start, branch = moves[i]
            void = void or branch is None  # 불명확한 switch 하나가 체인 전체를 무효화
            if latest is None or start > latest[0]:
                latest = (start, branch)
            i += 1
        out[n] = _UNREADABLE if void else (latest[1] if latest else None)
    return out


class _MergeCall(NamedTuple):
    """머지 호출 하나의 자리 — 정규식 매치와 인용된 철자를 한 모양으로 읽음."""

    head: int  # `git` 낱말이 시작하는 자리
    opts: tuple[int, int]  # 전역 옵션 영역(`-C <dir>` 이 사는 곳)
    operands: int  # 피연산자가 시작하는 자리
    word: str = ""  # 서브커맨드를 그룹으로 고르는 문법이면 그 서브커맨드


def _merge_calls(masked: str, command: str, pattern: GitSubcommand = _MERGE_RE):
    """이 명령의 `git … merge`(`pattern` 이 다른 서브커맨드면 그것) 호출들, 나타난 순서대로.

    두 갈래를 합침: 마스크 위의 정규식 매치와, **인용 제거 뒤에야** merge 가 되는 철자
    (`git 'merge' --no-ff fix/x`·`git \\merge …`·`git merge"" …`). 후자를 빼 두면
    `--classify` 는 `merge=1` 이라 답하는데 전략 판정만 조용히 비어, fail-CLOSED 예외가
    열린 채로 남음(실측: 러너 exit 0, 실제 bash 는 머지함).
    """
    # 낱말 단위 읽기가 **먼저**. 정규식은 서브커맨드 낱말 안에서 끝날 수 있어
    # (`git merge"" --no-ff fix/x` 는 `merge` 뒤 `""` 가 남음) 피연산자가 낱말 한가운데서
    # 시작하고, shlex 가 빈 토큰을 내 소스가 없는 것으로 읽힘(실측: 러너 exit 0).
    calls = {
        head: _MergeCall(head, (opts_a, opts_b), operands, _chosen(m))
        for head, opts_a, opts_b, operands, m in _spelled_with_quotes(command, masked, pattern)
    }
    for m in git_invocations(masked, pattern):
        call = _MergeCall(m.start(), (m.start(1), m.end(1)), m.end(), _chosen(m))
        calls.setdefault(m.start(), call)
    buried = [
        _MergeCall(m.start(), (m.start(1), m.end(1)), m.end(), _chosen(m))
        for m in pattern.finditer(masked)
    ]
    buried += [
        _MergeCall(head, (opts_a, opts_b), operands, _chosen(m))
        for head, opts_a, opts_b, operands, m in _spelled_with_quotes(
            command, masked, pattern, anywhere=True
        )
    ]
    runs = _BuriedRuns(command, masked)
    for call in buried:
        if call.head not in calls and runs(call):
            calls[call.head] = call
    return sorted(calls.values())


class _BuriedRuns:
    """명령 자리 밖에 선 `git …` 호출이 실제로 도는가 — 둘 중 하나면 돎.

    - 그 인자가 다시 파싱됨(`eval`·`watch`·`ssh` 뒤, `reparse_depth`) — switch 도 이 경우만.
      돌지 않는 switch 를 읽으면 target 이 규칙 밖으로 옮겨 머지가 조용히 통과할 수 있음
      (`npm run git switch x`). 머지를 더 읽는 쪽은 더 막을 뿐임.
    - merge·pull 이고, 그 호출이 선 파이프라인 단계가 면제를 못 받음(`is_invocation`) —
      `find . -exec git merge …`·`sudo -u x git merge …` 처럼 인자로 받은 명령을 돌리는
      프로그램 뒤. `echo git merge …` 의 낱말은 면제가 버림.

    둘 다 아니면 낱말일 뿐 — 호출로 세면 첫 매치가 엉뚱한 소스·target 으로 심사됨.
    면제 판정은 단계마다 한 번만 함: 호출마다 단계 전체를 다시 읽으면 길이의 제곱.
    """

    def __init__(self, command: str, masked: str) -> None:
        self.command, self.masked = command, masked
        self._stages: list[tuple[int, int]] | None = None
        self._verdicts: dict[tuple[int, int, str], bool] = {}

    def __call__(self, call: _MergeCall) -> bool:
        if reparse_depth(self.command, self.masked, call.head, call.operands):
            return True
        if call.word not in ("merge", "pull"):
            return False
        stage = self._stage_of(call.head)
        if stage is None:
            return False
        key = (*stage, call.word)
        if key not in self._verdicts:
            a, b = stage
            self._verdicts[key] = is_invocation(self.command[a:b], call.word)
        return self._verdicts[key]

    def _stage_of(self, head: int) -> tuple[int, int] | None:
        if self._stages is None:
            # `>|`·`|&` 의 `|` 는 단계를 가르지 않음 — 리다이렉션을 지운 마스크에서 셈
            _text, plain = _blank_redirections(self.command, self.masked)
            self._stages = []
            for a, b in _list_elements(self.command, self.masked):
                cuts = [a + m.start() for m in _PIPE_RE.finditer(plain[a:b])]
                bounds = [a, *cuts, b]
                self._stages += [
                    (s + (1 if n else 0), e) for n, (s, e) in enumerate(zip(bounds, bounds[1:]))
                ]
        i = bisect.bisect_right(self._stages, (head, len(self.command) + 1)) - 1
        if i >= 0 and self._stages[i][0] <= head < self._stages[i][1]:
            return self._stages[i]
        return None


# 파이프라인 단계를 가르는 `|` — `||` 는 목록 구분자라 `_list_elements` 가 이미 가름.
_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")


def _chosen(m: re.Match) -> str:
    """서브커맨드를 그룹 2 로 고르는 문법의 매치에서 그 서브커맨드. 없으면 빈 문자열."""
    return m.group(2) if m.re.groups >= 2 else ""


@functools.lru_cache(maxsize=4)
def _live_calls(command: str, masked: str) -> dict[str, tuple[_MergeCall, ...]]:
    """돌아가는 merge·pull·switch(checkout 포함) 호출들 — 서브커맨드별로, 나타난 순서대로.

    넷을 한 번에 모아 다른 머지 경로 명령의 피연산자 사이에 **인자로 적힌** 것을
    버림(`runs_among_operands`): `git switch dev git merge feature/x` 의 머지는 돌지 않고,
    남겨 두면 저마다 명령 끝까지 피연산자를 읽어 호출이 늘어선 명령에서 길이의 제곱이 됨.
    """
    found = _merge_calls(masked, command, _MERGE_PATH_RE)
    among = runs_among_operands(command, masked, [(c.head, c.operands) for c in found])
    live: dict[str, list[_MergeCall]] = {"merge": [], "pull": [], "switch": []}
    for call, dropped in zip(found, among):
        if not dropped:
            word = "switch" if call.word == "checkout" else call.word
            live[word].append(call)
    return {word: tuple(calls) for word, calls in live.items()}


def _call_operands(
    command: str, masked: str, call: _MergeCall, limit: int | None = None
) -> tuple[list[str], int]:
    """호출 하나의 피연산자 낱말과 그 영역이 끝나는 자리. 끝은 `operand_end` 가 **마스크
    위에서** 정함 — 뒤 명령의 단어도, 주석에 적힌 플래그도 이 호출 것이 아님. `eval`·`watch`·
    `ssh` 뒤면 한 번 더 파싱한 대로 읽고, 그 파싱이 세운 구분자에서 끝남(`call_operands`)."""
    end = operand_end(command, masked, call.operands)
    return call_operands(command, masked, call.head, call.operands, end, limit)


def _call_words(command: str, masked: str, call: _MergeCall) -> tuple[list[str], list[str]]:
    """호출 하나의 (전역 옵션 낱말, 피연산자 낱말)."""
    return (
        operand_words(command, masked, call.opts[0], call.opts[1]),
        _call_operands(command, masked, call)[0],
    )


class _Judged(NamedTuple):
    """이름으로 하는 머지 하나 — 판정이 target 을 안 뒤 다시 읽을 낱말까지 함께 듦."""

    call: _MergeCall
    flags: set[str]
    source: str
    global_opts: list[str]
    operands: list[str]
    pull: bool
    # pull 만: 명령줄이 정한 rebase — 플래그(`flag_rebase`)와 `-c pull.rebase`(`cmd_rebase`).
    flag_rebase: bool | None = None
    cmd_rebase: bool | None = None


def _merges_with_a_source(command: str, masked: str):
    """소스 피연산자를 지목하는 `git … merge` 호출들."""
    for call in _live_calls(command, masked)["merge"]:
        global_opts, operands = _call_words(command, masked, call)
        flags, source = _merge_operands(operands, global_opts)
        if source:
            yield _Judged(call, flags, source, global_opts, operands, False)


def _pulls_with_a_source(command: str, masked: str):
    """브랜치를 대는 `git … pull` 호출들 — 들이는 브랜치마다 하나. rebase 하는 pull 도
    포함하고, 그 플래그는 `_pull_flags` 가 target 없이 정할 수 있는 만큼 정함."""
    for call in _live_calls(command, masked)["pull"]:
        global_opts, operands = _call_words(command, masked, call)
        words = _pull_operands(operands, global_opts)
        flags = _pull_flags(words, None, global_opts)
        for source in words.sources:
            yield _Judged(
                call,
                flags,
                source,
                global_opts,
                operands,
                True,
                words.flag_rebase,
                words.cmd_rebase,
            )


def _pull_rebase(words: _PullWords, target: str | None, global_opts: list[str]) -> bool | None:
    """명령줄이 정한 pull 의 rebase 여부 — git 순서대로 플래그 > `-c branch.<target>.rebase` >
    `-c pull.rebase`. 명령줄이 정하지 않으면 None(저장소 config 가 정함)."""
    rebase = words.flag_rebase
    if rebase is None and target is not None:
        branch = _branch_config(global_opts, target, "rebase")
        if branch is not None:
            rebase = _config_bool(branch.lower()) is not False
    return words.cmd_rebase if rebase is None else rebase


def _pull_flags(words: _PullWords, target: str | None, global_opts: list[str]) -> set[str]:
    """pull 이 target 에 남기는 머지 플래그. rebase 하면 빈 집합 — 머지 커밋도 squash 도 없이
    소스 이력이 그대로 들어오므로, `--squash`·`--no-ff` 를 요구하는 행은 막고 `--no-ff` 를
    금하는 행은 통과함. 명령줄이 rebase 를 정하지 않으면 철자한 머지로 읽음 — 저장소
    config 의 몫은 `merge_check_output` 이 **더하는** 읽기로만 씀(`_config_rebases`)."""
    return set() if _pull_rebase(words, target, global_opts) else words.flags


def _judged(command: str, masked: str) -> list[_Judged]:
    """이 명령이 이름으로 하는 머지 **전부** — 판정과 앵커가 공유하는 유일한 기준.
    `git merge` 와 `git pull` 을 나타난 순서대로 섞음: target 은 각 머지 앞의 switch 가 정함."""
    found = [*_merges_with_a_source(command, masked), *_pulls_with_a_source(command, masked)]
    return sorted(found, key=lambda judged: judged.call.head)


def _switch_operand(words: list[str]) -> str | None:
    """피연산자 낱말이 `words` 인 `git switch`/`git checkout` 이 HEAD 를 올려놓는 브랜치.
    불명확하면 None.

    명확 = 피연산자 정확히 하나 + 플래그 전무. 그 외의 모든 모양은 이 파서가 이름 붙일 수 없는
    곳으로 HEAD 를 옮기므로 "첫 맨몸 단어"가 아니라 불명확으로 봄:
      - `checkout dev -- a/b.py` 는 dev 에서 **파일**을 복원. HEAD 는 아예 움직이지 않음.
      - `switch -c feature/y` / `checkout -b` 는 **다른** 브랜치를 만들어 거기 올라섬.
      - `checkout origin/dev`·`checkout refs/heads/dev` 는 detached HEAD 로 감 — 그런데
        _branch_matches 가 ref 접두(`_REF_PREFIX_RE`)를 벗기므로, 이를 채택하면 들어간 적
        없는 integration 규칙에 매칭돼 버림.
      - `checkout main~0`·`main^0`·`main@{1}` 도 detached HEAD — 리비전 접미를 벗겨 main 으로
        읽으면 main 에 들지 않는 머지를 main 규칙으로 차단함(`_REVISION_SUFFIX_RE`).
      - `switch -`, `checkout --detach`, 따옴표 불균형(낱말 없음), 치환이 출력하는 브랜치
        (`OPAQUE_CH`): 이름 붙일 수 없음.
    """
    if len(words) != 1:
        return None
    branch = words[0]
    if (
        branch.startswith("-")
        or OPAQUE_CH in branch
        or _REF_PREFIX_RE.match(branch)
        or _REVISION_SUFFIX_RE.search(branch)
    ):
        return None
    return branch


def _target_from_command(command: str, merge: _MergeCall | None = None) -> str | None:
    """**이 머지** 앞의 `git switch`/`git checkout` 이 옮겨 가는 브랜치 — 그 머지의 진짜
    target. 기본은 첫 머지.

    `git switch dev && git merge feature/x` 는 dev 로 머지하는데 훅 시점 HEAD 는 아직
    feature/x. 명령어가 target 을 명시하고 있으므로 훅 시점 브랜치보다 우선함.

    규칙은 **"merge 앞의 모든 switch/checkout 이 명확해야 하고, 그 다음 마지막 것이 이긴다"**
    이지 "마지막으로 파싱되는 것"이 아님. 체인 어디든 불명확한 호출이 하나라도 있으면 None 을
    반환 — 그것이 실제로 HEAD 를 정하는 호출일 수 있기 때문:
    `git switch dev && git switch -c feature/y && git merge feature/x` 에서 HEAD 는 feature/y 로
    끝나고 어떤 규칙도 이를 다루지 않는데, 마지막 *파싱 가능한* switch 를 고르면 낡은 dev 를
    채택해 정책이 관장하지도 않는 머지를 차단. None → 호출측이 훅 시점 브랜치로 폴백
    (FAIL-OPEN, Invariant #1 — 이 방향은 언제나 덜 차단하는 쪽으로만 작용).
    """
    if not command:
        return None
    # 다른 서브커맨드와 같이 마스크 위에서 찾음: 주석에 적힌·메시지에 인용된·heredoc
    # 본문에 든 `git switch` 는 텍스트이고, 그 브랜치를 채택하면 아무도 서지 않은 flow 로
    # merge 를 심사함. 피연산자 낱말은 인용을 살린 판에서 읽어 따옴표 든 브랜치 이름도
    # 셸이 읽는 대로 읽힘.
    masked = mask_literals(command)
    if merge is None:
        merge = _merge_match(command)
    if merge is None:  # 머지가 없으면 명령 끝까지의 switch 를 읽음
        merge = _MergeCall(len(command), (len(command), len(command)), len(command))
    (target,) = _switch_targets(command, masked, [merge])
    # 불명확한 switch 하나가 체인 전체를 무효화함
    return None if target is _UNREADABLE else target  # type: ignore[return-value]


def _points_elsewhere(
    command: str, root: Path, merge: _MergeCall | None = None, masked: str | None = None
) -> bool:
    """**이 머지**가 ``root`` 아닌 디렉터리에서 도는가. `merge` 없으면 판정 대상 머지.

    실행 디렉터리를 지정하는 셸 형태는 둘이고 둘 다 인식해야 함: `git -C <dir> merge X`
    (git 자신의 전역 옵션)와 선행 `cd <dir> && … git merge X`. 어느 쪽이든 소스는 명령어에서
    오는데 target 은 **이쪽** root 에서 읽히므로, 그 불일치가 규칙조차 없는 flow 를 지목하는
    false block 을 내 왔음. merge 경로는 worktree 재지정을 하지 않으므로(Invariant "worktree
    재지정은 커밋 경로 전용") 외부 디렉터리는 그냥 FAIL-OPEN 함(Invariant #1). ``root`` 자신
    으로 해석되는 디렉터리는 외부가 아니며 계속 강제됨. 해석 불가 경로는 외부로 취급.

    **머지마다** 물음. 명령 하나로 답하면 앞에 선 머지 하나가 뒤 전체를 면제함 —
    `git -C ../other merge feature/x && git merge stage` 에서 러너 exit 2 → 0(실측). `-C` 는
    그 호출만의 전역 옵션이고, 선행 `cd` 는 그 뒤 전부에 걸리므로 각 머지 **앞**에서 찾음
    (`cd ../other && git merge X && git merge Y` 는 둘 다 저쪽이라 둘 다 면제됨).

    상대 경로는 프로세스 cwd 가 아니라 ``root`` 기준으로 해석함: merge 검사는
    precommit-runner.sh 의 `cd "$ROOT"` **앞**에서 돌기 때문에, 인터프리터 cwd 는 훅 cwd 이고
    거기서 `git -C .` 을 읽으면 root 자신을 외부로 판정해 게이트를 건너뜀.
    """
    if masked is None:
        masked = mask_literals(command)
    if merge is None:
        merge = _merge_match(command)
    if merge is None:
        return False
    # 둘 다 서면 `-C` 는 `cd` 가 옮긴 곳 기준 — `cd /elsewhere && git -C . merge X` 는
    # 저쪽에서 돎. `-C` 만 보면 root 로 읽어 일어나지 않는 flow 를 차단했음(실측).
    cdir = _merge_dash_c(command, merge, masked)
    cd = _merge_cd_prefix(command, masked, merge.head)
    if not cdir and not cd:
        return False
    if cd == _UNKNOWN_CD:
        return True
    try:
        where = Path(root, cd or "", _host_path(cdir) if cdir else "").resolve()
        base = Path(root).resolve()
        if where == base:
            return False
        where.relative_to(base)
    except ValueError:
        return True  # root 밖
    except Exception:
        return True
    # root 의 하위 디렉터리는 같은 저장소 — 사이에 다른 저장소(.git: 중첩 저장소·worktree)가
    # 없으면. 경로만 비교하면 `cd sub && git merge dev` 가 판정을 비켜 갔음(실측: 실제 git 은
    # 같은 저장소에서 fast-forward). 훅 시점에 없는 디렉터리는 저쪽으로 둠 — 같은 명령이
    # 그것을 만들면(`mkdir d && cd d && git merge …`) 판정에서 빠짐(fail-open, 문서화됨).
    if not where.is_dir():
        return True
    probe = where
    while probe != base:
        if (probe / ".git").exists():
            return True
        probe = probe.parent
    return False


@functools.lru_cache(maxsize=8)
def _rebase_config(root: Path) -> dict[str, str]:
    """git config(저장소·전역·시스템)의 `pull.rebase` 와 모든 `branch.<이름>.rebase` — 훅마다
    git 을 **한 번**만 띄움. 키마다 띄우면 target 이 다른 pull 마다 spawn 이 늘어 판정이
    선형이 아님(실측: target 이 다른 pull 을 이은 100KB 에서 spawn 1924회·309초). 같은 키가
    여럿이면 git 처럼 마지막 값. 못 읽으면 빈 dict."""
    try:
        r = subprocess.run(
            ["git", "config", "--get-regexp", r"^(pull|branch\..*)\.rebase$"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    values: dict[str, str] = {}
    for line in r.stdout.splitlines():
        key, sep, value = line.partition(" ")
        values[key] = value if sep else "true"
    return values


def _config_rebases(root: Path, target: str) -> bool:
    """git config 가 명령줄이 정하지 않은 pull 을 rebase 로 바꾸는가 — `branch.<target>.rebase`
    > `pull.rebase`. 이 답은 판정에 **읽기 하나를 더할 뿐** 철자한 머지 읽기를 빼지 않음:
    rebase 면 `git pull --no-ff origin dev` 가 fast-forward 라 `--no-ff` 행을 어기고(실측),
    명령 안에서 config 를 바꾸면(`git config pull.rebase false && git pull …`) 훅 시점 값이
    낡음 — 두 읽기 중 하나라도 어기면 막으므로 낡은 값도 덜 막지는 않음. 못 읽으면 False."""
    values = _rebase_config(root)
    value = values.get(f"branch.{target}.rebase", values.get("pull.rebase"))
    return value is not None and _config_bool(value.lower()) is not False


def _branch_config(global_opts: list[str], branch: str, key: str) -> str | None:
    """명령줄 `-c branch.<branch>.<key>=…` 의 마지막 값(다듬지 않음). 없으면 None.
    git 처럼 섹션·키는 대소문자를 안 가리고 브랜치 이름은 가림."""
    value = None
    for flag, item in zip(global_opts, global_opts[1:]):
        if flag != "-c":
            continue
        name, eq, val = item.partition("=")
        section, _dot, rest = name.partition(".")
        sub, _dot2, last = rest.rpartition(".")
        if section.lower() == "branch" and sub == branch and last.lower() == key:
            value = val if eq else "true"
    return value


def _mergeoptions(global_opts: list[str], target: str) -> list[str]:
    """명령줄 `-c branch.<target>.mergeoptions=…` 의 낱말들 — git 은 이것을 target 으로의
    모든 머지(pull 이 하는 머지 포함)의 기본 옵션으로 읽음(실측: `-c
    branch.dev.mergeoptions=--no-ff` 가 머지 커밋을 만듦). 저장소 config 의 값과
    `--config-env` 는 읽지 않음.
    쪼갤 수 없는 값은 빈 목록."""
    import shlex

    value = _branch_config(global_opts, target, "mergeoptions")
    if not value:
        return []
    try:
        return shlex.split(value)
    except ValueError:
        return []


# 브랜치 이름 앞에 붙어도 그 브랜치를 가리키는 것: 전체 ref, 원격 추적 ref(`remotes/` 뒤 한
# 마디가 원격), `origin/`. 안 벗기면 `git merge refs/heads/feature/x` 가 `feature/*` 행을
# 비켜 감(실측: 러너 exit 0, 실제 git 은 머지함).
_REF_PREFIX_RE = re.compile(r"^(?:refs/heads/|heads/|(?:refs/)?remotes/[^/]+/|origin/)")
# 브랜치 이름에 `~`·`^`·`@{` 는 못 들어감(git check-ref-format) — 그 뒤는 리비전 접미.
_REVISION_SUFFIX_RE = re.compile(r"(?:[~^]|@\{).*\Z", re.S)


def _branch_matches(pattern: str, branch: str, branches: dict) -> bool:
    """브랜치가 merge_strategy 의 source/target 패턴에 맞는가.

    패턴에 `/` 가 있으면 브랜치 접두사 glob(`feature/*` → `feature/` 로 시작), 없으면
    vdev-config.branches 의 키로 보고 그 키의 값과 비교. 비교 전에 ref 접두
    (`_REF_PREFIX_RE`)를 벗기므로 `git merge origin/stage`·`refs/heads/stage` 가 `staging`
    키와 매칭됨. 모르는 키는 절대 매칭되지 않음(FAIL-OPEN — 적용할 규칙이 없음).
    """
    if not pattern or not branch:
        return False
    # 리비전 접미(`stage^0`·`stage~1`·`stage@{1}`)도 그 브랜치에서 온 커밋을 머지함.
    name = _REVISION_SUFFIX_RE.sub("", _REF_PREFIX_RE.sub("", branch))
    if "/" in pattern:
        return name.startswith(pattern.rstrip("*"))
    configured = branches.get(pattern)
    return bool(configured) and name == str(configured)


def match_merge_rule(rules: list[dict], source: str, target: str, branches: dict) -> dict | None:
    """source 와 target 이 둘 다 맞는 첫 규칙. 없으면 None(FAIL-OPEN)."""
    for rule in rules:
        if _branch_matches(str(rule.get("source", "")), source, branches) and _branch_matches(
            str(rule.get("target", "")), target, branches
        ):
            return rule
    return None


def _is_rebased(root: Path, source: str, target: str) -> bool:
    """target 이 source 의 조상인가(= source 가 target 위로 rebase 되었는가).

    경고 경로에서만 씀 — 여기서 False 가 나와도 절대 차단하지 않음. git 이 **실행조차
    안 되면**(FileNotFoundError·Timeout 등 예외) True("불만 없음")를 반환. 단 ref 가
    없으면 git 은 예외가 아니라 non-zero(128)를 내므로 이 함수는 False → 경고가 뜸. 그건
    의도된 것: 원격을 fetch 하지 않아 target ref 가 낡았을 때 경고하는 게 이 검사의 목적이고,
    사용자 메시지의 "origin ref 가 낡았다면 무시하세요" 단서가 그 오탐을 흡수함.
    """
    try:
        rc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", target, source],
            cwd=str(root),
            capture_output=True,
            timeout=5,
        ).returncode
    except Exception:
        return True
    return rc == 0


# 어디서든 선 `cd`·`pushd`·`popd`·서브셸·`env`(그 `-C` 가 명령을 옮김), 또는 `--git-dir`·
# `--work-tree`·`GIT_DIR`·`GIT_WORK_TREE` 로 지목한 저장소 — 머지가 셸이 선 트리가 아닌 데에
# 떨어질 수 있음.
_SHELL_MOVE_RE = re.compile(
    r"(?<![\w-])(?:cd|pushd|popd|env)(?![\w-])|\(|--git-dir|--work-tree|GIT_DIR|GIT_WORK_TREE"
)


def merge_check_output() -> None:
    """`git merge` 호출을 merge_strategy 정책에 비추어 검사.

    차단(BLOCK_EXIT_CODE)은 순수 형태 판정 둘뿐 — require 플래그 누락, forbid 플래그 존재.
    그 외 전부는 exit 0 (FAIL-OPEN — Invariant #1). 판정이 예외로 끝났거나 rebase 선행이
    안 보이는 통과는 그 사실을 stdout 의 ``systemMessage`` JSON 으로 말함 — exit 0 인 훅의
    stderr 는 사용자에게 닿지 않음.
    Invariant #2: 출력 전에 force_utf8_io.

    **채널 분리**: 차단 사유와 통지는 둘 다 **stdout** 으로 내고 exit code 로 구분함
    (차단=BLOCK_EXIT_CODE, 통지=0). 셸은 stdout 만 캡처하므로, 게이트 스크립트를 못 여는 등의
    인터프리터 오류(stderr + exit 2)가 차단 사유가 되지 않음(Invariant #1 — 내부 오류는
    게이트를 막지 않음). 커밋 경로의 main() 과 같은 규약.

    훅 JSON 을 **stdin** 으로 받음 — `--classify` 와 같음. 환경변수 관용구는 호환 alias
    `--resolve-worktree` 에만 남아 있음(옛 러너가 그렇게 넘김).
    """
    force_utf8_io()
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command") or ""
    try:
        notes = _merge_verdict(command, payload)
    except Exception as exc:  # FAIL-OPEN 이되 소리 내어
        notes = [f"merge 전략 판정 실패 — 판정 없이 통과: {type(exc).__name__}"]
    if notes:
        print(json.dumps({"systemMessage": "\n".join(notes)}, ensure_ascii=False))
    sys.exit(0)


def _merge_verdict(command: str, payload: dict) -> list[str]:
    """:func:`merge_check_output` 의 판정: 위반이면 BLOCK_EXIT_CODE 로 끝내고, 아니면 통과의
    통지들을 돌려줌.

    target 은 명령어가 말하면 명령어에서(`git switch dev && git merge …`), 그렇지 않을 때만
    HEAD 에서 읽음 — _target_from_command 참조.
    """
    notes: list[str] = []
    masked = mask_literals(command)
    judged = _judged(command, masked)
    if not judged:
        return notes

    root = host_root()
    # 머지마다 target 을 그 머지 **앞**의 switch 에서 읽음. 첫 머지의 target 하나로 전부를
    # 심사하면 사이에 선 switch 뒤의 머지가 정책에 없는 flow 로 차단되거나 판정에서 빠짐.
    # 저쪽 디렉터리에서 도는 머지는 **그 머지만** 뺌 — 명령 하나로 답하면 앞의 한 머지가
    # 뒤 전체를 면제했음(실측: `git -C ../other merge X && git merge stage` 가 exit 0).
    merges = []
    head: str | None = None
    # 디렉터리를 대는 머지도, 셸을 옮기는 것도 없는 명령의 머지는 셸이 선 트리의 HEAD 로
    # 들어감 — 이 저장소의 다른 worktree 는 root 가 아니라 자기 브랜치로 머지함. 그 밖은
    # `_points_elsewhere` 가 이미 판정한 대로 root 를 읽음. 정책·브랜치 이름은 여전히 root 것.
    head_tree = root
    named = [_merge_dash_c(command, j.call, masked) for j in judged]
    if all(d in (None, ".", "./") for d in named) and not _SHELL_MOVE_RE.search(command):
        head_tree = working_root(project_dir=root, hook_cwd=payload.get("cwd") or None)
    targets = _switch_targets(command, masked, [j.call for j in judged])
    for j, target in zip(judged, targets):
        # 불명확한 switch(`switch -c`, pathspec, origin ref …)는 HEAD 를 훅 시점과 다른 곳으로
        # 옮기므로, stale HEAD 로 판정하면 일어나지도 않는 flow 를 차단. 그 머지는 HEAD 폴백을
        # 안 씀.
        if target is _UNREADABLE or _points_elsewhere(command, root, j.call, masked):
            continue
        if target is None:
            head = head or _current_branch(head_tree)
            target = head
        if not isinstance(target, str) or not target:  # detached HEAD → 그 머지는 FAIL-OPEN
            continue
        prefix = _mergeoptions(j.global_opts, target)
        readings = [j.flags]
        if j.pull:
            words = _pull_operands(j.operands, j.global_opts, prefix)
            rebase = _pull_rebase(words, target, j.global_opts)
            readings = [set() if rebase else words.flags]
            if rebase is None and words.flags and _config_rebases(root, target):
                readings.append(set())
        elif prefix:
            readings = [_merge_operands(j.operands, j.global_opts, prefix=prefix)[0]]
        merges.append((readings, j.source, target))
    if not merges:  # 판정할 머지가 남지 않음 → FAIL-OPEN
        return notes

    try:
        import yaml

        data = yaml.safe_load(config_path(root).read_text(encoding="utf-8")) or {}
        branches = data.get("branches") or {}
    except Exception:
        branches = {}

    strategy = load_merge_strategy(tiers_path(root))
    # 이 명령이 돌리는 머지 **전부**를 판정. 정책이 허용하는 머지 하나가 앞에 서면 그
    # 뒤가 미판정으로 남았고, 이 판정은 fail-open 하면 안 됨.
    # 읽기가 둘이면(철자한 머지와 config 가 만든 rebase) 하나라도 어기면 막음.
    for readings, source, target in merges:
        rule = match_merge_rule(strategy, source, target, branches)
        if rule is None:
            continue

        required = rule.get("require")
        if required and not all(_carries(flags, required) for flags in readings):
            # 차단 사유는 stdout — 셸이 캡처해 deny 로 씀(인터프리터 오류 stderr 와 격리).
            print(
                f"머지 전략 위반 — '{rule.get('source')}' → '{target}' 는 "
                f"{required} 가 필요합니다. "
                f"절차는 주입된 risk-tiers 가 지목하는 rules/merge-strategy.md 를 따르세요."
            )
            sys.exit(BLOCK_EXIT_CODE)

        forbidden = rule.get("forbid")
        if forbidden and any(_carries(flags, forbidden) for flags in readings):
            print(
                f"머지 전략 위반 — '{rule.get('source')}' → '{target}' 에는 "
                f"{forbidden} 를 쓰지 않습니다. "
                f"절차는 주입된 risk-tiers 가 지목하는 rules/merge-strategy.md 를 따르세요."
            )
            sys.exit(BLOCK_EXIT_CODE)

        if rule.get("warn_unless_rebased") and not _is_rebased(root, source, target):
            notes.append(
                f"[경고] 머지 전략: '{rule.get('source')}' → '{target}' 는 "
                f"rebase 선행이 요구됩니다. "
                f"'{source}' 가 '{target}' 위에 rebase되어 있지 않은 것으로 보입니다"
                f"(origin ref 가 낡았다면 무시하세요)."
            )
    return notes


def policy_parseable(tiers_path: Path) -> bool:
    """vdev-tiers.yaml 이 정상 로드되고 tiers 섹션을 가지는가(정책 신뢰성).

    미분류 fail-closed 차단은 게이트가 *정상 작동 중*일 때만 적용해야 함(Invariant #1:
    깨진/부재 정책이 커밋을 영구 차단하지 않음). 파일 부재·파싱 실패·빈 tiers 는 모두
    "신뢰할 수 없음"으로 False — 차단 대신 FAIL-OPEN 으로 떨어짐.
    """
    if not tiers_path.is_file():
        return False
    try:
        import yaml

        data = yaml.safe_load(tiers_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return bool(data.get("tiers"))


def config_intact(config_path: Path) -> bool:
    """vdev-config.yaml 이 부재(정상)이거나 정상 로드되는가.

    부재는 정상(feature 작업·vdev-init 이전엔 config 가 없을 수 있음) → True.
    존재하는데 파싱 실패면 내부 오류 → False: lifecycle(staging/release) 판정이
    무력화된 상태이므로 promotion 커밋을 "미분류"로 오차단하지 않게 차단을 보류함.
    """
    if not config_path.is_file():
        return True
    try:
        import yaml

        yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return True


def missing_gates(vdev_dir: Path, gates: list[str]) -> list[str]:
    """RUNTIME_GATES(훅이 직접 실행하는 게이트)를 제외하고 <gate>.done 이 없는 게이트."""
    return [g for g in gates if g not in RUNTIME_GATES and not (vdev_dir / f"{g}.done").is_file()]


def _current_branch(root: Path) -> str | None:
    """현재 git 브랜치명을 반환. 실패 시 None."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def _resolve_context_tier(root: Path, vdev: Path, current: str | None) -> tuple[str | None, bool]:
    """현재 브랜치/.vdev tier 마커에서 적용할 티어 라벨을 해석.

    반환 ``(tier, is_lifecycle)``:
    - 라이프사이클 브랜치(stage/main)면 그 티어와 ``True``.
    - ``.vdev/tier`` 마커가 있고 현재 브랜치에 적용되면 그 티어와 ``False``.
    - 미분류(마커 없음)·다른 브랜치의 마커면 ``(None, False)``.

    1단계 증거 검사(main)와 2단계 모듈 사전검사(module_commands)가 공유하는
    유일한 티어 해석 지점(중복 정의 금지 — rule-dry-constants).
    """
    lifecycle = load_lifecycle_branches(config_path(root)).get(current or "")
    if lifecycle:
        return lifecycle, True
    tier_file = vdev / "tier"
    if not tier_file.is_file():
        return None, False
    tier, _, branch = tier_file.read_text(encoding="utf-8").strip().partition(":")
    tier, branch = tier.strip().lower(), branch.strip()
    if branch and current is not None and current != branch:
        return None, False
    return tier, False


def tiers_path(root: Path) -> Path:
    """vdev-tiers.yaml(플러그인 정책)의 위치를 해석.

    정책 파일은 게이트 스크립트와 함께 호스트로 배포되므로 다음 순서로 찾음:
    1. ``CLAUDE_PLUGIN_ROOT/vdev-tiers.yaml`` — 플러그인 hook 으로 직접 실행될 때
    2. config 디렉터리의 ``vdev-tiers.yaml`` — ``.claude/vway-kit/config/`` 로
       복사된 경우(게이트 스크립트는 형제 ``scripts/`` 에 있으므로 그 형제
       디렉터리 config/ 를 __file__ 기준으로 가리킴 — host_root() 불안정성에
       영향받지 않음).
    3. ``root`` 아래 ``.claude/vway-kit/config/`` 의 ``vdev-tiers.yaml`` — 2단계와 같은
       호스트 레이아웃을 __file__ 이 아니라 ``root`` 로 해석한 것. 2단계는 스크립트가
       호스트 사본 위치에서 *실행될* 때만 맞아떨어지므로, 모듈이 import 되는
       호출자(테스트·개발)에서는 빗나가 실제로 설치된 정책을 두고도 없는 것처럼 읽어
       게이트가 조용히 fail-open 함.
    4. 호스트 루트 ``vdev-tiers.yaml`` — 폴백(개발/테스트).
    """
    plugin = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin and (p := Path(plugin) / TIERS_FILENAME).is_file():
        return p
    config_copy = Path(__file__).resolve().parent.parent / Path(CONFIG_DIR).name / TIERS_FILENAME
    if config_copy.is_file():
        return config_copy
    host_config_copy = config_path(root).parent / TIERS_FILENAME
    if host_config_copy.is_file():
        return host_config_copy
    return root / TIERS_FILENAME


def _changed_files(root: Path) -> list[str]:
    """커밋 대상 변경 파일 목록. staged(--cached) 우선, 비면 working tree(HEAD diff)
    폴백(`git commit -a` 케이스). git 실패/변경 없음은 [] (FAIL-OPEN)."""
    # `-z` 로 받음 — 기본 `core.quotePath` 에서 비ASCII 경로가 C-인용돼 오면 `is_file()` 도
    # 모듈 prefix 매칭도 그 항목을 버려, 그 파일만 문체 경고와 모듈 사전검사 밖에 남음.
    for args in (["diff", "--cached", "--name-only", "-z"], ["diff", "HEAD", "--name-only", "-z"]):
        # `-z` 가 git 의 ASCII 보장을 없앰 — C-인용은 늘 ASCII 였지만 원시 바이트는 아님.
        # `errors="replace"` 와 try 안의 분해가 그래서 필수(`_vway_paths._git` 과 같은 근거):
        # strict 디코드는 리더 스레드에서 터져 `stdout` 이 None 이 되고, try 밖의 분해는
        # AttributeError 로 호출자를 넘어 그 커밋의 모듈 사전검사·문체 경고를 통째로 지움.
        # `strip()` 도 안 씀 — 이름이 공백으로 시작·끝나는 파일의 경로를 망가뜨림.
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            files = [name for name in (out.stdout or "").split("\0") if name]
        except Exception:
            continue
        if files:
            return files
    return []


def _match_modules(changed: list[str], modules: list[dict]) -> tuple[list[dict], list[str]]:
    """변경 파일을 modules[].path 와 prefix 매칭.

    반환 ``(매칭 모듈(순서 보존·중복 제거), 미커버 파일)``. 빈 path("")는 전체 매칭
    (단일스택 단일모듈). 첫 매칭 모듈에 귀속하고, 어떤 path 에도 안 걸리면 미커버.
    """
    matched: list[dict] = []
    seen: set[str] = set()
    uncovered: list[str] = []
    for f in changed:
        hit: dict | None = None
        for mod in modules:
            path = str(mod.get("path") or "")
            if path == "" or f.startswith(path):
                hit = mod
                break
        if hit is None:
            uncovered.append(f)
            continue
        key = str(hit.get("name") or hit.get("path") or "")
        if key not in seen:
            seen.add(key)
            matched.append(hit)
    return matched, uncovered


def _parse_check(key: str, val) -> tuple[str | None, str]:
    """checks 항목 하나를 (명령, 타이밍)으로 파싱.

    val 은 문자열(기존) 또는 {run, when} 확장 dict. timing 은 CHECK_TIMINGS
    로 정규화. 하위호환·FAIL-OPEN(Invariant #1):
      - 문자열 → every-commit. 단 key=='security' 는 promotion(매직 키 잔존).
      - dict 의 when 이 CHECK_TIMINGS 밖(생략·오타)이면 키 기반 기본값으로 라우팅.
    빈 명령은 (None, timing) — 호출측이 skip.

    타이밍 필드명은 `when`(`on` 아님). YAML 1.1(PyYAML)은 따옴표 없는
    `on:` 매핑 키를 불리언 True 로 해석하는 함정이 있어("Norway Problem"의 키
    버전 — GitHub Actions `on:` 트리거와 동일), config 작성자가 `on: promotion`
    을 쓰면 키가 문자열이 아니라 True 가 됨. `when` 은 boolean 토큰이 아니라
    이 함정이 원천적으로 없음.
    """
    default = "promotion" if key == "security" else "every-commit"
    if isinstance(val, dict):
        cmd = val.get("run")
        timing = val.get("when")
        if timing not in CHECK_TIMINGS:
            timing = default
        return (str(cmd) if cmd else None, timing)
    return (str(val) if val else None, default)


def _check_cmds(mod: dict, *, promotion: bool) -> list[str]:
    """모듈 checks 중 요청 타이밍 버킷의 명령만(config 작성 순서 보존, 빈 명령 skip).

    promotion=True → promotion 타이밍(security-scan 버킷),
    promotion=False → every-commit 타이밍(precommit 버킷)."""
    checks = mod.get("checks") or {}
    want = "promotion" if promotion else "every-commit"
    cmds: list[str] = []
    for k, v in checks.items():
        cmd, timing = _parse_check(k, v)
        if cmd and timing == want:
            cmds.append(cmd)
    return cmds


def wiki_gate(root: Path, gates: list[str] | None) -> bool:
    """wiki 런타임 게이트를 in-process 로 실행. True = 차단, False = 통과.

    **의도적으로** module_commands 를 타지 않음. 그 채널의 계약은 "비영 종료 = 검사
    실패"인데 런타임 게이트는 그것을 지킬 수 없음 — 스크립트 분실·인터프리터 손상·OOM
    kill 이 곧 저장소 전체 커밋 차단이 되고, wiki 는 Invariant #1 의 fail-closed 3대
    예외(의존성 부재·미분류 커밋·머지전략 위반) 중 어느 것도 아님. 여기서는 cmd_verify
    자신의 판정만 차단하고, 나머지는 전부 통과: wiki 미설정, 이 티어 gates 에 wiki 없음,
    반쪽 설치로 wiki_graph.py 부재(cmd_verify is None), 그리고 모든 예외.

    명령 문자열을 만들어 넘기지 않고 in-process 로 도는 덕에 `bash -c` 가 끌고 오던
    따옴표/인터프리터 버그류가 통째로 사라짐 — 셸이 실행할 시점엔 이미 사라졌을 수도
    있는 sys.executable 이 문자열에 박히지도, Windows 경로가 셸에 토큰화되지도 않음.
    """
    if not gates or "wiki" not in gates or cmd_verify is None:
        return False
    try:
        # load_wiki_config 로 미리 거르지 않음: cmd_verify 가 이미 wiki 부재 시 0 을
        # 돌려주고, 사전 검사는 매 커밋마다 vdev-config.yaml 을 한 번 더 파싱할 뿐.
        return cmd_verify(root) != 0
    except Exception:
        return False  # FAIL-OPEN — Invariant #1


def _rel(root: Path, path: Path) -> str:
    """저장소 상대 posix 경로. basename 만으로는 **어느** SKILL.md 인지 못 댐."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


def doc_style_gate(root: Path, gates: list[str] | None) -> str | None:
    """이 커밋이 바꾸는 파일의 산문을 검사. 보고할 텍스트, 깨끗하면 None.

    **경고만 하고 절대 차단하지 않음.** 판정은 트리 전체를 보는 CI(`doc-style.yml`)
    몫 — 여기서 막으면 규칙을 조인 순간 아무도 예측 못 한 커밋들이 거부됨. 불확실한
    것은 전부 침묵: 게이트 꺼짐·설정 꺼짐·doc_style_check.py 부재·어떤 예외든
    (Invariant #1).

    범위는 CI 의 `--lint-config` 와 **같은** :func:`doc_style_check.in_scope` 에서 옴.
    그래서 소비자가 쓴 `paths`/`exclude` 가 두 팔 모두에 걸림.
    """
    if not gates or "doc-style" not in gates or lint_paths is None or in_scope is None:
        return None
    try:
        paths = [root / f for f in _changed_files(root)]
        items = lint_paths(in_scope(root, [path for path in paths if path.is_file()]))
        lines = [
            f"{_rel(root, path)}:{lineno}: {code}: {message}"
            for path, findings in items
            for severity, lineno, code, message in findings
            if severity == "error"
        ]
    except Exception:
        # 보고를 만드는 일까지 try 안 — 밖에 두면 여기서 난 예외가 main() 까지 올라감.
        return None
    if not lines:
        return None
    head = "\n".join(lines[:20])
    more = f"\n... 외 {len(lines) - 20}건" if len(lines) > 20 else ""
    return f"문체 규율 위반 (vway-kit rules/doc-style.md)\n{head}{more}"


def module_commands(
    root: Path, tier: str | None, gates: list[str] | None
) -> tuple[list[str], list[str]]:
    """gates 리스트가 켜진 항목만 모듈 사전검사 명령을 만듦(tiers.yaml gates 가 SSOT
    — tier 라벨로 하드코딩하지 않음. gates 에서 빼면 그 검사가 꺼짐).

    - docs/None tier, 또는 gates 비어있음 → ([], []) — 모듈 사전검사 대상 없음.
    - "precommit" in gates → 변경 모듈의 every-commit 타이밍 checks(+ 미커버 리포트)
    - "security-scan" in gates → 전체 모듈의 promotion 타이밍 checks(승격 시)
    "wiki"·"doc-style" 게이트는 여기 없음 — 오류 계약이 다른 런타임 게이트라 main() 이
    프로세스 내부에서 :func:`_runtime_notices` 로 실행. 이 채널은 0 아닌 종료 코드를
    전부 "검사가 실패했다"로 읽으므로, 그 둘의 내부 오류가 커밋 차단으로 바뀌어 버림.
    config 파싱 실패·modules 부재는 ([], []) (FAIL-OPEN — Invariant #1)."""
    if tier is None or tier == "docs" or not gates:
        return [], []
    cfg = config_path(root)
    if not cfg.is_file():
        return [], []
    try:
        import yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return [], []
    modules = data.get("modules") or []
    if not modules:
        return [], []
    cmds: list[str] = []
    report: list[str] = []
    if "precommit" in gates:
        matched, uncovered = _match_modules(_changed_files(root), modules)
        for mod in matched:
            cmds += _check_cmds(mod, promotion=False)
        if uncovered:
            report.append(
                "다음 파일은 모듈 미커버라 사전검사 생략 — 새 모듈이면 "
                "vdev-config.modules[] 에 등록하세요:"
            )
            report += [f"  - {f}" for f in uncovered]
    if "security-scan" in gates:
        for mod in modules:
            cmds += _check_cmds(mod, promotion=True)
    return cmds, report


def main() -> None:
    """vdev 게이트 검사 진입점. 게이트 미충족 시 exit(BLOCK_EXIT_CODE), 통과 시 exit(0)."""
    force_utf8_io()
    root = host_root()
    # 호스트 측 vway-kit 산출물은 모두 .claude/vway-kit/ 한 곳에 모임
    # (config·증거·복사 스크립트). 경로 조립은 공용 헬퍼로 단일화.
    vdev = vdev_dir(root)
    tiers = tiers_path(root)
    current = _current_branch(root)

    tier, is_lifecycle = _resolve_context_tier(root, vdev, current)
    if tier is None:
        # tier 미해석을 두 원인으로 가름(같은 None 을 반대로 해석):
        #  - 정책(vdev-tiers.yaml)·설정(vdev-config.yaml)이 정상 작동 + tier 마커 파일
        #    자체 부재 = vdev 미진입(미분류) → FAIL-CLOSED 차단. vdev 를 우회한 커밋이
        #    게이트를 통째로 건너뛰지 못하게 함. 강제가 불필요하면 사용자가
        #    /vdev-uninstall 로 게이트 자체를 떼면 됨(escape hatch 를 코드에 두지 않음
        #    — 두면 그 우회로를 모델이 스스로 쓸 수 있음).
        #  - 정책 부재/파싱 실패, config 파싱 실패(설치/환경 불확정·내부 오류), 또는
        #    마커가 다른 브랜치(branch-bound stale) → FAIL-OPEN. Invariant #1(깨진/부재
        #    게이트가 커밋을 영구 차단하지 않음)·branch-bound(stale 마커가 무관한 브랜치
        #    작업을 막지 않음) 보존. "파일 존재"가 아니라 "신뢰성 있게 작동"이 기준.
        if (
            policy_parseable(tiers)
            and config_intact(config_path(root))
            and not (vdev / "tier").is_file()
        ):
            print(
                "vdev 미진입: 분류되지 않은 커밋입니다. /vdev 로 작업을 분류한 뒤 "
                "커밋하세요(강제가 불필요하면 /vdev-uninstall)."
            )
            sys.exit(BLOCK_EXIT_CODE)
        sys.exit(0)
    gates = required_gates(tiers, tier)
    if gates is None:  # 알 수 없는 티어 → FAIL-OPEN
        sys.exit(0)
    miss = missing_gates(vdev, gates)
    if miss:
        if is_lifecycle:
            print(f"{tier} 게이트 (브랜치 '{current}'): {miss} 증거가 필요합니다.")
        else:
            print(f"vdev 게이트: '{tier}' 티어는 {miss} 증거가 필요합니다.")
        sys.exit(BLOCK_EXIT_CODE)
    # 런타임 게이트는 이 프로세스에 얹힘 — tier 를 한 번만 해석하고, 두 번째 spawn 이면
    # 그걸 다시 해석하게 됨(spawn 2→1).
    _runtime_notices(root, gates)
    sys.exit(0)


def module_commands_output() -> None:
    """현재 tier 의 gates 로 켜진 모듈 사전검사 명령을 stdout(줄단위), 미커버 리포트를
    stderr 로 냄.

    gates 에 precommit 있으면 변경 모듈 non-security, security-scan 있으면 +전체 모듈
    security(tiers.yaml gates 리스트가 SSOT — 여기서 제거하면 해당 검사가 꺼짐).
    판정 실패는 빈 출력(FAIL-OPEN). precommit-runner.sh 가 stdout 명령을 실행하고
    stderr 리포트는 그대로 사용자에게 노출."""
    force_utf8_io()
    root = host_root()
    try:
        tier, _ = _resolve_context_tier(root, vdev_dir(root), _current_branch(root))
        gates = required_gates(tiers_path(root), tier) if tier else None
    except Exception:
        return  # FAIL-OPEN
    cmds, report = module_commands(root, tier, gates)
    for line in report:
        print(line, file=sys.stderr)
    for cmd in cmds:
        print(cmd)


def _wiki_stage(root: Path, gates: list[str] | None) -> str | None:
    """main() 의 단계로 도는 wiki 게이트. 할 말은 전부 STDOUT 으로 냄.

    stderr 가 아니라 stdout 인 이유는 둘 다 훅 계약에서 나옴:

    - ``python3 <없는 파일>`` 은 exit 2 + stderr 로 불평 — 차단과 완전히 같은 모양.
      vdev_gate_check.py 사본이 없는 호스트는 그러면 인터프리터 오류를 사유로 모든 커밋을
      거부당함. 그래서 precommit-runner.sh 는 stdout 만 읽고, 인터프리터는 stdout 에
      쓰지 않으므로 그 충돌이 fail-closed 로 이어질 수 없음.
    - exit 0 일 때 훅의 stdout·stderr 는 **둘 다** 디버그 로그로만 감 — 그래프 품질
      경고가 사람에게 영영 닿지 않음. 그래서 경고는 ``systemMessage`` JSON 페이로드로
      돌려주고(문서상 "사용자에게 보여줄 경고" 필드), 러너가 커밋을 통과시킬 때 그대로
      내보냄.

    ``VWAY_PRECOMMIT_DRYRUN=1`` 이면 통째로 건너뜀 — 러너의 옛 2단계 가드를 env 분기로
    보존해, 드라이런이 그래프 순회 비용을 치르거나 경고를 내지 않게 함.

    차단은 여기서 끝내고(exit), 통과했을 때의 경고는 **문자열로 돌려줌** —
    :func:`_runtime_notices` 가 다른 런타임 게이트의 경고와 하나의 JSON 으로 합침.
    """
    if os.environ.get("VWAY_PRECOMMIT_DRYRUN") == "1":
        return None
    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        blocked = wiki_gate(root, gates)
    text = captured.getvalue().strip()
    if blocked:
        if text:
            print(text)  # precommit-runner.sh 가 deny() 사유로 넘길 차단 사유
        sys.exit(BLOCK_EXIT_CODE)
    return f"wiki graph 경고\n{text}" if text else None


def _held_merge_note() -> str | None:
    """러너가 ``VWAY_MERGE_NOTE`` 로 넘긴 merge 단계 통지의 본문 — 훅이 낼 수 있는 JSON
    객체는 하나라서 이 단계의 통지에 실려 나감."""
    raw = os.environ.get("VWAY_MERGE_NOTE") or ""
    try:
        return (json.loads(raw) or {}).get("systemMessage") or None if raw else None
    except Exception:
        return None


def _runtime_notices(root: Path, gates: list[str] | None) -> None:
    """main() 에 얹힌 런타임 게이트들을 돌리고, 경고를 **하나의** 페이로드로 냄.

    precommit-runner.sh 는 통과한 커밋에서 이 stdout 을 그대로 내보냄. 같은 스트림에
    JSON 객체가 둘이면 파싱되지 않음 — 그래서 러너가 쥔 merge 단계 통지도 여기서 함께 나감.

    ``VWAY_PRECOMMIT_DRYRUN=1`` 은 wiki 뿐 아니라 **모든** 게이트 단계를 건너뜀(넘겨받은
    통지는 아님): 드라이런은 돌릴 명령과 넘겨받은 통지만 찍음.
    """
    notes = [_held_merge_note()]
    if os.environ.get("VWAY_PRECOMMIT_DRYRUN") != "1":
        notes += [_wiki_stage(root, gates), doc_style_gate(root, gates)]
    notes = [note for note in notes if note]
    if notes:
        print(json.dumps({"systemMessage": "\n\n".join(notes)}, ensure_ascii=False))


def wiki_check_output() -> None:
    """흡수된 wiki 단계(`--wiki-check`)의 호환 alias. 옛 계약 그대로.

    러너는 이걸 부르지 않음 — main() 이 같은 프로세스에서 wiki 게이트를 돌림.
    다만 반쯤 복사된 호스트가 옛 precommit-runner.sh 를 들고 있을 수 있고, 여기서 답해 주는
    비용은 분기 하나.
    """
    force_utf8_io()
    root = host_root()
    try:
        tier, _ = _resolve_context_tier(root, vdev_dir(root), _current_branch(root))
        gates = required_gates(tiers_path(root), tier) if tier else None
    except Exception:
        return  # FAIL-OPEN
    note = _wiki_stage(root, gates)
    if note:
        print(json.dumps({"systemMessage": note}, ensure_ascii=False))


def _detect_worktree(hook_cwd: str | None, command: str | None) -> Path | None:
    """커밋이 실제로 도는 worktree — main 과 다를 때만. 불확실하면 None(FAIL-OPEN).

    `CLAUDE_PROJECT_DIR` 은 세션 시작 위치에 고정돼 있으므로, 그 세션 안에서 만든 worktree 의
    커밋은 재지정 없이는 main 을 검사당한다(staged diff 안 보임 · 브랜치 바인딩된 tier 마커
    불일치 · 상대 경로 모듈 lint 가 worktree 파일을 놓침).
    """
    try:
        w = working_root(project_dir=host_root(), hook_cwd=hook_cwd, command=command)
    except Exception:
        return None  # FAIL-OPEN → 재지정 없음
    return w if w and w.resolve() != host_root().resolve() else None


# 다른 저장소의 커밋으로 읽는 명령은 둘뿐: `git -C <dir> commit …` 하나, 또는
# `cd <dir> && git commit …` 하나 — 앞에 아무것도 없고, 두 번째 명령·확장·이스케이프를 열 수
# 있는 글자가 어디에도 없을 때. 두 번째 `-C` 는 첫 것에 쌓이고 `--git-dir`·`GIT_DIR`·접두는
# 커밋을 이 저장소로 되돌릴 수 있으므로, 다른 모양은 전부 게이팅된 채 둠(Invariant 7).
# 낱말 구분은 공백·탭뿐 — 개행은 두 번째 명령을 엶. 디렉터리는 화이트리스트: bash 는 `~`·glob·
# brace 낱말을 다시 쓰고(`~+` 는 $PWD) `cd` 는 선두 `-` 를 $OLDPWD 나 옵션으로 읽는데, Python 은
# 둘 다 이름으로 읽음.
_DIR_WORD = r"(?!-)[\w./:+@%,=-]+"
_FOREIGN_COMMIT_RE = re.compile(
    rf"\A[ \t]*(?:cd[ \t]+(?P<cd>{_DIR_WORD})[ \t]*&&[ \t]*git[ \t]+commit"
    rf"|git[ \t]+-C[ \t]+(?P<c>{_DIR_WORD})[ \t]+commit)"
    r"(?:[ \t][^;&|`$()<>\\\n]*)?\Z"
)


def _commits_in_another_repo(command: str, root: Path, cwd: str | None) -> bool:
    """명령의 커밋 하나가 root 아닌 저장소에서 돈다는 것이 증명되는가.

    `git -C ../other commit` 이나 서브모듈의 커밋은 그 저장소 자신의 것이고, root 의 tier
    마커로 판정하면 이 게이트가 관장하지 않는 작업을 막음. 증명은 명령이
    `_FOREIGN_COMMIT_RE` 에 맞고, 셸 cwd 에서 읽은 그 디렉터리의 ``--git-common-dir`` 가
    다를 것 — 못 읽는 디렉터리는 게이팅된 채 둠. 디렉터리는 bash 와 git 이 같은 트리로 읽는
    모양일 때만 증명이 됨.
    """
    m = _FOREIGN_COMMIT_RE.match(command)
    if not m or "--git-dir" in command or "--work-tree" in command:
        return False
    word = m.group("cd") or m.group("c")
    # 프로브는 `-C` 의 git 처럼 디렉터리를 물리적으로 풂. bash 의 `cd` 는 받은 경로 위에서 `..`
    # 를 접으므로 심링크를 지나면 둘이 다른 트리를 가리킴.
    if m.group("cd") and ".." in word.split("/"):
        return False
    # Git Bash 의 `cd` 는 모든 경로를 MSYS 마운트 표로 옮기는데 Python 은 그 표를 안 읽음.
    # `-C` 값은 `C:/…` 나 평범한 상대 경로만 남김 — 선두 `/` 는 MSYS 가 네이티브 git 에 닿기 전에
    # 다시 씀.
    if os.name == "nt" and (m.group("cd") or not re.fullmatch(r"(?:[A-Za-z]:/)?[^/:][^:]*", word)):
        return False
    named = Path(cwd or ".", word)
    ours, theirs = _git_common_dir(root), _git_common_dir(named)
    return ours is not None and theirs is not None and ours != theirs


def classify_output() -> None:
    """훅의 명령이 **무엇인지** 냄 — 그 물음에 대한 게이트의 유일한 권위.

    precommit-runner.sh 는 이걸 띄울지 말지만 정하고, 그래서 그쪽 필터는 일부러 거칢.
    같은 물음을 손으로 쓴 문법 **둘**이 답하던 때, 한쪽만 받아 주는 철자는 좁은 게이트가
    아니라 조용히 꺼진 게이트였음: 경로 붙은 `git … commit` 은 러너를 통과하고도 worktree 를
    못 풀어 ROOT 를 깨끗한 main 에 남겼고, 거기서 exit 0 했음. 문법은 한 곳 —
    다른 모든 용도로 명령을 읽는 그 함수들 — 에 있으므로 러너가 그것과 어긋날 수 없음.

    다섯 줄, 각각 참일 때만 냄:
      ``ok=1`` — **읽었음**. 이게 없으면 러너는 판정을 못 받은 것으로 보고 스스로 게이팅함.
      ``commit=1`` / ``merge=1`` — 명령이 그 호출을 담고 있음.
      ``unresolved=1`` — 커밋이 이름을 댈 수 없는 트리에서 돎. worktree 줄이 뒤따르든 말든
        냄: `working_root` 는 명령이 답을 못 줘도 훅 자신의 cwd 에서 트리 하나에 닿을 수
        있고, 그 트리는 커밋이 어디 떨어지는지에 대한 **추측**이지 읽기가 아님. 러너는 어느
        쪽이든 이걸 알아야 함 — 그 트리가 깨끗한 동안 커밋은 딴 데서 돌 수 있음.
      ``worktree=<path>`` — 커밋이 main 아닌 git worktree 에서 돎(브랜치 키로 탐지).
    실패는 언제나 **덜** 냄: 읽을 수 없는 명령은 이것이 게이팅할 호출이 아니고, 탐지 못 한
    worktree 는 ROOT 를 main 에 남김(Invariant #1 · 7, FAIL-OPEN).
    Invariant #2: 어떤 print 보다 먼저 force_utf8_io.
    """
    force_utf8_io()
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return  # FAIL-OPEN → 판정 없음 → 러너가 스스로 게이팅함
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        # 읽을 명령이 없으니 낼 판정도 없음. 여기서 `ok=1` 을 내면 "읽었고 커밋이 아니다"가
        # 되고 러너는 그것을 통과로 받음 — 페이로드가 도구가 보내는 모양이 아닐 때 남는
        # 유일한 뒷받침(raw stdin 필터)까지 버리는 셈.
        return
    try:
        is_commit = is_invocation(command, "commit")
        # 브랜치를 대는 pull 은 그 브랜치의 머지 — 전략 판정을 받으려면 merge 로 답해야 함.
        is_merge = is_invocation(command, "merge") or any(
            _pulls_with_a_source(command, mask_literals(command))
        )
    except Exception:
        return  # FAIL-OPEN
    try:
        if is_commit and _commits_in_another_repo(command, host_root(), payload.get("cwd")):
            is_commit = False
    except Exception:
        pass  # 증명 못 함 → 커밋은 게이팅된 채
    print("ok=1")
    if is_commit:
        print("commit=1")
    if is_merge:
        print("merge=1")

    if not is_commit:  # 커밋 경로만 worktree 를 재지정함(Invariant 7)
        return
    if commit_tree_unresolved(command):
        print("unresolved=1")
    w = _detect_worktree(payload.get("cwd") or None, command or None)
    if w:
        print(f"worktree={w}")


def resolve_worktree_output() -> None:
    """`--classify` 이전 계약의 호환 alias. 훅 JSON 은 VWAY_HOOK_JSON 에서 읽음.

    스크립트는 호스트로 **한 파일씩** 복사되고 vdev_gate_check.py 가 러너보다 먼저 복사되므로
    (vdev_init_setup.COPY_FILES), 동기화 도중의 호스트는 새 스크립트에 옛 러너를 물림.
    이 갈래가 없으면 그 러너의 물음이 `main()` 으로 떨어져 게이트 판정이 통째로 돎."""
    force_utf8_io()
    hook_cwd = None
    command = None
    raw = os.environ.get("VWAY_HOOK_JSON")
    if raw:
        try:
            data = json.loads(raw)
            hook_cwd = data.get("cwd") or None
            command = (data.get("tool_input") or {}).get("command") or None
        except Exception:
            pass
    w = _detect_worktree(hook_cwd, command)
    if w:
        print(str(w))


if __name__ == "__main__":
    try:
        if "--module-commands" in sys.argv:
            module_commands_output()
        elif "--classify" in sys.argv:
            classify_output()
        elif "--resolve-worktree" in sys.argv:
            resolve_worktree_output()
        elif "--wiki-check" in sys.argv:
            wiki_check_output()
        elif "--merge-check" in sys.argv:
            merge_check_output()
        else:
            main()
    except SystemExit:
        raise
    except Exception as exc:  # FAIL-OPEN
        print(f"[vdev-gate] unexpected error, allowing: {exc}", file=sys.stderr)
        sys.exit(0)
