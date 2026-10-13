"""vdev-config.yaml 의 슬롯 백필과 값 진단.

example 에 새 섹션이 생겼을 때 호스트 설정에 빠진 슬롯을 찾아내되 **값은 건드리지
않음**. 폐기된 전역 `test.command`·잘못된 `checks.when` 처럼 파싱은 되지만 뜻이
없는 값의 진단도 여기 모임.
"""

from pathlib import Path

import yaml as _yaml

from scripts.vdev_init_setup import (
    detect_check_timing_issues,
    detect_legacy_test_command,
    missing_config_slots,
    report_alm_layers,
    report_check_timing,
    report_legacy_test_command,
    report_missing_config_slots,
    run_setup,
)
from tests.vdev_init._helpers import (
    PLUGIN,
    _mk_example,
    _mk_host_config,
)


def test_missing_config_slots_top_level_section(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "branches:\n  integration: dev\ncontract_test:\n  enable: true\n")
    _mk_host_config(host, "branches:\n  integration: dev\n")
    assert missing_config_slots(host, plugin) == [
        {"path": ["contract_test"], "parent": [], "label": "contract_test"}
    ]


def test_missing_config_slots_nested_key(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "test:\n  command: x\n  coverage_threshold: 80\n")
    _mk_host_config(host, "test:\n  command: x\n")
    assert missing_config_slots(host, plugin) == [
        {
            "path": ["test", "coverage_threshold"],
            "parent": ["test"],
            "label": "test.coverage_threshold",
        }
    ]


def test_missing_config_slots_empty_value_preserved(tmp_path: Path):
    # host 에 키가 있고 값이 비어도(빈 문자열/null) 빠짐으로 보지 않음.
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "doc_sync:\n  service_docs: services/*/CLAUDE.md\n")
    _mk_host_config(host, 'doc_sync:\n  service_docs: ""\n')
    assert missing_config_slots(host, plugin) == []


def test_missing_config_slots_all_present(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "test:\n  command: x\n")
    _mk_host_config(host, "test:\n  command: x\n  extra: y\n")
    assert missing_config_slots(host, plugin) == []


def test_missing_config_slots_handoff_kind_nested(tmp_path: Path):
    # handoff 흡수: 섹션은 있고 종류만 빠지면 parent=["handoff"] 슬롯.
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(
        plugin,
        "handoff:\n  summary:\n    enable: true\n  done_flag:\n    enable: false\n",
    )
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n")
    assert missing_config_slots(host, plugin) == [
        {"path": ["handoff", "done_flag"], "parent": ["handoff"], "label": "handoff.done_flag"}
    ]


def test_missing_config_slots_section_absent_inserts_whole(tmp_path: Path):
    # host 에 handoff 섹션 자체가 없으면 섹션 통째가 삽입 단위.
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "handoff:\n  summary:\n    enable: true\n")
    _mk_host_config(host, "branches:\n  integration: dev\n")
    assert missing_config_slots(host, plugin) == [
        {"path": ["handoff"], "parent": [], "label": "handoff"}
    ]


def test_missing_config_slots_order_preserved(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "a: 1\nb: 2\nc: 3\n")
    _mk_host_config(host, "b: 2\n")
    assert [s["label"] for s in missing_config_slots(host, plugin)] == ["a", "c"]


def test_missing_config_slots_host_absent(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "branches:\n  integration: dev\nhandoff:\n  summary:\n    enable: true\n")
    # host config 파일 없음 → example 최상위 전부
    assert [s["label"] for s in missing_config_slots(host, plugin)] == ["branches", "handoff"]


def test_missing_config_slots_host_parse_fail(tmp_path: Path):
    # 망가진 host YAML → _load_yaml_safe 가 {} → example 최상위 전부(absent 와 동등).
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "branches:\n  integration: dev\ntest:\n  command: x\n")
    _mk_host_config(host, "branches:\n  integration: [unclosed\n")
    assert [s["label"] for s in missing_config_slots(host, plugin)] == ["branches", "test"]


