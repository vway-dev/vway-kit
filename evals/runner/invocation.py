"""The invocation arm: run each case's sessions concurrently and score whether the skill fires
on the prompts it should and stays quiet on the rest.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from evals.runner import baseline, case_corpus, config, diagnose, session


@dataclass
class Outcome:
    """One scored session.

    Truncation is only meaningful together with `fired`: a session that fired and then was
    cut short answered the question this harness asks. Ambiguity is exclusively "ended
    without firing, and ended because it ran out of turns or was killed at
    `SESSION_TIMEOUT_S` rather than because it was done".
    """

    fired: bool
    # Out of turns OR killed at SESSION_TIMEOUT_S (`ParsedSession.cut_short`) — the same
    # "stopped before it was done" for `truncated`.
    hit_turn_cap: bool
    # Which SIBLING skills fired instead, deduplicated. Diagnostic only — nothing gates on
    # it — and the reason it is collected per outcome rather than aggregated on the fly is
    # that `run_arm` restores case order, so a later reader can still say WHICH prompt lost.
    others: tuple[str, ...] = ()
    # Carried up from the stream so the entry can report it (see `parse_stream`). A miss
    # in a session that also aborted a Skill call is a miss this parser is less sure of.
    aborted_skill_calls: int = 0

    @property
    def cut_before_firing(self) -> bool:
        return self.hit_turn_cap and not self.fired


def _report_timeout(exc: subprocess.TimeoutExpired, where: str, prompt: str) -> None:
    """Name the case a session timed out on, and where its record went.

    The run still stops (`main` handles `TimeoutExpired`); what changes is knowing what
    stopped it. A bare "a session exceeded 300s" left two full runs unable to say which
    case hung. The stream itself is kept by `diagnose.record`, whose path `run_session`
    appended to the exception's stderr."""
    err = exc.stderr or ""
    if isinstance(err, bytes):
        err = err.decode("utf-8", errors="replace")
    head = " ".join(prompt.split())[:80]
    kept = next(
        (line.strip() for line in err.splitlines() if line.strip().startswith("record:")), ""
    )
    config._log(
        f"  {where} -> TIMEOUT after {config.SESSION_TIMEOUT_S}s: {head!r}"
        + (f" | {kept}" if kept else "")
    )


