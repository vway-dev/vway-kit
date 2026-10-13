"""Whether a new measurement is a regression: the exact binomial test, its family-wise alpha,
the conditions two measurements must share to be compared, and confirmation merging.
"""

from __future__ import annotations

import math
from typing import Any

from evals.runner import case_corpus, config

# The family-wise false-alarm budget for the WHOLE skill set, per confirmed regression.
# The per-run per-skill threshold is derived from it in `alpha_single`.
#
# There is no `RATCHET_DELTA` here any more. A fixed width was the wrong tool, not a
# badly-chosen number: binomial noise scales with p and a constant does not. At n=25 and
# p≈0.8 the difference between two runs carries SE 0.113, so δ=0.10 was 0.88σ — a one-sided
# false alarm about every fifth run on a corpus nobody touched. That arithmetic was
# observed, not predicted: three full runs of an unchanged corpus moved vdev 0.80 -> 0.96,
# past the delta, with only sampling between them.
#
# The replacement compares k/n with k/n exactly (`ratchet_trips`). It is not uniformly
# looser or tighter — at the top of the range the two rules trip at the same place; they
# part company in the mid-range, which is where the false alarms lived.
ALPHA_FAMILY = 0.05


def alpha_single_shot(n_skills: int) -> float:
    """Per-run, per-skill threshold for a judgement made ONCE, with no confirmation.

    Šidák over the skill family and nothing more. Testing every skill at 0.05 each turns
    one of them red per run on its own; the correction spends one budget across the set.

    `alpha_single` below is this value square-rooted, and that square root is PAID FOR by
    the confirmation re-measure — two independent trips at sqrt(α) compound back to α. A
    single-shot judgement has no second reading to compound with, so it has to use this
    one. Reusing the looser ratchet value for a single-shot test spends the family budget
    several times over, which is not a hypothetical: computed at n=25, a declaration of
    0.75 warns on 0.030 of runs whose true rate IS the declared one, 0.85 on 0.026 and
    0.70 on 0.044. Across every declaration in the corpus that compounds to several times
    the stated budget of 0.05 — a warning lit far more often than advertised, and this repo's
    own position is that a permanently-lit warning is not a signal. The figure itself is not
    written down here: it moves with the skill count, and one added skill made an earlier
    version of this sentence wrong the same day. `tests/eval_harness/test_ratchet.py` reads
    the count and the rates from the corpus and asserts the relation instead.
    """
    return 1 - (1 - ALPHA_FAMILY) ** (1 / n_skills)


def alpha_single(n_skills: int) -> float:
    """Per-run, per-skill trip threshold for the RATCHET, which confirms before it fails.

    Šidák over the skill family, then square-rooted. The square root is there because a
    FAIL requires two consecutive trips (the confirmation re-measure), and two independent
    trips at sqrt(α) compound to α — so the per-run alpha stays loose (a few percent at the
    corpus sizes this repo has) while the family-wise rate after confirmation is
    `ALPHA_FAMILY`.

    That square root is also where the confirmation re-measure stops being optional: drop
    it and that loose per-run alpha becomes the family-wise rate, which is no improvement on
    the delta era. The tool changed; the re-measure being a load-bearing part did not.

    It is therefore only valid for a test that re-measures. Anything judged in one shot
    reads `alpha_single_shot`, which is where the derivation above holds.
    """
    return alpha_single_shot(n_skills) ** 0.5


def binom_cdf(k: int, n: int, p: float) -> float:
    """Lower tail P(X <= k) for X ~ Binomial(n, p). Exact, stdlib `math.comb` only.

    No SciPy: this runs inside `uv run pytest`, which must stay a millisecond-scale gate
    with no dependency a consumer host would have to install.
    """
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def _shrunk(k: int, n: int) -> float:
    """Jeffreys-shrunk reference rate, `(k + 0.5) / (n + 1)`.

    Reading a recorded rate as exact breaks at the ends. At p=1.00, P(X <= n-1) is 0, so a
    single miss becomes infinitely significant — and this baseline has two skills at 1.00,
    which is enough to collapse the gate on its first re-measure. The shrink is not a
    fudge: a 25/25 does not mean the true rate is 1.00, it means 25 samples could not tell
    it apart from 1.00, and 25.5/26 concedes exactly that. It stays sharp — against a
    25/25 baseline, 23/25 passes and 22/25 trips.
    """
    return (k + 0.5) / (n + 1)


def ratchet_trips(k_new: int, n_new: int, k_base: int, n_base: int, alpha: float) -> bool:
    """Did the new measurement fall significantly BELOW the recorded baseline?

    One-sided low tail, so a rise never trips — a level once reached becomes the floor.
    Valid when `n_new != n_base`, because it compares k/n with k/n rather than one rounded
    rate with another.
    """
    return binom_cdf(k_new, n_new, _shrunk(k_base, n_base)) < alpha


def ratchet_trips_upward(k_new: int, n_new: int, k_base: int, n_base: int, alpha: float) -> bool:
    """The same test for a metric where higher is WORSE (`false_fire`).

    Kept rather than dropped when the delta went. `false_fire` has an absolute ceiling in
    the gate, but a ceiling alone lets a skill drift 0/25 -> 4/25 unremarked, and that
    drift is a description getting greedier — exactly what the ratchet is for. The upper
    tail is P(X >= k), i.e. one minus the lower tail below it.
    """
    if k_new == 0:
        return False  # nothing to be significant about, and binom_cdf(-1, ...) is 0
    return 1 - binom_cdf(k_new - 1, n_new, _shrunk(k_base, n_base)) < alpha


