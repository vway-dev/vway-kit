"""`harnesses` 키 읽기 — 어떤 하네스에 게이트를 심을지와, 그 목록을 믿어도 되는지를 잼.

- 키 부재 = `[claude]` — Codex 이전에 설치된 모든 호스트가 바뀌지 않은 그 호스트.
- 예시 config 의 슬롯은 주석이라 `[config 슬롯 점검]` 이 기존 호스트에 새 슬롯을 권하지 않음.
"""

from pathlib import Path

import scripts.vdev_init_setup as vis
from tests.harnesses.setup_wiring._helpers import _cfg
from tests.vdev_init._helpers import PLUGIN


def test_absent_key_means_claude_only(tmp_path: Path):
    assert vis.load_harnesses(tmp_path) == (["claude"], [], True)


def test_claude_is_always_first_and_unknowns_are_reported(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [codex, gemini, antigravity]\n")
    names, lines, reliable = vis.load_harnesses(tmp_path)
    assert names == ["claude", "codex"]
    assert any("gemini" in line and "[!]" in line for line in lines), lines
    assert any("antigravity" in line and "[=]" in line for line in lines), lines
    # 잘 짜인 목록 속 모르는 이름 하나는 그 이름에 대한 사실이지 목록 전체의 것이 아님.
    assert reliable is True


def test_a_repeated_or_explicit_claude_name_is_not_duplicated(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [claude, codex, codex]\n")
    assert vis.load_harnesses(tmp_path)[0] == ["claude", "codex"]


def test_a_non_list_harnesses_value_is_reported_and_stays_claude_only(tmp_path: Path):
    _cfg(tmp_path, "harnesses: codex\n")
    names, lines, reliable = vis.load_harnesses(tmp_path)
    assert names == ["claude"]
    assert any("[!]" in line and "harnesses" in line for line in lines), lines
    assert reliable is False


def test_an_explicit_claude_only_list_reads_as_the_absent_key(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [claude]\n")
    assert vis.load_harnesses(tmp_path) == vis.load_harnesses(tmp_path / "absent")


def test_the_example_carries_the_slot_only_as_a_comment():
    text = (PLUGIN / vis.EXAMPLE_CONFIG).read_text(encoding="utf-8")
    assert "# harnesses: [claude, codex]" in text
    assert "harnesses" not in vis._load_yaml_safe(PLUGIN / vis.EXAMPLE_CONFIG)


def test_the_slot_report_does_not_offer_the_commented_slot(tmp_path: Path):
    """예시 전체를 가진 기존 호스트 — 새 주석 슬롯 때문에 `[i]` 가 새로 뜨면 안 됨."""
    _cfg(tmp_path, (PLUGIN / vis.EXAMPLE_CONFIG).read_text(encoding="utf-8"))
    assert vis.report_missing_config_slots(tmp_path, PLUGIN) == ["  [=] config 슬롯 최신 (skip)"]
    assert "harnesses" not in [s["label"] for s in vis.missing_config_slots(tmp_path, PLUGIN)]
