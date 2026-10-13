"""머지를 둘러싼 맥락을 전략 판정이 git 처럼 읽는가 — 명령줄 `-c` 의 mergeoptions·rebase,
`cd`·`-C` 가 정하는 트리, 저장소 git config 의 rebase.

판정은 fail-CLOSED 예외(Invariant 1 ③). target 이 다른 트리라 읽을 수 없으면 fail-open 이고,
같은 저장소의 하위 디렉터리는 다른 트리가 아님. git 동작에 기대는 행은 실제 git(2.47)으로 잰 것.
"""

import sys

import pytest

import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import _rg, _run_merge_check, _write_policy


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        # 명령줄 mergeoptions 는 target 으로의 머지 기본 옵션 — 명령줄 플래그가 이김
        ("git -c branch.dev.mergeoptions=--no-ff merge fix/x", "dev", True),
        ("git -c Branch.dev.MergeOptions=--no-ff merge fix/x", "dev", True),
        ("git -c branch.dev.mergeoptions=--no-ff merge --ff fix/x", "dev", False),
        ("git -c branch.main.mergeoptions=--no-ff merge fix/x", "dev", False),
        ("git -c 'branch.dev.mergeoptions=-q --no-ff' merge fix/x", "dev", True),
        ("git -c branch.dev.mergeoptions=--no-ff pull origin fix/x", "dev", True),
        ("git -c branch.main.mergeoptions=--squash merge stage", "main", True),
        # mergeoptions 는 merge.ff 를 이김
        ("git -c merge.ff=true -c branch.dev.mergeoptions=--no-ff merge fix/x", "dev", True),
        # `-C` 는 앞의 `cd` 기준
        ("cd /elsewhere && git -C . merge stage", "main", False),
        ("cd /elsewhere && git -C . pull origin stage", "main", False),
        # 명령줄 `branch.<target>.rebase` 는 `pull.rebase` 를 이기고, 플래그는 둘 다 이김
        (
            "git -c pull.rebase=true -c branch.dev.rebase=false pull --no-ff origin fix/x",
            "dev",
            True,
        ),
        ("git -c branch.dev.rebase=true pull --no-ff origin fix/x", "dev", False),
        ("git -c branch.dev.rebase=true pull --no-rebase --no-ff origin fix/x", "dev", True),
        # pull 에서 `pull.ff` 는 자식 머지에 넘기는 플래그라 mergeoptions 를 이김
        ("git -c pull.ff=false -c branch.dev.mergeoptions=--ff pull origin fix/x", "dev", True),
        ("git -c pull.ff=only -c branch.dev.mergeoptions=--no-ff pull origin fix/x", "dev", False),
        ("git -c merge.ff=false -c branch.dev.mergeoptions=--ff pull origin fix/x", "dev", False),
        # mergeoptions 는 `--` 에서 옵션 읽기를 멈춤
        ("git -c 'branch.stage.mergeoptions=-- --no-ff' merge dev", "stage", True),
        # 같은 저장소의 하위 디렉터리는 다른 트리가 아님; `cd` 는 전부 이어 읽음
        ("cd sub && git merge dev", "stage", True),
        ("git -C sub merge dev", "stage", True),
        ("cd sub && cd deeper && git -C ../.. merge dev", "stage", True),
    ],
)
def test_command_line_config_and_directory_spellings(
    monkeypatch, tmp_path, command, branch, blocked
):
    _write_policy(tmp_path)
    (tmp_path / "sub" / "deeper").mkdir(parents=True)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


def test_a_nested_repository_inside_root_is_elsewhere(monkeypatch, tmp_path):
    """root 안이어도 사이에 `.git` 이 서면(중첩 저장소·worktree) 다른 트리 — 그 머지의 target
    은 여기서 읽을 수 없음."""
    _write_policy(tmp_path)
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert _run_merge_check(monkeypatch, tmp_path, "git -C wt merge dev", "stage") == 0
    assert _run_merge_check(monkeypatch, tmp_path, "cd wt && git merge dev", "stage") == 0


