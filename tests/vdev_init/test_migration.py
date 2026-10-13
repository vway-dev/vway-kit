"""구버전 설치의 이전 — 경로·마커·설정 스키마.

루트에 흩어졌던 config·증거·스크립트를 `.claude/vway-kit/` 분류 위치로 옮기고,
옛 티어 마커와 최상위 `teamer:` 같은 죽은 스키마를 진단함. 신규 설치는 전부 skip
이어야 하므로, 이 파일이 재는 것은 **재실행이 안전한가**다.
"""

from pathlib import Path

from scripts.vdev_init_setup import (
    detect_legacy_alm_config,
    load_alm_config,
    migrate_legacy_paths,
    report_legacy_alm_config,
    run_setup,
)
from tests.vdev_init._helpers import (
    _mk_example,
    _mk_host_config,
)


def test_migrate_legacy_removes_flat_scripts(tmp_path: Path):
    # 구버전 평면 스크립트(.claude/vway-kit/ 직속)는 scripts/ 로 옮겨지므로 잔재 제거
    flat = tmp_path / ".claude" / "vway-kit"
    flat.mkdir(parents=True)
    (flat / "precommit-runner.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (flat / "vdev-tiers.yaml").write_text("tiers: {}\n", encoding="utf-8")
    report = migrate_legacy_paths(tmp_path)
    assert any("평면 스크립트 제거" in line for line in report)
    assert not (flat / "precommit-runner.sh").exists()
    assert not (flat / "vdev-tiers.yaml").exists()


def test_migrate_relocates_scripts_tiers_to_config(tmp_path: Path):
    # scripts/→config/ 재배치: 옛 scripts/vdev-tiers.yaml 잔재를 제거함.
    # (config/ 에는 copy_artifacts 가 새로 넣으므로 옛 위치는 잔재.)
    sd = tmp_path / ".claude" / "vway-kit" / "scripts"
    sd.mkdir(parents=True)
    (sd / "vdev-tiers.yaml").write_text("tiers: {}\n", encoding="utf-8")
    report = migrate_legacy_paths(tmp_path)
    assert not (sd / "vdev-tiers.yaml").exists()
    assert any("재배치 잔재" in line for line in report)


def test_migrate_legacy_idempotent_and_no_clobber(tmp_path: Path):
    # 신규 설치(옛 경로 없음) → skip; 새 경로가 이미 있으면 옛 것을 덮지 않음
    assert any("없음" in line for line in migrate_legacy_paths(tmp_path))
    vd = tmp_path / ".claude" / "vway-kit"
    (vd / "config").mkdir(parents=True, exist_ok=True)
    (vd / "config" / "vdev-config.yaml").write_text("new\n", encoding="utf-8")
    (tmp_path / "vdev-config.yaml").write_text("old\n", encoding="utf-8")
    migrate_legacy_paths(tmp_path)
    assert (vd / "config" / "vdev-config.yaml").read_text(encoding="utf-8") == "new\n"  # 보존
    assert (tmp_path / "vdev-config.yaml").read_text(encoding="utf-8") == "old\n"  # 미이전


def test_migrate_flow_config_to_vdev_config(tmp_path: Path):
    # flow→vdev 재명명 마이그레이션: config/flow-config.yaml → config/vdev-config.yaml (무손실)
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "flow-config.yaml").write_text("branches:\n  integration: dev\n", encoding="utf-8")
    report = migrate_legacy_paths(tmp_path)
    assert (cfg_dir / "vdev-config.yaml").read_text(encoding="utf-8") == (
        "branches:\n  integration: dev\n"
    )
    assert not (cfg_dir / "flow-config.yaml").exists()
    assert any("vdev-config.yaml" in line for line in report)


