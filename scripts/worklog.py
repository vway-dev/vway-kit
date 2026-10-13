"""ALM 작업의 착수·완료 시각과 AI Agent 활동 시간.

- `measure` — task-sync 가 summary 끝 `Worklog` 섹션과 handoff literal `${started}` 에 쓰는 값.
  착수 = task 문서 `**Created:**`, 완료 = 실행 시각.
- `record-wait` — Notification 훅(`permission_prompt`)이 권한 승인 대기 시각을
  `.vdev/waits` 에 적음.
- 셈 규칙의 사용자 설명은 docs/usage/alm.md 'Worklog', 근거는 각 함수 독스트링.
- 커밋 게이트 아님 — 실패는 활동 시간 없이 `warnings` 로 끝나고 exit 0(FAIL-OPEN).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from _vway_paths import _GIT_PATH_ENCODING, VDEV_DIR, config_path, force_utf8_io, host_root
except ImportError:
    from scripts._vway_paths import (
        _GIT_PATH_ENCODING,
        VDEV_DIR,
        config_path,
        force_utf8_io,
        host_root,
    )

# 사람을 기다린 구간 하나의 상한 — 턴 사이, 질문 도구, 권한 승인 대기.
IDLE = timedelta(minutes=15)


def when(raw: object) -> datetime | None:
    """ISO 시각 → 타임존 있는 datetime. 없거나 못 읽으면 None."""
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def merge(spans: list) -> list:
    """겹치거나 맞닿은 구간을 합침 — 여러 세션·하네스가 같은 분을 두 번 세지 않음."""
    out: list = []
    for s, e in sorted(x for x in spans if x[1] > x[0]):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def intersect(a: list, b: list) -> list:
    """두 구간 집합의 공통 시간."""
    a, b = merge(a), merge(b)
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if s < e:
            out.append((s, e))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def subtract(a: list, b: list) -> list:
    """`a` 에서 `b` 를 뺀 시간."""
    holes = merge(b)
    out = []
    for s, e in merge(a):
        cur = s
        for hs, he in holes:
            if he <= cur or hs >= e:
                continue
            if hs > cur:
                out.append((cur, hs))
            cur = max(cur, he)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def capped(span: tuple) -> tuple:
    """사람 대기 구간을 앞에서부터 `IDLE` 만큼만 남김."""
    s, e = span
    return (s, min(e, s + IDLE))


def total(spans: list) -> timedelta:
    return sum((e - s for s, e in merge(spans)), timedelta())


def hhmm(td: timedelta) -> str:
    """분 미만은 버림. 시는 24 를 넘어도 그대로."""
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def local(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


# 사람이 답해야 끝나는 도구 — 호출~결과는 사람 대기.
ASK_TOOLS = frozenset({"AskUserQuestion", "request_user_input"})
_END_REASONS = frozenset({"end_turn", "stop_sequence"})
_TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
# 사람이 친 로컬 명령의 기록 — 에이전트가 이어서 답할 때만 턴이 됨(`/model`·`/compact`·`!cmd`).
_LOCAL_TAGS = (
    "<command-name>",
    "<command-message>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
)


def read_records(path: Path) -> list:
    """JSONL → 시각순 레코드. 깨진 줄·시각 없는 줄은 건너뜀 — 한 줄이 측정을 죽이지 않음."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                t = when(rec.get("timestamp")) if isinstance(rec, dict) else None
                if t is not None:
                    rec["_t"] = t
                    out.append(rec)
    except OSError:
        return []
    out.sort(key=lambda r: r["_t"])
    return out


def _items(rec: dict) -> list:
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [x for x in content if isinstance(x, dict)] if isinstance(content, list) else []


def _claude_role(rec: dict, items: list) -> str | None:
    """레코드가 턴에 하는 일.

    - `prompt` 사람 입력 · `notice` 백그라운드 완료 알림(턴을 엶, 사람 아님)
    - `local` 로컬 명령·compact 요약 — 뒤이어 assistant 가 오면 그 시각부터 턴
    - `end` 턴 닫힘 · `stop` limit·인증 오류로 정지 · `retry` 자동 재시도 중 오류
    """
    kind = rec.get("type")
    if kind == "assistant":
        if rec.get("error") or rec.get("isApiErrorMessage"):
            return "stop"
        if (rec.get("message") or {}).get("stop_reason") in _END_REASONS:
            return "end"
        return None
    if kind == "system" and rec.get("subtype") == "api_error":
        return "retry"
    if kind != "user" or rec.get("isMeta") or any(x.get("type") == "tool_result" for x in items):
        return None
    text = "".join(x.get("text", "") for x in items if x.get("type") == "text").lstrip()
    if rec.get("isCompactSummary") or text.startswith(_LOCAL_TAGS):
        return "local"
    if text.startswith("<task-notification>"):
        return "notice"
    if text.startswith("[Request interrupted"):
        return "end"
    return "prompt"


