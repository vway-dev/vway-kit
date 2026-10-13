"""전이 판정 — 목표 상태가 그 보드에 실재하는지, 전진인지.

I3/Ruling 19: `recoble-status.md` 「등급」이 `sortOrder` 로 서열을 만들지 말라고 못 박아
금지함 — 한 보드의 `IN_PROGRESS` 그룹에 진행 중·검토와 함께 보류·QA 가 살고, 그 `sortOrder`
는 워크플로 순서가 아니라 배치 순서라서임. 보드 플래그만으로 매길 수 있는 등급은 셋
(0=TODO, 1=`IN_PROGRESS` 중 `sortOrder` 최소, 3=done) — 현재·목표 어느 한쪽이라도 이 셋
밖이면(예: 검토처럼 보드별 config 가 있어야 알 수 있는 상태) 전진 판정을 안 함.
"""

from __future__ import annotations

from scripts.alm_plan_check import _grade, check_plan
from tests.alm_plan_check._helpers import PROPAGATE, plan


def test_a_proposed_status_must_exist_on_that_board():
    """보드가 안 가진 키를 보내면 UI 가 못 보여주는 유령 값이 됨."""
    p = plan()
    p["entries"][0]["proposed"]["status"] = "QA"
    assert any("QA" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_a_backward_sort_order_from_an_ungraded_current_no_longer_blocks():
    """실측된 false positive — REVIEW 는 등급 밖(그 보드의 `IN_PROGRESS` 최소 sortOrder 가
    아니라서)이라 그 sortOrder(2)가 목표 IN_PROGRESS 의 sortOrder(1)보다 커도 서열로 재지 않음."""
    p = plan()
    p["entries"][0]["current"]["status"] = "REVIEW"
    p["entries"][0]["proposed"]["status"] = "IN_PROGRESS"
    assert check_plan(p, {}, PROPAGATE) == []


def test_a_definite_retreat_between_two_gradable_statuses_is_rejected():
    """done(3) → 시작 전(0) 은 둘 다 등급이 매겨지는 명백한 강등."""
    p = plan()
    p["entries"][0]["current"]["status"] = "DONE"
    p["entries"][0]["proposed"]["status"] = "NOT_STARTED"
    assert any("전진" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_a_tie_between_two_gradable_statuses_is_rejected():
    """같은 등급으로의 제안은 판정 절이 금하는 동률 — fork 가 판정을 안 따랐다는 증거."""
    p = plan()
    p["entries"][0]["current"]["status"] = "IN_PROGRESS"
    p["entries"][0]["proposed"]["status"] = "IN_PROGRESS"
    assert any("전진" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_grade_done_flag_wins_over_status_group():
    """`recoble-status.md` 「등급」 — 3 은 `done: true`, `statusGroup == "DONE"` 은 그 키가
    아예 없을 때만 대신 씀. `done: false` 인데 그룹이 `DONE` 인 상태는 넷 등급 밖(`None`)."""
    statuses = {
        "DONE_FLAG": {"done": True, "statusGroup": "IN_PROGRESS", "sortOrder": 9},
        "NO_DONE_KEY": {"statusGroup": "DONE", "sortOrder": 9},
        "FALSE_DONE_BUT_DONE_GROUP": {"done": False, "statusGroup": "DONE", "sortOrder": 9},
    }
    assert _grade(statuses, "DONE_FLAG") == 3
    assert _grade(statuses, "NO_DONE_KEY") == 3
    assert _grade(statuses, "FALSE_DONE_BUT_DONE_GROUP") is None
