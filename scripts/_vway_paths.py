"""vway-kit 게이트/스크립트 공용 상수·경로 헬퍼 (매직값 SSOT).

이 repo 의 [rule-dry-constants] 규율(매직 넘버·문자열은 한 곳에서 정의)을 게이트
스크립트 자신에게 적용하는 단일 출처. 경로 세그먼트·파일명·차단 exit code·런타임
게이트 키·라이프사이클 티어 라벨을 여기서만 정의하고, 다른 스크립트는 import 함.

**왜 모듈인가(import 양립)**: 플러그인 스크립트는 호스트로 *단일 파일씩* 복사되어
실행되므로(`from vdev_init_setup import ...` 할 동료가 없음) 이 모듈을 vdev_init_setup
의 COPY_FILES 에 포함시켜 게이트 스크립트와 함께 복사함. 그러면 두 실행 모드 모두에서
import 가 성립함:
  - 직접 실행(`python3 .../scripts/vdev_gate_check.py`): sys.path[0]=scripts/ →
    형제 `import _vway_paths` 성립.
  - 패키지 import(pytest 의 `from scripts.vdev_gate_check import ...`):
    `from scripts._vway_paths import ...` 성립.
호출측은 아래 관용구로 둘을 양립시킴(부트스트랩이라 추상화 불가):

    try:
        from _vway_paths import host_root, force_utf8_io  # 직접 실행(형제)
    except ImportError:
        from scripts._vway_paths import host_root, force_utf8_io  # 패키지(테스트/개발)

**외부 계약값은 여기 두지 않음**: 훅 이벤트명(PreToolUse/SessionStart)·환경변수
키(CLAUDE_PROJECT_DIR 등)는 Claude Code 런타임/SDK 가 강제하므로 키 문자열 자체는
불변이고 JSON/셸과 교차 공유가 불가능. 단 그 키를 *읽는 폴백 헬퍼*(host_root/
plugin_root)는 변종이 갈라지기 쉬워 여기로 모음.
"""

from __future__ import annotations

import ntpath
import os
import re
import subprocess
import sys
from bisect import bisect_left, bisect_right
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import NamedTuple

# ── 호스트 쓰기 루트 아래 경로 세그먼트(루트 기준 상대경로 문자열) ──────────────
# CLAUDE.md: 모든 호스트 쓰기는 .claude/vway-kit/ 한 곳에 모음. vdev_init_setup 이
# `host / SCRIPTS_DIR` 처럼 호스트 루트와 join 하므로 문자열 상대경로로 노출.
VWAY_DIR = ".claude/vway-kit"  # 호스트 측 산출물 루트
SCRIPTS_DIR = f"{VWAY_DIR}/scripts"  # 복사 게이트 스크립트 (플러그인 소유·git추적)
CONFIG_DIR = f"{VWAY_DIR}/config"  # vdev-config·vdev-tiers(정책)·계정·웹훅
VDEV_DIR = f"{VWAY_DIR}/.vdev"  # 게이트 증거 (gitignored)
# 플러그인 매니페스트 — 이 저장소가 플러그인을 **출하**하는지의 답. 그 저장소의 루트
# `templates/` 는 출하본이라 셋업이 옮기지도, 소비자 스킬이 폴백을 알리지도 않음.
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
# 이름은 플러그인 쪽 출하 디렉터리와 같고 자리만 다름 — 그 비대칭의 SSOT 는
# `templates_lookup`. DIRNAME 이 경로를 만들고(스킬이 찾는 자리 = 셋업이 두는 자리),
# DIR 은 사람이 읽는 보고 줄이 그 자리를 그대로 부르게 함.
TEMPLATES_DIRNAME = "templates"  # 호스트 사본은 VWAY_DIR 밑, 플러그인 원본은 저장소 루트
TEMPLATES_DIR = f"{VWAY_DIR}/{TEMPLATES_DIRNAME}"  # 호스트 양식 (호스트 소유·git추적)

# ── config 디렉터리 하위 파일명 ────────────────────────────────────────────────
# 둘 다 config/ 에 위치하나 소유권이 다름: vdev-config 는 호스트 환경값(사람이 편집),
# vdev-tiers 는 플러그인 정책(tier→gates, 불변·SSOT — config/ 에 있으나 편집 금지).
CONFIG_FILENAME = "vdev-config.yaml"  # 호스트 환경값(브랜치·modules·teamer·handoff)
TIERS_FILENAME = "vdev-tiers.yaml"  # 플러그인 정책(tier→gates, 불변·SSOT)

# ── 게이트 계약 상수 ───────────────────────────────────────────────────────────
# Invariant #3: PreToolUse 차단은 exit 2 가 실제 차단 수단. 생산자(vdev_gate_check)는
# 이 상수로 차단하고, 소비자(precommit-runner.sh)·테스트는 같은 값을 byte-match 함.
BLOCK_EXIT_CODE = 2
# 마커 없이 훅이 직접 실행하는 런타임 게이트 집합(= 검사 타이밍 버킷) — vdev_gate_check
# 의 .done 검사에서 제외. vdev-tiers.yaml gates 리스트의 동일 키와 정확히 일치해야 함
# (desync 시 missing_gates 가 해당 게이트를 미충족으로 잘못 보고 — rename 시 동기화).
# precommit·security-scan 은 modules[].checks 위의 타이밍 버킷이라, 각 검사가 자기 when
# (every-commit | promotion)으로 버킷에 라우팅됨(CHECK_TIMINGS). wiki 는 modules[] 와
# 무관 — 아래 참조.
# - precommit: every-commit 타이밍(변경 모듈, 매 커밋). precommit-runner.sh 가 직접 실행.
# - security-scan: promotion 타이밍(전체 모듈, staging/release 승격 시). 동.
# - wiki·doc-style: vdev_gate_check.py main() 이 **프로세스 내부 단계**로 실행
#   (`--wiki-check` 는 호환 alias 로 존치). 위 모듈 명령 채널로는 절대 돌지 않음.
#   wiki 는 vdev-config.wiki 가 살아 있을 때만, doc-style 은 vdev-config.doc_style 이
#   켜졌을 때만 동작하고, 그때는 전 티어에서 각각 그래프 drift·구조 위반과 산문 문체를
#   검사함. 미설정 → 아무것도 돌지 않음. 모듈 채널 밖에 두는 이유는 두 채널의 오류 계약이
#   정반대이기 때문: 모듈 채널에선 비영 종료가 곧 "검사 실패"지만, 런타임 게이트는 진짜
#   판정이 아닌 모든 것에 FAIL-OPEN 해야 함(Invariant #1). main() 에 얹혀 가야 통과하는
#   커밋에서도 경고가 사용자에게 닿음 — 모듈 채널은 출력을 로그로 모았다가 실패 시에만
#   뿌림. 둘의 차이는 차단 여부: wiki 는 차단할 수 있고, doc-style 은 경고만 함
#   (판정은 트리 전체를 보는 CI 몫 — rules/risk-tiers.md Gates 용어집).
RUNTIME_GATES = ("precommit", "security-scan", "wiki", "doc-style")
# 모듈 검사 타이밍 버킷. checks 값이 {run, when} 확장 dict 일 때 when 값의 허용 집합이자,
# 문자열/오류값의 라우팅 대상(_parse_check). precommit↔every-commit, security-scan↔
# promotion 로 대응.
CHECK_TIMINGS = ("every-commit", "promotion")
# 라이프사이클 브랜치 → 티어 라벨. vdev-tiers.yaml tiers: 키와 byte-match 해야 게이트가
# 강제된다(desync 시 required_gates 가 None → FAIL-OPEN 으로 게이트 silent skip).
STAGING_TIER = "staging"
RELEASE_TIER = "release"


# ── 호스트 루트 기준 절대 경로(Path) 헬퍼 ──────────────────────────────────────
def vway_dir(root: Path) -> Path:
    """host_root 아래 .claude/vway-kit/ 절대 경로."""
    return root / ".claude" / "vway-kit"


def config_dir(root: Path) -> Path:
    """.claude/vway-kit/config/ — 호스트 소유 설정(vdev-config·웹훅·계정)."""
    return vway_dir(root) / "config"


def vdev_dir(root: Path) -> Path:
    """.claude/vway-kit/.vdev/ — 게이트 증거(<gate>.done·tier 마커)."""
    return vway_dir(root) / ".vdev"


def config_path(root: Path) -> Path:
    """.claude/vway-kit/config/vdev-config.yaml — 호스트 환경값 설정 파일."""
    return config_dir(root) / CONFIG_FILENAME


# git 이 경로를 내는 인코딩 — Windows 의 git 은 늘 UTF-8, POSIX 의 git 은 파일 이름의 원시 바이트.
# `surrogateescape` 와 짝이면 POSIX 의 비UTF-8 바이트 이름도 원래대로 돌아옴(`os.fsdecode` 와 같음).
# 루트를 정하는 조회(host_root·worktree 판정)만 이것 — 틀린 루트는 그 밑의 config·양식·계정 파일을
# 통째로 놓치게 함. 목록 조회(`_git`)는 한 항목이 빗나가는 것으로 끝나 utf-8·replace 유지.
# Windows 에 fs 인코딩을 안 씀 — `PYTHONLEGACYWINDOWSFSENCODING=1` 이 그것을 mbcs 로 돌림.
_GIT_PATH_ENCODING = "utf-8" if os.name == "nt" else sys.getfilesystemencoding()


