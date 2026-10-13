"""I4/Ruling 14 — 방문 상한의 세 경계.

멈춤 규칙: 판정한 상위가 상한에 닿았는데 아직 볼 상위가 남았으면 거기서 멈추고
`visit_cap_hit: true`. 그래서 상한을 넘는 개수는 항상 위반, `visit_cap_hit` 이
`true` 인데 개수가 상한과 다른 것도 위반, 정확히 상한에서 자연 종료(`visit_cap_hit: false`)는
통과 — `>=` 하나로 뭉개면 상한에서 자연히 끝난 정상 그래프까지 막힘.

`VISIT_CAP` 의 SSOT 는 `recoble-propagation.md` 「연쇄」(현재 100) — 드리프트 테스트가 그
문장에서 숫자를 직접 읽어 대조함.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from scripts.alm_plan_check import VISIT_CAP, check_plan
from tests.alm_plan_check._helpers import PROPAGATE, plan

REPO = Path(__file__).resolve().parents[2]


def _replicate(count: int) -> dict:
    p = plan()
    template = p["entries"][0]
    p["entries"] = [copy.deepcopy(template) for _ in range(count)]
    for i, e in enumerate(p["entries"]):
        e["item"]["id"] = f"d{i}"
    return p


def test_more_than_the_cap_is_always_a_violation():
    p = _replicate(VISIT_CAP + 1)
    assert any(str(VISIT_CAP) in problem for problem in check_plan(p, {}, PROPAGATE))


def test_visit_cap_hit_true_without_exactly_the_cap_count_is_a_violation():
    p = plan()
    p["visit_cap_hit"] = True
    assert any("visit_cap_hit" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_exactly_the_cap_with_a_natural_end_passes():
    p = _replicate(VISIT_CAP)
    p["visit_cap_hit"] = False
    assert check_plan(p, {}, PROPAGATE) == []


def test_visit_cap_matches_the_ssot_sentence_in_the_propagation_doc():
    """드리프트 감지 — SSOT 문장에서 숫자를 읽어 `VISIT_CAP` 과 대조."""
    doc = (REPO / "skills" / "task-sync" / "references" / "recoble-propagation.md").read_text(
        encoding="utf-8"
    )
    section = doc.split("### 연쇄", 1)[1]
    match = re.search(r"판정한 상위가\s*(\d+)\s*에 닿았는데", section)
    assert match, "SSOT 문장을 못 찾음 — 문구가 바뀌었으면 이 테스트도 같이 고친다"
    assert int(match.group(1)) == VISIT_CAP
