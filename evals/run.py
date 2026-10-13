"""Skill-invocation eval runner — measures whether a skill fires.

`tests/skill_docs/` reads the skill files; this module drives real `claude -p`
sessions and records four ratios per skill in `evals/scores.json`:

* `invoke_rate`  — happy prompts where the right skill fired.        (gated)
* `false_fire`   — negative prompts where it fired anyway.           (gated)
* `truncated`    — of the happy prompts that did NOT fire, the share cut short — out of
                   turns, or killed at `SESSION_TIMEOUT_S` — rather than ended by an
                   agent that was done.
* `truncated_quiet` — the same, on the negative arm.
* `restricted`   — happy prompts that fire when every other tool is taken away.

`truncated` is the honesty check on the other two. A sample that was cut short — out of
turns, or killed at `SESSION_TIMEOUT_S` — is genuinely ambiguous either way: the skill
might have fired one turn, or one second, later. Folding it silently into `invoke_rate`
means the score moves when `--max-turns` moves (or when load slows turns enough to trip
the kill), i.e. the harness reports a description regression that is a change of
constant.
In the committed baseline playwright-scaffold, which scores 0.16, had 18 of its 21
misses cut off, while doc-sync at 0.32 had 6 of 17 and harness-insight at 1.00 had
none to explain. It is recorded, never gated — and a high value means the score is
UNSEPARATED from the budget, not that the budget explains it: re-measured at six
turns with nothing cut, playwright-scaffold scored the same.

`restricted` is the companion diagnostic: read against `invoke_rate` it separates "the
description does not match these prompts" from "the wording is fine, the agent
prefers to do the work itself". Also recorded, never gated — real sessions have all
their tools, so a gate on this would block on a situation that never occurs.

Two conditions are pinned rather than inherited, because both move the score more than
the descriptions do: the model (`--model`, verified to be inherited from the calling
session otherwise) and the turn budget (`--max-turns`). Both are written beside every
score, alongside the `cwd`, so a later measurement can tell "the skill got worse" from
"this was measured somewhere else".

**What `invoke_rate` is a fact about.** Not a description in a vacuum: the plugin's own
SessionStart hook fires in every measured session (`claude -p` is a startup), injecting
`rules/risk-tiers.md`, whose Principle routes any change request to `/vdev` first.
The measured system is therefore the description PLUS that injected rule, which is what a
consumer runs and so what this harness deliberately measures. Two consequences ride on
it: `description_sha` freshness is necessary but not sufficient — the description can be
current while the score it certifies was partly produced by the hook — and a happy miss
that lands on `vdev` has a mechanism rather than a mystery (`lost_to` measures it). The
corpus-wide caveat and its per-skill working-out live in `evals/cases.yaml`.

The gate that reads the scores (`tests/eval_harness/`) calls no model at all, so
nothing here may run at import or collection time — measurement happens under
`main()` only.

Usage::

    uv run python -m evals.run --dry-run          # print the plan, start nothing
    uv run python -m evals.run                    # incremental (sha changed only)
    uv run python -m evals.run --all              # every skill in cases.yaml
    uv run python -m evals.run --skill vdev       # one skill
    uv run python -m evals.run --max-turns 6      # widen the per-session turn budget
    uv run python -m evals.run --skill vdev --accept --reason "..."
    uv run python -m evals.run --skill vdev --probe --reps 15   # calibrate, write nothing

A measurement that falls significantly below the baseline — an exact one-sided binomial
test, not a fixed width — is re-measured once before it counts as a drop.
See `ratchet_trips` and `measure()`.

Exit codes: 0 ok · 1 config/stream error · 2 usage · 3 rate-limit abort ·
4 unaccepted CONFIRMED drop · 5 session could not be scored
(auth/API failure).

A session that could not be scored as-is — killed at the timeout, failed, never reached
`init`, or missing its skill — leaves a summary, its transcript and its stderr under
`evals/.runs/<UTC>-<pid>/` (`evals/runner/diagnose.py`); the error or console line names the
file. This module keeps the plan and the CLI; the measurement lives in `evals/runner/`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from evals.runner import baseline, case_corpus, config, invocation, ratchet, session


def _drop_detail(worse: dict[str, float], entry: dict) -> str:
    return ", ".join(f"{metric} {old} -> {entry[metric]}" for metric, old in sorted(worse.items()))


def _score_line(entry: dict) -> str:
    """The one-line summary of a measured skill, shared by the recording and probe paths.

    Shared so the two cannot drift: a probe that reported a different set of numbers from
    the run it is calibrating would be answering a question about something else.
    """
    return (
        f"invoke_rate={entry['invoke_rate']} "
        f"false_fire={entry['false_fire']} "
        f"truncated={entry['truncated']}/{entry['truncated_quiet']} "
        f"restricted={entry['restricted']}"
    )


def select_skills(args: argparse.Namespace, cases: dict[str, dict], scores: dict) -> list[str]:
    """Incremental by default: only skills whose measurement has gone stale.

    Re-measuring everything costs hours, and a design that demands that is a design
    people stop running — at which point the freshness gate blocks all merges.
    """
    if args.skill:
        if args.skill not in cases:
            raise config.EvalError(f"--skill {args.skill}: not in {config.CASES_PATH.name}")
        return [args.skill]
    if args.all:
        return list(cases)
    return [
        name
        for name, spec in cases.items()
        if not baseline.measurement_is_current(scores["skills"].get(name, {}), name, spec)
    ]


@dataclass
class SkillPlan:
    """What one selected skill will cost, before anything runs."""

    name: str
    happy: int
    negative: int
    sessions: int
    # This skill's EFFECTIVE sample size, resolved once here so the printed plan and the
    # session count cannot tell the operator two different stories.
    reps: int


@dataclass
class RunPlan:
    """The whole run, priced. Built without touching the CLI or the network."""

    reason: str
    # The corpus DEFAULT. Each entry above carries what that skill is measured at,
    # and `format_plan` prints the per-skill value wherever the two differ — a header number
    # alone would misdescribe exactly the skills someone chose to sample differently.
    reps: int
    max_turns: int
    skills: list[SkillPlan]

    @property
    def total_sessions(self) -> int:
        return sum(entry.sessions for entry in self.skills)

    @property
    def hours(self) -> float:
        return self.total_sessions * config.wall_clock_per_session(self.max_turns) / 3600


def selection_reason(args: argparse.Namespace, selected: list[str]) -> str:
    """Why these skills and not others — the half of the plan a session count cannot say."""
    if args.skill:
        return f"explicit --skill {args.skill}"
    if args.all:
        return f"--all: every skill in {config.CASES_PATH.name}"
    if not selected:
        return (
            f"incremental: every description_sha and corpus_sha matches {config.SCORES_PATH.name}"
        )
    return f"incremental: description_sha or corpus_sha changed vs {config.SCORES_PATH.name}"


def build_plan(
    args: argparse.Namespace, cases: dict[str, dict], reps: int, selected: list[str]
) -> RunPlan:
    entries: list[SkillPlan] = []
    for name in selected:
        happy = len(cases[name].get("happy") or [])
        negative = len(cases[name].get("negative") or [])
        skill_reps = case_corpus.effective_reps(cases[name], reps)
        entries.append(
            SkillPlan(
                name=name,
                happy=happy,
                negative=negative,
                # `+ happy`: the restricted diagnostic re-runs the happy cases once each.
                # It is deliberately NOT multiplied by reps — see `measure_skill`, which
                # runs that arm at reps=1 because it is a direction to look in, not a
                # number anything compares against.
                sessions=(happy + negative) * skill_reps + happy,
                reps=skill_reps,
            )
        )
    return RunPlan(
        reason=selection_reason(args, selected),
        reps=reps,
        max_turns=args.max_turns,
        skills=entries,
    )


def format_plan(plan: RunPlan) -> list[str]:
    """Render the plan as ASCII lines.

    ASCII only, deliberately: this is printed before a run that may be the operator's
    last chance to hit Ctrl-C, and a UnicodeEncodeError on a cp949 console (CLAUDE.md
    Invariant #2) would replace the warning with a traceback.
    """
    width = max((len(entry.name) for entry in plan.skills), default=1)
    overrides = sum(entry.reps != plan.reps for entry in plan.skills)
    lines = [
        f"plan: {len(plan.skills)} skill(s), reps={plan.reps}"
        + (f" (+{overrides} with their own)" if overrides else "")
        + f", max-turns={plan.max_turns} [{plan.reason}]"
    ]
    for entry in plan.skills:
        # The per-skill sample size is printed only where it DIFFERS from the default. Every
        # line carrying `reps N` would bury the exception in the rule, and this block exists
        # to be read in the seconds before an operator decides whether to Ctrl-C a run that
        # bills for hours — the number worth their attention is the one they did not expect.
        own = f"  reps {entry.reps}" if entry.reps != plan.reps else ""
        lines.append(
            f"  {entry.name:<{width}}  happy {entry.happy}  neg {entry.negative}{own}"
            f"  -> {entry.sessions} session(s)"
        )
    lines.append(f"  TOTAL {plan.total_sessions} session(s)")
    lines.append(
        f"  estimated wall-clock ~{plan.hours * 60:.0f}min "
        f"at {config.CONCURRENCY} concurrent, ~{config.SESSION_WALL_CLOCK_S}s/session"
    )
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals.run",
        description="Measure whether vway-kit skills actually fire.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan (skills, session counts, wall-clock) and exit without measuring",
    )
    parser.add_argument("--all", action="store_true", help="measure every skill in cases.yaml")
    parser.add_argument("--skill", help="measure one skill (cases.yaml key)")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=config.DEFAULT_MAX_TURNS,
        help=(
            f"per-session turn budget (default: {config.DEFAULT_MAX_TURNS}). Raise it when "
            "`truncated` is high AND the cut is the turn cap rather than a session "
            "killed at the timeout -- only the former is a measurement of this budget"
        ),
    )
    parser.add_argument(
        "--model",
        default=config.MODEL,
        help=(
            f"model to measure against (default: {config.MODEL}). Pinned rather than inherited: "
            "a `claude -p` child otherwise adopts the calling session's model, and the "
            "model moves the score more than anything else this harness measures"
        ),
    )
    parser.add_argument(
        "--accept", action="store_true", help="record a confirmed drop (requires --reason)"
    )
    parser.add_argument("--reason", help="why the drop is acceptable; stored as lowered_reason")
    parser.add_argument(
        "--probe",
        action="store_true",
        help=(
            "measure and report, write nothing. For calibration runs whose numbers answer "
            "a question rather than becoming the baseline"
        ),
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=None,
        help=(
            "override the sample size for THIS run only. REQUIRES --probe. The exact test "
            "is fine with a different n (it compares k/n against k/n), but WRITING at one "
            "is not: the run would replace a skill's real entry with probe data whose "
            "recorded reps no longer matches what the corpus declares for it. To change a "
            "standing sample size, declare it in cases.yaml -- `reps:` under the skill for "
            "one of them, or the top-level `reps:` for the corpus default"
        ),
    )
    parser.add_argument(
        "--cwd",
        help=(
            "working directory for the measured sessions (default: a per-session temp dir "
            "holding the case's fixture). Naming one SUPPRESSES fixtures -- the operator "
            "picked the environment, so the runner does not build over it"
        ),
    )
    return parser


def measure(args: argparse.Namespace) -> int:
    """Measure the selected skills. Raises `EvalError`; `main` renders the exit code."""
    reps, cases = case_corpus.load_cases()
    # The corpus declares the sample size; `--reps` overrides it for a probe. Validated in
    # `main` rather than here so a bad value is an argparse usage error (exit 2) instead of
    # a config error (exit 1) -- the fault is in the command, not in cases.yaml.
    if args.reps is not None:
        reps = args.reps
        # ...and it overrides the PER-SKILL declarations too, which is why they are stripped
        # rather than left for `effective_reps` to prefer. Without this a file value beats the
        # command line: `--skill X --probe --reps 15` against a skill declaring `reps: 3`
        # measured at 3 while the plan header announced 15, and the flag's own help promises
        # "the sample size for THIS run only". An operator who names a number and silently
        # gets another has no way to notice -- the run completes and the figure is wrong.
        cases = {
            name: {key: value for key, value in spec.items() if key != "reps"}
            for name, spec in cases.items()
        }
    scores = baseline.load_scores()
    selected = select_skills(args, cases, scores)
    plan = build_plan(args, cases, reps, selected)

    # Before `_claude_binary()`, on purpose: --dry-run must answer "what would this
    # cost?" on any host, including one with no CLI installed.
    if args.dry_run:
        for line in format_plan(plan):
            config._log(line)
        config._log("--dry-run: no session was started, nothing was written")
        return 0

    if not selected:
        config._log("nothing to measure — every description_sha in scores.json is current")
        return 0
    binary = session._claude_binary()

    unaccepted: list[str] = []
    # `ignore_cleanup_errors`: measured on Windows after a real run -- the CLI child
    # still holds a handle on the session cwd when the context manager exits, and the
    # resulting PermissionError propagated as a traceback AFTER every score had been
    # written. A teardown failure must not be able to make a completed measurement look
    # like a crashed one; the OS reclaims the temp directory either way.
    with tempfile.TemporaryDirectory(prefix="vway-eval-", ignore_cleanup_errors=True) as work:
        # Sessions run outside the repo by default. A measured session is a real agent
        # with real tools; pointing it at this working tree would let a measurement edit
        # the code under measurement. `--plugin-dir` loads the plugin regardless of cwd.
        explicit = Path(args.cwd).resolve() if args.cwd else None

        # The same summary --dry-run prints, emitted BEFORE the first session. The
        # bare command starts a run that bills for hours; the operator gets to read the
        # bill while it is still cheap to abort, not discover it afterwards.
        for line in format_plan(plan):
            config._log(line)

        # Entered here rather than around the whole function so that --dry-run and an
        # empty selection never need credentials (isolation exits when they are missing, and a
        # cost estimate must work on any host).
        with session.isolated_config_dir() as config_dir:
            workspace = session.Workspace(root=Path(work), config_dir=config_dir, explicit=explicit)
            unaccepted += _measure_selected(
                args,
                cases=cases,
                scores=scores,
                selected=selected,
                reps=reps,
                workspace=workspace,
                binary=binary,
            )

    if unaccepted:
        config._log(f"finished with unrecorded confirmed drops: {', '.join(unaccepted)}")
        return 4
    return 0


def _measure_selected(
    args: argparse.Namespace,
    *,
    cases: dict[str, dict],
    scores: dict,
    selected: list[str],
    reps: int,
    workspace: session.Workspace,
    binary: str,
) -> list[str]:
    """The per-skill loop. Split out of `measure` so the rate-limit handler below can see
    which skills are still outstanding — the recovery message needs the remainder, and that
    is only knowable inside the loop."""
    unaccepted: list[str] = []
    position = 0

    def measure_one(name: str) -> dict:
        """One skill, with the rate-limit recovery attached.

        Wrapped rather than inlined because the CONFIRMATION re-measure calls this too, and
        the window is at least as likely to close during the second reading as the first —
        it is one more skill's worth of sessions, spent after hours of running.
        """
        try:
            return invocation.measure_skill(
                name,
                cases[name],
                # `reps` here is the corpus DEFAULT; the skill may declare its own. Resolved
                # at the call rather than once for the loop because the loop spans skills
                # with different declarations, and a single value hoisted out of it would
                # measure one skill at another's sample size.
                reps=case_corpus.effective_reps(cases[name], reps),
                workspace=workspace,
                binary=binary,
                max_turns=args.max_turns,
                model=args.model,
            )
        except config.RateLimitAbort:
            # "Re-run without --all" was the advice here and it is wrong for an interrupted
            # full run: every remaining skill's entry still carries a matching
            # description_sha, so the incremental default skips them all and reports every
            # score current. Name the remainder as commands the operator can paste.
            config._log(f"[{name}] rate limit reached before this skill was recorded.")
            config._log(
                f"{position}/{len(selected)} skill(s) measured and saved. When the window "
                f"resets, finish the rest one at a time:"
            )
            for remaining in selected[position:]:
                config._log(f"  uv run python -m evals.run --skill {remaining}")
            raise

    for position, name in enumerate(selected):
        config._log(f"[{name}] start")
        previous = scores["skills"].get(name)
        entry = measure_one(name)

        if args.probe:
            # Report and stop. A probe answers a question ("is the turn budget enough at
            # this concurrency?") and its numbers are not a baseline, so it writes nothing.
            #
            # The ratchet is skipped too, not merely the write. A suspected drop would
            # otherwise spend ~50 further sessions confirming a fall against a baseline
            # this run has already decided not to record — cost with no possible outcome.
            config._log(f"[{name}] PROBE {_score_line(entry)} -- nothing written")
            continue

        changed = ratchet.incomparable_conditions(entry, previous) if previous else {}
        if changed:
            # Recorded and skipped rather than silently compared: the new number is
            # valid on its own, it has no baseline to fall from. Suppressing the
            # ratchet here is what stops a budget change from reading as a
            # description regression.
            detail = ", ".join(
                f"{key} {old!r} -> {now!r}" for key, (old, now) in sorted(changed.items())
            )
            config._log(
                f"[{name}] conditions changed since the baseline ({detail}) -- the "
                "ratchet is skipped for this skill because the two measurements are "
                "not comparable. The new value becomes the baseline."
            )
        worse = {} if changed else ratchet.ratchet_violations(entry, previous, n_skills=len(cases))

        if worse and args.accept:
            # The operator has already decided this drop is acceptable, so a
            # confirmation would only spend sessions re-learning something that
            # changes no outcome.
            config._log(
                f"[{name}] --accept: recording {_drop_detail(worse, entry)} without a "
                "confirmation re-measure"
            )
        elif worse:
            # Confirmation re-measure. `alpha_single` is deliberately loose per run (a few
            # percent at the corpus sizes here) because a FAIL needs two trips; the square root
            # only pays for itself if this second measurement happens.
            cost = ratchet.confirmation_cost(cases[name], reps)
            config._log(
                f"[{name}] SUSPECTED drop ({_drop_detail(worse, entry)}) -- confirming "
                f"with a second measurement of this skill only: {cost} more session(s), "
                f"~{cost * config.SESSION_WALL_CLOCK_S / 3600:.1f}h. A single measurement trips "
                "this test by chance often enough that one drop is not yet evidence; "
                "two consecutive trips are what the family-wise budget is built on."
            )
            second = measure_one(name)
            worse_again = ratchet.ratchet_violations(second, previous, n_skills=len(cases))
            merged = ratchet.merge_confirmation(entry, second)
            pair = ", ".join(
                f"{metric} {one} then {two}"
                for metric, (one, two) in sorted(merged["confirmation"].items())
            )
            # Confirmed = fell in BOTH runs. A metric that recovered leaves the
            # violation set; the recorded value is the second reading either way
            # (merge_confirmation explains why that needs no tie-break rule).
            worse = {metric: old for metric, old in worse.items() if metric in worse_again}
            entry = merged
            if worse:
                config._log(f"[{name}] CONFIRMED drop ({pair}) -- both measurements fell")
            else:
                config._log(
                    f"[{name}] NOT confirmed ({pair}) -- the second measurement "
                    "recovered, so the first reading was noise; recording the second "
                    "(necessarily the higher) value"
                )

        if worse and not args.accept:
            # The measured drop is NOT written: `lowered_from` has to record the
            # pre-drop baseline, and overwriting it here would destroy the only
            # number worth recording.
            detail = _drop_detail(worse, entry)
            config._log(
                f"[{name}] CONFIRMED DROP NOT RECORDED ({detail}). scores.json keeps the "
                f'baseline; re-run with --skill {name} --accept --reason "..." to '
                "record it, or fix the description and measure again."
            )
            unaccepted.append(name)
            continue
        if worse:
            entry["lowered_from"] = worse
            entry["lowered_reason"] = args.reason
        scores["skills"][name] = entry
        # Per-skill write — the next skill may hit the rate-limit wall. The file carries
        # no run-level provenance, so this rewrite touches only the entry measured; the
        # others round-trip byte-identical.
        baseline.write_scores(scores)
        config._log(f"[{name}] {_score_line(entry)} -> {config.SCORES_PATH.name}")
        if entry.get("aborted_skill_calls"):
            # Surfaced rather than left in the JSON, because what it qualifies is the score
            # printed on the line above. Each one is a `Skill` event this parser declined to
            # read a name from; they are normally aborted calls, but the same shape is what
            # a moved CLI schema would produce, and then these misses are not misses.
            config._log(
                f"[{name}] NOTE: {entry['aborted_skill_calls']} Skill call(s) carried no "
                "readable input.skill and were counted as 'did not fire'. Normal for an "
                "aborted call; read a raw stream before trusting the score if it is large."
            )
        if entry.get("lost_to"):
            # Printed rather than left for whoever opens the JSON: it is the one line that
            # turns "this description is losing" into "it is losing to THIS sibling", and
            # the two have different repairs.
            losses = ", ".join(f"{winner} x{count}" for winner, count in entry["lost_to"].items())
            config._log(f"[{name}] happy misses reached for {losses} instead")
        # Warned per arm, because the two say different things. A high `truncated`
        # means `invoke_rate` is pessimistic; a high `truncated_quiet` means
        # `false_fire` is OPTIMISTIC -- and that one is the live gate.
        for metric, cut, arm_name in (
            ("invoke_rate", entry["truncated"], "happy"),
            ("false_fire", entry["truncated_quiet"], "negative"),
        ):
            if not isinstance(cut, int | float) or cut <= config.TRUNCATED_WARN:
                continue
            # States what was seen, not what caused it. An earlier wording said the
            # score "is substantially a measurement of --max-turns" — asserting the
            # explanation with the same confidence as the observation. Measurement
            # refuted it: playwright-scaffold warned at 0.86 here, and re-measured at
            # six turns where nothing was cut at all it scored 0.07 against 0.16 —
            # the same number within sampling error. Cutting makes a score UNVERIFIED
            # against the budget; it does not make the budget the reason for it.
            config._log(
                f"[{name}] WARNING: {cut:.0%} of the {arm_name} samples that did not "
                f"fire were cut short (out of turns, or killed at {config.SESSION_TIMEOUT_S}s) "
                f"rather than finishing, so {metric}={entry[metric]} has not been "
                f"separated from --max-turns {args.max_turns}. A larger-budget "
                "re-measure settles the turn-cap share of it; a session killed at the "
                "timeout needs a faster run, not a bigger one -- the score may well be "
                "unchanged either way."
            )

    return unaccepted


def main(argv: list[str] | None = None) -> int:
    config._force_utf8_io()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.all and args.skill:
        parser.error("--all and --skill are mutually exclusive")
    if args.accept and not args.reason:
        parser.error("--accept requires --reason: an unexplained lowered baseline is not a record")
    if args.accept and not args.skill:
        parser.error("--accept applies to one skill; pass --skill")
    if args.max_turns < 1:
        parser.error("--max-turns must be at least 1")
    if args.reps is not None and args.reps < 1:
        # Caught at the flag rather than downstream: `--reps 0` measures nothing and would
        # write an entry with n=0, which every ratio and every exact test then divides by.
        parser.error("--reps must be at least 1")
    if args.reps is not None and not args.probe:
        # The flag's own help advertises `--skill playwright-scaffold --reps 15`, and before
        # this guard that command REPLACED the skill's committed entry with probe data — so
        # following the documentation lost the baseline and turned the suite red. A probe is
        # a question, not a baseline; make the operator say which one they are running.
        #
        # The gate now catches the same thing from the other side: an entry written at 15
        # while the corpus declares 5 fails the per-entry `reps` check. Both stay. This one
        # refuses the command; that one refuses the artifact, and only the second survives a
        # baseline edited by hand.
        parser.error(
            "--reps requires --probe: a run at a sample size the corpus does not declare "
            "would overwrite the baseline entry with probe data. To change a standing "
            f"sample size instead, declare it in {config.CASES_PATH.name} -- `reps:` under the "
            "skill, or the top-level `reps:` for the corpus default."
        )

    # Every failure below is reported as a message plus an exit code, never a traceback:
    # whatever was already written per-skill stays valid, and the operator needs to read
    # the reason at the end of a run that may have been going for hours.
    try:
        return measure(args)
    except config.RateLimitAbort as exc:
        config._log(f"ABORT: {exc}")
        config._log(
            f"scores.json holds every skill completed before this point ({config.SCORES_PATH})."
        )
        return 3
    except config.SessionFailure as exc:
        # Its own exit code because the fix is its own thing: re-authenticate (or wait
        # out the API outage) and re-run. Folding it into the generic error code would
        # have the operator hunting a config bug that is not there.
        config._log(f"ABORT: {exc}")
        config._log("the session itself failed -- check `claude` auth, then re-run.")
        config._log(
            f"scores.json holds every skill completed before this point ({config.SCORES_PATH})."
        )
        return 5
    except subprocess.TimeoutExpired:
        config._log(f"ERROR: a session exceeded {config.SESSION_TIMEOUT_S}s and was not scored")
        return 1
    except config.EvalError as exc:
        config._log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