# ── 환경변수 폴백 헬퍼(키 자체는 외부 계약·불변, 폴백 로직만 단일화) ────────────
def host_root() -> Path:
    """호스트 저장소 루트. CLAUDE_PROJECT_DIR → git toplevel → .claude 마커 역산 → cwd.

    가장 견고한 폴백을 표준으로 둠(teams_alert._host_root 와 같은 사다리). CLAUDE_PROJECT_DIR
    은 훅 실행 시에만 자동 주입되고 pre-push·수동 호출엔 비어 있을 수 있어, git
    toplevel 로 폴백하고 git 마저 실패하면 호스트 사본 위치(.claude/vway-kit/scripts/)
    에서 `.claude` 의 부모를 역산(고정 인덱스 대신 마커 탐색 — 설치 깊이 무관).
    마커가 없으면(SOURCE/standalone) cwd 로 떨어짐.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding=_GIT_PATH_ENCODING,
            errors="surrogateescape",
            check=True,
            timeout=3,
        )
        top = out.stdout.strip()
        if top:
            return Path(top)
    except Exception:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == ".claude":
            return parent.parent
    return Path.cwd()


def plugin_root() -> Path:
    """플러그인 루트. CLAUDE_PLUGIN_ROOT 우선, 없으면 이 스크립트의 상위(scripts/..)."""
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(env) if env else Path(__file__).resolve().parent.parent


# ── worktree 탐지(브랜치-키): 커밋이 실제로 도는 worktree 를 해석 ──────────────
# CLAUDE_PROJECT_DIR 은 세션 시작 위치(보통 main)에 고정돼, main 세션 안에서 만든
# worktree 의 커밋을 main 기준으로 검사하는 문제가 있음. 아래 헬퍼가 커밋 실행 위치를
# 결정론적 신호부터 읽어 worktree 루트를 특정. 불확실/오류는 project_dir 반환
# (FAIL-OPEN — 게이트가 깨진 탐지로 커밋을 막지 않음).
# 경로 토큰: 셸 단어 하나 — 조각(맨몸 문자 · "쌍따옴표" 덩어리 · '홑따옴표' 덩어리)의
# 반복. 통짜 대안(따옴표 전체 또는 맨몸 전체)으로 읽으면 `git -C "C:/My Project"/wt
# commit` 에서 `C:/My Project` 만 잡고 `/wt` 를 버림 — 셸은 이 명령을 커밋으로
# 라우팅하는데 그 부모는 이 repo 의 worktree 가 아니라 후보에서 기각되고, 게이트는
# 세션 루트를 검사함 — 그쪽이 깨끗하면 조기 종료로 미분류 커밋이 통과.
# 조각 반복은 각 위치에서 진행할 길이 하나뿐이라 백트래킹 갈래도 만들지 않음.
# git -C / cd 대상 디렉터리를 읽는 모든 정규식이 이 조각을 공유(rule-dry-constants).
# vdev_gate_check 의 merge 경로 정규식도 이것을 import 해서 씀.
_WORD = r"""(?:[^\s"']|"[^"]*"|'[^']*')+"""
_PATH_TOKEN = rf"({_WORD})"

# 인용의 권위는 **하나**. 아래 스캐너가 리터럴 구간을 정하고, 패턴들은 그것을 덮은
# 마스크에만 매치함. 정규식이 따옴표 규칙을 자기 안에 다시 적으면 두 벌이 되고, 실제로
# 두 벌이 서로 다르게 틀림 — 커밋 쪽에서 고친 결함이 merge 쪽 분할에 그대로 남아 있었음.
# 마스크 위에서는 따옴표 인자가 공백 없는 덩어리 하나이므로 옵션 토큰이 맨 `\S+` 여도 되고,
# 그래서 갈래가 곱해질 자리 자체가 사라짐(지수 백트래킹 소멸).


# git 과 서브커맨드 사이의 전역 옵션 영역 — 마스크 위에서만 뜻이 통함. 마스크가 따옴표
# 인자를 공백 없는 덩어리 하나로 만들어 두므로 플래그도 인자도 맨 `\S+`. 단독 `-` 도 토큰
# (`git -C - commit` 은 `-` 라는 디렉터리에서 돎).
# `switch`/`checkout` 을 찾는 vdev_gate_check 의 정규식도 이 조각을 import 해서 씀
# (rule-dry-constants — 옵션 영역 문법은 한 곳에서만 정의).
_GLOBAL_OPTS = r"(?:\s+-\S*(?:\s+(?!-)\S+)?)*"


# 프로그램 토큰과 그 뒤 전역 옵션 연속 — 아래 문법의 두 절반. 따로 두는 것은 이미 읽은
# 연속 안에 선 `git` 을 검색이 건너뛰게 하려는 것.
_GIT_HEAD_RE = re.compile(r"\bgit(?:\.exe)?")
_GIT_OPTIONS_RE = re.compile(_GLOBAL_OPTS)


class GitSubcommand:
    """컴파일한 `git … <word>` 문법. `search`·`finditer`·`match` 가 정규식 하나가 낼 매치를
    그대로 냄.

    정규식을 `git` 마다 걸면 옵션 연속을 그 끝까지 매번 다시 훑어, `-a git` 쌍이 이어진
    명령은 길이의 제곱이 됨(28,000자에서 7.7초, 실측) — 훅 타임아웃을 넘기면 판정이 없음.
    앞서 시도한 `git` 의 옵션 연속 **안에서** 끝나는 `git` 은 건너뜀: 거기서는 옵션이나 그
    값일 뿐이고, 그 뒤에 무엇이 오든 앞 시작점도 읽을 수 있었으므로 같은 자리에서 실패함.
    같음은 `tests/vway_paths/test_quote_removal.py` 가 생성한 명령으로 원래 정규식과 대조함.
    """

    def __init__(self, word: str) -> None:
        self._re = re.compile(rf"\bgit(?:\.exe)?({_GLOBAL_OPTS})\s+{word}(?![\w./-])")
        self.pattern = self._re.pattern

    def match(self, string: str, pos: int = 0, endpos: int | None = None):
        return self._re.match(string, pos, len(string) if endpos is None else endpos)

    def finditer(self, string: str, pos: int = 0, endpos: int | None = None):
        end = len(string) if endpos is None else endpos
        read_until = -1
        i = pos
        while True:
            head = _GIT_HEAD_RE.search(string, i, end)
            if head is None:
                return
            if head.end() > read_until:
                m = self._re.match(string, head.start(), end)
                if m:
                    yield m
                    i = max(m.end(), head.start() + 1)
                    continue
                read_until = _GIT_OPTIONS_RE.match(string, head.end(), end).end()
            i = head.start() + 1

    def search(self, string: str, pos: int = 0, endpos: int | None = None):
        return next(self.finditer(string, pos, endpos), None)


def git_subcommand_re(word: str) -> GitSubcommand:
    r"""진짜 `git … <word>` 호출. 그룹 1 = 전역 옵션 영역.

    게이트가 보는 두 서브커맨드(`commit`·`merge`)가 문법 하나를 공유.
    **반드시 `mask_literals` 출력에 매치**할 것 — 원본에 걸면 메시지·본문 안의 낱말이 호출로
    읽힘. `\bgit` 앵커는 `mygit` 을 막고, 백틱·명령 치환 안의 진짜 호출은 살림(명령
    자리인지는 `at_command_start` 가 따로 판정). `(?!-)` 는 `-` 로 시작하는 토큰을 언제나
    플래그로 못박아 "앞 플래그의 인자"라는 두 번째 해석을 없앰. 온전한 낱말 종결이라
    `commit-graph`·`merge-base` 는 이 서브커맨드가 아님.


    `/usr/bin/git` 처럼 디렉터리가 붙은 철자는 `\b` 가 이미 통과시키고, 그것이 명령 자리인지는
    `at_command_start` 가 판정 — 여기 접두를 정규식으로 넣으면 매 위치마다 되감아
    **2차**가 됨(800회 반복에서 0.2ms → 331ms, 실측).
    """
    return GitSubcommand(word)


_GIT_COMMIT_RE = git_subcommand_re("commit")

# 텍스트를 받아 **코드로 실행하는** 프로그램들. 이 목록은 둘째 읽기의 방아쇠도, heredoc
# 본문이 스크립트인지 메시지인지를 정하는 것도 **아님** — 둘 다였을 때는 목록에 없는 이름
# 하나가 곧 게이트가 exit 0 하는 진짜 커밋이었음 — 목록을 늘려도 다음 이름이 또 나왔음.
# 지금 남은 쓰임은 `_EXECUTES_NEXT_RE` 하나 — 인용 span 이 `-c` 인자로 서는 자리를 재는 데
# 이름이 필요함. 거기서 이름이 빠져도 둘째 읽기가 그 원소를 **비판독**으로 보고 스크립트로
# 다시 읽으므로, 목록의 구멍이 게이트의 구멍이 되지는 않음(그것이 방아쇠를 뗀 이유).
# 긴 이름 먼저 — `python3` 이 "python 뒤에 숫자"로 읽히지 않게.
_RUNS_TEXT = (
    "powershell",
    "python3",
    "python2",
    "busybox",
    "python",
    "source",
    "perl",
    "pwsh",
    "ruby",
    "node",
    "bash",
    "dash",
    "eval",
    "zsh",
    "ksh",
    "ash",
    "cmd",
    "sh",
)
# 오직 **읽기만 하는** 프로그램들. 원소가 돌리는 프로그램이 전부 여기 있을 때만 둘째 읽기를
# 건너뜀 — 실행하는 것을 나열하던 것의 반대. 이 목록에서 빠진 이름은 오차단 하나이고
# 사용자가 보고 우회할 수 있지만, 저 목록에서 빠진 이름은 아무 말 없이 꺼진 게이트였음.
# 이름이 면제를 얻는 조건은 **자기 인자에 적힌 명령도, 자기 환경이 지목하는 명령도 돌릴 방법이
# 없을 것**. `awk`(`system`·파이프·`getline`)·`sed`(GNU `e`)·`find`(`-exec`)·`ack`·
# `ag`(`--pager` 가 셸을 거침)는 앞의 것이 있음 — 그래서 그 옆에서 쓰이는 도구들만 여기 있고
# 그것들은 없음. `less` 는 뒤의 것이 있어 빠짐: 대부분 배포판이 login profile 에서 설정하는
# `LESSOPEN` 이 `less` 가 돌릴 명령을 지목하므로 명령 텍스트에는 아무 흔적도 없고, 실제로
# 커밋이 돌았음(실측). `more` 는 여러 호스트에서 같은 프로그램이라 함께 뺌.
# `sort`·`rg`·`printf` 는 **평범한 검색·출력 용법으로는** 여기 남음: 셸 문자열이 아니라
# PATH 로 프로그램을 부르므로 명령이 적은 것 중 무엇도 명령이 되지 않음. 다만 프로그램을
# 지목하는 실행 플래그가 붙으면 그 **원소 하나**에 한해 면제를 회수함 —
# `_EXEC_FLAG_READERS`·`_runs_by_flag`.
_READS_ONLY = frozenset(
    (
        "cat",
        "cut",
        "diff",
        "dirname",
        "du",
        "echo",
        "egrep",
        "false",
        "fgrep",
        "file",
        "grep",
        "head",
        "ls",
        "printf",
        "pwd",
        "rg",
        "shellcheck",
        "sort",
        "stat",
        "tail",
        "tr",
        "tree",
        "true",
        "type",
        "uniq",
        "wc",
        "whereis",
        "which",
    )
)
# `_READS_ONLY` 에 있으면서도 **프로그램을 지목하는 실행 플래그**를 받으면 면제를 잃는
# 판독기들. 그 플래그의 값은 PATH 로 돌아가는 프로그램이므로, 값이 실제로 이름이 될 수
# 있으면(존재하고 공백이 없으면) 무언가가 돎. 판정은 파이프 단계마다 **자기 인자 범위
# 위에서** — `printf x | rg -v y` 의 `-v` 는 `rg` 것이지 `printf` 것이 아님.
_EXEC_FLAG_READERS = {
    # 프로그램: 토큰 하나가 면제를 끄는가(shlex 토큰 하나에 대한 술어)
    "printf": lambda t: t.startswith("-v"),  # bash `printf -v NAME` 은 대입 — `-vNAME` 도 같음
    "rg": lambda t: t == "--pre" or t.startswith("--pre="),  # `--pre-glob` 은 아님
    "sort": lambda t: t.startswith("--co"),  # GNU 는 `--co…` 로 `--compress-program` 을 줄임
}
# 값이 **따로 서는** 프로그램들. `rg`·`sort` 는 다음 토큰이나 `=` 뒤가 값이라 그 값이
# 이름이 될 수 있는지를 더 물음. `printf -v` 는 플래그 자체가 대입이라 값을 안 물음.
_EXEC_FLAG_VALUE_PROGRAMS = ("rg", "sort")
# 읽기 전용은 아니지만 둘째 읽기를 면제받는 이름. **하나뿐이고, 근거가 다름.** `git` 이
# 자기 인자에 적힌 명령을 돌리려면 아래 플래그 중 하나를 들어야 하고, 그 플래그가 있으면
# 면제가 사라짐. 그것 없는 `git` 은 인자를 데이터로만 쓰므로, 실제로 돌리는 커밋은 정밀한
# 읽기가 마스크 위에서 이미 잡음. 면제하지 않았을 때의 비용은 우회로가 없는 읽기 전용
# 작업의 차단이었음 — `git grep 'git commit'`·`git log --grep='git commit'`·
# `git log -S 'git commit -m'` 이 전부 미분류로 막혔음(실측: 43개 중 9개).
_EXEMPT_BEYOND_READERS = frozenset({"git"})
# git 이 자기 인자를 **명령으로 돌리는** 철자들. 플래그만이 아니라 서브커맨드도 있음 —
# `git submodule foreach 'git commit -am x'` 는 실제 git 에서 서브모듈 커밋 수를 늘렸고,
# `git bisect run <cmd>` 는 그 인자를 돌리며, `git filter-branch --tree-filter '<cmd>'` 도
# 같음(실측). `--exec`/`-x` 는 alias 도 config 도 아닌 평범한 플래그이고
# `git rebase --exec 'git commit …' --root` 는 진짜로 커밋함(실측: 커밋 수가 늘었음).
# `-c` 는 `alias.x='!cmd'`·`core.pager=cmd` 를 실음.
# 이 철자가 있어도 커밋처럼 생긴 텍스트가 없으면 그물은 아무것도 물지 않음 —
# `git -c commit.gpgsign=false log` 는 여전히 통과함(실측).
# 갈래는 전부 **리터럴**. `--[a-z-]+-filter` 처럼 적으면 `-filter` 를 못 찾는 긴 토큰마다
# 되감아 2차가 되고, 훅에서의 2차는 타임아웃 = 조용한 게이트 스킵.
# `run`·`foreach` 는 **자기 서브커맨드에 묶어서만** 봄. 낱말만 보면 `git grep 'git commit'
# -- run` 처럼 경로가 그 이름인 읽기 전용 명령이 우회로 없이 막힘(실측 4건).
_GIT_RUNS_A_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:-c|-x|--exec|--config-env|--upload-pack"
    r"|--tree-filter|--index-filter|--commit-filter|--msg-filter"
    r"|--env-filter|--parent-filter|--tag-name-filter)(?:=|\s|$)"
    r"|(?:^|\s)submodule(?:\s+-\S+)*\s+foreach(?:\s|$)"
    r"|(?:^|\s)bisect(?:\s+-\S+)*\s+run(?:\s|$)"
)
# 면제를 받는 이름 전부. 두 집합을 갈라 둔 것은 근거가 다르기 때문 — `_READS_ONLY` 는
# "돌릴 방법이 없다", 이쪽은 "돌리는 철자가 없으면 인자가 데이터다"(그래서 조건부).
_EXEMPT = _READS_ONLY | _EXEMPT_BEYOND_READERS
# 프로그램이 설 자리에 서는 **셸 자신의** 낱말들. 목록이 셸의 것이라 닫혀 있고, 두 읽기가
# 모두 필요로 함: 이 낱말 뒤에서 명령이 시작되며 그 낱말 자신은 그 프로그램이 아님.
_RESERVED_WORDS = frozenset(
    (
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "function",
        "if",
        "in",
        "select",
        "then",
        "time",
        "until",
        "while",
    )
)
# 예약어 중 **뒤에 명령이 오지 않는** 것들. `for f`·`select f`·`case $x`·`… in a)`·
# `function name` 뒤에 서는 것은 프로그램이 아니라 이름·패턴·낱말 목록. 명령 자리로
# 세면 그 낱말이 프로그램 이름으로 잡혀 면제가 깨짐 — `case $x in a) echo 'git commit';;
# esac` 이 패턴 `a` 때문에 미분류 커밋으로 막혔음(실측). 이름을 거르는 쪽에는 그대로 남음.
_NAMES_A_WORD = frozenset(("case", "for", "function", "in", "select"))
# 명령이 시작될 수 있는 자리. 그것을 찾아야 하는 것 전부가 이 조각 **하나**를 씀 — 각자
# 철자했더니 저마다 어딘가에서 셸보다 좁았음. `!` 는 부정 접두이고, 그 뒤가 명령 자리.
# `)` 는 `case` 갈래를 여는 자리이기도 함 — 서브셸 짝으로 이미 들어 있음.
_CMD_START_CHARS = ";&|(){}`\n!"
# 디렉터리 접두를 **정규식으로 적지 않음**. 앵커이면서 동시에 별표의 먹이인 글자는 그
# 연속에서 위치마다 끝까지 갔다가 `[/\\]` 를 찾으며 되감아 2차를 만드는데, 앵커는
# `_CMD_START_CHARS` 뿐이 아니라 **예약어**이기도 함 — 그 글자들(`d`·`o`·`i`·`f` …)을 별표
# 집합에서 뺄 수는 없으므로 별표 자체를 없앰. `echo git commit ` + `do:`×k 에서 러너 wall
# 이 16KB 2.7초·32KB 7.1초·64KB 23초·128KB 95초였음(실측, 배수마다 약 4배).
# 접두는 `_program_name` 이 파이썬에서 벗김 — 그쪽은 매치된 토큰 위에서만 도니 O(토큰).
_COMMAND_START = (
    r"["
    + re.escape(_CMD_START_CHARS)
    + r"]|\b(?:"
    + "|".join(sorted(_RESERVED_WORDS - _NAMES_A_WORD))
    + r")\b"
)
_COMMAND_START_RE = re.compile(_COMMAND_START)
# 명령이 프로그램 **앞에** 지닐 수 있는 것 전부. 어느 것도 이름이 아니므로 걸음이 넘어가되,
# 넘어간 자리에서 이름을 다시 읽음 — 거기서 멈추면 그 명령의 프로그램이 면제 판정에서
# 통째로 빠져 `cat f & > /dev/null 'git' commit -m x` 가 `cat` 하나로 리더가 됐음(실측).
#
# 성능 계약: 별표·플러스 **앞에** 앵커를 두지 않음. 선행 공백은 파이썬이 건너뛰고(별표를
# 앞에 두면 공백 연속에서 자리마다 되감아 2차), 되감기가 남는 두 조각은 길이 상한으로
# 묶음 — fd 번호와 환경변수 이름은 실제로 그 안에 들고, 넘는 것은 대입이 아닌 것으로
# 읽혀 면제를 잃는 **안전한** 쪽으로 감(실측: 상한 없이 `a`×16000 에 0.25초).
_NOT_SEPARATOR = r"[^\s<>" + re.escape(_CMD_START_CHARS) + r"]"
_COMMAND_PREFIX_RE = re.compile(
    r"!|[0-9]{0,9}[<>]{1,2}&?[ \t]*"
    + _NOT_SEPARATOR
    + r"+|(?P<assign>[A-Za-z_][A-Za-z0-9_]{0,127}=)"
    + _NOT_SEPARATOR
    + r"*"
)
# 명령 자리에 선 토큰 하나, 그리고 그 안에서 프로그램 이름이 차지하는 앞부분
# (`/usr/bin/git` 의 `git`). 토큰 쪽은 별표가 없고 뒤에 아무 요구도 없어 되감기지 않음.
_PROGRAM_TOKEN_RE = re.compile(r"[^\s'\"" + re.escape(_CMD_START_CHARS) + r"]+")
_PROGRAM_NAME_RE = re.compile(r"[A-Za-z0-9_.+-]+")
# 예약어가 예약어이려면 그 **앞**에 무엇이 서야 하는가. 명령이 시작될 수 있는 자리에서만
# 예약어 — 인자 자리에서 하나로 읽으면 그 뒤의 인용 텍스트가 이름 못 읽는 프로그램이 되어
# `echo bash and then "git commit"` 이 아무것도 안 돌면서 차단됐음(실측).
_RESERVED_TAIL_RE = re.compile(r"\b(?:" + "|".join(sorted(_RESERVED_WORDS)) + r")$")
_LONGEST_RESERVED = max(len(w) for w in _RESERVED_WORDS)
# 확장되는 치환. **자리를 묻지 않음** — 명령 자리로 읽으려면 명령이 지닐 수 있는 접두를
# 전부 알아야 하고 하나만 빠져도 면제가 되돌아옴. 치환을 하나라도 확장하는 원소가 돌리는
# 프로그램은 거기 **적힌** 것들만이 아님.
_SUBSTITUTION_RE = re.compile(r"\$\(|`")
# 명령 리스트의 원소가 끝나는 자리. 그물은 원소 **하나**를 읽음 — 다른 원소의 인터프리터가
# 이 원소의 인용 텍스트를 스크립트로 만들지 않고, 문자열 전체를 읽으면 python 이나 bash 옆에서
# 도는 읽기 전용 명령이 전부 차단됨(실측). 파이프는 경계가 **아님**: 텍스트를 파이프로
# 인터프리터에 넘기면 스크립트가 그 인터프리터 **앞** 원소에 있음.
_LIST_SEPARATOR_RE = re.compile(r"&&|\|\||[;\n]")


def _program_name(token: str) -> str:
    """명령 자리 토큰에서 프로그램 이름. 못 뽑으면 빈 문자열."""
    tail = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    m = _PROGRAM_NAME_RE.match(tail)
    return m.group() if m else ""


def _program_spans(element: str) -> list[tuple[str | None, int, int]]:
    """`element` 의 **모든** 명령 자리에 선 프로그램과 그 **인자 범위**. 못 읽은 자리는 `None`.

    걸음은 **하나**. 둘이면 서로 다른 답을 냄 — 접두(`!`·리다이렉션·대입)를 넘어간 쪽은
    그 뒤의 프로그램을 봤고 이름을 모으던 쪽은 못 봐서, `cat f | > /dev/null env 'git'
    commit -m x` 가 `cat` 하나로 면제를 받았음(실측).

    예약어는 프로그램이 아니라 **그 뒤** 명령이 시작되는 자리. 그리고 명령이 시작될 수 있는
    자리에서만 예약어 — 인자 자리의 `then` 을 하나로 읽으면 그 뒤 인용 텍스트가 이름 못
    읽는 프로그램이 되어 아무것도 안 도는 명령이 차단됨(실측). `_NAMES_A_WORD` 뒤에 서는
    것은 이름·패턴·낱말 목록이라 명령 자리가 아니므로, 거기서는 걸음을 멈춤.

    `None` 은 아무 이름도 읽히지 않는 자리(마스크가 인용된 프로그램 자리에 남긴 것)와, 이름은
    있으나 **그 이름이 면제를 벌 수 없는** 자리 — 대입·리다이렉션이 앞에 선 자리가 그것이고,
    근거는 아래 `not name or opaque` 주석에 있음. 어느 쪽이든 **빼지 않고 그렇다고 알림**:
    빼면 그 프로그램을 모르는 채로 면제가 결정되고, 그것이 이 게이트가 틀리면 안 되는 방향.

    끝나지 않을 여지가 없음: 시작 자리는 고정 패턴 한 번의 스캔에서 오고, 접두를 걷는 안쪽
    루프는 앞으로만 감.

    인자 범위는 `(args_start, args_end)` — 시작은 프로그램 토큰 **바로 뒤**(이름을 못 댄
    자리는 명령 자리 자신), 끝은 그 뒤 첫 `_SEPARATOR_RE` 이거나 원소 끝. 뒤의 판정들이
    자리를 **이 걸음에서** 읽음 — 자리를 읽는 두 번째 판독기를 만들지 않는 것이 규칙이고,
    둘이면 서로 다른 답을 냄.
    """
    found: list[tuple[str | None, int, int]] = []
    # 구분자 자리는 **한 번만** 훑음. 명령 자리마다 `search` 를 새로 걸면 구분자 없는 긴
    # 연속에서 자리마다 끝까지 가 2차가 됨(`!x`×16000 에서 6.9초, 실측). 자리도 매치도
    # 단조 증가라 이분 탐색으로 답이 같음.
    seps = [m.start() for m in _SEPARATOR_RE.finditer(element)]

    def _args_end(at: int) -> int:
        j = bisect_left(seps, at)
        return seps[j] if j < len(seps) else len(element)

    # 이미 어느 걸음이 풀어낸 데까지. 그 안에 떨어지는 시작은 새 명령이 아니라 이미 읽은
    # 명령의 토큰 — 다시 걷지 않는 것이 `!`×k 같은 접두 연속에서 2차를 막음.
    seen = -1
    for start in _command_starts(element):
        if start <= seen:
            continue
        i, opaque = start, False
        while True:
            while True:
                while i < len(element) and element[i] in " \t":
                    i += 1
                n = _COMMAND_PREFIX_RE.match(element, i)
                if n is None or n.end() <= i:
                    break
                # `!` 만이 정밀한 읽기도 넘어가는 접두. 리다이렉션과 대입은 그쪽이
                # 이 자리를 명령 자리로 안 보므로, 여기서 이름을 대면 그 이름이 벌어 준
                # 면제가 아무도 안 읽는 호출을 덮음.
                opaque = opaque or n.group() != "!"
                i = n.end()
            if i >= len(element) or element[i] in _CMD_START_CHARS or element[i] == "\x00":
                # NUL 은 heredoc 본문의 텍스트임 — 본문을 여는 개행을 타고 여기 떨어짐.
                # `_list_elements` 가 그 span 을 한 원소로 이미 묶어 두므로 이 자리에서
                # 시작하는 명령은 없음. 인용된 프로그램 자리는 마스크에 **따옴표 자체**를
                # 남기므로(NUL 은 그 사이뿐) 여기 안 떨어지고, 아래 `not name` 갈래로 가
                # `None` 을 받음 — 이 걸음이 그 자리에 아직 지고 있는 빚.
                seen = i
                break  # 시작은 있었지만 명령이 열리지 않음
            token = _PROGRAM_TOKEN_RE.match(element, i)
            raw = token.group() if token else ""
            if raw in _RESERVED_WORDS:
                if raw in _NAMES_A_WORD:
                    seen = i
                    break  # 뒤에 서는 것은 프로그램이 아니라 이름·패턴
                # 예약어는 프로그램이 아니라 그것이 여는 명령이 프로그램이고, 그 명령의
                # 접두는 예약어 **뒤**에 옴. 이름으로 내놓으면 그 프로그램을 못 봄.
                i += len(raw)
                continue
            name = _program_name(raw)
            if not name or opaque:
                # 대입은 프로그램도 그 인자도 아님. 이름이 벌어 준 면제 **안**으로
                # 들어가므로(`LESSOPEN`·`LD_PRELOAD`), 그 자리는 이름 없는 것으로 읽음.
                # 리다이렉션도 같음 — 조건부 `git` 면제는 "정밀한 읽기가 진짜 커밋을 이미
                # 잡는다"에 기대는데, `at_command_start` 는 피연산자가 떨어진 리다이렉션
                # (`> /dev/null git commit -m x`·`2>&1 git commit -m x`)을 명령 자리로
                # 안 봄. 이름을 대면 그 커밋을 두 읽기 모두 놓침(실측: 실제 bash 가
                # 커밋을 돌림). 범위는 **명령 자리에서** 시작 — 이름이 없으니 넘어갈
                # 토큰도 없음.
                found.append((None, i, _args_end(i)))
            else:
                args_start = i + len(raw)
                text = name[:-4] if name.lower().endswith(".exe") else name
                found.append((text, args_start, _args_end(args_start)))
            seen = i
            break
    return found


def _programs(element: str) -> list[str | None]:
    """명령 자리마다의 프로그램 **이름**만 — `_program_spans` 의 얇은 포장."""
    return [name for name, _s, _e in _program_spans(element)]


def _command_starts(element: str):
    """`element` 에서 명령이 시작될 수 있는 자리들 — 왼쪽부터, 처음은 언제나 0."""
    yield 0
    for m in _COMMAND_START_RE.finditer(element):
        word = m.group()
        if word == "&" and m.start() and element[m.start() - 1] in "<>":
            continue  # `2>&1` 의 `&` 이지 명령을 여는 것이 아님
        if word not in _CMD_START_CHARS:
            j = m.start()
            while j and element[j - 1] in " \t":
                j -= 1
            if (
                j
                and element[j - 1] not in _CMD_START_CHARS
                and not _RESERVED_TAIL_RE.search(element, max(0, j - _LONGEST_RESERVED), j)
            ):
                continue  # 명령 자리가 아니면 예약어가 아니라 낱말
        yield m.end()


def _reads_only(element: str) -> bool:
    """`element` 가 돌리는 프로그램이 전부 읽기만 하는가 — 판정은 **마스크 위에서**.

    파이프라인의 **단계마다** 따로 물음. 파이프는 원소 경계가 아니므로(스크립트가
    인터프리터 앞 단계에 있을 수 있음) 한 원소에 여러 명령이 들어오는데, 이름을 원소 전체에서
    한 번에 모으면 이름을 못 뽑은 단계가 뒤 단계의 리더 이름 뒤에 숨음 —
    `bash -c 'git commit -m x' | cat` 이 그렇게 면제를 받아 게이트가 꺼졌음(실측).

    프로그램이 아예 없는 단계는 면제가 **아님**: 맨 대입은 뒤에서 실행될 스크립트를 담고,
    면제는 이름으로 얻는 것이지 이름의 부재로 얻는 것이 아님. 치환을 확장하는 단계도
    아님 — `$(echo "git commit -m x")` 가 돌리는 것은 그 안에 적힌 리더의 **출력**이고,
    거기 적힌 이름은 도는 프로그램이 아님.
    """
    for stage in element.split("|"):  # `||` 는 이미 원소를 갈랐으므로 여기 오지 않음
        if _SUBSTITUTION_RE.search(stage):
            return False
        names = _programs(stage)
        if not names or not all(n is not None and n in _EXEMPT for n in names):
            return False
        # `git` 의 면제는 그것이 인자를 데이터로만 쓸 때. `--exec`·`-x`·`-c` 가 있으면
        # 인자가 명령이므로 면제가 사라짐.
        if any(n in _EXEMPT_BEYOND_READERS for n in names) and _GIT_RUNS_A_COMMAND_RE.search(stage):
            return False
    return True


# 토큰 경계가 되는 글자들 — 공백류·따옴표·명령 구분자·백틱, 그리고 `\n`·`\t`·`\r` **이스케이프**.
# 마지막 것은 자기 이스케이프를 xargs·parallel 이 나눌 구분자로 바꾸는 판독기 때문임:
# `printf 'merge\n--no-ff\ndev' | xargs git` 에는 `merge` 와 `--no-ff` 사이에 셸 수준의 공백이
# 한 번도 없고, 그 자리를 만드는 것은 출력 시점의 printf `\n` 임. **맨몸 백슬래시는 일부러
# 뺌** — Windows 경로(`C:\git\commit\run.sh`)가 구간마다 그것을 달고 있어, 경계로 읽으면
# Invariant 7 이 금지하는 오차단이 됨. 백슬래시 뒤의 글자까지 요구하는 것이 경로 구간을
# 영원히 자격 밖에 둠.
_BOUNDARY_CHARS = r"\s;&|()'\"" + chr(96)  # 백틱 — 소스에 날글자로 두면 인용 스캐너가 걸림
_TOKEN_BOUNDARY = rf"[{_BOUNDARY_CHARS}]|\\[ntr]"
# 호스트가 프로그램을 적는 그대로의 `git` 낱말 하나(디렉터리 접두·`.exe` 포함).
# 디렉터리 접두를 **별표로 적지 않음**(성능 계약). 앵커 갈래 하나가 두 글자
# (`\n`·`\t`·`\r`)라 그 첫 글자인 백슬래시가 앵커이면서 동시에 별표의 먹이가 되고, 먹이를
# 앵커 **문자 집합**의 여집합으로 파생해도 그 두 글자짜리 갈래는 거기서 안 빠짐 —
# `\n`×32000 에서 16.5초(실측). 대신 접두를 **폭 없는 lookbehind** 로 받음: `/usr/bin/git` 의
# `git` 앞은 `/`. 같은 입력에서 0.0023초.
_GIT_TOKEN_RE = re.compile(
    rf"(?:^|{_TOKEN_BOUNDARY}|(?<=[/\\]))git(?:\.exe)?(?=$|{_TOKEN_BOUNDARY})"
)
# 하위 명령을 **표준 입력에서** 받아 인자 순서를 뒤집는 프로그램들.
_XARGS = frozenset(("xargs", "parallel"))


def _standalone_word(view: str, word: str) -> bool:
    r"""`view` 위에서 `word` 가 낱말 하나로 서는가 — 경계는 공백류·따옴표·명령 구분자·백틱·
    `\n`·`\t`·`\r` 이스케이프·문자열 끝. `commit.gpgsign`·`*commit*`·Windows 경로 구간
    (`\commit\`)은 해당하지 않음."""
    pattern = rf"(?:^|{_TOKEN_BOUNDARY}){re.escape(word)}(?=$|{_TOKEN_BOUNDARY})"
    return re.search(pattern, view) is not None


def _runs_by_flag(raw_element: str, masked_element: str) -> bool:
    """`raw_element` 의 판독기가 **프로그램을 지목하는 실행 플래그**를 받았는가.

    파이프 단계마다 자기 인자 범위 위에서 물음 — `printf x | rg -v y` 의 `-v` 는 `rg` 것임.
    프로그램 자리는 **마스크**에서 읽고(자리의 권위는 `_program_spans` 하나), 인자 텍스트는
    **원본**에서 shlex 로 쪼갬 — 인용된 값의 공백과 `$`·백틱 확장을 봐야 하기 때문.
    shlex 가 `ValueError` 를 내거나 인자 범위에 `$`·백틱이 있으면 면제를 잃음: 확장이
    플래그가 될 수 있음. 틀리는 방향을 오차단 쪽으로 둠(Invariant 7).
    """
    import shlex  # 이 파일의 관용구 — 모듈 최상위에 안 둠(훅 임포트 비용은 매 Bash 호출)

    for name, s, e in _program_spans(masked_element):
        pred = _EXEC_FLAG_READERS.get(name) if name is not None else None
        if pred is None:
            continue
        arg_raw = raw_element[s:e]
        if DOLLAR_CH in arg_raw or BT_CH in arg_raw:
            return True
        try:
            toks = shlex.split(arg_raw)
        except ValueError:
            return True
        for idx, t in enumerate(toks):
            if not pred(t):
                continue
            if name not in _EXEC_FLAG_VALUE_PROGRAMS:
                return True  # `printf -v`: 플래그 자체가 대입이라 첨자가 평가됨
            # `rg`·`sort`: 값은 `--flag=VAL` 이거나 다음 토큰. 존재하고 공백이 없을 때만
            # 이름이 될 수 있음 — 공백 든 값은 존재할 수 없는 프로그램 이름임.
            val = t.split("=", 1)[1] if "=" in t else (toks[idx + 1] if idx + 1 < len(toks) else "")
            if val and not any(c.isspace() for c in val):
                return True
    return False


# 인용, 그리고 따옴표를 이스케이프하는 백슬래시. 그 밖의 것을 이스케이프하는 백슬래시는
# 그대로 둠 — 이 게이트가 도는 호스트에서 그것은 경로 구분자이고, 지워 버리면
# `bash C:\git\commit\run.sh` 가 호출이 됨.
_QUOTING_RE = re.compile(r"\\?[\"'`]")

# heredoc 여는 자리. 본문은 어떻게 인용하든 리터럴 텍스트. `<<<`(here-string)는 낱말 문법상
# 이미 제외되고, lookaround 가 더 긴 `<` 연속의 중간에서 시작하는 것까지 막음.
# 구분자는 셸이 읽는 그대로 **낱말 하나** — 인용된 조각과 맨몸 조각을 이어 붙인 것이고,
# 공백이나 메타문자에서 끝남. 맨몸 토큰 하나로 읽으면 `<<\EOF`(백슬래시가 따옴표와 같은
# 일을 함)도 `<<'EO'F`(조각을 이음)도 그 철자를 못 알아보고, 그러면 종결자를 영영 못 만나
# 본문이 문자열 끝까지 감 — 그 "본문"은 게이트가 읽으려던 진짜 호출(실측).
# `\r` 은 낱말에서 뺌: 이 층은 종결자 줄의 CR 을 `_heredoc_body` 에서 벗기므로, 구분자
# 쪽에도 실으면 둘이 서로 어긋남(Invariant #2 — CRLF 는 한 곳에서만 처리).
# 그룹 1 의 `-` 만이 종결자의 선행 탭을 벗김. 그룹 2 는 따옴표를 벗기기 **전**의 낱말.
_HEREDOC_RE = re.compile(
    r"""(?<!<)<<(-?)(?!<)[ \t]*((?:'[^']*'|"[^"]*"|\\.|[^ \t\r\n;&|<>()'"\\])+)"""
)
# 스캐너가 철자하지 않고 **이름으로** 부르는 글자들. 앞의 셋은 heredoc 구분자가 지녀야
# 본문이 코드가 아니라 리터럴 텍스트가 되는 것들.
SQ_CH, DQ_CH, BS_CH, BT_CH, DOLLAR_CH = chr(39), chr(34), chr(92), chr(96), chr(36)
# 백슬래시가 **인용하는** 것: 공백류, 두 따옴표, 자기 자신, 개행(글자를 인용하는 게 아니라 두
# 줄을 이음), 그리고 셸이 구분자로 읽는 글자들. 그 밖의 글자 앞에 선 백슬래시는 평범한 두
# 글자 — 그래야 `C:\Git\bin\git` 이 `git` 낱말을 잃지 않음. 구분자를 빼면 이스케이프한
# `;` 가 명령을 끝내는 것으로 읽혀, 그 위에 걸린 인용 인자가 다시 코드로 노출됨.
# 백틱도 인용함 — 이스케이프한 백틱은 치환을 열지 않음. 여는 것으로 읽으면 뒤의 진짜 백틱과
# 짝을 지어 그것이 감싼 듯한 명령을 거기서 끝내고, 그 뒤 git 이 읽는 플래그를 떨어뜨림.
_QUOTED_BY_BACKSLASH = frozenset(" \t\"'\\\r\n;&|()<>" + BT_CH)
# 다음에 오는 인용 인자를 **실행하는** 것. 두 모양: 명령을 받는 낱말(`eval`·`trap`)과
# 인터프리터의 스크립트 플래그 — 후자는 반드시 인터프리터가 앞에 서야 함. 아니면 같은
# `-c` 가 git 자신의 전역 옵션과 모든 도구의 개수 플래그까지 가로챔. `-C` 는 둘 다 아님:
# git 의 디렉터리 옵션은 명령이 아니라 경로를 받음.
# 디렉터리 접두의 문자 집합은 앞 앵커 `[\s;&|(`]` 의 글자를 하나도 담지 않음 — 앵커이면서
# 동시에 별표의 먹이인 글자는 그 연속에서 2차를 만듦. 백틱이 그랬음(16K 에서 1.9초, 실측).
# `_EXECUTES_NEXT_WINDOW` 가 스캔을 128자로 묶어 실제 지연은 없었지만, 창이 넓어지는 순간
# 살아나는 잠복 결함이라 규칙 쪽을 고침. 시간 가드가 이 패턴도 함께 측정.
_EXECUTES_NEXT_RE = re.compile(
    r"(?:^|[\s;&|(`])(?:"
    r"(?:eval|trap|source|exec|foreach)"
    r"|(?:[^\s;&|()'\"`]*[/\\])?"
    r"(?:" + "|".join(_RUNS_TEXT) + r")(?:\.exe)?(?:\s+-[^\s-]\S*)*\s+-[a-z]*c(?:\s+--)?"
    r"|--run|-Command|/[cCkK]"
    r")[ \t]+$"
)
# 위 두 앵커가 되짚을 수 있는 최대 거리: 어느 쪽이 이름 붙인 가장 긴 낱말과 그 뒤 공백.
# 스캔을 묶어 따옴표 하나당 O(1) 로 만듦 — 0 부터 훑으면 따옴표마다 명령을 다시 읽어,
# 따옴표가 빽빽한 인자에서 훅 지연이 초 단위가 되고 타임아웃 뒤에는 판정이 아예 없음.
_EXECUTES_NEXT_WINDOW = 128
# 인용 span 이 **프로그램 이름**으로 서는 자리. `'git' commit` 은 커밋을 돌리고, 따옴표를
# 리터럴로 읽으면 그 커밋이 통째로 사라짐. 이스케이프된 구분자는 구분자가 아님.
# 여기는 `_COMMAND_START` 를 **쓰지 않음**. 이 판정은 마스크를 바꾸고 마스크는 정밀한
# 읽기가 보는 판이라, 넓히면 오차단이 그쪽으로 샘: 예약어 갈래를 더했더니 인자로 선
# `then` 뒤의 문자열이 프로그램 이름으로 읽혀 `echo bash and then "git commit -m x"` 가
# 발화했음(실측). 예약어 뒤 명령 자리는 면제 쪽에서 이미 덮임 — 이름을 하나도 못 뽑은
# 단계는 면제를 못 받으므로 `then 'git' commit | cat` 은 그물이 그대로 읽음.
_AT_COMMAND_START_RE = re.compile(r"(?:^|(?<!\\)[;&|({}\n])[ \t]*$")
# 마스크가 NUL 이 아니라 **공백**으로 덮는 종류들: 토큰을 가르는 자리이지, 토큰 안에 앉은
# 리터럴 텍스트가 아님.
_BLANKED = frozenset({"continuation", "delimiter"})
# 한 단순 명령이 끝나고 다음이 시작되는 자리. **개행은 `&&` 와 똑같이 두 명령을 가르고**,
# merge-strategy 가 squash 머지에 문서화한 블록이 개행으로 나뉜 3줄이므로 빠뜨리면 정책이
# 문서화한 모양이 한 명령으로 읽힘. `\r` 은 CRLF 를 덮음.
# 리다이렉션 안의 `&` 는 명령을 끝내지 않음 — `git merge 2>&1 --no-ff fix/x` 에서 거기서
# 끊으면 피연산자가 `2` 하나로 줄어 전략 판정이 사라짐(실측).
_SEPARATOR_RE = re.compile(r"[;|)\n\r]|(?<![<>])&")

# `-C` 를 **옵션으로서** 찾음. 값 안에 든 `-C` 는 옵션이 아니므로 자리는 마스크에서 찾고,
# 경로는 그 오프셋의 **원본**에서 읽음 — 따옴표가 살아 있어야 공백 든 경로가 한 토큰.
_DASH_C_RE = re.compile(r"(?:^|\s)-C\s+")
_PATH_TOKEN_RE = re.compile(_PATH_TOKEN)
# 조각별 내용만 이어 붙여 따옴표를 벗김 — 단어 전체에서 따옴표 문자를 지우는 것과 다름.
# 첫 조각이 **이스케이프한 공백**. `_shell_regions` 가 그 공백을 마스킹해 토큰을 잇는데,
# 값을 읽을 때 되살리지 않으면 `git -C /tmp/My\\ P/wt commit` 의 답이 `/tmp/My\\` 로 잘려
# 나옴 — 실재하는 **형제 worktree** 를 지목할 수 있고(Windows 는 끝의 `\\` 를 정규화)
# `_same_repo_toplevel` 도 통과함. 그러면 게이트는 커밋이 돌지 않는 트리의 status·티어
# 마커를 읽음(양방향 오작동). 다른 `\\` 는 그대로 둠 — Windows 경로의 구분자.
_PATH_PIECE = re.compile(r'\\(\s)|"([^"]*)"|\'([^\']*)\'|((?:[^\s"\'\\]|\\(?!\s))+)')


def _heredoc_body(command: str, start: int, word: str, dash: bool) -> int:
    """`start`(본문 첫 줄) 에서 열린 heredoc 본문의 끝 인덱스.

    종결자가 없으면 셸이 그러듯 문자열 끝까지 본문 — "본문 없음"으로 돌리면 메시지가
    구문으로 파서에 넘어감. `<<-` 는 종결자의 선행 **탭만** 벗기므로 맨 `<<` 는 줄이 정확히
    일치해야 함. 느슨하게 보면 들여쓴 유사 줄에서 구간이 일찍 끝나고 나머지 본문이 명령으로
    읽힘.

    CRLF 는 따로 벗김(Invariant #2): Windows 호스트가 보내는 명령의 종결 줄은 `EOF\\r` 이고,
    그대로 비교하면 종결자를 못 찾아 본문이 문자열 끝까지 가 **진짜 호출까지** 덮임 —
    워크트리 재지정이 조용히 사라짐.
    """
    at = start
    while at < len(command):
        eol = command.find("\n", at)
        line = command[at : len(command) if eol == -1 else eol].rstrip("\r")
        if (line.lstrip("\t") if dash else line) == word:
            return at
        if eol == -1:
            break
        at = eol + 1
    return len(command)


def _delimiter_word(raw: str) -> str:
    """heredoc 구분자에서 인용을 벗긴 것 — 종결자 줄이 같아야 하는 그 낱말.

    벗기기만 함: 조각들은 이미 한 낱말이고, 어떤 인용 형태든 본문의 확장을 똑같이 끄므로
    어느 쪽을 썼는지는 여기서 살아남지 않음.
    """
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == "\\" and i + 1 < n:
            out.append(raw[i + 1])
            i += 2
        elif c in "\"'":
            j = raw.find(c, i + 1)
            j = n if j == -1 else j
            out.append(raw[i + 1 : j])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _matching(command: str, at: int, opener: str, closer: str, depth: int = 1) -> int:
    """`at` 에서 시작해 열린 `opener` `depth` 개를 닫는 `closer` 바로 뒤 인덱스.

    닫는 쪽을 **먼저** 봄. 백틱은 자기 자신이 닫는 문자라, 여는 것으로 세면 짝이 영영
    맞지 않고 스캔이 명령의 나머지를 통째로 삼킴 — 그 뒤의 호출 전부와 함께.
    """
    n = len(command)
    while at < n and depth:
        c = command[at]
        if c == "\\":
            at += 2
            continue
        if c == closer:
            depth -= 1
        elif c == opener:
            depth += 1
        at += 1
    return at


def _nested(command: str, a: int, b: int) -> list[tuple[int, int, str]]:
    """부분 명령 `command[a:b]` 의 구간들을, 문자열 **전체**의 좌표로.

    실행되는 span 은 그것이 실제로 무엇인지 — 명령 — 로 스캔. 그래야 그 안의 인용도
    어디서나 같은 규칙으로 읽히고, 안의 `git … commit` 은 호출이면서 안의
    `grep 'git commit'` 은 여전히 호출이 아님.
    """
    return [(a + x, a + y, kind) for x, y, kind in _shell_regions(command[a:b])]


def _expanding(
    command: str, a: int, b: int, kind: str, stop: str | None = None
) -> tuple[int, list[tuple[int, int, str]]]:
    """`command[a:b]` 의 구간들 — 셸이 확장하는 자리만 빼고 리터럴인 텍스트.

    겹따옴표 span 과 확장이 켜진 heredoc 본문은 같은 모양: 치환 사이의 구간은 텍스트이고
    각 치환은 그것이 실제로 무엇인지인 명령. span 을 통째로 덮으면 셸이 진짜로 돌리는
    커밋을 잃고(`"$(git commit)"` 은 커밋함), 통째로 스캔하면 메시지를 구문으로 파서에
    넘김. `stop` 은 구간을 `b` 가 아니라 그 글자의 첫 이스케이프되지 않은 출현에서 끝냄 —
    인용 span 이 다르게 하는 유일한 것: 셸이 닫는 자리에서 닫히고, 지나온 치환 안의
    따옴표에서는 닫히지 않음. 구간이 끝난 자리와 그 안의 구간들을 돌려줌.
    """
    regions: list[tuple[int, int, str]] = []
    j = lit = a
    while j < b and command[j] != stop:
        if command[j] == BS_CH:
            j += 2
            continue
        if command[j] == BT_CH or (command[j] == DOLLAR_CH and command[j + 1 : j + 2] == "("):
            if j > lit:
                regions.append((lit, j, kind))
            opened = j + 1 if command[j] == BT_CH else j + 2
            end = (
                _matching(command, opened, BT_CH, BT_CH)
                if command[j] == BT_CH
                else _matching(command, opened, "(", ")")
            )
            regions.extend(_nested(command, opened, min(end, b) - 1))
            j = lit = min(end, b)
            continue
        j += 1
    end = min(j, b)
    if end > lit:
        regions.append((lit, end, kind))
    return end, regions


def _double_quoted(command: str, i: int) -> tuple[int, list[tuple[int, int, str]]]:
    """`i` 에서 열리는 `"…"` span 을 스캔 — 끝나는 자리와 그 안의 구간들."""
    n = len(command)
    end, regions = _expanding(command, i + 1, n, "quote", DQ_CH)
    return min(end + 1, n), regions


def _code_span(command: str, a: int, b: int) -> list[tuple[int, int, str]]:
    """내용이 코드인 인용 span 의 구간들. `command[a:b]` 가 그 내부.

    구분자는 따옴표 문자로 남지 않고 **공백**이 됨. 그래야 토큰 문법이 셸에 있는 낱말
    경계를 그 자리에서 보고 인용에 대해 아무 의견도 가질 필요가 없음. 내부는 그것이 실제로
    무엇인지인 명령으로 스캔.
    """
    return [(a - 1, a, "delimiter"), (b, b + 1, "delimiter"), *_nested(command, a, b)]


def _executed_span(command: str, quote_at: int) -> bool:
    """`quote_at` 에서 열리는 인용 span 이 무언가 **실행하는** 인자인가.

    `bash -c '…'` 와 `eval "…"` 는 인자를 셸에 넘기므로, 안의 텍스트는 어떻게 인용됐든
    명령. 집합은 작고 추론이 아니라 **이름으로** 적혀 있음 — 문자열이 코드가 되는 모든
    길을 따라가는 게이트는 그냥 셸이고, 작정한 우회는 어차피 철자가 무한함(터미널 커밋은
    이미 모든 층을 건너뜀). 하지만 이것이 대체한 부분 문자열 매치보다 **좁아서는** 안 됨.
    """
    # 두 패턴 모두 `$` 에서 끝나므로 span 바로 앞 글자들만 매치할 수 있음. 0 부터 훑으면
    # 따옴표마다 명령을 다시 읽어, 따옴표가 빽빽한 인자에서 훅 지연이 초 단위가 되고
    # 타임아웃을 넘기면 판정이 아예 없음.
    start = max(0, quote_at - _EXECUTES_NEXT_WINDOW)
    return bool(
        _EXECUTES_NEXT_RE.search(command, start, quote_at)
        or _AT_COMMAND_START_RE.search(command, start, quote_at)
    )


def _arith_end(command: str, at: int) -> int:
    """`at` 에서 본문이 시작되는 산술 구문을 닫는 자리 바로 뒤 인덱스.

    산술은 덮지 않고 **건너뜀** — 리터럴 텍스트도 아니고 명령이 살 수 있는 자리도 아님.
    다만 그 안의 `<<` 는 왼쪽 시프트이고, heredoc 도입부로 읽으면 그 뒤 전부가 본문으로
    덮임 — 그 "본문"이 게이트가 읽으려던 명령 줄의 나머지(실측).

    세 철자가 이 자리를 만듦. bash 로 재 보면 `$((1 << 2))`·`(( 1 << 2 ))`·`$[1 << 2]`
    뒤의 `git commit` 은 전부 **실행됨** — 셋 다 산술. 반면 `let x=1<<2` 는 bash 자신이
    heredoc 으로 읽으므로("here-document ... wanted `2'") 여기서 건너뛰지 않는 것이 맞음.
    남는 잔여는 `${a[1 << 1]}` 같은 **배열 첨자**: 파라미터 확장 안까지 따라 들어가면
    `${x:-$(git commit)}` 의 진짜 호출을 잃으므로, 방향이 같은 FAIL-OPEN 인 쪽을 택했음.
    """
    return _matching(command, at, "(", ")", depth=2)


def _heredoc_bodies(
    command: str, at: int, pending: list[tuple[bool, str, bool, int]]
) -> tuple[int, list[tuple[int, int, str]]]:
    """한 줄이 연 heredoc 들의 본문을, 셸이 읽는 순서대로 소비.

    본문마다 자기 종결자까지 가고 다음은 그 **뒤**에서 시작. 그 줄의 두 번째 `<<` 는
    적어 둘 한계가 아니라 **덮이지 않은 본문**이고, 덮이지 않은 텍스트는 구문으로 파서에
    넘어감 — git 을 하나도 돌리지 않는 명령이 본문에 적힌 `-C` 로 ROOT 를 옮김(실측).
    """
    regions = []
    n = len(command)
    for dash, word, literal, intro in pending:
        end = _heredoc_body(command, at, word, dash)
        # 구분자를 인용하거나 백슬래시로 막아야만 확장이 꺼짐. 켜져 있으면 본문 안의 치환은
        # 셸이 돌리는 명령이고, 본문을 통째로 덮으면 그것을 잃음.
        #
        # 폭 0 짜리 표식 둘이 먼저 나감. 확장이 켜진 본문이 **치환으로 시작하면**
        # `_expanding` 은 그 앞에 리터럴 구간을 만들지 않으므로 본문이 어디서 시작하는지
        # 기록이 남지 않고, 그러면 `_list_elements` 가 본문을 여는 개행을 원소 경계로 읽어
        # 인터프리터와 그것이 건네받은 스크립트를 서로 다른 원소로 찢음 — `bash <<EOF` /
        # `$(pwd)/setup.sh` / `git commit -m x` / `EOF` 에서 게이트가 꺼졌음(실측).
        # 도입부 자리도 같은 이유로 기록: 도입부와 본문 **사이**에 선 구분자를 경계로
        # 읽으면 본문이 다음 원소로 넘어가고, 거기 리더가 하나 있으면 그 원소가 면제를 받아
        # 게이트가 또 꺼짐 — `bash <<EOF && echo ok` / `git commit -m x` / `EOF`
        # (실측: 러너 exit 2 → 0). 폭이 0 이라 마스크·뷰·낱말 경계 어디에도 영향이 없음.
        regions.append((intro, intro, "heredoc-open"))
        regions.append((at, at, "heredoc"))
        regions.extend(
            [(at, end, "heredoc")]
            if literal
            else _expanding(command, at, min(end, n), "heredoc")[1]
        )
        eol = command.find("\n", end)
        at = n if eol == -1 else eol + 1
    return at, regions


@lru_cache(maxsize=8)
def _shell_regions(command: str) -> tuple[tuple[int, int, str], ...]:
    r"""마스크가 다시 쓰는 `command` 의 인덱스 범위들과, 각각이 **무엇인지**.

    한 명령을 읽는 주체가 여럿이라(호출 문법 · `-C` 값 · merge 피연산자 · switch 피연산자)
    같은 스캔이 되풀이되므로 메모이즈. 인자 하나에 대해 순수하니 캐시는 일만 덜어 줌.

    따옴표 문자마다 짝을 세는 게 아니라 **상태 머신 하나**: `'…'` 안의 `"` 는 리터럴 한
    글자이고, `python3 -c '… "x" …'` 는 이 repo 스킬이 실제로 내는 모양이라 따로 세면 그 뒤
    명령 전부가 따옴표 안으로 읽혀 진짜 커밋 호출이 보이지 않음. `'…'` **밖**에서는 `\` 가
    다음 글자를 인용하므로, `'\''` 관용구(홑따옴표 문자열에 아포스트로피를 넣는 유일한
    방법이자 그런 커밋 제목이 만들어 내는 모양)가 짝 계산을 한 칸 밀지 않음.

    종류는 마스크가 무엇으로 덮는지, 그리고 명령의 낱말이 거기서 끝나는지(:func:`operand_end`)
    로 갈림:
      - `quote`/`heredoc`/`escape` — 리터럴 텍스트, NUL 로 덮음. heredoc 본문은 따옴표
        구간이 아니면서 셸에게 리터럴이고, 이 repo 의 커밋 메시지가 사는 곳: 본문의
        `git -C <wt> commit` 은 커밋을 **말하는** 메시지이지 커밋하는 명령이 아니며, 그
        디렉터리를 읽으면 ROOT 가 커밋이 돌지 않는 트리를 가리킴(Invariant 7). `escape` 는
        백슬래시가 인용한 **그 글자만** 덮으므로, 이스케이프한 공백이 든 토큰은 마스크에서
        공백 없는 한 덩어리로 남고 원본에는 백슬래시가 그대로 보임.
      - `comment` — 리터럴이면서 **명령을 끝냄**. 그래서 따로 표시.
      - `continuation` — `\`+개행은 두 줄을 이음. NUL 이 아니라 **공백**으로 덮음: 아무것도
        가르지 않는 자리에 토큰 경계가 생기면 이어진 호출이 두 낱말로 갈리고, 그러면 커밋이
        "커밋 아님"으로 읽혀 러너가 게이트를 돌리기도 전에 exit 0 함(실측).
    """
    regions: list[tuple[int, int, str]] = []
    # 이 줄이 연 heredoc 들(bash 가 읽는 순서): (탭벗김, 구분자, 리터럴, 도입부 오프셋)
    pending: list[tuple[bool, str, bool, int]] = []
    body_at: int | None = None  # 그중 첫 본문이 시작되는 자리
    i, n = 0, len(command)
    while i < n:
        if body_at is not None and i >= body_at:
            i, bodies = _heredoc_bodies(command, body_at, pending)
            regions.extend(bodies)
            pending, body_at = [], None
            continue
        ch = command[i]
        if ch == "\\" and command[i + 1 : i + 2] in _QUOTED_BY_BACKSLASH:
            # 백슬래시는 인용이 필요한 것만 인용함. **아무** 다음 글자나 인용으로 보면 이
            # 게이트가 도는 호스트의 실제 경로가 망가짐: `C:\Git\bin\git` 에서 문법이
            # 봐야 하는 `git` 이 사라짐.
            # 줄이음은 **CRLF 도** 줄이음(Invariant #2 — 훅이 받는 명령은 Windows 에서
            # 옴). `\r` 을 빼 뒀을 때 `git \<CR><LF> commit -m x` 가 게이트를 꺼트렸음 —
            # `\`+CR 이 이스케이프로 안 읽히고 `_SEPARATOR_RE` 의 `\r` 이 피연산자 영역을
            # 즉시 끊었음(실측: 러너 exit 0, 실제 bash 는 argv 로 `commit` 을 넘김).
            width = 2
            if command[i + 1] in "\r\n":
                kind = "continuation"
                if command[i + 1 : i + 3] == "\r\n":
                    width = 3
            else:
                kind = "escape"
            regions.append((i, i + width, kind) if kind == "continuation" else (i + 1, i + 2, kind))
            i += width
            continue
        if ch == "#" and (i == 0 or command[i - 1] in " \t\n;&|("):
            eol = command.find("\n", i)
            end = n if eol == -1 else eol
            regions.append((i, end, "comment"))  # 주석의 `-C` 도 옵션이 아님
            i = end
            continue
        if ch == "(" and command[i + 1 : i + 2] == "(":
            # 인용 밖의 `((` 는 언제나 산술 — 중첩 서브셸은 `( (` 로 띄어야 하고,
            # 명령 치환 `$(cmd)` 는 `(` 하나라 여기 안 걸림. `$((` 도 이 갈래가 받음:
            # `$` 는 그냥 지나가고 뒤의 `((` 가 같은 자리에서 같은 끝을 찾음.
            # 빠뜨리면 `(( 1 << 2 ))` 뒤의 진짜 커밋이 본문으로 덮여 게이트가 통째로
            # 꺼짐 — HEAD 는 차단하던 명령(실측).
            i = _arith_end(command, i + 2)
            continue

        if ch == "$" and command[i + 1 : i + 2] == "[":  # $[…] — 옛 산술 철자
            i = _matching(command, i + 2, "[", "]")
            continue

        if ch == "$" and command[i + 1 : i + 2] == "(":  # 어디에 있든 명령
            end = _matching(command, i + 2, "(", ")")
            regions.extend(_nested(command, i + 2, min(end, n) - 1))
            i = end
            continue
        if ch == "`":
            i += 1  # 내용은 명령이고, 구분자만 명령이 아님
            continue

        if ch == "$" and command[i + 1 : i + 2] == "'":  # $'…' — 안에서 `\` 가 이스케이프
            j = i + 2
            while j < n and command[j] != "'":
                j += 2 if command[j] == "\\" else 1
            regions.append((i + 2, min(j, n), "quote"))
            i = j + 1
            continue
        if ch == '"':
            end, inner = _double_quoted(command, i)
            code = _executed_span(command, i) and end - 1 <= n
            regions.extend(_code_span(command, i + 1, end - 1) if code else inner)
            i = end
            continue
        if ch == "'":
            j = command.find("'", i + 1)
            j = n if j == -1 else j
            code = _executed_span(command, i) and j < n
            regions.extend(_code_span(command, i + 1, j) if code else [(i + 1, j, "quote")])
            i = j + 1
            continue
        m = _HEREDOC_RE.match(command, i)
        if m:
            eol = command.find("\n", m.end())
            if eol != -1:  # 개행이 없으면 본문 자체가 없고, 줄 나머지는 여전히 구문
                if body_at is None:
                    body_at = eol + 1
                raw = m.group(2)
                literal = any(q in raw for q in (SQ_CH, DQ_CH, BS_CH))
                pending.append((bool(m.group(1)), _delimiter_word(raw), literal, m.start()))
            i = m.end()
            continue
        i += 1
    if body_at is not None:  # 여는 줄이 스캔의 전부였음
        regions.extend(_heredoc_bodies(command, body_at, pending)[1])
    return tuple(regions)


def mask_literals(command: str) -> str:
    """모든 리터럴 구간을 덮은 `command` — 길이도 구분자도 그대로.

    따옴표 인자가 공백 없는 토큰 하나로 남으므로 옵션 문법이 따옴표 규칙을 다시 적지 않아도
    되고, 오프셋은 원본을 그대로 가리킴(값은 원본에서 읽음). 줄이음만 **공백**이 됨 —
    아무것도 가르지 않으므로 거기서 토큰이 끝나면 안 됨.
    """
    out = list(command)
    for a, b, kind in _shell_regions(command):
        out[a:b] = (" " if kind in _BLANKED else "\x00") * (b - a)
    return "".join(out)


@lru_cache(maxsize=8)
def _comment_starts(command: str) -> tuple[int, ...]:
    """이 명령 안 주석들이 시작되는 자리(오름차순).

    구간 전체를 호출마다 훑지 않으려고 따로 뽑아 둠. `operand_end` 는 명령 안의 switch
    하나마다 불리므로, 주석이 K 개인 명령에서 선형 탐색은 K² 가 됨 — 30KB 명령에서
    209ms 를 실측했고, 훅에서의 2차는 타임아웃이며 타임아웃은 판정을 건너뛰는 것과 같음.
    """
    return tuple(sorted(a for a, _b, kind in _shell_regions(command) if kind == "comment"))


def _scripted_view(command: str) -> str:
    """인용된 텍스트를 **지우는** 대신 인용을 **지운** `command`.

    그물이 읽는 판. 목적은 인터프리터가 건네받은 스크립트를 보는 것인데, 그것을 덮어
    버리는 마스크로는 볼 수 없음. 주석만 반대로 감 — 덮음: `#` 구간은 어떤 인터프리터도
    건네받을 수 없는 유일한 리터럴.

    heredoc 본문은 **늘 남김**. 본문이 데이터인지는 그 원소가 면제를 받는지가 정하고(받으면
    그물이 그 원소를 아예 안 봄), 여기서 이름으로 다시 가르면 `git commit -F- <<EOF` 의
    메시지를 지우는 값으로 목록 밖 실행기의 본문까지 함께 지우게 됨 — 그것이 이름 목록을
    방아쇠에서 뗀 이유. 길이는 그대로라, 이 판과 마스크가 같은 문자열을 기술.
    """
    out = list(command)
    for a, b, kind in _shell_regions(command):
        if kind == "comment":
            out[a:b] = " " * (b - a)
    return _QUOTING_RE.sub(lambda m: " " * len(m.group()), "".join(out))


def _opening_spans(
    regions: tuple[tuple[int, int, str], ...],
) -> list[tuple[int, int]]:
    """각 heredoc 의 (도입부 오프셋, 본문 시작) 구간, 시작 오프셋 오름차순.

    **구간 순서에서 직접 짝을 읽음.** `_heredoc_bodies` 가 heredoc 하나마다 도입부 표식과
    본문 시작 표식을 그 순서로 잇달아 내므로, `heredoc-open` 다음의 첫 폭 0 `heredoc` 이
    그 본문. 두 목록을 따로 뽑아 i 번째끼리 zip 하면 어긋남 — 확장이 켜진 본문은
    청크마다 `heredoc` 구간을 내므로 본문 쪽이 더 길어짐(실측).
    """
    spans: list[tuple[int, int]] = []
    intro: int | None = None
    for a, b, kind in regions:
        if kind == "heredoc-open":
            intro = a
        elif kind == "heredoc" and a == b and intro is not None:
            spans.append((intro, a))
            intro = None
    return sorted(spans)


def _substitutions(masked: str) -> list[tuple[int, int]]:
    """마스크 위에서 구분자가 경계가 **아닌** span 들 — `$( … )`·백틱·프로세스 치환.

    프로세스 치환 `<( … )`·`>( … )` 이 여기 드는 것은 `_list_elements` 를 위해서임. 안쪽
    `;` 에서 원소를 자르면 잘린 꼬리가 리더 하나만 든 원소가 되어 면제를 받고, 그 앞의
    인터프리터가 진짜로 돌리는 커밋을 아무도 안 읽음 — 프로세스 치환으로 인터프리터에 넘긴
    스크립트 안의 커밋이 그렇게 통째로 빠져나갔음(실측).

    `_SUBSTITUTION_RE`(면제 취소용)는 **안 건드림**: `<( … )` 이 명령 자리에 내놓는 것은
    출력이 아니라 파일 이름이라, `cat <(echo "git commit")` 은 언급으로 남아야 함.
    """
    spans: list[tuple[int, int]] = []
    i, n = 0, len(masked)
    while i < n:
        if masked[i] == DOLLAR_CH and masked[i + 1 : i + 2] == "(":
            end = _matching(masked, i + 2, "(", ")")
        elif masked[i] == BT_CH:
            end = _matching(masked, i + 1, BT_CH, BT_CH)
        elif masked[i] in "<>" and masked[i + 1 : i + 2] == "(":
            end = _matching(masked, i + 2, "(", ")")
        else:
            i += 1
            continue
        spans.append((i, min(end, n)))
        i = min(end, n) if end > i else i + 1
    return spans


@lru_cache(maxsize=16)
def _substitution_tree(masked: str) -> tuple[tuple[int, ...], ...]:
    """마스크 위 치환 **전부**(중첩 포함)의 (starts, ends, closes, parents), 시작 오름차순.

    `closes` 는 닫는 `)`·백틱의 자리(안 닫혔으면 끝), `parents` 는 그것을 직접 감싼 치환의
    번호(없으면 -1). 치환마다 안쪽을 한 번씩만 다시 훑으므로 합은 길이 × 중첩 깊이.
    """
    found = []
    pending = [(0, len(masked), -1)]
    while pending:
        a, b, parent = pending.pop()
        for i, e in _substitutions(masked[a:b]):
            i, e = i + a, e + a
            closed = e - 1 > i and masked[e - 1] in (")", BT_CH)
            close = e - 1 if closed else e
            found.append((i, e, close, parent))
            pending.append((i + (1 if masked[i] == BT_CH else 2), close, i))
    found.sort()
    index = {f[0]: n for n, f in enumerate(found)}
    return (
        tuple(f[0] for f in found),
        tuple(f[1] for f in found),
        tuple(f[2] for f in found),
        tuple(index.get(f[3], -1) for f in found),
    )


@lru_cache(maxsize=16)
def _children(masked: str) -> dict[int, list[int]]:
    """치환마다 그것이 직접 감싼 치환들의 번호. 맨 바깥은 -1 밑."""
    out: dict[int, list[int]] = {}
    for c, parent in enumerate(_substitution_tree(masked)[3]):
        out.setdefault(parent, []).append(c)
    return out


def _list_elements(command: str, masked: str) -> list[tuple[int, int]]:
    """명령 리스트의 원소 하나마다 하나씩인 `command` 의 인덱스 범위들.

    **마스크에서** 가름 — 메시지나 주석 안의 구분자는 아무것도 끝내지 않음. heredoc
    본문을 여는 개행도 경계가 아님: 본문은 그 명령의 입력이고, 거기서 잘라내면 인터프리터와
    그것이 건네받은 스크립트가 서로 다른 원소로 떨어짐.

    도입부와 본문 **사이**의 구분자도 마찬가지. `bash <<EOF && echo ok` 에서 `&&` 를 경계로
    읽으면 본문이 `echo` 쪽 원소로 넘어가고, 그 원소는 리더만 돌리므로 면제를 받아 본문에 든
    진짜 커밋이 아무에게도 읽히지 않음(실측: 러너 exit 2 → 0). 셸은 그 본문을 도입부가 선
    명령의 입력으로 줌.

    치환 **안**의 구분자도 아님. `$(cat /dev/null; echo git commit -m x)` 는 명령 하나이고,
    거기서 자르면 꼬리가 리더만 든 원소가 되어 면제를 도로 받음 — 치환이 출력하는 진짜
    커밋을 아무도 안 읽음(실측: 실제 bash 가 커밋을 돌림).
    """
    regions = _shell_regions(command)
    bodies = {a for a, _b, kind in regions if kind == "heredoc"}
    # 두 종류의 구간이 같은 물음에 답함 — "이 안의 구분자는 경계가 아니다".
    opening = sorted(_opening_spans(regions) + _substitutions(masked))
    # 구분자마다 구간을 훑으면 `구분자 × heredoc` 이라 2차 — heredoc 2048 개·구분자 8191 개
    # 짜리 명령에서 1073ms 대 5.9ms 를 실측. 시작 오프셋으로 정렬해 두고 이분 탐색으로
    # 물음. 구간은 겹침
    # (한 줄이 heredoc 둘을 열면 도입부가 둘 다 본문보다 앞섬). 끝값의 **접두 최대**를 함께
    # 들고 다녀 "앞선 구간 중 아직 안 닫힌 것"을 봄 — 끝값의 순서를 가정하지 않는 한 패스.
    starts = [a for a, _b in opening]
    reach: list[int] = []
    for _a, b in opening:
        reach.append(b if not reach else max(reach[-1], b))
    spans, start = [], 0
    for m in _LIST_SEPARATOR_RE.finditer(masked):
        if m.group() == "\n" and m.end() in bodies:
            continue
        at = bisect_right(starts, m.start())
        if at and reach[at - 1] > m.start():
            continue
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(command)))
    return spans


