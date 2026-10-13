"""안전 플래그 — `--dry-run` 은 세션을 하나도 시작하지 않음.

계획은 첫 세션 **전에** 출력되고, CLI 가 PATH 에 없어도 돎.
"""

from __future__ import annotations

import pytest

from evals import run as runner
from evals.runner import config, session
from evals.runner.case_corpus import (
    load_cases,
)
from evals.runner.config import (
    EvalError,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._stubs import (
    _no_sessions,
)


def test_dry_run_starts_no_session_at_all(monkeypatch, capsys):
    """The flag's entire contract. Asserted against the stub rather than by reading the
    code, because "it looked like it returned early" is what an accidental full run sounds
    like afterwards."""
    started = _no_sessions(monkeypatch)
    assert runner.main(["--all", "--max-turns", "6", "--dry-run"]) == 0
    assert started == [], f"--dry-run started {len(started)} session(s)"
    out = capsys.readouterr().err
    assert "TOTAL 497 session(s)" in out and "~195min" in out, out


def test_the_plan_is_printed_before_the_first_session(monkeypatch, capsys):
    """A cost disclosed after the bill is not a disclosure. The stub raises on its first
    call, so anything already on stderr necessarily preceded every session."""
    started = _no_sessions(monkeypatch)
    with pytest.raises(EvalError):
        runner.measure(runner.build_parser().parse_args(["--all"]))
    assert started, "the stub never ran, so this test proves nothing about ordering"
    out = capsys.readouterr().err
    assert "TOTAL 497 session(s)" in out, f"the plan was not printed before session 1: {out!r}"
    # The figure is derived, not literal. A hard-coded "~91min" here asserted that the
    # default turn budget had not moved, so raising it reddened a test about ORDERING.
    reps, cases = load_cases()
    args = runner.build_parser().parse_args(["--all"])
    planned = runner.build_plan(args, cases, reps, list(cases))
    assert f"~{round(planned.hours * 60)}min" in out, out


def test_dry_run_needs_no_cli_on_path(monkeypatch, capsys):
    """--dry-run answers "what would this cost?" on a host with no `claude` installed --
    including CI, where nobody should be able to trip a measurement by accident."""
    monkeypatch.setattr(session.shutil, "which", lambda _: None)
    monkeypatch.setattr(session, "run_session", lambda *a, **k: pytest.fail("session started"))
    assert runner.main(["--all", "--dry-run"]) == 0
    assert "TOTAL 497 session(s)" in capsys.readouterr().err


def test_the_plan_matches_the_designs_own_budget_table():
    """Spec 7 prices the full run at 497 sessions -- ~97min at 3 turns, ~195 at 6. Those
    numbers are what a reader decides against, so drift between the plan and the design
    is a defect in whichever one moved.

    The session count does NOT move with the turn budget; only the wall-clock does. That
    is the whole reason raising `--max-turns` is a real decision rather than a free one.
    """
    reps, cases = load_cases()
    parser = runner.build_parser()
    # Both budgets are priced explicitly rather than one of them riding on whatever the
    # default happens to be. The anchor is measured AT three turns, so a test that asked
    # for "the default" was asserting that the default had not moved -- and when it
    # moved to 6 this line failed for a reason that had nothing to do with the budget table.
    narrow = runner.build_plan(parser.parse_args(["--all", "--max-turns", "3"]), cases, reps, cases)
    assert (narrow.total_sessions, round(narrow.hours * 60)) == (497, 97)
    wide = runner.build_plan(parser.parse_args(["--all", "--max-turns", "6"]), cases, reps, cases)
    assert (wide.total_sessions, round(wide.hours * 60)) == (497, 195)
    # The default is one of the two, and the estimate follows it. This is what caught the
    # anchor being re-read: `wall_clock_per_session` divided by `DEFAULT_MAX_TURNS`, so
    # raising the default kept quoting 91 minutes for a run that had doubled.
    full = runner.build_plan(parser.parse_args(["--all"]), cases, reps, list(cases))
    assert full.hours == (wide if config.DEFAULT_MAX_TURNS == 6 else narrow).hours
    solo = parser.parse_args(["--skill", "vdev", "--max-turns", "3"])
    one = runner.build_plan(solo, cases, reps, ["vdev"])
    assert (one.total_sessions, round(one.hours * 60)) == (61, 12)
