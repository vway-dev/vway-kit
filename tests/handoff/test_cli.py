"""CLI 표면 — 스킬 문서가 박아 둔 명령이 실제로 돎.

순수 함수만 재면 argparse 철자·출력 키 집합이 문서와 어긋나도 초록이고 런타임에서만 터짐."""

from pathlib import Path

from tests.handoff._helpers import _mk, _run_cli


def test_cli_accepts_the_provider_flag_the_skills_document(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n"
        "  summary:\n    enable: true\n    author: AI\n    field: item_content\n"
        "  qa:\n    enable: true\n    author: AI\n"
        "    field:\n      teamer: col22\n",
        encoding="utf-8",
    )
    recoble = _run_cli(cfg, "--provider", "recoble")
    assert recoble["provider"] == "recoble" and recoble["configured"] is True
    assert [k["kind"] for k in recoble["kinds"]] == ["summary"]
    assert recoble["kinds"][0]["field"] == "comment"

    teamer = _run_cli(cfg, "--provider", "teamer")
    assert {k["kind"] for k in teamer["kinds"]} == {"summary", "qa"}


def test_cli_separates_no_handoff_config_from_no_kinds_for_this_provider(tmp_path: Path):
    """둘 다 kinds 가 비지만 요구하는 행동이 정반대 — 설정이 없으면 예전 동작으로
    떨어지고, 있는데 이 provider 대상이 없으면 아무것도 보내면 안 됨."""
    absent = tmp_path / "absent.yaml"
    absent.write_text("branches:\n  staging: stage\n", encoding="utf-8")
    # host 를 tmp 로 지목 — 소비자 호스트를 재는 테스트라 실행 저장소를 끌어들이지 않음
    assert _run_cli(absent, "--provider", "recoble", host=tmp_path) == {
        "provider": "recoble",
        "configured": False,
        "kinds": [],
        "warnings": [],
    }

    teamer_only = tmp_path / "teamer-only.yaml"
    teamer_only.write_text(
        "handoff:\n  qa:\n    enable: true\n    author: AI\n    field:\n      teamer: col22\n",
        encoding="utf-8",
    )
    result = _run_cli(teamer_only, "--provider", "recoble")
    assert result["configured"] is True and result["kinds"] == []


def test_cli_surfaces_the_legacy_template_warning(tmp_path: Path):
    """CLI 배선까지 재야 함 — 단위 함수만 재면 출력에 안 실린 채로 초록."""
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n  summary:\n    enable: true\n    field: item_content\n", encoding="utf-8"
    )
    _mk(tmp_path / "templates" / "handoff" / "summary.md", "old")
    out = _run_cli(cfg, "--provider", "recoble", host=tmp_path)
    assert any("handoff/summary.md" in w for w in out["warnings"])


def test_cli_survives_a_non_string_handoff_key(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text("handoff:\n  2024:\n    enable: true\n    field: col1\n", encoding="utf-8")
    assert _run_cli(cfg, "--provider", "recoble", host=tmp_path)["configured"] is True


def test_cli_survives_a_date_shaped_handoff_key(tmp_path: Path):
    """YAML 은 `2024-01-01:` 를 date 로 줌 — 그대로 JSON 에 실으면 직렬화가 터져
    handoff 단계 전체가 죽음(자매 alm_layers 는 경계에서 형을 맞춰 살아남음)."""
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text("handoff:\n  2024-01-01:\n    enable: true\n    field: col1\n", encoding="utf-8")
    out = _run_cli(cfg, "--provider", "teamer", host=tmp_path)
    assert [k["kind"] for k in out["kinds"]] == ["2024-01-01"]


def test_cli_narrows_the_warning_to_the_asked_provider(tmp_path: Path):
    """CLI 가 --provider 를 안 넘기면 단위 함수의 필터가 있어도 소용없음."""
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n  qa:\n    enable: true\n    field:\n      teamer: col22\n", encoding="utf-8"
    )
    _mk(tmp_path / "templates" / "handoff" / "qa.md", "old")
    assert _run_cli(cfg, "--provider", "recoble", host=tmp_path)["warnings"] == []
    assert _run_cli(cfg, "--provider", "teamer", host=tmp_path)["warnings"] != []
