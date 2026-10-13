"""의심되는 하락은 믿기 전에 다시 잼.

반복되는 하락만 실행을 막음. 잡음 구간 안의 측정은 두 번째 실행 값을 치르지 않고,
수용된 하락은 확인 비용 없이 기록만 남음.
"""

from __future__ import annotations

import json
import re

from evals import run as runner
from evals.runner import baseline, case_corpus, config, invocation, session
from evals.runner.baseline import (
    description_sha,
)
from evals.runner.config import (
    SKILLS_DIR,
)
from evals.runner.session import (
    DEFAULT_CWD_LABEL,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._checks import (
    acceptance_failures,
    check,
    cwd_mismatches,
    read_declaration,
)
from tests.eval_harness._stubs import (
    _baseline,
    _canned_measurements,
    _measurement,
    _stub_sessions,
)


def test_a_suspected_drop_is_re_measured_before_it_is_believed(monkeypatch, tmp_path, capsys):
    """A first reading below baseline-delta must NOT reach the exit-4 path on its own."""
    scores_path, calls = _canned_measurements(
        monkeypatch,
        tmp_path,
        _baseline(invoke_rate=0.96, false_fire=0.04),
        [_measurement(invoke_rate=0.72, false_fire=0.04), _measurement(invoke_rate=0.92)],
    )
    assert runner.main(["--skill", "vdev"]) == 0, "a single unconfirmed reading failed the run"
    assert len(calls) == 2, f"the drop was judged on {len(calls)} measurement(s), not two"

    written = json.loads(scores_path.read_text(encoding="utf-8"))["skills"]["vdev"]
    assert written["invoke_rate"] == 0.92, "the recovered (higher) value must be recorded"
    assert written["confirmation"]["invoke_rate"] == [0.72, 0.92], "the pair must stay visible"
    assert "lowered_from" not in written, "a refuted drop is not an accepted drop"

    err = capsys.readouterr().err
    assert "SUSPECTED" in err and "NOT confirmed" in err, err
    # The cost is stated before it is spent, like the run plan itself.
    assert "55 more session(s)" in err, err


def test_only_a_drop_that_repeats_blocks_the_run(monkeypatch, tmp_path, capsys):
    """Both readings fall -> exit 4, and the pre-drop baseline is what stays on disk:
    overwriting it would destroy the only number `--accept` could later record from."""
    scores_path, calls = _canned_measurements(
        monkeypatch,
        tmp_path,
        _baseline(invoke_rate=0.96, false_fire=0.04),
        [_measurement(invoke_rate=0.72, false_fire=0.04), _measurement(invoke_rate=0.70)],
    )
    assert runner.main(["--skill", "vdev"]) == 4
    assert len(calls) == 2
    assert json.loads(scores_path.read_text(encoding="utf-8"))["skills"]["vdev"]["invoke_rate"] == (
        0.96
    ), "a confirmed drop must not overwrite the baseline it fell from"
    err = capsys.readouterr().err
    assert "CONFIRMED drop" in err and "invoke_rate 0.72 then 0.7" in err, err


def test_a_measurement_within_the_noise_band_costs_no_second_run(monkeypatch, tmp_path):
    """The re-measure is 55 sessions. Spending them on every wobble is how the runner
    stops being run at all."""
    _, calls = _canned_measurements(
        monkeypatch,
        tmp_path,
        _baseline(invoke_rate=0.96, false_fire=0.04),
        [_measurement(invoke_rate=0.90, false_fire=0.08)],
    )
    assert runner.main(["--skill", "vdev"]) == 0
    assert len(calls) == 1, "a within-delta move triggered a confirmation re-measure"


def test_accept_records_the_drop_without_paying_for_a_confirmation(monkeypatch, tmp_path):
    """The escape hatch survives: the operator has already judged the drop, so a second
    measurement would spend 55 sessions to change nothing."""
    scores_path, calls = _canned_measurements(
        monkeypatch,
        tmp_path,
        _baseline(invoke_rate=0.96, false_fire=0.04),
        [_measurement(invoke_rate=0.72, false_fire=0.04)],
    )
    argv = ["--skill", "vdev", "--accept", "--reason", "description narrowed on purpose"]
    assert runner.main(argv) == 0
    assert len(calls) == 1
    written = json.loads(scores_path.read_text(encoding="utf-8"))["skills"]["vdev"]
    assert written["lowered_from"] == {"invoke_rate": 0.96}
    assert written["lowered_reason"] == "description narrowed on purpose"
    # The record it writes must satisfy the gate that reads such records back.
    assert acceptance_failures({"skills": {"vdev": written}}) == []


def test_the_confirmation_re_measure_uses_the_same_turn_budget(monkeypatch, tmp_path):
    """Both readings must be taken under the same conditions or the comparison is not a
    comparison. A confirmation run at a different `--max-turns` could "recover" purely by
    giving the agent more room, and the recorded value -- which is the second reading --
    would then describe a budget the baseline was never measured at.
    """
    _, calls = _canned_measurements(
        monkeypatch,
        tmp_path,
        _baseline(invoke_rate=0.96, false_fire=0.04),
        [
            _measurement(invoke_rate=0.72, false_fire=0.04),
            _measurement(invoke_rate=0.92, false_fire=0.04),
        ],
    )
    assert runner.main(["--skill", "vdev", "--max-turns", "6"]) == 0
    assert len(calls) == 2, "the suspected drop was not confirmed by a second measurement"
    assert [call["max_turns"] for call in calls] == [6, 6]


def test_the_entry_records_counts_not_only_the_rounded_rate(monkeypatch, tmp_path):
    """An exact binomial test needs k and n, and a rounded rate cannot supply them.

    The rate stays as a human-readable derived field and the gate reads the integers.
    Both halves of that split are load-bearing: `scores.json` is committed and hand-edited
    (the same threat model `lowered_from` already assumes), so the two can drift apart and
    the integers have to be the ones believed -- and at a reps-raised `n` a true 0.204
    rounds to a passing 0.20 while a single hit rounds to a 0.00 that reads as "this
    description never fires".
    """
    _stub_sessions(monkeypatch)
    entry = invocation.measure_skill(
        "vdev",
        {"happy": [{"prompt": "happy"}], "negative": [{"prompt": "negative"}]},
        reps=1,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=6,
        model=config.MODEL,
    )
    assert (entry["invoke_hits"], entry["invoke_n"]) == (1, 1)
    assert (entry["false_hits"], entry["false_n"]) == (0, 1)
    # The derived fields stay, because a reviewer reading a diff of this file needs a
    # number they can compare at a glance; they are not what the gate reads.
    assert (entry["invoke_rate"], entry["false_fire"]) == (1.0, 0.0)


def test_a_skill_with_no_happy_path_records_null_counts_not_zero(monkeypatch, tmp_path):
    """`harness-authoring`'s shape (spec 3.1). "No happy path exists" and "it fired zero
    times out of 25" are different statements, and 0/0 written as 0 would collapse them --
    straight into the one data-independent floor, `invoke_hits == 0`, which would then fail
    a skill that is behaving exactly as designed.
    """
    _stub_sessions(monkeypatch)
    entry = invocation.measure_skill(
        "harness-authoring",
        {"happy": [], "negative": [{"prompt": "negative"}]},
        reps=1,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=3,
        model=config.MODEL,
    )
    assert (entry["invoke_hits"], entry["invoke_n"]) == (None, None)
    assert (entry["false_hits"], entry["false_n"]) == (0, 1)


def test_measure_skill_records_the_cwd_alongside_the_ratios(monkeypatch, tmp_path):
    """The recording half of Fix 4, with `measure_skill` REAL and only the session stubbed.

    The plumbing test below stubs `measure_skill` out, so on its own it proves the label
    is computed and passed and nothing about it reaching the file -- dropping the `cwd`
    key entirely leaves it green. This one holds the actual entry the runner builds.
    """
    seen = _stub_sessions(monkeypatch)
    entry = invocation.measure_skill(
        "vdev",
        {"happy": [{"prompt": "happy"}], "negative": [{"prompt": "negative"}]},
        reps=1,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=6,
        model=config.MODEL,
    )
    assert entry["cwd"] == DEFAULT_CWD_LABEL, "the measured environment was not recorded"
    assert entry["description_sha"] == description_sha(SKILLS_DIR / "vdev")
    assert (entry["invoke_rate"], entry["false_fire"]) == (1.0, 0.0)
    # Recorded beside the ratios for the same reason `cwd` is: a score is only comparable
    # to another score taken under the same budget and model (spec 5.1). `truncated` is
    # null rather than 0.0 because this stub fires on every happy prompt — there are no
    # misses for the turn cap to be blamed for.
    assert (entry["truncated"], entry["max_turns"], entry["model"]) == (None, 6, config.MODEL)
    # The restricted diagnostic re-runs the happy case with every other tool removed.
    # Asserting the flag reached the session is the point: without it the arm measures
    # the same thing as `invoke_rate` and the two columns agree for the wrong reason.
    assert entry["restricted"] == 1.0
    assert ("happy", "Skill") in seen, f"the restricted arm did not block other tools: {seen}"
    assert ("negative", None) in seen, "the negative arm must run with tools available"


def test_what_measure_skill_writes_is_what_the_gate_reads(monkeypatch, tmp_path):
    """The seam between the two halves of this harness, and nothing crossed it.

    Every test around `check()` builds its entry by hand (`_measurement()`), and every test
    around `measure_skill` asserts individual fields. So a key the runner stops writing, or
    starts writing under another name, breaks the contract in the one place neither side
    looks -- and the failure is not loud. The sister repo shipped exactly this: a missing
    model stamp made every LATER entry fail the model gate, unfixable by re-measuring
    because re-measuring reproduced it, while the write-side check read the absent key as a
    model change and stopped ratcheting entirely (harness-tier `tests/test_evals.py`).

    The gap is live here in `corpus_sha`. `_measurement()` omits it and `measure_skill`
    writes it, so nothing asserted it reaches an entry -- and if it stopped, `check()` only
    WARNS (an entry predating the key is not wrong, only old), so the suite would stay green
    while `measurement_is_current` read every entry as stale and re-measured every skill in
    the corpus, every run. Both readers are asserted below for that reason: the gate's
    verdict and the runner's freshness decision are different consumers of the same key.
    """
    _stub_sessions(monkeypatch)
    spec = {
        "expect_invoke": 0.5,
        "expect_why": "not the subject of this test; `read_declaration` requires it present",
        "happy": [{"prompt": "happy"}],
        "negative": [{"prompt": "negative"}],
    }
    entry = invocation.measure_skill(
        "vdev",
        spec,
        reps=2,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=config.DEFAULT_MAX_TURNS,
        model=config.MODEL,
    )

    verdict = check(
        "vdev",
        entry,
        description_sha(SKILLS_DIR / "vdev"),
        read_declaration("vdev", spec),
        n_skills=9,
        corpus=case_corpus.corpus_sha(spec),
    )
    assert verdict.level == "ok", verdict.message
    # The runner's own reader of the same fingerprints. A `warn` above would already have
    # failed this test, but this is the consumer whose cost is measured in hours.
    assert baseline.measurement_is_current(entry, "vdev", spec), (
        "the entry measure_skill just wrote does not satisfy the freshness check that "
        "decides whether to measure it again"
    )
    # The third reader, and the third fingerprint: `cwd` is derived inside `measure_skill`
    # from the resolved cases, and `cwd_mismatches` re-derives it from the same spec.
    assert cwd_mismatches({"skills": {"vdev": entry}}, {"vdev": spec}) == []


def test_a_measurement_carries_its_own_date_rather_than_the_files(monkeypatch, tmp_path):
    """Provenance per skill, because the file header cannot carry it.

    The default mode is incremental: the normal run measures ONE skill and rewrites the
    whole file. A date that exists only in the header therefore claims this run's
    measurement date for the entries it never touched, and the question it answers
    wrongly -- "how old is this number?" -- is the one asked immediately before trusting a
    score.
    Ported from the sister repo, which stamps the same per-entry date (harness-tier
    `evals/run.py`) and whose `save()` writes nothing file-level for this reason.

    `reps` was once the deliberate exception, kept in the header too because it equalled the
    corpus's declared sample size and a gate asserted so. A per-skill `reps:` turned that one
    number into a default the assertion no longer covered, so the header went and the gate
    moved onto the entry. Neither field has a file-level form now.

    This test calls the UNSTUBBED `measure_skill`, which is what makes it the owner of the
    stamp: `test_an_incremental_run_leaves_the_skills_it_never_measured_untouched` runs
    against a stub and could only read back a literal it supplied itself.
    """
    _stub_sessions(monkeypatch)
    entry = invocation.measure_skill(
        "vdev",
        {"happy": [{"prompt": "happy"}], "negative": [{"prompt": "negative"}]},
        reps=1,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=config.DEFAULT_MAX_TURNS,
        model=config.MODEL,
    )
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["measured_at"]), entry.get("measured_at")


def test_the_measured_cwd_is_recorded_with_the_scores(monkeypatch, tmp_path):
    """Fix 4: the environment stops being invisible. The runner labels the default empty
    temp dir rather than writing its random path, which would differ every run and so
    could never be compared."""
    scores_path, calls = _canned_measurements(
        monkeypatch,
        tmp_path,
        _baseline(invoke_rate=0.96, false_fire=0.04),
        [_measurement(invoke_rate=0.96, false_fire=0.04)],
    )
    assert runner.main(["--skill", "vdev"]) == 0
    assert calls[0]["workspace"].explicit is None, "the default run names no directory"
    assert json.loads(scores_path.read_text(encoding="utf-8"))["skills"]["vdev"]["cwd"] == (
        DEFAULT_CWD_LABEL
    )

    project = tmp_path / "a-real-project"
    project.mkdir()
    _, explicit = _canned_measurements(
        monkeypatch,
        tmp_path,
        _baseline(invoke_rate=0.96, false_fire=0.04),
        [_measurement(invoke_rate=0.96, false_fire=0.04)],
    )
    assert runner.main(["--skill", "vdev", "--cwd", str(project)]) == 0
    assert explicit[0]["workspace"].explicit == project.resolve()