# 인용 제거를 마친 낱말이 `git` 을 부르는가. 디렉터리 접두와 호스트의 `.exe` 를 받음.
_IS_GIT_WORD_RE = re.compile(r"(?:.*[/\\])?git(?:\.exe)?$", re.IGNORECASE)
# 낱말 하나가 끝나는 자리 — 인용·이스케이프가 지워진 판에서 봄.
_WORD_BREAK = " \t\n\r;&|()<>"
# 한 명령 자리에서 읽는 낱말 수의 상한. 전역 옵션이 이만큼 늘어설 일은 없고, 안 걸어 두면
# 명령 자리 하나가 명령 전체를 읽어 `명령자리 × 길이` 로 2차가 됨.
_SUBCOMMAND_WORDS = 32
# 낱말 안의 공백을 덮을 글자. 문법이 옵션 토큰을 `\S+` 로 보므로 무엇이든 공백만 아니면 됨.
_WHITESPACE_RE = re.compile(r"\s")


class _Bounded:
    """`stream` 을 `end` 에서 끝난 것처럼 읽게 함 — shlex 가 쓰는 `seek`·`read` 만."""

    def __init__(self, stream, end: int) -> None:
        self._stream, self._end = stream, end

    def seek(self, pos: int) -> None:
        self._stream.seek(pos)

    def read(self, n: int = -1) -> str:
        left = self._end - self._stream.tell()
        if left <= 0:
            return ""
        return self._stream.read(left if n < 0 else min(n, left))

    def readline(self) -> str:
        return self.read()


