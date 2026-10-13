"""게이트에 이빨이 있는가 — 조작한 baseline 을 먹여 붉어지는지 잼.

검사가 `*_failures(scores) -> list[str]` 로 쓰인 이유가 이것. 맨 assert 였다면
이빨 빠진 게이트를 탐지할 방법이 없음.
"""

from __future__ import annotations

from pathlib import Path

from evals import run as runner
from evals.runner import case_corpus, config
from evals.runner.baseline import (
    description_sha,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._checks import (
    acceptance_failures,
    check,
    gate_verdicts,
    read_declaration,
)
from tests.eval_harness._stubs import (
    _measurement,
    _verdict,
)


def test_the_freshness_check_reds_when_a_description_moves(tmp_path: Path):
    """The proof for the load-bearing judgement, run against real files: fingerprint a
    skill, edit only its description, and require the gate to notice."""
    skill = tmp_path / "probe"
    skill.mkdir()
    target = skill / "SKILL.md"
    target.write_text(
        "---\nname: probe\ndescription: Use when the probe fires.\n---\n\nbody\n",
        encoding="utf-8",
    )
    cases = {"probe": {"expect_invoke": 0.5, "expect_why": "declared"}}
    scores = {
        "skills": {
            "probe": _measurement(
                description_sha=description_sha(skill),
                # A healthy entry carries BOTH fingerprints now; without this the entry is
                # merely stale in the other direction and the "ok" below would be a warn.
                corpus_sha=case_corpus.corpus_sha(cases["probe"]),
            )
        }
    }
    assert [v.level for v in gate_verdicts(scores, cases, tmp_path)] == ["ok"]

    target.write_text(
        "---\nname: probe\ndescription: Use when the probe fires on something else.\n---\n\nbody\n",
        encoding="utf-8",
    )
    stale = gate_verdicts(scores, cases, tmp_path)
    assert [v.level for v in stale] == ["fail"] and "re-measure" in stale[0].message.lower()

    # The body is NOT fingerprinted: re-measuring the whole corpus for an edit that cannot
    # move the score is how a team learns to delete the gate.
    target.write_text(
        "---\nname: probe\ndescription: Use when the probe fires.\n---\n\nrewritten body\n",
        encoding="utf-8",
    )
    assert [v.level for v in gate_verdicts(scores, cases, tmp_path)] == ["ok"], (
        "a body edit must not demand a re-measure"
    )


def test_the_freshness_check_reds_when_a_prompt_or_a_fixture_moves(tmp_path: Path, monkeypatch):
    """The second fingerprint, and the demonstration that one was not enough.

    `invoke_rate`'s inputs are (description, prompts, fixture) and only the description was
    pinned, so the corpus could be rewritten under a committed score in total silence: every
    `description_sha` still matched, this gate said nothing, and `select_skills` returned an
    empty list -- the runner reported "nothing to measure" while the recorded counts went on
    describing prompts that no longer existed. This branch was in exactly that state, with
    a batch of prompts rewritten and fixture overrides added.

    The fixture half matters as much as the prompt half: the same sentence asked in a web
    project and in an empty directory is two different questions (spec 4.5), so a
    fingerprint over prompt text alone would miss every override.
    """
    skill = tmp_path / "probe"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: probe\ndescription: Use when the probe fires.\n---\n\nbody\n",
        encoding="utf-8",
    )
    cases = {
        "probe": {
            "expect_invoke": 0.5,
            "expect_why": "declared",
            "fixture": "empty-web",
            "happy": [{"prompt": "첫 케이스 만들어줘."}],
        }
    }
    entry = _measurement(
        description_sha=description_sha(skill), corpus_sha=case_corpus.corpus_sha(cases["probe"])
    )
    scores = {"skills": {"probe": entry}}
    assert [v.level for v in gate_verdicts(scores, cases, tmp_path)] == ["ok"]

    reworded = {"probe": {**cases["probe"], "happy": [{"prompt": "스펙 하나 깔아줘."}]}}
    verdicts = gate_verdicts(scores, reworded, tmp_path)
    assert [v.level for v in verdicts] == ["fail"], "a rewritten prompt is a stale score"
    assert "corpus_sha" in verdicts[0].message and "re-measure" in verdicts[0].message.lower()

    moved = {"probe": {**cases["probe"], "fixture": "custom-testdir"}}
    assert [v.level for v in gate_verdicts(scores, moved, tmp_path)] == ["fail"], (
        "the same prompt in another project is another question"
    )

    # And the runner's half: a stale corpus must SELECT the skill, or the gate reports a
    # re-measurement nobody would ever be told to run. A missing fingerprint counts as
    # stale there while it is only a warning here -- the asymmetry is deliberate, since a
    # needless re-measure costs one skill's sessions and a skipped one costs a lying baseline.
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    args = runner.build_parser().parse_args([])
    assert runner.select_skills(args, reworded, scores) == ["probe"]
    assert runner.select_skills(args, cases, scores) == []
    stale = {"skills": {"probe": {**entry, "corpus_sha": None}}}
    assert runner.select_skills(args, cases, stale) == ["probe"]