def test_missing_config_slots_example_absent(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_host_config(host, "branches:\n  integration: dev\n")
    assert missing_config_slots(host, plugin) == []


def test_report_missing_config_slots_lists_new(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "test:\n  command: x\ncontract_test:\n  enable: true\n")
    _mk_host_config(host, "test:\n  command: x\n")
    out = report_missing_config_slots(host, plugin)
    assert any("contract_test" in line for line in out)
    assert any("/vdev-init" in line for line in out)


def test_report_missing_config_slots_skip_when_current(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "test:\n  command: x\n")
    _mk_host_config(host, "test:\n  command: x\n")
    assert report_missing_config_slots(host, plugin) == ["  [=] config 슬롯 최신 (skip)"]


def test_run_setup_reports_config_slots(tmp_path: Path, capsys):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "test:\n  command: x\ncontract_test:\n  enable: true\n")
    _mk_host_config(host, "test:\n  command: x\n")
    run_setup(host, plugin)
    captured = capsys.readouterr().out
    assert "[config 슬롯 점검]" in captured


# ── 폐기된 전역 test.command 진단 (재실행 마이그레이션) ──────────────────────────


def test_detect_legacy_test_command_absent(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, "branches:\n  integration: dev\n")
    diag = detect_legacy_test_command(host)
    assert diag == {"present": False, "command": None, "module_test_covered": False}


def test_detect_legacy_test_command_present_uncovered(tmp_path: Path):
    # 전역 test.command 있고 modules 없음 → 미커버(먼저 이전해야 함).
    host = tmp_path / "host"
    _mk_host_config(host, "test:\n  command: bash scripts/test.sh\n  coverage_threshold: 80\n")
    diag = detect_legacy_test_command(host)
    assert diag["present"] is True
    assert diag["command"] == "bash scripts/test.sh"
    assert diag["module_test_covered"] is False


def test_detect_legacy_test_command_present_covered(tmp_path: Path):
    # 전역 test.command 있고 modules[].checks.test 존재 → 커버(안전 제거).
    host = tmp_path / "host"
    _mk_host_config(
        host,
        "test:\n  command: pytest\n"
        "modules:\n  - name: api\n    path: services/api/\n"
        "    checks:\n      test: uv run pytest services/api\n",
    )
    diag = detect_legacy_test_command(host)
    assert diag["present"] is True
    assert diag["module_test_covered"] is True


def test_detect_legacy_test_command_no_command_key(tmp_path: Path):
    # test: 블록은 있으나 command 키가 없으면 잔재로 보지 않는다(오탐 방지).
    host = tmp_path / "host"
    _mk_host_config(host, "test:\n  coverage_threshold: 80\n")
    assert detect_legacy_test_command(host)["present"] is False


def test_detect_legacy_test_command_parse_fail_failopen(tmp_path: Path):
    # 망가진 host YAML → _load_yaml_safe {} → present=False(FAIL-OPEN, 셋업 안 막음).
    host = tmp_path / "host"
    _mk_host_config(host, "test:\n  command: [unclosed\n")
    assert detect_legacy_test_command(host)["present"] is False


def test_report_legacy_test_command_uncovered_warns(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, "test:\n  command: bash scripts/test.sh\n")
    out = report_legacy_test_command(host)
    assert any("[!]" in ln for ln in out)
    assert any("bash scripts/test.sh" in ln for ln in out)
    assert any("modules[].checks.test" in ln for ln in out)


