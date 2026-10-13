"""`--areas` — `/vdev` SRS 단계가 읽는 라우팅 입력.

docs/srs 부재 계약을 먼저 단언: 모든 하위 명령이 이를 상속하고, SRS 가 없는 저장소는
대응 못 할 경고 대신 무출력이어야 함.
"""

from pathlib import Path

from tests.srs_check._helpers import run, write


def test_no_srs_dir_is_silent_success(tmp_path: Path, capsys):
    code, out = run(["--root", str(tmp_path), "--areas"], capsys)
    assert code == 0
    assert out == ""


def test_empty_srs_dir_is_silent_success(tmp_path: Path, capsys):
    (tmp_path / "docs" / "srs").mkdir(parents=True)
    code, out = run(["--root", str(tmp_path), "--areas"], capsys)
    assert code == 0
    assert out == ""


def test_areas_lists_stem_and_title(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/README.md", "# SRS\n")
    write(tmp_path, "docs/srs/payment.md", "---\nwiki_id: srs.payment\n---\n# Payment\n")
    write(tmp_path, "docs/srs/user-auth.md", "# User Auth\n")
    code, out = run(["--root", str(tmp_path), "--areas"], capsys)
    assert code == 0
    assert out.splitlines() == ["payment\tPayment", "user-auth\tUser Auth"]


def test_readme_is_not_an_area(tmp_path: Path, capsys):
    write(tmp_path, "docs/srs/README.md", "# SRS\n")
    code, out = run(["--root", str(tmp_path), "--areas"], capsys)
    assert code == 0
    assert out == ""