def run_arm(
    cases: list[case_corpus.Case],
    *,
    skill_id: str,
    reps: int,
    workspace: session.Workspace,
    binary: str,
    max_turns: int,
    model: str,
    label: str,
    allowed_tools: str | None = None,
    concurrency: int = config.CONCURRENCY,
) -> list[Outcome]:
    """Run every case × rep of one arm concurrently, returning outcomes in case order.

    Order is restored before returning even though the sessions finish out of order:
    the caller reports per-case results, and a shuffled list would attribute one case's
    behaviour to another while every ratio still came out right — a wrong diagnosis
    that no aggregate check could catch. `pool.map` supplies that for free; the
    submit/`as_completed` form below has to reassemble it by hand (see the comment there),
    and `test_an_arm_returns_its_outcomes_in_case_order` is what holds it.
    """
    work = [(index, rep, case) for index, case in enumerate(cases, 1) for rep in range(1, reps + 1)]

    def one(item: tuple[int, int, case_corpus.Case]) -> Outcome:
        index, rep, case = item
        with session.session_cwd(workspace, case.fixture) as cwd:
            try:
                parsed = session.run_session(
                    case.prompt,
                    plugin_dir=config.REPO_ROOT,
                    cwd=cwd,
                    config_dir=workspace.config_dir,
                    binary=binary,
                    max_turns=max_turns,
                    model=model,
                    skill_id=skill_id,
                    allowed_tools=allowed_tools,
                    on_unscored=lambda raw, seen, reason: diagnose.record(
                        raw,
                        seen,
                        skill=skill_id.removeprefix(config.SKILL_PREFIX),
                        arm=label,
                        index=index,
                        rep=rep,
                        prompt=case.prompt,
                        fixture=case.fixture,
                        reason=reason,
                    ),
                )
            except subprocess.TimeoutExpired as exc:
                _report_timeout(exc, f"{label}[{index}] rep {rep}/{reps}", case.prompt)
                raise
        outcome = Outcome(
            fired=parsed.fired(skill_id),
            hit_turn_cap=parsed.cut_short(),
            # Siblings only, and stripped of the plugin prefix so the tally reads as skill
            # names. `dict.fromkeys` rather than `set`: a session that reached for the same
            # neighbour twice lost ONE prompt to it, not two, and order is kept stable.
            others=tuple(
                name[len(config.SKILL_PREFIX) :]
                for name in dict.fromkeys(parsed.fired_skills)
                if name.startswith(config.SKILL_PREFIX) and name != skill_id
            ),
            aborted_skill_calls=parsed.aborted_skill_calls,
        )
        mark = "FIRED" if outcome.fired else ("cut" if outcome.cut_before_firing else "-")
        if parsed.timed_out:
            # Scored by the rule every cut session meets; the record says where it hung.
            mark += (
                f" (killed at {config.SESSION_TIMEOUT_S}s after {parsed.tool_calls} tool calls,"
                f" last {diagnose.last_name(parsed)}"
                + (f" — {parsed.record}" if parsed.record else "")
                + ")"
            )
        config._log(f"  {label}[{index}] rep {rep}/{reps} -> {mark}")
        return outcome

    # This was `list(pool.map(one, work))` inside a `with`, on the reasoning that `map`
    # "re-raises the first exception — so a rate limit stops the run". Ported away from that
    # shape after the sister repo (harness-tier `evals/run.py`), which measured what
    # it costs: hitting the cap on session 1 of 35 still burned the other 34.
    #
    # `map` is better than that reputation and the difference is worth writing down, because
    # the obvious version of this argument is wrong. Its result iterator cancels the
    # not-yet-started futures in a `finally` when the exception propagates out of `list()`,
    # so the tail of the plan does NOT run — measured here, not assumed.
    #
    # What it cannot do is raise EARLY. The iterator yields in SUBMISSION order, so an abort
    # on session 5 is withheld until sessions 0-4 have finished — and every one of those
    # completions frees a worker that starts a fresh session against the shut window. At
    # concurrency 8 that is the 8 already in flight plus as many again started while
    # the caller waits, all of them refused, before anyone is told. The burn is smaller than
    # "the whole queue" and it is real.
    #
    # The pool is deliberately NOT a context manager, for the second half of the same
    # argument. `with` exits through `shutdown(wait=True)`, which on a rate-limit stop
    # blocks for up to SESSION_TIMEOUT_S on the <= `concurrency` sessions already in flight.
    # Those are already spent and their results are discarded, so waiting on them only
    # delays the per-skill `write_scores` in `_measure_selected` — which is the one thing a
    # rate-limit stop exists to protect. `cancel_futures` drops everything not yet
    # started; the interpreter still joins the surviving threads at exit, so nothing is
    # orphaned.
    #
    # What the change costs is the case-order guarantee in the docstring, and it has to be
    # paid back by hand: `as_completed` yields in COMPLETION order, so the position each
    # item was submitted at is carried alongside its future. A dict keyed by that position
    # rather than a pre-sized list of `None`s, so a slot that was somehow never filled is a
    # KeyError here instead of a `None` reaching `Outcome`-typed callers.
    outcomes: dict[int, Outcome] = {}
    pool = ThreadPoolExecutor(max_workers=max(concurrency, 1))
    try:
        futures = {pool.submit(one, item): position for position, item in enumerate(work)}
        for future in as_completed(futures):
            # `.result()` re-raises HERE, as each session lands — the whole point of the
            # change. A rate limit, an auth failure or a malformed stream stops the arm on
            # the session that saw it rather than at the input position `map` made us wait
            # for.
            outcomes[futures[future]] = future.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return [outcomes[position] for position in range(len(work))]


def cut_share_of_misses(results: list[Outcome]) -> float | None:
    """Of the sessions that did not fire, the share that was cut short — out of turns, or
    killed at `SESSION_TIMEOUT_S` (`Outcome.hit_turn_cap`, fed by `ParsedSession.cut_short`).

    Conditioned on the misses rather than on every session, and that is the whole design.
    An unconditional cut rate is bounded by `1 - invoke_rate`, so it slides downward on
    its own whenever a skill fires more — reporting one number twice under two names, the
    fault that retired `ablation_delta`. Conditioning divides the misses into "ran out of
    road" and "had the room and declined", which `invoke_rate` cannot say either way.

    `None` when nothing missed: there is no low score to explain, and 0/0 is not 0.0.
    """
    misses = [o for o in results if not o.fired]
    if not misses:
        return None
    return round(sum(o.cut_before_firing for o in misses) / len(misses), 4)


