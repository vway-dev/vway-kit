"""기능 설계 계층 — `feature_design` 플래그의 검증과 직접 도출 링크(`direct_from`) 계산.

기능 설계 항목은 여러 요구사항·작업이 공유하므로 전파 밖이고, 그 아래 계층이 요구사항에
직접 걸릴 대상을 해석기가 정해 두는지 잼."""

from pathlib import Path

from scripts.alm_layers import normalize_layer
from tests.alm_layers._helpers import resolve

CHAIN = (
    "          requirement:\n            workboard: 요구사항\n"
    "          design:\n            workboard: 설계\n"
    "            derives_from: requirement\n            feature_design: true\n"
    "          task:\n            workboard: 개발 작업\n"
    "            derives_from: design\n            marker: true\n"
)


def _layer(got: dict, key: str) -> dict:
    return next(x for x in got["layers"] if x["key"] == key)


def test_normalize_layer_defaults_carry_the_new_keys(tmp_path: Path):
    got = normalize_layer("design", {"workboard": "설계"}, tmp_path, tmp_path)
    assert got["feature_design"] is False
    assert got["direct_from"] is None


def test_a_layer_under_the_feature_design_gets_a_direct_link_target(tmp_path: Path):
    got = resolve(tmp_path, CHAIN)
    assert got["errors"] == [], got["errors"]
    assert _layer(got, "design")["feature_design"] is True
    assert _layer(got, "task")["direct_from"] == "requirement"
    assert _layer(got, "requirement")["direct_from"] is None
    assert _layer(got, "design")["direct_from"] is None


def test_the_flag_is_not_an_unknown_declaration(tmp_path: Path):
    got = resolve(tmp_path, CHAIN)
    assert [w for w in got["warnings"] if "모르는 선언" in w] == []


def test_without_the_flag_nothing_gets_a_direct_link(tmp_path: Path):
    got = resolve(tmp_path, CHAIN.replace("            feature_design: true\n", ""))
    assert all(x["feature_design"] is False for x in got["layers"])
    assert all(x["direct_from"] is None for x in got["layers"])


def test_only_a_literal_true_turns_it_on(tmp_path: Path):
    got = resolve(tmp_path, CHAIN.replace("feature_design: true", 'feature_design: "yes"'))
    assert _layer(got, "design")["feature_design"] is False
    assert _layer(got, "task")["direct_from"] is None


def test_two_feature_design_layers_is_an_error(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          a:\n            workboard: A\n            feature_design: true\n"
        "          b:\n            workboard: B\n            feature_design: true\n",
    )
    assert any("feature_design 계층이 둘 이상" in e for e in got["errors"]), got["errors"]
    assert got["layers"] == []


def test_feature_design_cannot_share_a_layer_with_marker(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          a:\n            workboard: A\n"
        "            feature_design: true\n            marker: true\n",
    )
    assert any("feature_design" in e and "marker" in e for e in got["errors"]), got["errors"]


def test_feature_design_without_derives_from_warns(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          design:\n            workboard: 설계\n            feature_design: true\n"
        "          task:\n            workboard: 작업\n            derives_from: design\n",
    )
    assert got["errors"] == [], got["errors"]
    assert any("derives_from 미선언" in w for w in got["warnings"]), got["warnings"]
    assert _layer(got, "task")["direct_from"] is None


def test_verifying_the_feature_design_warns(tmp_path: Path):
    """설계를 검증하는 선언은 전파에서 함께 빠짐 — 조용히 안 돌면 아무도 모름."""
    got = resolve(
        tmp_path,
        CHAIN
        + "          review:\n            workboard: 설계 검토\n            verifies: design\n",
    )
    assert got["errors"] == [], got["errors"]
    assert any("review.verifies" in w and "전파 밖" in w for w in got["warnings"]), got["warnings"]
