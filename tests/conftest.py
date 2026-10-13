"""전체 스위트 공용 격리 픽스처.

- Codex MCP 판정(`scripts/harness/codex/mcp.py`)은 `codex` 실행 파일을 찾아 실제로 부름 —
  개발자 머신에 Codex CLI 가 설치돼 있으면(예: Task 6 acceptance 실측이 남긴 상태) `codex mcp
  list --json` 이 그 머신의 진짜 global config 를 최대 20초 읽어, `run_uninstall`·`run_setup` 을
  호출하는 아무 테스트나 그 자리에서 느려지고 CI 와 결과가 갈림.
- 단일 seam(`mcp._codex_path`)만 patch — 전역 `shutil.which` 를 patch 하면 bash·git 실행 파일을
  찾는 무관한 테스트까지 깨짐(실측: 이 patch 로 `uv run pytest -q` 전체 스위트가 그린).
- 개별 테스트가 Codex 가 있는 경우를 재려면 자기 안에서 다시
  `monkeypatch.setattr(mcp, "_codex_path", lambda: "<경로>")` 로 덮어씀 — 같은 `monkeypatch`
  인스턴스라 이 fixture 뒤에 걸려 우선함.
"""

import pytest


@pytest.fixture(autouse=True)
def _hermetic_codex_lookup(monkeypatch):
    try:
        from scripts.harness.codex import mcp as _codex_mcp
    except ImportError:
        return
    monkeypatch.setattr(_codex_mcp, "_codex_path", lambda: None)
