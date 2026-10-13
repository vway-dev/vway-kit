"""code-style 렌즈 — 스택별 블록을 정해진 순서로 끼움.

비표준 문서는 건드리지 않고 경고함. 손으로 쓴 문서를 재배열하면 사람이 잃는 것이
얻는 것보다 큼.
"""

import pytest

import scripts.harness_scaffold as hs
from tests.harness._helpers import (
    _lensed,
)


def test_classify_nonstandard_when_no_bp_heading():
    r = hs.classify_code_style_doc("# 제목\n## 툴체인\n내용\n", "react")
    assert r == {"state": "nonstandard", "present": []}


def test_classify_flat_when_bp_heading_no_markers():
    r = hs.classify_code_style_doc("## 베스트 프랙티스\n- 자유 산문\n", "react")
    assert r == {"state": "flat", "present": []}


def test_classify_lensed_collects_present_in_canonical_order():
    text = (
        "## 베스트 프랙티스\n"
        "<!-- code-style:lens:react:ux BEGIN (managed) -->\n"
        "### UX\n"
        "<!-- code-style:lens:react:ux END -->\n"
        "<!-- code-style:lens:react:correctness BEGIN (managed) -->\n"
        "### 정확성\n"
        "<!-- code-style:lens:react:correctness END -->\n"
    )
    r = hs.classify_code_style_doc(text, "react")
    assert r["state"] == "lensed"
    assert r["present"] == ["correctness", "ux"]  # LENS_KEYS 순서(정확성 먼저)


def test_classify_ignores_other_stack_markers():
    text = (
        "## 베스트 프랙티스\n"
        "<!-- code-style:lens:go:ux BEGIN -->\nx\n<!-- code-style:lens:go:ux END -->\n"
    )
    assert hs.classify_code_style_doc(text, "react") == {"state": "flat", "present": []}


def test_classify_flat_recognizes_english_heading():
    assert (
        hs.classify_code_style_doc("## Best Practices (by lens)\n- x\n", "react")["state"] == "flat"
    )


def test_scan_code_style_reports_states(tmp_path):
    d = tmp_path / "docs/code-style"
    d.mkdir(parents=True)
    (d / "README.md").write_text("index\n", encoding="utf-8")
    (d / "react.md").write_text("## 베스트 프랙티스\n- 산문\n", encoding="utf-8")
    (d / "go.md").write_text(
        "## 베스트 프랙티스\n<!-- code-style:lens:go:ux BEGIN -->\n"
        "x\n<!-- code-style:lens:go:ux END -->\n",
        encoding="utf-8",
    )
    rows = hs.scan_code_style(tmp_path)
    by = {r["stack"]: r for r in rows}
    assert "README" not in by  # README 제외
    assert by["react"]["state"] == "flat"
    assert by["go"]["state"] == "lensed" and by["go"]["present"] == ["ux"]


def test_lens_marker_id_format():
    assert hs._lens_marker_id("typescript-react", "ux") == "code-style:lens:typescript-react:ux"


def test_upsert_lens_insert_after_heading_when_empty():
    out = hs.upsert_lens_block("## 베스트 프랙티스\n", "react", "ux", "### UX\n- a")
    assert "code-style:lens:react:ux BEGIN" in out
    # 헤딩 바로 다음에 위치
    assert out.splitlines()[1].startswith("<!-- code-style:lens:react:ux BEGIN")


def test_upsert_lens_inserts_in_canonical_order():
    # correctness(0) 와 ux(4) 존재 → performance(3) 는 그 사이(ux 앞)에 삽입
    text = _lensed(("correctness", "### 정확성"), ("ux", "### UX"))
    out = hs.upsert_lens_block(text, "react", "performance", "### 성능")
    pos_perf = out.index("react:performance BEGIN")
    pos_corr = out.index("react:correctness BEGIN")
    pos_ux = out.index("react:ux BEGIN")
    assert pos_corr < pos_perf < pos_ux


def test_upsert_lens_appends_after_last_when_highest():
    text = _lensed(("correctness", "### 정확성"))
    out = hs.upsert_lens_block(text, "react", "cross-cutting", "### 계층 횡단")
    assert out.index("react:correctness BEGIN") < out.index("react:cross-cutting BEGIN")


def test_upsert_lens_replaces_existing_block():
    text = _lensed(("ux", "### UX\n- old"))
    out = hs.upsert_lens_block(text, "react", "ux", "### UX\n- new")
    assert "- new" in out and "- old" not in out
    assert out.count("react:ux BEGIN") == 1


def test_upsert_lens_corrupt_marker_raises():
    # END 없음
    text = "## 베스트 프랙티스\n<!-- code-style:lens:react:ux BEGIN (managed) -->\n### UX\n"

    with pytest.raises(ValueError):
        hs.upsert_lens_block(text, "react", "ux", "### UX\n- x")


def test_upsert_lens_no_heading_raises():

    with pytest.raises(ValueError):
        hs.upsert_lens_block("## 툴체인\n내용\n", "react", "ux", "### UX")


def test_replace_bp_section_preserves_neighbors():
    text = "## 네이밍\n- n\n\n## 베스트 프랙티스\n- 옛 산문\n\n## 툴체인\n- t\n"
    out = hs.replace_bp_section(text, "<!-- b -->\n### X\n<!-- e -->\n")
    assert "옛 산문" not in out
    assert "## 네이밍" in out and "## 툴체인" in out
    assert "### X" in out
    # 순서 유지: 네이밍 < 베스트 < 툴체인
    assert out.index("## 네이밍") < out.index("## 베스트") < out.index("## 툴체인")


def test_replace_bp_section_eof_when_last():
    text = "## 네이밍\n- n\n\n## 베스트 프랙티스\n- 옛\n"
    out = hs.replace_bp_section(text, "### X\n")
    assert out.rstrip().endswith("### X")
    assert "옛" not in out


def test_replace_bp_section_no_heading_raises():

    with pytest.raises(ValueError):
        hs.replace_bp_section("## 툴체인\n- t\n", "### X\n")
