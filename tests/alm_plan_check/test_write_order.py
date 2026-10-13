"""M3 — 쓰기 목록은 `level` 이 아니라 `depends_on` 위상 순, 순환은 `check_plan` 위반.

같은 level 의 두 항목이 서로 기댈 수 있어(같은 상위의 두 하위처럼) `level` 정렬은 순서를
못 정함. `depends_on` 이 순환하면 위상 정렬 자체가 불가능하므로 `check_plan` 이 그
자리에서 막음 — 쓰기 단계까지 가면 무엇을 먼저 써야 할지 아무도 모름.
"""

from __future__ import annotations

import copy

from scripts.alm_plan_check import check_plan, minimal_writes
from tests.alm_plan_check._helpers import BOARDS, plan


def _entry(item_id: str, depends_on: dict | None = None) -> dict:
    """다른 불변식은 건드리지 않는 최소 유효 항목 — 의존 그래프만 다름."""
    return {
        "item": {"id": item_id, "name": item_id, "projectId": "b-design"},
        "level": 1,
        "layer": None,
        "layer_mode": "fallback",
        "current": {"status": "NOT_STARTED", "progress": 0},
        "children": [],
        "enumeration": {"paths": [], "pages": 1, "complete": True},
        "ratio": {"done": 0, "total": 0},
        "branch": "none",
        "proposed": {
            "status": "IN_PROGRESS",
            "progress": None,
            "coverage_status": None,
            "depends_on": depends_on or {},
        },
        "skip_reason": None,
    }


def _plan_with(entries: list[dict]) -> dict:
    return {
        "space": "dev3",
        "depth": 0,
        "visit_cap_hit": False,
        "mcp_calls": 0,
        "boards": copy.deepcopy(BOARDS),
        "entries": entries,
    }


def test_minimal_writes_carries_only_what_the_parent_needs():
    """부모는 계획이 아니라 이 출력을 읽음 — 계획을 읽으면 원본을 다시 들이는 것과 같음."""
    rows = minimal_writes(plan())
    assert [r["id"] for r in rows] == ["d1"]
    assert set(rows[0]) == {
        "id",
        "name",
        "projectId",
        "level",
        "current",
        "proposed",
        "depends_on",
    }


def test_an_entry_without_a_proposal_is_not_a_write():
    p = plan()
    p["entries"][0]["proposed"] = None
    p["entries"][0]["skip_reason"] = "하위집합 비었음"
    assert minimal_writes(p) == []


def test_same_level_entries_are_ordered_by_dependency_not_insertion():
    """A 가 B 에 기댐 — 둘 다 level 1 이라 `level` 만으로는 이 순서를 못 정함."""
    a = _entry("A", {"status": ["B"]})
    b = _entry("B")
    rows = minimal_writes(_plan_with([a, b]))
    assert [r["id"] for r in rows] == ["B", "A"]


def test_a_dependency_cycle_is_a_violation_naming_both_ids():
    a = _entry("A", {"status": ["B"]})
    b = _entry("B", {"status": ["A"]})
    problems = check_plan(_plan_with([a, b]), {}, {})
    assert any("A" in problem and "B" in problem for problem in problems)
