"""setup_wiring 분류 파일이 함께 쓰는 헬퍼 — 호스트 config 쓰기와 게이트 심기."""

import json
from pathlib import Path

import scripts.vdev_init_setup as vis

CFG = Path(".claude/vway-kit/config/vdev-config.yaml")
HOOKS = Path(".codex/hooks.json")


def _cfg(host: Path, text: str) -> None:
    (host / CFG).parent.mkdir(parents=True, exist_ok=True)
    (host / CFG).write_text(text, encoding="utf-8")


def _codex():
    """`vis` 가 실제로 부르는 Codex 설치 모듈. `scripts/` 가 sys.path 앞에 있으면 `harness.*`
    와 `scripts.harness.*` 가 서로 다른 모듈 객체로 두 번 로드됨 — 테스트가 따로 임포트하면
    실행되지 않는 쪽을 잴 수 있어 `vis` 의 레지스트리에 물음."""
    return vis.harness.installer("codex")


def _codex_mcp():
    """`vis` 가 실제로 부르는 Codex MCP 판정 모듈 — `_codex()` 와 같은 이유로 `vis` 를 통해 얻음."""
    return vis._codex_mcp_module()


def _plant_claude_gate(host: Path) -> Path:
    """settings.json 에 살아 있는 Claude 게이트 훅이 있는 호스트."""
    claude_dir = host / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings = claude_dir / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [vis.GATE_ENTRY]}}), encoding="utf-8")
    return settings


def _corrupt_codex_hooks(host: Path) -> None:
    """`_load` 가 거절하는 모양(낯선 최상위 키)을 등록된 게이트 옆에 둠 — `unregister` 는 그것을
    보고하고 파일을 그대로 두므로 훅이 남음."""
    path = host / HOOKS
    data = json.loads(path.read_text(encoding="utf-8"))
    data["extra"] = 1
    path.write_text(json.dumps(data), encoding="utf-8")
