"""선언 한 줄의 모양 — 스페이스 해석·정규화·필드 역할.

무엇이 계층 하나의 결정이 되는가. 값이 빠지거나 형이 어긋날 때 그 항목만 빠지는지."""

from pathlib import Path

import pytest

from scripts.alm_layers import load_layers_config, normalize_layer, resolve_layers
from tests.alm_layers._helpers import CONFIG, resolve, write_config


def test_load_layers_config_uses_default_space(tmp_path: Path):
    layers, space = load_layers_config(write_config(tmp_path, CONFIG), None)
    assert space == "dev3"
    assert set(layers) == {"requirement", "design"}


def test_load_layers_config_explicit_space(tmp_path: Path):
    layers, space = load_layers_config(write_config(tmp_path, CONFIG), "dev3")
    assert space == "dev3"
    assert layers["design"]["derives_from"] == "requirement"


def test_load_layers_config_unknown_space(tmp_path: Path):
    layers, space = load_layers_config(write_config(tmp_path, CONFIG), "nope")
    assert layers == {}
    assert space == "nope"


def test_load_layers_config_missing_file(tmp_path: Path):
    layers, _ = load_layers_config(tmp_path / "absent.yaml", "dev3")
    assert layers == {}


def test_load_layers_config_broken_yaml(tmp_path: Path):
    layers, _ = load_layers_config(write_config(tmp_path, "alm: [unclosed"), "dev3")
    assert layers == {}


def test_normalize_layer_defaults(tmp_path: Path):
    got = normalize_layer("design", {"workboard": "설계"}, tmp_path, tmp_path)
    assert got["key"] == "design"
    assert got["workboard"] == "설계"
    assert got["derives_from"] is None
    assert got["verifies"] is None
    assert got["marker"] is False
    assert got["status"] is None
    assert got["category"] is None
    assert got["template"] is None


def test_normalize_layer_implicit_template(tmp_path: Path):
    (tmp_path / "templates" / "alm").mkdir(parents=True)
    (tmp_path / "templates" / "alm" / "design.md").write_text("t", encoding="utf-8")
    got = normalize_layer("design", {"workboard": "설계"}, tmp_path, tmp_path)
    assert got["template"].endswith("design.md")


def test_normalize_layer_explicit_template(tmp_path: Path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "custom.md").write_text("t", encoding="utf-8")
    got = normalize_layer(
        "design", {"workboard": "설계", "template": "custom.md"}, tmp_path, tmp_path
    )
    assert got["template"].endswith("custom.md")


def test_normalize_layer_marker_and_relations(tmp_path: Path):
    spec = {
        "workboard": "결함 관리",
        "verifies": "requirement",
        "marker": True,
        "status": "NOT_STARTED",
        "category": "검증",
    }
    got = normalize_layer("verification", spec, tmp_path, tmp_path)
    assert got["verifies"] == "requirement"
    assert got["marker"] is True
    assert got["status"] == "NOT_STARTED"
    assert got["category"] == "검증"


def test_normalize_layer_rejects_non_dict(tmp_path: Path):
    assert normalize_layer("design", "설계", tmp_path, tmp_path) is None


@pytest.mark.parametrize("spec", [{}, {"workboard": ""}, {"workboard": None}])
def test_normalize_layer_missing_workboard(tmp_path: Path, spec: dict):
    got = normalize_layer("design", spec, tmp_path, tmp_path)
    assert got["workboard"] == ""


def test_load_layers_config_yaml_not_dict(tmp_path: Path):
    layers, space = load_layers_config(write_config(tmp_path, "[1, 2, 3]"), "dev3")
    assert layers == {}
    assert space == "dev3"


def test_load_layers_config_recoble_not_dict(tmp_path: Path):
    layers, space = load_layers_config(
        write_config(tmp_path, "alm:\n  recoble: not_a_dict"), "dev3"
    )
    assert layers == {}
    assert space == "dev3"


def test_normalize_layer_defect_flag_defaults_false(tmp_path: Path):
    """결함 진입은 옵트인 — 선언하지 않은 계층이 결함을 받으면 안 됨."""
    got = normalize_layer("verification", {"workboard": "테스트 케이스"}, tmp_path, tmp_path)
    assert got["defect"] is False
    truthy = normalize_layer("defect", {"workboard": "결함", "defect": "yes"}, tmp_path, tmp_path)
    assert truthy["defect"] is False, "marker 와 같이 True 하나만 켬 — 문자열은 선언이 아님"
    on = normalize_layer("defect", {"workboard": "결함", "defect": True}, tmp_path, tmp_path)
    assert on["defect"] is True


