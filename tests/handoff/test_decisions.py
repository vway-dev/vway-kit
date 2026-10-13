"""종류별 결정 — author·대상 필드·쓰기 모드·provider 선별.

무엇이 어디에 어떤 모드로 쓰이는가. 그 판정이 provider 마다 갈리는 지점을 잼."""

from pathlib import Path

from scripts.handoff_resolve import (
    is_ai_author,
    load_handoff_config,
    resolve_field,
    resolve_handoff,
    resolve_source_mode,
    resolve_write_mode,
)


def test_is_ai_author_variants():
    assert is_ai_author("AI")
    assert is_ai_author("llm")
    assert is_ai_author("Agent")
    assert not is_ai_author("bsyu")
    assert not is_ai_author("")


def test_resolve_source_mode_ai_guided():
    assert resolve_source_mode({"author": "AI", "AskUserQuestion": True}) == "ai_guided"


def test_resolve_source_mode_ai_auto():
    assert resolve_source_mode({"author": "AI", "AskUserQuestion": False}) == "ai_auto"


def test_resolve_source_mode_human_ask():
    assert resolve_source_mode({"author": "bsyu", "AskUserQuestion": True}) == "human_ask"


def test_resolve_source_mode_human_doc():
    assert resolve_source_mode({"author": "bsyu", "AskUserQuestion": False}) == "human_doc"


def test_resolve_source_mode_ask_defaults_false():
    # AskUserQuestion 미지정 → false 취급
    assert resolve_source_mode({"author": "AI"}) == "ai_auto"


def test_resolve_write_mode():
    assert resolve_write_mode("item_content") == "append"
    assert resolve_write_mode("col22") == "replace"


def test_resolve_write_mode_append_flag_overrides():
    # 불리언 플래그가 field 기반 기본을 덮어씀
    assert resolve_write_mode("col22", True) == "append"
    assert resolve_write_mode("item_content", False) == "replace"


def test_resolve_write_mode_falls_back_when_no_flag():
    # 플래그 미지정(None) → field 기반 폴백
    assert resolve_write_mode("item_content", None) == "append"
    assert resolve_write_mode("col22", None) == "replace"


def test_resolve_write_mode_ignores_non_bool_flag():
    # 불리언이 아닌 값(문자열 등)은 미지정 취급 → field 폴백
    assert resolve_write_mode("col22", "yes") == "replace"
    assert resolve_write_mode("item_content", "no") == "append"


def test_load_handoff_config_missing(tmp_path: Path):
    assert load_handoff_config(tmp_path / "absent.yaml") == {}


