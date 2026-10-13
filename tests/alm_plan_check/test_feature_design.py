"""불변식 11 — 기능 설계 계층 항목은 전파의 상위도 하위도 아님.

기능 설계 항목은 여러 요구사항·작업이 공유하는 설계서라, 그것을 상위로 닫거나 하위로 세면
한 요구사항의 완료가 설계를 공유한 다른 요구사항까지 닫음. 계층 픽스처는 생산자
(`resolve_layers`) 출력을 씀."""

from __future__ import annotations

from scripts.alm_plan_check import check_plan
from tests.alm_plan_check._helpers import (
    PROPAGATE,
    layers_via_producer,
    layers_with_feature_design,
    plan,
)


def _clean_plan() -> dict:
    p = plan()
    p["entries"][0]["layer"] = "requirement"
    p["entries"][0]["children"][0]["layer"] = "task"
    return p


def test_a_plan_that_skips_the_design_layer_is_clean(tmp_path):
    assert check_plan(_clean_plan(), layers_with_feature_design(tmp_path), PROPAGATE) == []


def test_a_feature_design_parent_is_a_violation(tmp_path):
    p = _clean_plan()
    p["entries"][0]["layer"] = "design"
    problems = check_plan(p, layers_with_feature_design(tmp_path), PROPAGATE)
    assert any("기능 설계 항목을 전파 상위로" in x for x in problems), problems


def test_a_feature_design_child_is_a_violation(tmp_path):
    p = _clean_plan()
    p["entries"][0]["children"][0]["layer"] = "design"
    problems = check_plan(p, layers_with_feature_design(tmp_path), PROPAGATE)
    assert any("하위로 셌다" in x for x in problems), problems


def test_a_fallback_judgement_is_a_violation_when_the_flag_is_declared(tmp_path):
    """계층을 못 풀고 상태 규칙으로 떨어지면 설계 항목이 다시 섞임 — 멈춰야 함."""
    p = _clean_plan()
    p["entries"][0]["layer_mode"] = "fallback"
    problems = check_plan(p, layers_with_feature_design(tmp_path), PROPAGATE)
    assert any("계층을 해석하지 않고" in x for x in problems), problems


def test_a_fallback_judgement_without_the_flag_is_not_flagged(tmp_path):
    """대조군 — 플래그 없는 호스트의 폴백은 기존 경로 그대로."""
    p = _clean_plan()
    p["entries"][0]["layer_mode"] = "fallback"
    assert check_plan(p, layers_via_producer(tmp_path), PROPAGATE) == []
