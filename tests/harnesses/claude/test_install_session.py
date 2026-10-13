"""호스트 `.claude/settings.json` 의 SessionStart·PostToolUse·Notification 훅 등록 — Claude
플러그인은 훅을 싣지 않음(Claude 디렉터리가 Verified 조직 아닌 배포자의 command 훅을 거부함)."""

import json
import os
from pathlib import Path

import pytest

from scripts.harness.claude import install
from tests._bash import BASH
from tests._proc import run_bounded

SETTINGS = Path(".claude/settings.json")
ROOT = "${CLAUDE_PROJECT_DIR:-.}/.claude/vway-kit"


def _read(host: Path) -> dict:
    return json.loads((host / SETTINGS).read_text(encoding="utf-8"))


def _grouped() -> dict:
    out: dict = {}
    for event, entry in install.SESSION_ENTRIES:
        out.setdefault(event, []).append(entry)
    return out


def test_session_hook_strings_are_pinned():
    # 바꾸면 모든 소비자의 settings.json 이 재동기화 때 "보정" 으로 다시 쓰임.
    assert _grouped() == {
        "SessionStart": [
            {
                "matcher": "startup|resume|clear|compact|fork",
                "hooks": [
                    {
                        "type": "command",
                        "shell": "bash",
                        "command": (
                            f'CLAUDE_PLUGIN_ROOT="{ROOT}" bash "{ROOT}/hooks/inject-risk-tiers.sh"'
                        ),
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Edit|Write|MultiEdit|NotebookEdit",
                "hooks": [
                    {
                        "type": "command",
                        "shell": "bash",
                        "command": f'bash "{ROOT}/hooks/invalidate-gate-markers.sh"',
                        "timeout": 10,
                    }
                ],
            }
        ],
        "Notification": [
            {
                "matcher": "permission_prompt|idle_prompt|elicitation_dialog"
                "|elicitation_url_dialog|agent_needs_input",
                "hooks": [
                    {
                        "type": "command",
                        "shell": "bash",
                        "command": f'bash "{ROOT}/hooks/notify-waiting.sh"',
                        "timeout": 10,
                    }
                ],
            },
            {
                "matcher": "permission_prompt",
                "hooks": [
                    {
                        "type": "command",
                        "shell": "bash",
                        "command": f'bash "{ROOT}/hooks/record-wait.sh"',
                        "timeout": 10,
                    }
                ],
            },
        ],
    }


def test_register_session_creates_and_is_idempotent(tmp_path):
    assert "등록" in install.register_session(tmp_path)
    assert "이미" in install.register_session(tmp_path)
    assert _read(tmp_path) == {"hooks": _grouped()}


def test_register_session_beside_the_gate_keeps_both(tmp_path):
    install.register(tmp_path)
    install.register_session(tmp_path)
    hooks = _read(tmp_path)["hooks"]
    assert hooks["PreToolUse"] == [install.GATE_ENTRY]
    assert hooks["SessionStart"] == _grouped()["SessionStart"]
    assert install.problems(tmp_path) == []


def test_register_session_keeps_user_hooks(tmp_path):
    (tmp_path / ".claude").mkdir()
    user = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo mine"}]}
    (tmp_path / SETTINGS).write_text(
        json.dumps({"hooks": {"SessionStart": [user]}}), encoding="utf-8"
    )
    install.register_session(tmp_path)
    assert _read(tmp_path)["hooks"]["SessionStart"] == [user, *_grouped()["SessionStart"]]


def test_register_session_repairs_a_stale_hook_in_place(tmp_path):
    (tmp_path / ".claude").mkdir()
    stale = {
        "matcher": "startup",
        "hooks": [{"type": "command", "command": 'bash "x/vway-kit/hooks/inject-risk-tiers.sh"'}],
    }
    (tmp_path / SETTINGS).write_text(
        json.dumps({"hooks": {"SessionStart": [stale]}}), encoding="utf-8"
    )
    assert "[+]" in install.register_session(tmp_path)
    (entry,) = _read(tmp_path)["hooks"]["SessionStart"]
    assert entry["hooks"] == _grouped()["SessionStart"][0]["hooks"]


@pytest.mark.parametrize("bad", ['{"hooks": []}', '{"hooks": {"Notification": {}}}', "{x"])
def test_register_session_refuses_a_malformed_file(tmp_path, bad):
    (tmp_path / ".claude").mkdir()
    (tmp_path / SETTINGS).write_text(bad, encoding="utf-8")
    assert "[!]" in install.register_session(tmp_path)
    assert (tmp_path / SETTINGS).read_text(encoding="utf-8") == bad


def test_unregister_session_keeps_the_gate_then_gate_removes_the_file(tmp_path):
    install.register(tmp_path)
    install.register_session(tmp_path)
    assert "해제" in install.unregister_session(tmp_path)
    assert _read(tmp_path) == {"hooks": {"PreToolUse": [install.GATE_ENTRY]}}
    install.unregister(tmp_path)
    assert not (tmp_path / SETTINGS).exists()
    assert "없음" in install.unregister_session(tmp_path)


def test_unregister_session_keeps_user_hooks(tmp_path):
    (tmp_path / ".claude").mkdir()
    user = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo mine"}]}
    (tmp_path / SETTINGS).write_text(
        json.dumps({"hooks": {"SessionStart": [user]}}), encoding="utf-8"
    )
    install.register_session(tmp_path)
    install.unregister_session(tmp_path)
    assert _read(tmp_path) == {"hooks": {"SessionStart": [user]}}


def test_the_injection_hook_emits_claude_code_shape(tmp_path):
    """호스트 사본 배치에서 SessionStart 명령을 그대로 돌려 `hookSpecificOutput` 을 받는지."""
    repo = Path(__file__).resolve().parents[3]
    vway = tmp_path / ".claude" / "vway-kit"
    (vway / "hooks").mkdir(parents=True)
    (vway / "rules").mkdir()
    for rel in ("hooks/inject-risk-tiers.sh", "rules/risk-tiers.md", "rules/doc-style.md"):
        (vway / rel).write_bytes((repo / rel).read_bytes())
    (entry,) = _grouped()["SessionStart"]
    command = entry["hooks"][0]["command"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    env["CLAUDE_PROJECT_DIR"] = tmp_path.as_posix()
    out = run_bounded(
        [BASH, "-c", command], input="{}", encoding="utf-8", env=env, check=True
    ).stdout
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "<vway-kit-risk-tiers>" in context
    assert "/.claude/vway-kit/rules" in context