def test_load_handoff_config_reads_tree(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text("handoff:\n  qa:\n    enable: true\n    field: col22\n", encoding="utf-8")
    assert load_handoff_config(cfg) == {"qa": {"enable": True, "field": "col22"}}


def test_load_handoff_config_no_handoff_key(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text("branches:\n  staging: stage\n", encoding="utf-8")
    assert load_handoff_config(cfg) == {}


def test_resolve_handoff_filters_disabled(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n"
        "  summary:\n    enable: false\n    author: AI\n    field: item_content\n"
        "  qa:\n    enable: true\n    author: AI\n"
        "    AskUserQuestion: true\n    field: col22\n"
        '    instruction: "QA 인수인계"\n',
        encoding="utf-8",
    )
    result = resolve_handoff(cfg, tmp_path / "p", tmp_path / "h")
    assert [r["kind"] for r in result] == ["qa"]
    assert result[0]["source_mode"] == "ai_guided"
    assert result[0]["write_mode"] == "replace"
    assert result[0]["template_path"] is None
    assert result[0]["instruction"] == "QA 인수인계"


def test_resolve_handoff_skips_non_dict_and_missing_enable(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n  bad: 123\n  qa:\n    author: AI\n    field: col22\n",  # enable 없음 → skip
        encoding="utf-8",
    )
    assert resolve_handoff(cfg, tmp_path / "p", tmp_path / "h") == []


def test_resolve_source_mode_value_is_literal():
    # value 가 있으면 author/AskUserQuestion 보다 우선해 literal
    assert resolve_source_mode({"value": "완료", "author": "AI"}) == "literal"
    assert resolve_source_mode({"value": "${today}", "AskUserQuestion": True}) == "literal"


def test_resolve_source_mode_no_value_unchanged():
    # value 없으면 기존 결정 그대로(회귀)
    assert resolve_source_mode({"author": "AI"}) == "ai_auto"
    assert resolve_source_mode({"author": "bsyu", "AskUserQuestion": True}) == "human_ask"


def test_resolve_handoff_includes_value_and_append(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n"
        "  done_date:\n    enable: true\n    field: col30\n"
        '    value: "${today}"\n    append: false\n'
        "  progress_log:\n    enable: true\n    field: col33\n    append: true\n",
        encoding="utf-8",
    )
    result = resolve_handoff(cfg, tmp_path / "p", tmp_path / "h")
    by_kind = {r["kind"]: r for r in result}
    assert by_kind["done_date"]["value"] == "${today}"
    assert by_kind["done_date"]["source_mode"] == "literal"
    assert by_kind["done_date"]["write_mode"] == "replace"
    assert by_kind["progress_log"]["value"] is None
    assert by_kind["progress_log"]["write_mode"] == "append"
    assert by_kind["progress_log"]["source_mode"] == "human_doc"


def test_resolve_field_string_is_teamer_vocabulary():
    # colXX/item_content 는 Teamer 어휘 — Recoble 은 해석하지 않고 기본 대상으로 감
    assert resolve_field({"field": "col22"}, "teamer") == "col22"
    assert resolve_field({"field": "col22"}, "recoble") == "comment"
    assert resolve_field({"field": "item_content"}, "recoble") == "comment"


def test_resolve_field_missing_key_keeps_teamer_empty_string():
    # field 부재는 기존과 같이 빈 문자열(회귀)
    assert resolve_field({}, "teamer") == ""
    assert resolve_field({}, "recoble") == "comment"


def test_resolve_field_dict_selects_per_provider():
    spec = {"field": {"teamer": "col22", "recoble": "custom:field_17"}}
    assert resolve_field(spec, "teamer") == "col22"
    assert resolve_field(spec, "recoble") == "custom:field_17"


def test_resolve_field_dict_without_provider_key_is_none():
    # 명시적 선언이므로 없는 provider 에는 보내지 않음
    assert resolve_field({"field": {"recoble": "description"}}, "teamer") is None
    assert resolve_field({"field": {"teamer": "col22"}}, "recoble") is None


def test_resolve_field_literal_does_not_fall_through_to_a_recoble_comment():
    """`literal` 은 Teamer 필드에 값을 꽂으려는 선언이지 Recoble 에 할 말이 아님.

    문자열 `field` 는 Teamer 어휘라 Recoble 에서 기본 대상(`comment`)으로 떨어지는데,
    `value` 가 있는 종류에까지 그 폴백이 걸리면 example 이 이미 슬롯으로 들고 있는
    `done_flag: {field: col31, value: "완료"}` 가 본문이 "완료" 한 단어인 댓글이 되어
    sync 마다 새로 쌓임. literal 을 Recoble 로 보내려면 provider 별 dict 로 대상을
    **명시**해야 함 — 그 경우는 아래 두 번째 단언이 그대로 통과시킴.
    """
    assert resolve_field({"field": "col31", "value": "완료"}, "recoble") is None
    assert resolve_field({"field": "col30", "value": "${today}"}, "recoble") is None
    # 명시 선언은 막지 않음.
    spec = {"field": {"recoble": "custom:field_9"}, "value": "완료"}
    assert resolve_field(spec, "recoble") == "custom:field_9"
    # Teamer 쪽은 회귀 없이 그대로.
    assert resolve_field({"field": "col31", "value": "완료"}, "teamer") == "col31"


def test_resolve_write_mode_recoble_defaults():
    assert resolve_write_mode("comment", None, "recoble") == "append"
    assert resolve_write_mode("description", None, "recoble") == "append"
    assert resolve_write_mode("custom:field_17", None, "recoble") == "replace"
    assert resolve_write_mode("progress", None, "recoble") == "replace"


def test_resolve_write_mode_append_flag_wins_for_both_providers():
    assert resolve_write_mode("comment", False, "recoble") == "replace"
    assert resolve_write_mode("custom:field_17", True, "recoble") == "append"
    assert resolve_write_mode("col22", True, "teamer") == "append"


def test_resolve_handoff_recoble_drops_a_literal_aimed_at_a_teamer_field(tmp_path: Path):
    """`kinds` 는 task-sync 가 실제로 소비하는 층임 — 그 층에서 빠지는지를 잠금.

    위 단위 테스트는 `resolve_field` 만 봄. 이 저장소가 출하하는 example 슬롯 모양
    (`done_flag: {field: col31, value: "완료"}`)이 Recoble 에서 `kinds` 에 남으면
    task-sync R3·R4 가 본문이 "완료" 한 단어인 댓글을 매 sync 마다 새로 달게 됨.
    Teamer 쪽에서는 그대로 남아야 하므로 같은 config 로 두 provider 를 함께 측정.
    """
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n"
        "  summary:\n    enable: true\n    author: AI\n    field: item_content\n"
        "  done_flag:\n    enable: true\n    field: col31\n"
        '    value: "완료"\n',
        encoding="utf-8",
    )
    recoble = {r["kind"] for r in resolve_handoff(cfg, tmp_path / "p", tmp_path / "h", "recoble")}
    assert recoble == {"summary"}, "문자열 field 를 가진 literal 이 Recoble 댓글로 샜다"
    teamer = {r["kind"] for r in resolve_handoff(cfg, tmp_path / "p", tmp_path / "h", "teamer")}
    assert teamer == {"summary", "done_flag"}, "Teamer 쪽 literal 이 회귀했다"


def test_resolve_handoff_recoble_uses_mapped_field(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n"
        "  summary:\n    enable: true\n    author: AI\n    field: item_content\n"
        "  qa:\n    enable: true\n    author: AI\n"
        "    field:\n      teamer: col22\n      recoble: description\n"
        "  done_flag:\n    enable: true\n"
        "    field:\n      teamer: col31\n"
        '    value: "완료"\n',
        encoding="utf-8",
    )
    result = resolve_handoff(cfg, tmp_path / "p", tmp_path / "h", "recoble")
    by_kind = {r["kind"]: r for r in result}
    assert set(by_kind) == {"summary", "qa"}, "teamer 키만 있는 종류는 Recoble 에서 빠진다"
    assert by_kind["summary"]["field"] == "comment"
    assert by_kind["summary"]["write_mode"] == "append"
    assert by_kind["qa"]["field"] == "description"
    assert by_kind["qa"]["write_mode"] == "append"
    assert by_kind["qa"]["provider"] == "recoble"


def test_resolve_handoff_teamer_is_unchanged_by_the_provider_arg(tmp_path: Path):
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n  qa:\n    enable: true\n    author: AI\n    field: col22\n",
        encoding="utf-8",
    )
    default = resolve_handoff(cfg, tmp_path / "p", tmp_path / "h")
    explicit = resolve_handoff(cfg, tmp_path / "p", tmp_path / "h", "teamer")
    assert default == explicit
    assert default[0]["field"] == "col22" and default[0]["write_mode"] == "replace"
