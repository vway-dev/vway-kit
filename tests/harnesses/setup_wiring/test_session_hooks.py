"""Codex 세션 훅의 호스트 사본 — 셋업이 등록한 훅이 지목하는 파일을 플러그인과 같은 배치로
`.claude/vway-kit/` 아래 두는지, 해제와 재동기화가 그것을 치우는지 잼."""

import json
import os
import shutil
from pathlib import Path

import pytest

import scripts.vdev_init_setup as vis
from tests.harnesses.setup_wiring._helpers import HOOKS, _cfg
from tests.vdev_init._helpers import PLUGIN

ROOT = Path(".claude/vway-kit")


def test_codex_setup_installs_the_session_hooks_it_registers(tmp_path: Path):
    """Codex 패키지는 라이프사이클 훅을 싣지 않음 — 호스트 hooks.json 이 지목하는 사본은
    플러그인 루트에서처럼 돌아야 함."""
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    assert vis.run_setup(tmp_path, PLUGIN)
    hooks = json.loads((tmp_path / HOOKS).read_text(encoding="utf-8"))["hooks"]
    assert hooks["SessionStart"] and hooks["PostToolUse"]
    for rel in (
        "hooks/inject-risk-tiers.sh",
        "hooks/invalidate-gate-markers.sh",
        "hooks/codex/run-hook.cmd",
        "rules/risk-tiers.md",
        "rules/harness-tools/codex.md",
        "scripts/harness/codex/hook_io.py",
    ):
        assert (tmp_path / ROOT / rel).read_bytes() == (PLUGIN / rel).read_bytes(), rel


def test_uninstall_removes_the_codex_session_hooks(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    assert vis.run_uninstall(tmp_path)
    assert not (tmp_path / HOOKS).exists()
    assert not (tmp_path / ROOT).exists()


def test_setup_fails_when_a_codex_session_hook_script_is_missing(tmp_path: Path, monkeypatch):
    """복사가 쓰지 못한 스크립트 위에 등록된 훅은 127 로 끝남 — 리뷰 뒤 편집이 그 증거를 남김."""
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    real = vis.shutil.copyfile

    def flaky(src, dest, *a, **kw):
        if Path(dest).name == "invalidate-gate-markers.sh":
            raise OSError("locked")
        return real(src, dest, *a, **kw)

    monkeypatch.setattr(vis.shutil, "copyfile", flaky)
    assert not vis.run_setup(tmp_path, PLUGIN)


def test_resync_drops_a_rule_the_plugin_no_longer_ships(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    stale = tmp_path / ROOT / "rules" / "retired.md"
    stale.write_text("old\n", encoding="utf-8")
    vis.run_setup(tmp_path, PLUGIN)
    assert not stale.exists()
    assert (tmp_path / ROOT / "rules" / "risk-tiers.md").is_file()


@pytest.mark.parametrize("link", ["rules", ""])
def test_resync_never_deletes_through_a_linked_directory(tmp_path: Path, link):
    """저장소는 신뢰할 수 없는 입력 — rules 디렉터리나 그 위 vway-kit 디렉터리에 커밋된 링크가
    낡은 룰 정리를 호스트 문서로 돌리면 안 됨."""
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    docs = tmp_path / "docs"
    (docs / "rules").mkdir(parents=True)
    mine = docs / "rules" / "mine.md" if not link else docs / "mine.md"
    mine.write_text("mine\n", encoding="utf-8")
    at = tmp_path / ROOT / link if link else tmp_path / ROOT
    if not link:
        (docs / "config").mkdir()
        (docs / "config" / "vdev-config.yaml").write_text(
            "harnesses: [claude, codex]\n", encoding="utf-8"
        )
        shutil.rmtree(at)
    at.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(docs, at, target_is_directory=True)
    except OSError:
        pytest.skip("심링크를 만들 수 없음")
    vis.run_setup(tmp_path, PLUGIN)
    assert mine.read_text(encoding="utf-8") == "mine\n"


def test_claude_only_setup_copies_no_session_hooks(tmp_path: Path):
    assert vis.run_setup(tmp_path, PLUGIN)
    assert not (tmp_path / ROOT / "hooks").exists()
    assert not (tmp_path / ROOT / "rules").exists()