@pytest.mark.parametrize(
    "key,command,branch,blocked",
    [
        # config 가 rebase 로 바꾸면 철자한 `--no-ff` 는 무시되고 fast-forward 함
        ("pull.rebase", "git pull --no-ff origin dev", "stage", True),
        ("branch.stage.rebase", "git pull --no-ff origin dev", "stage", True),
        # 명령줄이 rebase 를 끄면 config 는 끼어들지 않음
        ("pull.rebase", "git pull --no-rebase --no-ff origin dev", "stage", False),
        ("pull.rebase", "git -c pull.rebase=false pull --no-ff origin dev", "stage", False),
        # config 를 명령 안에서 바꿔도 덜 막지는 않음 — 철자한 머지 읽기가 남음
        (
            "pull.rebase",
            "git config pull.rebase false && git pull --no-ff origin fix/x",
            "dev",
            True,
        ),
    ],
)
def test_git_config_rebase_adds_a_reading(monkeypatch, tmp_path, key, command, branch, blocked):
    _write_policy(tmp_path)
    _rg(["init", "-q"], tmp_path)
    _rg(["config", key, "true"], tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


def test_cd_back_returns_to_where_it_was(monkeypatch, tmp_path):
    _write_policy(tmp_path)
    (tmp_path / "sub").mkdir()
    assert (
        _run_merge_check(monkeypatch, tmp_path, "cd sub && cd - && git merge dev", "stage")
        == fgc.BLOCK_EXIT_CODE
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash 드라이브 철자는 Windows 전용")
def test_a_git_bash_drive_path_is_this_repository(monkeypatch, tmp_path):
    _write_policy(tmp_path)
    (tmp_path / "sub").mkdir()
    posix = tmp_path.as_posix()
    bash_path = f"/{posix[0].lower()}{posix[2:]}"
    for command in (f"cd {bash_path} && git merge dev", f"cd {bash_path}/sub && git merge dev"):
        code = _run_merge_check(monkeypatch, tmp_path, command, "stage")
        assert code == fgc.BLOCK_EXIT_CODE, (command, code)


def test_a_deepening_cd_chain_stays_linear(monkeypatch, tmp_path):
    """`cd sub/d` 를 반복하면 경로가 머지마다 깊어짐 — 그 경로를 머지마다 파일시스템에 물으면
    2차였음(실측: 16KB 21초). 깊이 상한 뒤로는 이름을 댈 수 없는 디렉터리로 봄."""
    import time

    _write_policy(tmp_path)
    piece = "cd sub/d && git merge --squash feature/x"
    command = " && ".join([piece] * (16_000 // (len(piece) + 4)))
    fgc._cd_chain.cache_clear()
    started = time.perf_counter()
    _run_merge_check(monkeypatch, tmp_path, command, "dev")
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"{elapsed:.2f}s — 선형이면 1초 안쪽"


def test_git_config_is_read_once_per_hook(monkeypatch, tmp_path):
    """target 마다 config 를 따로 읽으면 spawn 이 target 수에 비례함(실측: 100KB 에서 1924회,
    309초). 한 번의 `--get-regexp` 로 읽음."""
    import subprocess

    _write_policy(tmp_path)
    _rg(["init", "-q"], tmp_path)
    _rg(["config", "pull.rebase", "true"], tmp_path)
    spawned = []
    real_run = subprocess.run

    def counting_run(args, *a, **kw):
        spawned.append(args)
        return real_run(args, *a, **kw)

    monkeypatch.setattr(fgc.subprocess, "run", counting_run)
    command = " && ".join(f"git switch b{i} && git pull --no-ff origin fix/x" for i in range(200))
    _run_merge_check(monkeypatch, tmp_path, command, "dev")
    assert len([a for a in spawned if a[:2] == ["git", "config"]]) == 1, spawned[:5]
