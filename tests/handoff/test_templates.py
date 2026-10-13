"""템플릿 해석 — rel 규칙·호스트 우선·구경로 폴백 알림.

무엇이 template_path 가 되는가, 그리고 그 자리가 옮겨진 뒤에도 호스트가 자기 양식이
안 쓰이는 것을 알 수 있는가."""

from pathlib import Path

from scripts._vway_paths import vway_dir
from scripts.handoff_resolve import (
    legacy_template_warnings,
    resolve_handoff,
    resolve_template_path,
)
from tests.handoff._helpers import _mk


def test_resolve_template_path_host_overrides_plugin(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    _mk(vway_dir(host) / "templates" / "handoff" / "summary.md", "H")
    assert resolve_template_path({}, "summary", plugin, host) == str(
        vway_dir(host) / "templates" / "handoff" / "summary.md"
    )


def test_resolve_template_path_plugin_fallback(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    assert resolve_template_path({}, "summary", plugin, host) == str(
        plugin / "templates" / "handoff" / "summary.md"
    )


def test_resolve_template_path_implicit_kind_lookup(tmp_path: Path):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    _mk(plugin / "templates" / "handoff" / "qa.md", "Q")
    assert resolve_template_path({}, "qa", plugin, host) == str(
        plugin / "templates" / "handoff" / "qa.md"
    )


def test_resolve_template_path_explicit_value(tmp_path: Path):
    """적힌 경로는 확장자까지 그대로 — 암묵 탐색만 md 로 고정됨."""
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    _mk(plugin / "templates" / "custom" / "x.md", "X")
    assert resolve_template_path({"template": "custom/x.md"}, "qa", plugin, host) == str(
        plugin / "templates" / "custom" / "x.md"
    )


def test_resolve_template_path_missing_returns_none(tmp_path: Path):
    assert resolve_template_path({}, "qa", tmp_path / "p", tmp_path / "h") is None


def test_implicit_template_lookup_is_markdown_for_every_target(tmp_path: Path):
    """암묵 탐색 확장자는 대상과 무관하게 md — 나란히 놓인 .html 은 후보가 아님.

    확장자가 대상마다 갈리면 같은 규칙을 담은 자매 템플릿 둘이 생기고, 한쪽만 고친
    순간 두 ALM 이 서로 다른 요약을 받음.
    """
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    _mk(plugin / "templates" / "handoff" / "summary.html", "H")
    _mk(plugin / "templates" / "handoff" / "summary.md", "M")
    assert resolve_template_path({}, "summary", plugin, host) == str(
        plugin / "templates" / "handoff" / "summary.md"
    )


def test_implicit_lookup_ignores_a_stray_html_sibling(tmp_path: Path):
    """.md 가 없으면 template_path 는 null — .html 로 조용히 떨어지지 않음."""
    plugin = tmp_path / "plugin"
    _mk(plugin / "templates" / "handoff" / "summary.html", "H")
    assert resolve_template_path({}, "summary", plugin, tmp_path / "h") is None


def test_the_shipped_summary_template_is_one_markdown_file():
    """.md 가 없으면 template_path 가 null 로 떨어지고, 스킬이 '템플릿 없음'
    폴백(일반 요약)으로 조용히 내려감. .html 자매의 부활도 함께 막음 — 그것이
    돌아오면 규칙이 두 곳에 살고 provider 마다 다른 요약이 나감."""
    shipped = Path(__file__).resolve().parents[2] / "templates" / "handoff"
    assert (shipped / "summary.md").is_file()
    assert not (shipped / "summary.html").exists()


def test_resolve_handoff_gives_both_providers_the_same_markdown_template(tmp_path: Path):
    """task-sync 가 실제로 소비하는 층에서 두 provider 가 한 파일을 받는지 잠금."""
    plugin = tmp_path / "plugin"
    _mk(plugin / "templates" / "handoff" / "summary.html", "H")
    _mk(plugin / "templates" / "handoff" / "summary.md", "M")
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(
        "handoff:\n  summary:\n    enable: true\n    author: AI\n    field: item_content\n",
        encoding="utf-8",
    )
    recoble = resolve_handoff(cfg, plugin, tmp_path / "h", "recoble")[0]
    assert recoble["field"] == "comment"
    assert recoble["template_path"].endswith("summary.md")

    teamer = resolve_handoff(cfg, plugin, tmp_path / "h", "teamer")[0]
    assert teamer["field"] == "item_content"
    assert teamer["template_path"] == recoble["template_path"]
    # 형식이 하나뿐이라 형식 키 자체가 없음 — 스킬이 그 키를 읽지 않게 함께 잠금.
    assert "content_format" not in teamer and "content_format" not in recoble


def test_legacy_template_warning_names_an_unmigrated_override(tmp_path: Path):
    """구경로에 양식을 둔 채 /vdev-init 을 안 돌린 호스트는 출하본으로 떨어짐 —
    그 폴백이 조용하면 나가는 요약이 자기 양식이 아님을 알 길이 없음."""
    host = tmp_path / "host"
    cfg = host / "vdev-config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "handoff:\n  summary:\n    enable: true\n    field: item_content\n", encoding="utf-8"
    )
    _mk(host / "templates" / "handoff" / "summary.md", "old")
    warnings = legacy_template_warnings(cfg, host)
    assert any("handoff/summary.md" in w for w in warnings)


def test_legacy_template_warning_is_silent_once_migrated(tmp_path: Path):
    host = tmp_path / "host"
    cfg = host / "vdev-config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "handoff:\n  summary:\n    enable: true\n    field: item_content\n", encoding="utf-8"
    )
    _mk(host / "templates" / "handoff" / "summary.md", "old")
    _mk(vway_dir(host) / "templates" / "handoff" / "summary.md", "new")
    assert legacy_template_warnings(cfg, host) == []