def _leading_words(stream, start: int, limit: int) -> list[str]:
    """`start` 부터의 낱말들 — 셸과 같은 인용 제거로, **필요한 만큼만** 읽음.

    `shlex.split` 은 문자열 끝까지 읽음. 명령 자리마다 그렇게 하면 구분자 없는 명령에서
    `명령자리 × 길이` 라 2차 — `env git ` 을 k 번 이은 명령이 16KB 에서 7.4초, 러너 wall
    로는 64KB 에서 244초였음(실측; 훅 timeout 600초 = 약 90KB 부터 판정 없음).

    선형을 만드는 것은 **둘**. ① 스트림을 받아 seek — 자리마다 `text[start:]` 로
    자르면 그 자르기가 O(길이) 라 같은 2차가 그대로 돌아옴(주석 달린 switch 12800 줄,
    243KB 에서 3.1초, 실측). ② `limit` 이 자리마다 읽는 낱말 수를 묶음.

    **서브커맨드를 지난 첫 낱말**에서 멈추는 것은 그 위의 상수 절감(실측 약 6배: 낱말
    뒤에 4000자짜리 인자가 붙은 1.6MB 명령에서 515ms 대 3142ms). 둘 다 선형이므로 이 조기
    중단이 없다고 게이트가 꺼지지는 않음 — 성능 계약을 지키는 것은 ①과 ②.
    """
    import shlex

    stream.seek(start)
    lexer = shlex.shlex(stream, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # `shlex.split` 과 같은 규약 — `#` 은 여기서 낱말을 끝내지 않음
    words: list[str] = []
    try:
        while len(words) < limit:
            token = lexer.get_token()
            if token is None:
                break
            words.append(token)
            if len(words) >= 3 and not token.startswith("-") and not words[-2].startswith("-"):
                break  # 서브커맨드를 지났음
    except ValueError:
        pass
    return words


def _word_end(masked: str, start: int, count: int) -> int:
    """`start` 에서 셸 낱말 `count` 개를 지난 자리 — **마스크 위에서** 셈.

    마스크는 오프셋을 보존하면서 인용 안의 공백을 NUL 로 덮으므로, 낱말 경계는 그냥 공백.
    원본에서 세면 따옴표 안의 공백이 낱말을 끊음.
    """
    i, n = start, len(masked)
    for _ in range(count):
        while i < n and masked[i] in " \t":
            i += 1
        while i < n and masked[i] not in _WORD_BREAK:
            i += 1
    return i


def _command_words(masked: str, view: str | None = None, anywhere: bool = False) -> list[int]:
    """명령 자리에 선 낱말들 중 **git 일 수 있는** 것들의 시작 오프셋.

    `git` 을 담고 있거나 인용·백슬래시·낱말 안 줄이음(`_JOIN_FILL`)을 담은 낱말만 후보.
    이름이 마스크에서 쪼개지는 것이 그것들뿐이라서 — `gi't'`·`gi"t"`·`gi''t`·`g\\it` 은
    마스크에 `git` 이 없는데도 셸이 argv 로 `commit` 을 넘김(실측). 한 번의 선형 훑기로
    낱말 경계를 세고, 자리는 `at_command_start` 가 판정. 경계는 `view`(기본은 마스크)에서
    셈 — `_word_view` 를 주면 명령 자리 인용 span 의 따옴표가 낱말을 가르지 않음.
    """
    view = masked if view is None else view
    starts: set[int] = set()
    at: int | None = None
    marked = False
    for i, ch in enumerate(view):
        if ch in _WORD_BREAK:
            if at is not None and marked:
                starts.add(at)
            at, marked = None, False
            continue
        if at is None:
            at = i
        if ch in "'\"\\" or ch == _JOIN_FILL or view.startswith("git", i):
            marked = True
    if at is not None and marked:
        starts.add(at)
    if anywhere:
        return sorted(starts)
    # 자리는 마스크로 판정 — 되살린 따옴표 뒤의 첫 글자에서
    return sorted(s for s in starts if at_command_start(masked, _past_quotes(view, masked, s)))


def _spelled_with_quotes(command: str, masked: str, pattern: GitSubcommand, anywhere: bool = False):
    """`git 'commit'`·`gi't' commit` — 셸의 **인용 제거** 뒤에야 호출이 되는 철자들.

    매치마다 `(낱말 시작, 전역옵션 시작, 전역옵션 끝, 피연산자 시작, 문법 매치)` 를 냄. 앞
    넷은 정규식 매치의 `start()`·`span(1)`·`end()` 와 같은 자리라, merge 전략이 두 갈래를 한
    모양으로 읽음. 문법 매치는 서브커맨드를 그룹으로 고르는 문법에서 어느 것인지 알려 줌.

    마스크는 인용된 텍스트를 데이터로 덮는데, **낱말의 철자**에 든 인용은 데이터가 아님.
    `git 'commit'`·`git com''mit`·`gi't' commit`·`g\\it commit` 은 전부 진짜 커밋을 만들고
    (실측), 마스크만 보면 전부 "커밋 아님"이었음 — `--classify` 가 `ok=1` 만 내 러너가
    게이트 단계 전에 exit 0 함.

    문법은 **선두 고정**으로 걸어 둠. `search` 로 하면 `git grep 'git commit'` 이 인자 안의
    `git` 에서 매치돼 우회로 없는 오차단이 됨(실측 43개 중 9개가 그 모양이었음).

    `anywhere` 는 명령 자리 판정을 건너뜀 — 낱말 하나하나는 여전히 선두 고정으로 읽음.
    `eval git mer''ge …` 처럼 다시 파싱돼 도는 호출을 머지 판정이 찾을 때만 씀. 그 자리가
    정말 도는지는 부르는 쪽이 따로 판정함.
    """
    view = _word_view(command, masked)
    starts = _command_words(masked, view, anywhere)
    if not starts:
        return
    stream = StringIO(_blanked_view(command))
    # 판이 낱말을 잘못 주는 자리 — 원본에서 한 번만 찾음. 명령 자리마다 구간을 훑으면 구간
    # 계산만으로 상수배가 커짐(실측: `gitv=$a`×25000 에서 두 배).
    raw = StringIO(command)
    tricky = [m.start() for m in _TRICKY_RE.finditer(command)]
    seps = _bound_separators(view)
    for start in starts:
        j = bisect_left(seps, start)
        # 다음 구분자에서 끊음 — shlex 는 `;` 에서 낱말을 안 가르므로, 안 끊으면 `git;`×k 에서
        # 자리마다 남은 꼬리를 낱말 하나로 읽어 2차였음(실측: 32KB 에서 88초).
        bound = seps[j] if j < len(seps) else len(command)
        k = bisect_left(tricky, start)
        near = k < len(tricky) and tricky[k] < bound
        end = _segment_end(view, start) if near else start
        if near and tricky[k] < end:
            # 원본도 해독이 필요함: shlex 는 `$'merge'` 를 `$merge` 로, 판이 공백으로 덮은
            # 줄이음은 `mer\<개행>ge` 를 두 낱말로 읽음. 그 명령 하나만 원본에서 해독해 다시
            # 읽음 — 구간이 구분자나 낱말 상한에서 끝나므로 자리마다 다시 훑어도 합이 선형.
            segment = _CONTINUATION_RE.sub("", command[start:end])
            words = _leading_words(StringIO(requote_ansi_c(segment)), 0, _SUBCOMMAND_WORDS)
        elif _restored(view, masked, start):
            # 명령 자리의 인용 span 은 판에서 따옴표가 지워져 `"g"it` 이 두 낱말, 안의 백슬래시가
            # 이스케이프로 읽힘(`"C:\Git\git.exe"`) — 원본을 같은 경계에서 읽음. 줄이음·ANSI-C
            # 가 없으면 원본의 인용이 곧 bash 의 인용이라 해독할 것이 없음.
            words = _leading_words(_Bounded(raw, bound), start, _SUBCOMMAND_WORDS)
        else:
            words = _leading_words(_Bounded(stream, bound), start, _SUBCOMMAND_WORDS)
        if len(words) < 2 or not _IS_GIT_WORD_RE.match(words[0]):
            continue
        # 낱말 안의 공백은 낱말을 끝내지 않음(`--git-dir=/a/My\ P/.git`). 이어 붙이기 전에
        # 대체하지 않으면 문법이 그것을 두 낱말로 읽어 서브커맨드 자리가 밀림(실측).
        m = pattern.match("git " + " ".join(_WHITESPACE_RE.sub("\x01", w) for w in words[1:]))
        if m is None:
            continue
        # 인용이 든 철자는 길이가 다르므로 자리를 문자 수가 아니라 **낱말 수**로 셈:
        # `git` 하나 + 전역 옵션 영역 + 서브커맨드 하나.
        opts = len(m.group(1).split())
        first = _first_word_end(command, view, start)
        yield (
            start,
            first,
            _word_end(view, first, opts),
            _word_end(view, first, 1 + opts),
            m,
        )


def _word_view(command: str, masked: str) -> str:
    r"""낱말 경계를 셀 판 — 마스크에 명령 자리 인용 span 의 따옴표를 되살린 것.

    그 span 은 코드로 읽히므로 마스크가 따옴표만 공백으로 지움. 그 공백에서 낱말을 가르면
    `"g"it merge` 는 `g`·`it` 두 낱말이 되어 git 으로 안 읽히고, `"C:\Git\bin\git.exe"` 는
    닫는 따옴표 뒤에서 읽기 시작해 나머지가 인용으로 삼켜짐(실측: 둘 다 전략 판정 없음).
    마스크가 공백으로 덮은 줄이음 중 낱말 안의 것도 같은 이유로 낱말 글자로 채움 — 안
    그러면 `git mer\<개행>ge` 의 피연산자가 `ge` 에서 시작함."""
    quotes = "'" in command or '"' in command
    joins = _LINE_JOIN_RE.search(command) is not None
    if not quotes and not joins:
        return masked
    out = list(masked)
    if quotes:
        for i, (c, m) in enumerate(zip(command, masked)):
            if c in "'\"" and m == " ":
                out[i] = c
    # 마스크가 공백으로 덮은 줄이음 중 낱말 **안**의 것만 낱말 글자로 — `mer\<개행>ge` 는
    # bash 에게 낱말 하나. 낱말 사이에 홀로 선 것(`git \<개행> merge`)은 공백 그대로: 채우면
    # 그 자리가 낱말 하나로 세어져 피연산자가 서브커맨드에서 시작함(실측: 소스 `merge`).
    for m in _LINE_JOIN_RE.finditer(command):
        if masked[m.start()] == " " and _joins_a_word(command, m.start(), m.end()):
            out[m.start() : m.end()] = _JOIN_FILL * (m.end() - m.start())
    return "".join(out)


def _bound_separators(view: str) -> list[int]:
    """명령을 끝내는 구분자 자리 — `${…}` 안의 것은 뺌. 마스크는 파라미터 확장을 덮지 않아
    `${y:-a;b}` 의 `;` 가 남는데, 거기서 끊으면 `g\\it -c x=${y:-a;b} commit` 의 커밋이
    안 보임(실측: `--classify` 가 `ok=1` 만). 닫히지 않은 `${` 뒤로는 끊지 않음 — 덜 끊는
    쪽은 느려질 뿐 판정을 잃지 않음."""
    seps: list[int] = []
    depth, i, n = 0, 0, len(view)
    while i < n:
        if view.startswith("${", i):
            depth += 1
            i += 2
            continue
        ch = view[i]
        if ch == "}" and depth:
            depth -= 1
        elif ch in _SEGMENT_END and not depth:
            seps.append(i)
        i += 1
    return seps


def _joins_a_word(command: str, a: int, b: int) -> bool:
    """`command[a:b]` 의 줄이음이 양옆 글자를 낱말 하나로 잇는가 — 앞뒤가 둘 다 낱말 글자."""
    edge = " \t" + _WORD_BREAK
    return 0 < a and b < len(command) and command[a - 1] not in edge and command[b] not in edge


def _restored(view: str, masked: str, i: int) -> bool:
    """`i` 의 글자가 `_word_view` 가 되살린 따옴표인가."""
    return i < len(view) and view[i] in "'\"" and masked[i] == " "


def _past_quotes(view: str, masked: str, i: int) -> int:
    """`i` 부터 되살린 따옴표를 건넌 자리."""
    while _restored(view, masked, i):
        i += 1
    return i


def _first_word_end(command: str, view: str, start: int) -> int:
    r"""`start` 의 첫 낱말이 끝나는 자리. 따옴표로 열리면 원본에서 짝을 찾음 — 명령 자리의
    인용 span 은 마스크가 안의 공백을 남겨 `"C:\Program Files\…"` 를 두 낱말로 셈."""
    quote = command[start] if start < len(command) else ""
    if quote not in ("'", '"'):
        return _word_end(view, start, 1)
    i, n = start + 1, len(command)
    while i < n and command[i] != quote:
        i += 2 if quote == '"' and command[i] == "\\" else 1
    i = min(i + 1, n)
    if i < n and view[i] not in " \t":  # 닫는 따옴표에 붙은 나머지도 같은 낱말
        i = _word_end(view, i, 1)
    return i


# 인용 제거가 낱말에서 지우는 것 — 줄이음, 각 따옴표, ANSI-C·로캘 문자열을 여는 `$`, 그리고
# 문자 하나를 인용하는 백슬래시. `\r\n` 줄이음은 bash 에선 줄이음이 아니지만 Windows 에서 오는
# 훅 페이로드의 줄끝이라 함께 이음(과다 게이팅 쪽). `com''mit`·`c\ommit`·`$'commit'`·
# `co\<개행>mmit` 은 bash 에게 전부 `commit` 인데, 위의 판들은 조각을 떨어진 채로 둠.
_QUOTE_REMOVAL_RE = re.compile(r"\\\r?\n|\$(?=['\"])|['\"]|\\(?=\S)")


# 뜻이 고정된 ANSI-C 이스케이프. `\x`·`\u`·`\U`·8진·`\c` 는 따로 풂.
_ANSI_C_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}
_ANSI_C_NUMERIC = {"x": (16, 2), "u": (16, 4), "U": (16, 8)}
_HEX = frozenset("0123456789abcdefABCDEF")
# 큰따옴표 안의 백슬래시가 인용하는 글자. 그 밖의 글자 앞에서는 백슬래시가 남음.
_DQ_ESCAPED = frozenset('$`"\\\n')
# 줄이음 — bash 는 따옴표를 읽기 전에 지움.
_CONTINUATION_RE = re.compile(r"(?:\\\r?\n)*")
# 줄이음 하나, 그리고 ANSI-C·로캘 문자열을 여는 `$` — 둘 다 없는 텍스트는 문자 루프를 건너뜀.
_LINE_JOIN_RE = re.compile(r"\\\r?\n")
_ANSI_OPEN_RE = re.compile(r"\$(?:\\\r?\n)*['\"]")
# 문맥 없이 여는 `$'` — 지운 판은 이것을 전부 풂.
_ANSI_C_START_RE = re.compile(r"\$(?:\\\r?\n)*'")
# 인용 제거가 바꿀 수 있는 글자 — 하나도 없으면 벗긴 판은 원문 그대로.
_QUOTING_CHAR_RE = re.compile(r"['\"\\]")
# `_could_spell` 이 지우는 글자 — 어느 겹에서든 인용·이스케이프·줄이음이 될 수 있는 것 전부.
_QUOTING_CHARS = str.maketrans("", "", "$\\'\"\r\n")
# `_word_view` 가 줄이음 자리에 두는 글자 — 공백도 낱말 경계도 아님.
_JOIN_FILL = "\x02"
# 셸 분할 판이 낱말을 잘못 주는 자리: 줄이음과 ANSI-C·로캘 문자열.
_TRICKY_RE = re.compile(f"{_LINE_JOIN_RE.pattern}|{_ANSI_OPEN_RE.pattern}")
# 인용을 한 번 벗길 횟수 — 인터프리터 하나가 한 겹: `sh -c "eval 'git c\\ommit'"` 은 셋.
# 이보다 깊은 중첩은 지우는 읽기(`_joined`)가 받음 — `eval` 이 겹마다 백슬래시를 반으로 줄임.
_QUOTE_LEVELS = 4


