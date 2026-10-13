"""Codex 호스트의 `.codex/hooks.json`(Codex 의 프로젝트 훅 파일)에 커밋 게이트를 등록·해제함.

- Codex 는 trusted 프로젝트에서만 이 파일을 읽고, 훅은 사용자가 `/hooks` 에서 승인해야 돎.
  승인은 훅의 내용과 위치에 묶이므로 명령 문자열은 상수이고 게이트 엔트리는 끝에 덧붙이기만
  함(끼워 넣으면 뒤따르는 사용자 훅의 승인이 풀림).
- 명령은 저장소 루트 기준 절대 경로 — Codex 는 `CLAUDE_PROJECT_DIR` 을 주지 않고 cwd 가
  하위 디렉터리일 수 있음. wrapper(`gate.sh`·`gate.cmd`)가 러너의 exit 2 를 deny JSON 으로 바꿈.
- matcher 판정은 Codex 자신의 문법(`[A-Za-z0-9_|]` 만이면 정확한 이름 목록) — Claude 설치자의
  판정 코드를 재사용하지 않음(같은 `Bash,Read` 가 두 방언에서 다르게 읽힘).
- trust 확인은 사용자 `config.toml` 을 **읽기만** 함 — 사용자 홈에 쓰지 않음.
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path

try:
    from harness.gate_spec import GATE
    from harness.jsonfile import load_json_object, why, write_json, write_or_remove
except ImportError:
    from scripts.harness.gate_spec import GATE
    from scripts.harness.jsonfile import (
        load_json_object,
        why,
        write_json,
        write_or_remove,
    )

_WRAPPER = GATE.runner_rel.rsplit("/", 1)[0] + "/harness/codex/gate"
GATE_COMMAND = f'bash "$(git rev-parse --show-toplevel)/{_WRAPPER}.sh"'
GATE_COMMAND_WINDOWS = f'& "$(git rev-parse --show-toplevel)/{_WRAPPER}.cmd"'
GATE_HOOK = {
    "type": "command",
    "command": GATE_COMMAND,
    "commandWindows": GATE_COMMAND_WINDOWS,
    "timeout": GATE.timeout,
    "statusMessage": GATE.status,
}
GATE_ENTRY = {"matcher": "Bash", "hooks": [GATE_HOOK]}
# 게이트 자신의 훅을 알아보는 두 낱말 — 함께 봐야 호스트의 다른 `gate` 훅과 섞이지 않음.
MARKER = ("vway-kit", "harness/codex/gate")
# Codex 는 이 밖의 최상위 키가 하나라도 있으면 파일 전체를 무시함.
ALLOWED_TOP = {"description", "hooks"}

# Codex matcher 문법(codex-rs 근거):
# - `[A-Za-z0-9_|]` 로만 철자된 matcher 는 `|` 로 가른 정확한 도구 이름 목록.
# - 그 밖(쉼표·하이픈·공백 포함)은 여기서 평가하지 않는 정규식 — Claude 방언의 목록
#   `Bash,Read` 가 Codex 에선 `Bash` 에 매치하지 않는 정규식.
_EXACT_MATCHER_RE = re.compile(r"[A-Za-z0-9_|]*")


def _fires_on_bash(matcher: object) -> bool | None:
    """PreToolUse matcher 가 Bash 에 발화하는가. True·False, 또는 판정 불가면 None."""
    if matcher is None or matcher in ("", "*"):
        return True
    if not isinstance(matcher, str) or not _EXACT_MATCHER_RE.fullmatch(matcher):
        return None
    return "Bash" in matcher.split("|")


def _path(host: Path) -> Path:
    return host / ".codex" / "hooks.json"


def _is_gate(hook: object) -> bool:
    return (
        isinstance(hook, dict)
        and isinstance(hook.get("command"), str)
        and all(w in hook["command"] for w in MARKER)
    )


def _load(host: Path) -> tuple[dict | None, str | None]:
    data, err = load_json_object(_path(host), ".codex/hooks.json")
    if data is None:
        return None, err
    if set(data) - ALLOWED_TOP:
        return None, (
            "  [!] .codex/hooks.json 에 description·hooks 외 키가 있어 Codex 가 파일 전체를"
            " 읽지 않습니다 — 수동 확인 필요"
        )
    if not isinstance(data.get("hooks", {}), dict) or not isinstance(
        data.get("hooks", {}).get("PreToolUse", []), list
    ):
        return None, "  [!] .codex/hooks.json hooks 형식 비정상 — 게이트 미등록(수동 확인)"
    return data, None


def _entries(data: dict) -> list:
    return data.get("hooks", {}).get("PreToolUse", [])


def register(host: Path) -> str:
    """커밋 게이트를 .codex/hooks.json 에 등록.

    - Bash 에 발화한다고 증명되는 matcher 아래 이미 있으면 skip, 옛 모양이면 제자리 보정.
    - 발화하지 않는다고 증명되는 matcher 아래의 게이트 훅은 빼 옴 — Claude 설치자와 같은 규칙,
      matcher 판정만 Codex 문법.
    """
    data, err = _load(host)
    if data is None:
        return err
    entries = _entries(data)
    # Bash 를 놓친다고 증명되는 matcher 아래의 게이트 훅은 게이트가 아님 — 남겨 두면 돌지
    # 않는 훅 위에 "이미 등록됨" 이 찍힘. 그 엔트리는 호스트 훅을 함께 담을 수 있으므로 게이트
    # 훅만 옮기고 엔트리·matcher·나머지 훅은 그대로 둠.
    moved = 0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            continue
        if _fires_on_bash(entry.get("matcher")) is False:
            kept = [h for h in entry["hooks"] if not _is_gate(h)]
            moved += len(entry["hooks"]) - len(kept)
            entry["hooks"] = kept
    gate_hooks = [
        h
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("hooks"), list)
        for h in e["hooks"]
        if _is_gate(h)
    ]
    # 발화한다고 **알려진** matcher 아래의 훅만 등록된 게이트로 셈. 판정 못 하는 matcher
    # 아래의 것은 그 자리에 두고, 발화가 알려진 엔트리를 그 옆에 덧붙임 — 다른 게이트 훅처럼
    # 낡았으면 다시 씀.
    firing = [
        h
        for e in entries
        if isinstance(e, dict)
        and isinstance(e.get("hooks"), list)
        and _fires_on_bash(e.get("matcher")) is True
        for h in e["hooks"]
        if _is_gate(h)
    ]
    added = not firing
    if added:
        data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(copy.deepcopy(GATE_ENTRY))
    stale = [h for h in gate_hooks if h != GATE_HOOK]
    if not added and not stale and not moved:
        return "  [=] Codex 커밋 게이트 이미 등록됨 (skip)"
    for h in stale:
        h.clear()
        h.update(copy.deepcopy(GATE_HOOK))
    try:
        _path(host).parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"  [!] .codex 를 만들지 못했습니다({why(exc)}) — 수동 확인 필요"
    failed = write_json(_path(host), data, host)
    if failed:
        return failed
    if added and moved:
        return (
            "  [+] Codex 커밋 게이트 등록 (.codex/hooks.json, 발화하지 않는 matcher 항목에서"
            f" {moved}건 이동 — Codex 의 /hooks 에서 승인해야 실행)"
        )
    verb = "등록" if added else "보정"
    return (
        f"  [+] Codex 커밋 게이트 {verb} (.codex/hooks.json — Codex 의 /hooks 에서 승인해야 실행)"
    )


def unregister(host: Path) -> str:
    """게이트 훅만 뗌. 비워진 자기 엔트리는 지우고, 남은 훅이 없으면 파일도 지움."""
    if not _path(host).is_file():
        return "  [=] Codex 게이트 훅 없음 (skip)"
    data, err = _load(host)
    if data is None:
        return err
    removed = 0
    kept_entries = []
    for e in _entries(data):
        if isinstance(e, dict) and isinstance(e.get("hooks"), list):
            before = len(e["hooks"])
            e["hooks"] = [h for h in e["hooks"] if not _is_gate(h)]
            removed += before - len(e["hooks"])
            if before and not e["hooks"] and set(e) == {"matcher", "hooks"}:
                continue
        kept_entries.append(e)
    if not removed:
        return "  [=] Codex 게이트 훅 없음 (skip)"
    hooks = data.setdefault("hooks", {})
    if kept_entries:
        hooks["PreToolUse"] = kept_entries
    else:
        hooks.pop("PreToolUse", None)
    # 링크는 너머로 쓰고, `{"hooks": {}}` 가 Codex 가 로드하는 것으로 확인된 빈 모양.
    if not hooks and set(data) <= {"hooks"} and not _path(host).is_symlink():
        data.clear()
    failed, dropped = write_or_remove(_path(host), data, host, ".codex/hooks.json")
    if failed:
        return failed
    if dropped:
        return "  [-] Codex 커밋 게이트 해제 (.codex/hooks.json 삭제 — 남은 훅 없음)"
    return "  [-] Codex 커밋 게이트 해제 (.codex/hooks.json)"


def problems(host: Path) -> list[str]:
    """Codex 커밋 게이트가 돌지 않을 이유 중 .codex/hooks.json 만으로 말할 수 있는 것."""
    data, _err = _load(host)
    if data is None:
        return [
            ".codex/hooks.json 을 읽지 못해 Codex 커밋 게이트를 확인할 수 없습니다 — 위 [!] 를"
            " 해결한 뒤 /vdev-init 를 다시 실행하세요."
        ]
    # Bash 에 닿지 않는 matcher 아래의 게이트 훅은 명령 문자열이 같아도 게이트가 아님 —
    # Claude 설치자와 같은 세 갈래 읽기: 놓친다고 증명되는 matcher 만 탈락.
    firing = any(
        isinstance(e, dict)
        and _fires_on_bash(e.get("matcher")) is not False
        and isinstance(e.get("hooks"), list)
        and GATE_HOOK in e["hooks"]
        for e in _entries(data)
    )
    if firing:
        return []
    return [
        "Codex 커밋 게이트가 .codex/hooks.json 에 없습니다 — 위 [!] 를 해결한 뒤 /vdev-init 를"
        " 다시 실행하세요."
    ]


def hook_remains(host: Path) -> bool:
    """호스트 .codex/hooks.json 에 게이트 훅이 남아 있을 수 있는가.

    - `_load` 의 모양 규칙 없이 읽음 — 낯선 최상위 키는 Codex 가 파일을 무시하게 하지만
      게이트 훅이 그 안에 있는지와는 무관.
    - 읽지 못하는 파일은 남은 것으로 셈(지우지도 못한 파일). 부재는 `load_json_object` 가 이미
      `{}` 로 답하므로 여기서 파일시스템에 다시 묻지 않음 — 그 물음의 PermissionError 는 `_step`
      밖에서 도는 uninstall 판정까지 샘.
    """
    data, _err = load_json_object(_path(host), ".codex/hooks.json")
    if data is None:
        return True
    hooks = data.get("hooks", {})
    entries = hooks.get("PreToolUse", []) if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        return True
    return any(
        _is_gate(h)
        for e in entries
        if isinstance(e, dict)
        for h in (e.get("hooks") if isinstance(e.get("hooks"), list) else [])
    )


def _toml_project_key(key: str) -> str:
    """`[projects.<key>]` 의 그 부분 — 경로를 TOML 이 그대로 되읽는 철자로 감쌈.

    작은따옴표가 없는 키는 literal string(작은따옴표, 이스케이프 없음) — basic string(큰따옴표)
    으로 감싸면 Windows 경로의 `\\U`(예: `...\\Users\\...`)가 8자리 hex 를 요구하는 유니코드
    이스케이프로 읽혀 파싱 오류가 남. 작은따옴표가 든 키만 basic string 으로 `\\`·`"` 를
    이스케이프해 감쌈(literal string 은 작은따옴표를 못 담음).
    """
    if "'" not in key:
        return f"[projects.'{key}']"
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'[projects."{escaped}"]'


_BASIC_ESCAPE = re.compile(r"\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.|\Z)", re.S)
_RAW_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_SIMPLE_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def _basic_unescape(text: str) -> str | None:
    """TOML basic string 의 값 — TOML 이 거부하는 이스케이프·날 제어 문자가 있으면 None."""
    if _RAW_CONTROL.search(text):
        return None
    invalid = []

    def decode(m: re.Match) -> str:
        code = m.group(1)
        if code in _SIMPLE_ESCAPES:
            return _SIMPLE_ESCAPES[code]
        if len(code) > 1:
            value = int(code[1:], 16)
            if value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF:
                return chr(value)
        invalid.append(code)
        return ""

    out = _BASIC_ESCAPE.sub(decode, text)
    return None if invalid else out


def project_trusted(host: Path, codex_home: Path | None = None) -> bool:
    """Codex 사용자 설정이 이 호스트를 trusted 로 적었는가 — 읽기만 함.

    - TOML 파서가 아닌 휴리스틱(3.8–3.10 에 `tomllib` 없음): 이해 못 하는 입력(파일 부재·
      UTF-8 아님·이상한 괄호)은 raise 하거나 trusted 로 짐작하지 않고 False 로 떨어짐. TOML 이
      거부하는 이스케이프를 담은 basic string 키도 같음.
    - 키 비교는 Codex 저장 방식대로 — Windows(`nt`)만 대소문자 무시.
    """
    home = codex_home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    key = str(host.resolve())
    try:
        text = (home / "config.toml").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    for m in re.finditer(r"^\[projects\.(['\"])(.+?)\1\]\s*$([^\[]*)", text, re.M | re.S):
        name = m.group(2)
        if m.group(1) == '"':
            # basic string(큰따옴표)만 이스케이프를 풂 — literal(작은따옴표)은 그대로.
            name = _basic_unescape(name)
            if name is None:
                continue
        same = name.lower() == key.lower() if os.name == "nt" else name == key
        if same and re.search(r'^\s*trust_level\s*=\s*"trusted"', m.group(3), re.M):
            return True
    return False


def trust_notes(host: Path, codex_home: Path | None = None) -> list[str]:
    """경고만, 실패 아님 — 두 해결책 모두 사용자가 적용할 것. 판정은 `project_trusted`."""
    notes = []
    key = str(host.resolve())
    if not project_trusted(host, codex_home):
        notes.append(
            f"  [!] Codex 가 이 프로젝트를 trusted 로 모릅니다 — .codex/ 가 무시됩니다."
            f" Codex 에서 이 폴더를 신뢰하거나 config.toml 에 {_toml_project_key(key)}"
            ' trust_level = "trusted"'
        )
    notes.append(
        "  [i] Codex 의 /hooks 에서 vway-kit 게이트 훅을 승인해야 실행됩니다"
        "(승인 전엔 조용히 skip)."
    )
    return notes