def _queued_notice(rec: dict) -> str:
    """턴 도중 끝난 백그라운드 작업의 알림은 user 기록이 아니라 `queue-operation`·`attachment`
    본문에 먼저 남음(실측). 그 본문 — 턴을 열지는 않고 구간만 닫음."""
    if rec.get("type") == "queue-operation":
        return str(rec.get("content") or "")
    if rec.get("type") == "attachment":
        return json.dumps(rec.get("attachment"), ensure_ascii=False)
    return ""


def credit(busy: list, human: list, wait: list, bg: list) -> list:
    """에이전트 구간에서 사람이 답할 차례인 구간을 빼고 15분만 돌려놓음. 백그라운드는 전부."""
    return merge(subtract(busy, human) + [capped(s) for s in human] + wait + bg)


def claude_session(path: Path, inside, waits: list) -> list:
    """Claude Code 세션 하나 → 활동 구간.

    - 턴은 `prompt`·`notice` 에서 열리고 `end`·`stop` 에서 닫힘. `local` 은 다음 assistant 가
      올 때만 그 시각부터 턴 — 답이 없는 `/model`·`/compact` 뒤 자리 비움은 대기. 닫힌 뒤 기록
      (`attachment`·`queue-operation`)은 다음 프롬프트까지의 사람 대기 안에 있음(실측).
    - 사람 대기: 턴 사이는 15분 상한, 정지 뒤는 0분. 재시도가 프롬프트로 끝나면 정지.
    - 권한 대기 시각(`waits`)이 든 도구 호출은 그 시각부터 결과까지가 사람 대기.
    - 백그라운드 구간은 그 id 의 알림이 처음 보인 기록에서 닫힘 — user 기록뿐 아니라
      `queue-operation`·`attachment` 본문도.
    - 서브에이전트 기록은 부모의 도구 호출~결과 구간 안이라 따로 안 읽음.
    - 구간마다 시작 기록의 cwd 가 `inside` 일 때만 셈.
    """
    busy, human, wait, bg = [], [], [], []
    uses: dict = {}
    calls: list = []
    bg_open: dict = {}
    in_turn, idle = False, None  # idle = (시각, 정지 여부, 안인가)
    prev_t, prev_in, prev_role, cwd = None, False, None, None
    last_t, pending = None, None  # pending = 턴 밖 `local` 의 (시각, 안인가)
    for rec in read_records(path):
        t = rec["_t"]
        last_t = t
        items = _items(rec)
        role = _claude_role(rec, items)
        cwd = rec.get("cwd") or cwd
        here = inside(cwd)
        if in_turn and prev_t is not None and prev_in:
            if not (role == "prompt" and prev_role == "retry"):
                busy.append((prev_t, t))
        if not in_turn and pending is not None and rec.get("type") == "assistant":
            if idle is not None and idle[2] and not idle[1]:
                wait.append(capped((idle[0], pending[0])))
            if pending[1]:
                busy.append((pending[0], t))
            in_turn, idle, pending = True, None, None
        for tid in _TASK_ID.findall(_queued_notice(rec)):
            start = bg_open.pop(tid, None)
            if start is not None and start[1]:
                bg.append((start[0], t))
        if role == "local" and not in_turn:
            pending = (t, here)
        elif role == "prompt":
            if not in_turn and idle is not None and idle[2] and not idle[1]:
                wait.append(capped((idle[0], t)))
            in_turn, idle, pending = True, None, None
        elif role == "notice":
            for tid in _TASK_ID.findall(items[0].get("text", "") if items else ""):
                start = bg_open.pop(tid, None)
                if start is not None and start[1]:
                    bg.append((start[0], t))
            in_turn, idle, pending = True, None, None
        elif role in ("end", "stop") and in_turn:
            in_turn, idle = False, (t, role == "stop", here)
        for item in items:
            if item.get("type") == "tool_use":
                uses[item.get("id")] = (t, item.get("name"), here)
            elif item.get("type") == "tool_result":
                use = uses.pop(item.get("tool_use_id"), None)
                if use is not None and use[2]:
                    calls.append((use[0], t))
                    if use[1] in ASK_TOOLS:
                        human.append((use[0], t))
        result = rec.get("toolUseResult")
        if isinstance(result, dict):
            tid = result.get("backgroundTaskId") or (
                result.get("agentId") if result.get("isAsync") else None
            )
            if tid:
                bg_open[str(tid)] = (t, here)
        prev_t, prev_in, prev_role = t, here, role
    for start, ok in bg_open.values():
        if ok and last_t is not None:
            bg.append((start, last_t))
    for w in waits:
        for s, e in calls:
            if s <= w < e:
                human.append((w, e))
                break
    return credit(busy, human, wait, bg)