def _ansi_c_end(text: str, i: int) -> int:
    """`i` 에서 시작하는 `$'…'` 본문을 닫는 따옴표 자리. 해독 **전에** 백슬래시가 뒤 글자를
    데려감 — 닫는 따옴표도."""
    n = len(text)
    while i < n and text[i] != "'":
        i += 2 if text[i] == "\\" else 1
    return min(i, n)


def _ansi_c(text: str, i: int) -> tuple[str, int]:
    """`i` 에서 시작하는 `$'…'` 본문의 값과 닫는 따옴표 다음 자리. `git $'\\x63ommit'` 은
    커밋을 돌리므로 이스케이프를 텍스트로 두지 않고 풂. 어떤 글자도 아닌 코드 포인트는 적힌
    그대로 둠 — 예외로 던지면 그 머지의 낱말이 통째로 비어 판정이 fail-open."""
    end = _ansi_c_end(text, i)
    out = []
    while i < end:
        if text[i] != "\\" or i + 1 >= end:
            out.append(text[i])
            i += 1
            continue
        c = text[i + 1]
        if c in _ANSI_C_ESCAPES:
            out.append(_ANSI_C_ESCAPES[c])
            i += 2
        elif c in _ANSI_C_NUMERIC:
            base, width = _ANSI_C_NUMERIC[c]
            j = i + 2
            while j < min(end, i + 2 + width) and text[j] in _HEX:
                j += 1
            code = int(text[i + 2 : j], base) if j > i + 2 else -1
            out.append(chr(code) if 0 <= code < 0xD800 or 0xDFFF < code <= 0x10FFFF else text[i:j])
            i = j
        elif c in "01234567":
            j = i + 1
            while j < min(end, i + 4) and text[j] in "01234567":
                j += 1
            out.append(chr(int(text[i + 1 : j], 8) & 0xFF))
            i = j
        elif c == "c" and i + 2 < end:
            out.append(chr(ord(text[i + 2]) & 0x1F))
            i += 3
        else:
            out.append(text[i : i + 2])
            i += 2
    return "".join(out), end + 1


def _opens_string(text: str, i: int) -> tuple[str, int]:
    """`i` 의 `$` 뒤에서 ANSI-C·로캘 문자열을 여는 따옴표(사이의 줄이음은 건넘)와 그 자리.
    아니면 ("", i)."""
    j = _CONTINUATION_RE.match(text, i + 1).end()
    return (text[j], j) if text[j : j + 1] in ("'", '"') else ("", i)


