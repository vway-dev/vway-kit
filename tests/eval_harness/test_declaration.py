"""스킬별 선언 — 무엇을 기대하고 왜 그런가.

선언 없는 스킬은 '측정 안 됨' 경고보다 **먼저** 실패함. happy path 가 없는 스킬은
그렇다고 선언해야 하고, 값이 비어 있는 것과는 다름.
"""

from __future__ import annotations

from evals.runner.case_corpus import (
    load_cases,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._checks import (
    Declaration,
    check,
    read_declaration,
)
from tests.eval_harness._stubs import (
    _measurement,
)


def test_every_skill_declares_what_it_expects_and_why():
    """The declaration is what replaced the global floor, so a skill without one is
    ungated -- there is no constant left to fall back on.

    `expect_why` is required beside the number because the number alone cannot be
    reviewed. The claim being made is about how directly this skill's prompts name it, and
    that claim has to be legible to whoever later reads a warning saying the measurement
    fell short of it.
    """
    _, cases = load_cases()
    problems = [
        problem
        for name, spec in sorted(cases.items())
        if isinstance(problem := read_declaration(name, spec), str)
    ]
    assert not problems, "\n".join(problems)


def test_an_undeclared_skill_fails_before_the_unmeasured_warn():
    """Order is the point, not merely that both judgements exist.

    Reading the entry first returns "not measured yet" for a skill that is BOTH unmeasured
    and undeclared -- which is exactly a newly added skill, the case the forcing function
    exists for -- and it would pass as a warning, quietly leaving the replacement for the
    floor switched off for the only skill that needed it.
    """
    verdict = check("newcomer", None, "s" * 64, read_declaration("newcomer", {}), n_skills=9)
    assert verdict.level == "fail", "an undeclared skill must not reach the unmeasured warn"
    assert "expect_invoke" in verdict.message, verdict.message

    # ...and with a declaration in hand the same unmeasured skill IS only a warning, so
    # the ordering above is doing real work rather than failing everything.
    declared = read_declaration("newcomer", {"expect_invoke": 0.7, "expect_why": "direct"})
    assert check("newcomer", None, "s" * 64, declared, n_skills=9).level == "warn"


def test_a_skill_with_no_happy_path_declares_that_rather_than_going_undeclared():
    """The design leaves exactly one decision to the implementation and this is it.

    If `expect_invoke: null` meant "undeclared", then "this skill has no happy
    path" -- a JUDGEMENT -- and "nobody wrote a declaration" -- an OMISSION -- become
    the same value, and the undeclared-FAIL above would keep `harness-authoring`
    permanently red for behaving exactly as designed. That is the failure the design names.

    The choice made here: null is a legal declaration, distinguished from undeclared by
    the KEY's presence rather than its value, and licensed only for a skill registered in
    `NO_HAPPY_PATH` -- the same reviewed registry that already licenses an empty `happy`
    list. So a new skill cannot grant itself the exemption by writing null.
    """
    spec = {"expect_invoke": None, "expect_why": "no happy path exists (spec 3.1)"}
    licensed = read_declaration("harness-authoring", spec)
    assert isinstance(licensed, Declaration) and licensed.expect is None

    assert isinstance(read_declaration("vdev", spec), str), (
        "only a registered no-happy-path skill may declare a null expectation"
    )
    assert isinstance(read_declaration("harness-authoring", {"expect_why": "..."}), str), (
        "the key must still be present -- absent is undeclared, null is a decision"
    )
    assert isinstance(read_declaration("vdev", {"expect_invoke": 0.7}), str), (
        "a number with no stated reason is a value nobody can review"
    )
    assert isinstance(read_declaration("vdev", {"expect_invoke": 1.4, "expect_why": "x"}), str), (
        "an expectation outside (0, 1] is not a rate"
    )


def test_a_measurement_significantly_below_its_declaration_warns():
    """A warn, not a fail. `n=25` cannot support hard-failing an aspiration, and a
    suite that is red by default stops being read -- the same argument that put the
    guessed 0.80 floor to sleep. The declaration gap is information; enforcement is the
    ratchet's job.

    Significance is the same exact binomial the ratchet uses, against a different
    reference: the ratchet measures against yesterday's k/n, this against a human's stated
    intent. So an undershoot `n=25` cannot resolve is NOT a warning -- 18/25 against a
    declared 0.80 is well inside sampling noise, and warning on it would train people to
    tune the declaration down toward the measurement, which is the tautology the declaration exists
    to prevent.
    """
    declared = Declaration(expect=0.80, why="the prompts name it outright")
    short = check("s", _measurement(invoke_hits=10), "s" * 64, declared, n_skills=9)
    assert short.level == "warn" and "below its declared" in short.message, short

    near = check("s", _measurement(invoke_hits=18), "s" * 64, declared, n_skills=9)
    assert near.level == "ok", f"a one-sigma undershoot is not evidence: {near}"


def test_the_gate_reads_the_counts_rather_than_the_rounded_rate():
    """Both surviving thresholds key on integers.

    At a reps-raised `n` a true `false_fire` of 0.204 rounds to a passing 0.20, and a
    single invocation in a large `n` rounds to a 0.00 that is indistinguishable from a
    description which never fires at all. The rounded fields in the entry below say
    "passing" and "zero"; the counts say otherwise, and the counts are what is read.
    """
    declared = Declaration(expect=0.80, why="...")
    over = _measurement(false_hits=51, false_n=250, false_fire=0.20)
    assert check("s", over, "s" * 64, declared, n_skills=9).level == "fail"

    sparse = _measurement(invoke_hits=1, invoke_n=250, invoke_rate=0.0)
    verdict = check("s", sparse, "s" * 64, declared, n_skills=9)
    assert verdict.level == "warn" and "never fires" not in verdict.message, verdict


def test_an_entry_missing_its_counts_names_the_skill_and_the_prescription():
    """A bare `KeyError` reads like a bug in the harness rather than what it is: a
    baseline written before counts existed, or hand-edited since. The threat model here is
    the same one `lowered_from` already assumes -- this file is committed, and the CLI is
    not the only thing that writes it."""
    stale = _measurement()
    del stale["invoke_n"]
    verdict = check("s", stale, "s" * 64, Declaration(0.8, "..."), n_skills=9)
    assert verdict.level == "fail"
    assert "invoke_n" in verdict.message and "re-measure" in verdict.message, verdict
