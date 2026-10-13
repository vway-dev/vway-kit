"""SessionStart 훅 테스트 공용 픽스처 — 플러그인 루트 모양 디렉터리, 훅 실행, 주입 컨텍스트 추출."""

import json
import os
import subprocess
from pathlib import Path

from tests._bash import find_bash

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "hooks" / "inject-risk-tiers.sh"


# bash 를 고르는 규칙은 tests/_bash.py 가 SSOT — 이름으로 부르면 Windows 의
# CreateProcess 가 PATH 보다 앞선 System32 의 WSL 스텁을 집어 stdin 을 물고 매달림.
# 여기서는 없을 때 이름으로 폴백함(이 파일의 모든 테스트가 bash 를 요구함).
BASH = find_bash() or "bash"

STARTUP = json.dumps({"hook_event_name": "SessionStart", "source": "startup"})
RULE_BODY = "# rule\n훅이 실제로 읽어야 하는 본문\n"
STYLE_BODY = "# style\n문체 룰 본문\n"
STYLE_OPEN = "<vway-kit-doc-style>"

NOTICE_OPEN = "<vway-kit-stale-build>"
NOTICE_CLOSE = "</vway-kit-stale-build>"
RELAY = "Relay this to the user before doing anything else:"

# 출력 분기별로: 그 분기를 고르는 env 와, 주입 컨텍스트가 놓이는 자리.
BRANCHES = {
    "claude": ({}, ("hookSpecificOutput", "additionalContext")),
    "cursor": ({"CURSOR_PLUGIN_ROOT": "x"}, ("additional_context",)),
    "sdk": ({"COPILOT_CLI": "1"}, ("additionalContext",)),
}


def _manifest(root: Path, name: str, version: str | None, author: str = "someone-else") -> Path:
    """플러그인 루트 모양의 디렉터리 — 매니페스트와 훅이 주입할 룰."""
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {"name": name}
    if version is not None:
        body["version"] = version
    # 최상위 `name` 뒤에 오는 `author.name` 은 실제 매니페스트의 배치이고, 마지막 매치를
    # 취하는 읽기가 거꾸로 집게 되는 모양. 두 루트가 같은 author 를 쓰면 그 잘못된
    # 읽기도 "같은 이름"으로 판정돼 통과하므로, 판별하려면 서로 달라야 함.
    body["author"] = {"name": author}
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(body), encoding="utf-8")
    (root / "rules").mkdir(exist_ok=True)
    # newline="" 로 Windows 가 줄바꿈을 바꾸지 못하게 함 — 훅이 읽는 바이트가 곧 단언 대상.
    (root / "rules" / "risk-tiers.md").write_text(RULE_BODY, encoding="utf-8", newline="")
    return root


def _run(
    plugin_root: Path,
    project_dir: Path | None,
    stdin: str = STARTUP,
    extra_env=None,
    script: Path = SCRIPT,
):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
    }
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.update(extra_env or {})
    # encoding="utf-8" 은 Invariant #2. 빠뜨리면 Windows 가 훅의 UTF-8 한글을 ANSI
    # 코드페이지로 디코드하다가 리더 스레드에서 UnicodeDecodeError 로 죽고, 그 예외는 삼켜져
    # `stdout is None` + `returncode == 0` 이 됨 — 읽을 수 있는 실패가 아니라 엉뚱한
    # TypeError 로 나타남(PYTHONUTF8 없이 24건 실패로 실측).
    return subprocess.run(
        [BASH, str(script)],
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=30,
    )


def _out(result) -> dict:
    assert result.returncode == 0, (
        f"훅은 언제나 exit 0 이어야 한다 (got {result.returncode}): {result.stderr}"
    )
    return json.loads(result.stdout)


def _context(result, branch: str = "claude") -> str:
    node = _out(result)
    for key in BRANCHES[branch][1]:
        node = node[key]
    assert isinstance(node, str), f"컨텍스트 문자열이 와야 한다 (got {type(node).__name__})"
    return node


def _extract(context: str) -> str | None:
    """알림은 주입 컨텍스트 안에 자기 태그로 실림 — 그 태그가 있어야 "조용한 실행"과
    언제나 존재하는 룰 텍스트를 구분할 수 있음."""
    if NOTICE_OPEN not in context:
        return None
    return context.split(NOTICE_OPEN, 1)[1].split(NOTICE_CLOSE, 1)[0]


def _notice(result, branch: str = "claude") -> str | None:
    return _extract(_context(result, branch))
