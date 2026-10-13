"""코퍼스 무결성 — cases.yaml 과 스킬 집합이 서로를 덮는가.

`tests/skill_docs/` 의 covered-XOR-registered 규칙을 eval 케이스에 적용한 것.
모델 호출 가능한 새 스킬은 케이스 없이 도착 불가, 호출 금지 스킬은 절대 발화할
수 없는 케이스를 달고 도착 불가.
"""

from __future__ import annotations

from evals.runner.case_corpus import (
    load_cases,
)
from evals.runner.config import (
    CASES_PATH,
    SKILLS_DIR,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._checks import (
    MAX_FAR_NEGATIVES,
    NO_HAPPY_PATH,
    VALID_KINDS,
)
from tests.eval_harness._stubs import (
    _model_invocable,
)


def test_every_skill_is_either_model_invocable_with_cases_or_neither():
    """The XOR `tests/skill_docs/` applies to sandbox coverage, applied to eval cases.

    A model-invocable skill's description is the ONLY thing deciding whether it fires,
    so shipping one with no cases means shipping the untested half of the product. The
    other direction matters too: `disable-model-invocation` skills are reached by the
    user typing `/name`, so eval cases for one would measure a path that does not
    exist and report coverage that is not there (spec 3).
    """
    _, cases = load_cases()
    problems: list[str] = []
    for skill_dir in sorted(SKILLS_DIR.glob("*/")):
        if not (skill_dir / "SKILL.md").is_file():
            continue
        name = skill_dir.name
        invocable = _model_invocable(skill_dir)
        has_cases = name in cases
        if invocable and not has_cases:
            problems.append(
                f"{name}: model-invocable but absent from {CASES_PATH.name} -- add happy "
                f"and negative cases, or set disable-model-invocation if it is /-only"
            )
        if not invocable and has_cases:
            problems.append(
                f"{name}: disable-model-invocation, yet {CASES_PATH.name} carries cases "
                f"for it -- the description never reaches the model, so they measure nothing"
            )
    assert not problems, "\n".join(problems)


def test_every_cases_key_names_a_real_skill():
    """`load_cases()` rejects this first; the assert stands for the day it stops.

    A key for a deleted or renamed skill is a corpus that describes a product that no
    longer exists, and the eval reads green because nothing measures a missing skill.
    """
    _, cases = load_cases()
    missing = [name for name in cases if not (SKILLS_DIR / name / "SKILL.md").is_file()]
    assert not missing, f"{CASES_PATH.name} names skill(s) with no SKILL.md: {missing}"


def test_negative_cases_declare_a_valid_kind():
    _, cases = load_cases()
    problems: list[str] = []
    for name, spec in sorted(cases.items()):
        for index, case in enumerate(spec.get("negative") or []):
            kind = case.get("kind")
            if kind not in VALID_KINDS:
                problems.append(
                    f"{name}.negative[{index}]: kind={kind!r}, expected one of "
                    f"{sorted(VALID_KINDS)} -- an unlabelled case escapes the far cap"
                )
    assert not problems, "\n".join(problems)


def test_no_skill_leans_on_more_than_one_far_negative():
    """Near x4 + far <=1.

    Far cases are the cheap ones to write and the least informative to score -- a
    prompt sharing no vocabulary with the skill was never going to fire it, so its
    0.00 measures the corpus's laxity rather than the skill's precision. Capping them
    keeps `false_fire` a statement about the near boundary, where over-firing lives.
    """
    _, cases = load_cases()
    problems: list[str] = []
    for name, spec in sorted(cases.items()):
        far = [c for c in (spec.get("negative") or []) if c.get("kind") == "far"]
        if len(far) > MAX_FAR_NEGATIVES:
            problems.append(
                f"{name}: {len(far)} far negatives > {MAX_FAR_NEGATIVES} -- replace the "
                f"extras with near cases that share the skill's own vocabulary"
            )
    assert not problems, "\n".join(problems)


def test_only_the_registered_skill_may_have_no_happy_cases():
    """An empty `happy` list is a declaration that the skill has no direct path,
    not a shortcut for "not written yet" -- it makes `invoke_rate` null, and the
    threshold check then skips the skill entirely. Exactly one skill has earned that.
    """
    _, cases = load_cases()
    problems: list[str] = []
    for name, spec in sorted(cases.items()):
        if (spec.get("happy") or []) or name in NO_HAPPY_PATH:
            continue
        problems.append(
            f"{name}: no happy cases, so invoke_rate is null and the floor never applies "
            f"to it. Only {sorted(NO_HAPPY_PATH)} may do that (spec 3.1)."
        )
    assert not problems, "\n".join(problems)


def test_the_no_happy_path_exemption_names_a_caller_that_really_calls(monkeypatch):
    """`NO_HAPPY_PATH` exempts a whole arm from measurement, and its justification was prose.

    The claim is that harness-authoring has no direct path -- its only reach is another
    skill invoking it -- so an autonomous rate would measure the thing the description says
    not to do. That is a claim about a DIFFERENT file: `skills/harness-init/SKILL.md`
    invokes it today. Delete that line and the skill is simultaneously unmeasured (this
    registry) and unreachable (nothing calls it), with the suite green either way.

    So the exemption has to be earned in machine-readable form. `reached_programmatically`
    says the path exists; `invoked_by` names the file; this checks the file contains the
    call. Ported from the sister repo (harness-tier
    `tests/test_evals.py`), whose cases.yaml carries the same two keys.

    The second half is the sister's argument that vway-kit lacked, and it is the one that
    looks like a tidy-up. **A skill must stay MODEL-invoked to be reachable from another
    skill at all** -- a `disable-model-invocation` skill is reachable only by the user
    typing its name. harness-authoring's description says it is not invoked directly
    ("직접 호출하지 않는다"), which reads like an invitation to set that flag; doing so would
    sever the harness-init fan-out and nothing about the description would look wrong.
    `test_every_skill_is_either_model_invocable_with_cases_or_neither` would also red, but
    for an unrelated reason (it has cases), and a reader fixing THAT would delete the cases.
    """
    _, cases = load_cases()
    declared = {name for name, spec in cases.items() if spec.get("reached_programmatically")}

    # The registry and the declaration have to be the same set. A skill exempted from the
    # happy arm with no declared caller has an unexamined exemption; a skill declaring one
    # while carrying happy cases is claiming a justification it does not use.
    assert declared == set(NO_HAPPY_PATH) & set(cases), (
        f"skills exempted from the happy arm are {sorted(set(NO_HAPPY_PATH) & set(cases))} "
        f"but {CASES_PATH.name} declares reached_programmatically for {sorted(declared)} -- "
        f"the exemption's justification has to be readable by this test, not only by a human"
    )

    for name in sorted(declared):
        callers = {
            path.parent.name
            for path in SKILLS_DIR.glob("*/SKILL.md")
            if path.parent.name != name
            and f"invoke skill `{name}`" in path.read_text(encoding="utf-8").lower()
        }
        assert callers, (
            f"{name}: {CASES_PATH.name} declares reached_programmatically, but no shipped "
            f"skill says Invoke skill `{name}`. Either the caller was removed -- leaving "
            f"this skill unmeasured AND unreachable -- or the claim is stale."
        )
        # The declared file, not merely SOME file. `invoked_by` is what a reader follows;
        # a stale pointer sends them to a file that no longer makes the call while another
        # one quietly keeps the claim true.
        invoked_by = cases[name].get("invoked_by")
        assert invoked_by in {f"{caller}/SKILL.md" for caller in callers}, (
            f"{name}: invoked_by={invoked_by!r}, but the skills that actually invoke it are "
            f"{sorted(callers)}"
        )
        # And it has to stay model-invocable, or the caller above cannot reach it either.
        assert _model_invocable(SKILLS_DIR / name), (
            f"{name}: disable-model-invocation would sever the very path "
            f"reached_programmatically claims -- a skill is reachable from another skill "
            f"only while it is model-invoked"
        )
