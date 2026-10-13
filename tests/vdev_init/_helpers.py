"""vdev-init 테스트가 공유하는 헬퍼 — 호스트 뼈대 만들기 · 훅 조회 · 파라미터 표.

분류별 테스트 파일이 같은 호스트 모양과 같은 판정 도구를 쓰기 때문에, 여기가 그
SSOT. 어느 한 파일에서만 쓰는 헬퍼도 여기 두는 편이 나음 — 옮겨 간 테스트가
어느 파일에 있든 같은 이름으로 부름.
"""

import copy
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest
import yaml as _yaml

from scripts.vdev_init_setup import (
    _is_gate_hook,
)

PLUGIN = Path(__file__).resolve().parent.parent.parent  # repo root == 플러그인 루트


def _gate_hook() -> dict:
    """이 플러그인이 쓰는 게이트 훅 그대로. 일부 필드만 철자하면 그것은 **수리 대상**이라
    (호스트가 더한 `if`·`async`·`type` 을 되돌리는 것이 그 수리), 손대지 않는 경로를
    재려던 테스트가 수리 경로를 재게 됨."""
    from scripts.vdev_init_setup import GATE_ENTRY

    return copy.deepcopy(GATE_ENTRY["hooks"][0])


def _is_gate(command: str) -> bool:
    """설치자 자신의 술어에 물음. 마커를 테스트가 직접 철자하면, 무엇을 게이트로 세는지를
    코드에 묻기를 그만두는 것 — 누구의 훅을 가져갈지 정하는 것이 바로 그 절반임."""
    return _is_gate_hook({"type": "command", "command": command})


def _gate_commands(settings: Path) -> list[str]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]


def _pre(settings: Path) -> list[dict]:
    return json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]


# hooks 레퍼런스가 도구 이름 하나 또는 `|` 목록으로 정의하는 철자 중, 모든 호스트 버전이
# 같게 읽는 형태. 저마다 커밋에 발화하므로 게이트는 이미 그 아래 등록돼 있고, 그 엔트리를
# 건드리는 것은 호스트가 요청한 커버리지를 떨어뜨리는 일.
COVERS_BASH = [
    "*",
    "",
    None,
    "Bash",
    "Bash|Write",
    "Bash|",
    "|Bash",
    "Bash||Write",
    "Bash| Write",
    "Write|Read|Bash",
]
# 커밋이 도착하는 도구를 하나도 이름 대지 않는 철자. 두 읽기가 일치하므로 게이트 훅은
# 엔트리에서 나오고 엔트리는 나머지 전부를 유지함.
COVERS_NOTHING = ["Read", "bash", "Write|Edit", "Write, Edit"]
# 이 스크립트가 판정할 수 없는 철자. 이름 알파벳 밖은 JavaScript 정규식이고 파이썬 방언은
# 그것과 어긋남(`(?i)`·`\Z` 는 파이썬만의 것). 쉼표 구분자와 이름 주변 공백은 이것이
# 도는 가장 오래된 호스트보다 나중 것이라 거기서는 같은 텍스트가 패턴으로 읽힘. 미판정은
# 엔트리를 호스트가 쓴 그대로 두면서 **동시에** 게이트에 자기 엔트리를 줌 — 어느 쪽이든
# 게이트는 존재함.
CANNOT_DECIDE = [
    ["Bash"],
    7,
    False,
    0,
    {"tool": "Bash"},
    "Bash, Write",
    "Bash,Write",
    "Write,Bash",
    "Bash | Write",
    "Bash ",
    "Ba.h",
    "^Bash$",
    ".*",
    "Bash|.*",
    "^Notebook",
    "mcp__.*",
    "Bash[",
    "(?i)bash",
    "Bash" + chr(92) + "Z",
]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def _write_vdev_config(host: Path, contract: dict) -> None:
    cfg_dir = host / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "vdev-config.yaml").write_text(
        _yaml.safe_dump({"contract_test": contract}, allow_unicode=True), encoding="utf-8"
    )


def _mk_example(plugin: Path, body: str) -> None:
    """tmp 플러그인에 vdev-config.example.yaml 을 씀(임의 본문)."""
    (plugin / "vdev-config.example.yaml").write_text(body, encoding="utf-8")


def _mk_host_config(host: Path, text: str) -> None:
    """tmp 호스트의 config_path 위치에 vdev-config.yaml 을 씀."""
    from scripts.vdev_init_setup import config_path

    cfg = config_path(host)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text, encoding="utf-8")


# ── 구 방식 release 워크플로 진단 (RELEASE_TOKEN 마이그레이션) ────────────────────


def _mk_host_release_wf(host: Path, text: str) -> None:
    wf = host / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")


def _write_unit_test_config(host: Path, unit_test: dict) -> None:
    """호스트 config 에 unit_test 블록만 씀(다른 섹션 없음)."""
    cfg_dir = host / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "vdev-config.yaml").write_text(
        _yaml.safe_dump({"unit_test": unit_test}, allow_unicode=True), encoding="utf-8"
    )