def test_resolve_layers_warns_on_unknown_declaration(tmp_path: Path):
    """모르는 선언 키는 조용히 버려지면 안 됨 — 구버전 호스트에서 새 선언이 통째로 무시됨."""
    got = resolve(
        tmp_path,
        "          design:\n            workboard: 설계\n            derivesfrom: requirement\n",
    )
    assert any("derivesfrom" in w for w in got["warnings"]), got["warnings"]


def test_resolve_layers_quiet_on_known_declarations(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          requirement:\n            workboard: 요구사항\n"
        "          design:\n            workboard: 설계\n"
        "            derives_from: requirement\n            template: alm/design.md\n",
    )
    assert [w for w in got["warnings"] if "모르는 선언" in w] == []


def test_resolve_layers_maps_field_roles(tmp_path: Path):
    """필드 key 는 호스트 것, 역할 이름은 스펙 것 — 매핑이 그 둘을 이음."""
    got = resolve(
        tmp_path,
        "          design:\n            workboard: 설계\n"
        "            fields:\n              module: service\n"
        "              feature: feature\n              bogus: x\n",
    )
    design = next(x for x in got["layers"] if x["key"] == "design")
    assert design["fields"] == {"module": "service", "feature": "feature"}
    assert any("bogus" in w for w in got["warnings"]), got["warnings"]


def test_resolve_layers_fields_not_a_dict_warns(tmp_path: Path):
    got = resolve(
        tmp_path,
        "          design:\n            workboard: 설계\n            fields: nope\n",
    )
    design = next(x for x in got["layers"] if x["key"] == "design")
    assert design["fields"] == {}
    assert any("fields" in w for w in got["warnings"]), got["warnings"]


def test_resolve_layers_without_fields_is_quiet(tmp_path: Path):
    got = resolve(tmp_path, "          design:\n            workboard: 설계\n")
    design = next(x for x in got["layers"] if x["key"] == "design")
    assert design["fields"] == {}
    assert [w for w in got["warnings"] if "fields" in w] == []


def test_resolve_layers_empty_fields_is_quiet(tmp_path: Path):
    """빈 매핑은 선언 안 한 것과 같음 — 경고를 내면 역할을 아직 안 정한 호스트가 매번 시끄러움."""
    got = resolve(
        tmp_path,
        "          design:\n            workboard: 설계\n            fields: {}\n",
    )
    design = next(x for x in got["layers"] if x["key"] == "design")
    assert design["fields"] == {}
    assert [w for w in got["warnings"] if "fields" in w] == []


def test_resolve_layers_non_string_declaration_key_does_not_crash(tmp_path: Path):
    """YAML 은 `on:`·`2:` 를 bool·int 로 읽음 — 정렬이 터지면 오타를 잡으려던 코드가 오타에 죽음.

    `1` 을 안 쓰는 이유: 파이썬에서 `True == 1` 이라 집합이 둘을 하나로 접음."""
    got = resolve(
        tmp_path,
        "          design:\n            workboard: 설계\n            on: x\n            2: y\n",
    )
    assert got["errors"] == [], got["errors"]
    assert len([w for w in got["warnings"] if "모르는 선언" in w]) == 2, got["warnings"]


def test_resolve_layers_survives_a_non_string_layer_key(tmp_path: Path):
    """YAML 은 `2024-01-01:` 를 date 로 줌 — 문자열 키와 섞이면 위상 정렬의 sorted 가
    형을 비교하는 순간 터짐. 경계에서 형을 맞춰야 그 config 가 그냥 돎."""
    cfg = write_config(
        tmp_path,
        "alm:\n  recoble:\n    spaces:\n      dev3:\n        layers:\n"
        "          2024-01-01:\n            workboard: a\n"
        "          task:\n            workboard: b\n",
    )
    out = resolve_layers(cfg, "dev3", tmp_path / "p", tmp_path / "h")
    assert {x["key"] for x in out["layers"]} == {"2024-01-01", "task"}
