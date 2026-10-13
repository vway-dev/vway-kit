"""티어 정책 로딩 — 어느 티어가 어느 게이트를 요구하는가.

`vdev-tiers.yaml` 이 tier→gates 의 SSOT 고, 그 파일을 **어디서 읽는가**(플러그인 루트 →
호스트 사본)까지가 이 파일의 계약임. `precommit`·`security-scan`·`wiki` 는 마커 없는
런타임 게이트라 `missing_gates` 가 세지 않아야 함.
"""

from pathlib import Path

import yaml

from scripts._vway_paths import RUNTIME_GATES
from scripts.vdev_gate_check import (
    load_lifecycle_branches,
    missing_gates,
    required_gates,
    tiers_path,
)


def test_lifecycle_branches_from_config(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text("branches:\n  staging: stage\n  production: main\n", encoding="utf-8")
    assert load_lifecycle_branches(cfg) == {"stage": "staging", "main": "release"}


def test_lifecycle_branches_custom_names(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text("branches:\n  staging: qa\n  production: release\n", encoding="utf-8")
    assert load_lifecycle_branches(cfg) == {"qa": "staging", "release": "release"}


def test_lifecycle_branches_missing_file(tmp_path: Path):
    assert load_lifecycle_branches(tmp_path / "absent.yaml") == {}


def test_required_gates_dev(tmp_path: Path):
    tiers = tmp_path / "vdev-tiers.yaml"
    tiers.write_text(
        "tiers:\n  dev:\n    gates: [review, doc-sync]\n",
        encoding="utf-8",
    )
    assert required_gates(tiers, "dev") == ["review", "doc-sync"]


def test_required_gates_unknown_tier(tmp_path: Path):
    tiers = tmp_path / "vdev-tiers.yaml"
    tiers.write_text("tiers:\n  docs:\n    gates: [doc-sync]\n", encoding="utf-8")
    assert required_gates(tiers, "nope") is None


def test_security_scan_is_runtime_gate_no_marker(tmp_path: Path):
    # security-scan 은 RUNTIME_GATES 에 속하므로 .done 마커 없이도 미충족에 안 들어감.
    assert "security-scan" in RUNTIME_GATES
    # release gates 중 security-scan 은 .done 검사 대상이 아님
    vdev = tmp_path / ".vdev"
    vdev.mkdir()
    # review.done 은 없고 security-scan.done 도 없지만 security-scan 은 런타임 → 제외
    result = missing_gates(vdev, ["review", "security-scan", "security"])
    assert "security-scan" not in result
    assert "review" in result
    assert "security" in result


def test_precommit_is_runtime_gate_no_marker(tmp_path: Path):
    # precommit 도 RUNTIME_GATES 에 속하므로 .done 마커 없이도 미충족에 안 들어감.
    assert "precommit" in RUNTIME_GATES
    vdev = tmp_path / ".vdev"
    vdev.mkdir()
    result = missing_gates(vdev, ["precommit", "review", "doc-sync"])
    assert "precommit" not in result
    assert "review" in result
    assert "doc-sync" in result


def test_missing_gates_skips_runtime_gates(tmp_path: Path):
    # 모든 RUNTIME_GATES 멤버는 .done 마커 없이도 missing_gates 에서 제외됨.
    vdev = tmp_path / ".vdev"
    vdev.mkdir()
    (vdev / "doc-sync.done").touch()
    # security-scan 은 런타임 게이트 → 제외됨
    assert missing_gates(vdev, ["security-scan", "review", "doc-sync"]) == ["review"]


def test_bump_is_marker_gate(tmp_path: Path):
    # bump 는 RUNTIME_GATES 가 아니므로 .done 마커가 없으면 미충족에 포함됨
    # (승격 시 bump 결정을 게이트로 강제 — 없으면 staging 커밋 차단).
    vdev = tmp_path / ".vdev"
    vdev.mkdir()
    (vdev / "review.done").touch()
    gates = ["precommit", "review", "bump", "security-scan"]
    assert missing_gates(vdev, gates) == ["bump"]  # bump.done 없음 → 차단
    (vdev / "bump.done").touch()
    assert missing_gates(vdev, gates) == []  # bump 결정 기록 후 통과


def test_staging_policy_declares_bump_gate():
    # 정책 SSOT(vdev-tiers.yaml)의 staging 티어가 bump 게이트를 선언함 — 문서 규율이
    # 아니라 게이트로 승격 bump 결정을 강제(회귀 방지).

    root = Path(__file__).resolve().parent.parent.parent
    data = yaml.safe_load((root / "vdev-tiers.yaml").read_text(encoding="utf-8"))
    assert "bump" in data["tiers"]["staging"]["gates"]


def test_release_policy_declares_no_review_gate():
    # release 티어는 코드 리뷰를 의도적으로 안 돌림 — 승격되는 diff 는 Dev 에서 태스크
    # 단위로, Staging 에서 배치로 이미 읽혔고, 이 시점의 지적은 릴리스를 되감아야 값을
    # 치름. 없음은 한 줄만 되돌아와도 조용히 사라지므로 단언으로 못박음.

    root = Path(__file__).resolve().parent.parent.parent
    data = yaml.safe_load((root / "vdev-tiers.yaml").read_text(encoding="utf-8"))
    assert "review" in data["tiers"]["staging"]["gates"]
    assert "review" not in data["tiers"]["release"]["gates"]
    assert "security" in data["tiers"]["release"]["gates"]  # 남겨 둔 리뷰 레이어


def test_tiers_path_prefers_plugin_root(tmp_path: Path, monkeypatch):
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "vdev-tiers.yaml").write_text("tiers: {}\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin))
    assert tiers_path(tmp_path / "host") == plugin / "vdev-tiers.yaml"


def test_tiers_path_falls_back_to_host_root(tmp_path: Path, monkeypatch):
    # 플러그인 루트 미설정 + config/ 복사본 부재 → 호스트 루트로 폴백
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    host = tmp_path / "host"
    host.mkdir()
    assert tiers_path(host) == host / "vdev-tiers.yaml"


def test_tiers_path_reads_the_host_config_copy(tmp_path: Path, monkeypatch):
    # 호스트 레이아웃(.claude/vway-kit/config/vdev-tiers.yaml)을 root 기준으로도 찾음.
    # __file__ 기준 탐색(2단계)은 스크립트가 호스트 사본 위치에서 *실행될* 때만 맞고,
    # 모듈이 import 되는 호출자(테스트·개발)에서는 빗나가 호스트 루트로 폴백해 버림.
    # 그러면 실제로 설치된 정책을 두고도 없는 것처럼 읽어 게이트가 조용히 fail-open 함.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    host = tmp_path / "host"
    cfg = host / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-tiers.yaml").write_text("tiers: {}\n", encoding="utf-8")
    assert tiers_path(host) == cfg / "vdev-tiers.yaml"