def _remove_quotes(text: str) -> str:
    """bash 의 인용 제거 뒤의 `text`. `com''mit`·`c\\ommit`·`$'\\x63ommit'`·줄이음이 끊은
    낱말은 전부 `commit` 이고, 큰따옴표 안의 백슬래시는 bash 처럼 남음 —
    `"C:\\Git\\bin\\git.exe"` 는 여전히 git 의 경로. 닫히지 않은 따옴표는 끝까지 감."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            if text.startswith("\r\n", i + 1):
                i += 3
            elif i + 1 < n:
                if text[i + 1] != "\n":
                    out.append(text[i + 1])
                i += 2
            else:
                out.append(c)
                i += 1
        elif c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            out.append(text[i + 1 : j])
            i = j + 1
        elif c == "$" and _opens_string(text, i)[0] == "'":
            value, i = _ansi_c(text, _opens_string(text, i)[1] + 1)
            out.append(value)
        elif c == "$" and _opens_string(text, i)[0] == '"':
            i = _opens_string(text, i)[1]
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and text.startswith("\r\n", i + 1):
                    i += 3
                elif text[i] == "\\" and i + 1 < n and text[i + 1] in _DQ_ESCAPED:
                    if text[i + 1] != "\n":
                        out.append(text[i + 1])
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def requote_ansi_c(text: str) -> str:
    """인용 밖의 `$'…'` 마다 그것이 풀리는 작은따옴표 문자열로, `$"…"` 는 맨 큰따옴표
    문자열로 바꾼 `text` — shlex 가 모르는 두 철자. 안 바꾸면 `git merge $'--no-ff'` 의
    플래그가 `$--no-ff` 로 읽혀 전략 판정에 안 닿음."""
    out, i, n = [], 0, len(text)
    quote = ""
    while i < n:
        c = text[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < n:
                out.append(text[i : i + 2])
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        elif c == "$" and _opens_string(text, i)[0] == "'":
            value, i = _ansi_c(text, _opens_string(text, i)[1] + 1)
            out.append("'" + value.replace("'", "'\\''") + "'")
            continue
        elif c == "$" and _opens_string(text, i)[0] == '"':
            i = _opens_string(text, i)[1]
            continue
        elif c in "'\"":
            quote = c
        out.append(c)
        i += 1
    return "".join(out)


def _joined(text: str) -> str:
    """지우는 읽기 — `$'…'` 해독 뒤 줄이음·따옴표·백슬래시를 전부 지운 `text`. bash 보다
    거칠고 깊이 제한이 없음(큰따옴표 안 백슬래시도 지움). `$'…'` 는 **문맥을 묻지 않고**
    전부 풂 — 인용 안이든 이스케이프 뒤든: 확장되는 heredoc 본문이나 인터프리터의 안쪽 겹은
    그 `\\$` 를 벗긴 뒤 풀어 `bash <<E` 가 `bash -c "git \\\\$'\\143'ommit"` 을 커밋으로
    돌림(실측: bash 5.2)."""
    return _QUOTE_REMOVAL_RE.sub("", _every_ansi_c_decoded(text))


def _every_ansi_c_decoded(text: str) -> str:
    """`text` 의 모든 `$'…'` 를 그 값으로 — 인용·이스케이프 문맥 없이."""
    if not _ANSI_OPEN_RE.search(text):
        return text
    out, i = [], 0
    for m in _ANSI_C_START_RE.finditer(text):
        if m.start() < i:
            continue
        out.append(text[i : m.start()])
        value, i = _ansi_c(text, m.end())
        out.append(value)
    out.append(text[i:])
    return "".join(out)


def _unquoted_readings(text: str) -> list[str]:
    """`text` 의 인용을 지운 판들 — 지우는 읽기 하나와, 인터프리터가 벗길 수 있는 겹마다
    bash 그대로 한 번씩 벗긴 판(`bash -c 'git c\\ommit'` 은 그것이 돌리는 커밋). 앞의 것이
    깊은 중첩을, 뒤의 것들이 큰따옴표 안에 남는 백슬래시(`"C:\\Git\\git.exe"`)를 받음."""
    views = [_joined(text)]
    if not _QUOTING_CHAR_RE.search(text):
        return views
    for _ in range(_QUOTE_LEVELS):
        peeled = _remove_quotes(text)
        if peeled == text:
            break
        views.append(peeled)
        text = peeled
    return views


_SEGMENT_END = frozenset(";&|()\n")


def _segment_end(masked: str, start: int) -> int:
    """`start` 의 명령이 끝나는 자리 — 마스크의 구분자, 줄이음의 개행은 빼고. 낱말
    `_SUBCOMMAND_WORDS` 개에서도 멈춤: 서브커맨드는 git 과 전역 옵션 몇 개 뒤에 서고, 안
    멈추면 구분자 없는 명령에서 `명령자리 × 길이` 로 2차가 됨."""
    end = _word_end(masked, start, _SUBCOMMAND_WORDS + 1)
    i = start
    while i < end:
        ch = masked[i]
        if ch in _SEGMENT_END and not (
            ch == "\n" and (masked[i - 1 : i] == "\\" or masked[i - 2 : i] == "\\\r")
        ):
            return i
        i += 1
    return end


def _joined_at_command_starts(command: str, masked: str, pattern: GitSubcommand) -> bool:
    """명령 자리(마스크로 판정)마다 그 명령을 인용 제거한 판이 `git … <word>` 로 시작하는가.

    `_spelled_with_quotes` 는 낱말을 자기 자리에서만 이어, `$'commit'`·낱말 한가운데의 줄이음을
    놓침. 자리를 마스크로 정하므로 인자로 선 `"git commit"`·heredoc 본문은 여기 오지 않음."""
    view = _word_view(command, masked)
    starts = _command_words(masked, view)
    if not starts:
        return False
    uncommented = _uncommented(command)
    for s in starts:
        e = _segment_end(view, s)
        # 인용 안의 공백은 낱말을 끝내지 않음 — 마스크가 그 자리를 NUL 로 덮었으므로 거기서
        # 가려 낱말 안의 글자로 둠. 안 그러면 `echo … then "git commit"` 의 인자가 명령이 됨.
        # 개행은 그대로 — 큰따옴표 안의 줄이음(`"co\<개행>mmit"`)도 bash 는 지움(실측).
        seg = "".join(
            "\x01" if ch in " \t" and mch == "\x00" else ch
            for ch, mch in zip(uncommented[s:e], masked[s:e])
        )
        # 벗긴 판의 프로그램 낱말은 지운 판의 것에 인용 글자를 더한 것뿐이라, 지운 판이
        # git 으로 안 끝나면 벗긴 판도 git 이 아님 — 판마다 문자 루프를 돌 이유가 없음.
        joined = _joined(seg)
        if not joined.partition(" ")[0].lower().endswith(("git", "git.exe")):
            continue
        for reading in _unquoted_readings(seg):
            program, _sep, rest = reading.partition(" ")
            # 경로 붙은 이름(`/usr/bin/git`)도 git — 문법은 맨 이름에서 시작함.
            if _IS_GIT_WORD_RE.match(program) and pattern.match("git " + rest):
                return True
    return False


def _uncommented(command: str) -> str:
    """주석만 공백으로 덮고 나머지는 적힌 그대로인 `command` — 길이 같음. 원소마다의 인용
    제거(:data:`_QUOTE_REMOVAL_RE`)가 이 위에서 돎."""
    out = list(command)
    for a, b, kind in _shell_regions(command):
        if kind == "comment":
            out[a:b] = " " * (b - a)
    return "".join(out)


def _could_spell(text: str, word: str) -> bool:
    """`text` 의 어느 읽기든 `git` 과 `word` 를 철자할 수 있는가 — 아래 `is_invocation` 의
    필요조건. 읽기가 원문에 없는 글자를 만드는 길은 ANSI-C 이스케이프 하나 — `$`·`'`·백슬래시가
    다 있어야 열림. 하나라도 없으면 읽기의 글자는 원문 글자에서 인용 글자를 지운 것뿐이라
    지운 판 하나에 다 있음. 셋이 다 있으면 판정하지 않고 True: 어느 `$'` 가 열리는지와 몇 겹
    풀리는지가 겹마다 달라 한 판으로 못 정함(실측: 앞의 `'foo$'` 가 뒤 `$'\x63ommit'` 의 해독을
    어긋나게 하고, 짝수 백슬래시 겹은 한 번 풀어서는 철자가 안 됨)."""
    if "$" in text and "'" in text and "\\" in text:
        return True
    # 인용 글자는 전부 지움 — 바깥 겹이 사이 글자를 벗긴 뒤에야 안쪽 겹이 인용으로 읽는 것도
    # 있음(`$\""` 은 안쪽에서 `$""`, `\'"<개행>` 은 안쪽에서 줄이음). 지우기만 하므로 안전함.
    joined = text.translate(_QUOTING_CHARS)
    return "git" in joined.lower() and re.search(word, joined) is not None


def is_invocation(command: str, word: str) -> bool:
    """`command` 가 `git <word>` 를 실행하는가 — 그 물음에 대한 게이트의 유일한 권위.

    두 번 읽음. 정밀한 쪽은 문법에게 **마스크**를 물음. 거기서 인용된 텍스트는 데이터이고,
    그래서 읽기 전용 `git -c commit.gpgsign=false log` 가 미분류 커밋으로 차단되지 않음.
    단 **서브커맨드 자리의 인용은 데이터가 아니라 철자**이므로, 같은 읽기가 낱말 단위로도
    한 번 봄(`_spelled_with_quotes`) — `git 'commit'` 은 진짜 커밋.
    그 뒤에 마스크가 틀리는 경우를 위한 그물이 있음 — 명령 리스트의 그 **원소**가 읽기만
    하는 것이 아닌 무언가를 돌리면, 그 원소의 인용 텍스트(와 그것이 건네받은 heredoc 본문)는
    데이터가 아니라 스크립트일 수 있음. 그때 같은 문법을 그 원소의 인용 지우고 heredoc 본문은
    남긴 판 위에서 다시 읽음.

    **면제가 목록이지 게이팅이 목록이 아님.** 아무도 읽기 전용으로 적어 두지 않은 프로그램은
    오차단되고 사용자가 그것을 보고 우회하지만, 아무도 실행한다고 적어 두지 않은 통로는 아무
    말 없이 게이트를 껐음 — 통로를 세는 판은 셀 때마다 또 하나를 남겼음. 그래서 그물은
    그 원소가 **무엇을** 돌리는지 묻지 않음: 판독기가 아닌 원소는(그리고 실행 플래그가 붙어
    면제를 잃은 판독기는) heredoc 본문까지 전부 이 판으로 다시 읽힘 — 목록이 아는 인터프리터
    이름을 대든 안 대든. 이름의 부재는 오차단이지 꺼진 게이트가 아니어야 함.

    인용 제거 판(`$'…'` 해독 포함)은 두 자리에서 읽음 — 명령 자리마다
    (`_joined_at_command_starts`, 판독기인 `git` 자신 포함), 그리고 그물의 원소 전체. bash 가 한
    낱말의 조각을 잇듯 `git com''mit`·`git $'commit'`·줄이음으로 끊긴 낱말을 이어 붙임.

    둘째 읽기는 **명령 자리 판정을 하지 않음**. 인터프리터가 받은 스크립트 안에서 `git`
    앞에 서는 것은 이쪽 셸의 낱말이 아니라 그 스크립트의 것이고, 그 자리를 이쪽 규칙으로
    재면 진짜 스크립트를 떨어뜨림.

    두 문법 읽기 모두 `git` 과 `<word>` 가 **붙어 있기**를 요구하지는 않지만, 둘 다 셸 명령
    하나를 읽음. 그런데 `xargs`·`parallel` 은(그리고 방금 면제를 잃은 판독기는) 그 둘을 셸
    문법이 하나도 끼지 않은 **따로 선 토큰**으로 다음 프로세스에 건넴 —
    `echo commit -m x | xargs git` 은 어느 판에서도 `git … commit` 을 철자하지 않음. 그
    모양에서는 그물이 한 번 더 물러나, 스크립트 판에서 `git` 과 `word` 가 각각 낱말 하나로
    서는지만 봄. 문법 없이 존재만.

    탐지 전용. merge 의 **플래그**는 여전히 마스크에서 읽으므로, 그물만이 찾아낸 merge 는
    전략 판정이 없어 fail-open 함 — 불확실하니 허용.
    """
    # 필요조건(`_could_spell`)이 서지 않으면 아래 읽기 전부를 건너뜀 — `"g"it;`×k 를 원소마다
    # 묻는 커밋 경로에서 두 배였음.
    if not _could_spell(command, word):
        return False
    pattern = git_subcommand_re(word)
    masked = mask_literals(command)
    if next(git_invocations(masked, pattern), None) is not None:
        return True
    if next(_spelled_with_quotes(command, masked, pattern), None) is not None:
        return True
    if _joined_at_command_starts(command, masked, pattern):
        return True
    scripted = _scripted_view(command)
    uncommented = _uncommented(command)
    for a, b in _list_elements(command, masked):
        if not _could_spell(uncommented[a:b], word):  # 같은 필요조건, 원소마다
            continue
        by_flag = _runs_by_flag(command[a:b], masked[a:b])
        if _reads_only(masked[a:b]) and not by_flag:
            continue
        if pattern.search(scripted[a:b]):
            return True
        if any(pattern.search(view) for view in _unquoted_readings(uncommented[a:b])):
            return True
        names = _programs(masked[a:b])
        if (
            (by_flag or (set(names) & _XARGS))
            and _GIT_TOKEN_RE.search(scripted[a:b])
            and _standalone_word(scripted[a:b], word)
        ):
            return True
    return False


@lru_cache(maxsize=8)
def _blanked_view(command: str) -> str:
    """줄이음과 heredoc 구분자를 공백으로 덮은 원본 — 인용은 그대로 살아 있음.

    명령 **하나당 한 번** 만듦. 구간을 호출마다 훑으면 `호출 × 구간` 이라 2차 —
    인용 인자를 하나씩 든 원소 4000 개에서 구간 순회가 1600만 번, 790ms 였음(실측).
    """
    text = list(command)
    for a, b, kind in _shell_regions(command):
        if kind in _BLANKED:
            text[a:b] = " " * (b - a)
    return "".join(text)


# 치환의 텍스트가 그것이 선 명령의 낱말들 안에서 읽히는 모양 — 셸이 출력으로 갈아 끼우는
# 글자 한 덩어리. 따옴표도 공백도 없으므로 그것이 든 낱말을 가르지 않고, 안의 따옴표·주석·
# heredoc 본문을 shlex 에 넘기지도 않음.
OPAQUE_CH = chr(1)
# `_Level` 이 아직 가르지 않은 토큰의 표지.
_UNREAD = object()
# 겹 마스크에서 낱말이 속한 단순 명령을 끝내는 것. 리다이렉션(`>&`·`>|`·`2>&1`) 안의
# `&`·`|` 는 경계가 아님 — 경계로 세면 `eval >|A=1 git merge …` 의 lead 가 `eval >` 를 잃고
# 프로그램 자리로 읽혀, 다시 파싱돼 도는 머지를 버림(`_SEPARATOR_RE` 의 `&` 가드와 같은 근거).
_COMMAND_BREAK_RE = re.compile(r"[;\n\r()`]|(?<![<>])[&|]")
# 프로그램 앞에 서서 그 인자를 **다시 파싱하지 않고** 그대로 돌리는 낱말 — 그 사이에 인용된
# 구분자는 인자로 남음. 목록 밖 낱말(`eval`·`watch`·`ssh`·리다이렉션·치환)이 서면 프로그램
# 자리로 보지 않음: 다시 파싱하는 낱말을 세는 쪽이면 빠진 이름 하나가 게이트를 끔.
_UNPARSED_PREFIXES = frozenset(
    ("{", "!", "if", "then", "else", "elif", "do", "while", "until")
    + ("time", "command", "nohup", "sudo", "builtin")
)
_ASSIGNMENT_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")


def _runs_unparsed(word: str) -> bool:
    """프로그램 앞에 선 `word` 가 그 인자를 다시 파싱하지 않고 돌리는가."""
    return word in _UNPARSED_PREFIXES or bool(_ASSIGNMENT_WORD_RE.fullmatch(word))


def _reparse_depth(lead: list[str]) -> int:
    """프로그램 앞에 선 단순 명령의 낱말 `lead` 뒤의 낱말이, 그 프로그램이 돌기 전에 몇 번 더
    파싱되는가 — 앞의 것이 돌리는 자리에 선 `eval`·`watch`(명령을 직접 돌리는 `-x` 없이)·`ssh`
    하나마다 한 번씩. `watch`·`ssh` 의 옵션과 `ssh` 가 붙는 호스트는 건너뜀."""
    depth, i = 0, 0
    while True:
        while i < len(lead) and _runs_unparsed(lead[i]):
            i += 1
        program = _program_name(lead[i]) if i < len(lead) else None
        if program not in _REPARSING_PROGRAMS:
            return depth
        short, long = _REPARSING_PROGRAMS[program]
        i += 1
        while i < len(lead) and lead[i].startswith("-"):
            if program == "watch" and (lead[i] == "--exec" or re.fullmatch(r"-[^-]*x.*", lead[i])):
                return depth
            option = lead[i]
            if option.startswith("--"):
                takes = "=" not in option and option in long
            else:
                takes = _short_bundle_takes_next(option, short)
            i += 2 if takes else 1
        if program == "ssh":
            i += 1
        depth += 1


# 뒤의 낱말을 다시 파싱하는 프로그램 — 각자 다음 낱말을 값으로 받는 짧은 옵션 글자와 긴 옵션.
_REPARSING_PROGRAMS = {
    "eval": ("", ()),
    "watch": ("nq", ("--interval", "--equexit")),
    "ssh": ("BbcDEeFIiJLlmOoPpQRSWw", ()),
}


def _short_bundle_takes_next(tok: str, with_arg: str, owns_rest: str = "") -> bool:
    """짧은 옵션 묶음 `tok` 이 다음 낱말을 값으로 받는가 — `with_arg` 글자가 묶음 **끝**에 설 때.
    `owns_rest` 글자는 붙은 나머지만 값으로 받고 다음 낱말은 안 받음."""
    for i, letter in enumerate(tok[1:], 1):
        if letter in owns_rest:
            return False
        if letter in with_arg:
            return i == len(tok) - 1
    return False


def _shlex_words(text: str) -> tuple[str, ...] | None:
    """shlex 가 `text` 를 가른 낱말들. 못 가르면 None."""
    import shlex

    try:
        return tuple(shlex.split(requote_ansi_c(text)))
    except ValueError:
        return None


def _reread(words: tuple[str, ...] | None) -> tuple[tuple[str, ...] | None, bool]:
    """`eval` 이 인자를 파싱하듯 `words` 를 다시 파싱한 것 — 첫 구분자나 주석까지,
    리다이렉션은 빼고 — 과, 그 둘 중 하나가 거기서 끊었는가."""
    if words is None:
        return None, False
    again = " ".join(words)
    # 인자로서 낱말 뒤에 둔 채 마스크 — 명령 자리의 마스크는 인용된 낱말을 프로그램 이름으로
    # 벗겨 `';'` 의 `;` 를 드러냄
    masked = mask_literals(": " + again)[2:]
    text, plain = _blank_redirections(again, masked)
    stop = len(again)
    m = _SEPARATOR_RE.search(plain)
    if m:
        stop = m.start()
    stop = min([stop, *(c for c in _comment_starts(again) if plain[c] != " ")])
    if any(not r.group("target") for r in _REDIRECTION_RE.finditer(masked, 0, stop)):
        # 대상이 다음 토큰의 낱말 — 토큰 혼자 읽으면 그 낱말이 피연산자로 남음
        return None, False
    out = _shlex_words(text[:stop])
    return (out, stop < len(again)) if out is not None else (None, False)


def _reread_times(words: tuple[str, ...] | None, depth: int) -> tuple[str, ...] | None:
    """`words` 를 `depth` 번 다시 파싱한 것(:func:`_reread`)."""
    for _ in range(depth):
        words, _cut = _reread(words)
    return words


class _RereadIndex(NamedTuple):
    """겹의 토큰을 다시 파싱한 것 — :meth:`_Level.reread_index` 참조."""

    reread: list[tuple[tuple[str, ...] | None, bool]]
    flat: list[str]
    offsets: list[int]
    stops: list[int]


@lru_cache(maxsize=8)
def _heredoc_intros(command: str) -> tuple[int, ...]:
    """heredoc 도입부(`<<`)가 서는 자리, 오름차순."""
    return tuple(sorted(a for a, _b, kind in _shell_regions(command) if kind == "heredoc-open"))


def _between(points: tuple[int, ...], lo: int, hi: int) -> tuple[int, ...]:
    """오름차순 `points` 중 `[lo, hi)` 에 드는 것."""
    return points[bisect_left(points, lo) : bisect_left(points, hi)]


class _Level:
    """중첩 한 겹 — 명령 전체이거나 치환 하나의 안쪽 — 의 피연산자 판. 그 겹에서 열린 치환은
    전부 불투명한 한 덩어리(`OPAQUE_CH`)로 보임.

    겹마다 한 번 만들고 그 겹의 호출 전부가 읽음. 한 명령에 호출이 많으면 저마다 명령 끝까지
    가는 피연산자 영역을 가질 수 있고, 영역마다 새로 가르면 길이의 제곱임. 인용 밖에서 이
    판의 공백은 셸이 가르는 공백이고 인용된 텍스트는 공백 없는 덩어리라, 토큰마다 혼자
    갈리면 토큰별로 가른 낱말이 영역 전체를 가른 낱말과 같음. 혼자 안 갈리는 토큰이 있으면
    영역을 통째로 읽음.

    텍스트 쪽은 `operand_words` 가 낱말로 치지 않는 것을 미리 지움 — 리다이렉션과 그 대상,
    heredoc 도입부와 구분자. 리다이렉션은 마스크에서도 지움: `>|`·`&>` 의 `|`·`&` 가 구분자로
    남으면 피연산자가 거기서 끊김. 낱말 안의 줄이음은 `_JOIN_FILL` 로 채워 두고 가를 때 지움.
    """

    def __init__(self, command: str, masked: str, k: int) -> None:
        starts, ends, closes, _parents = _substitution_tree(masked)
        if k < 0:
            self.lo, self.hi = 0, len(command)
        else:
            self.lo = starts[k] + (1 if masked[starts[k]] == BT_CH else 2)
            self.hi = closes[k]
        lo, hi = self.lo, self.hi
        mask = list(masked[lo:hi])
        text = list(_blanked_view(command)[lo:hi])
        kids = _children(masked).get(k, ())
        for c in kids:
            a, b = starts[c] - lo, min(ends[c], hi) - lo
            mask[a:b] = text[a:b] = OPAQUE_CH * (b - a)
        level_mask = "".join(mask)
        for a in _between(_heredoc_intros(command), lo, hi):
            m = _HEREDOC_RE.match(command, a)
            if m and level_mask[a - lo] != OPAQUE_CH:
                text[a - lo : min(m.end(), hi) - lo] = " " * (min(m.end(), hi) - a)
        for m in _REDIRECTION_RE.finditer(level_mask):
            mask[m.start() : m.end()] = text[m.start() : m.end()] = " " * (m.end() - m.start())
        for m in _LINE_JOIN_RE.finditer(command, lo, hi):
            if level_mask[m.start() - lo] != OPAQUE_CH and _joins_a_word(
                command, m.start(), m.end()
            ):
                for i in range(m.start() - lo, m.end() - lo):
                    text[i] = _JOIN_FILL
                    if mask[i] == " ":
                        mask[i] = _JOIN_FILL
        self.mask, self.text = "".join(mask), "".join(text)
        tokens = [(m.start() + lo, m.end() + lo) for m in re.finditer(r"\S+", self.mask)]
        self.starts = tuple(a for a, _b in tokens)
        self.ends = tuple(b for _a, b in tokens)
        # 토큰의 낱말은 처음 읽힐 때 한 번 가름 — 어느 호출의 영역에도 들지 않는 토큰까지
        # 가르면 상수배만 커짐
        self._words: list = [_UNREAD] * len(tokens)
        self.comments = tuple(
            a for a in _between(_comment_starts(command), lo, hi) if self.mask[a - lo] != OPAQUE_CH
        )
        self.separators = tuple(m.start() + lo for m in _SEPARATOR_RE.finditer(self.mask))
        self.breaks = tuple(m.start() + lo for m in _COMMAND_BREAK_RE.finditer(self.mask))
        self._reread_index: _RereadIndex | None = None
        # `case` 패턴의 `)` 는 마스크에서 치환을 일찍 닫음 — 그 뒤는 셸이 안에서 돌리는데도
        # 이 겹의 텍스트로 읽힘
        self.risky = tuple(
            starts[c] for c in kids if re.search(r"\bcase\b", command[starts[c] : ends[c]])
        )

    def word(self, k: int) -> tuple[str, ...] | None:
        """토큰 k 가 혼자 갈리는 낱말들. shlex 가 못 가르면 None."""
        if self._words[k] is _UNREAD:
            self._words[k] = self.split(self.starts[k], self.ends[k])
        return self._words[k]

    def lead(self, start: int) -> list[str]:
        """`start` 의 `git` 앞에 선, 자기 단순 명령의 낱말들(마스크 위)."""
        b = bisect_right(self.breaks, start) - 1
        lead = self.mask[(self.breaks[b] + 1 if b >= 0 else self.lo) - self.lo : start - self.lo]
        return lead.replace(_JOIN_FILL, "").split()

    def heads_command(self, start: int) -> bool:
        """`start` 의 `git` 이 자기 단순 명령의 프로그램인가 — 그 앞에 대입과
        `_UNPARSED_PREFIXES` 만 섬. 호출 탐지용 `at_command_start` 는 일부러 넓어
        (`eval A=1 git …` 도 명령 자리) 버리는 판정에 쓰면 다시 파싱돼 도는 머지를 버림."""
        return all(_runs_unparsed(w) for w in self.lead(start))

    def region(self, start: int, end: int) -> tuple[int, int, int]:
        """영역 `[start, end)` 가 닿는 토큰 `[i, j)` 와, 이 겹에서의 영역 끝."""
        end = min(end, self.hi)
        return bisect_right(self.ends, start), bisect_left(self.starts, end), end

    def piece(self, k: int, start: int, end: int) -> tuple[str, ...] | None:
        """토큰 k 의 낱말 — 영역 `[start, end)` 가 토큰을 자르면 잘린 채로 읽음."""
        if start <= self.starts[k] and self.ends[k] <= end:
            return self.word(k)
        return self.split(max(self.starts[k], start), min(self.ends[k], end))

    def reread_index(self) -> _RereadIndex:
        """토큰마다 다시 파싱한 낱말(`_reread`), 그 낱말을 이어 놓은 목록과 토큰별 오프셋, 그리고
        토큰마다 그 자리나 뒤에서 구분자·주석이 끊거나 갈리지 않는 첫 토큰. 겹마다 한 번 만듦 —
        `eval` 뒤 호출마다 새로 만들면 호출 연쇄가 길이의 제곱을 여러 번 치름."""
        if self._reread_index is None:
            reread = [_reread(self.word(k)) for k in range(len(self.starts))]
            flat: list[str] = []
            offsets = [0]
            for words, _cut in reread:
                flat.extend(words or ())
                offsets.append(len(flat))
            stops = [len(reread)] * (len(reread) + 1)
            for k in range(len(reread) - 1, -1, -1):
                words, cut = reread[k]
                stops[k] = k if words is None or cut else stops[k + 1]
            self._reread_index = _RereadIndex(reread, flat, offsets, stops)
        return self._reread_index

    def reparsed_once(self, start: int, end: int, i: int, j: int) -> tuple[list[str], int] | None:
        """:func:`_reparsed_operands` 의 한 번 더 파싱을 색인에서 토큰 단위로 읽음. 혼자 안
        갈리는 토큰이 있으면 None."""
        out: list[str] = []
        lo = i + (i < j and self.starts[i] < start)
        hi = max(lo, j - (self.ends[j - 1] > end if i < j else 0))
        # 영역이 자르는 토큰은 혼자 읽고, 그 사이 토큰은 색인에서 읽음
        for k in [*range(i, lo), None, *range(hi, j)]:
            if k is None:
                index = self.reread_index()
                s = min(index.stops[lo], hi) if lo < hi else lo
                out += index.flat[index.offsets[lo] : index.offsets[s]]
                if s == hi:
                    continue
                k, (words, cut) = s, index.reread[s]
            else:
                words, cut = _reread(self.piece(k, start, end))
            if words is None:
                return None
            out += words
            if cut:
                return out, self.ends[k]
        return out, end

    def risky_between(self, start: int, end: int) -> bool:
        """마스크가 일찍 닫았을 수 있는 치환이 `[start, end)` 에서 열리는가."""
        i = bisect_left(self.risky, start)
        return i < len(self.risky) and self.risky[i] < end

    def split(self, start: int, end: int) -> tuple[str, ...] | None:
        """이 겹의 `[start, end)` 가 갈리는 낱말들. shlex 가 못 가르면 None."""
        return _shlex_words(self.text[start - self.lo : end - self.lo].replace(_JOIN_FILL, ""))


@lru_cache(maxsize=16)
def _levels(command: str, masked: str) -> dict[int, _Level]:
    """지금까지 만든 `command` 의 겹들 — 그것이 든 치환의 번호로."""
    return {}


def _level(command: str, masked: str, start: int) -> _Level:
    """피연산자가 `start` 에서 시작되는 단순 명령이 속한 겹 — `start` 를 감싼 가장 안쪽
    치환의 안, 없으면 명령 전체."""
    starts, ends, _closes, parents = _substitution_tree(masked)
    k = bisect_left(starts, start) - 1
    while k >= 0 and ends[k] <= start:
        k = parents[k]
    levels = _levels(command, masked)
    if k not in levels:
        levels[k] = _Level(command, masked, k)
    return levels[k]


def operand_words(
    command: str, masked: str, start: int, end: int, limit: int | None = None
) -> list[str]:
    """`command[start:end]` 가 담은 낱말들 — 셸이 가르는 대로. `limit` 이 있으면 앞의 그만큼만.

    원본이 아니라 인용을 살린 판에서 가져오되, 구간은 **마스크**에서 쟀으므로 원본 조각이
    마스크가 덮은 span 의 닫는 구분자를 실어 올 수 있음. 그러면 shlex 가 거기서 터지고, 그
    예외는 "여기 merge 없음"으로 읽혀 fail-CLOSED 판정이 통째로 사라짐. 줄이음도 함께
    지움 — 개행 앞의 `\\` 는 낱말이 아님.

    **리다이렉션은 낱말이 아님.** `shlex` 는 `>` 에서 안 끊으므로 `git merge>/dev/null
    --no-ff fix/x` 의 소스가 `>/dev/null` 이 되고, `--no-ff>/dev/null` 은 플래그 이름이
    통째로 달라짐 — 어느 쪽이든 규칙이 매칭되지 않아 fail-CLOSED 판정이 사라짐(실측:
    러너 exit 0, 실제 git 은 부모 둘짜리 머지 커밋을 만듦). 자리는 **마스크**에서 찾음
    — 인용된 `'>'` 는 리다이렉션이 아니라 인자.

    **치환은 낱말 하나**(`OPAQUE_CH` 덩어리) — 그 안의 `;`·`)`·주석·따옴표가 영역을 끊거나
    shlex 를 터뜨리면 `git merge fix/x $(true) --no-ff` 가 플래그를 잃고,
    `-m "Release $(date +%F)"` 를 든 머지는 아예 안 읽힘.
    """
    level = _level(command, masked, start)
    i, j, end = level.region(start, end)
    if i >= j:
        return []

    def piece(k: int) -> tuple[str, ...] | None:
        return level.piece(k, start, end)

    def whole() -> list[str]:
        # 혼자 안 갈리는 토큰은 마스크가 공백을 남긴 한 낱말의 조각일 수 있음 — 통째로 읽음
        out = list(level.split(start, end) or ())
        return out if limit is None else out[:limit]

    head = piece(i)
    if head is None:
        return whole()
    out = list(head)
    for k in range(i + 1, j):
        if limit is not None and len(out) >= limit:
            return out[:limit]
        words = level.word(k) if k < j - 1 else piece(k)
        if words is None:
            return whole()
        out.extend(words)
    return out if limit is None else out[:limit]


def _reparsed_operands(
    command: str, masked: str, start: int, end: int, depth: int
) -> tuple[list[str], int] | None:
    """`command[start:end]` 의 피연산자를 `depth` 번 더 파싱한 낱말과 그것이 끝나는 자리 —
    두 번째 파싱이 세우는 첫 구분자·주석을 든 토큰의 끝, 없으면 `end`. 갈리지 않으면 None."""
    level = _level(command, masked, start)
    i, j, end = level.region(start, end)
    if depth == 1:
        once = level.reparsed_once(start, end, i, j)
        if once:
            return once
    # 두 토큰에 걸친 인용, 또는 두 번째 `eval` — 영역을 통째로 다시 파싱
    words = _reread_times(tuple(operand_words(command, masked, start, end)), depth)
    return (list(words), end) if words is not None else None


def reparse_depth(command: str, masked: str, head: int, start: int) -> int:
    """`head` 의 `git` 피연산자(`start` 부터)가 그것이 돌기 전 몇 번 더 파싱되는가 —
    :func:`_reparse_depth`. 0 이면 적힌 대로 돎."""
    return _reparse_depth(_level(command, masked, start).lead(head))


def call_operands(
    command: str, masked: str, head: int, start: int, end: int, limit: int | None = None
) -> tuple[list[str], int]:
    """`head` 의 `git` 호출의 피연산자 낱말과 그것이 끝나는 자리 — 셸이 실제로 넘기는 대로.

    `eval`·`watch`·`ssh` 뒤면 그 인자가 한 번 더 파싱되므로 거기서 인용된 구분자나 `#` 가
    호출을 끝냄 — `eval git merge feature/a ';' git merge --squash feature/x` 의 앞 머지는
    `--squash` 를 갖지 않음. 다시 파싱한 것이 갈리지 않으면 적힌 대로 읽음."""
    depth = reparse_depth(command, masked, head, start)
    if depth:
        reparsed = _reparsed_operands(command, masked, start, end, depth)
        if reparsed:
            words, stop = reparsed
            return (words if limit is None else words[:limit]), stop
    return operand_words(command, masked, start, end, limit=limit), end


def operand_end(command: str, masked: str, start: int, end: int | None = None) -> int:
    """`start` 에서 피연산자가 시작되는 단순 명령이, 낱말 받기를 그만두는 자리.

    명령의 낱말은 다음 명령을 여는 구분자에서, 또는 주석에서 끝남. 입력 끝까지 읽으면 뒤
    명령의 플래그가 이 명령 것으로 합쳐지고, 주석에 적힌 `--squash` 가 그 플래그를 **요구**
    하는 정책 행을 만족시킴.
    구분자는 **마스크**에서 찾음 — 메시지나 heredoc 본문 안의 것은 아무것도 끝내지 않음.
    원본에서 자르면 따옴표 한가운데가 끊겨 shlex 가 터지고, merge 판정 전체가 FAIL-OPEN
    함(실측 — 이 repo 의 승격 머지가 바로 다중 줄 `-m`).

    명령을 감싼 치환이 닫히는 자리에서도 끝남 — `)` 든 닫는 백틱이든. 지나쳐 읽으면 백틱
    연쇄의 머지마다 명령의 나머지 전부를 피연산자로 가져감. 피연산자 사이에서 **열린**
    치환은 그 낱말 하나이고, 그 안의 `;`·`)`·주석은 아무것도 끝내지 않음.
    구분자·주석 자리는 겹마다 한 번 모아 둠 — 호출마다 다시 훑으면 길이의 제곱.
    """
    level = _level(command, masked, start)
    stop = min(len(command) if end is None else end, level.hi)
    c = bisect_left(level.comments, start)
    if c < len(level.comments) and level.comments[c] < stop:
        stop = level.comments[c]
    s = bisect_left(level.separators, start)
    if s < len(level.separators) and level.separators[s] < stop:
        return level.separators[s]
    return stop


def runs_among_operands(command: str, masked: str, calls: list[tuple[int, int]]) -> list[bool]:
    """`(git 자리, 피연산자 시작)` 순으로 놓인 merge·pull·switch·checkout 호출마다 버릴지 —
    앞 호출의 피연산자 사이에 **인자로 적혀** 돌지 않으면 버림.

    같은 겹에서 앞 호출의 피연산자 영역 안에 선 `git …` 은 그 단순 명령의 인자임. 버리는
    것은 그 앞 호출이 **자기 명령의 프로그램**일 때뿐(`_Level.heads_command`) —
    `git switch dev git merge x` 의 머지는 돌지 않음. 앞에 다른 낱말이 서면(대입 사이에
    섞여도) 버리지 않음: `eval`·`watch`·`ssh` 는 인자를 다시 파싱하고, 그때 치환의 **출력**도
    구분자가 됨 — `eval $(true) git merge --squash feature/a $(echo ';') git merge
    feature/x` 는 bash 가 뒤 머지를 실제로 돌림. 다시 파싱하는 낱말을 목록으로 세면 빠진
    이름 하나가 게이트를 끄므로, 버리는 쪽을 목록(프로그램 자리)으로 둠.
    `case` 를 담은 치환이 사이에 있으면 마스크가 그것을 일찍 닫았을 수 있어 버리지 않음.

    남긴 호출은 앞 호출의 영역 안에 서도 피연산자를 자기 `operand_end` 까지 읽음 — 뒤
    호출 머리에서 끊으면 치환 출력의 따옴표가 뒤 호출을 `-m` 값으로 삼킨 머지
    (``eval `true` git merge fix/a `echo '-m"'` git switch y `echo '"'` --no-ff``)가
    `--no-ff` 를 잃음. 그래서 프로그램이 아닌 낱말 뒤에 호출이 늘어선 명령은 호출마다
    영역 끝까지 읽어 길이의 제곱 — 의도된 잔여이고, 훅 타임아웃에 닿는 것은 수백 KB
    명령뿐(실측·예산은 `tests/gate_check/test_merge_substitutions.py`).
    """
    covered: dict[int, tuple[int, int, bool]] = {}
    out: list[bool] = []
    for head, operands in calls:
        level = _level(command, masked, operands)
        start, cover_end, heads = covered.get(level.lo, (0, -1, False))
        if head < cover_end:
            if heads and not level.risky_between(start, head):
                out.append(True)
                continue
            # 프로그램 자리가 아닌 앞 호출이면 다시 파싱될 수 있고, 일찍 닫혔을 수 있는 치환
            # 안이면 앞 호출의 인자가 아니라 치환 안의 명령 — 어느 쪽이든 앞 호출의 영역은
            # 그대로 두어야 그것이 이 호출 뒤에 도는 것으로 읽힘
        else:
            covered[level.lo] = (
                operands,
                operand_end(command, masked, operands),
                level.heads_command(head),
            )
        out.append(False)
    return out


# 명령을 여는 구분자와, 명령 **앞에 붙는** 낱말. 후자를 안 받으면 `time git … commit`
# `if …; then git …` `for …; do git …` `env VAR=1 git …` 가 호출로 안 보이고, 그러면
# 아래 답 집합이 모호로 떨어져 워크트리 재지정이 사라짐 — main 이 깨끗하면 러너가
# 아무것도 안 하고 exit 0 함(실측). 대입 접두(`VAR=1 git …`)도 같은 자리.
# 조건·반복을 **여는** 낱말도 같은 자리 — `if`·`while`·`until` 이 빠져 있어
# `if git commit -m x; then :; fi` 가 명령 자리로 안 보였고, 그물 쪽 `_COMMAND_START` 는
# 예약어를 명령 자리로 인정하므로 같은 물음에 두 판정이 반대로 답했음(러너 exit 0, 실측:
# 실제 bash 는 커밋을 만듦). `case x in x) …` 의 `)` 도 명령을 여므로 구분자에 넣음 —
# 없으면 `parse_merge_commands` 가 비어 merge 전략 판정이 통째로 사라짐(실측).
_CMD_OPENERS = ";&|\n\r({`)"
_CMD_PREFIX_WORDS = frozenset(
    {
        "then",
        "else",
        "elif",
        "if",
        "while",
        "until",
        "do",
        "time",
        "!",
        "sudo",
        "env",
        "nohup",
        "command",
        "exec",
        "nice",
    }
)
_ASSIGN_PREFIX = re.compile(r"^[A-Za-z_]\w*=")
# 프로그램 앞에 서는 리다이렉션 낱말 — `>x`·`2>&1`·`<in`·`>>log`. `<`·`>` 는 `_CMD_OPENERS`
# 가 아니므로(그 자리에서 명령이 시작되지는 않음) 낱말로 남고, 여기서 접두로 받음.
_REDIRECTION = re.compile(r"^[0-9]*(?:<|>)")
# 리다이렉션 연산자와 그 대상, 마스크 위 — 피연산자를 셀 때 지움. `>|` 의 `|`, `>&`·`&>` 의 `&` 는
# 아무것도 가르지 않음: 낱말로 읽으면 `git merge >|o --no-ff fix/x` 가 `>` 라는 소스를 머지하고 `|`
# 뒤 플래그를 잃음. heredoc 의 `<<`·`<<-` 는 구분자째 지움(본문은 자기 판독기가 읽음) — `<<<`·`<<`
# 는 `<` 보다 먼저 한 연산자로 읽음: `<` 셋으로 쪼개면 앞의 둘이 대상 없는 리다이렉션이 되어 다시
# 파싱된 here-string 이 삼킨 플래그를 머지 것으로 셈. 프로세스 치환의 `<(`·`>(` 는 두지
# 않음(낱말임). fd(`2>`·`{fd}>`)는 홀로 선 낱말일 때만 셈(bash 는 `fix2>o` 를 그렇게 읽음) — 그래서
# `--no-ff>/dev/null` 에서 플래그 이름은 남음. fd 런의 앞 경계를 lookbehind 로 묶어 둬 낱말
# 시작에서만 런을 먹음(안 묶으면 숫자 런마다 2차). `target` 이 빈 리다이렉션은 다시 파싱될 때 다음
# 낱말을 대상으로 가져감.
_REDIRECTION_RE = re.compile(
    r"(?:(?<![^\s;&|()])(?:[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\}))?"
    r"(?:&>>?|>>|>\||[<>]&|<>|<<<|<<-?|>(?!\()|<(?!\())"
    r"""(?P<target>[ \t]*(?:'[^']*'|"[^"]*"|[^\s;&|()<>'"])+)?"""
)


