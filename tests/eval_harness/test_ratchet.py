"""래칫 — 떨어진 것과 흔들린 것을 가르는 통계.

고정 폭 상수 없음. 폭은 p 에 따라 변하고, 한쪽 방향이며, 두 측정의 n 이 달라도
성립함. 조건이 바뀐 측정은 비교 대상이 아니라 래칫을 **끔**.
"""

from __future__ import annotations

import json

import pytest

from evals import run as runner
from evals.runner import case_corpus, config, ratchet
from evals.runner.ratchet import (
    binom_cdf,
    ratchet_violations,
)
from evals.runner.session import (
    DEFAULT_CWD_LABEL,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._stubs import (
    _baseline,
    _canned_measurements,
    _measurement,
)


def test_a_changed_condition_suppresses_the_ratchet_instead_of_reading_as_a_drop(
    monkeypatch, tmp_path
):
    """A baseline measured at one turn budget and a re-measurement at another are two
    different experiments (spec 5.1). Comparing them reports a regression nobody caused,
    and a ratchet that cries wolf gets `--accept`ed on reflex until it means nothing.

    The drop here is far outside the noise band, so without the guard this is a
    CONFIRMED drop, a second 55-session measurement, and exit 4.
    """
    baseline = _baseline(invoke_rate=0.96, false_fire=0.04)
    # Derived from the constant, never a literal: this line held a hard-coded 6 chosen
    # because the default was 3, so raising the default to 6 made the two sides agree and
    # the test started exercising the ratchet it was written to prove was skipped.
    baseline["skills"]["vdev"]["max_turns"] = config.DEFAULT_MAX_TURNS + 3
    scores_path, calls = _canned_measurements(
        monkeypatch, tmp_path, baseline, [_measurement(invoke_rate=0.40, false_fire=0.04)]
    )
    assert runner.main(["--skill", "vdev"]) == 0, "a condition change must not fail the run"
    assert len(calls) == 1, "the runner paid for a confirmation of an incomparable drop"
    written = json.loads(scores_path.read_text(encoding="utf-8"))["skills"]["vdev"]
    assert written["invoke_rate"] == 0.40, "the new measurement must become the baseline"
    assert "lowered_from" not in written, "an incomparable change is not an accepted drop"


def test_incomparable_conditions_names_what_changed_and_tolerates_older_entries():
    """Missing is not changed: entries written before a condition was recorded would
    otherwise all read as incomparable, which would disable the ratchet everywhere at
    once -- the quietest possible way to lose the gate."""
    new = {"model": "m2", "max_turns": 3, "cwd": DEFAULT_CWD_LABEL}
    assert ratchet.incomparable_conditions(new, dict(new)) == {}
    assert ratchet.incomparable_conditions(new, {**new, "max_turns": 6}) == {"max_turns": (6, 3)}
    assert ratchet.incomparable_conditions(new, {**new, "model": "m1"}) == {"model": ("m1", "m2")}
    assert ratchet.incomparable_conditions(new, {"invoke_rate": 0.9}) == {}, (
        "a pre-conditions entry has nothing to compare, which is not a mismatch"
    )


def test_no_fixed_delta_constant_survives():
    """Asserted rather than left as a deletion note. A fixed width is the intuitive thing
    to reach for, and re-adding one beside the exact test would restore the ~20% per-run
    false-alarm rate while every other test here stayed green."""
    assert not hasattr(runner, "RATCHET_DELTA")


def test_the_ratchet_scales_with_p_instead_of_a_fixed_width():
    """The retired `RATCHET_DELTA = 0.10` was 0.78-0.87 sigma across the mid-range skills
    and cried wolf about a fifth of the time per run -- observed here as vdev moving
    0.80 -> 0.96 across runs of an unchanged corpus, with nothing but sampling between
    them. Binomial noise scales with p, so the threshold has to.

    The two rules agree at the top of the range and part company in the middle, which is
    precisely where the false alarms were: against a 16/25 baseline the fixed width
    tripped at 13/25 while the exact test waits for 11/25. The cost is real and stated in
    the spec -- that is all the resolution n=25 buys -- and the point of the exact test is
    that it does not HIDE the limit the way a constant did.
    """
    alpha = ratchet.alpha_single(9)
    assert not ratchet.ratchet_trips(13, 25, 16, 25, alpha), "the retired fixed width fired here"
    assert ratchet.ratchet_trips(11, 25, 16, 25, alpha)


def test_a_perfect_baseline_tolerates_one_miss():
    """Jeffreys shrink, `(k + 0.5) / (n + 1)`.

    Treating a recorded 25/25 as exactly 1.00 makes ANY miss infinitely significant --
    `P(X <= 24 | n=25, p=1)` is 0 -- and this baseline has TWO skills at 1.00
    (harness-insight, task-import). Without the shrink the gate reports both as confirmed
    regressions on its first re-measure and collapses on the day it lands.

    The justification is not convenience. A 25/25 does not mean the true rate is 1.00; it
    means 25 samples could not tell it apart from 1.00, and reading it as 25.5/26 concedes
    exactly that. Nor is it blunt: 23/25 passes and 22/25 still trips.
    """
    alpha = ratchet.alpha_single(9)
    assert not ratchet.ratchet_trips(24, 25, 25, 25, alpha)
    assert not ratchet.ratchet_trips(23, 25, 25, 25, alpha)
    assert ratchet.ratchet_trips(22, 25, 25, 25, alpha)


def test_the_ratchet_is_one_sided():
    """A rise never trips. A level once reached becomes the floor -- that is what makes it
    a ratchet -- and a gate that fired on improvements would be `--accept`ed away."""
    alpha = ratchet.alpha_single(9)
    assert not ratchet.ratchet_trips(25, 25, 16, 25, alpha)
    assert not ratchet.ratchet_trips(16, 25, 16, 25, alpha)


def test_the_exact_test_holds_when_the_two_measurements_have_different_n():
    """It compares k/n with k/n rather than one rounded rate with another, so a changed
    `reps` is no longer a reason to skip the comparison. That is what took `reps` out of
    `COMPARABLE_CONDITIONS`, and it is what makes a per-skill `reps` override possible."""
    alpha = ratchet.alpha_single(9)
    assert not ratchet.ratchet_trips(8, 10, 20, 25, alpha), "0.80 against a 0.80 baseline"
    assert ratchet.ratchet_trips(2, 10, 20, 25, alpha)


def test_the_family_alpha_is_split_across_the_skill_set_and_square_rooted():
    """`ALPHA_FAMILY` is the budget for the whole set per CONFIRMED regression. Testing
    every skill at 0.05 each turns one of them red per run on its own, so it is Sidak-
    corrected by the skill count and then square-rooted -- a fail needs two consecutive
    trips, and two independent trips at sqrt(a) compound back to a.

    The square root is where the confirmation re-measure stops being optional: drop it and
    that loose per-run alpha becomes the family-wise rate, which is no better than the delta
    era.

    `n` is passed explicitly here because the identity holds for ANY set size; the figure
    the corpus produces is not written here — it moves with the skill count, and
    `test_a_single_shot_judgement...` is the one that reads the corpus.
    """
    assert ratchet.ALPHA_FAMILY == 0.05
    for n in (9, 13, 20):
        assert ratchet.alpha_single(n) ** 2 * n == pytest.approx(ratchet.ALPHA_FAMILY, abs=0.002)
    assert ratchet.alpha_single(20) < ratchet.alpha_single(9), "more skills, tighter per-skill"


def test_a_single_shot_judgement_does_not_borrow_the_ratchets_square_root():
    """The sqrt in `alpha_single` is PAID FOR by the confirmation re-measure -- two trips at
    sqrt(a) compound to a. Reusing it for a judgement made once spends the family budget
    several times over, because nothing compounds.

    The declaration warning is that judgement: `check` compares one measurement with a
    human's stated intent and never re-measures.

    The skill count and the declared rates are read from the **corpus**, not copied here.
    A copy pins whichever corpus it was written against: every figure then describes a
    hypothetical set, which is the message-outlives-its-meaning fault the baseline ledger in
    `test_baseline.py` exists to prevent. So the assertions below are RELATIONS that hold
    for any corpus, and the decimals today's produces sit in the comments beside them with
    the conditions that produced them.
    """
    _default_reps, cases = case_corpus.load_cases()
    n_skills = len(cases)
    declared_rates = [
        spec["expect_invoke"] for spec in cases.values() if spec.get("expect_invoke") is not None
    ]
    assert declared_rates, "no skill declares a rate -- this test would assert nothing"

    single_shot, ratchet_alpha = ratchet.alpha_single_shot(n_skills), ratchet.alpha_single(n_skills)
    assert ratchet_alpha == pytest.approx(single_shot**0.5)
    # Sidak's defining property: one budget spread across the family, so n independent
    # tests at this alpha come back to ALPHA_FAMILY.
    assert 1 - (1 - single_shot) ** n_skills == pytest.approx(ratchet.ALPHA_FAMILY)

    def warn_probability(declared: float, alpha: float, n: int = 25) -> float:
        """P(the warning fires) when the description performs EXACTLY as declared."""
        fires = [k for k in range(n + 1) if binom_cdf(k, n, declared) < alpha]
        return binom_cdf(max(fires), n, declared) if fires else 0.0

    # Per declaration, the ratchet's looser alpha costs at least as many false alarms as the
    # single-shot one -- the ratchet pays for that with the confirmation re-measure and a
    # single-shot judgement has nothing to pay with. `<=` rather than `<` because a
    # declaration can sit low enough that no k fires under either alpha, and then both are 0.
    for declared in declared_rates:
        assert warn_probability(declared, single_shot) <= warn_probability(declared, ratchet_alpha)

    # Family-wise across every declaration: the ratchet's alpha blows the stated budget
    # several times over and the single-shot alpha stays inside it. The two figures are not
    # written down — they move with the skill count, which is why the assertion below is a
    # relation.
    family = {}
    for label, alpha in (("ratchet", ratchet_alpha), ("single_shot", single_shot)):
        survives = 1.0
        for rate in declared_rates:
            survives *= 1 - warn_probability(rate, alpha)
        family[label] = 1 - survives
    assert family["single_shot"] <= ratchet.ALPHA_FAMILY < family["ratchet"]
    assert family["ratchet"] > 3 * ratchet.ALPHA_FAMILY, family


def test_reps_is_no_longer_a_comparability_condition():
    """Reversed on purpose, and the reason it was added no longer holds.

    `reps` went into `COMPARABLE_CONDITIONS` alongside `RATCHET_DELTA`, on the argument
    that "`reps` fixes n, and n is the only thing holding the delta up". That was true of a
    fixed width, whose whole defensibility came from the standard error at one sample size.
    The exact binomial takes k and n as arguments, so a different `reps` is the same
    experiment run more times rather than a different experiment. The four that remain are
    still different experiments: another model, another turn budget, another environment,
    another set of questions.
    """
    assert set(ratchet.COMPARABLE_CONDITIONS) == {"model", "max_turns", "cwd", "corpus_sha"}
    conditions = {"model": config.MODEL, "max_turns": 3, "cwd": DEFAULT_CWD_LABEL}
    thinner, base = {**conditions, "reps": 3}, {**conditions, "reps": 5}
    assert ratchet.incomparable_conditions(thinner, base) == {}


def test_a_prompts_only_change_is_a_different_experiment_too():
    """`corpus_sha` had to join the compared conditions, and a fixture change is why the gap
    stayed invisible: it moves the `cwd` label as a side effect, so it was caught by accident
    rather than on purpose. A PROMPTS-only edit moves nothing else at all — same model, same
    budget, same fixtures, same directory label — so the ratchet compared the re-measurement
    against a baseline built from questions nobody asks any more, which is precisely what
    the corpus fingerprint exists to stop.

    This branch made the change it describes: doc-sync had five happy prompts rewritten and
    performance two. Today it is masked, because `max_turns` 3 -> 6 already marks every
    skill incomparable; the mask lifts on the next run.
    """
    conditions = {
        "model": config.MODEL,
        "max_turns": config.DEFAULT_MAX_TURNS,
        "cwd": DEFAULT_CWD_LABEL,
        "corpus_sha": "a" * 64,
    }
    rewritten = {**conditions, "corpus_sha": "b" * 64}
    assert ratchet.incomparable_conditions(rewritten, conditions) == {
        "corpus_sha": ("a" * 64, "b" * 64)
    }
    assert ratchet.incomparable_conditions(dict(conditions), conditions) == {}
    # Entries written before the fingerprint existed are missing it rather than wrong, and
    # the usual tolerance still applies -- otherwise adding the key would switch the ratchet
    # off for every committed entry at once, which is the failure mode that argument was
    # written for (see `incomparable_conditions`).
    older = {key: value for key, value in conditions.items() if key != "corpus_sha"}
    assert ratchet.incomparable_conditions(dict(conditions), older) == {}


def test_the_ratchet_flags_a_real_drop_and_ignores_a_wobble():
    """Both directions, since `invoke_rate` and `false_fire` move opposite ways and a sign
    error would leave one of them silently ungated.

    The `false_fire` side is kept deliberately. Its absolute ceiling only catches a skill
    once it is already over 0.20; a drift from 0/25 to 4/25 is a description getting
    greedier and stays under the ceiling the whole way.
    """
    base = _measurement(invoke_hits=24, invoke_n=25, false_hits=1, false_n=25)
    fell = _measurement(invoke_hits=17, invoke_n=25, invoke_rate=0.68)
    assert ratchet_violations(fell, base, n_skills=9) == {"invoke_rate": 0.96}
    wobbled = _measurement(invoke_hits=22, invoke_n=25, invoke_rate=0.88)
    assert ratchet_violations(wobbled, base, n_skills=9) == {}

    noisier = _measurement(false_hits=7, false_n=25, false_fire=0.28)
    assert ratchet_violations(noisier, base, n_skills=9) == {"false_fire": 0.04}
    assert ratchet_violations(_measurement(false_hits=3, false_n=25), base, n_skills=9) == {}

    # An improvement is never a violation, there is no baseline to fall from on a first
    # measurement, and a null arm cannot be compared at all.
    assert ratchet_violations(_measurement(invoke_hits=25, false_hits=0), base, n_skills=9) == {}
    assert ratchet_violations(_measurement(invoke_hits=2), None, n_skills=9) == {}
    no_happy = _measurement(invoke_hits=None, invoke_n=None, invoke_rate=None)
    assert ratchet_violations(no_happy, base, n_skills=9) == {}
    # `truncated` is recorded, never gated (spec 4): it reports how much of the score is
    # an artefact of `--max-turns`, so blocking on it would block on a constant.
    assert ratchet_violations({"truncated": 0.99}, {"truncated": 0.01}, n_skills=9) == {}
