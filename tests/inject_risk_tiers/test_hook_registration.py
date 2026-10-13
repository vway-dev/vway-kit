"""플러그인 훅에 닿는 세션 이벤트 — Claude 와 Codex 각각."""

import json
import re
import subprocess
from pathlib import Path

import pytest

import scripts.teams_alert as ta
from scripts.harness.codex import install as codex_install

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = json.loads((ROOT / "hooks" / "claude" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
# Codex 세션 훅은 플러그인이 아니라 `/vdev-init` 이 호스트 `.codex/hooks.json` 에 등록함.
CODEX = {event: [entry] for event, entry in codex_install.SESSION_ENTRIES.items()}
# 디렉터리 심사는 훅 명령이 CLAUDE_PLUGIN_ROOT 아래 셸 스크립트를 리터럴 경로로 가리키길 요구함.
_LITERAL_SCRIPT = re.compile(r'^"\$\{CLAUDE_PLUGIN_ROOT\}"/(hooks/[\w-]+\.sh)$')


def _claude_commands() -> list[str]:
    return [h["command"] for entries in CLAUDE.values() for e in entries for h in e["hooks"]]


@pytest.mark.parametrize("hooks", [CLAUDE, CODEX], ids=["claude", "codex"])
def test_every_session_source_receives_the_rule(hooks):
    """SessionStart 가 발화하지 않으면 재개·분기한 세션은 룰 없이 시작함."""
    (entry,) = hooks["SessionStart"]
    assert set(entry["matcher"].split("|")) == {"startup", "resume", "clear", "compact", "fork"}


@pytest.mark.parametrize("command", _claude_commands())
def test_every_claude_hook_runs_a_shipped_executable_script(command):
    """인터프리터를 앞에 세우면 심사가 스크립트를 못 따라감. 리터럴 경로로 띄우므로 실행 비트가
    없으면 Linux·macOS 에서 `Permission denied`."""
    match = _LITERAL_SCRIPT.match(command)
    assert match, command
    script = match.group(1)
    assert (ROOT / script).is_file(), script
    mode = subprocess.run(
        ["git", "ls-files", "-s", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split(" ", 1)[0]
    assert mode == "100755", f"{script}: {mode}"


def _notification(script: str) -> dict:
    (entry,) = [
        e for e in CLAUDE["Notification"] if any(script in h["command"] for h in e["hooks"])
    ]
    return entry


def test_only_a_wait_for_the_user_posts_the_waiting_card():
    """matcher 가 없으면 모든 알림(`auth_success`·`agent_completed` 등)이 "입력 대기"를 게시하고
    알림마다 python 을 띄움."""
    entry = _notification("notify-waiting.sh")
    assert set(entry["matcher"].split("|")) == {
        "permission_prompt",
        "idle_prompt",
        "elicitation_dialog",
        "elicitation_url_dialog",
        "agent_needs_input",
    }
    wrapper = (ROOT / "hooks" / "notify-waiting.sh").read_text(encoding="utf-8")
    assert 'scripts/teams_alert.py" --channel personal --event waiting' in wrapper


def test_the_post_fits_inside_the_notification_hook_timeout():
    """훅 timeout 을 넘기면 프로세스가 죽고 카드는 안 나감."""
    (hook,) = _notification("notify-waiting.sh")["hooks"]
    assert ta.GIT_TIMEOUT + ta.POST_TIMEOUT < hook["timeout"]


def test_only_a_permission_prompt_records_a_worklog_wait():
    """다른 알림까지 적으면 idle 알림이 권한 대기로 읽혀 도구 실행 시간이 15분에서 잘림."""
    entry = _notification("record-wait.sh")
    assert entry["matcher"] == "permission_prompt"
    wrapper = (ROOT / "hooks" / "record-wait.sh").read_text(encoding="utf-8")
    assert 'scripts/worklog.py" record-wait' in wrapper