_CODEX_OPEN = "task_started"
_CODEX_CLOSE = frozenset({"task_complete", "turn_aborted"})
_CODEX_STOP = "error"


def codex_session(path: Path, inside) -> list:
    """Codex rollout 하나 → 활동 구간.

    - 턴은 `event_msg` 의 `task_started` 에서 열리고 `task_complete`·`turn_aborted` 에서 닫힘.
      `error` 는 정지 — 다음 턴까지 0분.
    - cwd 는 `session_meta`·`turn_context` 가 줌(턴마다 갱신).
    - 권한 승인 대기는 기록이 없어 15분 상한 없이 턴 안으로 셈.
    """
    busy, human, wait = [], [], []
    calls: dict = {}
    in_turn, idle = False, None
    prev_t, prev_in, cwd = None, False, None
    for rec in read_records(path):
        t = rec["_t"]
        kind = rec.get("type")
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        if kind in ("session_meta", "turn_context"):
            cwd = payload.get("cwd") or cwd
        here = inside(cwd)
        if in_turn and prev_t is not None and prev_in:
            busy.append((prev_t, t))
        event = payload.get("type") if kind == "event_msg" else None
        if event == _CODEX_OPEN:
            if not in_turn and idle is not None and idle[2] and not idle[1]:
                wait.append(capped((idle[0], t)))
            in_turn, idle = True, None
        elif event in _CODEX_CLOSE and in_turn:
            in_turn, idle = False, (t, False, here)
        elif event == _CODEX_STOP:
            in_turn, idle = False, (t, True, here)
        if kind == "response_item":
            if payload.get("type") == "function_call" and payload.get("name") in ASK_TOOLS:
                calls[payload.get("call_id")] = (t, here)
            elif payload.get("type") == "function_call_output":
                start = calls.pop(payload.get("call_id"), None)
                if start is not None and start[1]:
                    human.append((start[0], t))
        prev_t, prev_in = t, here
    return credit(busy, human, wait, [])


_CHECKOUT = re.compile(r"^checkout: moving from (\S+) to (\S+)$")
_SELECTOR = re.compile(r"\{([^}]+)\}")


def parse_moves(reflog: str) -> list:
    """`git reflog --date=iso-strict --format=%gd%x09%gs` → [(시각, 원래 브랜치, 새 브랜치)].

    rebase 의 detached HEAD 는 `rebase (…)` 로 남아 여기 안 잡힘 — rebase 중에도 브랜치는
    rebase 하던 작업 브랜치로 봄.
    """
    moves = []
    for line in reflog.splitlines():
        selector, _, subject = line.partition("\t")
        move = _CHECKOUT.match(subject)
        stamp = _SELECTOR.search(selector)
        t = when(stamp.group(1)) if stamp else None
        if move and t is not None:
            moves.append((t, move.group(1), move.group(2)))
    return sorted(moves)


