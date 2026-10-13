"""폴더 전체의 격리 픽스처 — 임포트가 아니라 conftest 로 두어 새 파일도 빠짐없이 받음.

- `trust_notes` 는 기본으로 이 머신의 `~/.codex/config.toml` 을 읽음 — `CODEX_HOME` 을 빈
  임시 디렉터리로 돌려 이 머신의 Codex trust 상태에 결과가 매이지 않게 함.
- uninstall 의 `[Recoble MCP]` Codex 판정이 `codex` 실행 파일을 찾는 것은 `tests/conftest.py`
  의 `_hermetic_codex_lookup` 이 스위트 전체에 이미 격리함(단일 seam `mcp._codex_path`) — 여기
  따로 두지 않음.
"""

import pytest


@pytest.fixture(autouse=True)
def _hermetic_codex_home(tmp_path, monkeypatch):
    home = tmp_path / "codexhome"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
