"""Claude Code transcript → 활동 구간. 턴 안은 전부, 사람 대기는 15분, 정지는 0분."""

from datetime import timedelta
from pathlib import Path

from scripts.worklog import claude_session, total
from tests.worklog._helpers import (
    api_error,
    attachment,
    everywhere,
    m,
    notice,
    prompt,
    said,
    tool_result,
    tool_use,
    write_jsonl,
)


def minutes(path: Path, waits=None, inside=everywhere) -> float:
    return total(claude_session(path, inside, waits or [])) / timedelta(minutes=1)


def test_long_gap_inside_a_turn_counts_fully(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [prompt(0), tool_use(1, "a"), tool_result(51, "a"), said(52)],
    )
    assert minutes(path) == 52


def test_wait_between_turns_is_capped_at_fifteen(tmp_path):
    path = write_jsonl(tmp_path / "s.jsonl", [prompt(0), said(10), prompt(70), said(75)])
    assert minutes(path) == 10 + 15 + 5


def test_short_wait_between_turns_counts_fully(tmp_path):
    path = write_jsonl(tmp_path / "s.jsonl", [prompt(0), said(10), prompt(14), said(15)])
    assert minutes(path) == 15


def test_turn_closes_only_on_end_turn_chunk(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl", [prompt(0), said(5, stop=None), said(30), prompt(40), said(41)]
    )
    assert minutes(path) == 30 + 10 + 1


def test_attachments_after_end_turn_stay_idle(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [prompt(0), said(10), attachment(200), attachment(299), prompt(300), said(301)],
    )
    assert minutes(path) == 10 + 15 + 1


def test_ask_user_question_is_capped(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [prompt(0), tool_use(1, "q", "AskUserQuestion"), tool_result(61, "q"), said(62)],
    )
    assert minutes(path) == 1 + 15 + 1


def test_permission_wait_is_capped_from_the_prompt(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl", [prompt(0), tool_use(1, "b"), tool_result(61, "b"), said(62)]
    )
    assert minutes(path, waits=[m(2)]) == 2 + 15 + 1


def test_background_counts_until_its_notification(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [
            prompt(0),
            tool_use(1, "bg"),
            tool_result(2, "bg", {"backgroundTaskId": "b1"}),
            said(3),
            notice(90, "b1"),
            said(91),
        ],
    )
    assert minutes(path) == 91


def test_async_agent_counts_as_background(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [
            prompt(0),
            tool_use(1, "ag", "Agent"),
            tool_result(2, "ag", {"isAsync": True, "agentId": "a9"}),
            said(3),
            notice(40, "a9"),
            said(41),
        ],
    )
    assert minutes(path) == 41


def test_background_without_notification_runs_to_session_end(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [
            prompt(0),
            tool_use(1, "bg"),
            tool_result(2, "bg", {"backgroundTaskId": "b1"}),
            said(3),
            attachment(50),
        ],
    )
    assert minutes(path) == 50


def test_rate_limit_stop_counts_zero_until_resume(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl", [prompt(0), said(10, error="rate_limit"), prompt(200), said(205)]
    )
    assert minutes(path) == 10 + 5


def test_retry_gaps_count_but_exhausted_retry_is_a_stop(tmp_path):
    # 0→1→3 은 턴 안(재시도 중). 3→120 은 재시도 뒤 프롬프트라 정지(0분). 120→121 새 턴.
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [prompt(0), api_error(1), api_error(3), prompt(120), said(121)],
    )
    assert minutes(path) == 3 + 1


def test_interrupt_closes_the_turn(tmp_path):
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [prompt(0), prompt(5, "[Request interrupted by user]"), prompt(100), said(101)],
    )
    assert minutes(path) == 5 + 15 + 1


def test_records_outside_the_worktree_are_dropped(tmp_path):
    # 0~10 턴은 /other 에서 열려 제외. said(10) 부터 cwd 는 /repo(헬퍼 기본값) —
    # 대기 10→12(2분)와 턴 12→20(8분)은 시작 기록이 안이라 셈.
    path = write_jsonl(
        tmp_path / "s.jsonl", [prompt(0, cwd="/other"), said(10), prompt(12), said(20)]
    )
    assert minutes(path, inside=lambda cwd: cwd == "/repo") == 2 + 8


def test_broken_lines_are_skipped(tmp_path):
    path = write_jsonl(tmp_path / "s.jsonl", [prompt(0), said(10)])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("{not json\n\n")
    assert minutes(path) == 10


def test_local_command_does_not_open_a_turn(tmp_path):
    # /model 같은 로컬 명령 뒤 4시간 자리 비움 — 에이전트가 안 움직였으니 턴 사이 대기(15분).
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [
            prompt(0),
            said(10),
            prompt(15, "<command-name>/model</command-name>"),
            prompt(16, "<local-command-stdout>Set model</local-command-stdout>"),
            attachment(255),
            prompt(255),
            said(256),
        ],
    )
    assert minutes(path) == 10 + 15 + 1


def test_slash_command_opens_a_turn_once_the_agent_answers(tmp_path):
    # 스킬을 부르는 슬래시 명령은 에이전트가 이어서 일하므로 그 명령 시각부터 턴.
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [
            prompt(0),
            said(10),
            prompt(15, "<command-name>/vdev</command-name>"),
            said(40, stop=None),
            said(50),
        ],
    )
    assert minutes(path) == 10 + 5 + 35


def test_compact_summary_is_not_a_prompt(tmp_path):
    summary = prompt(20, "This session is being continued")
    summary["isCompactSummary"] = True
    path = write_jsonl(tmp_path / "s.jsonl", [prompt(0), said(10), summary, prompt(300), said(301)])
    assert minutes(path) == 10 + 15 + 1


def test_queued_notification_closes_the_background_span(tmp_path):
    # 턴 도중 끝난 작업의 알림은 user 기록이 아니라 queue-operation·attachment 에 남음(실측).
    queued = {
        "type": "queue-operation",
        "operation": "enqueue",
        "timestamp": "",
        "content": "<task-notification>\n<task-id>b1</task-id>\n</task-notification>",
    }
    queued["timestamp"] = prompt(40)["timestamp"]
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [
            prompt(0),
            tool_use(1, "bg"),
            tool_result(2, "bg", {"backgroundTaskId": "b1"}),
            tool_use(3, "x"),
            queued,
            tool_result(60, "x"),
            said(61),
            attachment(500),
        ],
    )
    assert minutes(path) == 61


def test_attachment_notification_closes_the_background_span(tmp_path):
    note = attachment(30)
    note["attachment"] = {
        "type": "queued_command",
        "prompt": "<task-notification>\n<task-id>b1</task-id>\n</task-notification>",
    }
    path = write_jsonl(
        tmp_path / "s.jsonl",
        [
            prompt(0),
            tool_use(1, "bg"),
            tool_result(2, "bg", {"backgroundTaskId": "b1"}),
            said(3),
            note,
            attachment(500),
        ],
    )
    assert minutes(path) == 30
