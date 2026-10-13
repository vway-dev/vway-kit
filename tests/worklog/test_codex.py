"""Codex rollout → 활동 구간. 턴 경계는 `task_started`·`task_complete`."""

from datetime import timedelta

from scripts.worklog import codex_session, total
from tests.worklog._helpers import at, everywhere, write_jsonl


def event(t, kind):
    return {"type": "event_msg", "timestamp": at(t), "payload": {"type": kind}}


def context(t, cwd="/repo"):
    return {"type": "turn_context", "timestamp": at(t), "payload": {"cwd": cwd}}


def call(t, call_id, name):
    return {
        "type": "response_item",
        "timestamp": at(t),
        "payload": {"type": "function_call", "name": name, "call_id": call_id},
    }


def output(t, call_id):
    return {
        "type": "response_item",
        "timestamp": at(t),
        "payload": {"type": "function_call_output", "call_id": call_id},
    }


def minutes(path, inside=everywhere):
    return total(codex_session(path, inside)) / timedelta(minutes=1)


def test_turns_count_fully_and_gaps_cap(tmp_path):
    path = write_jsonl(
        tmp_path / "r.jsonl",
        [
            context(0),
            event(0, "task_started"),
            event(40, "task_complete"),
            event(100, "task_started"),
            event(102, "task_complete"),
        ],
    )
    assert minutes(path) == 40 + 15 + 2


def test_request_user_input_is_capped(tmp_path):
    path = write_jsonl(
        tmp_path / "r.jsonl",
        [
            context(0),
            event(0, "task_started"),
            call(1, "c1", "request_user_input"),
            output(61, "c1"),
            event(62, "task_complete"),
        ],
    )
    assert minutes(path) == 1 + 15 + 1


def test_error_stops_until_next_turn(tmp_path):
    path = write_jsonl(
        tmp_path / "r.jsonl",
        [
            context(0),
            event(0, "task_started"),
            event(5, "error"),
            event(300, "task_started"),
            event(301, "task_complete"),
        ],
    )
    assert minutes(path) == 5 + 1


def test_cwd_comes_from_turn_context(tmp_path):
    # 0~10 은 /other 턴(제외), 10→11 대기는 시작 기록의 cwd 가 /other 라 제외, 11~20 은 /repo.
    path = write_jsonl(
        tmp_path / "r.jsonl",
        [
            context(0, "/other"),
            event(0, "task_started"),
            event(10, "task_complete"),
            context(11),
            event(11, "task_started"),
            event(20, "task_complete"),
        ],
    )
    assert minutes(path, inside=lambda cwd: cwd == "/repo") == 9