def test_a_score_with_nothing_left_to_describe_reds(tmp_path: Path):
    """Two ways an entry outlives what it measured, and neither may be dropped silently --
    a score nobody can attach to a skill is a claim about a product that no longer exists.
    """
    entry = {"skills": {"deleted": _measurement()}}
    assert gate_verdicts(entry, {"deleted": {"expect_invoke": 0.5, "expect_why": "x"}}, tmp_path), (
        "a skill that cannot be fingerprinted must red"
    )
    orphan = gate_verdicts(entry, {}, tmp_path)
    assert [v.level for v in orphan] == ["fail"] and "absent from" in orphan[0].message


def test_the_false_fire_ceiling_reds_on_the_counts_and_passes_its_boundary():
    """The one absolute threshold that survives, because it needs no calibration: a skill
    intercepting more than a fifth of its neighbours' prompts is wrong however rarely it
    fires on its own."""
    assert _verdict(false_hits=5, false_n=25).level == "ok", "0.20 is the boundary and a PASS"
    assert _verdict(false_hits=6, false_n=25).level == "fail"
    assert _verdict(false_hits="4").level == "fail", "a string count is not a measurement"


def test_the_only_surviving_absolute_floor_is_the_zero_one():
    """Asserted rather than assumed, for the reason the retired global floor slept: if
    "deliberately absent" and "silently broken" look alike, that IS the failure this suite
    exists to catch.

    A skill measured at 1/25 is not failed by anything here -- it only warns against its
    own declaration -- while 0/25 is a hard failure. The difference is that a committed
    zero freezes into the ratchet's reference and keeps it there; if the true rate is
    merely low, a re-measure produces something nonzero, and this failure forces it.
    """
    assert _verdict(invoke_hits=1, invoke_n=25, expect=0.05).level == "ok"
    zero = _verdict(invoke_hits=0, invoke_n=25)
    assert zero.level == "fail" and "never fires" in zero.message

    # And the forcing function that replaced the retired global floor is armed: a skill
    # that declares nothing cannot be judged, so it fails rather than passing quietly.
    assert check("s", _measurement(), "s" * 64, read_declaration("s", {}), n_skills=9).level == (
        "fail"
    )


def test_the_gate_reads_null_counts_as_unmeasurable_not_as_zero():
    """`harness-authoring`'s shape: no happy path, negatives still scored. Reading
    those nulls as zero would drive the skill straight into the zero floor above and fail
    it forever for behaving exactly as designed."""
    no_happy = {"invoke_hits": None, "invoke_n": None, "invoke_rate": None}
    assert _verdict(name="harness-authoring", expect=None, **no_happy).level == "ok"
    assert _verdict(name="harness-authoring", expect=None, false_hits=6, **no_happy).level == (
        "fail"
    ), "a null invoke arm must not exempt the skill from the false_fire ceiling"
    assert (
        _verdict(
            name="harness-authoring",
            expect=None,
            false_hits=None,
            false_n=None,
            false_fire=None,
            **no_happy,
        ).level
        == "fail"
    ), "an all-null entry measures nothing and must not pass as a measurement"


def test_nulling_out_the_happy_arm_cannot_launder_a_failing_skill():
    """The exemption above is the one place a null makes judgements disappear, so it is
    pinned to the DECLARATION rather than to the numbers.

    Otherwise the cheapest way past the zero floor and the shortfall warn is to hand-edit
    `invoke_hits`/`invoke_n` to null: every judgement that reads them then skips and the
    entry goes green having measured nothing. So the declaration and the entry have to
    agree about whether a happy path exists at all, in both directions.
    """
    no_happy = {"invoke_hits": None, "invoke_n": None, "invoke_rate": None}
    assert _verdict(invoke_hits=0, invoke_n=25, expect=0.7).level == "fail", (
        "the state being escaped from must really fail, or this test proves nothing"
    )
    assert _verdict(expect=0.7, **no_happy).level == "fail", "...and nulling it out is no escape"

    # The mirror image: an entry that measured a happy arm for a skill declared to have
    # none means the corpus and the baseline disagree about what this skill even is.
    assert _verdict(name="harness-authoring", expect=None, invoke_hits=20, invoke_n=25).level == (
        "fail"
    )


def test_the_acceptance_check_reds_on_an_unexplained_or_invented_lowering():
    """The magnitude half now asks the exact test the same question the runner asked: would
    this drop ever have demanded `--accept`? A record claiming a fall the ratchet would have
    let through unremarked was not produced by the runner, and the only other author of this
    file is a person editing it by hand."""
    fell = _measurement(invoke_hits=11, invoke_n=25, invoke_rate=0.44)
    real_drop = dict(fell, lowered_from={"invoke_rate": 0.64})
    assert acceptance_failures({"skills": {"s": dict(real_drop, lowered_reason="traded")}}) == []
    assert acceptance_failures({"skills": {"s": real_drop}}), "a drop with no reason must red"

    invented = dict(fell, lowered_from={"invoke_rate": 0.48}, lowered_reason="noise")
    assert acceptance_failures({"skills": {"s": invented}}), (
        "a move the ratchet would never have flagged makes the record fabricated"
    )
    countless = {"invoke_rate": 0.44, "lowered_from": {"invoke_rate": 0.64}, "lowered_reason": "x"}
    assert acceptance_failures({"skills": {"s": countless}}), (
        "without counts the claim cannot be checked at all, which is not a pass"
    )
