"""`run_uninstall` 의 하네스 배선 — config 와 무관하게 Codex 게이트를 떼고, 판정이 두 훅 파일을
따로 되읽는지 잼.

- `.codex/hooks.json` 이 없는 호스트는 Codex 단계 자체가 없음(claude 전용 출력 byte-identical).
- 판정은 남은 곳을 이름으로 가름 — settings.json 과 .codex/hooks.json 은 서로 다른 단계가 못
  지운 서로 다른 파일.
- 확인하지 못한 것은 "사라짐" 이 아니라 "남았을 수 있음"(FAIL-OPEN 의 방향).
"""

import json
import os
from pathlib import Path

import pytest

import scripts.vdev_init_setup as vis
from tests.harnesses.setup_wiring._helpers import (
    HOOKS,
    _cfg,
    _codex,
    _corrupt_codex_hooks,
    _plant_claude_gate,
)
from tests.vdev_init._helpers import PLUGIN

CLAUDE_LEFT = "커밋 게이트 훅이 settings.json 에 남았습니다"
CODEX_LEFT = "Codex 커밋 게이트 훅이 .codex/hooks.json 에 남았습니다"
CODEX_UNCONFIRMED = "Codex 커밋 게이트 훅이 지워졌는지 확인하지 못했습니다"


def _raise(_name):
    raise ImportError("codex install module cannot be imported")


def test_uninstall_clears_codex_even_when_config_dropped_it(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    _cfg(tmp_path, "harnesses: [claude]\n")
    assert vis.run_uninstall(tmp_path)
    assert not (tmp_path / HOOKS).exists()


def test_a_claude_only_host_sees_no_codex_step(tmp_path: Path, capsys):
    """컨트롤러 판정 5: `.codex/hooks.json` 이 없으면 뗄 것도 없음 — 상류와 달리 줄 추가 없음."""
    vis.run_uninstall(tmp_path)
    assert "Codex" not in capsys.readouterr().out


def test_a_host_with_its_own_codex_hooks_gets_the_step(tmp_path: Path, capsys):
    (tmp_path / ".codex").mkdir()
    (tmp_path / HOOKS).write_text('{"hooks": {}}', encoding="utf-8")
    assert vis.run_uninstall(tmp_path) is True
    out = capsys.readouterr().out
    assert "[Codex 게이트 해제]" in out and "Codex 게이트 훅 없음 (skip)" in out, out


def test_verdict_keeps_todays_exact_message_when_only_claude_is_left(tmp_path: Path, capsys):
    settings = _plant_claude_gate(tmp_path)
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):  # 소유자에게 읽기 전용이 강제되지 않는 호스트
            pytest.skip("read-only is not enforced here")
        assert vis.run_uninstall(tmp_path) is False
        out = capsys.readouterr().out
        assert (
            "커밋 게이트 훅이 settings.json 에 남았습니다 — 방금 삭제된 스크립트를"
            " 가리키므로 직접 지우세요." in out
        )
        assert "Codex 커밋 게이트 훅이" not in out
    finally:
        settings.chmod(0o644)


def test_verdict_names_codex_when_only_codex_is_left(tmp_path: Path, capsys):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    _corrupt_codex_hooks(tmp_path)
    assert vis.run_uninstall(tmp_path) is False
    out = capsys.readouterr().out
    assert CODEX_LEFT in out
    assert CLAUDE_LEFT not in out


def test_verdict_names_both_when_both_are_left(tmp_path: Path, capsys):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    _corrupt_codex_hooks(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):
            pytest.skip("read-only is not enforced here")
        assert vis.run_uninstall(tmp_path) is False
        out = capsys.readouterr().out
        assert CLAUDE_LEFT in out and CODEX_LEFT in out
    finally:
        settings.chmod(0o644)


def test_an_unresolvable_codex_module_costs_only_its_step(tmp_path: Path, monkeypatch, capsys):
    """Codex 패키징 실패는 그 단계만 잃음 — Claude 게이트 해제는 그대로 돌아야 함.
    훅 파일이 있으니 확인 못 한 것은 "남았을 수 있음"."""
    settings = _plant_claude_gate(tmp_path)
    (tmp_path / ".codex").mkdir()
    (tmp_path / HOOKS).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(vis.harness, "installer", _raise)
    assert vis.run_uninstall(tmp_path) is False
    out = capsys.readouterr().out
    assert "[!] Codex 게이트 설치 모듈을 불러오지 못했습니다" in out, out
    assert "[-] 커밋 게이트 해제 (settings.json)" in out, out
    assert CODEX_UNCONFIRMED in out and CODEX_LEFT not in out, out
    assert not settings.exists()  # Claude 게이트와 함께 그 파일이 쥔 전부가 빠짐


def test_an_unresolvable_codex_module_with_no_hooks_file_is_not_a_leftover(
    tmp_path: Path, monkeypatch, capsys
):
    """아무것도 `.codex/hooks.json` 을 만든 적이 없으면 해석 실패가 숨길 것도 없음."""
    _plant_claude_gate(tmp_path)
    monkeypatch.setattr(vis.harness, "installer", _raise)
    assert vis.run_uninstall(tmp_path) is True
    out = capsys.readouterr().out
    assert "Codex" not in out, out
    assert out.rstrip().endswith("정리 완료."), out


@pytest.mark.parametrize(
    "body",
    [
        b"{broken",
        b"\xff\xfe{}",
        b"[]",
        b'{"hooks": "x"}',
        b'{"hooks": {"PreToolUse": "x"}}',
        b'{"hooks": {"PreToolUse": {}}}',
    ],
)
def test_a_hosts_own_unreadable_codex_hooks_file_does_not_fail_uninstall(
    tmp_path: Path, capsys, body
):
    """vway-kit 이 쓴 적 없는 `.codex/hooks.json` — 날바이트에 게이트 표식이 없음."""
    (tmp_path / ".codex").mkdir()
    (tmp_path / HOOKS).write_bytes(body)
    assert vis.run_uninstall(tmp_path) is True
    out = capsys.readouterr().out
    assert "Codex 커밋 게이트 훅이" not in out, out
    assert "[i] .codex/hooks.json 을 해석하지 못했지만" in out, out
    assert (tmp_path / HOOKS).read_bytes() == body


def test_an_unreadable_codex_hooks_file_carrying_the_gate_marker_fails_unconfirmed(
    tmp_path: Path, capsys
):
    (tmp_path / ".codex").mkdir()
    body = json.dumps({"hooks": {"PreToolUse": [_codex().GATE_ENTRY]}})[:-1]
    (tmp_path / HOOKS).write_text(body, encoding="utf-8")
    assert vis.run_uninstall(tmp_path) is False
    out = capsys.readouterr().out
    assert CODEX_UNCONFIRMED in out, out
    assert CODEX_LEFT not in out, out


def test_uninstall_does_not_report_a_gate_an_extra_key_file_never_held(tmp_path: Path, capsys):
    (tmp_path / ".codex").mkdir()
    own = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}, "x-team": True}
    (tmp_path / HOOKS).write_text(json.dumps(own), encoding="utf-8")
    assert vis.run_uninstall(tmp_path) is True
    assert "Codex 커밋 게이트 훅이" not in capsys.readouterr().out
