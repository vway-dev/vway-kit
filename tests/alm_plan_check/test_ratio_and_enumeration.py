"""`check_plan` 의 산수·자기모순 불변식 — enumeration·ratio·branch·depends_on 존재·depth 상한.

`branch` 값은 `full`(`ratio == 1`)·`partial`(`0 < ratio < 1`)·`none`(그 외) 셋 —
`propagate.status: all-done` 과 이름이 겹치지 않는 별개 축."""

from __future__ import annotations

from scripts.alm_plan_check import check_plan
from tests.alm_plan_check._helpers import PROPAGATE, plan


def test_a_clean_plan_passes():
    assert check_plan(plan(), {}, PROPAGATE) == []


def test_an_incomplete_enumeration_may_not_carry_a_proposal():
    """한 페이지에 안 들어온 하위집합은 비율이 틀림 — 그 상위는 판정 대상이 아님."""
    p = plan()
    p["entries"][0]["enumeration"]["complete"] = False
    assert any("enumeration" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_the_ratio_must_match_the_children():
    """산수는 부모가 MCP 없이 검산할 수 있는 유일한 축 — 여기서 안 잡으면 아무 데서도 안 잡힘."""
    p = plan()
    p["entries"][0]["ratio"] = {"done": 2, "total": 2}
    assert any("ratio" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_branch_must_match_what_the_ratio_implies():
    """branch 는 ratio 파생값 — 어긋나면 부모가 잘못된 갈래로 버릴 범위를 정함."""
    p = plan()
    p["entries"][0]["branch"] = "none"
    problems = check_plan(p, {}, PROPAGATE)
    assert any("d1" in problem and "none" in problem and "full" in problem for problem in problems)


def test_depends_on_may_not_name_an_absent_entry():
    """계획에 없는 id 에 기대면 거부·실패 시 무엇을 버릴지 못 정함."""
    p = plan()
    p["entries"][0]["proposed"]["depends_on"]["status"] = ["nope"]
    assert any("nope" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_level_may_not_exceed_depth():
    p = plan()
    p["entries"][0]["level"] = 5
    assert any("depth" in problem for problem in check_plan(p, {}, PROPAGATE))
