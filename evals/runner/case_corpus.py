"""The prompts each skill is measured with: `evals/cases.yaml`, its resolved cases, reps and
the fingerprint of the questions asked (`corpus_sha`).
"""

from __future__ import annotations

import hashlib
import json
from typing import NamedTuple

import yaml

from evals.runner import config
from scripts import skill_sandbox as sandbox


class Case(NamedTuple):
    """One prompt and the project state it is measured in."""

    prompt: str
    fixture: str | None


def arm_cases(spec: dict, arm: str) -> list[Case]:
    """One arm's cases with each fixture resolved: per-case override, else skill default.

    `case["fixture"]` present-and-null is an OVERRIDE ("run this one in an empty directory")
    and must beat the skill-level default, so the key's presence decides rather than its
    value — the same distinction `expect_invoke: null` already relies on. Reading a
    null override as "absent" would silently hand a contradicting fixture back to the case
    that was written to escape it.
    """
    default = spec.get("fixture")
    resolved: list[Case] = []
    for case in spec.get(arm) or []:
        fixture = case["fixture"] if "fixture" in case else default
        resolved.append(Case(case["prompt"], fixture))
    return resolved


def corpus_sha(spec: dict) -> str:
    """SHA-256 of the prompts and fixture assignment one skill is measured with.

    `description_sha` pins the text under measurement; this pins the QUESTIONS it is asked.
    `invoke_rate`'s inputs are (description, prompts, fixture) and only the first of the
    three was ever fingerprinted, so a corpus edit was invisible to everything downstream:
    rewriting all five of a skill's happy prompts left the freshness gate silent AND the
    incremental selection empty, and the runner reported "every description_sha is current
    — nothing to measure" over committed counts that now described prompts which no longer
    existed. That is not a hypothetical failure; this branch was in exactly that state.

    Hashed from the RESOLVED cases (`arm_cases`), so a per-case `fixture:` override moves
    the hash exactly as rewriting the prompt does. The fixture decides what a prompt means
    — the same sentence measured in a web project and in an empty directory is two
    different questions — so a fingerprint blind to it would miss half of what it exists to
    catch.

    NOT hashed: `kind` and `why`. Those annotate a case for a reviewer and cannot change
    what a session does, and hashing them would demand a ~11-minute re-measurement for
    editing a comment — the same argument that keeps the skill BODY out of
    `description_sha`.
    """
    payload = [
        [arm, case.prompt, case.fixture]
        for arm in ("happy", "negative")
        for case in arm_cases(spec, arm)
    ]
    # `sort_keys` is irrelevant to a list payload and `ensure_ascii=False` keeps the Korean
    # prompts as themselves; what matters is that the encoding is stable across runs, so
    # the separators are pinned rather than left to a future json default.
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _positive_reps(value: object, where: str) -> int:
    """Shared by the corpus default and the per-skill override so the two cannot drift into
    accepting different things.

    `bool` is excluded explicitly because `isinstance(True, int)` is True in Python: without
    the guard `reps: true` validates, reaches `range(1, 2)`, and measures every case exactly
    once while the file reads as a deliberate declaration. That is the shape of fault this
    whole module is built to refuse -- a number that is wrong rather than a run that stops.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise config.EvalError(f"{where}: `reps` must be a positive integer, not {value!r}")
    return value


def effective_reps(spec: dict, default: int) -> int:
    """The sample size THIS skill is measured at: its own `reps:` or the corpus default.

    Exists as one function because the runner and the gate must not be able to disagree about
    it. `measure_skill` stamps `entry["reps"]` from this, and
    `test_the_committed_baseline_round_trips` checks each committed entry against this -- if
    the gate re-derived the value with its own copy of the rule, a change to one would leave
    the other green while asserting something no longer true.

    Why a per-skill override is sound: the ratchet is an exact one-sided binomial comparing
    k/n with k/n, valid when `n_new != n_base` (spec 6). Under the fixed-width delta that
    preceded it this would have been a real error, since a single width's defensibility came
    entirely from the standard error at ONE sample size. That is why `reps` had to leave
    `COMPARABLE_CONDITIONS` first -- a different `reps` is now the same experiment run more
    times, not a different experiment.
    """
    declared = spec.get("reps")
    return default if declared is None else declared


def load_cases() -> tuple[int, dict[str, dict]]:
    if not config.CASES_PATH.is_file():
        raise config.EvalError(f"{config.CASES_PATH} not found")
    data = yaml.safe_load(config.CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise config.EvalError(f"{config.CASES_PATH}: top level is not a mapping")
    # The corpus DEFAULT, not a description of every entry: a skill may declare its own
    # below, and `effective_reps` is what resolves the two.
    reps = _positive_reps(data.get("reps"), str(config.CASES_PATH))
    skills = data.get("skills")
    if not isinstance(skills, dict) or not skills:
        raise config.EvalError(f"{config.CASES_PATH}: `skills` must be a non-empty mapping")

    for name, spec in skills.items():
        if not isinstance(spec, dict):
            raise config.EvalError(f"{config.CASES_PATH}: skills.{name} is not a mapping")
        # Validated HERE rather than where it is spent, because it is spent twice before any
        # session starts -- `build_plan` prices the run with it and `format_plan` prints that
        # price. A bad value caught at `range()` would surface after the operator has already
        # approved a session count computed from it.
        if spec.get("reps") is not None:
            _positive_reps(spec["reps"], f"{config.CASES_PATH}: skills.{name}")
        for arm in ("happy", "negative"):
            cases = spec.get(arm) or []
            if not isinstance(cases, list):
                raise config.EvalError(f"{config.CASES_PATH}: skills.{name}.{arm} is not a list")
            for index, case in enumerate(cases):
                if not isinstance(case, dict) or not isinstance(case.get("prompt"), str):
                    raise config.EvalError(
                        f"{config.CASES_PATH}: skills.{name}.{arm}[{index}] has no prompt"
                    )
            # Fail CLOSED on an unknown fixture, which is the opposite of this repo's
            # default for gate scripts and deliberately so (CLAUDE.md Invariant 1 is about
            # gates that must not block a commit forever). A typo here would fall back to
            # an empty directory, the run would still produce a number, and that number is
            # indistinguishable from a real score while measuring the wrong thing.
            for case in arm_cases(spec, arm):
                if case.fixture is not None and case.fixture not in sandbox.BY_NAME:
                    raise config.EvalError(
                        f"{config.CASES_PATH}: skills.{name}.{arm} names fixture "
                        f"{case.fixture!r}, which skill_sandbox does not build. Known "
                        f"scenarios: {sorted(sandbox.BY_NAME)}"
                    )
        if not (config.SKILLS_DIR / name / "SKILL.md").is_file():
            raise config.EvalError(
                f"{config.CASES_PATH}: skills.{name} has no skills/{name}/SKILL.md"
            )
    return reps, skills
