"""`--scan` — repo 측 목록. 매칭 키를 repo 가 지는 쪽의 유일한 판독기.

먼저 단언하는 것은 `docs/srs` 부재 계약임: 모든 하위 명령이 이를 상속하고, SRS 가
없는 저장소는 대응할 수 없는 경고 대신 무출력이어야 함.
"""

from pathlib import Path

from scripts import alm_docs
from tests.alm_docs._helpers import read_json, run, write

ONE = (
    '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 카드·간편결제를 지원함.'
    " <!-- alm: dev3/REQ-118 -->\n"
)


def test_no_srs_dir_writes_nothing_and_says_nothing(tmp_path: Path, capsys):
    out = tmp_path / "scan.json"
    code, text = run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert code == 0
    assert text == ""
    assert not out.exists()


def test_scan_reads_anchor_kind_area_line_title_and_alm(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", "# Payment\n\n" + ONE)
    out = tmp_path / "scan.json"
    code, _ = run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert code == 0
    assert read_json(out) == {
        "root": "docs/srs",
        "items": [
            {
                "anchor": "fr-payment-001",
                "kind": "FR",
                "area": "payment",
                "file": "docs/srs/payment.md",
                "line": 3,
                "title": "카드·간편결제를 지원함.",
                "alm": {"dev3": "REQ-118"},
            }
        ],
    }


def test_an_example_anchor_in_a_code_fence_is_not_scanned(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", '```markdown\n<a id="fr-payment-009"></a>\n```\n')
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert read_json(out)["items"] == []


def test_an_example_anchor_in_an_html_comment_is_not_scanned(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", '<!-- <a id="fr-payment-009"></a> -->\n')
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert read_json(out)["items"] == []


def test_a_line_number_survives_a_fence_above_it(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", "```\nx\ny\n```\n" + ONE)
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert read_json(out)["items"][0]["line"] == 5


def test_two_spaces_take_two_comments(tmp_path: Path, capsys):
    line = (
        '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 결제함.'
        " <!-- alm: dev3/REQ-118 --> <!-- alm: labs/REQ-7 -->\n"
    )
    write(tmp_path, "docs/srs/payment.md", line)
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    item = read_json(out)["items"][0]
    assert item["alm"] == {"dev3": "REQ-118", "labs": "REQ-7"}
    assert item["title"] == "결제함."


def test_an_unrelated_comment_leaves_the_title_and_keeps_the_mapping(tmp_path: Path, capsys):
    """`alm:` 아닌 주석도 제목에서 빠짐 — 남으면 그 글자가 영구 「제목 다름」을 세우고
    `--push` 가 주석 텍스트를 보드 항목 제목에 써 넣음.
    """
    line = (
        '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 카드 결제를 지원함.'
        " <!-- alm: dev3/REQ-118 --> <!-- TODO: 문장 다듬기 -->\n"
    )
    write(tmp_path, "docs/srs/payment.md", line)
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    item = read_json(out)["items"][0]
    assert item["title"] == "카드 결제를 지원함."
    assert item["alm"] == {"dev3": "REQ-118"}


def test_readme_anchors_carry_no_area(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/README.md", '<a id="c-003"></a>**C-003** 제약함.\n')
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    item = read_json(out)["items"][0]
    assert (item["kind"], item["area"], item["alm"]) == ("C", None, {})


def test_kinds_outside_fr_and_c_are_dropped(tmp_path: Path, capsys):
    write(
        tmp_path,
        "docs/srs/payment.md",
        '<a id="nfr-payment-001"></a>**NFR-PAYMENT-001** 빠름.\n' + ONE,
    )
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert [i["anchor"] for i in read_json(out)["items"]] == ["fr-payment-001"]


def test_an_anchor_without_a_trailing_number_is_dropped(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", '<a id="fr-payment"></a>**FR** 축이다.\n')
    out = tmp_path / "scan.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert read_json(out)["items"] == []


def test_a_broken_tag_body_in_the_title_cannot_cross_a_new_tag():
    """`<` 를 넘는 순간 `_A_ANY_TAG_RE` 의 태그 본문이 멈춤 — `_md_anchors._A_TAG_RE` 와 같은
    시작-자리 이차성이 가르는 경계(`tests/md_anchors/test_linearity.py` 의 `_CROSS_CASES` 가
    형제 패턴에서 재는 것과 같은 성질). 옛 패턴은 앞뒤 두 태그를 하나로 먹어 `<a foo ` 까지
    지웠음.
    """
    assert alm_docs._title('<a foo <a id="x">**FR-X-001** 제목') == "<a foo 제목"


def test_the_srs_location_is_not_redefined_here():
    """`docs/srs` 의 자리는 `srs_check` 하나가 쥠 — 재정의면 어느 한쪽만 고쳐도 갈라짐."""
    from scripts import srs_check

    assert alm_docs.SRS_REL == srs_check.SRS_REL
    assert alm_docs.INDEX_STEM == srs_check.INDEX_STEM
    body = Path(alm_docs.__file__).read_text(encoding="utf-8")
    for name in ("SRS_REL =", "INDEX_STEM ="):
        assert name not in body, f"{name} 가 alm_docs 에 아직 정의돼 있음"
