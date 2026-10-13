"""Codex 에 등록된 Recoble MCP 서버를 판정해 사람이 실행할 안내를 만듦 — 읽기 전용.

- Codex 는 서버를 global 스코프(`$CODEX_HOME/config.toml`)에 두고 토큰은 환경 변수 이름만 기록함.
  그래서 판정 대상은 transport 종류·url·`bearer_token_env_var` 존재 셋.
- 읽기는 `codex mcp list --json` — TOML 을 직접 파싱하지 않음(3.8 호환, 설정 레이어 해석은
  Codex 몫).
- 쓰지 않음: `config.toml` 은 Codex 소유이고 사용자의 다른 서버가 같이 있음.
- `codex mcp list` 는 호스트를 cwd 로 띄움 — trusted 프로젝트의 `.codex/config.toml`
  `[mcp_servers]` 도 합쳐지고 같은 이름이면 global 을 가림(실측). 그 항목은 `codex mcp
  remove`·`add` 로 못 고치므로(remove 는 global 만, add 는 global 에만) 어긋나면 그 파일을
  가리킴. 판정은 trust(`install.project_trusted`) + 이름 휴리스틱이고, 못 읽으면 global 안내로
  떨어짐(FAIL-OPEN).
- 환경 변수 값은 읽지 않음(Invariant 6). `/vdev-init` 프로세스 환경은 Codex 세션 환경과 달라
  설정 여부를 물어도 답이 되지 않음.
- 실행 파일 부재·비 0 종료·타임아웃·깨진 JSON 은 판정 불가 → 전부 안내(FAIL-OPEN).
- argv[0] 은 `shutil.which("codex")` 가 돌려주는 절대경로 — Windows 의 npm 전역 설치는
  `codex.CMD` 라 `subprocess.run(["codex", …])` 는 PATHEXT 를 안 보고 `FileNotFoundError`
  (WinError 2)로 죽음(실측). 리터럴 `"codex"` 를 argv[0] 에 쓰면 이 호스트에서 항상 판정 불가로
  접혀 setup 이 정상 등록에도 `codex mcp add` 를 찍고 uninstall 은 등록된 서버를 영영 못 봄.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .install import project_trusted

TIMEOUT_S = 20
RECOBLE_PREFIX = "recoble-"


def env_name(server_name: str) -> str:
    """서버 이름 → 토큰을 담을 환경 변수 이름(`recoble-dev3` → `RECOBLE_DEV3_PAT`)."""
    return re.sub(r"[^A-Z0-9]", "_", server_name.upper()) + "_PAT"


def _codex_path() -> str | None:
    """`codex` 실행 파일의 절대경로, 없으면 None — 이 판정이 `codex` 를 찾는 유일한 자리(단일
    seam). 다른 코드(`vdev_init_setup` 의 uninstall 배선 포함)는 여기 물어 답을 얻고, 테스트는
    이 함수 하나만 patch 하면 전역 `shutil.which` 를 건드리지 않고 격리됨."""
    return shutil.which("codex")


def codex_servers(runner=None, cwd: Path | None = None) -> tuple[dict, bool]:
    """(이름 → transport dict, 판정 가능 여부). `codex` 가 PATH 에 없으면 부르지 않고 판정 불가."""
    exe = _codex_path()
    if exe is None:
        return {}, False
    run = runner or subprocess.run
    try:
        proc = run(
            [exe, "mcp", "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}, False
    if proc.returncode != 0:
        return {}, False
    try:
        doc = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}, False
    if not isinstance(doc, list):
        return {}, False
    out = {}
    for item in doc:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            transport = item.get("transport")
            out[item["name"]] = transport if isinstance(transport, dict) else {}
    return out, True


def _project_shadows(host: Path | None) -> set[str]:
    """trusted 호스트의 `.codex/config.toml` 이 정의하는 MCP 서버 이름들 — 이름만 모음.

    TOML 파서가 아닌 휴리스틱(3.8–3.10 에 `tomllib` 없음). 세 철자를 읽음: 헤더
    `[mcp_servers.<k>]`(하위 테이블 포함), 루트의 점 키 `mcp_servers.<k>.…`, `[mcp_servers]`
    테이블 안의 `<k> = …`·`<k>.… = …`. 키는 맨 이름·큰따옴표·작은따옴표 모두.
    """
    if host is None or not project_trusted(host):
        return set()
    try:
        text = (host / ".codex" / "config.toml").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return set()
    key = r"""(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_-]+))"""
    names = set()
    # 공백은 `[ \t]*` 만 — TOML 공백이 그 둘뿐이고, `\s*` 는 개행을 넘어 줄마다 뒤 빈 줄 전체를
    # 다시 훑어 이차 시간이 됨(빈 줄 10만 개에 160초 실측)
    patterns = (
        rf"^[ \t]*\[[ \t]*mcp_servers[ \t]*\.[ \t]*{key}[ \t]*[\].]",
        rf"^[ \t]*mcp_servers[ \t]*\.[ \t]*{key}[ \t]*[.=]",
    )
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.M):
            names.add(next(g for g in m.groups() if g is not None))
    table = re.search(
        r"^[ \t]*\[[ \t]*mcp_servers[ \t]*\][ \t]*(?:#[^\n]*)?$(.*?)(?=^[ \t]*\[|\Z)",
        text,
        re.M | re.S,
    )
    if table:
        for m in re.finditer(rf"^[ \t]*{key}[ \t]*[.=]", table.group(1), re.M):
            names.add(next(g for g in m.groups() if g is not None))
    return names


def _problem(transport: dict, expected: dict) -> str | None:
    """등록이 config 와 어긋나는 첫 사유. 정상이면 None."""
    if transport.get("type") != "streamable_http":
        return "type 불일치"
    if transport.get("url") != expected["url"]:
        return "url 불일치"
    if not transport.get("bearer_token_env_var"):
        return "bearer_token_env_var 없음"
    return None


def instructions(servers: dict, runner=None, host: Path | None = None) -> list[str]:
    """config 의 Recoble 서버마다 Codex 등록 상태를 판정해 고칠 명령을 만듦."""
    registered, judged = codex_servers(runner, cwd=host)
    shadows = _project_shadows(host) if judged else set()
    lines = [
        "  [i] Codex — 아래는 사람이 자기 터미널에서 실행합니다(global 스코프: 모든 저장소가 공유)."
    ]
    if not judged:
        lines.append(
            "  [i] Codex 등록 상태를 확인할 수 없어 전부 안내합니다 (이미 등록됐으면 덮어씁니다)."
        )
    for key, expected in servers.items():
        transport = registered.get(key)
        if transport is not None:
            problem = _problem(transport, expected)
            if problem is None:
                lines.append(f"  [=] {key} (Codex) 정상 (skip)")
                continue
            if key in shadows:
                lines += [
                    f"  [~] {key} (Codex) {problem} — 이 프로젝트 .codex/config.toml 의"
                    f" [mcp_servers.{key}] 가 global 등록을 가립니다",
                    "        그 항목을 고치거나 지우세요(codex mcp remove·add 는 이 파일을 못"
                    f' 고칩니다): url = "{expected["url"]}",'
                    f' bearer_token_env_var = "{env_name(key)}"',
                ]
                continue
            lines.append(f"  [~] {key} (Codex) {problem} — 아래로 재등록")
            lines.append(f"        codex mcp remove {key}")
        else:
            lines.append(f"  [+] {key} (Codex) 미등록 — 아래로 등록")
        lines.append(
            f"        codex mcp add {key} --url {expected['url']}"
            f" --bearer-token-env-var {env_name(key)}"
        )
    lines.append("  [i] 토큰은 Codex 를 띄우는 셸의 환경 변수로 둡니다 — 세션에 붙여넣지 마세요.")
    return lines


def report(runner=None, host: Path | None = None) -> list[str]:
    """uninstall 보고용 — Codex 에 등록된 recoble-* 를 알리고 수동 제거를 안내함(자동 삭제 없음)."""
    registered, judged = codex_servers(runner, cwd=host)
    if not judged:
        return [
            "  [=] Codex 등록 상태를 확인할 수 없음 — `codex mcp list` 로 직접 확인하세요 (skip)"
        ]
    keys = sorted(k for k in registered if k.startswith(RECOBLE_PREFIX))
    shadows = _project_shadows(host)
    if not keys:
        return ["  [=] Codex 에 등록된 recoble 서버 없음 (skip)"]
    return [
        f"  [i] Codex 에 recoble 서버 {len(keys)}개 등록됨(global — 다른 저장소도 씀)"
        " — 필요 없으면 직접 제거하세요.",
        *(f"        codex mcp remove {k}" for k in keys),
        *(
            f"  [i] {k} 는 이 프로젝트 .codex/config.toml 의 [mcp_servers.{k}] 에도 있습니다"
            " — 그 항목은 파일에서 직접 지우세요(codex mcp remove 는 global 만 지움)."
            for k in keys
            if k in shadows
        ),
    ]
