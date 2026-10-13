"""하네스 레지스트리 — 아는 이름·지원 이름과 `installer()` 가 돌려주는 모듈의 공통 계약을 잼."""

import pytest

from scripts import harness


def test_known_and_supported():
    assert harness.KNOWN == ("claude", "codex", "antigravity")
    assert harness.SUPPORTED == ("claude", "codex")


def test_installer_rejects_unknown_and_stub():
    with pytest.raises(ValueError):
        harness.installer("gemini")
    with pytest.raises(NotImplementedError):
        harness.installer("antigravity")


def test_installer_returns_modules_with_the_shared_contract():
    for name in harness.SUPPORTED:
        mod = harness.installer(name)
        for attr in ("register", "unregister", "problems", "hook_remains"):
            assert callable(getattr(mod, attr)), (name, attr)