def read_moves(root: Path) -> list | None:
    """그 worktree 의 HEAD reflog. git 이 없거나 저장소가 아니면 None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "reflog", "--date=iso-strict", "--format=%gd%x09%gs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_moves(proc.stdout) if proc.returncode == 0 else None


def allowed_periods(moves: list, branch: str, integration: str, start, end) -> list:
    """작업 브랜치에 속한 [착수, 완료] 안의 구간.

    - 시각별 브랜치는 그 시각 이전 마지막 전환의 대상. 전환이 없으면 내내 같은 브랜치.
    - 착수부터 작업 브랜치에 처음 닿기까지는 브랜치 무관(`/vdev` 분류·브랜치 확정 대화).
    - 작업 브랜치를 마지막으로 떠난 전환의 대상이 integration 이면 그 뒤 완료까지(병합·sync).
    """
    if not moves:
        return [(start, end)]
    before = [mv for mv in moves if mv[0] <= start]
    current = before[-1][2] if before else moves[0][1]
    segments, seg_start = [], start
    for t, _src, dst in moves:
        if start < t < end:
            segments.append((seg_start, t, current))
            seg_start, current = t, dst
    segments.append((seg_start, end, current))
    work = [i for i, seg in enumerate(segments) if seg[2] == branch]
    if not work:
        return [(start, end)]
    periods = [(start, segments[work[0]][0])] if work[0] > 0 else []
    periods += [(segments[i][0], segments[i][1]) for i in work]
    after = work[-1] + 1
    if after < len(segments) and segments[after][2] == integration:
        periods.append((segments[after][0], end))
    return merge(periods)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _text(path) -> str:
    """경로의 텍스트 철자 — transcript 의 cwd·UTF-8 로 읽은 git 출력과 같은 영역. 비UTF-8 로캘의
    POSIX 는 argv 경로의 UTF-8 바이트를 surrogateescape 로 들이므로 그대로는 어느 것과도 안 맞음."""
    return os.fsencode(str(path)).decode("utf-8", "replace")


def nested_worktrees(root: Path) -> list | None:
    """`git worktree list` 의 경로 — root 아래에 놓인 다른 worktree 의 cwd 는 다른 작업.
    못 읽으면 None(`-z` 는 git 2.36 이상)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    prefix = "worktree "
    return [line[len(prefix) :] for line in proc.stdout.split("\0") if line.startswith(prefix)]


def worktree_filter(root: Path, nested: list):
    """cwd 가 root 이거나 그 아래이고, root 아래의 다른 worktree 밖인가."""
    base = _norm(_text(root))
    others = [o for o in map(_norm, nested) if o != base and o.startswith(base + os.sep)]

    def inside(cwd) -> bool:
        if not cwd:
            return False
        c = _norm(str(cwd))
        if c != base and not c.startswith(base + os.sep):
            return False
        return not any(c == o or c.startswith(o + os.sep) for o in others)

    return inside


_CREATED = re.compile(r"^\*\*Created:\*\*[ \t]*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})[ \t]*\r?$", re.M)