_UT_JOBS = [
    {
        "name": "api",
        "language": "python",
        "version": "3.12",
        "setup": "pip install uv && uv sync",
        "test": "uv run pytest",
    },
    {"name": "web", "language": "node", "version": "20", "setup": "npm ci", "test": "npm test"},
]


# --------------------------------------------------------- 게이트를 호스트가 읽을 수 있는가
#
# 아래는 harness-tier 의 게이트 도달성 판정을 이식한 것. 재는 것은 하나: **셋업이 끝났다고
# 말할 때 호스트에 실제로 도는 게이트가 있는가.** `register_gate` 가 찍은 줄에 물으면 질문이
# 스스로 답하므로(나중 단계의 쓰기 실패도, 발화하지 않는 매처도, 통째로 꺼진 훅도 그 줄은
# 문제 없다고 말함), 판정은 실행이 **남긴 것**을 되읽어 만듦.

ACCESS_ENTRIES = "system.posix_acl_access"

# 구버전(scripts/ 하위 디렉터리 이전) 설치가 쓰던 경로. 여전히 vway-kit 라고 적혀 있고,
# 그것이 호스트가 직접 쓴 훅과 이것을 가르는 지점.
STALE_COMMAND = 'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/vway-kit/precommit-runner.sh"'


def _planted(host: Path, entries: list) -> Path:
    """호스트 settings.json 에 PreToolUse 엔트리를 심고 그 경로를 줌."""
    settings = host / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"hooks": {"PreToolUse": entries}}), encoding="utf-8")
    return settings


def _host_with(tmp_path: Path, entries: list) -> Path:
    _planted(tmp_path, entries)
    return tmp_path


def _firing(pre: list) -> list:
    import scripts.vdev_init_setup as vis

    return [e for e in pre if any(vis._is_gate_hook(h) for h in e.get("hooks") or [])]


def _gate_is_in(settings: Path) -> bool:
    """게이트가 이 호스트 파일에 닿았는가 — 어떤 기형이든 살아남는 방식으로 읽음.
    이것을 묻는 입력이 바로 건강한 레이아웃이 하나도 없는 모양들이기 때문."""
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    hooks = data.get("hooks") if isinstance(data, dict) else None
    entries = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    return any(
        _is_gate(h["command"])
        for e in (entries if isinstance(entries, list) else [])
        if isinstance(e, dict) and isinstance(e.get("hooks"), list)
        for h in e["hooks"]
        if isinstance(h, dict) and isinstance(h.get("command"), str)
    )


def _acl_blob(uid: int) -> bytes:
    """POSIX access 목록 하나를, 커널이 저장하는 레이아웃 그대로: 버전 워드 다음에 항목마다
    태그·권한 비트·id 가 태그 순으로 옴. 진짜여야 함 — 기형 blob 은 거부돼 Linux 에서
    테스트를 skip 시키고, 지키려던 리더를 Windows 에서도 안 지킴."""
    undefined = 0xFFFFFFFF
    out = struct.pack("<I", 2)
    for tag, perm, ident in (
        (0x01, 6, undefined),  # 소유자
        (0x02, 6, uid),  # 이름 붙은 사용자 하나 — 평범한 모드가 옮기지 못하는 것
        (0x04, 4, undefined),  # 소유 그룹
        (0x10, 6, undefined),  # `st_mode` 가 group 비트로 보고하는 마스크
        (0x20, 0, undefined),  # 그 밖의 모두
    ):
        out += struct.pack("<HHI", tag, perm, ident)
    return out


def _set_acl(path: Path) -> bytes:
    """파일에 하나 걸거나, 이 호스트가 이 테스트를 지킬 수 없는 이유를 말함."""
    if not hasattr(os, "setxattr"):
        pytest.skip("no extended attributes here")
    acl = _acl_blob(65534)  # nobody
    try:
        os.setxattr(path, ACCESS_ENTRIES, acl)
    except OSError as exc:  # 그것을 받지 않는 파일시스템
        pytest.skip(str(exc))
    return acl


# ------------------------------------------------------------------------ 실행의 판정
#
# 셋업이 `기계적 셋업 완료.` 로 끝나고 exit 0 하는 것은 **호스트에 도는 게이트가 있을 때
# 뿐**임. 아래는 그 판정이 어긋나는 입력들.

MALFORMED = [
    ("hooks 가 리스트다", {"hooks": []}),
    ("hooks 가 문자열이다", {"hooks": "x"}),
    ("PreToolUse 가 매핑이다", {"hooks": {"PreToolUse": {"matcher": "Bash"}}}),
    (
        "남의 엔트리의 hooks 가 문자열이다",
        {"hooks": {"PreToolUse": [{"matcher": "Read", "hooks": "x"}]}},
    ),
    (
        "훅 command 가 숫자다",
        {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"command": 7}]}]}},
    ),
    (
        "훅 command 가 true 다",
        {"hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [{"command": True}]}]}},
    ),
    ("훅이 문자열이다", {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": ["theirs.sh"]}]}}),
    ("문서가 문자열이다", "x"),
    ("문서가 숫자다", 7),
    ("문서가 true 다", True),
]
