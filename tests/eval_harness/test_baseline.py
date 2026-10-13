"""baseline 왕복과 증분 실행 — 측정하지 않은 스킬은 건드리지 않음.

표본 크기는 스킬이 스스로 선언할 수 있고, 그 선언은 가격표만이 아니라 실제 측정에
도달해야 함. 명시 `--reps` 플래그가 선언을 이김.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evals import run as runner
from evals.runner import case_corpus, config, invocation, ratchet, session
from evals.runner.baseline import (
    load_scores,
)
from evals.runner.case_corpus import (
    load_cases,
)
from evals.runner.config import (
    CASES_PATH,
    SCORES_PATH,
    EvalError,
)
from evals.runner.session import (
    DEFAULT_CWD_LABEL,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._stubs import (
    _canned_measurements,
    _measurement,
    _stub_sessions,
)


def test_the_committed_baseline_round_trips():
    """`evals/scores.json` is committed, so a shape the runner cannot read would be
    discovered on the day someone finally runs the full measurement -- at the end of it.

    **A null `measured_at` is a first-class value**, not a gap to be filled in. It says
    "nobody knows when this was measured", which is the true thing to say about an entry
    carried over from before the field existed. Backfilling a probably-right date would
    reproduce the very fault the field exists to remove: a value that reads as measured when
    it was reconstructed, with nothing downstream able to tell the two apart. The next real
    measurement replaces it.
    """
    assert SCORES_PATH.is_file(), f"{SCORES_PATH} is missing; the gate has no baseline to read"
    scores = load_scores()
    assert isinstance(scores["skills"], dict)
    # NOTHING beside `skills`. A file-level `measured_at`/`reps` is a claim about every entry,
    # written by a run that measured ONE of them -- the default mode is incremental, so the
    # skills it never touched silently inherit this run's date and sample size. The
    # sister repo's `save()` writes nothing file-level for the same reason (harness-tier
    # `evals/run.py` names the fault). Provenance a reader can trust lives on the
    # entry, because only the entry was produced by the run that wrote it.
    assert set(scores) == {"skills"}, (
        f"scores.json carries file-level {sorted(set(scores) - {'skills'})} -- an incremental "
        f"run stamps those for the skills it never measured"
    )
    default_reps, cases = load_cases()
    # The replacement for the old one-number check `scores["reps"] == reps`. That assertion
    # held only while a single value described every entry; the moment a skill could declare
    # its own it would have kept passing while meaning nothing for the overriding skill -- a
    # gate whose message outlives its meaning, which is the exact defect this file's ledger
    # exists to prevent. Comparing EACH entry to ITS OWN effective declaration is strictly
    # stronger: it catches a per-skill `reps:` edit that the old check could not see at all.
    # Removing the file-level keys removed the only assertion that a DATE existed at all --
    # the old `set(scores) >= {"measured_at", "reps", "skills"}`. It asserted the wrong thing
    # (a header that described skills it had not measured), but it did assert presence,
    # and dropping it without a replacement opened a fresh hole in the very layer this change
    # exists to protect: delete `entry["measured_at"] = ...` from `measure_skill` and every
    # other check here stays green.
    #
    # So the KEY is mandatory and the VALUE may be null. Null means "measured before this
    # field existed" -- no committed entry is null today, but the allowance stays because an
    # entry carried over from then cannot be dated. `measure_skill` never writes null, so the
    # two are distinguishable: a stamp that stops being written leaves the key MISSING, which
    # fails here. What is NOT recoverable is a date for a measurement nobody dated, which is why
    # such an entry stays null rather than being backfilled -- see the round-trip note.
    undated = [n for n, e in scores["skills"].items() if "measured_at" not in e]
    assert not undated, (
        f"{undated} carry no `measured_at` key at all. Null is allowed (it means the "
        f"measurement predates the field); an absent key means nothing stamped it"
    )
    malformed = {
        n: e["measured_at"]
        for n, e in scores["skills"].items()
        if e["measured_at"] is not None
        and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e["measured_at"]))
    }
    assert not malformed, f"`measured_at` must be an ISO date or null: {malformed}"

    mismatched = {}
    for name, entry in scores["skills"].items():
        if name not in cases:
            continue
        declared = case_corpus.effective_reps(cases[name], default_reps)
        if entry.get("reps") != declared:
            mismatched[name] = f"entry {entry.get('reps')} vs corpus {declared}"
    # The remedy names `--skill` explicitly because the DEFAULT run will not do it. Selection
    # keys on `description_sha`/`corpus_sha` and `reps` is in neither -- deliberately, since
    # `corpus_sha` fingerprints the questions asked and asking one more times does not change
    # them. So a bare `uv run python -m evals.run` after a `reps:` edit prints "nothing to
    # measure" while this gate stays red. Telling someone to re-measure without naming the
    # command that re-measures sends them to that dead end.
    #
    # The dead end is still an improvement on what it replaced: under the one-number check,
    # measuring ANY skill rewrote the header and turned the gate green while the others
    # kept their old reps. Red-until-someone-acts beats green-because-something-was-touched.
    assert not mismatched, (
        f"these entries record a sample size the corpus no longer declares: {mismatched}. "
        f"Re-measure each with `uv run python -m evals.run --skill <name>` (the bare "
        f"incremental run will NOT pick this up -- `reps` is not part of corpus_sha), or "
        f"restore the declaration in {CASES_PATH.name}"
    )


def test_an_incremental_run_leaves_the_skills_it_never_measured_untouched(monkeypatch, tmp_path):
    """The whole reason the file-level fields had to go, held as behaviour rather than shape.

    `test_the_committed_baseline_round_trips` asserts the keys are absent, which a future
    edit could satisfy while reintroducing the fault somewhere else (a `save()` that stamps a
    date onto every entry it rewrites, say). This drives the REAL `measure()` over a
    two-skill baseline, measures ONE, and demands the other come back byte-identical.

    The old header made that impossible to satisfy: measuring `vdev` alone rewrote
    `measured_at` to today, and a reader asking "how old is the doc-sync number?" -- the
    reader most in need of an honest answer -- got today's date for a measurement that could
    be months stale. That is a silent false negative in the provenance layer: nothing errors,
    the file stays well-formed, and the wrong answer is the confident one.
    """
    untouched = _measurement(measured_at="2026-01-02", reps=5, invoke_rate=0.44)
    baseline = {
        "skills": {
            "vdev": _measurement(measured_at="2026-01-02", reps=5),
            "doc-sync": untouched,
        }
    }
    scores_path, _ = _canned_measurements(
        monkeypatch, tmp_path, baseline, [_measurement(measured_at="2026-07-20", reps=5)]
    )
    assert runner.main(["--skill", "vdev"]) == 0
    written = json.loads(scores_path.read_text(encoding="utf-8"))
    assert set(written) == {"skills"}, f"a run of one skill wrote file-level {sorted(written)}"
    assert written["skills"]["doc-sync"] == untouched, (
        "measuring vdev rewrote the doc-sync entry -- provenance for a measurement that "
        "never happened"
    )
    # No assertion that vdev's own date is today's. `_canned_measurements` stubs
    # `measure_skill`, so any such value is the literal this test handed it, and reading it
    # back checks a JSON round-trip while reading as a provenance check -- it stayed green
    # with `entry["measured_at"] = ...` deleted from the runner. The real stamp is held by
    # `test_a_measurement_carries_its_own_date_rather_than_the_files`, which calls the
    # unstubbed function. What THIS test owns is every other entry.


def test_a_skill_can_declare_its_own_sample_size():
    """Ported from the sister (harness-tier `evals/run.py`), which spends the extra
    sessions where they buy the most: a skill measured at 0.32 has a far wider confidence
    interval per session than one at 0.92, so a flat corpus-wide `reps` over-samples the
    settled descriptions and under-samples the only ones anyone is arguing about.

    This is sound ONLY because the ratchet is an exact binomial comparing k/n with k/n, valid
    at `n_new != n_base` (spec 6). Under the old fixed-width delta it would have been a real
    error -- the width's defensibility came from the standard error at ONE sample size -- and
    that is why `reps` had to leave `COMPARABLE_CONDITIONS` before this became portable.
    """
    corpus_default = 5
    spec: dict = {"happy": [{"prompt": "a"}], "negative": [{"prompt": "b"}]}
    assert case_corpus.effective_reps(spec, corpus_default) == 5, "no declaration -> the default"

    spec["reps"] = 15
    assert case_corpus.effective_reps(spec, corpus_default) == 15

    # The declaration has to reach the PRICE, not only the measurement: an operator reading
    # "31 sessions" before hitting Ctrl-C is entitled to a number that includes the override.
    plan = runner.build_plan(
        runner.build_parser().parse_args(["--all"]), {"vdev": spec}, corpus_default, ["vdev"]
    )
    assert plan.skills[0].reps == 15
    # (1 happy + 1 negative) * 15, plus the one restricted re-run of each happy case.
    assert plan.skills[0].sessions == 31
    # And the confirmation re-measure, which is what a suspected drop spends. Costed at the
    # skill's own reps or the operator is quoted a price the run will not honour.
    assert ratchet.confirmation_cost(spec, corpus_default) == 30


def test_the_declared_sample_size_reaches_the_measurement_and_not_just_the_price(
    monkeypatch, tmp_path
):
    """The three assertions above are all on pure functions, and a review found that leaves
    the feature's actual wiring unguarded: reverting `measure_skill(..., reps=effective_reps(
    cases[name], reps))` to `reps=reps` kept all 105 tests green. A test named for a feature
    that does not exercise the feature is the shape of green this file exists to refuse.

    The failure it lets through is the expensive kind. The plan quotes 155 sessions, the run
    spends 55, and the recorded entry then disagrees with the corpus -- so the gate does go
    red, but only after a measurement that has already been paid for in wall-clock. The
    millisecond gate cannot see it, because `measure_skill` stamps `entry["reps"]` from
    whatever it was called with; the two agree by construction however wrong the call was.
    Catching it needs an assertion on the CALL, which is this.
    """
    corpus = tmp_path / "cases.yaml"
    corpus.write_text(
        "reps: 5\n"
        "skills:\n"
        "  vdev:\n"
        "    fixture: null\n"
        "    reps: 2\n"
        "    expect_invoke: 0.8\n"
        "    expect_why: x\n"
        "    happy:\n      - prompt: h\n"
        "    negative:\n      - prompt: n\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CASES_PATH", corpus)
    _, calls = _canned_measurements(
        monkeypatch, tmp_path, {"skills": {}}, [_measurement(reps=2, measured_at="2026-07-21")]
    )
    assert runner.main(["--skill", "vdev"]) == 0
    assert calls[0]["reps"] == 2, (
        f"the corpus declares reps: 2 for vdev but measure_skill was called with "
        f"{calls[0]['reps']} -- the declaration reached the plan and not the run"
    )


def test_a_per_skill_reps_declaration_is_validated_like_the_corpus_one(tmp_path, monkeypatch):
    """Same failure mode, same guard. `reps: 0` measures nothing and would write an entry
    whose `invoke_n` is 0, and `reps: "many"` would reach `range()` mid-run -- after the
    operator has already been quoted a session count built from it.
    """
    corpus = tmp_path / "cases.yaml"

    def _write(declared: str) -> None:
        corpus.write_text(
            f"reps: 5\nskills:\n  vdev:\n    fixture: null\n    reps: {declared}\n"
            "    expect_invoke: 0.9\n    expect_why: x\n    happy:\n      - prompt: p\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(config, "CASES_PATH", corpus)
    # `true` is here because it is the guard's whole reason for existing: `isinstance(True,
    # int)` is True in Python, so without the explicit bool check `reps: true` validates,
    # reaches `range(1, 2)`, measures every case once, and leaves a file that reads as a
    # deliberate declaration. A review found the guard was documented at length and never
    # exercised -- deleting `isinstance(value, bool) or` left the suite green.
    for bad in ("0", "-3", "'many'", "2.5", "true"):
        _write(bad)
        with pytest.raises(EvalError) as caught:
            load_cases()
        assert "reps" in str(caught.value), f"{bad} was rejected for the wrong reason"
    _write("15")
    default, skills = load_cases()
    assert skills["vdev"]["reps"] == 15
    # `null` is NOT an error: the guard reads `is not None`, so an explicit null means "no
    # declaration, use the corpus default" -- the same idiom `fixture: null` already carries
    # throughout this corpus. Pinned rather than assumed, because the natural place to write
    # it is right where someone is removing an override.
    _write("null")
    default, skills = load_cases()
    assert skills["vdev"]["reps"] is None
    assert case_corpus.effective_reps(skills["vdev"], default) == default == 5


def test_an_explicit_reps_flag_beats_a_per_skill_declaration(monkeypatch, tmp_path, capsys):
    """Priority, not only precedence: `--reps` is an operator naming a number for THIS run,
    and its help says exactly that. Before this, it replaced only the corpus DEFAULT, so
    `--skill X --probe --reps 15` against a skill declaring `reps: 3` measured at 3 while the
    plan header announced 15 -- the two printed lines contradicting each other was the only
    signal, and nothing failed. An operator who names a sample size and silently gets another
    has no way to find out; the run completes and the number is wrong.
    """
    corpus = tmp_path / "cases.yaml"
    corpus.write_text(
        "reps: 5\nskills:\n  vdev:\n    fixture: null\n    reps: 3\n"
        "    expect_invoke: 0.8\n    expect_why: x\n    happy:\n      - prompt: h\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CASES_PATH", corpus)
    assert runner.main(["--skill", "vdev", "--probe", "--reps", "15", "--dry-run"]) == 0
    plan = capsys.readouterr().err
    assert "reps=15" in plan and "reps 3" not in plan, plan
    # 1 happy case * 15, plus the single restricted re-run. At the declared 3 it would be 4.
    assert "16 session(s)" in plan, plan


def test_the_committed_counts_and_the_derived_rates_tell_the_same_story():
    """The gate reads the integers and ignores the ratios, which means a drift between
    the two is INVISIBLE to every other check here -- so it gets its own.

    This baseline's counts were reconstructed by hand from `rate * 25` when counts were
    introduced, and a transcription slip in that table would silently move the reference
    every future ratchet measures against.
    """
    problems: list[str] = []
    for name, entry in sorted(load_scores()["skills"].items()):
        for rate_key, (hits_key, n_key, _) in ratchet.COUNTS_FOR_METRIC.items():
            hits, total, rate = entry.get(hits_key), entry.get(n_key), entry.get(rate_key)
            if hits is None and total is None and rate is None:
                continue
            if not isinstance(hits, int) or not isinstance(total, int) or total < 1:
                problems.append(f"{name}.{rate_key}: counts are {hits!r}/{total!r}")
                continue
            if round(hits / total, 4) != rate:
                problems.append(f"{name}: {hits}/{total} is not the recorded {rate_key} {rate}")
    assert not problems, "\n".join(problems)


def test_the_sample_size_is_recorded_per_entry_even_though_it_is_no_longer_compared(
    monkeypatch, tmp_path: Path
):
    """`reps` left `COMPARABLE_CONDITIONS` with the delta that needed it (see
    `test_reps_is_no_longer_a_comparability_condition`), but it is still written per skill.

    There is no file header any more, and the reason it went is what this value replaced.
    Measuring a single skill at reps=3 stamped 3 over a header while the other entries,
    measured at 5, kept their ratios -- the run that CREATED the mismatch was the run that
    overwrote the record of it. What the per-entry value carries is provenance rather than
    comparability: `invoke_n` says how many samples there were, `reps` says how that n was
    reached, and those differ when the corpus itself grows.

    `assert measure_skill.__doc__ is not None` is not an assertion about anything:
    deleting `entry["reps"] = reps` leaves it green, and so would a committed entry carrying
    no `reps` at all. This holds the entry the runner builds, which is the only place the
    claim in the name is testable.
    """
    _stub_sessions(monkeypatch)
    entry = invocation.measure_skill(
        "vdev",
        {"happy": [{"prompt": "happy"}], "negative": [{"prompt": "negative"}]},
        reps=3,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=3,
        model=config.MODEL,
    )
    assert entry["reps"] == 3, "the per-entry sample size is the only one there is"
    # Provenance, not comparability: `invoke_n` counts the samples, `reps` says how that
    # count was reached. Three reps of one prompt and one rep of three prompts are the same
    # n and different corpora, and only these two fields together tell them apart.
    assert entry["invoke_n"] == 3 and entry["reps"] == 3

    baseline = {"model": config.MODEL, "max_turns": 3, "cwd": DEFAULT_CWD_LABEL, "reps": 5}
    thinner = {**baseline, "reps": 3}
    assert ratchet.incomparable_conditions(thinner, baseline) == {}
    # The exact test still judges the pair, using the counts rather than the sample size.
    assert ratchet.ratchet_violations(
        {**thinner, "invoke_hits": 3, "invoke_n": 15, "invoke_rate": 0.20},
        {**baseline, "invoke_hits": 20, "invoke_n": 25, "invoke_rate": 0.80},
        n_skills=9,
    ) == {"invoke_rate": 0.80}
