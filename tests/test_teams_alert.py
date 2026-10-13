import json
import sys
from pathlib import Path

import scripts._vway_paths as vp
import scripts.teams_alert as ta
from tests._non_utf8 import non_utf8_env
from tests._proc import run_bounded

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "teams_alert.py"


def test_host_root_is_shared_helper():
    # _host_root 는 공용 host_root 의 하위호환 alias 다. 폴백 로직(env → git toplevel →
    # .claude 마커 → cwd)의 SSOT 는 _vway_paths, 동작 검증은 test_vway_paths 몫.
    assert ta._host_root is vp.host_root


def test_host_root_prefers_env(monkeypatch, tmp_path: Path):
    # alias 가 실제로 공용 헬퍼로 연결돼 env 를 존중하는지 확인.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert ta._host_root() == tmp_path.resolve()


def test_set_and_resolve_webhook(monkeypatch, tmp_path: Path):
    # URL 은 local 파일, 브랜치 이름은 tracked 파일 + 병합 해석 + push 채널 제외
    tracked = tmp_path / "teams-webhooks.json"
    local = tmp_path / ".teams-webhooks.local.json"
    monkeypatch.setattr(ta, "TRACKED_FILE", tracked)
    monkeypatch.setattr(ta, "LOCAL_FILE", local)
    monkeypatch.delenv(ta.PERSONAL_OPTION_ENV, raising=False)

    assert ta.set_webhook("personal", "https://x") == local  # personal → local 파일
    assert ta.set_webhook("dev", "https://y") == local  # 브랜치 URL 도 git 밖
    assert ta.set_webhook("main", "https://z", shared=True) == tracked
    assert ta.resolve_webhook("personal") == "https://x"
    assert ta.resolve_webhook("dev") == "https://y"
    assert ta.resolve_webhook("main") == "https://z"
    assert ta.resolve_webhook("absent") is None
    # tracked 파일은 모든 클론이 감시할 브랜치 이름을 쥐고, `sig=` URL 은 안 쥠.
    assert json.loads(tracked.read_text(encoding="utf-8")) == {"dev": "", "main": "https://z"}
    assert ta.push_channels() == ["dev", "main"]  # personal(local 전용)은 push 대상 제외


def test_the_plugin_option_wins_for_personal_only(monkeypatch, tmp_path: Path):
    """userConfig 값은 보안 저장소에서 훅 환경으로 옴 — 파일보다 먼저, personal 에만."""
    local = tmp_path / ".teams-webhooks.local.json"
    monkeypatch.setattr(ta, "TRACKED_FILE", tmp_path / "teams-webhooks.json")
    monkeypatch.setattr(ta, "LOCAL_FILE", local)
    local.write_text('{"personal": "https://file", "dev": "https://d"}', encoding="utf-8")
    monkeypatch.setenv(ta.PERSONAL_OPTION_ENV, " https://option ")
    assert ta.resolve_webhook("personal") == "https://option"
    assert ta.resolve_webhook("dev") == "https://d"
    monkeypatch.setenv(ta.PERSONAL_OPTION_ENV, "")
    assert ta.resolve_webhook("personal") == "https://file"


def test_the_option_name_matches_the_manifest():
    """Claude Code 는 userConfig 키를 대문자로 바꿔 `CLAUDE_PLUGIN_OPTION_` 뒤에 붙임."""
    manifest = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"
    option = json.loads(manifest.read_text(encoding="utf-8"))["userConfig"]
    (key,) = [k for k, v in option.items() if v.get("sensitive")]
    assert ta.PERSONAL_OPTION_ENV == "CLAUDE_PLUGIN_OPTION_" + key.upper()


def test_a_local_only_branch_is_still_a_push_target(monkeypatch, tmp_path: Path):
    """tracked 파일에 그 브랜치가 없는 클론도 쥔 URL 로 알림."""
    monkeypatch.setattr(ta, "TRACKED_FILE", tmp_path / "teams-webhooks.json")
    local = tmp_path / ".teams-webhooks.local.json"
    monkeypatch.setattr(ta, "LOCAL_FILE", local)
    local.write_text('{"personal": "https://x", "stage": "https://s"}', encoding="utf-8")
    assert ta.push_channels() == ["stage"]


def test_setting_a_branch_locally_keeps_a_teammates_tracked_url(monkeypatch, tmp_path: Path):
    tracked = tmp_path / "teams-webhooks.json"
    monkeypatch.setattr(ta, "TRACKED_FILE", tracked)
    monkeypatch.setattr(ta, "LOCAL_FILE", tmp_path / ".teams-webhooks.local.json")
    tracked.write_text('{"dev": "https://team"}', encoding="utf-8")
    ta.set_webhook("dev", "https://mine")
    assert json.loads(tracked.read_text(encoding="utf-8")) == {"dev": "https://team"}
    assert ta.resolve_webhook("dev") == "https://mine"


def test_the_cli_names_the_url_that_still_wins(tmp_path: Path):
    """한쪽을 등록하는 동안 다른 쪽이 URL 을 쥐면 사본이 둘 — git 밖에 남는 것은 local 뿐이라
    CLI 가 어느 쪽이 남았는지 말함. 비UTF-8 로캘에서 돌려 한글 안내가 깨지지 않음도 같이 잼."""
    cfg = tmp_path / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)

    def cli(*args: str) -> str:
        r = run_bounded(
            [sys.executable, str(SCRIPT), "--set", *args],
            env=non_utf8_env(CLAUDE_PROJECT_DIR=str(tmp_path)),
            cwd=str(tmp_path),
        )
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
        return r.stdout.decode("utf-8")

    assert "teams-webhooks.json" in cli("dev", "https://team.invalid", "--shared")
    assert "아직 남아" in cli("dev", "https://mine.invalid")
    assert "우선합니다" in cli("dev", "https://team2.invalid", "--shared")
    tracked = json.loads((cfg / "teams-webhooks.json").read_text(encoding="utf-8"))
    assert tracked == {"dev": "https://team2.invalid"}
