"""`--apply-pull`·`--record` — 문서를 다시 쓰는 쪽.

재는 것 셋: 두 번 돌려도 한 번과 같은가(멱등), 일부만 성공해도 성공한 것이 남는가,
원본의 줄끝이 살아남는가. 마지막이 조용히 깨지는 쪽 — 개발 호스트는 CRLF, CI 는 LF 라
줄끝이 뒤집히면 한 줄 편집이 파일 전체 diff 로 나감.
"""

import json
from pathlib import Path

from tests.alm_docs._helpers import read_json, run, write

BARE = '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 결제함.\n'
ONE = '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 결제함. <!-- alm: dev3/REQ-1 -->\n'


def _rec(space: str, item_id: str, anchor: str = "fr-payment-001") -> dict:
    """되쓰기 한 줄 — 줄이 100자를 안 넘게 하는 축약."""
    return {
        "file": "docs/srs/payment.md",
        "anchor": anchor,
        "space": space,
        "item": item_id,
    }


def _plan(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _pull(tmp_path, capsys, writes):
    return run(
        ["--root", str(tmp_path), "--apply-pull", "--plan", _plan(tmp_path, {"writes": writes})],
        capsys,
    )


def _record(tmp_path, capsys, records):
    return run(
        ["--root", str(tmp_path), "--record", "--map", _plan(tmp_path, {"records": records})],
        capsys,
    )


def _read_payment(tmp_path: Path) -> str:
    return (tmp_path / "docs" / "srs" / "payment.md").read_text(encoding="utf-8")


_WRITE = {
    "file": "docs/srs/payment.md",
    "anchor": "fr-payment-002",
    "id": "FR-PAYMENT-002",
    "title": "정기 결제를 지원함",
    "alm": {"dev3": "REQ-204"},
}


def test_apply_pull_appends_the_line_with_the_review_mark(tmp_path: Path, capsys):
    path = write(tmp_path, "docs/srs/payment.md", "# Payment\n")
    code, text = _pull(tmp_path, capsys, [_WRITE])
    assert code == 0
    body = path.read_text(encoding="utf-8")
    assert (
        '<a id="fr-payment-002"></a>**FR-PAYMENT-002** 정기 결제를 지원함 (확인 필요)'
        " <!-- alm: dev3/REQ-204 -->" in body
    )
    assert "[+]" in text


def test_apply_pull_is_idempotent(tmp_path: Path, capsys):
    path = write(tmp_path, "docs/srs/payment.md", "# Payment\n")
    _pull(tmp_path, capsys, [_WRITE])
    first = path.read_text(encoding="utf-8")
    code, text = _pull(tmp_path, capsys, [_WRITE])
    assert code == 0
    assert path.read_text(encoding="utf-8") == first
    assert "[=]" in text


def test_apply_pull_skips_a_missing_file_and_keeps_going(tmp_path: Path, capsys):
    path = write(tmp_path, "docs/srs/payment.md", "# Payment\n")
    missing = dict(_WRITE, file="docs/srs/refund.md", anchor="fr-refund-001")
    code, text = _pull(tmp_path, capsys, [missing, _WRITE])
    assert code == 0
    assert "[!]" in text and "refund" in text
    assert "fr-payment-002" in path.read_text(encoding="utf-8")


def test_apply_pull_adds_a_final_newline_when_the_file_lacks_one(tmp_path: Path, capsys):
    path = tmp_path / "docs" / "srs" / "payment.md"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# Payment")
    _pull(tmp_path, capsys, [_WRITE])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Payment"
    assert lines[1].startswith('<a id="fr-payment-002">')


def test_apply_pull_keeps_crlf(tmp_path: Path, capsys):
    path = tmp_path / "docs" / "srs" / "payment.md"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# Payment\r\n")
    _pull(tmp_path, capsys, [_WRITE])
    with path.open("r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    # 줄끝이 **정확히** CRLF 하나 — `newline=None` 되돌림은 `\r\r\n` 을 내므로 조각에
    # 고아 `\r` 이 남음. `"\r\n" in raw` 만으로는 그것이 안 잡힘.
    parts = raw.split("\r\n")
    assert len(parts) == 3
    assert parts[0] == "# Payment"
    assert parts[2] == ""
    assert not [p for p in parts if "\r" in p or "\n" in p]


def test_the_review_mark_is_not_a_title_drift(tmp_path: Path, capsys):
    """수입한 줄을 되스캔해 같은 보드와 대조하면 「제목 다름」이 0건 — 왕복이 닫힌 증거.

    `REVIEW_MARK` 가 제목 비교에 들어가면 수입 직후의 상태가 곧 가짜 드리프트이고,
    이어지는 `--push` 가 그 표식을 보드 제목에 써 넣음.
    """
    write(tmp_path, "docs/srs/payment.md", "# Payment\n")
    _pull(tmp_path, capsys, [_WRITE])
    repo = tmp_path / "repo.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(repo)], capsys)
    board = tmp_path / "board.json"
    board.write_text(
        json.dumps(
            {"space": "dev3", "items": [{"id": "REQ-204", "title": _WRITE["title"]}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "diff.json"
    code, _ = run(
        ["--diff", "--repo", str(repo), "--board", str(board), "--json", str(out)], capsys
    )
    assert code == 0
    assert read_json(out)["counts"]["title_differs"] == 0


def test_a_review_mark_inside_the_sentence_is_still_a_title_drift(tmp_path: Path, capsys):
    """말미가 아닌 자리의 같은 글자는 문장의 일부 — 어디서나 벗기면 두 문장이 같아 보임."""
    write(
        tmp_path,
        "docs/srs/payment.md",
        '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 한도 초과 시 (확인 필요) 알림을 보냄'
        " <!-- alm: dev3/REQ-1 -->\n",
    )
    repo = tmp_path / "repo.json"
    run(["--root", str(tmp_path), "--scan", "--out", str(repo)], capsys)
    board = tmp_path / "board.json"
    board.write_text(
        json.dumps(
            {"space": "dev3", "items": [{"id": "REQ-1", "title": "한도 초과 시 알림을 보냄"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "diff.json"
    code, _ = run(
        ["--diff", "--repo", str(repo), "--board", str(board), "--json", str(out)], capsys
    )
    assert code == 0
    assert read_json(out)["counts"]["title_differs"] == 1


def test_a_plan_without_the_writes_key_names_it(tmp_path: Path, capsys):
    """모델이 최상위 키를 다르게 쓰면 무출력 exit 0 이 아니라 기대한 이름이 나옴."""
    code, text = run(
        ["--root", str(tmp_path), "--apply-pull", "--plan", _plan(tmp_path, {"wrytes": []})],
        capsys,
    )
    assert code == 0
    assert "writes" in text


def test_a_mapping_without_the_records_key_names_it(tmp_path: Path, capsys):
    code, text = run(
        ["--root", str(tmp_path), "--record", "--map", _plan(tmp_path, {"recs": []})], capsys
    )
    assert code == 0
    assert "records" in text


def test_a_record_element_keeping_the_old_key_is_named_not_raised(tmp_path: Path, capsys):
    """원소가 옛 이름을 지니면 트레이스백이 아니라 빠진 이름·자리와 종료 0."""
    path = write(tmp_path, "docs/srs/payment.md", BARE)
    row = _rec("dev3", "REQ-1")
    row["id"] = row.pop("item")
    code, text = _record(tmp_path, capsys, [row])
    assert code == 0
    assert "[!]" in text and "건너뜀: item" in text
    assert path.read_text(encoding="utf-8") == BARE


def test_a_write_missing_a_key_does_not_take_the_sound_one_with_it(tmp_path: Path, capsys):
    path = write(tmp_path, "docs/srs/payment.md", "# Payment\n")
    broken = {k: v for k, v in _WRITE.items() if k != "id"}
    broken["anchor"] = "fr-payment-003"
    code, text = _pull(tmp_path, capsys, [broken, _WRITE])
    assert code == 0
    assert "[!]" in text and "건너뜀: id" in text
    body = path.read_text(encoding="utf-8")
    assert "fr-payment-002" in body
    assert "fr-payment-003" not in body


def test_a_missing_plan_warns_instead_of_raising(tmp_path: Path, capsys):
    """입력 부재는 이 스크립트의 판정이 아님 — 경로를 대는 한 줄과 종료 0."""
    code, text = run(
        ["--root", str(tmp_path), "--apply-pull", "--plan", str(tmp_path / "nope.json")], capsys
    )
    assert code == 0
    assert "nope.json" in text


def test_a_mapping_that_is_not_json_warns_instead_of_raising(tmp_path: Path, capsys):
    bad = tmp_path / "record.json"
    bad.write_text("{", encoding="utf-8")
    code, text = run(["--root", str(tmp_path), "--record", "--map", str(bad)], capsys)
    assert code == 0
    assert "record.json" in text


def test_record_writes_the_comment_onto_the_anchor_line(tmp_path: Path, capsys):
    path = write(tmp_path, "docs/srs/payment.md", BARE)
    code, text = _record(tmp_path, capsys, [_rec("dev3", "REQ-1")])
    assert code == 0
    assert path.read_text(encoding="utf-8") == ONE
    assert "[+]" in text


def test_record_is_idempotent(tmp_path: Path, capsys):
    path = write(tmp_path, "docs/srs/payment.md", ONE)
    code, text = _record(tmp_path, capsys, [_rec("dev3", "REQ-1")])
    assert code == 0
    assert path.read_text(encoding="utf-8") == ONE
    assert "[=]" in text


def test_record_keeps_another_space_and_replaces_its_own(tmp_path: Path, capsys):
    path = write(tmp_path, "docs/srs/payment.md", ONE)
    _record(tmp_path, capsys, [_rec("labs", "REQ-7"), _rec("dev3", "REQ-9")])
    body = path.read_text(encoding="utf-8")
    assert "<!-- alm: dev3/REQ-9 -->" in body
    assert "<!-- alm: labs/REQ-7 -->" in body
    assert "REQ-1 -->" not in body


def test_record_skips_an_anchor_that_is_not_there(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", "# Payment\n")
    code, text = _record(tmp_path, capsys, [_rec("dev3", "REQ-1", "fr-payment-404")])
    assert code == 0
    assert "[!]" in text


def test_record_ignores_an_example_anchor_in_a_fence(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", "```\n" + BARE + "```\n")
    code, text = _record(tmp_path, capsys, [_rec("dev3", "REQ-1")])
    assert code == 0
    assert "[!]" in text


def test_record_keeps_crlf(tmp_path: Path, capsys):
    path = tmp_path / "docs" / "srs" / "payment.md"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(BARE.replace("\n", "\r\n"))
    _record(tmp_path, capsys, [_rec("dev3", "REQ-1")])
    with path.open("r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    assert raw.endswith("<!-- alm: dev3/REQ-1 -->\r\n")


def test_scan_keeps_raw_and_masked_aligned_across_a_form_feed(tmp_path: Path, capsys):
    """코드펜스 안 폼피드(\\x0c)가 splitlines() 를 갈라도 그 아래 앵커 줄 번호가 안 밀림.

    `str.splitlines()` 는 `\\x0c` 도 줄 구분자로 세지만 `mask_examples` 의 마스킹은
    `\\n` 만 개행으로 남기므로, raw 와 masked 를 각자 `splitlines()` 하면 이 자리에서
    두 리스트 길이가 갈라져 그 뒤 앵커의 줄 번호가 통째로 밀림.
    """
    out = tmp_path / "scan.json"
    write(
        tmp_path,
        "docs/srs/payment.md",
        "a\n```\nx\x0cy\n```\n" + ONE,
    )
    code, _ = run(["--root", str(tmp_path), "--scan", "--out", str(out)], capsys)
    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert items[0]["line"] == 6
    assert items[0]["alm"] == {"dev3": "REQ-1"}


def test_record_keeps_a_form_feed_that_ends_the_anchor_line(tmp_path: Path, capsys):
    """`\\x0c` 로 끝난 앵커 줄도 줄끝이 살아 다음 줄과 안 합쳐짐.

    줄을 가른 것이 `splitlines()` 인데 줄끝을 좁은 집합으로 되읽으면 그 구분자가 본문으로
    보이고, 되쓰기의 `rstrip()` 이 그것을 지워 문서가 깨짐.
    """
    body = '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 결제함.'
    write(tmp_path, "docs/srs/payment.md", body + "\x0c다음 줄 본문\n")
    code, text = _record(tmp_path, capsys, [_rec("dev3", "REQ-1")])
    assert code == 0
    assert "[+]" in text
    assert _read_payment(tmp_path) == body + " <!-- alm: dev3/REQ-1 -->\x0c다음 줄 본문\n"


def test_record_keeps_raw_and_masked_aligned_across_a_form_feed(tmp_path: Path, capsys):
    """`scan` 과 같은 정렬 결함을 `record` 쪽에서도 재현·확인."""
    write(
        tmp_path,
        "docs/srs/payment.md",
        "a\n```\nx\x0cy\n```\n" + BARE,
    )
    code, text = _record(tmp_path, capsys, [_rec("dev3", "REQ-1")])
    assert code == 0
    assert "[+]" in text
    assert _read_payment(tmp_path) == "a\n```\nx\x0cy\n```\n" + ONE
