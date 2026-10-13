"""`alm_plan_check` 테스트가 공유하는 것 — 보드·propagate 픽스처와 깨끗한 계획 하나.

`layers_via_producer` 는 손으로 만든 dict 대신 `scripts/alm_layers.py` 의 실제
`resolve_layers()` 출력을 만들어 줌 — 계층 픽스처의 모양을 그 생산자에 묶어 두는 것이
`_field_layers` 가 리스트 대신 dict 를 기대하며 죽는 결함(C1)의 재발 방지책.
"""

from __future__ import annotations

import copy
from pathlib import Path

from tests.alm_layers._helpers import resolve

BOARDS = {
    "b-design": {
        "name": "설계",
        "statuses": [
            {
                "key": "NOT_STARTED",
                "done": False,
                "statusGroup": "TODO",
                "sortOrder": 0,
                "isEntry": True,
            },
            {
                "key": "IN_PROGRESS",
                "done": False,
                "statusGroup": "IN_PROGRESS",
                "sortOrder": 1,
                "isEntry": False,
            },
            {
                "key": "REVIEW",
                "done": False,
                "statusGroup": "IN_PROGRESS",
                "sortOrder": 2,
                "isEntry": False,
            },
            {"key": "DONE", "done": True, "statusGroup": "DONE", "sortOrder": 3, "isEntry": False},
        ],
    }
}

PROPAGATE = {"enable": True, "depth": 2, "status": "all-done", "progress": "rollup"}

# 계층 선언이 무관한 테스트용 — `_field_layers` 는 이것을 빈 계층 목록으로 읽음.
LAYERS_EMPTY: dict = {}


def plan() -> dict:
    """규칙을 모두 만족하는 계획 하나. 케이스마다 여기서 한 곳만 망가뜨림."""
    return {
        "space": "dev3",
        "depth": 2,
        "visit_cap_hit": False,
        "mcp_calls": 7,
        "boards": copy.deepcopy(BOARDS),
        "entries": [
            {
                "item": {"id": "d1", "name": "설계 A", "projectId": "b-design"},
                "level": 1,
                "layer": "design",
                "layer_mode": "declared",
                "current": {"status": "IN_PROGRESS", "progress": 40},
                "children": [
                    {
                        "id": "t1",
                        "projectId": "b-design",
                        "layer": "design",
                        "basis": "status",
                        "done": True,
                    }
                ],
                "enumeration": {"paths": ["derives"], "pages": 1, "complete": True},
                "ratio": {"done": 1, "total": 1},
                "branch": "full",
                "proposed": {
                    "status": "REVIEW",
                    "progress": 100,
                    "coverage_status": None,
                    "depends_on": {"status": [], "progress": []},
                },
                "skip_reason": None,
            }
        ],
    }


def layers_via_producer(tmp_path: Path) -> dict:
    """`resolve_layers()` 실제 출력 — `design` 은 평범한 계층, `case` 는 `latest_result` 선언."""
    layers_yaml = (
        "          design:\n"
        "            workboard: 설계\n"
        "          case:\n"
        "            workboard: 케이스\n"
        "            fields:\n"
        "              latest_result: f_1\n"
    )
    return resolve(tmp_path, layers_yaml)


def layers_with_coverage(tmp_path: Path) -> dict:
    """`resolve_layers()` 실제 출력 — `requirement` 가 `coverage_status` 를 선언하고 `case` 가
    그것을 검증. 커버리지 도출이 계층 선언을 생산자와 같은 모양으로 읽는지 재는 자리."""
    layers_yaml = (
        "          requirement:\n"
        "            workboard: 요구사항\n"
        "            fields:\n"
        "              coverage_status: f_2\n"
        "          case:\n"
        "            workboard: 케이스\n"
        "            verifies: requirement\n"
        "            fields:\n"
        "              latest_result: f_1\n"
    )
    return resolve(tmp_path, layers_yaml)


def layers_with_feature_design(tmp_path: Path) -> dict:
    """`resolve_layers()` 실제 출력 — `design` 이 `feature_design` 이고 `task` 가 그 아래."""
    layers_yaml = (
        "          requirement:\n"
        "            workboard: 요구사항\n"
        "          design:\n"
        "            workboard: 설계\n"
        "            derives_from: requirement\n"
        "            feature_design: true\n"
        "          task:\n"
        "            workboard: 개발 작업\n"
        "            derives_from: design\n"
    )
    return resolve(tmp_path, layers_yaml)
