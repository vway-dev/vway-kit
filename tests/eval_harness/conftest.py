"""이 패키지의 모든 테스트를 모델 없이 묶어 두는 autouse 가드.

conftest 에 두는 이유: 분류별 파일 어디에 테스트가 새로 생기든 **자동으로** 걸려야
함. 임포트해서 쓰는 픽스처였다면 새 파일이 임포트를 빠뜨리는 순간 그 파일만 조용히
모델을 부름 — 잊는 것이 예상된 실패 모드라 구조로 막음.
"""

from __future__ import annotations

import subprocess

import pytest

from evals.runner import session

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.


class _NoRealSessions:
    """Stands in for `subprocess` inside `evals.runner.session`, refusing both spawn doors.

    `Popen` is the one `run_session` uses; `subprocess.run` is the `taskkill` helper and the
    historical spawn path. Refusing BOTH keeps the guard ahead of a refactor that moves
    between them -- a guard that only covers today's entry point stops covering anything the
    day someone changes it, silently.

    Everything else is delegated, because `run_session` also reads `DEVNULL`, `PIPE` and
    `TimeoutExpired` from this module and a bare object would fail with an AttributeError
    that says nothing about why.
    """

    @staticmethod
    def run(*_args, **_kwargs):
        raise AssertionError(
            "this test tried to spawn a real `claude` session. Every test in this package must "
            "be model-free: stub the session layer instead -- `_stub_sessions` (fires on the "
            "prompt named 'happy'), `_canned_run` (a fixed stream through the real "
            "`run_session`), or `_no_sessions` (records and refuses). A real session spends "
            "rate-limit budget, takes ~94s, and in CI there are no credentials for it to "
            "spend anyway."
        )

    Popen = run

    def __getattr__(self, attr):
        return getattr(subprocess, attr)


@pytest.fixture(autouse=True)
def no_real_sessions(monkeypatch):
    """Make "nothing here reaches a model" structural instead of a convention.

    The package overview states that rule three times in prose -- module docstring, the safety-flag
    section, the isolation section -- and until now nothing enforced it. Each test that
    stays model-free does so because its author remembered to stub `run_session`; a new one
    that forgets spawns real `claude` processes against the rate limit, in CI, slowly and
    without saying so. The whole point of an autouse fixture here is that forgetting is the
    expected failure and it has to fail loudly.

    Patching `evals.runner.session`'s own `subprocess` REFERENCE rather than
    `subprocess.Popen` itself keeps the block scoped to that module, so the rest of the suite
    can still shell out --
    `tests/gate_check/` and friends run real processes on purpose.
    """
    monkeypatch.setattr(session, "subprocess", _NoRealSessions())
