"""세션 격리 — provider 변수를 벗기고 자격증명만 든 설정 디렉터리를 줌.

벗기는 순서가 계약. 설정 디렉터리는 벗긴 **뒤에** 세우고, UTF-8 플래그는 살아남음.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.runner import session

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.

#
# Tasks 5-7 of the measurement-validity plan. Everything here is stubbed: a test in this
# file must never reach a model, a CLI, or the network.


def test_session_env_strips_provider_variables(monkeypatch):
    """Isolation is not only the config dir. A single `ANTHROPIC_BASE_URL` routes every
    session through a proxy and `ANTHROPIC_API_KEY` moves authentication off the credential
    that `isolated_config_dir` copied -- either way the committed baseline becomes a
    fact about one developer's shell (spec 2.4).
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-leak")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy.internal")
    monkeypatch.setenv("CLAUDE_CODE_EXTRA", "x")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = session.session_env(Path("/tmp/cfg"))

    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_BASE_URL" not in env
    assert "CLAUDE_CODE_EXTRA" not in env
    assert "PATH" in env, "a whitelist would starve the CLI of the system variables it needs"


def test_the_config_dir_is_set_after_the_stripping_not_before(monkeypatch):
    """`CLAUDE_CONFIG_DIR` carries the very prefix the blacklist removes, so the order is
    load-bearing: strip first and the isolation instruction survives, strip last and the
    isolation erases itself while every other check here still passes (spec 2.4).
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "C:/Users/dev/.claude")
    env = session.session_env(Path("/tmp/cfg"))
    assert env["CLAUDE_CONFIG_DIR"] == str(Path("/tmp/cfg"))


def test_the_utf8_flag_survives_the_stripping(monkeypatch):
    """CLAUDE.md Invariant 2. This host is cp949, and a session whose Python child loses
    `PYTHONUTF8` raises `UnicodeEncodeError` on the Korean prompts mid-run."""
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    assert session.session_env(Path("/tmp/cfg"))["PYTHONUTF8"] == "1"


def test_an_absent_credential_stops_the_run_and_says_why(monkeypatch, tmp_path):
    """An empty config dir emits a well-formed `init` -- skills array and all -- and then
    answers "Not logged in", so every session scores 0.0 for a reason that has nothing to
    do with any description (spec 2.4). Falling back to the real config dir would silently
    un-isolate the run, so absence has to stop it and name the reason.
    """
    monkeypatch.setattr(session.Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(SystemExit) as caught:
        with session.isolated_config_dir():
            pytest.fail("the run continued without credentials")
    assert "credentials" in str(caught.value).lower(), caught.value


def test_the_isolated_config_dir_carries_the_credential_and_nothing_else(monkeypatch, tmp_path):
    """The point of the isolation is that nothing else comes across: 95 visible skills fall
    to ~30 (spec 2.4). The credential is the one exception, and it is removed again on the
    way out rather than left in a world-writable temp tree.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text('{"token": "x"}', encoding="utf-8")
    (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(session.Path, "home", staticmethod(lambda: home))

    with session.isolated_config_dir() as config_dir:
        assert [p.name for p in config_dir.iterdir()] == [".credentials.json"]
        copied = config_dir / ".credentials.json"
        assert copied.read_text(encoding="utf-8") == '{"token": "x"}'
    assert not copied.exists(), "the copied credential outlived the run"
