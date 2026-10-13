"""게이트 판정 — `*_failures(scores) -> list[str]` 모양의 검사들.

맨 assert 가 아니라 목록을 돌려주는 이유: 이빨 빠진 게이트를 스스로 탐지하려면
검사에 조작된 baseline 을 먹여 붉어지는지 볼 수 있어야 함.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from evals.runner import case_corpus, config, ratchet, session
from evals.runner.baseline import (
    _hook_assisted,
    description_sha,
)
from evals.runner.config import (
    CASES_PATH,
    GATED_METRICS,
    SCORES_PATH,
    SKILLS_DIR,
    EvalError,
)
from evals.runner.ratchet import (
    alpha_single,
    binom_cdf,
)
from evals.runner.session import (
    DEFAULT_CWD_LABEL,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
FALSE_FIRE_CEILING = 0.20

# There is NO global `invoke_rate` floor, and there is no longer a plan to set one from
# data. The first value, 0.80, was a guess written before a single skill had been measured;
# the committed baseline runs 0.16 / 0.32 / 0.64 / 0.72 / 0.72 / 0.96 / 1.00 / 1.00 (plus
# one null), so nothing would have cleared it and a suite red on arrival stops being read.
#
# It was then put to sleep with "measure everything, then set it from the distribution",
# and THAT is the sentence the design retires. A floor derived from a distribution passes that
# distribution by construction — the measurement sets the standard and the standard passes
# the measurement, which carries zero bits about whether a skill is doing its job. The
# sister repo ran the experiment and picked 0.25 that way, then had to bolt an
# `exempt_floor` onto it, because skills fire at different proper rates BY DESIGN.
#
# The replacement is per-skill: `expect_invoke` / `expect_why` in cases.yaml, declared as
# intent and deliberately not tuned to the baseline. What survives from the old
# floor is the requirement that its absence be ASSERTED rather than assumed — "deliberately
# off" and "silently broken" must not look alike. That assertion now lives on the
# declaration: a skill that declares nothing FAILS, before any other judgement.
#
# One data-independent floor does remain, `invoke_hits == 0`, and it reads the integer.
#
# Retracted here as well: the claim that a floor would be gating truncation rather than
# description. It cited numbers spliced across two runs of different sizes, and the skill it
# named as truncation-confounded (playwright-scaffold) was re-measured at six turns where
# NOTHING was cut and scored 0.07 against 0.16 — the budget does not explain it. What went
# wrong next is the part worth keeping: "not the budget" was written down as "therefore the
# description", skipping the explanations nobody had tested. Two have since been measured.
# Isolating the config dir (95 skills visible -> 30) moved it 0.00 -> 0.13, and every probe
# ran at n=15 where the standard error is ~0.10 — the unchanged control arm alone read
# 0.00 / 0.13 / 0.13 across three runs, so none of them could resolve anything. Separating a
# 0.15 difference at 80% power needs n≈114 per arm. The sister repo settles it with no new
# sessions: the same skill, same trigger wording, measured inside the project fixture its
# prompts describe and against an isolated plugin set, scores 15/15. A 0.84 gap is a
# measurement condition, not a description defect.

# The integers every judgement below reads. The ratios beside them in `scores.json` are
# derived fields for humans: a committed file gets hand-edited, and rounding hides both
# ends (a true 0.204 rounds to a passing 0.20; one hit in a large n rounds to 0.00).
COUNT_KEYS = ("invoke_hits", "invoke_n", "false_hits", "false_n")

# Negatives are near x4 + far <=1. The cap is the point of the split — near cases
# are the ones that measure precision (they share the skill's own vocabulary), so a
# corpus that drifts toward far cases scores 0.00 while proving nothing.
MAX_FAR_NEGATIVES = 1
VALID_KINDS = frozenset({"near", "far"})

# Its description forbids direct invocation, so a happy case would measure the
# very thing the skill says not to do. Any OTHER skill with no happy cases is
# unmeasured for invoke_rate, which is a hole, not a design.
NO_HAPPY_PATH = frozenset({"harness-authoring", "alm-fetch"})


def _is_number(value: object) -> bool:
    """`True` is an `int` in Python, and `true` in JSON would sail past `>= 0.80`."""
    return isinstance(value, int | float) and not isinstance(value, bool)


# ------------------------------------------------------------- the model-free guarantee


# ------------------------------------------------------------------ the three checks


class Declaration(NamedTuple):
    """What `cases.yaml` says this skill's description OUGHT to achieve, and why.

    `expect` is `None` only for a skill with no happy path at all — a judgement,
    not a missing value. The difference between that and "nobody wrote a declaration" is
    carried by whether a `Declaration` exists at all, never by this field.
    """

    expect: float | None
    why: str


class Verdict(NamedTuple):
    level: str  # "ok" | "warn" | "fail"
    message: str


def read_declaration(name: str, spec: dict) -> Declaration | str:
    """The skill's declaration, or the message explaining why it does not have one.

    A string return is a FAILURE, and the caller must treat it as one before looking at
    anything else. There is no global constant left to fall back on, so an
    undeclared skill is one this gate can say nothing at all about.
    """
    if "expect_invoke" not in spec:
        return (
            f"{name}: declare `expect_invoke` and `expect_why` in {CASES_PATH.name}. The "
            f"global invoke_rate floor was retired (spec 6.2) and nothing replaces it "
            f"generically -- state the rate this description should reach and why."
        )
    why = spec.get("expect_why")
    if not isinstance(why, str) or not why.strip():
        return (
            f"{name}: expect_invoke is declared with no `expect_why`. The number alone "
            f"cannot be reviewed -- the claim is about how directly these prompts name "
            f"this skill, and that claim has to be readable beside the value."
        )
    expect = spec.get("expect_invoke")
    if expect is None:
        # The one decision the design leaves open. Null is a legal DECLARATION ("this skill has
        # no happy path, so there is no rate to expect"), distinguished from an omission by
        # the key's presence rather than by its value. The licence is the same reviewed
        # registry that already permits an empty `happy` list, so a new skill cannot grant
        # itself the exemption by writing null and going unmeasured.
        if name not in NO_HAPPY_PATH:
            return (
                f"{name}: expect_invoke is null, but only {sorted(NO_HAPPY_PATH)} may "
                f"declare no expectation (spec 3.1). A skill with happy cases has a rate "
                f"to expect; write it."
            )
        return Declaration(None, why)
    if not _is_number(expect) or not 0 < expect <= 1:
        return f"{name}: expect_invoke {expect!r} is not a rate in (0, 1]"
    return Declaration(float(expect), why)


def check(
    name: str,
    entry: dict | None,
    sha: str,
    declaration: Declaration | str,
    *,
    n_skills: int,
    corpus: str | None = None,
) -> Verdict:
    """One skill's verdict. THE ORDER OF THESE BRANCHES IS PART OF THE DESIGN.

    Specifically, the undeclared FAIL comes before the unmeasured WARN. Reading the
    entry first returns "not measured yet" for a skill that is both unmeasured and
    undeclared -- which is exactly a newly added skill, the case the forcing function
    exists for -- and it would pass as a warning.

    `corpus` is the skill's current `corpus_sha`. `gate_verdicts` always supplies it; the
    default exists for the meta-tests below, which construct one branch at a time and would
    otherwise all have to compute a fingerprint irrelevant to what they are exercising.
    """
    if isinstance(declaration, str):
        return Verdict("fail", declaration)
    if entry is None:
        return Verdict("warn", f"{name}: not measured yet -- run `python -m evals.run`")

    # The threat model is a hand-edited scores.json (the same one `lowered_from` assumes),
    # plus a baseline written before counts existed. Either way a missing key has to name
    # the skill and the prescription rather than surface as a bare KeyError, which reads
    # like a bug in the harness instead of a stale record.
    missing = [key for key in COUNT_KEYS if key not in entry]
    if missing:
        return Verdict("fail", f"{name}: entry is missing {missing} -- re-measure")
    counts = {key: entry[key] for key in COUNT_KEYS}
    malformed = [
        f"{key}={value!r}"
        for key, value in counts.items()
        if value is not None and (not isinstance(value, int) or isinstance(value, bool))
    ]
    if malformed:
        return Verdict("fail", f"{name}: {', '.join(malformed)} is not an integer or null")
    if counts["invoke_n"] is None and counts["false_n"] is None:
        # An entry that measures nothing while passing every threshold is the cheapest way
        # to launder a failing skill into a green suite.
        return Verdict(
            "fail",
            f"{name}: both arms are null -- this entry passes the gate without measuring "
            f"anything. Re-measure or delete it.",
        )

    # Freshness, the judgement the design calls its core. A score is a claim about the
    # text that decided the invocation; once that text moves the claim is about something no
    # longer shipped, and every other check here goes on passing.
    #
    # Naming BOTH inputs matters: for a `hook_assisted` skill the hash also covers what the
    # SessionStart hook injects, so a mismatch here often means the rule file moved and
    # SKILL.md did not. A message that blamed SKILL.md alone would send the reader to diff a
    # file that never changed and conclude the gate is broken.
    if entry.get("description_sha") != sha:
        moved = (
            f"skills/{name}/SKILL.md, or the text the SessionStart hook injects"
            if _hook_assisted(name)
            else f"skills/{name}/SKILL.md"
        )
        return Verdict(
            "fail",
            f"{name}: measured against description_sha {str(entry.get('description_sha'))[:12]}"
            f"..., but it now hashes to {sha[:12]}... {moved} changed since the measurement, "
            f"so this score describes text that is no longer shipped. "
            f"Re-measure: uv run python -m evals.run --skill {name}",
        )
    # The other half of freshness. The sha says the score measured this description; the
    # model says it measured it on the model the gate is pinned to. Model identity swings a
    # skill's rate 0.0 <-> 1.0 on the same case, so a mismatched fingerprint is
    # every bit as stale as an old sha.
    if entry.get("model") != config.MODEL:
        return Verdict(
            "fail",
            f"{name}: measured on model {entry.get('model')!r}, gate pinned to "
            f"{config.MODEL!r} -- re-measure",
        )
    # The third fingerprint, and the one whose absence was demonstrated to be exploitable:
    # `invoke_rate`'s inputs are (description, prompts, fixture), and pinning only the first
    # let all five of a skill's happy prompts be replaced with the gate silent and the
    # incremental selection empty. A description can be perfectly current while the score
    # certifying it answers questions nobody asks any more.
    recorded_corpus = entry.get("corpus_sha")
    if corpus is not None and recorded_corpus is not None and recorded_corpus != corpus:
        return Verdict(
            "fail",
            f"{name}: measured against corpus_sha {str(recorded_corpus)[:12]}..., but the "
            f"prompts and fixtures in {CASES_PATH.name} now hash to {corpus[:12]}... The "
            f"cases changed since the measurement, so this score describes questions that "
            f"are no longer asked. Re-measure: uv run python -m evals.run --skill {name}",
        )
    if corpus is not None and recorded_corpus is None:
        # An entry written before the fingerprint existed. A WARN rather than a FAIL,
        # because the entry is not wrong about anything -- it predates the key, and
        # failing here would red the suite over a gap the next measurement closes by itself
        # (the same argument that makes an unmeasured skill a warning). The runner is the
        # strict half: `measurement_is_current` reads a missing corpus_sha as stale, so the
        # skill is SELECTED for re-measurement rather than skipped.
        #
        # Placed ahead of the declaration warn below on purpose. Both are warnings, and this
        # one qualifies the other: an undershoot measured against unknown prompts may be
        # about prompts that no longer exist, so saying which prompts were used comes first.
        return Verdict(
            "warn",
            f"{name}: entry carries no `corpus_sha`, so it cannot vouch for the prompts and "
            f"fixtures now in {CASES_PATH.name}. The next measurement records it.",
        )

    # The declaration and the entry have to agree about whether a happy arm EXISTS, or the
    # null path becomes a laundering route: null out `invoke_hits`/`invoke_n` on a skill
    # that is failing its floor and every judgement below skips it, leaving a green entry
    # for a description nothing measured. `harness-authoring` is the only skill allowed to
    # have no happy arm, and it says so in its declaration rather than in its numbers.
    if (declaration.expect is None) != (counts["invoke_n"] is None):
        return Verdict(
            "fail",
            f"{name}: {CASES_PATH.name} declares expect_invoke={declaration.expect!r} but the "
            f"entry records invoke_n={counts['invoke_n']!r} -- one of them says this skill has "
            f"a happy path and the other says it does not. Re-measure.",
        )

    # The one surviving data-independent floor, and it reads the INTEGER: at a large enough
    # n a single hit rounds to 0.00, which would make "never" and "rare" the same value. A
    # committed all-zero baseline must never be green, because that zero would freeze in as
    # the ratchet's reference; if the true rate is merely low, a re-measure produces
    # something nonzero and this failure is what forces it.
    if counts["invoke_n"] is not None and counts["invoke_hits"] == 0:
        return Verdict(
            "fail", f"{name}: invoke_rate is 0 -- the description never fires, re-measure"
        )
    # Counts again, not the rounded rate: at a reps-raised n a true rate in (0.20, 0.205]
    # rounds down to a passing 0.20. A skill over this ceiling hijacks sessions it has no
    # business in -- a shipped defect at any calibration, which is why this one threshold
    # stays an absolute constant while the invoke side became a per-skill declaration.
    if (
        counts["false_n"] is not None
        and counts["false_hits"] > FALSE_FIRE_CEILING * (counts["false_n"])
    ):
        return Verdict(
            "fail",
            f"{name}: false_fire {counts['false_hits']}/{counts['false_n']} > "
            f"{FALSE_FIRE_CEILING} -- the skill fires on prompts written to keep it out. "
            f"Narrow the description, then re-measure.",
        )
    # Not reachable through the CLI, and deliberately kept anyway: `run.py` writes the two
    # keys together and argparse refuses `--accept` without `--reason`. That is exactly why
    # it is worth checking -- the state it catches is a hand edit that lowers a committed
    # number and deletes the justification, the one change that turns the ratchet's audit
    # trail back into a bare score.
    if "lowered_from" in entry and not entry.get("lowered_reason"):
        return Verdict("fail", f"{name}: lowered_from recorded with no lowered_reason")

    # A WARN, not a fail. n=25 cannot support hard-failing an aspiration, and a suite
    # red by default stops being read -- the same argument that retired the guessed 0.80.
    # The declaration gap is information; enforcement is the ratchet's job. Same exact
    # binomial the ratchet uses, against a different reference: the ratchet measures against
    # yesterday's k/n, this against a human's stated intent.
    #
    # But NOT the same alpha, and this once read `alpha_single`. That value is Sidak over
    # the family and then SQUARE-ROOTED, and the square root is paid for by the ratchet's
    # confirmation re-measure -- two trips at sqrt(a) compound back to a. This judgement is
    # single-shot: there is no second reading, so nothing compounds and the sqrt is only a
    # loosening. Measured cost of the mistake, at n=25 with a true rate EQUAL to the
    # declared one: 0.030 warn probability at 0.75, 0.026 at 0.85, 0.044 at 0.70 -- 0.33
    # family-wise across every declaration in the corpus against a stated budget of
    # 0.05. Warn-only, so it blocked nothing, but a warning lit several times more often
    # than advertised is the permanently-lit warning this repo's own design says is not a
    # signal. The relation, not these decimals, is what `test_ratchet` holds -- it reads
    # the count and the rates from the corpus so a corpus edit cannot leave it asserting a
    # set that no longer exists.
    if declaration.expect is not None and counts["invoke_n"]:
        if binom_cdf(
            counts["invoke_hits"], counts["invoke_n"], declaration.expect
        ) < ratchet.alpha_single_shot(n_skills):
            return Verdict(
                "warn",
                f"{name}: invoke_rate {counts['invoke_hits']}/{counts['invoke_n']} is "
                f"significantly below its declared expectation {declaration.expect:.2f} -- "
                f"the description needs work. Declared because: {declaration.why.strip()}",
            )
    return Verdict("ok", f"{name}: ok")


def gate_verdicts(scores: dict, cases: dict, skills_dir: Path = SKILLS_DIR) -> list[Verdict]:
    """Every skill's verdict, iterating the CORPUS rather than the baseline.

    Iterating `scores` would make an unmeasured skill invisible, which is the same hole the
    ordering inside `check` closes one level down. The union is taken so that an entry for a
    skill that has left `cases.yaml` is reported too, rather than being dropped along with
    whatever it was still claiming.
    """
    measured = scores.get("skills", {})
    verdicts: list[Verdict] = []
    for name in sorted(set(cases) | set(measured)):
        if name not in cases:
            verdicts.append(
                Verdict(
                    "fail",
                    f"{name}: {SCORES_PATH.name} holds a score for a skill absent from "
                    f"{CASES_PATH.name} -- delete the entry or restore the cases.",
                )
            )
            continue
        try:
            sha = description_sha(skills_dir / name)
        except EvalError as exc:
            verdicts.append(
                Verdict(
                    "fail",
                    f"{name}: cases exist for a skill that cannot be fingerprinted ({exc}) "
                    f"-- delete the entry or restore the skill.",
                )
            )
            continue
        verdicts.append(
            check(
                name,
                measured.get(name),
                sha,
                read_declaration(name, cases[name]),
                n_skills=len(cases),
                corpus=case_corpus.corpus_sha(cases[name]),
            )
        )
    return verdicts


def acceptance_failures(scores: dict) -> list[str]:
    """`lowered_from` records that must stay readable in a diff.

    Accepting a drop is the design's only escape hatch, and it is deliberately a
    ceremony: the record has to say what fell and why, or the next reviewer sees a
    lower baseline with no way to tell a considered trade-off from a regression that
    someone shrugged at.
    """
    failures: list[str] = []
    for name, entry in sorted(scores.get("skills", {}).items()):
        lowered = entry.get("lowered_from")
        if lowered is None:
            continue
        if not isinstance(lowered, dict) or not lowered:
            failures.append(f"{name}: lowered_from is {lowered!r}, expected a metric->value map")
            continue
        reason = entry.get("lowered_reason")
        if not isinstance(reason, str) or not reason.strip():
            failures.append(
                f"{name}: lowered_from {sorted(lowered)} carries no lowered_reason -- an "
                f"unexplained lowered baseline is not a record."
            )
        for metric, old in sorted(lowered.items()):
            if metric not in GATED_METRICS:
                failures.append(f"{name}: lowered_from names {metric!r}, not a gated metric")
                continue
            now = entry.get(metric)
            if not _is_number(old) or not _is_number(now):
                failures.append(f"{name}: lowered_from[{metric}] compares {old!r} to {now!r}")
                continue
            hits_key, n_key, trips = ratchet.COUNTS_FOR_METRIC[metric]
            hits, total = entry.get(hits_key), entry.get(n_key)
            if not isinstance(hits, int) or not isinstance(total, int) or total < 1:
                # Not skipped quietly. Without counts there is no way to ask whether the
                # runner would ever have demanded `--accept` for this drop, and the record
                # is exactly the artefact a hand edit produces.
                failures.append(
                    f"{name}: lowered_from[{metric}] cannot be checked -- the entry carries "
                    f"no {hits_key}/{n_key}. Re-measure rather than hand-edit this record."
                )
                continue
            # Would the exact test have tripped on this pair? The baseline's own n
            # is not recorded in `lowered_from`, so the entry's n stands in for it: `reps`
            # fixes n for a whole corpus, and the point here is to catch an invented record
            # rather than to re-adjudicate a real measurement.
            alpha = alpha_single(len(scores["skills"]))
            if not trips(hits, total, round(old * total), total, alpha):
                failures.append(
                    f"{name}: lowered_from[{metric}] claims a drop from {old} to {now} that "
                    f"the ratchet would never have demanded --accept for, so this record "
                    f"was hand-written."
                )
    return failures


def cwd_mismatches(scores: dict, cases: dict | None = None) -> list[str]:
    """Entries measured somewhere other than where the runner measures today.

    A session is a real agent in a real directory and many happy prompts presume a
    project, so the cwd decides whether some skills can fire at all. Two scores taken
    in different directories are not comparable, and comparing them anyway is how an
    environment change gets read as a description regression.

    The expected label is now PER SKILL, computed from that skill's own fixtures rather
    than from one global default. A fixed default would flag the four
    fixture-backed skills forever — they are supposed to record a project, not an empty
    directory — and a warning that is always on stops being read. With `cases` in hand the
    question becomes the one worth asking: was this score measured in the
    environment this skill is measured in TODAY.

    Reported as a warning, not a failure, for the same reason an unmeasured skill is:
    a score from another directory is still a real measurement, but not one this run
    may ratchet against.
    """
    problems: list[str] = []
    for name, entry in sorted(scores.get("skills", {}).items()):
        spec = (cases or {}).get(name)
        if spec is None:
            default = DEFAULT_CWD_LABEL
        else:
            fixtures = [
                case.fixture
                for arm in ("happy", "negative")
                for case in case_corpus.arm_cases(spec, arm)
            ]
            default = session.environment_label(fixtures)
        recorded = entry.get("cwd")
        if recorded == default:
            continue
        if recorded is None:
            problems.append(
                f"{name}: baseline records no `cwd`, so the environment it was measured "
                f"in is unknown and cannot be compared with the current default {default!r}"
            )
        else:
            problems.append(
                f"{name}: measured in cwd {recorded!r}, but this runner now measures in "
                f"{default!r} -- re-measure before reading a difference as a regression"
            )
    return problems


# ---------------------------------------------------------------- corpus integrity