def test_migrate_flow_evidence_dir_to_vdev(tmp_path: Path):
    # .claude/vway-kit/.flow/ → .claude/vway-kit/.vdev/ (게이트 증거 디렉터리 재명명)
    old = tmp_path / ".claude" / "vway-kit" / ".flow"
    old.mkdir(parents=True)
    (old / "tier").write_text("dev:", encoding="utf-8")
    migrate_legacy_paths(tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / ".vdev" / "tier").is_file()
    assert not old.exists()


def test_migrate_removes_renamed_orphan_scripts(tmp_path: Path):
    # 옛 이름 스크립트 사본(flow_gate_check.py·flow-tiers.yaml)을 scripts/ 에서 제거
    sd = tmp_path / ".claude" / "vway-kit" / "scripts"
    sd.mkdir(parents=True)
    (sd / "flow_gate_check.py").write_text("# old", encoding="utf-8")
    (sd / "flow-tiers.yaml").write_text("tiers: {}\n", encoding="utf-8")
    report = migrate_legacy_paths(tmp_path)
    assert not (sd / "flow_gate_check.py").exists()
    assert not (sd / "flow-tiers.yaml").exists()
    assert any("flow_gate_check.py" in line for line in report)


def test_migrate_flow_config_no_clobber(tmp_path: Path):
    # 새 vdev-config.yaml 이 이미 있으면 옛 flow-config.yaml 로 덮지 않는다(설정 보존)
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-config.yaml").write_text("new\n", encoding="utf-8")
    (cfg_dir / "flow-config.yaml").write_text("old\n", encoding="utf-8")
    migrate_legacy_paths(tmp_path)
    assert (cfg_dir / "vdev-config.yaml").read_text(encoding="utf-8") == "new\n"
    assert (cfg_dir / "flow-config.yaml").read_text(encoding="utf-8") == "old\n"


def test_migrate_prefers_config_flow_over_root_flow(tmp_path: Path):
    # #1: config/flow-config.yaml(정규 팀 설정)이 root flow-config.yaml(stale)보다 우선해야 함
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "flow-config.yaml").write_text("REAL\n", encoding="utf-8")  # 정규 위치
    (tmp_path / "flow-config.yaml").write_text("STALE\n", encoding="utf-8")  # 옛 루트 flat
    migrate_legacy_paths(tmp_path)
    assert (cfg_dir / "vdev-config.yaml").read_text(encoding="utf-8") == "REAL\n"


def test_migrate_translates_standard_tier_marker(tmp_path: Path):
    # #3: 옛 standard tier 마커를 dev 로 번역(미번역 시 unknown tier → FAIL-OPEN 게이트 우회)
    flow = tmp_path / ".claude" / "vway-kit" / ".flow"
    flow.mkdir(parents=True)
    (flow / "tier").write_text("standard:feature/x", encoding="utf-8")
    migrate_legacy_paths(tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / ".vdev" / "tier").read_text(
        encoding="utf-8"
    ) == "dev:feature/x"


def test_migrate_translates_fast_tier_marker(tmp_path: Path):
    flow = tmp_path / ".claude" / "vway-kit" / ".flow"
    flow.mkdir(parents=True)
    (flow / "tier").write_text("fast:", encoding="utf-8")
    migrate_legacy_paths(tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / ".vdev" / "tier").read_text(
        encoding="utf-8"
    ) == "docs:"


def test_apply_migrations_failopen_on_migration_error(tmp_path):
    from scripts import vdev_init_setup as m

    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"vway-kit","version":"1.0.0"}', encoding="utf-8"
    )
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)

    def bad_mig(h, p):
        raise RuntimeError("boom")

    reg = {"1.0.0": bad_mig}
    # 마이그레이션 예외가 발생해도 FAIL-OPEN — 예외를 전파하지 않고 버전 기록함
    result = m.apply_migrations(host, plugin, registry=reg)
    assert any("실패" in line for line in result)
    # 버전은 여전히 기록됨(FAIL-OPEN)
    assert m.applied_version(host) == "1.0.0"


