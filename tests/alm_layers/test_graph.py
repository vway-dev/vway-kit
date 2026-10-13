"""계층 그래프 — 위상 순서·링크 판정·marker/defect/run 유일성.

무엇을 먼저 만들어야 앵커가 서는가, 그리고 어떤 선언이 실행을 세우는가."""

from pathlib import Path

from scripts.alm_layers import resolve_layers
from tests.alm_layers._helpers import resolve, write_config


def test_resolve_layers_topological_order(tmp_path: Path):
    # 선언 순서는 design → requirement 지만, 의존 순서는 그 반대임.
    got = resolve(
        tmp_path,
        "          design:\n"
        "            workboard: 설계\n"
        "            derives_from: requirement\n"
        "          requirement:\n"
        "            workboard: 요구사항\n",
    )
    assert [x["key"] for x in got["layers"]] == ["requirement", "design"]
    assert got["errors"] == []


def test_resolve_layers_verifies_orders_target_first(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          verification:\n"
        "            workboard: 결함 관리\n"
        "            verifies: requirement\n"
        "          requirement:\n"
        "            workboard: 요구사항\n",
    )
    assert [x["key"] for x in got["layers"]] == ["requirement", "verification"]


def test_resolve_layers_cycle_is_error(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          a:\n            workboard: A\n            derives_from: b\n"
        "          b:\n            workboard: B\n            derives_from: a\n",
    )
    assert got["layers"] == []
    assert any("순환" in e for e in got["errors"])


def test_resolve_layers_unknown_reference_drops_link(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          design:\n            workboard: 설계\n            derives_from: analysis\n",
    )
    assert got["errors"] == []
    assert got["layers"][0]["derives_from"] is None
    assert any("analysis" in w for w in got["warnings"])


def test_resolve_layers_two_markers_is_error(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          a:\n            workboard: A\n            marker: true\n"
        "          b:\n            workboard: B\n            marker: true\n",
    )
    assert got["layers"] == []
    assert any("marker" in e for e in got["errors"])


def test_resolve_layers_no_marker_is_warning_only(tmp_path: Path):
    got = resolve(tmp_path, "          a:\n            workboard: A\n")
    assert got["errors"] == []
    assert [x["key"] for x in got["layers"]] == ["a"]
    assert any("marker" in w for w in got["warnings"])


def test_resolve_layers_missing_workboard_is_error(tmp_path: Path):
    got = resolve(tmp_path, "          a:\n            template: alm/a.md\n")
    assert got["layers"] == []
    assert any("workboard" in e for e in got["errors"])


def test_resolve_layers_non_dict_layer_warns_and_skips(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          a:\n            workboard: A\n            marker: true\n          b: 설계\n",
    )
    assert [x["key"] for x in got["layers"]] == ["a"]
    assert any("b" in w for w in got["warnings"])


def test_resolve_layers_absent_block_is_unconfigured(tmp_path: Path):
    body = "alm:\n  recoble:\n    default: dev3\n    spaces:\n      dev3:\n        workboard: b\n"
    got = resolve_layers(write_config(tmp_path, body), None, tmp_path, tmp_path)
    assert got["configured"] is False
    assert got["layers"] == []
    assert got["errors"] == []


def test_resolve_layers_broken_config_is_fail_open(tmp_path: Path):
    got = resolve_layers(write_config(tmp_path, "alm: [unclosed"), None, tmp_path, tmp_path)
    assert got["configured"] is False
    assert got["errors"] == []


def test_resolve_layers_rejects_two_defect_layers(tmp_path: Path):
    """둘이면 결함을 어느 보드에 만들지 알 수 없음 — marker 와 같은 판정."""
    got = resolve(
        tmp_path,
        "          requirement:\n            workboard: 요구사항\n"
        "          task:\n            workboard: 작업\n"
        "            derives_from: requirement\n            marker: true\n"
        "          defect:\n            workboard: 결함\n"
        "            verifies: requirement\n            defect: true\n"
        "          bug:\n            workboard: 버그\n"
        "            verifies: requirement\n            defect: true\n",
    )
    assert any("defect 계층이 둘 이상" in x for x in got["errors"]), got
    assert got["layers"] == [], "errors 가 있으면 만들 순서를 내지 않음"