def test_report_legacy_test_command_covered_info(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(
        host,
        "test:\n  command: pytest\n"
        "modules:\n  - name: api\n    path: services/api/\n"
        "    checks:\n      test: uv run pytest\n",
    )
    out = report_legacy_test_command(host)
    assert any("[i]" in ln for ln in out)
    assert not any("[!]" in ln for ln in out)


def test_report_legacy_test_command_absent_skip(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, "branches:\n  integration: dev\n")
    assert report_legacy_test_command(host) == ["  [=] 폐기된 전역 test.command 없음 (skip)"]


def test_run_setup_reports_legacy_test_command(tmp_path: Path, capsys):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "branches:\n  integration: dev\n")
    _mk_host_config(host, "test:\n  command: bash scripts/test.sh\n")
    run_setup(host, plugin)
    captured = capsys.readouterr().out
    assert "[폐기 필드 점검]" in captured
    assert "bash scripts/test.sh" in captured


# ── checks.when 타이밍 값 검증 (작성 시점 엄격 점검, 런타임 fail-open 과 이중화) ──────


def test_detect_check_timing_flags_bad_when(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(
        host,
        "modules:\n"
        "  - name: api\n    path: services/api/\n"
        "    checks:\n"
        "      lint: 'ruff check'\n"
        "      perf: { run: 'pytest bench', when: promotion }\n"
        "      audit: { run: 'pip-audit', when: bogus }\n",
    )
    issues = detect_check_timing_issues(host)
    assert issues == [{"module": "api", "check": "audit", "when": "bogus"}]


def test_detect_check_timing_clean_config_empty(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(
        host,
        "modules:\n  - name: api\n    path: services/api/\n    checks:\n      lint: 'ruff check'\n",
    )
    assert detect_check_timing_issues(host) == []


def test_detect_check_timing_dict_without_when_not_flagged(tmp_path: Path):
    # dict 형식이라도 when 이 완전히 생략되면 진단하지 않음("when" not in val).
    # 문자열 값·유효한 when 값도 함께 섞어 "생략만 조용히 통과"를 명확히 보임.
    host = tmp_path / "host"
    _mk_host_config(
        host,
        "modules:\n"
        "  - name: api\n    path: services/api/\n"
        "    checks:\n"
        "      lint: 'ruff check'\n"
        "      typecheck: { run: 'mypy .' }\n"
        "      perf: { run: 'pytest bench', when: promotion }\n",
    )
    assert detect_check_timing_issues(host) == []


def test_detect_check_timing_failopen_no_config(tmp_path: Path):
    # config 부재·파싱 실패 → [] (FAIL-OPEN, 셋업을 막지 않음).
    host = tmp_path / "host"
    assert detect_check_timing_issues(host) == []


def test_report_check_timing_warns_on_issue(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(
        host,
        "modules:\n  - name: api\n    path: services/api/\n"
        "    checks:\n      audit: { run: 'pip-audit', when: bogus }\n",
    )
    lines = report_check_timing(host)
    assert any("audit" in ln and "bogus" in ln for ln in lines)


def test_report_check_timing_clean_skip(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_config(host, "branches:\n  integration: dev\n")
    assert report_check_timing(host) == ["  [=] checks.when 타이밍 값 정상 (skip)"]


def test_run_setup_reports_check_timing(tmp_path: Path, capsys):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    _mk_example(plugin, "branches:\n  integration: dev\n")
    _mk_host_config(
        host,
        "modules:\n  - name: api\n    path: services/api/\n"
        "    checks:\n      audit: { run: 'pip-audit', when: bogus }\n",
    )
    run_setup(host, plugin)
    captured = capsys.readouterr().out
    assert "[checks 타이밍 점검]" in captured
    assert "audit" in captured


def test_example_config_ships_the_recoble_propagate_slot():
    """전파 설정이 example 에서 조용히 빠지면 호스트는 슬롯이 있는 줄도 모름 —
    /vdev-init 의 슬롯 백필이 채워 넣는 것이 이 블록."""
    ex = _yaml.safe_load((PLUGIN / "vdev-config.example.yaml").read_text(encoding="utf-8"))
    prop = ex["alm"]["recoble"]["propagate"]
    assert set(prop) == {"enable", "links", "progress", "status", "depth"}
    # hierarchy/derives/verifies 는 Recoble 시스템 링크 유형 code 에 대응함 — 오타가
    # 나면 그 경로만 조용히 안 걸리고 전파가 절반만 돎.
    assert set(prop["links"]) <= {"parent", "hierarchy", "derives", "verifies"}
    assert "parent" in prop["links"] and "hierarchy" in prop["links"]
    assert prop["status"] in {"all-done", "ask", "off"}


def test_example_config_shows_a_per_provider_handoff_field():
    """field 가 dict 를 받는다는 것은 example 에서만 보임 — 문자열 예시만 남으면
    Recoble 사용자는 종류별 필드를 쓸 수 있다는 사실에 도달하지 못함."""
    ex = _yaml.safe_load((PLUGIN / "vdev-config.example.yaml").read_text(encoding="utf-8"))
    fields = [spec.get("field") for spec in ex["handoff"].values() if isinstance(spec, dict)]
    assert any(isinstance(f, dict) and "recoble" in f for f in fields), (
        "provider 별 field 매핑 예시가 없다"
    )


def _layers_config(layers_yaml: str) -> str:
    """layers 선언 하나만 다른 최소 호스트 config."""
    return (
        "alm:\n"
        "  recoble:\n"
        "    default: labs\n"
        "    spaces:\n"
        "      labs:\n"
        "        workboard: dev\n" + layers_yaml
    )


def test_report_alm_layers_skips_when_undeclared(tmp_path: Path):
    """계층 추적은 옵트인 — 안 쓰는 호스트에 할 말이 없어야 함."""
    _mk_host_config(tmp_path, _layers_config(""))
    assert report_alm_layers(tmp_path, PLUGIN) == ["  [=] ALM 계층 선언 없음 (skip)"]


def test_report_alm_layers_names_the_resolved_layers(tmp_path: Path):
    _mk_host_config(
        tmp_path,
        _layers_config(
            "        layers:\n"
            "          requirement:\n"
            "            workboard: 요구사항\n"
            "          task:\n"
            "            workboard: 작업\n"
            "            derives_from: requirement\n"
            "            marker: true\n"
        ),
    )
    assert report_alm_layers(tmp_path, PLUGIN) == ["  [=] labs: 계층 2개 (requirement, task)"]


def test_report_alm_layers_surfaces_a_broken_declaration(tmp_path: Path):
    """깨진 선언이 셋업에서 조용하면 alm-trace 를 처음 부르는 순간에야 드러남 — 그때는
    이미 호스트가 계층 추적이 켜진 줄 알고 보드를 만들어 둔 뒤."""
    _mk_host_config(
        tmp_path,
        _layers_config(
            "        layers:\n"
            "          requirement:\n"
            "            marker: true\n"
            "          task:\n"
            "            workboard: 작업\n"
            "            marker: true\n"
        ),
    )
    lines = report_alm_layers(tmp_path, PLUGIN)
    assert any("workboard 가 없다" in x for x in lines), lines
    assert any("marker 가 둘 이상" in x for x in lines), lines
    assert all(x.startswith("  [!] labs:") for x in lines), lines


def test_report_alm_layers_warns_when_no_marker(tmp_path: Path):
    """marker 없는 선언은 항목과 링크는 만들되 작업 문서·task-sync 가 안 돎 — 실행은
    되므로 errors 가 아니라 경고, 다만 말은 해야 함."""
    _mk_host_config(
        tmp_path,
        _layers_config(
            "        layers:\n          requirement:\n            workboard: 요구사항\n"
        ),
    )
    lines = report_alm_layers(tmp_path, PLUGIN)
    assert any(x.startswith("  [~] labs:") and "marker 계층 없음" in x for x in lines), lines
    assert "  [=] labs: 계층 1개 (requirement)" in lines