def lost_to(results: list[Outcome]) -> dict[str, int]:
    """Of the happy prompts that missed, which SIBLING skill took each one.

    `invoke_rate` says a description is losing; this says what it is losing to, and those
    are different repairs: "reword the description" versus "the boundary with this sibling
    is in the wrong place". Diagnostic only — no gate reads it, so a shift here can never
    pass or fail anything.

    **A miss landing on `vdev` has a known mechanism, and this is the instrument that
    quantifies it.** Every measured session receives the plugin's own SessionStart hook
    (`hooks/claude/hooks.json` → `inject-risk-tiers.sh`), whose injected rule opens on an imperative
    naming one skill: "Enter `/vdev` (via the Skill tool) as your FIRST action on any code
    change, feature, fix, or development request". Any happy prompt that asks for
    a CHANGE is therefore claimed by that instruction before its own description is
    consulted, so `{"vdev": n}` beside a low `invoke_rate` is not necessarily a boundary
    defect between two descriptions — it can be the injected rule doing exactly what it
    was written to do. The hook is kept because consumers run with it (see the corpus-wide
    caveat at the top of `cases.yaml`), which makes reading this tally the only way to tell
    interception from a genuine sibling overlap.

    Bounded by what it can see, and the bound matters when reading a result. Only
    `vway-kit:*` names are counted, so a prompt lost to another plugin, to a built-in
    skill, or to the agent doing the work with Bash reads as an EMPTY dict rather
    than as a named winner. An empty `lost_to` beside a low `invoke_rate` therefore means
    "no sibling took it", not "nothing took it" — and under the isolated config dir there
    are still ~30 non-vway-kit skills in the session, so that gap is real rather
    than theoretical. `restricted` is the metric that separates those two readings.
    """
    tally: dict[str, int] = {}
    for outcome in results:
        if outcome.fired:
            continue
        for winner in outcome.others:
            tally[winner] = tally.get(winner, 0) + 1
    return dict(sorted(tally.items()))


