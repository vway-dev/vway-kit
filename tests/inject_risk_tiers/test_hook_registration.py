"""세션 이벤트 훅 — Claude 와 Codex 각각. 둘 다 `/vdev-init` 이 호스트에 등록함."""

import re
import subprocess
from pathlib import Path

import pytest

import scripts.teams_alert as ta
from scripts.harness.claude import install as claude_install
from scripts.harness.codex import install as codex_install

ROOT = Path(__file__).resolve().parents[2]
CLAUDE: dict[str, list[dict]] = {}
for _event, _entry in claude_install.SESSION_ENTRIES:
    CLAUDE.setdefault(_event, []).append(_entry)
CODEX = {event: [entry] for event, entry in codex_install.SESSION_ENTRIES.items()}
# 호스트 사본(`VWAY_DIR/hooks/`)의 셸 스크립트를 리터럴 경로로 띄움.
_LITERAL_SCRIPT = re.compile(
    r'^(CLAUDE_PLUGIN_ROOT="\$\{CLAUDE_PROJECT_DIR:-\.\}/\.claude/vway-kit" )?'
    r'bash "\$\{CLAUDE_PROJECT_DIR:-\.\}/\.claude/vway-kit/(hooks/[\w-]+\.sh)"$'
)


def _claude_commands() -> list[str]:
    return [h["command"] for entries in CLAUDE.values() for e in entries for h in e["hooks"]]


@pytest.mark.parametrize("hooks", [CLAUDE, CODEX], ids=["claude", "codex"])
def test_every_session_source_receives_the_rule(hooks):
    """SessionStart 가 발화하지 않으면 재개·분기한 세션은 룰 없이 시작함."""
    (entry,) = hooks["SessionStart"]
    assert set(entry["matcher"].split("|")) == {"startup", "resume", "clear", "compact", "fork"}


@pytest.mark.parametrize("command", _claude_commands())
def test_every_claude_hook_runs_a_shipped_executable_script(command):
    """`/vdev-init` 이 복사하는 출하 스크립트를 가리킴. 복사본에 실행 비트를 주는 것은 복사
    단계 — 원본의 모드는 플러그인 캐시에서 직접 돌리는 경로(eval 러너)를 위해 고정."""
    match = _LITERAL_SCRIPT.match(command)
    assert match, command
    script = match.group(2)
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
