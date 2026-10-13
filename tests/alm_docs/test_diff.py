"""`--diff` — 다섯 갈래와, 갈래를 셀 수 없는 경우.

재는 것 셋: 갈래마다 정확히 그 줄만 켜지는가, 잘린 열거가 두 갈래를 끄는가, 어긋남이
몇 건이든 종료 코드가 0 인가. 마지막이 이 스크립트의 계약 — 판정이 커밋을 막지 않음.
"""

import json
from pathlib import Path

from scripts import alm_docs
from tests.alm_docs._helpers import read_json, run


def _repo(*items) -> dict:
    return {"root": "docs/srs", "items": list(items)}


def _item(anchor: str, title: str, alm: dict) -> dict:
    return {
        "anchor": anchor,
        "kind": "FR",
        "area": "payment",
        "file": "docs/srs/payment.md",
        "line": 3,
        "title": title,
        "alm": alm,
    }


def _board(items, truncated=False, space="dev3") -> dict:
    return {
        "space": space,
        "board": "wb-1",
        "items": list(items),
        "meta": {"pages": 1, "mcp_calls": 1, "truncated": truncated},
    }


def _one(item_id: str, title: str) -> list:
    """항목 하나짜리 보드 목록 — 줄이 100자를 안 넘게 하는 축약."""
    return [{"id": item_id, "title": title}]


def _run(tmp_path: Path, capsys, repo: dict, boards: list):
    repo_path = tmp_path / "repo.json"
    repo_path.write_text(json.dumps(repo, ensure_ascii=False), encoding="utf-8")
    board_paths = []
    for n, board in enumerate(boards):
        p = tmp_path / f"board{n}.json"
        p.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        board_paths.append(str(p))
    out = tmp_path / "diff.json"
    code, text = run(
        ["--diff", "--repo", str(repo_path), "--board", *board_paths, "--json", str(out)],
        capsys,
    )
    return code, text, read_json(out)


def test_an_anchor_with_no_comment_is_never_pushed(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {}))
    code, _, result = _run(tmp_path, capsys, repo, [_board([])])
    assert code == 0
    assert result["counts"]["never_pushed"] == 1
    assert result["drift"]["never_pushed"][0]["anchor"] == "fr-payment-001"


def test_a_comment_naming_a_missing_item_is_a_broken_mapping(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {"dev3": "REQ-9"}))
    _, _, result = _run(tmp_path, capsys, repo, [_board(_one("REQ-1", "결제함"))])
    assert result["counts"]["broken_mapping"] == 1
    assert result["drift"]["broken_mapping"][0]["item"] == "REQ-9"


def test_an_unreferenced_board_item_is_board_only(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {"dev3": "REQ-1"}))
    board = _board(_one("REQ-1", "결제함") + _one("REQ-2", "환불함"))
    _, _, result = _run(tmp_path, capsys, repo, [board])
    assert result["drift"]["board_only"] == [{"space": "dev3", "item": "REQ-2", "title": "환불함"}]


def test_a_differing_title_is_reported_with_both_sides(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "카드로 결제함", {"dev3": "REQ-1"}))
    _, _, result = _run(tmp_path, capsys, repo, [_board(_one("REQ-1", "결제함"))])
    row = result["drift"]["title_differs"][0]
    assert (row["repo_title"], row["board_title"]) == ("카드로 결제함", "결제함")


def test_whitespace_alone_is_not_a_differing_title(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "카드로  결제함", {"dev3": "REQ-1"}))
    _, _, result = _run(tmp_path, capsys, repo, [_board(_one("REQ-1", "카드로 결제함"))])
    assert result["counts"]["title_differs"] == 0


def test_a_trailing_review_mark_on_the_board_is_not_a_title_drift(tmp_path: Path, capsys):
    """대칭 — 사람이 보드 제목 끝에 표식을 남겨도 repo 가 어긋난 것이 아님.

    한쪽만 벗기면 4단계 6번의 Edit 으로 고쳐도 다음 스캔이 또 벗겨 판정이 안 닫힘.
    """
    repo = _repo(_item("fr-payment-001", "정기 결제를 지원함", {"dev3": "REQ-1"}))
    board = _board(_one("REQ-1", "정기 결제를 지원함 (확인 필요)"))
    _, _, result = _run(tmp_path, capsys, repo, [board])
    assert result["counts"]["title_differs"] == 0


