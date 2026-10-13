"""러너 방어 — 타임아웃·트리 킬·표본 크기 검증·레이트리밋 회복.

시간 초과한 세션은 파이프를 비우기 **전에** 트리를 죽임(손자까지). 다른 표본
크기의 탐침은 baseline 을 덮어쓸 수 없음.
"""

from __future__ import annotations

import json
import subprocess
import threading

import pytest

from evals import run as runner
from evals.runner import case_corpus, config, invocation, session, stream
from evals.runner.config import (
    SKILLS_DIR,
    MalformedStream,
    RateLimitAbort,
)
from evals.runner.stream import (
    parse_stream,
)
from tests.eval_harness._presuppositions import (
    _arm_kwargs,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._stubs import (
    INIT,
    RESULT,
    _assistant,
    _canned_measurements,
    _measurement,
    _skill_use,
    _stream,
)


def test_a_rate_limit_warning_is_not_a_stop_signal():
    """`allowed_warning` and its neighbours ride on a session whose request SUCCEEDED.
    Treating every status that is not on a short allowlist as fatal kills any run started
    late in the five-hour window on its first session -- a full-run abort caused by a healthy
    session, which from the operator's chair is indistinguishable from a real throttle.
    """
    for status in ("allowed_warning", "allowed_warning_overage", "warning"):
        event = {"type": "rate_limit_event", "rate_limit_info": {"status": status}}
        fired = _assistant(_skill_use("vway-kit:vdev"))
        assert parse_stream(_stream(INIT, event, fired, RESULT)).fired("vway-kit:vdev"), status


def test_a_null_skill_input_is_skipped_rather_than_fatal():
    """An aborted Skill call serialises as `{"skill": null}`. Raising on it discards a whole
    session that parsed fine otherwise -- and the discard is fatal, so one aborted call in a
    520-session run ends the run. The tool call still counts: it happened.
    """
    aborted = {"type": "tool_use", "name": "Skill", "id": "tu_1", "input": {"skill": None}}
    parsed = parse_stream(
        _stream(INIT, _assistant(aborted), _assistant(_skill_use("vway-kit:vdev")), RESULT)
    )
    assert parsed.fired("vway-kit:vdev")
    assert parsed.tool_calls == 2, "an aborted call is still a tool call"

    # A Skill block whose `input` is missing entirely is the same aborted event one step
    # earlier; a non-string skill is not, and still stops the run.
    no_input = {"type": "tool_use", "name": "Skill", "id": "tu_2"}
    assert parse_stream(_stream(INIT, _assistant(no_input), RESULT)).fired_skills == []
    with pytest.raises(MalformedStream):
        bad = {"type": "tool_use", "name": "Skill", "id": "tu_3", "input": {"skill": 7}}
        parse_stream(_stream(INIT, _assistant(bad), RESULT))


def test_reps_below_one_is_rejected():
    """argparse, not a later assertion: `--reps 0` measures nothing and would write an entry
    with n=0 that every downstream check divides by."""
    with pytest.raises(SystemExit):
        runner.main(["--all", "--dry-run", "--probe", "--reps", "0"])
    with pytest.raises(SystemExit):
        runner.main(["--all", "--dry-run", "--probe", "--reps", "-3"])
    assert runner.main(["--skill", "vdev", "--dry-run", "--probe", "--reps", "2"]) == 0


def test_a_probe_at_another_sample_size_cannot_overwrite_the_baseline(monkeypatch, tmp_path):
    """`--reps` advertises a probe usage in its own help (`--skill X --reps 15`), and that
    command, unguarded, does two destructive things at once: replace the skill's real entry
    with probe data, and -- where scores.json still carries one -- stamp `reps: 15` over a
    file header a gate asserts equals cases.yaml. Following the documentation loses the
    baseline AND turns the suite red.

    The no-write path exists for exactly that usage, and `--reps` requires
    it. A probe is a question; a measurement is a record; the operator says which.

    The header is gone, but the first half of the damage is not: a probe's entry would still
    replace the real one, and `test_the_committed_baseline_round_trips` would then find a
    `reps` the corpus does not declare. This guard refuses the command; that check refuses
    the artifact. Only the second survives a baseline edited by hand.
    """
    with pytest.raises(SystemExit):
        runner.main(["--skill", "vdev", "--dry-run", "--reps", "15"])

    # And a probe that runs writes nothing at all -- not the entry, not the header.
    before = {"skills": {"vdev": _measurement()}}
    scores_path, _ = _canned_measurements(
        monkeypatch, tmp_path, before, [_measurement(invoke_hits=1, invoke_n=15)]
    )
    args = runner.build_parser().parse_args(["--skill", "vdev", "--probe", "--reps", "15"])
    assert runner.measure(args) == 0
    assert json.loads(scores_path.read_text(encoding="utf-8")) == before, (
        "a probe left a mark on the committed baseline"
    )


def test_lost_to_records_which_neighbour_won_the_prompt(monkeypatch, tmp_path):
    """A miss says the skill did not fire. `lost_to` says what fired instead, and that is the
    difference between "reword the description" and "the boundary with a sibling is wrong".
    """

    def _stub_session(prompt: str, **kwargs: object):
        fired = ["vway-kit:integration"] if prompt == "happy" else []
        return stream.ParsedSession(
            loaded_skills=["vway-kit:playwright-scaffold", "vway-kit:integration"],
            fired_skills=fired,
            saw_result=True,
            result_subtype="success",
        )

    monkeypatch.setattr(session, "run_session", _stub_session)
    entry = invocation.measure_skill(
        "playwright-scaffold",
        {"happy": [{"prompt": "happy"}], "negative": [{"prompt": "neg"}]},
        reps=2,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=3,
        model=config.MODEL,
    )
    assert entry["invoke_hits"] == 0
    assert entry["lost_to"] == {"integration": 2}


def test_a_timed_out_session_kills_the_tree_before_draining_the_pipes(monkeypatch, tmp_path):
    """`subprocess.run(timeout=)` kills only the direct child and then drains the pipes with
    an UNBOUNDED `communicate()`. A surviving grandchild still holding the inherited write
    handles blocks that read forever -- the hang guard becomes the hang, and this module has
    its own Windows evidence that children outlive the kill.

    Order is the assertion. Draining first is the bug; killing the tree first is what makes
    the drain terminate, because with every writer dead the pipes close.
    """
    log: list[str] = []

    class _Hanging:
        pid = 4242
        returncode = None

        def communicate(self, timeout=None):
            if timeout is not None:
                log.append("wait")
                raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
            log.append("drain")
            return "", ""

    monkeypatch.setattr(session.subprocess, "Popen", lambda *a, **k: _Hanging())
    monkeypatch.setattr(session, "_kill_process_tree", lambda proc: log.append("kill-tree"))

    with pytest.raises(subprocess.TimeoutExpired):
        session.run_session(
            "prompt",
            plugin_dir=SKILLS_DIR.parent,
            cwd=tmp_path,
            config_dir=tmp_path,
            binary="stub",
            max_turns=3,
            model=config.MODEL,
            skill_id="vway-kit:vdev",
        )
    assert log == ["wait", "kill-tree", "drain"], log


def test_the_tree_kill_reaches_the_grandchildren_on_both_platforms(monkeypatch):
    """The whole point of the change is the TREE. `proc.kill()` alone on Windows leaves the
    node processes the CLI spawned holding the pipe, which is the state the ordering above
    cannot help with.
    """
    calls: list[object] = []

    class _Proc:
        pid = 4242

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(session.os, "name", "nt")
    monkeypatch.setattr(session.subprocess, "run", lambda argv, **k: calls.append(argv))
    session._kill_process_tree(_Proc())
    assert calls == [["taskkill", "/F", "/T", "/PID", "4242"]], calls

    calls.clear()
    monkeypatch.setattr(session.os, "name", "posix")
    monkeypatch.setattr(
        session.os, "killpg", lambda pid, sig: calls.append((pid, sig)), raising=False
    )
    session._kill_process_tree(_Proc())
    assert calls == [(4242, session._POSIX_KILL_SIGNAL)], calls

    # A process group that has already exited must not turn the timeout path into a crash.
    calls.clear()

    def _gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(session.os, "killpg", _gone, raising=False)
    session._kill_process_tree(_Proc())
    assert calls == ["kill"]


def test_the_suite_cannot_spawn_a_real_session(tmp_path):
    """The guard itself, asserted rather than assumed.

    `no_real_sessions` is autouse in this package's conftest, so every other test in the
    package silently depends on it.
    An autouse fixture that quietly stopped applying -- renamed, moved out of scope, or made
    to patch a reference the runner no longer uses -- would leave the suite exactly as it
    was before it existed, and the first symptom would be a CI run that got slow and started
    burning rate-limit budget.
    """
    with pytest.raises(AssertionError, match="model-free"):
        session.run_session(
            "prompt",
            plugin_dir=SKILLS_DIR.parent,
            cwd=tmp_path,
            config_dir=tmp_path,
            binary="stub-claude",
            max_turns=1,
            model=config.MODEL,
            skill_id="vway-kit:vdev",
        )
    # The other door. `_kill_process_tree` reaches for `subprocess.run`, so a refactor that
    # moved the spawn back onto it would otherwise walk straight past the guard.
    with pytest.raises(AssertionError, match="model-free"):
        session.subprocess.run(["claude", "-p", "prompt"])


def test_an_arm_returns_its_outcomes_in_case_order(monkeypatch, tmp_path):
    """The guarantee `pool.map` gives for free, reassembled by hand here.

    It matters because nothing downstream could notice it breaking: `invoke_rate`,
    `false_fire` and `truncated` are all order-independent sums, so a shuffled list produces
    every ratio correctly while `lost_to` and the per-case progress log attribute one
    prompt's behaviour to another. A wrong diagnosis, arrived at from right numbers.

    The sessions are released in REVERSE, so completion order is exactly the opposite of
    submission order and an implementation that returned results as they landed would come
    back reversed rather than merely unlucky. Each session parks on its own gate and opens
    the previous one, which needs every worker resident at once -- hence `concurrency=n`.
    """
    n = 6
    gates = [threading.Event() for _ in range(n)]

    def _stub_session(prompt: str, **_: object):
        index = int(prompt)
        assert gates[index].wait(timeout=30), "the reverse-release chain stalled"
        if index:
            gates[index - 1].set()
        # The sibling name carries the case index back out: `Outcome.others` is the one
        # field that survives per session, so the returned list can be compared with the
        # input positionally rather than by a count that a shuffle would leave intact.
        return stream.ParsedSession(
            loaded_skills=["vway-kit:vdev"],
            fired_skills=[f"vway-kit:sibling{index}"],
            saw_result=True,
            result_subtype="success",
        )

    monkeypatch.setattr(session, "run_session", _stub_session)
    gates[-1].set()
    results = invocation.run_arm(
        [case_corpus.Case(str(index), None) for index in range(n)],
        **_arm_kwargs(tmp_path, concurrency=n),
    )
    assert [outcome.others for outcome in results] == [(f"sibling{index}",) for index in range(n)]


def test_a_rate_limit_stops_the_arm_the_moment_the_window_shuts(monkeypatch, tmp_path):
    """The window is shut, so every session still queued would be refused the same way --
    and a refused session is not a cheap no-op. It is a real spawn, and scoring one as "the
    skill did not fire" is the poisoned baseline the rate-limit stop exists to prevent.

    The assertion is WHEN the abort surfaces, not how many sessions ran, and that is the
    only thing separating this from the `pool.map` shape it replaced. `map` is better than
    its reputation here: its result iterator cancels the not-yet-started futures in a
    `finally` when the exception propagates out of `list()`, so the queue does not run to
    the end. What it cannot do is raise EARLY. The iterator yields in SUBMISSION order, so
    an abort on session 5 is withheld until sessions 0-4 have finished -- and at
    concurrency 8 every one of those completions frees a worker that starts another
    session against the closed window. That is the burn, and it is invisible to a count
    taken afterwards.

    So: session 0 is parked and never released before the assertion runs. If the abort can
    only reach the caller behind session 0's result, `blocker_done` is necessarily set by
    the time we look. With the abort judged as each session lands it is necessarily not.
    No timing threshold, no sleep -- the two implementations differ in whether an event has
    been set at all.
    """
    calls: list[str] = []
    lock = threading.Lock()
    release = threading.Event()
    blocker_started = threading.Event()
    blocker_done = threading.Event()

    def _stub_session(prompt: str, **_: object):
        with lock:
            calls.append(prompt)
        if prompt == "p1":
            # Held until session 0 is demonstrably in flight, so "0 has not finished" is a
            # statement about a session that started rather than one still queued.
            assert blocker_started.wait(timeout=10), "session 0 never started"
            raise RateLimitAbort("five-hour window exhausted")
        if prompt == "p0":
            blocker_started.set()
        # The hang guard is what keeps a regression from wedging the suite: `release` is
        # only ever set by the `finally` below, which runs after the assertions.
        release.wait(timeout=10)
        if prompt == "p0":
            blocker_done.set()
        return stream.ParsedSession(
            loaded_skills=["vway-kit:vdev"],
            fired_skills=["vway-kit:vdev"],
            saw_result=True,
            result_subtype="success",
        )

    monkeypatch.setattr(session, "run_session", _stub_session)
    try:
        with pytest.raises(RateLimitAbort):
            invocation.run_arm(
                [case_corpus.Case(f"p{index}", None) for index in range(10)],
                **_arm_kwargs(tmp_path, concurrency=2),
            )
        assert not blocker_done.is_set(), (
            "the abort was withheld until an earlier-submitted session finished -- at "
            "concurrency 8 that wait is what starts fresh sessions against a shut window"
        )
        # And the caller is not made to wait on the sessions already in flight either:
        # `shutdown(wait=True)` would block here for up to SESSION_TIMEOUT_S apiece, which
        # is time stolen from the per-skill save a rate-limit stop exists to protect.
        assert not release.is_set(), "run_arm returned only after the parked session ended"
        # Secondary, and deliberately loose: the two workers hold p0 and p1, so at most one
        # further session can have been picked up before the pool was shut down.
        assert len(calls) <= 3, calls
    finally:
        release.set()


def test_the_rate_limit_recovery_names_the_remaining_skills_as_flags(monkeypatch, tmp_path, capsys):
    """ "Re-run without --all" is wrong advice for an interrupted full run: the remaining
    skills' entries still carry matching shas, so the incremental default skips them and
    reports every score current. The operator has to be handed the actual commands.
    """
    _canned_measurements(
        monkeypatch,
        tmp_path,
        {"skills": {}},
        [_measurement(), _measurement(), RateLimitAbort("five-hour window exhausted")],
    )
    assert runner.main(["--all"]) == 3
    err = capsys.readouterr().err
    assert "--skill integration" in err, err
    assert "--skill harness-authoring" in err, err
    assert "--skill vdev" not in err, "an already-measured skill must not be re-run"


def test_a_timed_out_session_names_its_case_and_its_record(monkeypatch, tmp_path, capsys):
    """The timeout still stops the run, but not anonymously: a bare "a session exceeded
    300s" left two full runs unable to say which case hung. The log names the arm, case
    and rep, and the record `run_session` kept (`test_diagnose.py` covers the record)."""

    def _stub_session(prompt: str, **_: object):
        raise subprocess.TimeoutExpired(
            cmd="claude",
            timeout=config.SESSION_TIMEOUT_S,
            output='{"partial": 1}\n',
            stderr="e\n  record: /runs/vdev-happy-1-r1.json",
        )

    monkeypatch.setattr(session, "run_session", _stub_session)
    with pytest.raises(subprocess.TimeoutExpired):
        invocation.run_arm([case_corpus.Case("hang here", None)], **_arm_kwargs(tmp_path))
    err = capsys.readouterr().err
    assert "happy[1] rep 1/1" in err and "hang here" in err, err
    assert f"TIMEOUT after {config.SESSION_TIMEOUT_S}s" in err, err
    assert "record: /runs/vdev-happy-1-r1.json" in err, err
