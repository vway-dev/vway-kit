"""쓰기 두 자리가 `--root` 밖으로 못 나가는가.

재는 것은 거절 자체가 아니라 **원본이 그대로인가** — 계획의 `file` 은 보드 텍스트를 읽은
모델이 저작하므로 원격 비신뢰 입력이고, `..` 하나가 저장소 밖 기존 파일에 한 줄을 얹음.
`is_file()` 가드는 새 파일 생성만 막고 기존 파일 덧쓰기는 막지 않으므로 봉쇄가 아니라는
것도 여기서 붙잡음.
"""

import json
from pathlib import Path

import pytest

from tests._proc import run_bounded
from tests.alm_docs._helpers import run, write

OUTSIDE = "건드리면 안 되는 파일\n"
DOC = '<a id="fr-payment-001"></a>**FR-PAYMENT-001** 결제함.\n'


def _tree(tmp_path: Path) -> tuple:
    """`--root` 와, 그 밖에 이미 있는 파일 하나."""
    root = tmp_path / "repo"
    (root / "docs/srs").mkdir(parents=True)
    write(root, "docs/srs/payment.md", DOC)
    outside = tmp_path / "outside.md"
    outside.write_text(OUTSIDE, encoding="utf-8")
    return root, outside


def _plan(root: Path, data: dict) -> str:
    p = root / "plan.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _escapes(root: Path) -> list:
    """거절되어야 하는 `file` 값 — 상대 탈출·절대·드라이브·역슬래시."""
    return ["../outside.md", str(root.parent / "outside.md"), "C:/outside.md", r"..\outside.md"]


def test_apply_pull_leaves_a_file_outside_the_root_alone(tmp_path, capsys):
    root, outside = _tree(tmp_path)
    for rel in _escapes(root):
        writes = [{"file": rel, "anchor": "fr-x-001", "id": "FR-X-001", "title": "밖"}]
        plan = _plan(root, {"writes": writes})
        code, out = run(["--root", str(root), "--apply-pull", "--plan", plan], capsys)
        assert outside.read_text(encoding="utf-8") == OUTSIDE, rel
        assert repr(rel) in out, rel
        assert code == 0, rel


def test_record_leaves_a_file_outside_the_root_alone(tmp_path, capsys):
    root, outside = _tree(tmp_path)
    outside.write_text(DOC, encoding="utf-8")
    for rel in _escapes(root):
        records = [{"file": rel, "anchor": "fr-payment-001", "space": "dev3", "item": "REQ-1"}]
        mapping = _plan(root, {"records": records})
        code, out = run(["--root", str(root), "--record", "--map", mapping], capsys)
        assert outside.read_text(encoding="utf-8") == DOC, rel
        assert repr(rel) in out, rel
        assert code == 0, rel


def test_a_rejected_path_is_named_rather_than_dropped(tmp_path, capsys):
    """조용한 0건은 성공으로 읽힘 — 거절은 이름을 대야 함."""
    root, _ = _tree(tmp_path)
    writes = [{"file": "../outside.md", "anchor": "fr-x-001", "id": "FR-X-001", "title": "밖"}]
    plan = _plan(root, {"writes": writes})
    _, out = run(["--root", str(root), "--apply-pull", "--plan", plan], capsys)
    assert "[!]" in out
    assert "루트 밖" in out


def _link(target: Path, link: Path) -> bool:
    """정션이 서면 True. 권한·파일시스템이 거절하면 False(그 호스트는 이 축이 없음)."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    done = run_bounded(["cmd", "/c", "mklink", "/J", str(link), str(target)])
    return done.returncode == 0 and link.exists()


def test_a_link_inside_the_root_does_not_carry_a_write_outside(tmp_path, capsys):
    """`..` 가 없어도 링크 너머는 남의 디렉터리 — 렉시컬 판정만으로는 못 막음."""
    root, _ = _tree(tmp_path)
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "target.md").write_text(OUTSIDE, encoding="utf-8")
    if not _link(secret, root / "docs/srs/link"):
        pytest.skip("이 호스트에서 링크·정션을 만들 수 없음")
    writes = [
        {"file": "docs/srs/link/target.md", "anchor": "fr-x-001", "id": "FR-X-001", "title": "밖"}
    ]
    plan = _plan(root, {"writes": writes})
    code, out = run(["--root", str(root), "--apply-pull", "--plan", plan], capsys)
    assert (secret / "target.md").read_text(encoding="utf-8") == OUTSIDE
    assert "링크 너머라" in out  # 사유가 갈려야 함 — 링크는 루트 안을 가리킬 수도 있음
    assert code == 0


def test_a_path_inside_the_root_still_writes(tmp_path, capsys):
    """봉쇄가 성한 쓰기까지 막으면 그 단계가 통째로 죽음."""
    root, _ = _tree(tmp_path)
    rel = "docs/srs/payment.md"
    writes = [{"file": rel, "anchor": "fr-x-001", "id": "FR-X-001", "title": "안"}]
    plan = _plan(root, {"writes": writes})
    code, out = run(["--root", str(root), "--apply-pull", "--plan", plan], capsys)
    assert code == 0
    assert "[+]" in out
    assert 'id="fr-x-001"' in (root / "docs/srs/payment.md").read_text(encoding="utf-8")