def _blank_redirections(text: str, masked: str) -> tuple[str, str]:
    """`text` 와 그 마스크에서 마스크가 보이는 리다이렉션을 대상째 공백으로 지운 것."""
    t, m = list(text), list(masked)
    for r in _REDIRECTION_RE.finditer(masked):
        t[r.start() : r.end()] = m[r.start() : r.end()] = " " * (r.end() - r.start())
    return "".join(t), "".join(m)


def at_command_start(text: str, i: int) -> bool:
    """`text[i]` 가 새 명령이 시작되는 자리인가. `text` 는 마스크여야 함.

    마스크가 인용·본문·주석을 이미 지우므로 여기 남는 일은 **인용되지 않은 낱말**뿐 —
    `echo git commit done` 처럼. 그걸 두 번째 호출로 세면 모호 판정이 발동해 재지정을 잃음.
    반대로 진짜 호출을 놓쳐도 같은 값을 치르므로, 명령 앞 낱말은 받아 줌.

    잔여: `git` 바로 앞에 **대입꼴 토큰**이 선 인용 밖 텍스트(`echo a=1 git commit`)는
    여전히 호출로 세어져 모호 판정을 부름. 방향은 FAIL-OPEN 이고 실제로 발행되는 명령
    모양이 아님 — 주석과 메시지는 `mask_literals` 가 이미 끊음.
    """
    while True:
        j = i - 1
        while j >= 0 and text[j] in " \t":
            j -= 1
        if j < 0 or text[j] in _CMD_OPENERS:
            return True
        end = j + 1
        while j >= 0 and text[j] not in " \t" and text[j] not in _CMD_OPENERS:
            j -= 1
        word = text[j + 1 : end]
        if not word.endswith(("/", "\\")):
            return (
                word in _CMD_PREFIX_WORDS
                or bool(_ASSIGN_PREFIX.match(word))
                # 리다이렉션도 프로그램 **앞에** 서는 낱말. 안 받으면
                # `>/dev/null git merge --no-ff fix/x` 가 명령 자리로 안 보여 merge 전략
                # 판정이 통째로 사라짐(실측: 러너 exit 0, 실제 bash 는 머지함).
                or bool(_REDIRECTION.match(word))
            )
        # 디렉터리 접두는 **같은 프로그램**을 부름(`/usr/bin/git`). 러너의 거친 필터는 그
        # 철자를 이미 넘기므로, 여기서만 떨어뜨리면 게이트는 돌면서 ROOT 가 main 에 남음 —
        # 깨끗한 main 에서 조기 종료하며 미분류 커밋이 통과(실측). 접두가 **구분자로
        # 끝날 때만** 받으므로 `mygit`·`foo.git` 은 계속 아님.

        # 정규식이 아니라 여기서 보는 것은 성능 때문: 선택적 접두를 패턴에 넣으면 매
        # 위치마다 되감아 전체가 2차가 되고(800회 반복 0.2ms → 331ms, 실측), 훅에서의 2차는
        # 타임아웃 = 조용한 게이트 스킵. 여기선 매치된 자리에서만 도니 O(낱말).
        i = j + 1  # 접두 앞자리를 다시 봄. i 가 매번 왼쪽으로 가므로 반드시 끝남


def unquote_path(word: str) -> str:
    """셸 단어 하나에서 따옴표를 벗긴 경로. `"$WT"/wt` → `$WT/wt`."""
    return "".join(
        m.group(1) or m.group(2) or m.group(3) or m.group(4) or ""
        for m in _PATH_PIECE.finditer(word)
    )


def dash_c_value(command: str, masked: str, start: int, end: int) -> str | None:
    """옵션 영역 `command[start:end]` 의 `-C <dir>`. 없으면 None.

    자리는 **마스크**에서 찾아 값 안의 `-C` 를 옵션으로 오인하지 않고, 경로는 그 오프셋의
    **원본**에서 읽어 따옴표가 살아 있게 함.

    `-C` 가 여럿이면 마지막을 돌려줌 — git 이 누적 해석하므로(`-C /a -C sub` → `/a/sub`)
    실효 디렉터리를 좌우하는 것이 마지막. 상대 경로가 섞이면 실제 대상과 어긋날 수 있고,
    그 해석은 훅 프로세스 cwd 기준으로 풀림.
    """
    last = None
    for d in _DASH_C_RE.finditer(masked, start, end):
        last = d
    if last is None:
        return None
    # 토큰의 **범위**도 마스크에서 잡음. 원본에서 잡으면 이스케이프한 공백에서 끊겨,
    # 문법이 한 단어로 읽은 것을 값 읽기가 반토막 내고 그 반토막이 실재하는 형제 worktree
    # 를 지목할 수 있음. 마스크는 그 공백을 이미 NUL 로 덮어 둠.
    m = _PATH_TOKEN_RE.match(masked, last.end())
    return unquote_path(command[m.start(1) : m.end(1)]) if m else None


def git_invocations(masked: str, pattern: GitSubcommand):
    """마스크 위의 **명령 자리에 선** `git … <word>` 호출들."""
    return (m for m in pattern.finditer(masked) if at_command_start(masked, m.start()))


class _UnknownDir:
    """센티널 타입: 셸 확장이나 glob 을 아직 담은 `-C` 값 — **이름을 댈 수 없는 트리**.
    맨 `object()` 대신 클래스인 것은 `_norm_dir`·`_dash_c_answers` 가 `str | None` 만
    돌려준다고 거짓말하지 않고 정직하게 타입을 적기 위함."""


_UNKNOWN_DIR = _UnknownDir()
# `$`·백틱·glob — 어느 것도 이 게이트가 읽을 수 있는 리터럴 디렉터리로 살아남지 않음.
_UNEXPANDED_RE = re.compile(r"[$`*?\[]")


def _norm_dir(d: str | None) -> str | None | _UnknownDir:
    """`-C` 값을 그것이 뜻하는 답으로 정규화.

    `.`·`./` 는 인자 없는 호출이 이미 도는 디렉터리이므로 **둘 다 "디렉터리 없음"**(None) —
    답 하나이지 둘이 아님. 이 정규화를 `_dir_from_command` 와 미해결 판정이 **함께** 써야
    함: 한쪽만 접으면 `git -C . commit && git commit --amend` 가 두 트리로 읽혀 선두 `cd` 를
    안 보고 엉뚱한 트리의 status 를 검사함.

    선두 `~` 는 펼침 — Invariant 7 은 불확실 집합을 작게 유지하라 하고, `~` 는 `$`·백틱·glob
    과 달리 뜻이 하나임. 그러고도 확장이나 glob 이 남으면 `_UNKNOWN_DIR`: 이름을 댈 수 없는
    트리라, 안 펼쳐진 텍스트가 우연히 철자한 "트리"로 읽는 대신 미해결로 둠.
    """
    if d is None or d in (".", "./"):
        return None
    if d.startswith("~"):
        d = os.path.expanduser(d)
    if _UNEXPANDED_RE.search(d):
        return _UNKNOWN_DIR
    return d


def _dash_c_answers(command: str) -> set[str | None | _UnknownDir]:
    """커밋 호출마다 그것이 지목하는 디렉터리(없거나 `.`·`./` 면 None). 답의 **집합**.
    텍스트만 읽음 — 저장소를 안 보므로 상태에 대해 오작동할 여지가 없음."""
    masked = mask_literals(command)
    return {
        _norm_dir(dash_c_value(command, masked, m.start(1), m.end(1)))
        for m in git_invocations(masked, _GIT_COMMIT_RE)
    }


def _parse_git_dash_c(command: str) -> str | None:
    r"""`git -C <dir> … commit` 의 -C 대상 디렉터리(따옴표 허용). 없거나 모호하면 None.

    git 전역 옵션 `-C` 는 서브커맨드 *앞*에 옴. 그래서 **데이터 밖(따옴표·주석·heredoc 본문
    밖) `git … commit`** 의 전역 옵션 영역에서만 읽음. 넷 다 필요:

    - `commit` 에 묶기 — `git commit -C <ref>`(reuse-message)를 배제하고, 체인의 다른
      명령(`git -C /a log && git commit`)이 낸 디렉터리를 커밋 위치로 읽지 않음.
    - 데이터 밖 — 메시지는 인자. 거기 적힌 `git -C <dir> commit` 은 텍스트이지 호출이
      아님. `mask_literals` 가 인용 구간·주석·heredoc 본문을 한꺼번에 끊음. 이 repo 는
      Invariant 7 때문에 커밋 본문에 그 명령 형태를 실제로 적음.
    - 명령 자리일 것 — 인용되지 않은 낱말(`echo git commit done`)은 호출이 아님.
    - 가리키는 트리가 하나일 것 — 호출이 여럿이어도 전부 같은 `-C` 면 모호하지 않음.
      서로 다르거나 한쪽만 `-C` 를 들면 진짜로 모호하니 추측하지 않고 None 으로 답함.
      여기서 None 을 남발하면 안 됨: ROOT 가 main 으로 떨어져 main 이 더러우면 정상
      커밋을 오차단하고 깨끗하면 게이트가 통째로 건너뛰어짐(양방향 실패).

    잘못 읽으면 ROOT 가 커밋이 돌지 않는 트리를 가리켜 그 트리의 status·티어 마커·
    스테이징 파일을 검사 — 분류된 커밋을 새로 막고 미분류 커밋을 통과시킴."""
    answers = _dash_c_answers(command)
    if len(answers) != 1:
        return None
    only = answers.pop()
    return only if isinstance(only, str) else None


# 커밋 경로 전용 선두 `cd` 접두 — `&&` 뿐 아니라 `;`·개행으로 끝나는 것도 읽음. `;`/개행
# 꼴도 `&&` 와 똑같이 커밋이 **실제로 떨어지는** 트리를 지목하므로, 안 읽으면 훅 cwd 기준의
# 미분류 차단이 남음(오차단). 한계: `;` 에서는 `cd` 가 실패해도 셸이 제자리에 남는데 이
# 판정은 X 를 기준으로 함 — 그 오차단이 흔한 쪽이라 넓히는 것이 순이득.
# 경로 토큰은 `_WORD` 조각을 그대로 공유하되(rule-dry-constants — `_PATH_TOKEN` 은 그 조각을
# 자기 캡처 그룹으로 이미 감싼 것이라 여기서는 조각을 직접 씀) **게으르게** 반복함.
# 뒤 구분자를 같은 정규식이 함께 보므로 `cd /x;git commit` 의 토큰이 `/x` 로 끝남 — 따로 보면
# `/x;git` 이 됨. 게으름이 더 필요한 것은 `cd /a;b;git commit` 때문: 탐욕이면 첫 `;` 를 지나쳐
# `/a;b` 를 답하는데 셸이 실제로 옮겨 가는 곳은 `/a` 임(없는 디렉터리라 fail-open 이지만,
# 해석기가 답을 아예 못 내는 것과 틀린 답을 내는 것은 다름).
# `\A` 는 **성능 계약**이기도 함. 이 패턴은 선두 전용이라 두 호출자 다 `match` 를 쓰지만,
# 앵커가 호출 방식에만 있으면 `search` 를 쓰는 다음 호출자가 조용히 2차를 얻음 — 선두 `\s*`
# 가 자리마다 공백 연속을 통째로 먹고 한 칸씩 되감음(`search` 로 공백 16000 에서 0.34초,
# `match` 는 0.0005초, 실측). 앵커를 패턴에 두면 둘이 같은 답·같은 비용.
_CD_PREFIX_RE = re.compile(rf"""\A\s*cd\s+({_WORD}?)\s*(?:&&|[;\n])""")


def _leading_cd_answer(command: str) -> str | None | _UnknownDir:
    """선행 `cd <dir>` 뒤에 `&&`·`;`·개행이 선 것의 디렉터리 — `-C` 와 **같은 정규화**를 지남.

    같은 정규화여야 하는 이유는 훅이 셸 확장 **전** 텍스트를 받기 때문임. `-C` 쪽만 덮으면
    `cd $WT && git commit` 의 `$WT` 가 디렉터리 이름으로 나가고, 해석기가 그런 트리를 못 찾아
    ROOT 를 깨끗한 프로젝트 디렉터리에 남김 — 러너가 거기서 조기 종료해 진짜 커밋에서 게이트가
    통째로 빠짐(실측: 펼친 대조군은 러너 exit 2, 안 펼친 쪽은 0).

    같은 정규화가 `~` 도 펼치므로 `cd ~/wt && git commit` 은 이제 그 worktree 를 지목함 —
    전에는 `~/wt` 라는 이름의 디렉터리를 찾아 실패했고 ROOT 가 프로젝트 디렉터리에 남았음.
    그 트리가 더러우면 **전에는 안 막던 것을 막음**(실측: 러너 exit 0 → 2). Invariant 7 의
    "새로 차단하면 안 됨" 이 금지하는 것은 커밋이 돌지 않는 트리를 읽어 생기는 **오**차단이고,
    이쪽은 커밋이 실제로 떨어지는 트리를 정확히 읽어 내는 것임 — `git -C ~/wt commit` 이
    이미 같은 답을 내고 있었으니 두 철자가 이제 일치함.
    """
    m = _CD_PREFIX_RE.match(command)
    if not m:
        return None
    return _norm_dir(unquote_path(m.group(1)))


