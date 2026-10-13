"""handoff 테스트가 공유하는 헬퍼 — 픽스처 쓰기 · 스킬 문서가 박아 둔 CLI 구동."""

import json
import subprocess
import sys
from pathlib import Path


def _mk(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _run_cli(cfg: Path, *args: str, host: Path | None = None) -> dict:
    """스킬 문서가 박아 둔 명령 그대로 실행. 순수 함수 테스트만으로는 argparse
    표면(--provider 철자·위치인자)이 문서와 어긋나도 green 이고, 런타임에서만 터짐.

    `host` 는 CLAUDE_PROJECT_DIR — 호스트 트리를 읽는 출력(구경로 경고)을 재려면
    그 뿌리를 지목해야 함."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "handoff_resolve.py"
    env = None
    if host is not None:
        import os

        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(host)}
    out = subprocess.run(
        [sys.executable, str(script), str(cfg), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    )
    return json.loads(out.stdout)
