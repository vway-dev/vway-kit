"""진단 기록 — 채점 못 한 세션이 실행 뒤에도 원인을 남기는가.

요약·트랜스크립트·stderr 세 파일, 재기록의 비덮어쓰기, 실행별 디렉터리를 잼.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from evals.runner import case_corpus, config, diagnose, invocation, session, stream
from tests.eval_harness._presuppositions import _arm_kwargs


@pytest.fixture
def runs_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnose, "RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


def _raw(text="{}\n", err="", *, timed_out=False, elapsed=1.0):
    return session.Raw(text=text, err=err, returncode=None, elapsed=elapsed, timed_out=timed_out)


def _record(raw, parsed, **overrides):
    kwargs = dict(
        skill="vdev",
        arm="happy",
        index=2,
        rep=1,
        prompt="p",
        fixture=None,
        reason=diagnose.TIMEOUT,
    )
    kwargs.update(overrides)
    return diagnose.record(raw, parsed, **kwargs)


def _sibling(path, suffix):
    return path.with_name(path.name.removesuffix(".json") + suffix)


def test_a_record_keeps_summary_transcript_and_stderr(runs_dir):
    parsed = stream.ParsedSession(tool_calls=3, last_tool={"name": "Bash", "input": {"c": "ls"}})
    raw = _raw("line\r\n", "\n\noops\n", timed_out=True, elapsed=config.SESSION_TIMEOUT_S)
    path = _record(raw, parsed)
    assert path.parent == runs_dir / diagnose.STAMP
    assert path.name == "vdev-happy-2-r1.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["reason"] == "timeout"
    assert summary["timed_out"] is True
    assert summary["timeout_s"] == config.SESSION_TIMEOUT_S
    assert summary["elapsed_s"] == config.SESSION_TIMEOUT_S
    assert summary["tool_calls"] == 3
    assert summary["last_tool"] == {"name": "Bash", "input": '{"c": "ls"}'}
    assert summary["stderr_tail"] == ["oops"]
    assert _sibling(path, ".jsonl").read_bytes() == b"line\r\n"
    assert _sibling(path, ".stderr.txt").read_text(encoding="utf-8") == "\n\noops\n"


def test_a_session_that_never_parsed_still_records(runs_dir):
    path = _record(_raw("", "boom"), None, reason=diagnose.NO_INIT)
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["reason"] == "no_init"
    assert summary["tool_calls"] is None and summary["last_tool"] is None


def test_a_long_tool_input_is_clipped(runs_dir):
    parsed = stream.ParsedSession(last_tool={"name": "Write", "input": {"t": "x" * 1000}})
    summary = json.loads(_record(_raw(), parsed).read_text(encoding="utf-8"))
    clipped = summary["last_tool"]["input"]
    assert len(clipped) == diagnose.INPUT_LIMIT + 3 and clipped.endswith("...")


def test_a_second_record_of_the_same_session_never_overwrites_the_first(runs_dir):
    first = _record(_raw("first"), None)
    second = _record(_raw("second"), None)
    assert first != second
    assert second.name == "vdev-happy-2-r1.n2.json"
    assert _sibling(first, ".jsonl").read_text(encoding="utf-8") == "first"
    assert _sibling(second, ".jsonl").read_text(encoding="utf-8") == "second"


def test_each_process_writes_its_own_run_directory():
    """같은 UTC 초에 시작한 두 실행이 디렉터리 하나를 두고 stem 경합하지 않게."""
    assert diagnose.STAMP.endswith(f"-{os.getpid()}")


def test_last_name_reads_none_when_no_tool_ran():
    assert diagnose.last_name(stream.ParsedSession()) == "none"
    assert diagnose.last_name(None) == "none"


def test_the_stream_parser_keeps_the_last_tool_call():
    text = "\n".join(
        json.dumps(e)
        for e in [
            {"type": "system", "subtype": "init", "model": "m", "skills": []},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "a"}},
                    ]
                },
            },
            {"type": "result", "subtype": "success"},
        ]
    )
    assert stream.parse_stream(text).last_tool == {"name": "Read", "input": {"file_path": "a"}}


def test_a_stream_without_init_raises_no_init():
    with pytest.raises(stream.NoInit):
        stream.parse_stream(json.dumps({"type": "result", "subtype": "success"}))


# ------------------------------------------------------- run_session·run_arm 연결
#
# 위는 기록 자체, 아래는 채점 못 한 세션이 실제로 기록에 닿는지 — `run_session` 이 사유를 가르고
# `run_arm` 이 케이스 맥락을 붙임.

SKILL = "vway-kit:vdev"
RESULT = {"type": "result", "subtype": "success"}


def _ev(event: dict) -> str:
    return json.dumps(event)


def _init(skills=(SKILL,)) -> str:
    return _ev({"type": "system", "subtype": "init", "model": config.MODEL, "skills": list(skills)})


def _tool(name: str) -> str:
    block = {"type": "tool_use", "name": name, "input": {"command": "ls"}}
    return _ev({"type": "assistant", "message": {"content": [block]}})


def _popen(monkeypatch, out: str, err: str = "", *, hang: bool = False) -> None:
    """A process that prints `out`/`err`; with `hang`, its first bounded wait times out the way a
    stuck session does, and the drain after the kill returns what it had streamed."""

    class _Process:
        returncode = 1
        pid = 1234

        def __init__(self):
            self.waits = 0

        def communicate(self, timeout=None):
            self.waits += 1
            if hang and self.waits == 1:
                raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
            return out, err

    monkeypatch.setattr(session.subprocess, "Popen", lambda *a, **k: _Process())
    monkeypatch.setattr(session, "_kill_process_tree", lambda proc: None)


def _keeper():
    seen: list[tuple[session.Raw, stream.ParsedSession | None, str]] = []

    def keep(raw, parsed, reason):
        seen.append((raw, parsed, reason))
        return diagnose.RUNS_DIR / f"{reason}.json"

    return seen, keep


def _run(tmp_path, keep):
    return session.run_session(
        "p",
        plugin_dir=tmp_path,
        cwd=tmp_path,
        config_dir=tmp_path,
        binary="claude",
        max_turns=config.DEFAULT_MAX_TURNS,
        model=config.MODEL,
        skill_id=SKILL,
        on_unscored=keep,
    )


@pytest.mark.parametrize(
    ("lines", "reason"),
    [
        ([], diagnose.NO_INIT),
        ([_ev(RESULT)], diagnose.NO_INIT),
        ([_init(skills=()), _ev(RESULT)], diagnose.NO_INIT),
        ([_init(skills=("vway-kit:other",)), _ev(RESULT)], diagnose.MISSING_SKILL),
        ([_init(), _ev({**RESULT, "is_error": True, "result": "Not logged in"})], diagnose.ERRORED),
    ],
    ids=["empty", "no-init", "plugin-not-loaded", "skill-not-offered", "session-failed"],
)
def test_an_unscorable_session_is_recorded_and_named(
    monkeypatch, tmp_path, runs_dir, lines, reason
):
    _popen(monkeypatch, "".join(line + "\n" for line in lines), "why")
    seen, keep = _keeper()
    with pytest.raises(config.EvalError) as caught:
        _run(tmp_path, keep)
    assert [r for _, _, r in seen] == [reason]
    assert seen[0][0].err == "why" and not seen[0][0].timed_out
    assert f"record: {diagnose.RUNS_DIR / f'{reason}.json'}" in str(caught.value)


def test_a_kill_before_init_is_a_recorded_timeout(monkeypatch, tmp_path, runs_dir):
    _popen(monkeypatch, "", "stuck", hang=True)
    seen, keep = _keeper()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        _run(tmp_path, keep)
    assert [(r, raw.timed_out) for raw, _, r in seen] == [(diagnose.TIMEOUT, True)]
    assert f"record: {diagnose.RUNS_DIR / 'timeout.json'}" in caught.value.stderr


def test_a_kill_after_init_is_recorded_and_still_scored(monkeypatch, tmp_path, runs_dir):
    _popen(monkeypatch, f'{_init()}\n{_tool("Bash")}\n{{"half', hang=True)
    seen, keep = _keeper()
    parsed = _run(tmp_path, keep)
    assert parsed.timed_out and diagnose.last_name(parsed) == "Bash"
    assert [r for _, _, r in seen] == [diagnose.TIMEOUT]
    assert parsed.record == diagnose.RUNS_DIR / "timeout.json"


def test_a_scored_timeout_names_its_record_on_the_console(monkeypatch, tmp_path, runs_dir, capsys):
    _popen(monkeypatch, f'{_init()}\n{_tool("Bash")}\n{{"half', hang=True)
    (outcome,) = invocation.run_arm([case_corpus.Case("p", None)], **_arm_kwargs(tmp_path))
    assert outcome.cut_before_firing
    err = capsys.readouterr().err
    assert f"killed at {config.SESSION_TIMEOUT_S}s after 1 tool calls, last Bash" in err, err
    (record,) = runs_dir.rglob("vdev-happy-1-r1.json")
    assert str(record) in err, err
    assert json.loads(record.read_text(encoding="utf-8"))["reason"] == diagnose.TIMEOUT


def test_a_record_that_cannot_be_written_keeps_the_original_failure(
    monkeypatch, tmp_path, runs_dir
):
    _popen(monkeypatch, "")

    def broken(*_a, **_k):
        raise OSError("read-only")

    monkeypatch.setattr(diagnose, "record", broken)
    with pytest.raises(config.MalformedStream, match="empty stream") as caught:
        invocation.run_arm([case_corpus.Case("p", None)], **_arm_kwargs(tmp_path))
    assert "record:" not in str(caught.value)
