"""게이트 진입점 `main()` — 무엇이 커밋을 막고 무엇이 통과시키는가.

FAIL-OPEN 이 기본. 정책·설정이 **파싱 성공**하는데 tier 마커가 없을 때만 막고,
파일이 깨졌거나 마커가 다른 브랜치 것이면 통과시킴.
"""

from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import (
    _run_main,
)


def test_main_allows_when_no_vdev(tmp_path: Path):
    # 정책 파일(vdev-tiers.yaml)조차 없는 환경 = 설치/환경 불확정 → fail-OPEN.
    (tmp_path / ".claude").mkdir()
    assert _run_main(tmp_path).returncode == 0


def test_main_blocks_unclassified_with_policy(tmp_path: Path):
    # 정책 파일은 정상인데 tier 마커가 전혀 없음 = vdev 미진입(미분류) → fail-CLOSED 차단.
    (tmp_path / "vdev-tiers.yaml").write_text(
        "tiers:\n  dev:\n    gates: [review, doc-sync]\n", encoding="utf-8"
    )
    (tmp_path / ".claude").mkdir()
    assert _run_main(tmp_path).returncode == 2


def test_main_allows_when_policy_unparseable(tmp_path: Path):
    # vdev-tiers.yaml 이 존재하나 파싱 깨짐(내부 오류) + 미분류 → FAIL-OPEN(차단 안 함).
    # Invariant #1: 깨진 정책 파일은 "정상 작동"이 아니므로 fail-closed 대상이 아님.
    (tmp_path / "vdev-tiers.yaml").write_text("tiers: [unclosed\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    assert _run_main(tmp_path).returncode == 0


def test_main_allows_when_config_corrupt(tmp_path: Path):
    # 정책 정상 + 미분류 + vdev-config.yaml 존재하나 파싱 깨짐(내부 오류) → FAIL-OPEN.
    # config 파싱 실패는 lifecycle(staging/release) 판정을 무력화하므로, promotion 커밋이
    # "미분류"로 오차단되지 않게 차단을 보류한다(Invariant #1).
    (tmp_path / "vdev-tiers.yaml").write_text(
        "tiers:\n  dev:\n    gates: [review]\n", encoding="utf-8"
    )
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-config.yaml").write_text("branches: [unclosed\n", encoding="utf-8")
    assert _run_main(tmp_path).returncode == 0


def test_main_allows_stale_marker_other_branch(tmp_path: Path, monkeypatch):
    # tier 마커는 존재하나 다른 브랜치 것(branch-bound stale) → 현재 작업 막지 않음(fail-OPEN).
    # 다른 브랜치 판정엔 실제 브랜치명이 필요하므로 _current_branch 를 패치해 in-process 호출.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(fgc, "_current_branch", lambda _root: "branch-b")
    (tmp_path / "vdev-tiers.yaml").write_text(
        "tiers:\n  dev:\n    gates: [review, doc-sync]\n", encoding="utf-8"
    )
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:branch-a", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        fgc.main()
    assert exc.value.code == 0


def test_main_blocks_missing_dev_gate(tmp_path: Path):
    (tmp_path / "vdev-tiers.yaml").write_text(
        "tiers:\n  dev:\n    gates: [review, doc-sync]\n", encoding="utf-8"
    )
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:", encoding="utf-8")
    result = _run_main(tmp_path)
    assert result.returncode == 2
    assert "review" in result.stdout
