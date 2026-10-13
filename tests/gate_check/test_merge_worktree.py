"""셸이 게이팅되는 저장소의 다른 worktree 에 선 세션에서 도는 머지 — 그 target 을 어느 트리에서
읽는가."""

import io
import json
import sys
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import _init_repo, _rg, _write_policy, requires_git


def _host(tmp_path: Path, main_branch: str, wt_branch: str) -> tuple[Path, Path]:
    main = tmp_path / "main"
    _init_repo(main)
    _write_policy(main)
    for b in {"dev", "stage", "feature/a", main_branch, wt_branch} - {"main"}:
        _rg(["branch", b], main)
    _rg(["switch", main_branch], main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", str(wt), wt_branch], main)
    return main, wt


def _check(monkeypatch, main: Path, cwd: Path, command: str):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(main))
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(fgc, "_is_rebased", lambda root, source, target: True)
    payload = {"cwd": str(cwd), "tool_input": {"command": command}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        fgc.merge_check_output()
    return exc.value.code


@requires_git
def test_a_merge_lands_on_the_worktree_the_shell_is_in(tmp_path, monkeypatch, capsys):
    """root 에서 읽으면 target 이 규칙 없는 feature/a 라, worktree 의 dev 로 가는 squash 없는
    머지가 통과했음."""
    main, wt = _host(tmp_path, "feature/a", "dev")
    assert _check(monkeypatch, main, wt, "git merge feature/x") == fgc.BLOCK_EXIT_CODE
    assert "--squash" in capsys.readouterr().out


@requires_git
def test_root_on_dev_does_not_judge_a_worktree_on_a_feature_branch(tmp_path, monkeypatch):
    """반대 방향: worktree 안의 feature → feature 머지가 root 의 dev 로 가는 머지로 판정됐음."""
    main, wt = _host(tmp_path, "dev", "feature/a")
    assert _check(monkeypatch, main, wt, "git merge feature/x") == 0


@requires_git
def test_a_shell_in_root_still_reads_root(tmp_path, monkeypatch):
    main, _wt = _host(tmp_path, "dev", "feature/a")
    assert _check(monkeypatch, main, main, "git merge feature/x") == fgc.BLOCK_EXIT_CODE


@requires_git
def test_a_shell_in_another_repo_reads_root(tmp_path, monkeypatch):
    """같은 저장소라는 증명이 없으므로 target 은 전처럼 root 것."""
    main, _wt = _host(tmp_path, "dev", "feature/a")
    other = tmp_path / "other"
    _init_repo(other)
    assert _check(monkeypatch, main, other, "git merge feature/x") == fgc.BLOCK_EXIT_CODE


@requires_git
@pytest.mark.parametrize(
    "command",
    [
        "git -C {main} merge stage",
        "git fetch -q; cd {main} && git merge stage",
        "pushd {main} && git merge stage",
        "(cd {main} && git merge stage)",
        "env -C {main} git merge stage",
        "git --git-dir={main}/.git merge stage",
        "GIT_DIR={main}/.git git merge stage",
    ],
)
def test_a_merge_the_command_moves_to_root_is_judged_as_roots(tmp_path, monkeypatch, command):
    """셸은 worktree 에 섰지만 이 머지들은 전부 stage 를 root 의 main 으로 들임."""
    main, wt = _host(tmp_path, "main", "feature/a")
    spelled = command.format(main=main.as_posix())
    assert _check(monkeypatch, main, wt, spelled) == fgc.BLOCK_EXIT_CODE


@requires_git
def test_a_commits_directory_does_not_move_the_merge(tmp_path, monkeypatch):
    """커밋의 `-C` 는 그 뒤 머지가 어디 떨어지는지 말하지 않음."""
    main, wt = _host(tmp_path, "main", "feature/a")
    command = f"git -C {wt.as_posix()} commit -m x && git merge stage"
    assert _check(monkeypatch, main, main, command) == fgc.BLOCK_EXIT_CODE


@requires_git
def test_dash_c_dot_is_the_shells_tree(tmp_path, monkeypatch):
    """`-C .` 는 셸이 선 디렉터리, 곧 worktree 를 지목함."""
    main, wt = _host(tmp_path, "dev", "feature/a")
    assert _check(monkeypatch, main, wt, "git -C . merge feature/x") == 0