def parse_created(doc: Path) -> datetime | None:
    """task 문서 `**Created:** YYYY-MM-DD HH:MM`(로컬) → 타임존 있는 시각."""
    try:
        found = _CREATED.search(doc.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    if not found:
        return None
    return datetime.strptime(found.group(1), "%Y-%m-%d %H:%M").astimezone()


def _config(path: Path) -> dict:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _claude_files(home: Path, root: Path, since: datetime) -> list:
    """`<home>/projects/<slug>*/*.jsonl` 중 착수 뒤에 고쳐진 것 — slug 규칙은
    harness_insight.project_dirs_from_cwd 와 같음(worktree 형제 포함)."""
    slug = re.sub(r"[^a-zA-Z0-9]", "-", _text(root))
    found = []
    for folder in (home / "projects").glob(slug + "*"):
        found += [p for p in folder.glob("*.jsonl") if p.stat().st_mtime >= since.timestamp()]
    return sorted(found)


def _codex_files(home: Path, since: datetime) -> list:
    return sorted(
        p
        for p in (home / "sessions").rglob("rollout-*.jsonl")
        if p.stat().st_mtime >= since.timestamp()
    )


def _waits(root: Path) -> dict:
    """`.vdev/waits` → {세션 id: [시각]}."""
    out: dict = {}
    try:
        lines = (root / VDEV_DIR / "waits").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    for line in lines:
        stamp, _, session = line.strip().partition(" ")
        t = when(stamp)
        if t is not None and session:
            out.setdefault(session, []).append(t)
    return out


def measure(config: Path, doc: Path, root: Path, branch, now, claude_home, codex_home) -> dict:
    """착수·완료 시각과 AI Agent 활동 시간. 어느 단계든 실패하면 경고하고 거기서 멈춤."""
    data = _config(config)
    alm = data.get("alm") if isinstance(data.get("alm"), dict) else {}
    out: dict = {"enabled": alm.get("worklog") is True, "warnings": []}
    started = parse_created(doc)
    if started is None:
        if not out["enabled"]:
            return out
        out["warnings"].append(
            f"착수 시각 없음 — {doc} 에 `**Created:** YYYY-MM-DD HH:MM` 줄이 없음"
        )
        return out
    out["started"] = local(started)
    if not out["enabled"]:
        return out
    out["completed"] = local(now)
    main_tree = _main_worktree(root)
    roots = [root] + ([main_tree] if main_tree and main_tree != Path(root).resolve() else [])
    branch = branch or next((b for b in map(_vdev_branch, roots) if b), None)
    if not branch:
        out["warnings"].append("작업 브랜치 없음 — .vdev/tier 가 없어 활동 시간을 안 셈")
        return out
    moves = read_moves(root)
    if moves is None:
        out["warnings"].append(f"{root} 의 reflog 를 못 읽음 — 브랜치 전환이 없는 것으로 셈")
        moves = []
    branches = data.get("branches") if isinstance(data.get("branches"), dict) else {}
    periods = allowed_periods(moves, branch, branches.get("integration") or "dev", started, now)
    nested = nested_worktrees(root)
    if nested is None:
        out["warnings"].append(
            f"{root} 의 worktree 목록을 못 읽음(git 2.36 이상 필요) — 중첩 worktree 를 안 거름"
        )
        nested = []
    inside = worktree_filter(root, nested)
    waits: dict = {}
    for r in roots:
        for session, stamps in _waits(r).items():
            waits.setdefault(session, []).extend(stamps)
    spans, sessions = [], {"claude": 0, "codex": 0}
    try:
        for path in _claude_files(claude_home, root, started):
            found = claude_session(path, inside, waits.get(path.stem, []))
            if intersect(found, periods):
                sessions["claude"] += 1
                spans += found
        for path in _codex_files(codex_home, started):
            found = codex_session(path, inside)
            if intersect(found, periods):
                sessions["codex"] += 1
                spans += found
    except OSError as exc:
        out["warnings"].append(f"transcript 를 못 읽음 — {exc}")
        return out
    out["active"] = hhmm(total(intersect(spans, periods)))
    out["sessions"] = sessions
    return out


def _main_worktree(root: Path):
    """root 가 연결된 worktree 면 메인 worktree — record-wait 가 쓰는 `CLAUDE_PROJECT_DIR` 의
    `.vdev/` 와 `/vdev` 의 tier 마커가 대개 거기 있음. 못 정하면 None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            encoding=_GIT_PATH_ENCODING,  # 파일을 여는 경로라 root 와 같은 fs 영역으로
            errors="surrogateescape",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common = Path(proc.stdout.strip())
    if proc.returncode != 0 or common.name != ".git":
        return None
    return common.parent.resolve()


def _vdev_branch(root: Path):
    """`.vdev/tier` 의 `<tier>:<branch>` 에서 브랜치."""
    try:
        text = (root / VDEV_DIR / "tier").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text.partition(":")[2] or None


def record_wait(payload: str) -> None:
    """Notification(`permission_prompt`) 훅 — 권한 승인 대기 시각을 `.vdev/waits` 에 덧붙임.

    - `.vdev/alm` 가 없으면 아무것도 안 함: ALM 작업 중이 아니면 셀 대상이 없음.
    - 출력·오류 없이 끝남 — 알림 훅이 세션에 흔적을 남기지 않음(FAIL-OPEN).
    """
    try:
        data = json.loads(payload)
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".")
        vdev = root / VDEV_DIR
        session = str(data.get("session_id") or "").strip()
        if not session or not (vdev / "alm").is_file():
            return
        with open(vdev / "waits", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().astimezone().isoformat()} {session}\n")
    except Exception:
        return


def main(argv=None) -> int:
    force_utf8_io()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("measure")
    cmd.add_argument("--task-doc", required=True, type=Path)
    cmd.add_argument("--config", type=Path)
    cmd.add_argument("--root", type=Path)
    cmd.add_argument("--branch")
    cmd.add_argument("--now")
    cmd.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    cmd.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"),
    )
    sub.add_parser("record-wait")
    args = parser.parse_args(argv)
    if args.command == "record-wait":
        record_wait(sys.stdin.read())
        return 0
    try:
        root = args.root or host_root()
        now = (when(args.now) if args.now else None) or datetime.now().astimezone()
        out = measure(
            args.config or config_path(root),
            args.task_doc,
            root,
            args.branch,
            now,
            args.claude_home,
            args.codex_home,
        )
    except Exception as exc:  # FAIL-OPEN — 측정 실패가 sync 를 멈추지 않음
        out = {"enabled": False, "warnings": [f"worklog 측정 실패 — {exc}"]}
    # 비UTF-8 로캘의 POSIX 는 argv 경로의 UTF-8 바이트를 surrogateescape 로 읽음 — 원래 바이트로
    # 되돌려 디코딩하지 않으면 그 경로를 담은 경고가 print 를 UnicodeEncodeError 로 죽임.
    text = json.dumps(out, ensure_ascii=False)
    print(text.encode("utf-8", "surrogateescape").decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
