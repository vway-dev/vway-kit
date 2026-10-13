"""게이트 자체 — 커밋된 baseline 이 모든 판정을 통과하는가.

측정하지 않은 스킬은 **경고**지 실패가 아님. 착륙하는 날 스위트를 붉게 만드는
하네스는 붉은 색을 정상으로 학습시키고, 그러면 정작 읽어야 할 freshness 실패가
아무도 안 보는 관중에게 도착함.
"""

from __future__ import annotations

import warnings

from evals.runner.baseline import (
    load_scores,
)
from evals.runner.case_corpus import (
    load_cases,
)
from evals.runner.session import (
    DEFAULT_CWD_LABEL,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._checks import (
    acceptance_failures,
    cwd_mismatches,
    gate_verdicts,
)


def test_the_committed_baseline_clears_every_gated_judgement():
    """Red when a description was edited without re-measuring (THE load-bearing one), when
    a score was taken on another model, when a skill never fires, when one hijacks more
    than a fifth of its neighbours' prompts, or when a skill declares nothing at all.

    One test rather than four because the ORDER those judgements are made in is itself
    part of the design -- splitting them into independent passes is what let an
    unmeasured-and-undeclared skill through as a warning. The message names which judgement
    failed; the meta-tests further down prove each branch can still bite.
    """
    verdicts = gate_verdicts(load_scores(), load_cases()[1])
    failures = [v.message for v in verdicts if v.level == "fail"]
    assert not failures, "\n".join(failures)


def test_accepted_drops_carry_a_reviewable_record():
    failures = acceptance_failures(load_scores())
    assert not failures, "\n".join(failures)


def test_the_gates_warnings_reach_a_human_without_turning_the_suite_red():
    """PASSES with a warning — see the module docstring for why these are not failures.

    Two things arrive here. An unmeasured skill has no evidence that it fires at all, and a
    measurement significantly below its declared `expect_invoke` says the description is not
    doing the job its author claimed for it. Neither can be a hard failure at n=25,
    and a suite that is red on arrival stops being read — but silence is the thing to avoid,
    so both have to reach a person somehow.

    A warning here is a FINDING, not a chore. Lowering the declaration to clear it is the
    one response that destroys the check: the gap between intent and measurement is the
    whole reason the declaration is not tuned to the baseline.
    """
    warned = [v.message for v in gate_verdicts(load_scores(), load_cases()[1]) if v.level == "warn"]
    if warned:
        warnings.warn(
            "eval gate warnings (spec 6.2 — information, not failure):\n" + "\n".join(warned),
            UserWarning,
            stacklevel=2,
        )


def test_baseline_measurements_share_the_current_measurement_cwd():
    """PASSES with a warning, like the unmeasured check above.

    Freshness pins the description, which does not pin the environment; without this check
    a baseline measured inside a real project and one measured in an empty temp dir are
    indistinguishable in the file.
    """
    problems = cwd_mismatches(load_scores(), load_cases()[1])
    if problems:
        warnings.warn(
            "eval baseline was measured in a different working directory than this "
            "runner uses now; scores are only comparable within one cwd (spec 5.1):\n"
            + "\n".join(problems),
            UserWarning,
            stacklevel=2,
        )


def test_the_cwd_check_notices_a_foreign_or_missing_directory():
    """The warning is only worth emitting if it can distinguish the cases at all."""
    assert cwd_mismatches({"skills": {"s": {"cwd": DEFAULT_CWD_LABEL}}}) == []
    assert cwd_mismatches({"skills": {"s": {"cwd": "C:/Work/some-real-project"}}})
    assert cwd_mismatches({"skills": {"s": {}}}), "a baseline with no recorded cwd is unknown"

    # ...and the expectation follows the skill's own fixtures, so a fixture-backed skill is
    # not permanently flagged for recording the project it is supposed to be measured in.
    fixtured = {"fixture": "empty-web", "happy": [{"prompt": "p"}], "negative": []}
    assert cwd_mismatches({"skills": {"s": {"cwd": "isolated:empty-web"}}}, {"s": fixtured}) == []
    assert cwd_mismatches({"skills": {"s": {"cwd": DEFAULT_CWD_LABEL}}}, {"s": fixtured}), (
        "a score measured in an empty dir for a skill that now gets a fixture is stale"
    )
