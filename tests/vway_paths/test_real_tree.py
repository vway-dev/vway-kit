"""`under_real_tree` — 링크 너머 쓰기를 가르는 술어 자신.

소비자가 둘(`vdev_init_setup` 의 이동, `alm_docs` 의 덧쓰기)이라 커버리지를 한쪽
분류 폴더에만 두면 그 폴더를 고치는 사람이 다른 소비자를 모른 채 술어를 좁힘. 재는
축 넷: root 자신이 링크 · 중간 조각이 링크 · `..` 의 조기 거절 · root 밑이 아님.
"""

from pathlib import Path

import pytest

from scripts._vway_paths import under_real_tree
from tests._proc import run_bounded


def _link(target: Path, link: Path) -> bool:
    """링크가 서면 True. 권한·파일시스템이 거절하면 False(그 호스트는 이 축이 없음)."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    done = run_bounded(["cmd", "/c", "mklink", "/J", str(link), str(target)])
    return done.returncode == 0 and link.exists()


def _linked(tmp_path: Path, at: str) -> tuple:
    """`<root>/<at>` 이 tmp_path/outside 를 가리키는 트리. 링크를 못 만들면 skip."""
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    if not _link(outside, root / at):
        pytest.skip("이 호스트에서 링크·정션을 만들 수 없음")
    return root, outside


def test_a_plain_path_under_the_root_passes(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    assert under_real_tree(root / "sub" / "a.md", root)


def test_the_root_itself_being_a_link_fails(tmp_path):
    """root 를 걸음에서 빼면 root 자신이 링크인 호스트가 통째로 구멍이 됨."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    if not _link(outside, root):
        pytest.skip("이 호스트에서 링크·정션을 만들 수 없음")
    assert not under_real_tree(root / "a.md", root)


def test_a_link_in_the_middle_fails(tmp_path):
    root, _ = _linked(tmp_path, "sub/ln")
    assert not under_real_tree(root / "sub" / "ln" / "a.md", root)


def test_a_link_as_the_last_segment_fails(tmp_path):
    root, _ = _linked(tmp_path, "ln")
    assert not under_real_tree(root / "ln", root)


def test_a_dotdot_segment_fails_before_any_walk(tmp_path):
    """걸음은 사전식이라 `..` 를 되짚지 못함 — 조각으로 먼저 걸러야 함."""
    root = tmp_path / "root"
    root.mkdir()
    assert not under_real_tree(root / ".." / "outside.md", root)


def test_a_path_outside_the_root_fails(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert not under_real_tree(tmp_path / "outside.md", root)
