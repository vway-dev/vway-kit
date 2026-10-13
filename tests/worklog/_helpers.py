"""transcript 픽스처 — 실제 레코드 모양 중 판독이 읽는 필드만."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

# 과거 고정 — measure 는 착수 뒤에 고쳐진 transcript 만 읽으므로 픽스처 파일의 mtime(지금)이
# 언제나 착수보다 뒤여야 함.
T0 = datetime(2026, 1, 7, 5, 0, tzinfo=UTC)
CWD = "/repo"


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def m(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def prompt(t: float, text: str = "해 줘", cwd: str = CWD) -> dict:
    return {"type": "user", "timestamp": at(t), "cwd": cwd, "message": {"content": text}}


def notice(t: float, task_id: str) -> dict:
    text = f"<task-notification>\n<task-id>{task_id}</task-id>\n</task-notification>"
    return {"type": "user", "timestamp": at(t), "cwd": CWD, "message": {"content": text}}


def said(t: float, stop: str | None = "end_turn", error: str | None = None) -> dict:
    rec = {
        "type": "assistant",
        "timestamp": at(t),
        "cwd": CWD,
        "message": {"stop_reason": stop, "content": [{"type": "text", "text": "ok"}]},
    }
    if error:
        rec["error"] = error
    return rec


def tool_use(t: float, use_id: str, name: str = "Bash") -> dict:
    return {
        "type": "assistant",
        "timestamp": at(t),
        "cwd": CWD,
        "message": {
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": use_id, "name": name}],
        },
    }


def tool_result(t: float, use_id: str, result: dict | None = None) -> dict:
    return {
        "type": "user",
        "timestamp": at(t),
        "cwd": CWD,
        "message": {"content": [{"type": "tool_result", "tool_use_id": use_id}]},
        "toolUseResult": result or {"stdout": ""},
    }


def attachment(t: float) -> dict:
    return {"type": "attachment", "timestamp": at(t), "cwd": CWD, "attachment": {"type": "x"}}


def api_error(t: float) -> dict:
    return {"type": "system", "subtype": "api_error", "timestamp": at(t), "retryAttempt": 1}


def write_jsonl(path: Path, records: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    return path


def everywhere(_cwd: object) -> bool:
    return True