def test_resolve_layers_warns_when_defect_cannot_attach_or_fix(tmp_path: Path):
    """켜 놓고 못 쓰는 두 모양 — 걸 대상이 없고, 수정 작업을 둘 자리도 없음.

    실행 도중 사람이 '결함' 을 고른 뒤에 발견되면 남는 선택지가 중단뿐이라 여기서 봄.
    """
    got = resolve(
        tmp_path,
        "          requirement:\n            workboard: 요구사항\n"
        "          defect:\n            workboard: 결함\n            defect: true\n",
    )
    assert got["errors"] == [], got
    assert any("verifies 미선언" in x for x in got["warnings"]), got
    assert any("marker 계층이 없어" in x for x in got["warnings"]), got


def test_resolve_layers_quiet_when_defect_layer_is_usable(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          requirement:\n            workboard: 요구사항\n"
        "          task:\n            workboard: 작업\n"
        "            derives_from: requirement\n            marker: true\n"
        "          defect:\n            workboard: 결함\n"
        "            verifies: requirement\n            defect: true\n",
    )
    assert got["errors"] == [], got
    unusable = [x for x in got["warnings"] if "verifies 미선언" in x or "marker 계층이 없어" in x]
    assert unusable == [], unusable
    assert [x["key"] for x in got["layers"] if x["defect"]] == ["defect"]


def test_resolve_layers_run_layer_is_outside_propagation(tmp_path: Path):
    """회차는 relates_to 로만 붙음 — 링크를 걸면 상위의 하위집합에 섞여 분모를 흐림."""
    got = resolve(
        tmp_path,
        "          requirement:\n            workboard: 요구사항\n"
        "          verification:\n            workboard: 테스트 케이스\n"
        "            verifies: requirement\n"
        "          run:\n            workboard: 테스트 실행\n"
        "            run: true\n            runs: verification\n"
        "            verifies: requirement\n",
    )
    run = next(x for x in got["layers"] if x["key"] == "run")
    assert run["run"] is True
    assert run["runs"] == "verification"
    assert run["verifies"] is None
    assert any("전파" in w for w in got["warnings"]), got["warnings"]


def test_resolve_layers_two_run_layers_is_an_error(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          a:\n            workboard: A\n            run: true\n"
        "          b:\n            workboard: B\n            run: true\n",
    )
    assert any("run 계층이 둘 이상" in e for e in got["errors"]), got["errors"]


def test_resolve_layers_run_with_unknown_target_warns(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          run:\n            workboard: 테스트 실행\n"
        "            run: true\n            runs: nope\n",
    )
    run = next(x for x in got["layers"] if x["key"] == "run")
    assert run["runs"] is None
    assert any("runs" in w for w in got["warnings"]), got["warnings"]


def test_resolve_layers_run_without_runs_warns(tmp_path: Path):
    """켜 놓고 못 쓰게 된 선언은 알림 — defect 의 verifies 미선언 경고와 같은 꼴."""
    got = resolve(
        tmp_path,
        "          run:\n            workboard: 테스트 실행\n            run: true\n",
    )
    assert any("runs 미선언" in w for w in got["warnings"]), got["warnings"]


def test_resolve_layers_link_pointing_at_a_run_layer_is_dropped(tmp_path: Path):
    """회차를 **가리키는** 링크도 막아야 함 — 한쪽만 막으면 회차가 하위집합에 그대로 쌓임."""
    got = resolve(
        tmp_path,
        "          run:\n            workboard: 테스트 실행\n"
        "            run: true\n            runs: verification\n"
        "          verification:\n            workboard: 테스트 케이스\n"
        "            verifies: run\n",
    )
    verification = next(x for x in got["layers"] if x["key"] == "verification")
    assert verification["verifies"] is None
    assert any("회차를 가리키는" in w for w in got["warnings"]), got["warnings"]