def test_a_mark_on_both_sides_does_not_hide_a_real_difference(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "카드로 결제함 (확인 필요)", {"dev3": "REQ-1"}))
    board = _board(_one("REQ-1", "계좌로 결제함 (확인 필요)"))
    _, _, result = _run(tmp_path, capsys, repo, [board])
    assert result["counts"]["title_differs"] == 1


def test_two_anchors_on_one_item_are_a_duplicate_mapping(tmp_path: Path, capsys):
    repo = _repo(
        _item("fr-payment-001", "결제함", {"dev3": "REQ-1"}),
        _item("fr-payment-002", "결제함", {"dev3": "REQ-1"}),
    )
    _, _, result = _run(tmp_path, capsys, repo, [_board(_one("REQ-1", "결제함"))])
    assert result["drift"]["duplicate_mapping"] == [
        {"space": "dev3", "item": "REQ-1", "anchors": ["fr-payment-001", "fr-payment-002"]}
    ]


def test_a_truncated_enumeration_suppresses_both_board_dependent_kinds(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {"dev3": "REQ-9"}))
    board = _board(_one("REQ-1", "환불함"), truncated=True)
    _, text, result = _run(tmp_path, capsys, repo, [board])
    assert result["truncated"] == ["dev3"]
    assert result["counts"]["broken_mapping"] == 0
    assert result["counts"]["board_only"] == 0
    assert "잘린 열거" in text


def test_a_truncated_enumeration_still_counts_what_it_can(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {}))
    _, _, result = _run(tmp_path, capsys, repo, [_board([], truncated=True)])
    assert result["counts"]["never_pushed"] == 1


def test_a_second_space_is_judged_on_its_own(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {"dev3": "REQ-1"}))
    boards = [
        _board(_one("REQ-1", "결제함")),
        _board(_one("REQ-5", "결제함"), space="labs"),
    ]
    _, _, result = _run(tmp_path, capsys, repo, boards)
    assert result["spaces"] == ["dev3", "labs"]
    assert [r["space"] for r in result["drift"]["never_pushed"]] == ["labs"]
    assert [r["space"] for r in result["drift"]["board_only"]] == ["labs"]


def test_two_spaces_missing_one_anchor_do_not_print_the_same_line_twice(tmp_path: Path, capsys):
    """스페이스가 표에 실림 — 안 실으면 바이트 동일한 줄이 두 번 나가, 건수가 앵커 수인지
    스페이스 수인지 읽는 쪽이 못 가름.
    """
    repo = _repo(_item("fr-payment-001", "결제함", {}))
    boards = [_board([]), _board([], space="labs")]
    _, text, result = _run(tmp_path, capsys, repo, boards)
    assert result["counts"]["never_pushed"] == 2
    rows = [ln for ln in text.splitlines() if "fr-payment-001" in ln]
    assert len(rows) == 2
    assert rows[0] != rows[1]
    assert "dev3" in rows[0] and "labs" in rows[1]


def test_a_title_drift_row_names_the_space_and_item(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "카드로 결제함", {"dev3": "REQ-1"}))
    _, text, _ = _run(tmp_path, capsys, repo, [_board(_one("REQ-1", "결제함"))])
    row = [ln for ln in text.splitlines() if "fr-payment-001" in ln][0]
    assert "-> dev3/REQ-1" in row


def test_two_files_for_one_space_merge_instead_of_overwriting(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {"dev3": "REQ-2"}))
    boards = [_board(_one("REQ-1", "a")), _board(_one("REQ-2", "결제함"))]
    _, _, result = _run(tmp_path, capsys, repo, boards)
    assert result["counts"]["broken_mapping"] == 0
    assert [r["item"] for r in result["drift"]["board_only"]] == ["REQ-1"]


def test_drift_does_not_move_the_exit_code(tmp_path: Path, capsys):
    repo = _repo(_item("fr-payment-001", "결제함", {}))
    code, _, _ = _run(tmp_path, capsys, repo, [_board(_one("REQ-1", "x"))])
    assert code == 0


def test_the_table_names_every_kind_even_at_zero(tmp_path: Path, capsys):
    _, text, _ = _run(tmp_path, capsys, _repo(), [_board([])])
    for label in ("한 번도 안 올림", "끊긴 매핑", "보드에만 있음", "제목 다름", "중복 매핑"):
        assert label in text


def test_a_board_without_a_space_key_is_counted_not_dropped(tmp_path: Path, capsys):
    """버린 열거가 0건과 구별됨 — 안 그러면 미푸시가 몇이든 「어긋남 없음」으로 읽힘."""
    repo = _repo(_item("fr-payment-001", "결제함", {}))
    board = _board(_one("REQ-1", "결제함"))
    board.pop("space")
    _, text, result = _run(tmp_path, capsys, repo, [board])
    assert result["ignored"]["no_space"] == 1
    assert "버린 입력" in text


