"""I2/Ruling 13 — `propagate.depth`·`status`·`progress` 가 계획을 어길 때의 판정.

config 의 `propagate` 가 실려 있으면 그 `depth` 가 권위(계획 자기 `depth` 와 달라도 됨을
허용하면 fetch 가 config 를 무시하고도 통과함). `status`/`progress` 가 `off` 인 축에 제안이
있으면 위반. `propagate` 가 `{}`(둘 다 미제공)면 이 셋을 판정하지 않음 — 무엇이 맞는지
모르는 채로 계획을 의심할 근거가 없어서임.
"""

from __future__ import annotations

import json

import pytest

from scripts.alm_plan_check import check_plan, main
from tests.alm_plan_check._helpers import PROPAGATE, plan


def test_a_depth_mismatch_between_config_and_plan_is_a_violation():
    p = plan()
    p["depth"] = 5  # PROPAGATE 의 depth 는 2
    assert any("depth" in problem for problem in check_plan(p, {}, PROPAGATE))


def test_status_off_forbids_a_proposed_status():
    p = plan()
    propagate = {**PROPAGATE, "status": "off"}
    assert any("status" in problem for problem in check_plan(p, {}, propagate))


def test_progress_off_forbids_a_proposed_progress():
    p = plan()
    propagate = {**PROPAGATE, "progress": "off"}
    assert any("progress" in problem for problem in check_plan(p, {}, propagate))


def test_no_propagate_config_at_all_still_passes_a_clean_plan():
    """config 가 없으면(둘 다 미제공) depth·status·progress 는 판정하지 않음 — 계획
    자기 일관성만 남음."""
    assert check_plan(plan(), {}, {}) == []


def test_status_off_flag_blocks_a_proposed_status_even_when_config_allows_it(tmp_path):
    """`--status-off` 는 config 의 `status` 가 `all-done` 이어도 상태 제안을 막음."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan()), encoding="utf-8")
    config_path = tmp_path / "vdev-config.yaml"
    config_path.write_text(
        "alm:\n  recoble:\n    propagate:\n      status: all-done\n", encoding="utf-8"
    )
    code = main([str(plan_path), "--config", str(config_path), "--status-off"])
    assert code == 3


def test_status_off_flag_still_derives_progress_for_a_facts_only_plan(tmp_path, capsys):
    """`--status-off` 는 상태 축만 덮고, `progress: rollup` 도출은 그대로 통과시킴."""
    p = plan()
    p["entries"][0]["proposed"]["status"] = None
    p["entries"][0]["proposed"]["progress"] = 40  # 고의로 틀린 값 — 도출값은 100
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(p), encoding="utf-8")
    config_path = tmp_path / "vdev-config.yaml"
    config_path.write_text(
        "alm:\n  recoble:\n    propagate:\n      progress: rollup\n", encoding="utf-8"
    )
    code = main([str(plan_path), "--config", str(config_path), "--status-off"])
    rows = json.loads(capsys.readouterr().out)
    assert code == 0
    assert rows[0]["proposed"]["progress"] == 100


def test_status_off_without_config_or_propagate_is_a_usage_error():
    """소스가 없으면 무엇을 덮을지 몰라 argparse 사용법 오류(exit 2)로 막음."""
    with pytest.raises(SystemExit) as exc_info:
        main(["fake-plan.json", "--status-off"])
    assert exc_info.value.code == 2
