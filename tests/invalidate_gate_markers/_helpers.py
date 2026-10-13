"""훅 테스트가 공유하는 것 — bash 선택, 페이로드·트리 만들기, 훅 실행."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests._bash import find_bash

REPO = Path(__file__).resolve().parent.parent.parent  # tests/<분류>/_helpers.py
SCRIPT = REPO / "hooks" / "invalidate-gate-markers.sh"

# bash 를 고르는 규칙은 tests/_bash.py 가 SSOT — 이름으로 부르면 Windows 의 CreateProcess 가
# PATH 보다 앞선 System32 의 WSL 스텁을 집고, 그 스텁은 stdin 을 물고 놓지 않음. None 이면
# 쓸 수 있는 bash 가 없다는 뜻이고, 이 테스트들은 벌지 않은 green 을 보고하는 대신 skip.
_BASH = find_bash()
pytestmark = pytest.mark.skipif(_BASH is None, reason="repo 를 볼 수 있는 bash 가 필요하다")
BASH = _BASH or "bash"

MARKERS = ("review.done", "doc-sync.done")
KEPT = ("bump.done", "security.done")


def payload(file_path: str | None, key: str = "file_path") -> str:
    body: dict[str, object] = {"hook_event_name": "PostToolUse", "tool_name": "Edit"}
    if file_path is not None:
        body["tool_input"] = {key: file_path}
    return json.dumps(body)


def vdev(project: Path) -> Path:
    return project / ".claude" / "vway-kit" / ".vdev"


def repo(root: Path, *, evidence: bool = True) -> Path:
    """게이트가 판정할 트리 — repo 루트와, 게이트 실행이 거기 남긴 증거. 훅의 걸음을 가두는
    것은 `.git` 이므로 그것이 없는 픽스처는 트리가 아님. `evidence=False` 는 빈 증거
    디렉터리가 아니라 **디렉터리 자체가 없음**을 뜻함 — 빈 디렉터리는 증거 디렉터리를 찾는
    걸음을 멈춰 세우는데, 몇몇 테스트가 봐야 하는 것이 바로 그 걸음."""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    if evidence:
        vdev(root).mkdir(parents=True, exist_ok=True)
        for name in MARKERS:
            (vdev(root) / name).touch()
    return root


def worktree_of(main: Path, root: Path, *, gitdir: str | None = None, eol: str = chr(10)) -> Path:
    """링크된 worktree: 그 `.git` 은 메인 repo 의 공통 디렉터리를 가리키는 **파일**임. 그
    포인터만이 "한 repo 의 두 시점" 을 "두 repo" 와 가르고, 훅은 두 시점을 모두 무효화해야
    함 — 게이트가 커밋이 어느 쪽에 속하는지 늘 댈 수 있는 것은 아님.

    `gitdir` 은 포인터의 철자를 덮고(`worktree.useRelativePaths` 에서 git 은 상대 경로를
    씀), `eol` 은 그 끝을 덮음 — 개행 없이 끝나는 파일도 git 이 쓴 파일임."""
    root.mkdir(parents=True, exist_ok=True)
    target = gitdir or f"{main.as_posix()}/.git/worktrees/{root.name}"
    (root / ".git").write_text(f"gitdir: {target}{eol}", encoding="utf-8")
    vdev(root).mkdir(parents=True, exist_ok=True)
    for name in MARKERS:
        (vdev(root) / name).touch()
    return root


def run(project: Path | None, stdin: str) -> subprocess.CompletedProcess[str]:
    # 실제 환경에서 테스트 대상 변수 하나만 뺌: 손으로 만든 env 는 Windows 에서 bash 자신이
    # 필요로 하는 것(SYSTEMROOT, TEMP)을 떨어뜨리고, 그러면 훅은 여기 어떤 단언과도 무관한
    # 이유로 실패함.
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    return subprocess.run(
        [BASH, str(SCRIPT)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
