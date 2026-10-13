"""러너 자체 — 세션 스트림을 어떻게 읽고 언제 중단하는가.

점수 0 과 '못 쟀다' 는 다름. 인증 실패·엔진 크래시·예산 초과·스로틀은 **중단**이고,
턴 상한은 채점하되, 모호한 표본만 truncated 로 셈.
"""

from __future__ import annotations

import pytest

from evals import run as runner
from evals.runner import config, invocation, session
from evals.runner.config import (
    SKILLS_DIR,
    MalformedStream,
    RateLimitAbort,
    SessionFailure,
)
from evals.runner.stream import (
    parse_stream,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._stubs import (
    HEALTHY_RATE_LIMIT,
    HEALTHY_RATE_LIMIT_DECOY_FIRST,
    INIT,
    RESULT,
    RESULT_ENGINE_CRASH,
    RESULT_NOT_LOGGED_IN,
    RESULT_OVER_BUDGET,
    RESULT_TURN_CAP,
    _arm_stub,
    _assistant,
    _both_arms,
    _canned_corpus,
    _canned_run,
    _skill_use,
    _stream,
)


@pytest.mark.parametrize(
    "event", [HEALTHY_RATE_LIMIT, HEALTHY_RATE_LIMIT_DECOY_FIRST], ids=["measured", "decoy-first"]
)
def test_a_healthy_rate_limit_event_does_not_abort_the_run(event: dict):
    """THE regression that matters most.

    `_check_rate_limit` reads `status` and nothing else. A "simplification" to any key
    containing "status" would match `overageStatus: "rejected"` and abort every run on a
    perfectly healthy host -- while `uv run pytest` stayed green, because until this test
    existed nothing here executed that function. A gate that aborts a full measurement on
    a normal session is indistinguishable, from the operator's chair, from a rate limit.

    Both key orders are exercised deliberately: the lax scan this guards against reads
    the first matching key, so a single fixture with `status` up front lets the mutation
    survive and the test would attest to a safety it had not checked.
    """
    parsed = parse_stream(_stream(INIT, event, _assistant(_skill_use("vway-kit:vdev")), RESULT))
    assert parsed.fired("vway-kit:vdev")


def test_a_genuinely_throttled_session_aborts_instead_of_scoring_zero():
    """The other half: a real throttle must never be scored as "the skill did not fire",
    because that contaminated 0.0 becomes the baseline (spec 7)."""
    throttled = {
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"},
    }
    with pytest.raises(RateLimitAbort):
        parse_stream(_stream(INIT, throttled, RESULT))

    unknown = {"type": "rate_limit_event", "rate_limit_info": {"rateLimitType": "five_hour"}}
    with pytest.raises(MalformedStream):
        parse_stream(_stream(INIT, unknown, RESULT))


def test_a_skill_that_fires_after_another_tool_is_still_counted():
    """Spec 2: with `--max-turns 3` the agent often runs `ls` first and invokes the skill
    on a later turn. Reading only the first tool_use scores those sessions 0.0 and lands
    the false negative straight in `invoke_rate`."""
    bash = {"type": "tool_use", "name": "Bash", "id": "tu_1", "input": {"command": "ls"}}
    parsed = parse_stream(
        _stream(
            INIT,
            _assistant(bash),
            _assistant({"type": "text", "text": "let me check"}, _skill_use("vway-kit:vdev")),
            RESULT,
        )
    )
    assert parsed.fired("vway-kit:vdev"), "a Skill after another tool_use was missed"
    assert not parsed.fired("vway-kit:doc-sync")


def test_a_truncated_stream_raises_instead_of_reading_as_did_not_fire():
    """A session cut off mid-flight looks EXACTLY like one where nothing fired. Silence
    is the failure this harness exists to prevent, so it is fatal rather than a 0.0."""
    with pytest.raises(MalformedStream):
        parse_stream(_stream(INIT, _assistant(_skill_use("vway-kit:vdev"))))  # no result
    with pytest.raises(MalformedStream):
        parse_stream(_stream(_assistant(_skill_use("vway-kit:vdev")), RESULT))  # no init
    with pytest.raises(MalformedStream):
        parse_stream("{not json}\n")


def test_a_skill_missing_from_a_loaded_plugin_aborts_instead_of_scoring_zero(monkeypatch, tmp_path):
    """One level below the "did the plugin load" check, and the same silent zero.

    If ONE skill's frontmatter stops parsing, that skill is dropped while its siblings
    load. The plugin-count check passes, and the broken skill records a clean 0.00 that
    reads exactly like a description which stopped working -- so the fix would be applied
    to the wrong file.
    """
    init = {"type": "system", "subtype": "init", "skills": ["vway-kit:doc-sync"], "model": "m"}
    _canned_run(monkeypatch, _stream(init, RESULT))
    with pytest.raises(MalformedStream) as caught:
        session.run_session(
            "prompt",
            plugin_dir=SKILLS_DIR.parent,
            cwd=tmp_path,
            config_dir=tmp_path,
            binary="stub",
            max_turns=3,
            model="m",
            skill_id="vway-kit:vdev",
        )
    assert "not among them" in str(caught.value)

    # ...and the same stream with the skill present is scored normally, so the guard is
    # not rejecting everything.
    init["skills"].append("vway-kit:vdev")
    _canned_run(monkeypatch, _stream(init, RESULT))
    parsed = session.run_session(
        "prompt",
        plugin_dir=SKILLS_DIR.parent,
        cwd=tmp_path,
        config_dir=tmp_path,
        binary="stub",
        max_turns=3,
        model="m",
        skill_id="vway-kit:vdev",
    )
    assert parsed.offered("vway-kit:vdev")


@pytest.mark.parametrize(
    "reported",
    [{"model": "some-other-model"}, {}],
    ids=["wrong-model", "field-absent"],
)
def test_the_model_assertion_fails_closed_when_init_does_not_name_the_model(
    monkeypatch, tmp_path, reported
):
    """The model is the widest single influence on a score -- the sister repo
    measured 4/4 on one model and 0/4 on another for the SAME case. `--model` silently
    falling back would therefore produce a full run of plausible numbers about the wrong
    thing.

    Absence has to fail the same way a mismatch does. The guard once read
    `session.model is not None and session.model != model`, so a CLI release that renamed
    or re-nested the field turned the assertion into a no-op -- and no test noticed,
    because the default `INIT` fixture carries no `model` key at all, meaning every other
    test in this file exercised precisely the branch that skipped the check.
    """
    init = {"type": "system", "subtype": "init", "skills": ["vway-kit:vdev"], **reported}
    _canned_run(monkeypatch, _stream(init, RESULT))
    with pytest.raises(MalformedStream) as caught:
        session.run_session(
            "prompt",
            plugin_dir=SKILLS_DIR.parent,
            cwd=tmp_path,
            config_dir=tmp_path,
            binary="stub",
            max_turns=3,
            # 핀에서 읽음. 리터럴로 적으면 재핀한 날 이 요청 모델이 낡은 값이 되고,
            # 그것이 `some-other-model` 과 여전히 달라 테스트는 초록인 채로 남음.
            model=config.MODEL,
            skill_id="vway-kit:vdev",
        )
    assert "not comparable to the baseline" in str(caught.value)


def test_an_unauthenticated_session_aborts_instead_of_scoring_zero():
    """The silent poisoner. Measured: a session with no valid credentials emits a
    well-formed `init` carrying a full skills array, then a well-formed `result` -- so
    every structural check passes and it scores as "the skill did not fire". A run
    spanning hours can outlive its credentials, and the sister repo wrote ten such
    sessions into a baseline before anyone noticed.

    A zero that means "not logged in" is indistinguishable, in `scores.json`, from a
    zero that means "this description is useless". That is the whole failure mode.
    """
    with pytest.raises(SessionFailure) as caught:
        parse_stream(_stream(INIT, RESULT_NOT_LOGGED_IN))
    assert "Not logged in" in str(caught.value), "the operator needs the actual reason"


@pytest.mark.parametrize(
    "result",
    [RESULT_ENGINE_CRASH, RESULT_OVER_BUDGET, {"type": "result", "subtype": "unheard_of"}],
    ids=["engine-crash", "over-budget", "future-subtype"],
)
def test_every_unscorable_result_subtype_aborts_not_only_the_authentication_one(result):
    """The third silent false negative this harness shipped, after `ablation_delta` and
    the fair-chance test. The guard was written against ONE measured failure -- auth
    expiry, which emits `subtype="success"` with `is_error` -- and keyed on exactly that
    pairing. The CLI's enum has five subtypes, three of which it therefore let through as
    ordinary sessions where the skill did not fire.

    An engine crash during a 465-session run cost 0.04 of `invoke_rate` per casualty and,
    worse, landed in the denominator of `truncated` as "had room and declined" -- so the
    one metric whose job is to announce that a score cannot be trusted was itself quieted
    by the same fault. An unrecognised subtype aborts for the same reason: a session this
    harness cannot classify is not evidence about a description.
    """
    with pytest.raises(SessionFailure):
        parse_stream(_stream(INIT, result))


def test_a_turn_capped_session_is_scored_rather_than_aborted():
    """The other side of the same discriminator, and the reason it cannot be `is_error`
    alone: the turn cap sets `is_error` too, yet that session is perfectly scorable --
    the fired Skill event is already in the stream. A guard keyed on `is_error` would
    abort every single measured session and look exactly like a broken CLI.
    """
    parsed = parse_stream(_stream(INIT, _assistant(_skill_use("vway-kit:vdev")), RESULT_TURN_CAP))
    assert parsed.fired("vway-kit:vdev")
    assert parsed.hit_turn_cap()


def test_truncated_counts_only_the_samples_the_turn_cap_made_ambiguous():
    """`truncated` exists to say "this score is partly a measurement of --max-turns".
    That claim only holds for samples where the budget ran out having fired NOTHING; a
    session that fired and then hit the cap answered the question, and counting it would
    inflate the warning until nobody reads it.
    """

    def outcome(**kw):
        return invocation.Outcome(**{"fired": False, "hit_turn_cap": True, **kw})

    assert not outcome(fired=True).cut_before_firing, "a session that fired is not ambiguous"
    assert outcome().cut_before_firing
    assert not outcome(hit_turn_cap=False).cut_before_firing, (
        "a session that ran to completion without firing is a real negative, not a cut one"
    )


def test_truncation_is_a_share_of_the_misses_not_of_every_session():
    """Conditioning is what keeps this from restating `invoke_rate` under another name.

    An unconditional cut rate can never exceed `1 - invoke_rate`, so it falls whenever a
    skill fires more often — which is how `ablation_delta` came to report a number the
    harness already had. Both arms below cut exactly one of their misses; only the
    conditional form says so.
    """
    fired = invocation.Outcome(fired=True, hit_turn_cap=True)
    cut = invocation.Outcome(fired=False, hit_turn_cap=True)
    declined = invocation.Outcome(fired=False, hit_turn_cap=False)

    assert invocation.cut_share_of_misses([cut, declined]) == 0.5
    assert invocation.cut_share_of_misses([fired, fired, cut, declined]) == 0.5, (
        "adding sessions that FIRED must not move a rate about the ones that did not"
    )


def test_truncation_is_null_when_nothing_missed():
    """0/0 is not 0.0. A skill that always fires has no low score needing an excuse, and
    writing 0.0 would claim the cap was measured and found blameless."""
    fired = invocation.Outcome(fired=True, hit_turn_cap=True)
    assert invocation.cut_share_of_misses([fired, fired]) is None


def test_truncated_reads_the_happy_arm_and_truncated_quiet_the_negative_one(monkeypatch, tmp_path):
    """WHICH arm feeds which diagnostic, pinned on inputs built to separate them.

    The runner argues at length (see `measure_skill`) that the arm split is the whole point:
    the SAME cut moves the two gated metrics in opposite directions, so a happy sample
    stopped early drags `invoke_rate` down while a negative sample stopped before the agent
    could over-fire makes `false_fire` look GOOD -- and `false_fire` carries the only live
    absolute threshold in this harness. Crossing the two lines would leave that threshold
    passing on a diagnostic that describes the other arm.

    Nothing held the claim. Swapping the two assignments in `measure_skill` reddened exactly
    one test, `test_measure_skill_records_the_cwd_alongside_the_ratios`, and only by
    accident: its stub fires on every happy prompt, so `truncated` is null there and the
    swap was caught as null-vs-0.0 rather than as a crossed arm. With misses on both arms --
    the state every real measurement is in -- it would have stayed green.
    `truncated_quiet` appeared nowhere in this file except as a constant key in
    `_measurement()`.

    The sister repo records the divergence occurring (harness-tier
    `tests/test_evals.py`): the happy arm counted every turn cap and the negative
    arm counted none, which made the two incomparable and inflated exactly one of them.
    """
    happy_cut = _both_arms(monkeypatch, tmp_path, cut="happy")
    assert (happy_cut["truncated"], happy_cut["truncated_quiet"]) == (1.0, 0.0)

    # The mirror image. Without it, an implementation that fed BOTH metrics from the happy
    # arm would pass the assertion above and the pair would only ever move together.
    negative_cut = _both_arms(monkeypatch, tmp_path, cut="negative")
    assert (negative_cut["truncated"], negative_cut["truncated_quiet"]) == (0.0, 1.0)


def test_the_truncation_warning_fires_per_metric_rather_than_once_for_both(
    monkeypatch, tmp_path, capsys
):
    """The reporting half of the arm split, and until now no test executed the loop at all.

    `_measure_selected` warns per arm because the two warnings say opposite things: a high
    `truncated` means `invoke_rate` is PESSIMISTIC, a high `truncated_quiet` means
    `false_fire` is OPTIMISTIC -- and only the second one qualifies a live threshold. The
    regression the sister repo names (harness-tier `tests/test_evals.py`) is a single
    `if` covering the happy arm, which leaves `false_fire` quietly unchecked while the happy
    warning goes on firing and the code still looks like it warns.

    All three combinations, because two of them cannot tell a crossed mapping from a correct
    one: warning on both arms whenever either is cut passes the happy-only and
    negative-only cases if it is read loosely enough, so the arm that is NOT over the line
    has to be asserted silent.
    """
    combinations = (("happy-", {"happy"}), ("negative-", {"negative"}), ("", {"happy", "negative"}))
    for cut, expected in combinations:
        _canned_corpus(monkeypatch, tmp_path)
        _arm_stub(monkeypatch, cut)
        assert runner.main(["--skill", "vdev"]) == 0
        err = capsys.readouterr().err
        warned = {arm for arm in ("happy", "negative") if f"of the {arm} samples" in err}
        assert warned == expected, f"cut={cut!r} warned about {sorted(warned)}:\n{err}"
        # ...and each warning has to name the metric its own arm qualifies. The score line
        # printed beside it carries both names already, so "so <metric>=" is what separates
        # a real warning from the summary that always mentions them.
        assert ("so invoke_rate=" in err) == ("happy" in expected), err
        assert ("so false_fire=" in err) == ("negative" in expected), err


def test_hitting_the_turn_cap_is_not_qualified_by_a_tool_call_threshold():
    """Regression guard for a retired metric (2026-07-19, 45 measured sessions).

    `truncated` once required a capped session to have made fewer than
    `FIRE_BY_TOOL_CALL = 3` tool calls. That conjunction is unsatisfiable: exhausting the
    turn budget requires acting on every turn, so `hit_turn_cap` implies
    `tool_calls >= max_turns`, and no threshold at or below the budget can ever fail. The
    metric read 0.00 on all nine skills — indistinguishable from "never truncated".
    """
    assert not hasattr(runner, "FIRE_BY_TOOL_CALL"), (
        "a tool-call threshold cannot qualify the turn cap while both are the same budget"
    )
    assert not hasattr(invocation.Outcome(fired=False, hit_turn_cap=True), "had_a_fair_chance")


def test_a_killed_session_is_read_up_to_where_it_stopped():
    """A session the runner killed at SESSION_TIMEOUT_S is read as far as it got: a `Skill`
    call already in the stream is a firing nothing later can undo, and the killed process's
    half-written last line is dropped rather than read as a malformed stream. Read whole,
    it would still raise -- only the runner's own kill earns the tolerance."""
    partial = _stream(INIT, _assistant(_skill_use("vway-kit:vdev"))) + '{"type": "assis'
    parsed = parse_stream(partial, killed=True)
    assert parsed.fired("vway-kit:vdev")
    assert parsed.timed_out and not parsed.saw_result
    with pytest.raises(MalformedStream):
        parse_stream(partial)


def test_a_killed_session_that_had_not_fired_counts_as_cut():
    """Not fired yet when killed is the same ambiguity as out of turns: it might have fired
    one turn later. It lands in `truncated` beside the turn-capped sessions instead of
    scoring as a decided miss."""
    parsed = parse_stream(_stream(INIT), killed=True)
    assert not parsed.fired("vway-kit:vdev")
    assert parsed.cut_short()
