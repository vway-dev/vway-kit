"""불변식 6 — 케이스 계층 하위는 상태가 아니라 `fields.latest_result` 로 판정됨.

계층 픽스처는 손으로 만든 dict 가 아니라 `scripts/alm_layers.py` 의 실제 `resolve_layers()`
출력(`layers_via_producer`) — 그 함수는 `layers["layers"]` 를 **리스트**로 냄. 손으로 만든
dict 픽스처는 이 모양 불일치를 못 드러내, `.items()` 가 매번 `AttributeError` 로 폴백하며
invariant 6 이 죽은 코드로 남아도 초록으로 보임.
"""

from __future__ import annotations

from scripts.alm_plan_check import check_plan
from tests.alm_plan_check._helpers import PROPAGATE, layers_via_producer, plan


def test_the_producer_output_actually_declares_the_case_layer(tmp_path):
    """픽스처 자체가 생산자를 통과했는지 — 그렇지 않으면 아래 테스트가 무엇을 재는지 불명."""
    layers = layers_via_producer(tmp_path)
    assert not layers["errors"]
    assert {layer["key"] for layer in layers["layers"]} == {"design", "case"}


def test_a_case_layer_child_is_judged_by_its_field(tmp_path):
    """케이스 상태축은 명세 수명주기라 승인만으로 상위가 닫힘 — 판정은 필드가 듦."""
    layers = layers_via_producer(tmp_path)
    p = plan()
    p["entries"][0]["children"][0]["layer"] = "case"
    problems = check_plan(p, layers, PROPAGATE)
    assert any("latest_result" in problem for problem in problems)


def test_a_case_layer_child_judged_by_latest_result_is_not_flagged(tmp_path):
    layers = layers_via_producer(tmp_path)
    p = plan()
    p["entries"][0]["children"][0]["layer"] = "case"
    p["entries"][0]["children"][0]["basis"] = "latest_result"
    assert check_plan(p, layers, PROPAGATE) == []
