"""/vdev-init 의 setup·uninstall 이 Codex 지침 블록을 렌더·제거하는지 — 그리고 claude 전용
호스트의 파일은 건드리지 않는지.

- 무엇을 재는가: codex 켜진 호스트의 `[Codex 지침 렌더]`·`[Codex 지침 블록 제거]` 단계, 호스트
  사본만으로 렌더러가 도는지(필요한 import 가 함께 내려앉았는지), 렌더러가 게이트 파일이 아닌지.
"""

import sys
from pathlib import Path

import pytest

import scripts.vdev_init_setup as vis
from scripts.harness.codex import instructions as codex
from tests._proc import run_bounded
from tests.vdev_init._helpers import PLUGIN

CFG = Path(".claude/vway-kit/config/vdev-config.yaml")
HOST_SCRIPTS = Path(".claude/vway-kit/scripts")


@pytest.fixture(autouse=True)
def _hermetic_codex_home(tmp_path, monkeypatch):
    home = tmp_path / "codexhome"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))


def _host(tmp_path: Path, harnesses: str | None) -> Path:
    host = tmp_path / "host"
    (host / CFG).parent.mkdir(parents=True)
    if harnesses is not None:
        (host / CFG).write_text(f"harnesses: {harnesses}\n", encoding="utf-8")
    (host / "CLAUDE.md").write_bytes(b"# Host\r\nbe careful\r\n")
    return host


def test_claude_only_setup_and_uninstall_never_touch_agents_md(tmp_path, capsys):
    host = _host(tmp_path, None)
    vis.run_setup(host, PLUGIN)
    assert not (host / "AGENTS.md").exists()
    (host / "AGENTS.md").write_bytes(b"mine\r\n")
    vis.run_setup(host, PLUGIN)
    vis.run_uninstall(host)
    assert (host / "AGENTS.md").read_bytes() == b"mine\r\n"
    # 블록이 없는 AGENTS.md 에는 단계 제목도 안 찍힘 — claude 전용 출력이 배선 전과 같음.
    assert "Codex 지침" not in capsys.readouterr().out


def test_codex_setup_renders_the_block(tmp_path, capsys):
    host = _host(tmp_path, "[claude, codex]")
    claude_md = (host / "CLAUDE.md").read_bytes()
    assert vis.run_setup(host, PLUGIN)
    assert "[Codex 지침 렌더]" in capsys.readouterr().out
    text = (host / "AGENTS.md").read_text(encoding="utf-8")
    assert codex.BEGIN in text and "be careful" in text
    assert (host / "CLAUDE.md").read_bytes() == claude_md


def test_uninstall_removes_the_block_and_keeps_user_text(tmp_path, capsys):
    host = _host(tmp_path, "[claude, codex]")
    (host / "AGENTS.md").write_bytes(b"user text\n")
    vis.run_setup(host, PLUGIN)
    assert codex.BEGIN.encode("utf-8") in (host / "AGENTS.md").read_bytes()
    vis.run_uninstall(host)
    assert "[Codex 지침 블록 제거]" in capsys.readouterr().out
    assert (host / "AGENTS.md").read_bytes() == b"user text\n"


def test_uninstall_removes_the_block_after_codex_left_harnesses(tmp_path):
    """uninstall 은 config 의 `harnesses` 와 무관 — 목록에서 codex 를 뺀 뒤에도 블록은 사라짐."""
    host = _host(tmp_path, "[claude, codex]")
    vis.run_setup(host, PLUGIN)
    (host / CFG).write_text("harnesses: [claude]\n", encoding="utf-8")
    vis.run_uninstall(host)
    assert not (host / "AGENTS.md").exists()


def test_leftover_block_is_reported_when_codex_leaves_harnesses(tmp_path, capsys):
    host = _host(tmp_path, "[claude, codex]")
    vis.run_setup(host, PLUGIN)
    (host / CFG).write_text("harnesses: [claude]\n", encoding="utf-8")
    capsys.readouterr()
    vis.run_setup(host, PLUGIN)
    out = capsys.readouterr().out
    assert "AGENTS.md 지침 블록" in out
    assert codex.BEGIN in (host / "AGENTS.md").read_text(encoding="utf-8")


def test_codex_host_copy_carries_the_renderer(tmp_path):
    vis.copy_artifacts(PLUGIN, tmp_path, harnesses=("claude", "codex"))
    for rel in (
        "harness/__init__.py",
        "harness/instructions.py",
        "harness/codex/__init__.py",
        "harness/codex/instructions.py",
        "_vway_paths.py",
    ):
        assert (tmp_path / HOST_SCRIPTS / rel).is_file(), rel


def test_the_host_copy_runs_on_its_own(tmp_path):
    """플러그인이 닿지 않는 호스트 사본에서 실행 — 필요한 import 가 전부 함께 내려앉았음."""
    host = _host(tmp_path, "[claude, codex]")
    vis.copy_artifacts(PLUGIN, host, harnesses=("claude", "codex"))
    script = host / HOST_SCRIPTS / "harness/codex/instructions.py"
    cmd = [sys.executable, "-I", str(script), "render", "--host", str(host)]
    run = run_bounded(cmd, text=True, cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert codex.BEGIN in (host / "AGENTS.md").read_text(encoding="utf-8")


def test_the_host_copy_names_a_missing_pyyaml(tmp_path):
    """호스트 사본은 형제 경로로 import 함 — 저장소 안 테스트는 그 경로에 닿지 않음."""
    host = _host(tmp_path, "[claude, codex]")
    vis.copy_artifacts(PLUGIN, host, harnesses=("claude", "codex"))
    script = host / HOST_SCRIPTS / "harness/codex/instructions.py"
    code = (
        "import runpy, sys; sys.modules['yaml'] = None; "
        f"sys.argv = [{str(script)!r}, 'render', '--check', '--host', {str(host)!r}]; "
        f"runpy.run_path({str(script)!r}, run_name='__main__')"
    )
    run = run_bounded([sys.executable, "-I", "-c", code], text=True)
    assert run.returncode == 1, run.stderr
    assert "PyYAML" in run.stdout and "Traceback" not in run.stderr


def test_renderer_modules_are_not_gate_files():
    gate = {source for _, source in vis.gate_files(("claude", "codex"))}
    assert not any(source.endswith("instructions.py") for source in gate)


def test_setup_leftover_probe_prefix_matches_the_renderer():
    """`vdev_init_setup` 이 모듈 없이 블록을 알아보는 접두는 렌더러의 BEGIN 접두와 같아야 함."""
    assert vis.CODEX_INSTRUCTIONS_BEGIN == codex._BEGIN_PREFIX