def measure_skill(
    name: str,
    spec: dict,
    *,
    reps: int,
    workspace: session.Workspace,
    binary: str,
    max_turns: int,
    model: str,
) -> dict:
    """Run every case of one skill and return its new scores entry."""
    skill_id = f"{config.SKILL_PREFIX}{name}"
    happy = case_corpus.arm_cases(spec, "happy")
    negative = case_corpus.arm_cases(spec, "negative")
    entry: dict[str, Any] = {
        "description_sha": baseline.description_sha(config.SKILLS_DIR / name),
        # The other half of the fingerprint. A score is a claim about a description
        # answering a particular set of prompts in a particular project state; pinning only
        # the description let the prompts move underneath a committed number.
        "corpus_sha": case_corpus.corpus_sha(spec),
        # Not decoration: without these, a later run under different conditions compares
        # against a baseline measured elsewhere and calls the difference a regression.
        # `description_sha` pins WHAT was measured; these pin the conditions it was
        # measured under. The gate warns when either stops matching the current default.
        #
        # The label is derived HERE, from the same resolved cases that choose the
        # directories, rather than passed in beside them — the two would otherwise drift,
        # and a `cwd` that disagrees with where the sessions ran asserts a
        # condition nobody measured under.
        "cwd": session.environment_label(
            [case.fixture for case in happy + negative], workspace.explicit
        ),
        "model": model,
    }

    def arm(
        cases: list[case_corpus.Case],
        label: str,
        *,
        allowed_tools: str | None = None,
        reps: int = reps,
    ) -> list[Outcome]:
        return run_arm(
            cases,
            skill_id=skill_id,
            reps=reps,
            workspace=workspace,
            binary=binary,
            max_turns=max_turns,
            model=model,
            label=label,
            allowed_tools=allowed_tools,
        )

    # A skill with no happy path (harness-authoring: its description says it is never
    # invoked directly) scores `null`, not 0.0 — "no happy path exists" is a different
    # statement from "it never fired", and the gate skips null. The counts are null
    # for the same reason: 0/0 written as 0 would walk straight into `invoke_hits == 0`,
    # the one surviving data-independent floor.
    #
    # `*_hits`/`*_n` are the integers the gate reads; the ratio beside them is a
    # DERIVED field kept for humans reading a diff. The exact binomial test needs k
    # and n, and a rounded rate cannot supply them — nor can it be trusted once written,
    # because this file is committed and hand-edited (the threat model `lowered_from`
    # already assumes) and because rounding hides both ends: at a reps-raised n a true
    # 0.204 rounds to a passing 0.20, and one hit in a large n rounds to 0.00.
    # Summed across every scored arm rather than reported per arm: it is a parser-health
    # signal, not a property of a prompt set, and one number is what an operator will
    # notice next to the ratios.
    aborted = 0

    if happy:
        results = arm(happy, "happy")
        aborted += sum(o.aborted_skill_calls for o in results)
        entry["invoke_hits"] = sum(o.fired for o in results)
        entry["invoke_n"] = len(results)
        entry["invoke_rate"] = round(entry["invoke_hits"] / entry["invoke_n"], 4)
        entry["truncated"] = cut_share_of_misses(results)
        entry["lost_to"] = lost_to(results)
    else:
        entry["invoke_hits"] = None
        entry["invoke_n"] = None
        entry["invoke_rate"] = None
        entry["truncated"] = None
        entry["lost_to"] = {}

    if negative:
        fires = arm(negative, "neg")
        aborted += sum(o.aborted_skill_calls for o in fires)
        entry["false_hits"] = sum(o.fired for o in fires)
        entry["false_n"] = len(fires)
        # **Do not read a green `false_fire` as "the description is precise."** This is the
        # FOURTH independent reason to distrust it, and the only one that is about the
        # arithmetic of the test rather than about how a session was run — the other three
        # are the 25-sample resolution grid, `truncated_quiet` (a negative sample cut
        # before it could over-fire records as correctly quiet), and hook routing.
        # It survives even when all three of those are clean.
        #
        # Measured on the committed baseline: 3 fires across 225 negative sessions (0.013),
        # every skill sitting at 0.00 or 0.04. The gate fails at `false_hits > 0.20 * n`,
        # so at n=25 a skill has to take 6 of 25 prompts written to keep it out — while the
        # pooled happy rate is 142/200 = 0.71 on prompts written to invite it. At the corpus
        # default the sample is n=15, where the same ceiling asks for 4 of 15 (0.267): a
        # coarser step, and the reason `vdev` — the skill whose `false_fire` the tier router
        # is judged on — declares reps 5 while the rest accept the coarser one. The ceiling
        # therefore asks a description to grab its neighbour's prompts at well under half
        # the rate it takes its own, and near-zero here is largely explained by how rarely
        # anything fires unbidden at all rather than by the boundaries being well drawn.
        #
        # The test's own power says the same thing, computed with `binom_cdf` at n=25:
        #
        #     true rate 0.10 -> passes the ceiling on 96.7% of runs
        #     true rate 0.15 -> passes on 83.9%
        #     true rate 0.20 -> passes on 61.7%
        #
        # A description whose true false-fire rate sits exactly ON the declared ceiling
        # still passes it more often than not. So this metric detects the gross case — a
        # description broad enough to hijack whole neighbourhoods — and nothing finer.
        #
        # The ceiling stays: it costs nothing and it would catch that gross case. What it is
        # NOT is evidence that the descriptions are cleanly separated. The thing that would
        # make it informative is raising `invoke_rate` — a corpus where skills fire readily
        # is one where an over-broad description has room to show itself.
        entry["false_fire"] = round(entry["false_hits"] / entry["false_n"], 4)
        # The SAME cut moves the two gated metrics in OPPOSITE directions: a happy sample
        # stopped early drags `invoke_rate` down, while a negative sample stopped before
        # the agent could over-fire makes `false_fire` look GOOD. Tracking truncation on
        # the happy arm alone therefore leaves the one live absolute threshold —
        # `false_fire <= 0.20` — passing on evidence nobody checked.
        #
        # This runner shipped with the opposite reasoning written out in full: that a
        # negative prompt was written for the skill not to fire, so a cut there is the
        # expected outcome. That confuses the outcome being EXPECTED with it being
        # OBSERVED. A session cut at turn three did not stay quiet; it never got to speak.
        entry["truncated_quiet"] = cut_share_of_misses(fires)
    else:
        entry["false_hits"] = None
        entry["false_n"] = None
        entry["false_fire"] = None
        entry["truncated_quiet"] = None

    # A diagnostic axis, not a score: one pass over the happy cases with every tool but
    # `Skill` taken away. Real sessions have all their tools, so gating on this would
    # measure a situation that never happens — but read against `invoke_rate` it says
    # WHICH problem a low score is, and those two problems have opposite fixes:
    #
    #   restricted high, invoke_rate low -> the wording is fine; the agent is choosing
    #                                       to do the work by hand instead
    #   restricted low,  invoke_rate low -> the description itself does not match the
    #                                       prompts
    #
    # One rep, not `reps`: it is a direction to look in, not a number anything compares
    # against, and five times the cost buys resolution nobody spends.
    #
    # Fixtures changed what this arm means, and not for the better. `--allowed-tools Skill`
    # removes Read and Bash, so it also removes the agent's ability to SEE the project
    # `session_cwd` built — the arm asks "does the prompt match the description on
    # its own words", with the fixture invisible. Expect `restricted <= invoke_rate` on a
    # fixture-backed skill for that reason alone, and do not read the gap as the
    # agent preferring to work by hand.
    #
    # Second caveat, on the number's PRECISION rather than its meaning: reps are not applied
    # here, so n is the happy case count (5) however many reps the scored arms ran. A
    # five-sample rate moves in steps of 0.2 and can only ever be one of six values — the
    # committed baseline is all 0.4, 0.6 and 1.0, exactly as that grid predicts. The
    # `round(..., 4)` below is shared with the scored arms, which need it (a reps-raised n
    # rounds a true 0.204 down to a passing 0.20), and it is three decimals more than this
    # arm can carry. Read `restricted` as a direction, never as a difference: 0.6 against
    # 0.4 is one session.
    if happy:
        blocked = arm(happy, "restricted", allowed_tools="Skill", reps=1)
        entry["restricted"] = round(sum(o.fired for o in blocked) / len(blocked), 4)
    else:
        entry["restricted"] = None

    # Recorded even when zero, because zero is the informative value: it says this skill's
    # ratios rest on streams the parser read whole. An absent key would leave a reader
    # unable to tell "none happened" from "nobody counted".
    entry["aborted_skill_calls"] = aborted
    entry["max_turns"] = max_turns
    # Recorded per skill, not only at file level, because the file-level value cannot be
    # trusted: the run that introduces a mismatch overwrites it (measure one skill at
    # reps=3 and the header says 3 while the entries measured at 5 keep their ratios).
    #
    # It is no longer a COMPARABLE_CONDITION, though — the exact binomial handles differing
    # n directly. What it remains is provenance: `invoke_n` says how many samples there
    # were, and `reps` says how that n was reached, which is what a reader needs to tell a
    # widened corpus from a repeated one.
    entry["reps"] = reps
    # Provenance per skill, and per skill ONLY — ported from the sister repo (harness-tier
    # `evals/run.py`), whose comment names the fault exactly: the default mode is
    # INCREMENTAL, so the normal run measures one skill and rewrites the whole file. Values
    # that lived in the file header therefore claimed this run's date and sample size for the
    # skills it never touched, and the reader they misled is the one who most needs
    # them — someone asking "how old is this number?" before trusting a score.
    #
    # `reps` was once written in BOTH places, on the argument that its header value was the
    # corpus's declared size and a gate asserted the two agreed. That argument held only
    # while one number described every entry; a per-skill `reps:` turns the header into a
    # default the assertion no longer covers. Rather than refuse the feature to preserve the
    # gate, the gate moved: it now compares each entry here against `effective_reps` for that
    # skill, which is what makes THIS line the checkable one.
    entry["measured_at"] = datetime.now(UTC).strftime("%Y-%m-%d")
    return entry
