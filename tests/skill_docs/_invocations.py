"""진짜 호출과 단순 언급의 표 — 게이트가 무엇을 붙잡아야 하는가.

출하 산문 목록과 디스패치 절 조각도 여기 삶.
"""

import re
import sys
from pathlib import Path

from tests.skill_docs._helpers import GIT_DOCS, REPO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

# `scripts/` must not linger on sys.path after this import: scripts/teams_alert.py (and
# friends) resolve `_vway_paths` with `try: import _vway_paths / except ImportError:
# import scripts._vway_paths` (see that module's docstring) so tests can `import
# scripts.xxx` as a package. A `scripts/` dir left on sys.path for the rest of the
# session flips that try-branch for every test file collected afterward (alphabetically,
# that is most of them), loading `_vway_paths` a SECOND time under a different module
# identity — `scripts.teams_alert._host_root is scripts._vway_paths.host_root` then
# reads False even though both come from the same file.
sys.path.pop(0)


REAL_INVOCATIONS = [
    "git commit -m x",
    "git -C '/c/My Work/wt' commit -F -",
    'git -C "/c/My Work/wt" commit -F -',
    'git -C "/c/My Work"/wt commit -F -',
    r"git -C /home/o\'b/wt commit -m x",
    r"""git -C '/a/o'\''b' commit -F -""",
    r'git -c user.name="a\"b" commit -m x',
    r"git -C /tmp/My\ Project/wt commit -m x",
    "/usr/bin/git -C /a/wt commit -m x",
    "C:/Git/bin/git commit --amend --no-edit",
    "git -c a='b\"c' commit -m x",
    # 줄이음. 셸은 두 줄을 한 명령으로 잇고, 마스크도 그렇게 읽음 — 여기서 낱말이
    # 끊기면 러너가 게이트를 돌리기도 전에 exit 0(실측).
    "git -C /a/wt \\\n  commit -m x",
    "git.exe commit -m x",
    "C:/Git/bin/git.exe -C /a/wt commit -m x",
    # 텍스트를 **실행하는** 프로그램에 건네진 커밋. 통로는 `-c` 인자만이 아님 —
    # here-string 도 heredoc 도 파이프라인도 스크립트를 실어 나름. 이름으로 닫은 철자마다
    # 닫히지 않은 다음 철자가 뒤따름. 공통점은 명령이 인터프리터로 시작한다는 것이고,
    # 매칭되는 것은 그것임.
    "bash -c 'git commit -m x'",
    "printf 'git commit -m x' | bash",
    'echo "git commit -m x" | sh',
    "bash <<< 'git commit -m x'",
    "eval $'git commit -m x'",
    "bash <<'EOF'\ngit commit -m x\nEOF",
]


# 낱말을 **말하기만** 하는 명령들. 긍정 목록만 있으면 전부 매칭하는 문법이 그것을 만족시키
# 므로, 문법이 무엇을 호출로 세는지는 이 반쪽이 있어야 정해짐. 전부 셸이 멀쩡히 실행하는
# 읽기 전용 명령이고, 호출로 읽히면 미분류라는 이유로 차단됨(fail-CLOSED 오작동).
MERE_MENTIONS = [
    """git -c a='b"c' log && echo "please commit" """,
    "grep 'git commit' README.md",
    'echo "git merge --no-ff stage"',
    "git log --oneline && echo 'now commit'",
    "# git -C /other/wt commit -m x",
    "cat <<'EOF' > /tmp/m\ngit -C /evil/wt commit -m x\nEOF",
    # 읽기 전용 `git log` 를 미분류 커밋으로 차단하면, 게이트가 볼 일이 아닌 작업을 막는 것.
    "git -c commit.gpgsign=false log --oneline",
    # 원소가 돌리는 프로그램이 전부 읽기만 하면 둘째 읽기는 아예 없음. 이것들이 개발자가
    # 온종일 쓰는 모양이고, 호출로 읽히면 읽기 전용 작업이 차단됨.
    'rg "git commit" --type sh',
    "which bash; echo 'git commit -m x'",
    "bash x.sh  # remember to git commit -m x",
    "bash C:\\git\\commit\\run.sh",
]


# 문체 규율의 강제 지점. 코퍼스는 `GIT_DOCS`(스킬·룰·에이전트)보다 넓음 — 소비자가 읽는
# 진입 문서(README·USAGE·docs/usage)와 이 repo 의 CLAUDE.md·스킬 편집 룰도 같은 규율 적용.
PROSE_DOCS = sorted(
    set(GIT_DOCS)
    | set(REPO.glob(".claude/rules/*.md"))
    | set(REPO.glob("docs/usage/*.md"))
    | {REPO / ".claude" / "CLAUDE.md", REPO / "README.md", REPO / "USAGE.md"}
)
PROSE_DOC_IDS = [p.relative_to(REPO).as_posix() for p in PROSE_DOCS]

FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
CODE_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
# 서술형 종결의 판정은 여기 없음 — `scripts/doc_style_check.py` 의 ENDING 규칙 하나가
# 답함. 정규식을 여기 한 벌 더 두면 같은 룰에 리더가 둘이 되고, 한쪽만 조여진 채 CI 와
# 이 스위트가 다른 답을 내게 됨(rules/doc-style.md 9 — 한 사실 한 곳).


# 스캔 디스패치의 모델 선언을 재는 자리. 절은 헤딩으로 자름 — 파일 전체를 보면 다른 절의
# 낱말이 통과시키고, 정작 디스패치가 비어도 초록으로 뜸.
MODEL_NAMES = ("opus", "sonnet", "haiku")


def section(text: str, start: str, end: str) -> str:
    """두 헤딩 사이를 자름.

    `str.split` 은 구분자를 못 찾아도 예외 없이 원본을 돌려줌 — 헤딩이 개명되거나 번호가
    밀리면 조각이 조용히 파일 전체가 되고, 다른 절의 낱말이 테스트를 통과시킴. 그 넓어짐이
    바로 이 조각이 막으려던 것이라, 없는 헤딩은 수집 단계에서 터뜨림.
    """
    missing = [s for s in (start, end) if s not in text]
    if missing:
        raise AssertionError(f"헤딩이 사라짐: {missing} — 절 조각이 파일 전체로 넓어진다")
    return text.split(start, 1)[1].split(end, 1)[0]


_ALM_TRACE = (REPO / "skills" / "alm-trace" / "SKILL.md").read_text(encoding="utf-8")
SCAN_DISPATCH = section(_ALM_TRACE, "### 4. ", "### 5. ")

TASK_SYNC_DOC = (REPO / "skills" / "task-sync" / "SKILL.md").read_text(encoding="utf-8")
PROPAGATE_MODE = section(TASK_SYNC_DOC, "#### 전파 전용 모드", "### Teamer branch")
R6_CHECK = section(TASK_SYNC_DOC, "돌아오면 검산함", "종료 코드 `0` 이면")

_INTEGRATION = (REPO / "skills" / "integration" / "SKILL.md").read_text(encoding="utf-8")
ROUND_END = section(_INTEGRATION, "### 3.6 ALM 항목 완료 제안과 전파", "## 4. ")
