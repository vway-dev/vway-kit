"""명령이 게이팅되는 저장소가 아닌 다른 저장소에서 돌리는 커밋 — 이 저장소의 커밋으로 읽지 않는
경우와, 증명이 안 돼 게이팅된 채 남는 경우."""

import io
import json
import os
import sys
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import (
    _init_repo,
    _rg,
    _run_runner,
    _write_policy,
    requires_bash_git,
    requires_git,
)


def _classify(monkeypatch, capsys, root: Path, command: str, cwd: Path | None = None):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.chdir(root)
    payload = {"cwd": str(cwd or root), "tool_input": {"command": command}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    fgc.classify_output()
    return capsys.readouterr().out.split()


@pytest.fixture
def repos(tmp_path):
    main, other = tmp_path / "main", tmp_path / "other"
    _init_repo(main)
    _init_repo(other)
    _rg(["branch", "dev"], main)
    _rg(["worktree", "add", str(tmp_path / "wt"), "dev"], main)
    return main, other, tmp_path / "wt"


_CD_ON_WINDOWS = pytest.mark.skipif(os.name == "nt", reason="Windows 의 cd 는 게이팅된 채 남음")


@requires_git
@pytest.mark.parametrize(
    "command",
    [
        "git -C {other} commit -m x",
        pytest.param("cd {other} && git commit -m x", marks=_CD_ON_WINDOWS),
    ],
)
def test_a_commit_in_another_repo_is_not_ours(monkeypatch, capsys, repos, command):
    main, other, _wt = repos
    out = _classify(monkeypatch, capsys, main, command.format(other=other.as_posix()))
    assert "ok=1" in out and "commit=1" not in out


@requires_git
@pytest.mark.skipif(os.name != "nt", reason="Windows Git Bash 의 cd 만")
def test_a_cd_on_windows_stays_gated(monkeypatch, capsys, repos):
    """Git Bash 의 cd 는 경로를 MSYS 마운트 표로 옮기는데 Python 은 그 표를 안 읽음."""
    main, other, _wt = repos
    command = f"cd {other.as_posix()} && git commit -m x"
    assert "commit=1" in _classify(monkeypatch, capsys, main, command)


@requires_git
@pytest.mark.parametrize(
    "command",
    [
        "git -C {wt} commit -m x",  # 게이팅되는 저장소의 worktree
        "git -C {missing} commit -m x",  # 읽을 수 없는 트리
        "git -C {other} commit -m x && git commit -m y",  # 커밋 하나는 여기서 돎
        "cd {other} && git commit -m x; cd {main} && git commit -m y",  # main 으로 되돌아옴
        "git commit -m x",
        # git 은 -C 를 쌓고, --git-dir·GIT_DIR 는 커밋을 main 으로 되돌림
        "git -C {other} -C {main} commit -m x",
        "git -C {other} --git-dir={main}/.git commit -m x",
        "git --git-dir={main}/.git -C {other} commit -m x",
        "GIT_DIR={main}/.git git -C {other} commit -m x",
        "export GIT_DIR={main}/.git; git -C {other} commit -m x",
        "cd {other} && GIT_DIR={main}/.git git commit -m x",
        "cd {other} && git --git-dir={main}/.git --work-tree={main} commit -m x",
        'git -C {other} commit -m "$(git -C {main} commit -m y)"',
        "git -C {other} commit -m x --git-dir={main}/.git",
        "git -C {other} commit -m x\ngit commit -am y",  # bash 는 개행에서 명령을 가름
        "cd {other} && git commit -m x\ngit commit -am y",
        "git -C {other} commit\ngit commit -am y",
    ],
)
def test_a_commit_not_proven_elsewhere_stays_gated(monkeypatch, capsys, repos, command):
    main, other, wt = repos
    spelled = command.format(
        other=other.as_posix(),
        wt=wt.as_posix(),
        missing=(main.parent / "none").as_posix(),
        main=main.as_posix(),
    )
    assert "commit=1" in _classify(monkeypatch, capsys, main, spelled)


@requires_git
@pytest.mark.parametrize("name", ["~+", "~-", "~", "~root", "[o]", "{o,p}", "-", "--", "-P"])
@pytest.mark.parametrize("command", ["git -C {d} commit -am x", "cd {d} && git commit -am x"])
def test_a_directory_bash_expands_stays_gated(monkeypatch, capsys, repos, name, command):
    """`~+` 는 bash 에겐 $PWD, Python 에겐 글자 그대로의 하위 저장소. `[o]` 는 평범한 `o` 로
    glob 됨. `cd -` 는 $OLDPWD, `cd --`·`cd -P` 단독은 $HOME."""
    main, _other, _wt = repos
    _init_repo(main / name)
    (main / "o").mkdir()
    assert "commit=1" in _classify(monkeypatch, capsys, main, command.format(d=name))


@requires_git
def test_a_cd_through_dotdot_stays_gated(monkeypatch, capsys, repos):
    """bash 는 `link/..` 를 $PWD 로 접고 git 은 링크를 따라감 — `..` 는 아무것도 증명 못 함."""
    main, _other, _wt = repos
    assert "commit=1" in _classify(monkeypatch, capsys, main, "cd ../other && git commit -m x")


@requires_git
def test_git_C_through_dotdot_is_read_as_git_reads_it(monkeypatch, capsys, repos):
    """git 은 프로브처럼 물리적으로 디렉터리를 바꾸므로 `-C ../other` 는 면제 유지."""
    main, _other, _wt = repos
    assert "commit=1" not in _classify(monkeypatch, capsys, main, "git -C ../other commit -m x")


@requires_git
@pytest.mark.skipif(os.name != "nt", reason="Windows 에서만 Git Bash 가 선두 / 를 자기 루트로 옮김")
@pytest.mark.parametrize("command", ["git -C {d} commit -m x", "cd {d} && git commit -m x"])
def test_a_rooted_path_on_windows_stays_gated(monkeypatch, capsys, repos, command):
    """Python 은 `/x` 를 cwd 의 드라이브로, Git Bash 는 설치 루트로 읽음 — 한 디렉터리가 아님."""
    main, other, _wt = repos
    rooted = other.as_posix()[len(other.drive) :]
    assert "commit=1" in _classify(monkeypatch, capsys, main, command.format(d=rooted))


@requires_git
@pytest.mark.skipif(os.name != "nt", reason="드라이브 상대 경로는 Windows 에만 있음")
def test_a_drive_relative_cd_on_windows_stays_gated(monkeypatch, capsys, repos):
    """Git Bash 는 `cd C:x` 를 드라이브 루트에서, Python 은 cwd 에서 읽음."""
    main, _other, _wt = repos
    command = f"cd {main.drive}other && git commit -m x"
    assert "commit=1" in _classify(monkeypatch, capsys, main, command, cwd=main.parent)


@requires_git
def test_a_relative_directory_is_read_from_the_shells_cwd(monkeypatch, capsys, repos):
    """셸은 부모에 섰고 거기서 `other` 는 다른 저장소 — main 에서 읽으면 아무것도 아님."""
    main, _other, _wt = repos
    out = _classify(monkeypatch, capsys, main, "git -C other commit -m x", cwd=main.parent)
    assert "commit=1" not in out


@requires_bash_git
def test_the_runner_leaves_another_repos_commit_alone(repos):
    """main 에는 tier 마커가 없으므로, main 의 커밋으로 판정하면 미분류로 막힘."""
    main, other, _wt = repos
    _write_policy(main)
    assert _run_runner(main, "git commit -m x").returncode == 2  # main 자신의 커밋은 막힘
    (other / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], other)
    r = _run_runner(main, f"git -C {other.as_posix()} commit -m x")
    assert r.returncode == 0, r.stderr