def test_apply_migrations_empty_registry(tmp_path):
    from scripts import vdev_init_setup as m

    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"vway-kit","version":"0.3.0"}', encoding="utf-8"
    )
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    # 빈 레지스트리(MIGRATIONS = {})라도 버전 기록은 됨
    result = m.apply_migrations(host, plugin, registry={})
    assert m.applied_version(host) == "0.3.0"
    assert any("기록" in line for line in result)


def test_plugin_version_fallback(tmp_path):
    from scripts import vdev_init_setup as m

    # plugin.json 없음 → 0.0.0 fallback
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    assert m.plugin_version(plugin) == "0.0.0"


def test_apply_migrations_marker_gitignored(tmp_path):
    # VERSION_MARKER_PATH 가 GITIGNORE_LINES 에 포함되어 있어야 함 —
    # append_gitignore(run_setup 에서 호출)가 이 경로를 .gitignore 에 자동 추가함.
    from scripts import vdev_init_setup as m

    assert m.VERSION_MARKER_PATH in m.GITIGNORE_LINES
    assert m.VERSION_MARKER_PATH == ".claude/vway-kit/.applied-version"

    # append_gitignore 를 호출하면 실제로 .gitignore 에 기록됨
    host = tmp_path / "host"
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    m.append_gitignore(host)
    gi_content = (host / ".gitignore").read_text(encoding="utf-8")
    assert m.VERSION_MARKER_PATH in gi_content


def test_load_alm_config_prefers_alm_block_over_legacy(tmp_path: Path):
    # alm: 이 생기면 최상위 teamer: 는 조용히 죽음 — report_legacy_alm_config 가
    # 존재하는 이유이자, 슬롯 백필이 example 을 그대로 넣으면 안 되는 이유.
    host = tmp_path / "host"
    _mk_host_config(
        host,
        'teamer:\n  project_no: "111"\n'
        'alm:\n  provider: recoble\n  teamer:\n    project_no: "996"\n',
    )
    alm = load_alm_config(host)
    assert alm["provider"] == "recoble"
    assert alm["teamer"]["project_no"] == "996"


def test_load_alm_config_absent_is_empty(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, "branches:\n  integration: dev\n")
    assert load_alm_config(host) == {}


# ── 폐기된 최상위 teamer: 진단 (I3 — 슬롯 백필이 못 잡는 잔재) ───────────────────────


def test_detect_legacy_alm_config_flags_top_level_teamer(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, 'teamer:\n  project_no: "111"\n  workflow_no: "333"\n')
    diag = detect_legacy_alm_config(host)
    assert diag["present"] is True
    assert diag["alm_present"] is False and diag["alm_teamer_covered"] is False
    assert diag["fields"]["project_no"] == "111"


def test_detect_legacy_alm_config_absent_and_parse_fail_failopen(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, "alm:\n  provider: recoble\n")
    assert detect_legacy_alm_config(host)["present"] is False
    _mk_host_config(host, "teamer:\n  project_no: [unclosed\n")
    assert detect_legacy_alm_config(host)["present"] is False


def test_report_legacy_alm_config_warns_when_alm_absent(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, 'teamer:\n  project_no: "111"\n')
    out = report_legacy_alm_config(host)
    assert any("[!]" in ln for ln in out)
    assert any("project_no=111" in ln for ln in out)
    assert any("alm.teamer" in ln for ln in out)


def test_report_legacy_alm_config_warns_when_already_dead(tmp_path: Path):
    # I3 의 해로운 상태: alm: 이 들어와 최상위 teamer: 가 이미 무시되고 있음.
    host = tmp_path / "host"
    _mk_host_config(host, 'teamer:\n  project_no: "111"\nalm:\n  provider: recoble\n')
    out = report_legacy_alm_config(host)
    assert any("[!]" in ln for ln in out)
    assert any("무시" in ln for ln in out)


