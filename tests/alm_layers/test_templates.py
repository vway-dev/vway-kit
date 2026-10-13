"""계층 본문 템플릿 — 구경로 폴백 알림.

호스트가 자기 양식을 잃고 출하본으로 떨어지는 것을 소비자가 댈 수 있는가."""

from pathlib import Path

from scripts.alm_layers import resolve_layers
from tests.alm_layers._helpers import CONFIG, write_config


def test_resolve_layers_warns_about_an_unmigrated_legacy_template(tmp_path: Path):
    """구경로에 계층 양식을 둔 채 셋업을 안 돌린 호스트는 출하본으로 떨어짐 —
    그 폴백이 조용하면 나가는 본문이 자기 양식이 아님을 알 길이 없음."""
    cfg = write_config(tmp_path, CONFIG)
    host = tmp_path / "host"
    legacy = host / "templates" / "alm"
    legacy.mkdir(parents=True)
    (legacy / "design.md").write_text("host", encoding="utf-8")
    out = resolve_layers(cfg, "dev3", tmp_path / "plugin", host)
    assert any("design" in w and "구경로" in w for w in out["warnings"])


def test_resolve_layers_is_silent_once_the_template_moved(tmp_path: Path):
    from scripts._vway_paths import vway_dir

    cfg = write_config(tmp_path, CONFIG)
    host = tmp_path / "host"
    for root in (host / "templates" / "alm", vway_dir(host) / "templates" / "alm"):
        root.mkdir(parents=True)
        (root / "design.md").write_text("x", encoding="utf-8")
    out = resolve_layers(cfg, "dev3", tmp_path / "plugin", host)
    assert not any("구경로" in w for w in out["warnings"])