def test_a_board_item_without_an_id_is_counted(tmp_path: Path, capsys):
    board = _board([{"title": "결제함"}])
    _, text, result = _run(tmp_path, capsys, _repo(), [board])
    assert result["ignored"]["no_id"] == 1
    assert "버린 입력" in text


def test_a_clean_run_says_nothing_about_ignored_input(tmp_path: Path, capsys):
    _, text, result = _run(tmp_path, capsys, _repo(), [_board(_one("REQ-1", "결제함"))])
    assert result["ignored"] == {"no_space": 0, "no_id": 0}
    assert "버린 입력" not in text


def test_a_missing_board_warns_and_the_rest_still_runs(tmp_path: Path, capsys):
    """펼쳐지지 않은 glob 이 그대로 넘어오는 자리 — 트레이스백이 아니라 경고 한 줄."""
    repo_path = tmp_path / "repo.json"
    repo = _repo(_item("fr-payment-001", "결제함", {}))
    repo_path.write_text(json.dumps(repo, ensure_ascii=False), encoding="utf-8")
    board_path = tmp_path / "board0.json"
    board_path.write_text(json.dumps(_board([]), ensure_ascii=False), encoding="utf-8")
    code, text = run(
        [
            "--diff",
            "--repo",
            str(repo_path),
            "--board",
            str(tmp_path / "board-*.json"),
            str(board_path),
        ],
        capsys,
    )
    assert code == 0
    assert "board-*.json" in text
    assert "[한 번도 안 올림] 1건" in text


def test_no_readable_board_leaves_no_table(tmp_path: Path, capsys):
    repo_path = tmp_path / "repo.json"
    repo_path.write_text(json.dumps(_repo(), ensure_ascii=False), encoding="utf-8")
    code, text = run(
        ["--diff", "--repo", str(repo_path), "--board", str(tmp_path / "none.json")], capsys
    )
    assert code == 0
    assert "스페이스:" not in text


def test_a_missing_repo_json_warns_instead_of_raising(tmp_path: Path, capsys):
    board_path = tmp_path / "board0.json"
    board_path.write_text(json.dumps(_board([]), ensure_ascii=False), encoding="utf-8")
    code, text = run(
        ["--diff", "--repo", str(tmp_path / "repo.json"), "--board", str(board_path)], capsys
    )
    assert code == 0
    assert "repo.json" in text
    assert "스페이스:" not in text


def test_a_doubled_review_mark_is_not_a_title_difference():
    """표식이 둘 쌓인 거울상 입력 — 양쪽이 같은 값에 닿아야 함.

    repo 쪽 제목은 `scan` 의 `_title` 과 `diff` 의 `_norm` 으로 변환을 두 번 받고 보드 쪽은
    한 번 받음. 말미 하나만 떼면 그 횟수 차이가 그대로 글자 차이가 되어, 같은 문장이
    「제목 다름」으로 나가고 `--push` 가 사람이 보드에 쓴 글자를 지움.
    """
    doubled = "정기 결제를 지원함 (확인 필요) (확인 필요)"
    repo = {
        "root": "docs/srs",
        "items": [
            {
                "anchor": "fr-pay-001",
                "kind": "FR",
                "area": "pay",
                "file": "docs/srs/pay.md",
                "line": 3,
                "title": alm_docs._title(f'<a id="fr-pay-001"></a>**FR-PAY-001** {doubled}'),
                "alm": {"dev3": "REQ-1"},
            }
        ],
    }
    boards = [{"space": "dev3", "items": [{"id": "REQ-1", "title": doubled}]}]
    result = alm_docs.diff(repo, boards)
    assert result["counts"]["title_differs"] == 0, result["drift"]["title_differs"]


def test_stripping_the_review_mark_is_idempotent():
    """멱등이 계약 — 변환 횟수가 양쪽이 다르므로 횟수가 답을 바꾸면 안 됨."""
    once = alm_docs._strip_review_mark("결제를 지원함 (확인 필요) (확인 필요)")
    assert once == "결제를 지원함"
    assert alm_docs._strip_review_mark(once) == once
    # 문장 가운데의 같은 글자는 그 문장의 일부 — 어디서나 지우면 다른 두 문장이 같아 보임.
    assert alm_docs._strip_review_mark("(확인 필요) 를 지움") == "(확인 필요) 를 지움"
