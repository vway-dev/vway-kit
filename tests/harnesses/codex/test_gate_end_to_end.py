"""Codex 게이트를 소비자가 받는 모양 그대로 — 호스트 사본의 wrapper 가 진짜 러너를 띄워 미분류
커밋을 JSON deny 로 막는지, Claude Code 환경 변수 없이 잼.

- 호스트 배치는 codex 를 켠 `copy_artifacts` 가 만든 그대로(러너·게이트 사본 + wrapper 두
  파일이 `scripts/harness/codex/`). 명령 문자열은 조립하지 않고 설치자가 `.codex/hooks.json`
  에 쓴 것을 읽어 그대로 띄움 — 설치자가 쓰는 것과 도는 것이 갈라지지 않게.
- 사유 문구까지 고정 — `deny` 만 보면 모든 커밋을 막는 wrapper 나 의존성 fail-CLOSED(python3·
  PyYAML 부재)도 통과함.
"""

import json
import os
from pathlib import Path

import pytest

import scripts.vdev_init_setup as vis
from scripts.harness.codex import install
from scripts.harness.gate_spec import GATE
from tests._bash import BASH
from tests._proc import run_bounded
from tests.vdev_init._helpers import PLUGIN

pytestmark = pytest.mark.skipif(BASH is None, reason="repo 를 볼 수 있는 bash 가 필요함")

WRAPPER_DIR = GATE.runner_rel.rsplit("/", 1)[0] + "/harness/codex"


def _git(cwd: Path, *args: str) -> None:
    run_bounded(["git", *args], cwd=cwd, check=True)


def _host(tmp_path: Path) -> Path:
    host = tmp_path / "host"
    host.mkdir()
    _git(host, "init", "-q")
    _git(host, "checkout", "-q", "-b", "feature/e2e")
    vis.copy_artifacts(PLUGIN, host, harnesses=("claude", "codex"))
    return host


def test_the_wrapper_sits_two_levels_under_the_runner():
    """wrapper 는 러너를 `../../precommit-runner.sh` 로 찾음 — 호스트 배치가 그 관계여야 함."""
    assert WRAPPER_DIR.rsplit("/", 2)[0] + "/precommit-runner.sh" == GATE.runner_rel


def test_the_registered_command_denies_an_unclassified_commit(tmp_path):
    host = _host(tmp_path)
    install.register(host)
    registered = json.loads((host / ".codex/hooks.json").read_text(encoding="utf-8"))
    hook = registered["hooks"]["PreToolUse"][-1]["hooks"][0]
    assert hook == install.GATE_HOOK
    sub = host / "src"
    sub.mkdir()
    payload = {
        "cwd": str(sub),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    run = run_bounded(
        [BASH, "-c", hook["command"]],
        cwd=sub,
        input=json.dumps(payload).encode("utf-8"),
        env=env,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr.decode("utf-8", errors="replace")
    decision = json.loads(run.stdout.decode("utf-8").strip())
    output = decision["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny", decision
    # 예외 2(미분류 커밋)의 문구 — vdev_gate_check.py main() 이 찍는 것을 Codex 어휘로 바꾼 것
    reason = output["permissionDecisionReason"].replace("\r\n", "\n").replace("\r", "\n")
    assert "분류되지 않은 커밋" in reason, reason
    assert "$vdev 로" in reason and "/vdev" not in reason, reason
