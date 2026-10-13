"""증분 편집이 깨뜨리는 것 — 오늘은 이것 말고 아무도 읽지 않음.

파일 간 케이스가 분할이 새로 만든 것: C 는 README 에 살고 그것을 인용하는 FR 은 영역
파일에 살아, 같은 파일 안 fragment 검사만으로는 죽은 링크를 통과시킴.
"""

import re
from pathlib import Path

from tests.srs_check._helpers import REPO, run, write

_TEMPLATE_PATH = REPO / "skills/harness-authoring/templates/srs-area.template.md"
_FORMAT_COMMENT_RE = re.compile(r"<!-- 형식 —.*?-->", re.DOTALL)


def _index(body: str = "") -> str:
    return "# SRS\n" + body


def _template_format_comment() -> str:
    """템플릿 자신의 "형식 —" 예시, 디스크에서 매번 새로 읽음.

    옮겨 적지 않음: 사본은 추적해야 할 템플릿에서 조용히 drift 함 — 이 파일이 잡으려는
    버그가 정확히 그것.
    """
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    m = _FORMAT_COMMENT_RE.search(text)
    assert m, f"no '형식 —' comment found in {_TEMPLATE_PATH}"
    return m.group(0) + "\n"


def test_clean_tree_is_silent_success(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/README.md", _index('<a id="c-001"></a>C-001 Cards.\n'))
    write(
        tmp_path,
        "docs/srs/payment.md",
        '# Payment\n<a id="fr-payment-001"></a>**FR-PAYMENT-001** '
        "(← [C-001](README.md#c-001)) Pay.\n",
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0
    assert out == ""


def test_dead_cross_file_link(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/README.md", _index('<a id="c-001"></a>C-001 Cards.\n'))
    write(
        tmp_path,
        "docs/srs/payment.md",
        '# Payment\n<a id="fr-payment-001"></a>(← [C-009](README.md#c-009))\n',
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "README.md#c-009" in out
    assert "payment.md" in out


def test_dead_same_file_fragment(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/README.md", _index("[gone](#nfr-perf-004)\n"))
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "#nfr-perf-004" in out


def test_duplicate_anchor_in_one_file(tmp_path: Path, capsys):
    write(
        tmp_path,
        "docs/srs/payment.md",
        '# Payment\n<a id="fr-payment-001"></a>\n<a id="fr-payment-001"></a>\n',
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "fr-payment-001" in out


def test_duplicate_anchor_across_area_files(tmp_path: Path, capsys):
    """같은 번호를 두 브랜치가 발급해도 막지 않고 탐지만 함."""
    write(tmp_path, "docs/srs/payment.md", '# Payment\n<a id="fr-payment-001"></a>\n')
    write(tmp_path, "docs/srs/refund.md", '# Refund\n<a id="fr-payment-001"></a>\n')
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "fr-payment-001" in out


def test_prefix_mismatch_in_an_area_file(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/payment.md", '# Payment\n<a id="fr-refund-001"></a>\n')
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "fr-refund-001" in out
    assert "payment" in out


def test_index_anchors_take_no_prefix_check(tmp_path: Path, capsys):
    write(
        tmp_path,
        "docs/srs/README.md",
        _index('<a id="c-001"></a>\n<a id="nfr-perf-001"></a>\n<a id="role-001"></a>\n'),
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0
    assert out == ""


def test_external_and_absolute_links_are_out_of_scope(tmp_path: Path, capsys):
    write(
        tmp_path,
        "docs/srs/README.md",
        _index("[x](https://example.com#frag)\n[y](../sds/README.md#mod)\n"),
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0


def test_no_srs_dir_is_silent_success(tmp_path: Path, capsys):
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0
    assert out == ""


def test_titled_link_to_dead_anchor_is_caught(tmp_path: Path, capsys):
    write(
        tmp_path,
        "docs/srs/README.md",
        _index('[C-999](README.md#c-999 "customer requirement")\n'),
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "c-999" in out


def test_titled_link_to_live_anchor_is_not_flagged(tmp_path: Path, capsys):
    write(
        tmp_path,
        "docs/srs/README.md",
        _index('<a id="c-001"></a>C-001 Cards.\n[C-001](README.md#c-001 "customer requirement")\n'),
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0
    assert out == ""


def test_anchor_in_code_fence_is_not_a_definition(tmp_path: Path, capsys):
    """코드로 펜스된 예시 앵커는 그 아래 진짜 앵커와 충돌해서는 안 됨."""
    write(
        tmp_path,
        "docs/srs/payment.md",
        '# Payment\n```\n<a id="fr-payment-001"></a>\n```\n<a id="fr-payment-001"></a>\n',
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0
    assert out == ""


def test_template_format_comment_anchor_is_not_a_definition(tmp_path: Path, capsys):
    write(
        tmp_path,
        "docs/srs/payment.md",
        "# Payment\n"
        + _template_format_comment()
        + '<a id="fr-payment-001"></a>**FR-PAYMENT-001** Pay.\n',
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0
    assert out == ""


def test_template_format_comment_link_to_undefined_id_does_not_fail(tmp_path: Path, capsys):
    """주석 자신의 예시 — `[C-003](README.md#c-003)` — 는 템플릿을 따르는 문서가
    아직 정의하지 않았을 수 있는 id 를 인용함 — CI 를 실패시키면 안 됨."""
    write(tmp_path, "docs/srs/README.md", _index('<a id="c-001"></a>C-001 Cards.\n'))
    write(tmp_path, "docs/srs/payment.md", "# Payment\n" + _template_format_comment())
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 0
    assert out == ""


def test_real_dead_link_still_reported_beside_the_template_comment(tmp_path: Path, capsys):
    """주석 자신의 링크를 벗기는 일이 진짜 링크를 못 보게 가려서는 안 됨."""
    write(tmp_path, "docs/srs/README.md", _index('<a id="c-001"></a>C-001 Cards.\n'))
    write(
        tmp_path,
        "docs/srs/payment.md",
        "# Payment\n"
        + _template_format_comment()
        + '<a id="fr-payment-001"></a>(← [C-999](README.md#c-999))\n',
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "README.md#c-999" in out


def test_duplicate_survives_alongside_a_commented_example(tmp_path: Path, capsys):
    """주석/코드펜스 제외가 진짜 중복을 삼켜서는 안 됨."""
    write(
        tmp_path,
        "docs/srs/payment.md",
        "# Payment\n"
        '<!-- example: <a id="fr-payment-999"></a> -->\n'
        '<a id="fr-payment-001"></a>\n'
        '<a id="fr-payment-001"></a>\n',
    )
    code, out = run(["--root", str(tmp_path), "--verify"], capsys)
    assert code == 1
    assert "fr-payment-001" in out