def test_legacy_template_warning_covers_the_unconfigured_summary(tmp_path: Path):
    """handoff 설정이 없는 호스트가 바로 그 폴백을 타는 쪽 — 경고가 거기 없으면
    정작 조용해지는 저장소에서 조용함."""
    host = tmp_path / "host"
    cfg = host / "vdev-config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("branches:\n  staging: stage\n", encoding="utf-8")
    _mk(host / "templates" / "handoff" / "summary.md", "old")
    assert any("handoff/summary.md" in w for w in legacy_template_warnings(cfg, host))


def test_legacy_template_warning_skips_a_disabled_kind(tmp_path: Path):
    """`enable: false` 종류는 아무것도 안 나감 — 경고가 나면 인과가 거짓."""
    host = tmp_path / "host"
    cfg = host / "vdev-config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("handoff:\n  qa:\n    enable: false\n    field: col22\n", encoding="utf-8")
    _mk(host / "templates" / "handoff" / "qa.md", "old")
    assert legacy_template_warnings(cfg, host) == []


def test_resolve_template_path_survives_a_non_string_kind(tmp_path: Path):
    """YAML 은 `2024:`·`on:`·`~:` 를 문자열 아닌 키로 줌 — 그 키 하나가 예외를 흘리면
    task-sync·task-import 의 handoff 단계 전체가 죽음(자매 alm_layers 는 이미 견딤)."""
    for kind in (2024, 1.0, True, None):
        assert resolve_template_path({}, kind, tmp_path / "p", tmp_path / "h") is None


def test_legacy_template_warning_skips_a_kind_aimed_at_another_provider(tmp_path: Path):
    """대상이 다른 provider 인 종류는 이 실행에서 아무것도 안 나감 — 경고가 나면
    task-sync 가 '아무것도 쓰지 마라' 와 '출하본이 나가는 중' 을 함께 말함."""
    host = tmp_path / "host"
    cfg = host / "vdev-config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "handoff:\n  qa:\n    enable: true\n    field:\n      teamer: col22\n", encoding="utf-8"
    )
    _mk(host / "templates" / "handoff" / "qa.md", "old")
    assert legacy_template_warnings(cfg, host, "recoble") == []
    assert legacy_template_warnings(cfg, host, "teamer") != []


def test_legacy_template_warning_survives_a_scalar_kind(tmp_path: Path):
    """자매 `resolve_handoff` 는 같은 config 를 견딤 — 이쪽만 죽으면 handoff 단계가 exit 1."""
    host = tmp_path / "host"
    cfg = host / "vdev-config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("handoff:\n  summary: just-a-string\n", encoding="utf-8")
    assert legacy_template_warnings(cfg, host, "recoble") == []