def test_report_legacy_alm_config_warns_on_value_mismatch(tmp_path: Path):
    # I3 그대로: 슬롯 백필이 example 의 예시 번호를 넣어 호스트 값이 죽은 상태.
    # 커버돼 있다는 이유로 [i] 로 넘기면 가장 해로운 경우가 조용히 지나감.
    host = tmp_path / "host"
    _mk_host_config(
        host,
        'teamer:\n  project_no: "111"\n'
        'alm:\n  provider: recoble\n  teamer:\n    project_no: "996"\n',
    )
    diag = detect_legacy_alm_config(host)
    assert diag["alm_teamer_covered"] is True and diag["alm_teamer_matches"] is False
    out = report_legacy_alm_config(host)
    assert any("[!]" in ln for ln in out)
    assert any("project_no=111" in ln for ln in out)


def test_report_legacy_alm_config_info_when_migrated(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(
        host,
        'teamer:\n  project_no: "111"\n'
        'alm:\n  provider: teamer\n  teamer:\n    project_no: "111"\n',
    )
    assert detect_legacy_alm_config(host)["alm_teamer_matches"] is True
    out = report_legacy_alm_config(host)
    assert any("[i]" in ln for ln in out)
    assert not any("[!]" in ln for ln in out)


def test_report_legacy_alm_config_absent_skip(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, "branches:\n  integration: dev\n")
    assert report_legacy_alm_config(host) == ["  [=] 폐기된 최상위 teamer: 없음 (skip)"]


def test_run_setup_reports_legacy_alm_config(tmp_path: Path, capsys):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "branches:\n  integration: dev\n")
    _mk_host_config(host, 'teamer:\n  project_no: "111"\n')
    run_setup(host, plugin)
    captured = capsys.readouterr().out
    assert "[폐기 필드 점검]" in captured
    assert "폐기된 최상위 teamer:" in captured


def test_migrate_legacy_moves_root_files(tmp_path: Path):
    # 구버전 루트 분산 config → config/, .claude/.vdev → vway-kit/.vdev 로 무손실 이전
    (tmp_path / "vdev-config.yaml").write_text("branches: {}\n", encoding="utf-8")
    vdev = tmp_path / ".claude" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:", encoding="utf-8")
    report = migrate_legacy_paths(tmp_path)
    assert any("이전" in line for line in report)
    vd = tmp_path / ".claude" / "vway-kit"
    assert (vd / "config" / "vdev-config.yaml").read_text(encoding="utf-8") == "branches: {}\n"
    assert (vd / ".vdev" / "tier").is_file()
    assert not (tmp_path / "vdev-config.yaml").exists()  # 옛 경로 제거됨
    assert not (tmp_path / ".claude" / ".vdev").exists()


def test_apply_migrations_records_version(tmp_path):
    from scripts import vdev_init_setup as m

    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"vway-kit","version":"0.2.0"}', encoding="utf-8"
    )
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    ran = []
    reg = {"0.2.0": lambda h, p: ran.append("mig-0.2.0")}
    # 최초: applied 없음 → 등록된 0.2.0 마이그레이션 실행 + 버전 기록
    m.apply_migrations(host, plugin, registry=reg)
    assert ran == ["mig-0.2.0"]
    assert m.applied_version(host) == "0.2.0"
    # 버전 마커는 gitignored 경로에 기록된다(.applied-version — config/ 아님)
    marker = host / ".claude" / "vway-kit" / ".applied-version"
    assert marker.is_file()
    # 재실행: 같은 버전 → 마이그레이션 재실행 안 함(멱등)
    m.apply_migrations(host, plugin, registry=reg)
    assert ran == ["mig-0.2.0"]


def test_load_alm_config_legacy_top_level_teamer(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, 'teamer:\n  project_no: "111"\n  workitem_no: "222"\n')
    alm = load_alm_config(host)
    assert alm["provider"] == "teamer" and alm["auto"] is False
    assert alm["teamer"]["project_no"] == "111"
