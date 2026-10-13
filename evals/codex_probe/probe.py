"""Codex 훅 동작 재실측 도구 — 훅이 받은 stdin·env·부모 프로세스 체인을 `log/` 에 기록.

- `log/` 는 실행 전에 만들어 둠.
- 인자 `session`·`pre`·`post_*` 가 이벤트 라벨. `pre` 는 명령 속 표식으로 exit 2 차단과 deny JSON
  + exit 0 차단을 갈라 냄 — Windows 에서 exit 2 가 살아남는지 재는 대조군.
- 부모 체인은 PowerShell `Get-CimInstance` 로 읽음 — Windows 전용.
"""

import json
import os
import subprocess
import sys
import time

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
label = sys.argv[1]
raw = sys.stdin.buffer.read().decode("utf-8", "replace")


def proc(pid):
    try:
        out = (
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | "
                    "Select-Object Name,CommandLine,ParentProcessId | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            ).stdout
            or ""
        )
        out = out.strip()
        return json.loads(out) if out else None
    except Exception as exc:
        return repr(exc)


chain, pid = [], os.getppid()
for _ in range(3):
    p = proc(pid)
    chain.append(p)
    if not isinstance(p, dict):
        break
    pid = p.get("ParentProcessId")

env = {
    k: os.environ.get(k)
    for k in (
        "PLUGIN_ROOT",
        "CLAUDE_PLUGIN_ROOT",
        "CLAUDE_PROJECT_DIR",
        "PLUGIN_DATA",
        "COMSPEC",
        "SHELL",
    )
}
rec = {
    "label": label,
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "stdin": raw,
    "env": env,
    "chain": chain,
}
with open(os.path.join(LOG, f"{label}-{time.time_ns()}.json"), "w", encoding="utf-8") as f:
    json.dump(rec, f, ensure_ascii=False, indent=1)

try:
    payload = json.loads(raw)
except Exception:
    payload = {}
cmd = str((payload.get("tool_input") or {}).get("command", ""))

if label == "session":
    filler = " ".join(f"filler{i}" for i in range(2500))
    ctx = (
        "CTXPROBE-START. If you can read the marker CTXPROBE-END at the very end of this "
        "context, put the word ENDSEEN in your final reply. " + filler + " CTXPROBE-END"
    )
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}
        )
    )
    sys.exit(0)

if label == "pre":
    deny = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"probe deny ({label})",
        }
    }
    if "PROBE_BLOCK_EXIT2" in cmd:
        print(json.dumps(deny))
        print("probe deny exit2", file=sys.stderr)
        sys.exit(2)
    if "PROBE_BLOCK_JSON0" in cmd:
        print(json.dumps(deny))
        sys.exit(0)
sys.exit(0)
