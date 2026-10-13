"""채점 못 한 세션의 기록 — 원인이 실행보다 오래 남는 유일한 자리.

작업 디렉터리와 메모리 속 트랜스크립트는 실행이 끝나면 사라짐. 타임아웃·실패 세션의 마지막
도구 호출·트랜스크립트·stderr 는 여기에만 남음."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from evals.runner import config, session, stream

RUNS_DIR = config.REPO_ROOT / "evals/.runs"
# 프로세스 하나 = 실행 하나라 그 기록이 한 디렉터리에 모임. pid 가 같은 초에 시작한 두 실행을 가름.
STAMP = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
INPUT_LIMIT = 300

# 사유 상수는 `config` 소유 — `session.run_session` 이 `diagnose` 를 import 하지 않고 씀(순환 방지).
TIMEOUT = config.TIMEOUT
ERRORED = config.ERRORED
NO_INIT = config.NO_INIT
MISSING_SKILL = config.MISSING_SKILL


def last_name(parsed: stream.ParsedSession | None) -> str:
    return parsed.last_tool["name"] if parsed and parsed.last_tool else "none"


def _clip(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= INPUT_LIMIT else text[:INPUT_LIMIT] + "..."


def record(
    raw: session.Raw,
    parsed: stream.ParsedSession | None,
    *,
    skill: str,
    arm: str,
    index: int,
    rep: int,
    prompt: str,
    fixture: str | None,
    reason: str,
) -> Path:
    """`<skill>-<arm>-<index>-r<rep>` 의 `.json` 요약·`.jsonl` 트랜스크립트·`.stderr.txt` 를 쓰고
    요약 경로를 돌려줌. 같은 세션의 두 번째 기록(confirm 재측정)은 덮지 않고 `.n<k>` 를 붙임."""
    out = RUNS_DIR / STAMP
    out.mkdir(parents=True, exist_ok=True)
    base = f"{skill}-{arm}-{index}-r{rep}"
    stem, attempt = base, 1
    while (out / f"{stem}.json").exists():
        attempt += 1
        stem = f"{base}.n{attempt}"
    last = parsed.last_tool if parsed else None
    if last is not None:
        last = {"name": last["name"], "input": _clip(last["input"])}
    summary = {
        "skill": skill,
        "arm": arm,
        "index": index,
        "rep": rep,
        "prompt": prompt,
        "fixture": fixture,
        "reason": reason,
        "timed_out": raw.timed_out,
        "timeout_s": config.SESSION_TIMEOUT_S,
        "elapsed_s": raw.elapsed,
        "returncode": raw.returncode,
        "tool_calls": parsed.tool_calls if parsed else None,
        "last_tool": last,
        "stderr_tail": [ln for ln in raw.err.strip().splitlines() if ln.strip()][-5:],
    }
    path = out / f"{stem}.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # newline="": 프로세스가 낸 바이트 그대로 — Windows 가 번역한 사본이 아님.
    (out / f"{stem}.jsonl").write_text(raw.text, encoding="utf-8", newline="")
    (out / f"{stem}.stderr.txt").write_text(raw.err, encoding="utf-8", newline="")
    return path