def _parse_leading_cd(command: str) -> str | None:
    """선행 `cd` 가 지목하는 트리. 이름을 댈 수 없으면(안 펼쳐진 값) None."""
    answer = _leading_cd_answer(command)
    return answer if isinstance(answer, str) else None


def _dir_from_command(command: str) -> str | None:
    """커밋의 실행 디렉터리(결정론적 신호). ① `git -C <dir>` → ② 선행 `cd <dir>`.

    ②는 **어떤 호출도 `-C` 를 들지 않았을 때만** 봄. 호출들이 서로 다른 트리를 지목하면
    답이 없는 것이고, 거기서 선행 `cd` 로 흘러가면 아무 호출도 지목하지 않은 세 번째 트리를
    ROOT 로 삼게 됨 — Invariant 7 은 모호를 추측이 아니라 읽기 종료로 끝내라고 함.
    확장이나 glob 이 남은 `-C` 값(`_norm_dir` → `_UNKNOWN_DIR`)도 이름을 댈 수 없는 트리라
    같은 답 — 안 펼쳐진 텍스트를 그대로 디렉터리로 내놓지 않음.
    """
    if not command:
        return None
    answers = _dash_c_answers(command)
    if _UNKNOWN_DIR in answers:  # 읽을 수 없는 `-C` 값 — 다음 사다리로 내려가지도 않음
        return None
    if len(answers) == 1:
        only = next(iter(answers))
        if isinstance(only, str):  # None("디렉터리 안 지목")을 걸러 냄
            return only
    elif answers:  # -C 를 든 호출이 있었는데 답이 하나가 아님 — 추측하지 않음
        return None
    return _parse_leading_cd(command)


def _cd_hop_before_bare_commit(command: str, masked: str) -> bool:
    """선두 `cd X &&`·`;` 접두 **밖의** `cd`·`pushd`·`popd` 가 인자 없는 커밋 앞에 서는가.

    선두 접두는 읽음(그것이 커밋이 떨어지는 트리를 지목). 그 뒤의 이동은 커밋이 떨어지는
    트리를 바꾸는데 해석기가 따라가지 않으므로, 그 대상은 이름을 댈 수 없는 트리임.
    서브셸 `(cd X && …)` 도 이동임 — `(` 는 명령 시작이지 선두 접두가 아님.
    """
    lead = _CD_PREFIX_RE.match(command)
    lead_end = lead.end() if lead else 0
    bare = [
        m.start()
        for m in git_invocations(masked, _GIT_COMMIT_RE)
        if _norm_dir(dash_c_value(command, masked, m.start(1), m.end(1))) is None
    ]
    if not bare:
        return False
    return any(
        name in ("cd", "pushd", "popd") and s > lead_end and any(s < c for c in bare)
        for name, s, _e in _program_spans(masked)
    )


def _net_only_commit(command: str, masked: str) -> bool:
    """마스크의 문법은 못 보고 :func:`is_invocation` 의 나머지 읽기만 보는 커밋이 든 원소가
    있는가 — 인터프리터가 받은 스크립트, 또는 인용으로 쪼개진 낱말. 디렉터리 판독기는 마스크를
    걸으므로 그 커밋의 `-C` 도 그 앞의 이동도 못 봄."""
    return any(
        not _GIT_COMMIT_RE.search(masked[a:b]) and is_invocation(command[a:b], "commit")
        for a, b in _list_elements(command, masked)
    )


def commit_tree_unresolved(command: str | None) -> bool:
    """커밋이 **이름을 댈 수 없는 곳**에서 도는가. 다섯:

    - 호출들이 서로 다른 트리를 지목함
    - 그중 하나가 풀 수 없는 트리를 지목함(안 펼쳐진 `-C`)
    - 인자 없는 커밋이 타고 있는 **선두 `cd`** 의 값이 안 펼쳐짐
    - 따라갈 수 없는 `cd`·`pushd`·`popd` 가 인자 없는 커밋이 떨어질 트리를 바꿈
    - 디렉터리 판독기가 아예 못 보는 커밋 — 인터프리터에 건넨 스크립트 안, 또는 인용·
      백슬래시가 쪼갠 낱말(`com''mit`·`c\\ommit`)

    그 경우에도 `working_root` 는 무언가로 답함 — Invariant 7 이 그러라고 함(main, 또는
    명령이 답을 못 주면 훅 자신의 cwd 에서 닿는 worktree). 어느 쪽도 커밋이 **어디 떨어지는지**
    에 대한 읽기가 아님: 명령이 트리를 둘 이상 대거나, 인자 없는 호출이 셸 자신의 디렉터리를
    거기 더하거나, 이동·풀 수 없는 `-C` 는 아예 이름을 못 대는 것임. 그래서 해석기가 어느
    트리를 돌려주든 그것이 깨끗하다는 사실은 이 명령이 커밋하는지에 대해 아무것도 말하지
    않고, 그걸 "게이팅할 것 없음"으로 읽는 호출자는 진짜 커밋에서 게이트를 통째로 건너뜀 —
    이 게이트가 결코 틀리면 안 되는 방향. 추측을 해석기 밖에 두려고 여기서 물음.
    """
    if not command:
        return False
    try:
        masked = mask_literals(command)
        # `_dash_c_answers` 가 `.`·`./` 를 이미 None 으로 접으므로, `git -C . commit &&
        # git commit --amend` 는 두 트리가 아님. `_UNKNOWN_DIR` 은 **혼자여도** 미해결 —
        # 원소가 하나인 `{_UNKNOWN_DIR}` 도 실재하는 트리를 하나도 못 댐.
        answers = _dash_c_answers(command)
        if len(answers) > 1 or _UNKNOWN_DIR in answers:
            return True
        # 선두 `cd` 도 같음 — 인자 없는 커밋이 그 트리에서 돌고, 값이 안 펼쳐졌으면 그 트리는
        # 이름을 댈 수 없음. `-C` 를 든 호출이 트리를 이미 지목했으면 커밋은 거기서 돌므로
        # 선두 `cd` 가 어디를 가리키든 상관없음(`_dir_from_command` 의 사다리와 같은 순서).
        if None in answers and _leading_cd_answer(command) is _UNKNOWN_DIR:
            return True
        return _cd_hop_before_bare_commit(command, masked) or _net_only_commit(command, masked)
    except Exception:
        return False  # FAIL-OPEN: 읽을 수 없는 명령은 아무것도 주장할 수 없는 명령


def _git(args: list[str], cwd: str | Path) -> str | None:
    """cwd 에서 git 을 실행해 stdout 을 반환(`-z` 목록은 원문 그대로). 어떤 실패든 None.

    조회 전용 범용 러너(비영 종료도 None) — 호출측이 "git 이 답하지 못했다"를 단일
    분기로 처리하도록. encoding="utf-8" 은 Invariant #2: Windows cp949 로캘에서 한글
    경로·커밋 제목이 디코딩 오류로 예외가 되면 게이트가 조용히 FAIL-OPEN 함.

    `errors="replace"`·`.strip()` 을 try 안에 두는 것도 같은 불변식. git 이 UTF-8 이
    아닌 blob(예: cp949 로 저장됐던 문서의 부모 리비전)을 뱉으면 strict 디코드는 리더
    스레드에서 터져 `stdout` 이 None 이 되고, try 밖의 `.strip()` 은 AttributeError 로
    호출자를 넘어 게이트 전체를 무너뜨림 — 그러면 그 커밋에서 도장뿐 아니라 drift·구조
    위반 검사까지 통째로 건너뜀. 손상 문자는 조회 결과를 못 맞추게 할 뿐이고, 그건
    "git 이 답하지 못했다"와 같은 취급으로 충분.

    `-z` 를 든 호출만 `.strip()` 을 건너뜀. NUL 로 끊는 출력에서 **첫** 경로의 선두 공백은
    이름의 일부인데 `.strip()` 이 그것을 먹어 존재하지 않는 경로를 만듦 — 그 손실은 조용해서
    그 파일만 "읽을 수 없음"으로 검사에서 빠짐. 뒤쪽 경로는 무사함: 출력이 늘 NUL 로 끝나고
    NUL 은 공백이 아니라, `.strip()` 이 마지막 이름에 닿지 못함.
    판정을 인자에서 뽑는 이유는 키워드로 두면 호출측이 잊을 수 있고 잊었는지 재는 가드가
    없기 때문. 읽는 범위는 `--` 앞까지 — 그 뒤는 경로라 `-z` 가 플래그가 아니라 파일 이름일
    수 있고, 그 이름의 파일은 실제로 만들어짐.
    """
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if out.returncode != 0:
            return None
        flags = args[: args.index("--")] if "--" in args else args
        return out.stdout if "-z" in flags else out.stdout.strip()
    except Exception:
        return None


def _git_common_dir(path: str | Path) -> str | None:
    """path 컨텍스트의 절대 git-common-dir. 실패 시 None."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            encoding=_GIT_PATH_ENCODING,
            errors="surrogateescape",
            check=True,
            timeout=3,
        )
    except Exception:
        return None
    return out.stdout.strip() or None


def _worktree_toplevel(path: str | Path) -> Path | None:
    """path 컨텍스트의 worktree toplevel(절대). 실패 시 None."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding=_GIT_PATH_ENCODING,
            errors="surrogateescape",
            check=True,
            timeout=3,
        )
    except Exception:
        return None
    top = out.stdout.strip()
    return Path(top) if top else None


def _same_repo_toplevel(candidate: str, project_dir: Path) -> Path | None:
    """candidate 가 project_dir 과 같은 repo 의 worktree면 그 toplevel, 아니면 None.

    same-repo 판정은 경로 prefix 가 아니라 git-common-dir 동일성으로 함(형제 레벨
    worktree 의 startswith 오탐 회피 — 설계 결정)."""
    cand_common = _git_common_dir(candidate)
    if cand_common is None or cand_common != _git_common_dir(project_dir):
        return None
    return _worktree_toplevel(candidate)


def working_root(
    *, project_dir: Path, hook_cwd: str | None = None, command: str | None = None
) -> Path:
    """커밋이 실제로 도는 worktree 루트. 불확실하면 project_dir 반환(FAIL-OPEN).

    탐지 사다리(결정론적 우선): ① 명령 `git -C <dir>` → ② 선행 `cd <dir> &&` →
    ③ 훅 cwd / 프로세스 cwd → ④ project_dir. 후보 디렉터리는 project_dir 과 같은
    repo(git-common-dir 동일)일 때만 채택(same-repo 안전판정 — 경로 prefix 금지).

    재지정은 후보의 worktree toplevel 이 **project_dir 자신의 toplevel 과 다를 때만**
    함(진짜 다른 worktree). 같으면 project_dir 유지 — 이게 없으면 CLAUDE_PROJECT_DIR
    이 git 루트의 *하위 디렉터리*인 레이아웃에서 평범한 커밋을 루트로 끌어올려
    tier 마커/‑config 위치가 어긋나 fail-CLOSED 오차단됨(리뷰 지적 회귀).
    """
    project_top = _worktree_toplevel(project_dir)
    if project_top is None:
        return project_dir  # project_dir 가 git 컨텍스트가 아니면 재지정 불가 → 유지
    candidates: list[str] = []
    if command:
        parsed = _dir_from_command(command)
        if parsed:
            candidates.append(parsed)
    if hook_cwd:
        candidates.append(hook_cwd)
    try:
        candidates.append(os.getcwd())
    except OSError:
        pass
    for cand in candidates:
        top = _same_repo_toplevel(cand, project_dir)
        if top is not None and top != project_top:
            return top
    return project_dir


# Windows 재파스 포인트 비트. 정션은 `Path.is_symlink()` 가 False 를 돌려주므로 이것을
# 함께 봐야 함 — 정션은 관리자 권한 없이 만들어져 심볼릭 링크보다 흔하고, `rglob` 은
# 정션을 따라감. `os.path.isjunction` 은 3.12+ 라 3.8 호스트에선 이 비트가 유일한 답.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point(path: Path) -> bool:
    """심볼릭 링크이거나 Windows 정션이면 True. 없는 경로·조회 실패는 False.

    "링크 너머는 남의 디렉터리" 판정을 한 곳에 모음 — `is_symlink()` 만 물으면 정션이
    그물을 그대로 통과해 저장소 밖 파일이 옮겨지고 남의 디렉터리가 지워짐."""
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if isjunction(path):
                return True
        except (OSError, ValueError):
            return False
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except (OSError, ValueError):
        return False
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def under_real_tree(path: Path, root: Path) -> bool:
    """root **자신을 포함해** path 까지 어느 조각도 링크가 아니면 True.

    링크 너머는 남의 디렉터리임 — `templates/alm` 이 링크면 그 안의 파일을 옮기는 것은
    호스트가 둔 적 없는 트리에서 파일을 꺼내는 일. root 를 빼면 `templates/` 자신이
    링크인 호스트가 통째로 그 구멍이 됨.

    거는 쪽은 둘: `vdev_init_setup` 이 호스트 양식을 **옮기기** 전에, `alm_docs` 가
    문서를 **덧쓰기** 전에. 소비자를 세어 두는 이유는 한쪽 계약만 보고 좁히면 다른
    쪽이 조용히 따라 움직이기 때문.

    `is_safe_template_rel` 과 **짝으로** 씀 — 그쪽은 순전한 렉시컬 판정이라 링크를
    보지 않고, 이쪽만 쓰면 `..` 를 정규화가 지운 뒤에 걸음이 시작됨."""
    if ".." in path.parts:
        return False  # 사전식 걸음은 `..` 를 되짚지 못함 — 조각으로 먼저 거름
    current = path
    while True:
        if is_reparse_point(current):
            return False
        if current == root:
            return True
        parent = current.parent
        if parent == current:
            return False  # root 밑이 아님
        current = parent


def is_safe_template_rel(value: object) -> bool:
    """`templates/` 안에 머무는 상대 경로면 True.

    거절: 문자열이 아닌 값 · 빈 값 · 절대 경로 · 드라이브·UNC 지정 · `..` 세그먼트.
    이 술어가 필요한 이유는 rel 을 **읽기에만** 쓰지 않기 때문 — `vdev_init_setup` 이
    같은 rel 로 파일을 **이동**하고 `alm_docs` 가 같은 모양의 rel 로 문서를 **덧씀**.
    `../../X` 하나가 저장소 밖 파일을 원위치에서 없애거나 고침. 판정을 정규화 전에 하는
    것도 같은 이유(정규화가 탈출을 지워 버림).

    렉시컬 판정이라 링크는 못 봄 — 쓰는 쪽은 `under_real_tree` 를 함께 걸 것."""
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.replace("\\", "/")
    if text.startswith("/") or ntpath.splitdrive(value)[0]:
        return False
    return ".." not in text.split("/")


def template_rel(name: str, spec: dict, subdir: str) -> str:
    """선언 하나(handoff 종류·ALM 계층) → templates/ 밑 상대 경로.

    `template` 이 적혔고 안전하면 그대로(확장자까지), 아니면 `<subdir>/<name>.md`.
    규칙이 한 곳인 이유는 읽는 쪽이 셋이기 때문 — handoff_resolve·alm_layers 가
    해석하고 vdev_init_setup 이 같은 rel 로 시드·이전을 정함. 사본이 갈리면 셋업이
    옮긴 파일과 스킬이 찾는 파일이 어긋남. 그 하나뿐인 자리라서 안전 판정도 여기 있음
    — 셋 중 하나만 막으면 나머지 둘이 여전히 탈출을 받음. 거절이 조용하지 않게 하는
    것은 셋업 몫(`_unsafe_template_declarations` 가 `[!]` 로 이름을 댐)."""
    value = spec.get("template")
    if isinstance(value, str) and is_safe_template_rel(value):
        return value
    return f"{subdir}/{_one_segment(name)}.md"


def _one_segment(name: str) -> str:
    """이름을 경로 **한 조각**으로 가둠.

    이름은 config 의 **키**(handoff 종류·ALM 계층)여서 값과 달리 사람이 고른 어휘가
    그대로 옴 — `../` 가 든 키 하나가 `template:` 값과 똑같이 셋업의 이동·삭제를
    저장소 밖으로 끌고 감. 구분자는 `_` 로 접고, 점만 남은 조각은 이름이 아님.

    형을 여기서 맞추는 이유는 YAML 이 `2024:`·`on:`·`~:` 를 문자열 아닌 키로 주기
    때문 — 호출부마다 `str()` 을 기억하게 두면 하나만 빠져도 그 스킬 단계가 통째로
    죽음(실측: handoff 경로가 `AttributeError` 로 exit 1)."""
    flat = str(name).replace("\\", "/").replace("/", "_").strip()
    return flat if flat and set(flat) != {"."} else "_"


def legacy_template_path(rel: str, host: Path) -> str | None:
    """구경로 `<host>/templates/<rel>` 에만 있는 호스트 양식. 없으면 None.

    호스트 사본의 자리가 `.claude/vway-kit/templates/` 로 옮겨졌으므로, 셋업을 아직
    안 돌린 저장소는 자기가 쓴 양식을 잃고 출하본으로 떨어짐. 그 폴백이 조용하지
    않게 소비자가 이 사실을 댈 수 있어야 함 — 이전이 끝난 호스트에선 None 이라 한
    번 옮기면 알림도 함께 사라짐.

    호스트가 **플러그인 SOURCE 저장소**면 조용함: 거기의 `templates/` 는 출하본이지
    누가 두고 간 오버라이드가 아니고, 알리면 권고를 따른 사람이 셋업으로 자기 출하
    SOURCE 를 VWAY_DIR 밑으로 옮기게 됨. 판정 축이 "두 루트가 같은가" 가 **아닌** 이유는
    개발자 세션이 설치 캐시를 실행해 두 경로가 늘 다르기 때문 — 물어야 할 것은 이
    저장소가 플러그인을 출하하느냐이고, 그 답은 매니페스트가 가짐."""
    if (host / PLUGIN_MANIFEST).is_file():
        return None
    if (vway_dir(host) / TEMPLATES_DIRNAME / rel).is_file():
        return None
    legacy = host / TEMPLATES_DIRNAME / rel
    return str(legacy) if legacy.is_file() else None


def templates_lookup(rel: str, host: Path, plugin: Path) -> str | None:
    """<rel> 을 호스트 우선·플러그인 폴백으로 찾음. 없으면 None.

    호스트가 같은 rel 에 파일을 두면 그것이 이김 — 팀마다 문서 양식이 다르고,
    플러그인 사본을 고치는 것은 이중 경로 규율 위반이라 덮어쓰기가 유일한 길.

    두 루트의 모양이 다름: 호스트 사본은 `.claude/vway-kit/templates/`(모든 호스트
    쓰기가 모이는 자리), 플러그인 원본은 저장소 루트 `templates/`. 호스트 쪽에서
    저장소 루트를 보지 않는 것은 그 이름이 남의 것일 수 있기 때문 — Django·Flask·
    Jekyll 프로젝트의 `templates/` 가 그 자리에 살고, 거기를 읽으면 호스트가 둔 적
    없는 파일이 요약·항목 본문 템플릿으로 승격됨.

    링크는 따라감 — 쓰기 경로(`vdev_init_setup`)가 링크 너머를 남의 트리로 보는 것과
    일부러 비대칭임. 그쪽이 막는 것은 남의 파일을 **없애는** 일이고, 읽기에는 그 피해가
    없는 대신 팀이 공유 디렉터리를 링크로 걸어 양식을 함께 쓰는 쓸모가 있음."""
    for cand in (
        vway_dir(host) / TEMPLATES_DIRNAME / rel,
        plugin / TEMPLATES_DIRNAME / rel,
    ):
        if cand.is_file():
            return str(cand)
    return None


def force_utf8_io() -> None:
    """stdin/stdout/stderr 를 UTF-8 로 재구성(Invariant #2).

    Windows 훅 환경(cp1252/cp949)에서 한글 사유 print() 가 UnicodeEncodeError 로
    깨지면 fail-open 되어 게이트가 무력화됨. PYTHONUTF8 도 설정해 자식 python
    프로세스까지 UTF-8 을 상속시킴(standalone 호출 대비).

    **stdin 도 같음.** 훅 페이로드는 UTF-8 바이트로 오는데(JSON 을 쓰는 쪽이 비-ASCII 를
    이스케이프해 준다는 보장이 없음), 로캘 코덱으로 읽으면 한글 커밋 메시지나 한글 경로에서
    `UnicodeDecodeError` 가 나고 그 예외는 최상위 핸들러가 삼켜 **판정 없이 exit 0** 함.
    러너는 판정이 없으면 스스로 게이팅하지만 worktree 재지정을 못 하므로 ROOT 가 프로젝트
    디렉터리에 남고, 그 트리가 깨끗하면 조기 종료로 진짜 커밋에서 게이트가 통째로 빠짐
    (실측: 한글 경로 worktree 커밋이 `PYTHONIOENCODING=cp949` 에서 러너 exit 0).
    러너가 자식에 주는 `PYTHONUTF8=1` 로는 못 막음 — `PYTHONIOENCODING` 이 그것을 이김(실측).
    `errors` 는 `surrogateescape`: UTF-8 모드가 stdin 에 주는 것과 같아 러너 아래에서는
    아무것도 안 바뀌고, 진짜로 UTF-8 이 아닌 바이트가 와도 판정을 죽이지 않고 살려 감.

    이 프로세스가 자식 출력을 읽는 인코딩은 못 바꿈 — UTF-8 모드는 시작 때 정해짐. 그래서
    `subprocess` 의 `text=True` 는 호출마다 `encoding=` 을 적어야 git 출력을 로캘 코드페이지로
    읽지 않음 — 텍스트는 `"utf-8"`, 루트를 정하는 경로는 `_GIT_PATH_ENCODING`.
    강제는 `tests/vway_paths/test_child_output.py`·`tests/gate_check/test_non_utf8_host.py`.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream, errors in ((sys.stdin, "surrogateescape"), (sys.stdout, None), (sys.stderr, None)):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors=errors)
            except (ValueError, OSError):  # 이미 닫혔거나 재구성 불가 → 무시
                pass
