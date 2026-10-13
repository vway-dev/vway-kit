"""훅이 페이로드를 얼마나 읽는가, 그리고 그 너머에서 무엇을 하는가."""

import json
import os
import subprocess
from pathlib import Path

from tests.invalidate_gate_markers._helpers import (
    BASH,
    MARKERS,
    SCRIPT,
    payload,
    pytestmark,  # noqa: F401 — 모듈 수준 skip 은 이 이름으로만 걸림
    repo,
    vdev,
)


def _edited_in_another_repo(tmp_path: Path) -> tuple[Path, Path]:
    other = repo(tmp_path / "other")
    edited = other / "src" / "a.py"
    edited.parent.mkdir(parents=True, exist_ok=True)
    edited.write_text("x", encoding="utf-8")
    return other, edited


def _hook(project: Path, stdin: str, *, timeout: int = 30, path_prefix: str | None = None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    argv = [BASH, str(SCRIPT)]
    if path_prefix is not None:
        # PATH 는 bash **안에서** 붙임. Git Bash 의 `bin/bash.exe` 는 시작하며 `/usr/bin` 을
        # 맨 앞에 다시 얹어, 환경으로 준 스텁을 가림(실측: `command -v grep` → /usr/bin/grep).
        # 그러면 이 테스트는 파이프라인을 쓰는 훅에도 통과함. `$BASH` 로 exec 해 래퍼를 안 거침.
        argv = [
            BASH,
            "-c",
            'd=$1; command -v cygpath >/dev/null 2>&1 && d=$(cygpath -u "$d")\n'
            'PATH="$d:$PATH" exec "$BASH" "$2"',
            "_",
            path_prefix,
            str(SCRIPT),
        ]
    return subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def test_the_payload_is_read_without_the_pipeline(project: Path, tmp_path: Path):
    """편집마다 돌고, Windows 에서는 띄운 프로세스 하나가 그 일보다 비쌈 — 하네스를 설치한 적
    없는 repo 도 지울 것이 없다는 답을 얻으려고 `cat | grep | head | sed` 파이프라인 전체를
    치렀음. 그중 넷이 사라짐. `head` 는 남음: bash 자신의 제한 읽기는 4.1 이상이고 macOS 는
    3.2 를 실음.

    편집이 **다른** repo 에 떨어지는 것이 이 단언을 가르는 장치: 경로를 못 읽은 훅은 포기하고
    **이** 프로젝트를 무효화하므로(안전한 방향), 편집된 repo 만 보는 테스트는 어느 쪽이든
    통과함."""
    other, edited = _edited_in_another_repo(tmp_path)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("grep", "sed", "tr", "cat", "awk", "cut"):
        stub = stubs / name
        stub.write_text(
            "#!/bin/sh" + chr(10) + "exit 7" + chr(10), encoding="utf-8", newline=chr(10)
        )
        stub.chmod(0o755)
    proc = _hook(project, payload(str(edited)), path_prefix=str(stubs))
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    for marker in MARKERS:
        assert not (vdev(other) / marker).exists(), f"{marker}: 편집된 repo 가 마커를 지켰다"
        assert (vdev(project) / marker).exists(), (
            f"{marker}: 이 프로젝트가 무효화됨 — 경로를 못 읽었다"
        )


def _padded_payload(edited: Path, pad: int) -> str:
    """`tool_input` 앞에 `pad` 바이트의 채움을 단 실제 모양의 PostToolUse 페이로드."""
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "padding": "x" * pad,
            "tool_input": {"file_path": str(edited), "content": "y"},
        }
    )


def test_a_path_past_the_read_cap_is_a_payload_with_no_path(project: Path, tmp_path: Path):
    """상한은 움직였을 때 무언가 알아채야 상한임. 올리면 바뀌는 관측값은 하나 — 그 너머의
    경로를 찾느냐 — 라서 그것을 단언함. 제한 없는 읽기도 맞추는 벽시계 예산이 아님.

    편집이 **다른** repo 에 떨어지므로 두 절반이 갈림: 못 읽으면 훅은 편집 위치를 못 잡아
    세션의 프로젝트를 대신 무효화하고, 편집된 repo 의 마커는 남음. 그것이 잘라 읽기의 안전하지
    않은 절반이고, 상한을 실제 페이로드가 경로를 두는 자리보다 세 자릿수 멀리 둔 이유."""
    other, edited = _edited_in_another_repo(tmp_path)
    proc = _hook(project, _padded_payload(edited, 70000))
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    for name in MARKERS:
        assert not (vdev(project) / name).exists(), f"{name}: 상한 너머의 경로를 읽었다"
        assert (vdev(other) / name).exists(), f"{name}: 편집된 repo 에 그래도 닿았다"


def test_a_path_inside_the_read_cap_is_still_found(project: Path, tmp_path: Path):
    """같은 경계의 반대편 — 페이로드를 아예 안 읽는 훅이 위 테스트를 만족하지 못하게 함."""
    other, edited = _edited_in_another_repo(tmp_path)
    proc = _hook(project, _padded_payload(edited, 30000))
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    for name in MARKERS:
        assert not (vdev(other) / name).exists(), f"{name}: 편집된 repo 가 마커를 지켰다"
        assert (vdev(project) / name).exists(), f"{name}: 프로젝트가 대신 무효화됐다"


def test_a_huge_payload_still_finishes_inside_the_hook_s_budget(project: Path):
    """상한과 별개: 편집마다 하는 일은 hooks.json 이 준 10초에 들어가야 함 — 죽은 훅은 마커를
    남김. 아래 timeout 이 그 예산. 상한을 고정하는 것은 위 테스트이고 여기는 비용을 고정함."""
    edited = project / "src" / "a.py"
    body = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(edited), "content": "x" * (16 * 1024 * 1024)},
        }
    )
    proc = _hook(project, body, timeout=10)
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    for name in MARKERS:
        assert not (vdev(project) / name).exists(), name
