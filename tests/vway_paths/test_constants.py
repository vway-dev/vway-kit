"""경로·파일명·게이트 계약 상수와 루트 해석.

호스트 루트는 `CLAUDE_PROJECT_DIR` 이 이기고, 없으면 git toplevel 로 떨어짐. 상수가
조용히 바뀌면 게이트가 남의 경로를 읽으므로 값 자체를 못 박음.
"""

from pathlib import Path

import scripts._vway_paths as vp


def test_path_segment_constants():
    # 호스트 쓰기 루트와 하위 분류는 모두 .claude/vway-kit/ 아래에 모인다(CLAUDE.md).
    assert vp.VWAY_DIR == ".claude/vway-kit"
    assert vp.SCRIPTS_DIR == ".claude/vway-kit/scripts"
    assert vp.CONFIG_DIR == ".claude/vway-kit/config"
    assert vp.VDEV_DIR == ".claude/vway-kit/.vdev"


def test_filename_constants():
    assert vp.CONFIG_FILENAME == "vdev-config.yaml"
    assert vp.TIERS_FILENAME == "vdev-tiers.yaml"


def test_gate_contract_constants():
    # Invariant #3: 차단 = exit 2. 런타임 게이트·티어 라벨은 yaml 키와 byte-match 대상.
    assert vp.BLOCK_EXIT_CODE == 2
    assert "security-scan" in vp.RUNTIME_GATES
    assert vp.STAGING_TIER == "staging"
    assert vp.RELEASE_TIER == "release"


def test_path_helpers_compose_from_root(tmp_path: Path):
    assert vp.vway_dir(tmp_path) == tmp_path / ".claude" / "vway-kit"
    assert vp.config_dir(tmp_path) == tmp_path / ".claude" / "vway-kit" / "config"
    assert vp.vdev_dir(tmp_path) == tmp_path / ".claude" / "vway-kit" / ".vdev"
    assert vp.config_path(tmp_path) == (
        tmp_path / ".claude" / "vway-kit" / "config" / "vdev-config.yaml"
    )


def test_host_root_prefers_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert vp.host_root() == tmp_path.resolve()


def test_host_root_fallback_no_crash(monkeypatch, tmp_path: Path):
    # env 미설정 + git 실패 → 마커(.claude) 탐색 실패 시 cwd 폴백(IndexError·크래시 없음).
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    def boom(*_a, **_k):
        raise OSError("no git")

    monkeypatch.setattr(vp.subprocess, "run", boom)
    result = vp.host_root()
    assert isinstance(result, Path)  # 마커 없는 경로 → cwd 폴백(크래시 X)


def test_plugin_root_prefers_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    assert vp.plugin_root() == tmp_path


def test_plugin_root_fallback_is_scripts_parent(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # _vway_paths.py 는 scripts/ 에 있으므로 폴백은 그 상위(플러그인 루트)다.
    assert vp.plugin_root() == Path(vp.__file__).resolve().parent.parent


def test_force_utf8_io_sets_pythonutf8(monkeypatch):
    # 자식 python 인코딩 상속을 위해 PYTHONUTF8 을 설정한다(Invariant #2 강화).
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    vp.force_utf8_io()
    assert vp.os.environ.get("PYTHONUTF8") == "1"
