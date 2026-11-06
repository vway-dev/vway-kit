"""Codex 훅 페이로드가 무엇을 편집했는가.

- 부르는 쪽은 `hooks/invalidate-gate-markers.sh --harness codex`.
- Codex 는 파일 편집을 전부 `apply_patch` 로 알림 — 모델이 셸로 apply_patch 를 돌리면 Bash 명령으로.
  패치 텍스트가 곧 명령이고, 경로는 그 헤더에 세션 `cwd` 기준 상대 경로로 있음.
- 호스트 사본이 아니라 플러그인 트리에서 돎(훅이 자기 위치 기준으로 부름) — 호스트 복사 대상 아님.
- `edited-paths` 는 출력과 함께 **종료 코드**로 답함 — "경로 없음" 이 무효화 훅이 갈라야 할
  두 뜻이라서:
  - 0: 경로를 출력했거나, 편집이 아님.
  - 3: 편집인데 경로를 하나도 못 댐.
  - 4: 판정할 만큼 페이로드를 못 읽음.
- 읽는 것은 `tool_input.command` 뿐, `tool_response` 는 안 읽음 — Bash 출력은 적용 안 한 패치도
  통째로 인용할 수 있음.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PureWindowsPath

EDIT_UNPLACED = 3
UNDECIDABLE = 4

_HEADER = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+?)\s*$", re.M)
# 봉투 자신의 줄. `*** Begin Patch` 는 줄 첫머리 또는 `apply_patch '…'` 인자의 따옴표 바로 뒤에서만,
# 그 줄에 다른 것 없이 봉투를 엶 — 명령 중간에 마커를 인용한 grep·echo 는 패치가 아님.
_BEGIN = re.compile(r"(?:^|['\"])\*\*\* Begin Patch[ \t]*\r?$", re.M)
_END = re.compile(r"^\*\*\* End Patch[ \t]*['\"]?[ \t]*\r?$", re.M)
_TOOL_NAME = re.compile(r'"tool_name"\s*:\s*"([^"\\]*)"')
_COMMAND_KEY = re.compile(r'"command"\s*:\s*"')
_STRING_BODY = re.compile(r'(?:[^"\\]|\\.)*')

# 선두의 `cd <dir>`(맨 낱말, 또는 공백 든 이름의 따옴표)가 `&&`·`;` 로 뒤와 이어진 모양 — 진짜 셸
# 없이 풀 수 있는 유일하게 단순한 셸 모양. 맨 낱말 클래스는 `~`·`$`·백틱·괄호·파이프·리다이렉션
# 글자를 빼므로 `cd ~/x`·`cd $X`·`cd $(x)` 는 여기서 아예 안 맞고, 그래서 아래 평범한 cwd 로
# 떨어짐(0 자리에 cd 없음 == 풀 것 없음).
_CD = re.compile(r'^cd\s+(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'$`~();&|<>]+))\s*(?:&&|;)\s*')


def _bash_effective_dir(command: str, cwd: str) -> str:
    """선두의 단순한 `cd` 사슬을 따라가 떨어지는 자리를 돌려줌.

    이해하는 것은 `cd <dir> (&&|;)` 의 접두 사슬뿐 — `pushd`, 서브셸, 다른 명령 뒤의 `cd`, 따옴표를
    벗겨도 `~`·변수·치환인 인자는 "단순" 이 아니고 시도 전체를 멈춤. 사슬 일부로 만든 추측이 아니라
    손대지 않은 `cwd` 를 돌려줌."""
    base = cwd
    text = command.lstrip()
    while True:
        m = _CD.match(text)
        if not m:
            break
        arg = next((g for g in m.groups() if g is not None), None)
        if not arg or any(ch in arg for ch in "~$`"):
            return cwd  # cd 는 있지만 단순한 모양이 아님 — 읽은 것을 아무것도 안 믿음
        if arg.startswith("/") or PureWindowsPath(arg).is_absolute():
            base = arg
        else:
            base = base.rstrip("/\\") + "/" + arg if base else arg
        text = text[m.end() :]
    return base


_ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.S)
_ANSI_C_ESCAPE = re.compile(r"\\(.)", re.S)
_ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}
_TAB_INDENT = re.compile(r"^\t+", re.M)


def _as_the_shell_reads_it(command: str) -> str:
    """셸이 apply_patch 에 건네는 패치 텍스트 — `$'…'` 문자열은 평범한 따옴표 문자열로 풀고,
    `<<-` heredoc 이 벗기는 줄 앞 탭은 모든 줄에서 지움."""

    def decode(m: re.Match) -> str:
        body = _ANSI_C_ESCAPE.sub(lambda e: _ANSI_C_ESCAPES.get(e.group(1), e.group(0)), m.group(1))
        return "'" + body + "'"

    return _TAB_INDENT.sub("", _ANSI_C.sub(decode, command))


def has_envelope(command: str) -> bool:
    """`*** Begin Patch` 줄 뒤에 `*** End Patch` 줄 — 언급이 아니라 패치."""
    command = _as_the_shell_reads_it(command)
    begin = _BEGIN.search(command)
    return bool(begin and _END.search(command, begin.end()))


def classify(payload: dict) -> tuple[bool, list[str]]:
    """(편집인가, 편집한 경로들). 읽는 것은 `tool_input.command` 뿐, `tool_response` 는 안 읽음 —
    Bash 명령의 출력은 적용하지 않은 패치를 통째로 인용할 수 있음."""
    if not isinstance(payload, dict):
        return False, []
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if tool == "apply_patch":
        if not isinstance(command, str):
            return True, []
    elif tool == "Bash":
        if not isinstance(command, str) or not has_envelope(command):
            return False, []
        command = _as_the_shell_reads_it(command)
    else:
        return False, []
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    base = cwd.rstrip("/\\")
    if tool == "Bash" and base:
        base = _bash_effective_dir(command, base)
    out = []
    for rel in _HEADER.findall(command):
        is_abs = rel.startswith("/") or PureWindowsPath(rel).is_absolute()
        out.append(rel if is_abs or not base else base + "/" + rel)
    return True, out


def edited_paths(payload: dict) -> list[str]:
    return classify(payload)[1]


def _undecoded_command(text: str) -> str | None:
    """파싱 안 되는 JSON 에서 읽은 `tool_input.command` — 무효화 훅의 읽기 상한에서 잘린 페이로드.
    문자열 자체도 잘렸을 수 있음: 살아남은 것은 풀고, 끊긴 이스케이프는 버림."""
    at = text.find('"tool_input"')
    key = _COMMAND_KEY.search(text, at) if at >= 0 else None
    if key is None:
        return None
    body = _STRING_BODY.match(text, key.end()).group(0)
    for cut in range(0, 7):
        try:
            return json.loads('"' + body[: len(body) - cut] + '"')
        except ValueError:
            continue
    return None


def verdict_for_unparsed(text: str) -> int:
    """유효한 JSON 이 아닌 페이로드의 종료 코드. apply_patch 는 어디서 잘렸든 편집. Bash 명령은
    남은 텍스트에 온전한 봉투가 있을 때만 — 패치 중간에서 잘린 명령은 마커를 인용한 명령과
    못 가름."""
    name = _TOOL_NAME.search(text)
    if name is None:
        return UNDECIDABLE
    if name.group(1) == "apply_patch":
        return EDIT_UNPLACED
    if name.group(1) != "Bash":
        return 0
    command = _undecoded_command(text)
    return EDIT_UNPLACED if command is not None and has_envelope(command) else 0


def main(argv: list[str]) -> int:
    try:
        from _vway_paths import force_utf8_io  # 직접 실행: 형제가 sys.path 에 있음
    except ImportError:
        from scripts._vway_paths import force_utf8_io  # 패키지 임포트: scripts/ 가 이미 올라 있음
    force_utf8_io()
    if argv != ["edited-paths"]:
        return 2
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return verdict_for_unparsed(raw.decode("utf-8", "replace"))
    is_edit, paths = classify(payload)
    for p in paths:
        print(p)
    return EDIT_UNPLACED if is_edit and not paths else 0


if __name__ == "__main__":
    # 여기 sys.path[0] 은 `scripts/` 가 아니라 이 파일의 디렉터리(`scripts/harness/codex`) — 그래서
    # `scripts/` 를 이 갈래에서만 넣고 임포트 시점에는 절대 안 넣음. 평범한
    # `import scripts.harness.codex.hook_io`(모든 테스트)가 sys.path 를 건드리면, 다른 곳의 맨
    # `import _vway_paths` 가 `scripts._vway_paths` 와 다른 **두 번째** 모듈 객체로 풀리고,
    # 둘 사이의 `is` 동일성 검사가 조용히 깨짐.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main(sys.argv[1:]))