# The conditions a score is only meaningful relative to. Two measurements taken under
# different values of any of these are two different experiments, and the difference
# between them is not a regression.
#
# `reps` is NOT one of them. The case for it belongs to `RATCHET_DELTA`: "`reps` fixes n,
# and n is the only thing holding the delta up" — true of a fixed width, whose entire
# defensibility came from the standard error at one sample size, so comparing across
# sample sizes compared two different noise floors.
# The exact binomial takes k and n as arguments and is valid when they differ, so the
# premise is gone and the entry with it. A different `reps` is the same experiment run
# more times. The four here are genuinely different experiments: another
# model, another turn budget, another environment, another set of questions.
#
# `corpus_sha` is the fourth and it was missing. A score's inputs are (description, prompts,
# fixture) and the last two are exactly what that key fingerprints, so a prompts-only edit
# left the ratchet comparing k/n against a baseline measured on questions that no longer
# exist — the incomparable-baseline fault, reached from the one direction nothing guarded.
# A FIXTURE change was already caught, but only incidentally: it moves the `cwd` label as a
# side effect.
# Rewriting five happy prompts moves nothing else at all, and this branch did exactly that
# to doc-sync (×5) and performance (×2).
#
# It does NOT make `measurement_is_current` redundant. That reader decides whether to spend
# one skill's worth of sessions re-measuring; this one decides whether the number that
# comes back may be ratcheted against the old one. Both have to say "changed", or the
# re-measure the first one demanded lands as a regression nobody caused.
COMPARABLE_CONDITIONS = ("model", "max_turns", "cwd", "corpus_sha")


def incomparable_conditions(new: dict, previous: dict) -> dict[str, tuple[Any, Any]]:
    """Conditions that changed between two measurements, as {name: (old, new)}.

    A baseline taken at `--max-turns 6` and a re-measurement at the default 3 differ by
    the budget, not by the skill — and the sister repo's data says that gap alone is
    worth 0.6 of `truncated`. Ratcheting across it reports a regression nobody caused,
    which trains people to `--accept` on reflex, and a reflexive accept ends the ratchet.

    Entries written before a condition was recorded have it missing rather than wrong,
    so a missing key on EITHER side is not treated as a change.
    """
    changed: dict[str, tuple[Any, Any]] = {}
    for key in COMPARABLE_CONDITIONS:
        old, now = previous.get(key), new.get(key)
        if old is None or now is None:
            continue
        if old != now:
            changed[key] = (old, now)
    return changed


# Which integers back each gated ratio, and which direction is worse. The ratchet reads
# the counts; the ratios beside them exist so a human can read a diff.
COUNTS_FOR_METRIC = {
    "invoke_rate": ("invoke_hits", "invoke_n", ratchet_trips),
    "false_fire": ("false_hits", "false_n", ratchet_trips_upward),
}


def ratchet_violations(new: dict, previous: dict | None, *, n_skills: int) -> dict[str, float]:
    """Metrics that fell significantly below the recorded baseline.

    Returns {metric: previous_rate} — the rate rather than the counts, because the value is
    only ever rendered into a message or a `lowered_from` record. "Significantly" is an
    exact one-sided binomial test against the Jeffreys-shrunk baseline at
    `alpha_single(n_skills)`, so the threshold scales with p instead of being a constant
    that is 0.88σ in the mid-range and 2σ at the top.

    Only `GATED_METRICS` are considered: `truncated` reports how much of the score is an
    artefact of `--max-turns`, so ratcheting it would ratchet a constant.

    An entry on either side that carries no counts is skipped rather than guessed at. That
    is not a silent hole — `tests/eval_harness/` FAILS any committed entry missing them, so
    a countless baseline cannot sit in this file quietly; it can only be a hand-edit that
    the gate reports on the next `pytest`.
    """
    if not previous:
        return {}
    alpha = alpha_single(n_skills)
    worse: dict[str, float] = {}
    for metric in config.GATED_METRICS:
        hits_key, n_key, trips = COUNTS_FOR_METRIC[metric]
        counts = [side.get(key) for side in (new, previous) for key in (hits_key, n_key)]
        if any(not isinstance(value, int) or isinstance(value, bool) for value in counts):
            continue
        k_new, n_new, k_base, n_base = counts
        if n_new < 1 or n_base < 1:
            continue
        if trips(k_new, n_new, k_base, n_base, alpha):
            worse[metric] = float(previous[metric])
    return worse


def merge_confirmation(first: dict, second: dict) -> dict:
    """Fold a confirmation re-measure into one entry.

    The recorded numbers are the SECOND measurement's, and that needs no cherry-picking
    rule: when the second run refutes a suspected drop it is *necessarily* the higher
    reading — tripping the test against the baseline is what made the first suspect, and
    not tripping it is what cleared the second, and the test is monotone in k. So
    "record the second" and "record the
    higher value" are the same instruction here, minus the optimistic bias that taking
    the better of two samples would introduce on metrics nobody questioned.

    Both readings survive under `confirmation` so a reviewer sees the pair rather than
    a number that hides how it was reached.
    """
    entry = dict(second)
    pair: dict[str, list[float]] = {}
    for metric in config.GATED_METRICS:
        one, two = first.get(metric), second.get(metric)
        if not isinstance(one, int | float) or not isinstance(two, int | float):
            continue
        pair[metric] = [float(one), float(two)]
    entry["confirmation"] = pair
    return entry


def confirmation_cost(spec: dict, default_reps: int) -> int:
    """Sessions one confirmation re-measure costs: every case of that skill, run again
    (~50 for a 5-happy/5-negative skill at reps=5).

    Priced at the SKILL's effective reps, not the corpus default: a skill that declared its
    own is re-measured at its own, and quoting the operator the default would understate the
    cost of exactly the skills that opted into more sampling.
    """
    cases = len(spec.get("happy") or []) + len(spec.get("negative") or [])
    return cases * case_corpus.effective_reps(spec, default_reps)
