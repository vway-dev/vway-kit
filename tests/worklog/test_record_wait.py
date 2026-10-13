"""record-wait — ALM 작업 중일 때만, 조용히, 실패 없이."""

import json
import sys
from pathlib import Path

from scripts.worklog import when
from tests._non_utf8 import non_utf8_env
from tests._proc import run_bounded

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "worklog.py"


def fire(root: Path, payload):
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return run_bounded(
        [sys.executable, str(SCRIPT), "record-wait"],
        input=body.encode("utf-8"),
        env=non_utf8_env(CLAUDE_PROJECT_DIR=str(root)),
    )


def test_appends_a_line_while_an_alm_task_runs(tmp_path):
    vdev = tmp_path / "한글" / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "alm").write_text("recoble:labs:X-1\n", encoding="utf-8")
    proc = fire(tmp_path / "한글", {"session_id": "s1", "cwd": str(tmp_path)})
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
    stamp, session = (vdev / "waits").read_text(encoding="utf-8").split()
    assert session == "s1" and when(stamp) is not None


def test_writes_nothing_without_an_alm_marker(tmp_path):
    proc = fire(tmp_path, {"session_id": "s1"})
    assert proc.returncode == 0 and proc.stdout == b""
    assert not (tmp_path / ".claude").exists()


def test_broken_payload_is_silent(tmp_path):
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "alm").write_text("x\n", encoding="utf-8")
    proc = fire(tmp_path, "{not json")
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
    assert not (vdev / "waits").exists()
