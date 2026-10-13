"""CLI 종료 코드 계약 — `main()` 이 규칙 위반(3)과 내부 오류(그 밖의 비영)를 가르는 자리.

I1/Ruling 12: 스키마 필수 최상위 키(`space`·`boards`·리스트 `entries`) 부재는 내부 오류임.
`entries: []` 는(다른 키가 다 있으면) 정당한 "할 일 없음" — 부모가 쓸 것이 없을 뿐 계획이
못 만들어진 것은 아니라서임. 이 둘을 가르지 않으면 `{}` 와 `{"entries": []}` 가 똑같이
`[]` 를 찍고 exit 0 이 되어, 계획이 아예 비어도 부모가 폴백해야 한다는 R6 의 약속을
아무 코드도 지키지 않게 됨.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.alm_plan_check import main
from tests.alm_plan_check._helpers import LAYERS_EMPTY, PROPAGATE, plan

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "alm_plan_check.py"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda p: p, 0),
        (
            lambda p: (
                p.update({"entries": [dict(p["entries"][0], ratio={"done": 9, "total": 9})]}) or p
            ),
            3,
        ),
    ],
)
def test_the_cli_splits_rule_violations_from_everything_else(tmp_path, mutate, code):
    """규칙 위반만 3. 내부 오류는 그 밖의 코드로 떨어져 부모가 폴백함 —
    둘을 묶으면 PyYAML 부재 하나가 전파를 막음."""
    mutated_plan = mutate(plan())
    paths = {}
    for name, blob in (("plan", mutated_plan), ("layers", LAYERS_EMPTY), ("propagate", PROPAGATE)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(blob), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(paths["plan"]),
            "--layers",
            str(paths["layers"]),
            "--propagate",
            str(paths["propagate"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == code, proc.stderr


def test_a_missing_plan_file_is_an_internal_error_not_a_violation(tmp_path):
    """파일이 없는 것은 계획이 틀렸다는 뜻이 아님 — 부모는 폴백해야 함."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "nope.json")],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode not in (0, 3), proc.stderr


def test_a_plan_missing_required_top_level_keys_is_an_internal_error(tmp_path):
    """`{}` 는 계획이 못 만들어진 것 — `entries: []` 정당한 값과는 다른 사유임."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    code = main([str(plan_path)])
    assert code not in (0, 3)


def test_empty_entries_with_the_rest_of_the_shape_present_is_a_legitimate_no_op(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({"space": "dev3", "boards": {}, "entries": []}), encoding="utf-8"
    )
    code = main([str(plan_path)])
    assert code == 0


def test_a_config_path_reaches_the_same_verdict_as_a_propagate_path(tmp_path):
    """`propagate.json` 을 만드는 단계가 없어 부모는 `--config` 로만 이 스크립트를 부름 —
    두 입력 경로가 같은 depth 를 권위로 삼아야 레벨 상한 불변식이 조용히 안 빠짐."""
    mutated_plan = plan()
    mutated_plan["depth"] = 2
    mutated_plan["entries"][0]["level"] = 3
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(mutated_plan), encoding="utf-8")
    layers_path = tmp_path / "layers.json"
    layers_path.write_text(json.dumps(LAYERS_EMPTY), encoding="utf-8")
    propagate_path = tmp_path / "propagate.json"
    propagate_path.write_text(json.dumps({**PROPAGATE, "depth": 2}), encoding="utf-8")
    config_path = tmp_path / "vdev-config.yaml"
    config_path.write_text(
        "alm:\n  recoble:\n    propagate:\n      depth: 2\n",
        encoding="utf-8",
    )

    def _run(*flags: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(plan_path), "--layers", str(layers_path), *flags],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    via_propagate = _run("--propagate", str(propagate_path))
    via_config = _run("--config", str(config_path))
    assert via_propagate.returncode == via_config.returncode == 3
    assert "depth" in via_propagate.stderr
    assert "depth" in via_config.stderr


def test_when_both_flags_are_given_the_propagate_flag_wins(tmp_path):
    """`--propagate` 와 `--config` 가 같이 오면 `--propagate` 가 이김 — 서로 다른 depth 를
    줘서 어느 쪽이 실제로 반영됐는지 판정 결과로 구분함."""
    mutated_plan = plan()
    mutated_plan["depth"] = 5
    mutated_plan["entries"][0]["level"] = 3
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(mutated_plan), encoding="utf-8")
    layers_path = tmp_path / "layers.json"
    layers_path.write_text(json.dumps(LAYERS_EMPTY), encoding="utf-8")

    # --config 쪽 depth=1 이면 level 3 이 그 depth 와도 안 맞고 넘기도 함. --propagate 쪽
    # depth=5 는 계획의 depth(5)와 맞고 level 도 안 넘음. --propagate 가 이겨야 하므로
    # 최종 판정은 통과여야 함.
    propagate_path = tmp_path / "propagate.json"
    propagate_path.write_text(json.dumps({**PROPAGATE, "depth": 5}), encoding="utf-8")
    config_path = tmp_path / "vdev-config.yaml"
    config_path.write_text("alm:\n  recoble:\n    propagate:\n      depth: 1\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(plan_path),
            "--layers",
            str(layers_path),
            "--config",
            str(config_path),
            "--propagate",
            str(propagate_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr


def test_malformed_config_yaml_is_an_internal_error_not_a_violation(tmp_path):
    """YAML 파싱 실패는 계획이 틀렸다는 뜻이 아님 — VIOLATION(3) 이 아니라 내부 오류로 떨어짐."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan()), encoding="utf-8")
    layers_path = tmp_path / "layers.json"
    layers_path.write_text(json.dumps(LAYERS_EMPTY), encoding="utf-8")
    config_path = tmp_path / "vdev-config.yaml"
    config_path.write_text("alm: [닫히지 않은 목록\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(plan_path),
            "--layers",
            str(layers_path),
            "--config",
            str(config_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode not in (0, 3), proc.stderr


def test_missing_pyyaml_is_an_internal_error_not_a_violation(tmp_path, monkeypatch):
    """PyYAML 없는 호스트를 시뮬레이션 — `import yaml` 의 `ImportError` 도 VIOLATION(3) 이
    아니라 내부 오류임. `sys.modules` 에 `None` 을 넣어 그 자리에서만 재현하고 다른 테스트로
    안 샘(monkeypatch 가 테스트 뒤 되돌림)."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan()), encoding="utf-8")
    layers_path = tmp_path / "layers.json"
    layers_path.write_text(json.dumps(LAYERS_EMPTY), encoding="utf-8")
    config_path = tmp_path / "vdev-config.yaml"
    config_path.write_text("alm:\n  recoble:\n    propagate:\n      depth: 2\n", encoding="utf-8")

    monkeypatch.setitem(sys.modules, "yaml", None)
    code = main([str(plan_path), "--layers", str(layers_path), "--config", str(config_path)])
    assert code not in (0, 3)
