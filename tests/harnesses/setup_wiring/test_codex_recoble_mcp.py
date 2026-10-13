"""`[Recoble MCP]` 단계의 세 번째 생산자(Codex 판정) 배선 — spec D3.

- setup: `codex` 가 `harnesses` 에 있고 recoble 스페이스가 있을 때만 추가. claude 전용이거나
  스페이스가 없으면 producer 자체가 없어 출력에 "Codex" 가 안 남음(골든 테스트가 그 경계를
  잼, 여기는 codex 가 있는 쪽의 동작을 잼).
- uninstall: `harnesses` config 와 무관 — `mcp._codex_path()`(단일 seam) 나 `.codex/` 존재로만
  가림(`tests/conftest.py` 의 `_hermetic_codex_lookup` 이 기본을 "PATH 에 없음" 으로 고정하므로,
  있는 경우를 재는 테스트는 각자 다시 monkeypatch).
- 실제 `codex` 바이너리를 스폰하지 않음 — `codex_servers`·`_codex_path` 를 직접 monkeypatch.
"""

from pathlib import Path

import scripts.vdev_init_setup as vis
from tests.harnesses.setup_wiring._helpers import _cfg, _codex_mcp
from tests.vdev_init._helpers import PLUGIN

RECOBLE_CFG = """\
harnesses: [claude, codex]
alm:
  provider: recoble
  recoble:
    spaces:
      dev3:
        mcp_url: https://r.example/mcp/dev3
"""


def _fake_codex_servers(registered):
    def run(runner=None, cwd=None):
        # cwd 가 호스트여야 codex 가 그 프로젝트의 .codex/config.toml 을 합침 — 배선이 빠지면
        # /vdev-init 프로세스의 cwd 로 판정함
        assert cwd is not None and (Path(cwd) / ".claude").exists()
        return dict(registered), True

    return run


def test_claude_only_host_with_recoble_spaces_has_no_codex_producer(tmp_path: Path, capsys):
    _cfg(tmp_path, RECOBLE_CFG.replace("[claude, codex]", "[claude]"))
    assert vis.run_setup(tmp_path, PLUGIN)
    assert "Codex" not in capsys.readouterr().out


def test_codex_active_without_recoble_spaces_has_no_codex_producer(tmp_path: Path, capsys):
    """codex 가 켜져 있어도(트러스트 안내는 남음) recoble 스페이스가 없으면 MCP 판정 줄은 없음."""
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    assert vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    assert "codex mcp" not in out and "(Codex)" not in out


def test_codex_active_with_recoble_spaces_emits_add_command(tmp_path: Path, monkeypatch, capsys):
    _cfg(tmp_path, RECOBLE_CFG)
    monkeypatch.setattr(_codex_mcp(), "codex_servers", _fake_codex_servers({}))
    assert vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    assert (
        "codex mcp add recoble-dev3 --url https://r.example/mcp/dev3"
        " --bearer-token-env-var RECOBLE_DEV3_PAT" in out
    )


def test_codex_active_with_a_healthy_registration_skips(tmp_path: Path, monkeypatch, capsys):
    _cfg(tmp_path, RECOBLE_CFG)
    registered = {
        "recoble-dev3": {
            "type": "streamable_http",
            "url": "https://r.example/mcp/dev3",
            "bearer_token_env_var": "RECOBLE_DEV3_PAT",
        }
    }
    monkeypatch.setattr(_codex_mcp(), "codex_servers", _fake_codex_servers(registered))
    assert vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    assert "[=] recoble-dev3 (Codex) 정상 (skip)" in out
    assert "codex mcp add" not in out


def test_an_unresolvable_codex_mcp_module_costs_only_its_line(tmp_path: Path, monkeypatch, capsys):
    _cfg(tmp_path, RECOBLE_CFG)

    def _raise():
        raise ImportError("codex mcp module cannot be imported")

    monkeypatch.setattr(vis, "_codex_mcp_module", _raise)
    assert vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    assert "[!] Codex MCP 판정 모듈을 불러오지 못했습니다" in out
    assert "기계적 셋업 완료" in out


def test_uninstall_skips_codex_producer_when_codex_is_absent(tmp_path: Path, capsys):
    """conftest 의 기본값(`_codex_path()` 없음) + `.codex/` 도 없음 → producer 없음."""
    assert vis.run_uninstall(tmp_path)
    assert "Codex" not in capsys.readouterr().out


def test_uninstall_adds_codex_producer_when_codex_is_on_path(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(_codex_mcp(), "_codex_path", lambda: "/usr/bin/codex")
    registered = {"recoble-dev3": {"type": "streamable_http"}}
    monkeypatch.setattr(_codex_mcp(), "codex_servers", _fake_codex_servers(registered))
    assert vis.run_uninstall(tmp_path)
    out = capsys.readouterr().out
    assert "codex mcp remove recoble-dev3" in out


def test_uninstall_adds_codex_producer_when_dot_codex_dir_exists_even_without_path(
    tmp_path: Path, monkeypatch, capsys
):
    (tmp_path / ".codex").mkdir()
    monkeypatch.setattr(_codex_mcp(), "codex_servers", _fake_codex_servers({}))
    assert vis.run_uninstall(tmp_path)
    out = capsys.readouterr().out
    assert "Codex 에 등록된 recoble 서버 없음 (skip)" in out


def test_uninstall_an_unresolvable_codex_mcp_module_costs_only_its_line(
    tmp_path: Path, monkeypatch, capsys
):
    (tmp_path / ".codex").mkdir()

    def _raise():
        raise ImportError("codex mcp module cannot be imported")

    monkeypatch.setattr(vis, "_codex_mcp_module", _raise)
    assert vis.run_uninstall(tmp_path)
    out = capsys.readouterr().out
    assert "[!] Codex MCP 판정 모듈을 불러오지 못했습니다" in out
    assert "정리 완료" in out


def test_an_unresolvable_codex_mcp_module_counts_as_present_without_codex_dir(
    tmp_path: Path, monkeypatch, capsys
):
    """`.codex/` 없이 import 실패만으로 `_codex_present` 가 참 — 거짓으로 접으면 판정 모듈이
    깨진 호스트에서 `[!]` 보고가 조용히 사라짐(FAIL-OPEN 이 숨는 쪽)."""
    assert not (tmp_path / ".codex").exists()

    def _raise():
        raise ImportError("codex mcp module cannot be imported")

    monkeypatch.setattr(vis, "_codex_mcp_module", _raise)
    assert vis._codex_present(tmp_path) is True
    assert vis.run_uninstall(tmp_path)
    assert "[!] Codex MCP 판정 모듈을 불러오지 못했습니다" in capsys.readouterr().out
