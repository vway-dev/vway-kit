"""값 도출 — `progress`·`coverage_status` 는 fork 가 아니라 검산된 `ratio` 에서 나옴.

fork(LLM)의 산술은 빗나갈 수 있고 반올림 관례도 갈림 — 파이썬 `round(12.5)` 는 12, 흔한
반올림은 13. 대조만 하면 관례 하나로 전파 전체가 중단되므로 스크립트가 정답을 직접 내고,
어긋나면 경고만 남김. 식의 SSOT 는 `recoble-propagation.md` 「판정」이고, 드리프트 테스트가
그 문서의 예시를 읽어 스크립트와 대조.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.alm_plan_check import _derive_coverage, _derive_progress, minimal_writes
from tests.alm_plan_check._helpers import (
    PROPAGATE,
    layers_via_producer,
    layers_with_coverage,
    plan,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "alm_plan_check.py"
PROPAGATION_DOC = REPO / "skills" / "task-sync" / "references" / "recoble-propagation.md"


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [(1, 8, 13), (2, 3, 67), (0, 5, 0), (5, 5, 100), (1, 3, 33)],
)
def test_progress_rounds_half_up(done, total, expected):
    assert _derive_progress(done, total) == expected


def test_no_children_means_no_progress():
    assert _derive_progress(0, 0) is None


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [(0, 0, "UNCOVERED"), (2, 2, "COVERED"), (1, 2, "NOT_COVERED"), (0, 3, "NOT_COVERED")],
)
def test_coverage_follows_the_ratio(done, total, expected):
    assert _derive_coverage(done, total) == expected


def _one(p: dict, *, ratio: dict, layer: str, **proposed) -> dict:
    """첫 항목의 `ratio`·`layer`·제안만 바꿈 — `minimal_writes` 는 `check_plan` 을 안 부르므로
    다른 불변식은 이 테스트의 관심이 아님."""
    e = p["entries"][0]
    e["ratio"] = ratio
    e["layer"] = layer
    e["proposed"].update(proposed)
    return p


def test_rollup_replaces_a_wrong_fork_progress_and_warns(tmp_path):
    p = _one(plan(), ratio={"done": 1, "total": 8}, layer="design", progress=12)
    warnings: list[str] = []
    rows = minimal_writes(p, layers_via_producer(tmp_path), PROPAGATE, warnings)
    assert rows[0]["proposed"]["progress"] == 13
    assert len(warnings) == 1 and "progress" in warnings[0]


def test_a_matching_fork_value_leaves_no_warning(tmp_path):
    warnings: list[str] = []
    rows = minimal_writes(plan(), layers_via_producer(tmp_path), PROPAGATE, warnings)
    assert rows[0]["proposed"]["progress"] == 100
    assert warnings == []


def test_without_config_the_fork_progress_passes_through(tmp_path):
    p = _one(plan(), ratio={"done": 1, "total": 8}, layer="design", progress=55)
    warnings: list[str] = []
    rows = minimal_writes(p, layers_via_producer(tmp_path), {}, warnings)
    assert rows[0]["proposed"]["progress"] == 55
    assert warnings == []


def test_rollup_with_no_children_drops_progress(tmp_path):
    p = _one(plan(), ratio={"done": 0, "total": 0}, layer="design", progress=0)
    rows = minimal_writes(p, layers_via_producer(tmp_path), PROPAGATE, [])
    assert rows[0]["proposed"]["progress"] is None


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        ({"done": 1, "total": 1}, "COVERED"),
        ({"done": 1, "total": 2}, "NOT_COVERED"),
        ({"done": 0, "total": 0}, "UNCOVERED"),
    ],
)
def test_coverage_is_derived_on_a_declaring_layer(tmp_path, ratio, expected):
    p = _one(plan(), ratio=ratio, layer="requirement", coverage_status=None)
    rows = minimal_writes(p, layers_with_coverage(tmp_path), PROPAGATE, [])
    assert rows[0]["proposed"]["coverage_status"] == expected


def test_a_layer_that_does_not_declare_coverage_gets_none(tmp_path):
    p = _one(plan(), ratio={"done": 1, "total": 1}, layer="design", coverage_status="COVERED")
    warnings: list[str] = []
    rows = minimal_writes(p, layers_via_producer(tmp_path), PROPAGATE, warnings)
    assert rows[0]["proposed"]["coverage_status"] is None
    assert any("coverage_status" in w for w in warnings)


@pytest.mark.parametrize(
    ("layers_kind", "layer_mode", "layer"),
    [
        ("none", "declared", "requirement"),
        ("real", "fallback", None),
        ("real", "declared", None),
        ("real", "fallback", "requirement"),
    ],
)
def test_an_unknown_layer_passes_the_fork_coverage_through(
    tmp_path, layers_kind, layer_mode, layer
):
    p = _one(plan(), ratio={"done": 1, "total": 2}, layer=layer, coverage_status="COVERED")
    p["entries"][0]["layer_mode"] = layer_mode
    layers = {} if layers_kind == "none" else layers_with_coverage(tmp_path)
    rows = minimal_writes(p, layers, PROPAGATE, [])
    assert rows[0]["proposed"]["coverage_status"] == "COVERED"


def test_the_cli_warns_on_stderr_and_still_exits_zero(tmp_path):
    p = plan()
    p["entries"][0]["proposed"]["progress"] = 99
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    layers_path = tmp_path / "layers.json"
    layers_path.write_text(
        json.dumps(layers_via_producer(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    prop_path = tmp_path / "propagate.json"
    prop_path.write_text(json.dumps(PROPAGATE), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(plan_path),
            "--layers",
            str(layers_path),
            "--propagate",
            str(prop_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert "도출값" in proc.stderr
    assert json.loads(proc.stdout)[0]["proposed"]["progress"] == 100


def test_the_rounding_example_in_the_propagation_doc_matches_the_script():
    """드리프트 감지 — 「판정」의 progress 규칙이 든 예시들(`1/8 → 13` 등)을 읽어 식과 대조.

    폴백 부모는 문서의 식을 밟고 위임 경로는 스크립트의 식을 밟음 — 둘이 갈리면 같은
    그래프에서 경로마다 다른 숫자가 보드에 써짐.
    """
    doc = PROPAGATION_DOC.read_text(encoding="utf-8")
    for heading in ("## 판정", "## 쓰기·보고"):
        assert heading in doc, f"헤딩이 사라짐: {heading} — 절 조각이 파일 전체로 넓어진다"
    judgement = doc.split("## 판정", 1)[1].split("## 쓰기·보고", 1)[0]
    lines = judgement.splitlines()
    marker = "`propagate.progress: rollup`"
    start = next((i for i, line in enumerate(lines) if marker in line), None)
    assert start is not None, "「판정」에서 progress 규칙 불릿을 못 찾음"
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.startswith("  "):
            break
        block.append(line)
    rule = " ".join(block)
    matches = re.findall(r"(\d+)/(\d+)\s*→\s*(\d+)", rule)
    assert matches, (
        "「판정」의 progress 규칙에 예시(`a/b → c`)가 없다 — 문구를 바꿨으면 같이 고친다"
    )
    for done, total, value in ((int(g) for g in m) for m in matches):
        assert _derive_progress(done, total) == value
