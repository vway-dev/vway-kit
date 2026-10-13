"""작업 브랜치에 속한 시간·이 worktree 에 속한 cwd."""

import os

import pytest

from scripts.worklog import allowed_periods, parse_moves, read_moves, worktree_filter
from tests._proc import run_bounded
from tests.worklog._helpers import m

LOG = (
    "HEAD@{2026-01-07T05:30:00+00:00}\tcheckout: moving from feature/x to dev\n"
    "HEAD@{2026-01-07T05:20:00+00:00}\tcommit: 메시지\n"
    "HEAD@{2026-01-07T05:15:00+00:00}\tcheckout: moving from other to feature/x\n"
    "HEAD@{2026-01-07T05:12:00+00:00}\trebase (start): checkout origin/dev\n"
    "HEAD@{2026-01-07T05:10:00+00:00}\tcheckout: moving from feature/x to other\n"
    "HEAD@{2026-01-07T05:05:00+00:00}\tcheckout: moving from dev to feature/x\n"
)


def test_parse_moves_reads_only_checkouts_in_time_order():
    assert parse_moves(LOG) == [
        (m(5), "dev", "feature/x"),
        (m(10), "feature/x", "other"),
        (m(15), "other", "feature/x"),
        (m(30), "feature/x", "dev"),
    ]


def test_allowed_keeps_lead_work_branch_and_integration_tail():
    periods = allowed_periods(parse_moves(LOG), "feature/x", "dev", m(0), m(60))
    assert periods == [(m(0), m(10)), (m(15), m(60))]


def test_other_branch_after_leaving_is_not_counted():
    log = LOG.replace("feature/x to dev", "feature/x to hotfix/y")
    periods = allowed_periods(parse_moves(log), "feature/x", "dev", m(0), m(60))
    assert periods == [(m(0), m(10)), (m(15), m(30))]


def test_no_moves_means_one_branch_all_along():
    assert allowed_periods([], "feature/x", "dev", m(0), m(60)) == [(m(0), m(60))]


def test_inside_excludes_nested_worktree(tmp_path):
    root = tmp_path / "repo"
    nested = root / ".claude" / "worktrees" / "w1"
    inside = worktree_filter(root, [str(nested)])
    assert inside(str(root))
    assert inside(str(root / "src"))
    assert not inside(str(nested / "src"))
    assert not inside(str(tmp_path / "repo-v2"))
    assert not inside(None)


@pytest.mark.skipif(os.name != "nt", reason="Windows 경로 규칙")
def test_inside_ignores_case_and_separator_on_windows(tmp_path):
    inside = worktree_filter(tmp_path, [])
    assert inside(str(tmp_path).lower().replace("\\", "/") + "/src")


def test_read_moves_outside_a_repo_is_none(tmp_path):
    assert read_moves(tmp_path) is None


def test_read_moves_from_a_real_repo(tmp_path):
    env = dict(
        os.environ,
        GIT_COMMITTER_DATE="2026-01-07T05:05:00+00:00",
        GIT_AUTHOR_DATE="2026-01-07T05:05:00+00:00",
    )
    for args in (
        ["init", "-q", "-b", "dev"],
        ["commit", "-q", "--allow-empty", "-m", "a"],
        ["switch", "-q", "-c", "feature/x"],
    ):
        run_bounded(
            ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            env=env,
            check=True,
        )
    assert read_moves(tmp_path) == [(m(5), "dev", "feature/x")]
