"""`--classify` — 이 명령이 무엇인가에 대한 **유일한** 권위.

러너의 stdin 필터는 후보를 띄울 뿐이고 판정은 여기서만 남. 인터프리터의 `-c` 인자에
실린 커밋도 명령으로 읽고, 판정이 아예 없으면 러너가 스스로 게이팅함.
"""

import json
import os
import sys
from pathlib import Path

import scripts.vdev_gate_check as fgc
from tests._proc import run_bounded
from tests.gate_check._helpers import (
    _REPO_BASH,
    _classify,
    _init_repo,
    _merge_repo,
    _rg,
    _run_runner,
    requires_bash_git,
    requires_git,
)


def test_classify_names_the_invocation_and_says_nothing_else():
    assert _classify("git commit -m x").splitlines() == ["ok=1", "commit=1"]
    assert _classify("git merge --no-ff dev").splitlines() == ["ok=1", "merge=1"]
    assert _classify("git merge --squash feature/x && git commit -m x").splitlines() == [
        "ok=1",
        "commit=1",
        "merge=1",
    ]
    # 낱말만 말하는 명령은 호출이 아님 — 러너의 거친 필터가 넘긴 것을 여기서 떨굼.
    # `ok=1` 은 그래도 나옴: 읽었고, 호출이 아니라는 것이 답임.
    assert _classify('git log --oneline && echo "now commit"').splitlines() == ["ok=1"]
    assert _classify("grep 'git merge' README.md").splitlines() == ["ok=1"]
    # 빈 **문자열**은 읽을 수 있는 명령이고, 아무것도 실행하지 않음 — 읽었다고 답함.
    # 명령 필드가 아예 없는 페이로드는 다른 경우임(아래 전용 테스트).
    assert _classify("").splitlines() == ["ok=1"]


@requires_git
def test_classify_reports_the_worktree_only_for_a_commit(tmp_path: Path):
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    out = _classify(f"git -C {wt.as_posix()} commit -m x", cwd=str(main), project=main)
    assert "commit=1" in out
    assert any(line.startswith("worktree=") for line in out.splitlines()), out
    # merge 경로는 재지정하지 않는다(Invariant 7 — 커밋 경로 전용). 훅 **cwd** 가 worktree 인
    # 경우로 잼: `-C <wt> merge` 는 커밋 호출이 없어 어차피 아무 디렉터리도 안 내므로,
    # 그걸로는 이 가드를 지워도 초록이다(실측).
    out = _classify("git merge dev", cwd=str(wt), project=main)
    assert "merge=1" in out
    assert "worktree=" not in out, out


@requires_bash_git
def test_runner_gates_a_line_continued_commit(tmp_path: Path):
    # `\`+개행은 두 줄을 한 명령으로 이음. 거기서 낱말이 끊기면 러너가 "커밋 아님"으로
    # 읽고 **의존성 검사·티어 게이트·모듈 검사 전부보다 앞에서** exit 0 함 — 게이트가
    # 통째로 꺼짐. 두 레이어를 가로질러 실제 exit 코드로 측정.
    main = tmp_path / "main"
    _init_repo(main)
    (main / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "-A"], main)
    r = _run_runner(main, "git \\\n  commit -m x")  # tier 마커 없음 → 미분류 차단
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_merge_gate_reads_a_multiline_merge_message(tmp_path: Path):
    # 이 repo 의 승격 머지는 다중 줄 `-m` 을 실음. 메시지 안의 개행이 피연산자 영역을
    # 끊으면 merge 판정이 FAIL-OPEN 해, `--no-ff` 를 **요구**하는 staging → production 행이
    # 아무 플래그 없는 머지에 적용되지 않음.
    main = _merge_repo(
        tmp_path, branch=None, config="branches:\n  staging: stage\n  production: main\n"
    )
    r = _run_runner(main, 'git merge origin/stage -m "Merge stage: x\n\n- 한 줄"')
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)
    assert "--no-ff" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_is_not_satisfied_by_a_comment(tmp_path: Path):
    # 주석에 적힌 `--squash` 가 그 플래그를 요구하는 행을 만족시키면, 정책은 텍스트로
    # 우회됨. 실제 exit 코드로 측정 — 차단(exit 2)이 유지되어야 함.
    main = _merge_repo(tmp_path, branch="dev", config="branches:\n  integration: dev\n")
    r = _run_runner(main, "git merge feature/x  # --squash 를 붙였어야 한다")
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)
    assert "--squash" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_exits_quietly_for_a_command_that_only_says_the_word(tmp_path: Path):
    # 거친 필터는 넓지만, 낱말만 말하는 명령은 --classify 가 떨굼. 더러운 트리에 tier
    # 마커가 없어도 차단되면 안 됨 — 읽기 전용 명령에 대한 fail-CLOSED 오작동임.
    main = tmp_path / "main"
    _init_repo(main)
    (main / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "-A"], main)
    for command in ("grep 'git commit' README.md", 'echo "git merge --no-ff stage"'):
        r = _run_runner(main, command)
        assert r.returncode == 0, (command, r.returncode, r.stdout, r.stderr)


def test_classify_says_it_read_the_command():
    # `ok=1` 이 없으면 러너는 판정을 못 받은 것으로 보고 스스로 게이팅함. 커밋이 아닌
    # 명령에도 나와야 함 — 그게 "읽었고 호출이 아니다"라는 답임.
    assert _classify("git commit -m x").splitlines() == ["ok=1", "commit=1"]
    assert _classify("echo hello").splitlines() == ["ok=1"]


def test_a_command_the_scanner_cannot_finish_falls_to_the_backstop():
    """치환 안을 명령으로 스캔하는 대가: 중첩이 깊으면 파이썬 재귀 한계에 닿음.

    방향이 계약임. `classify_output` 은 어떤 예외에도 조용히 끝나므로 `ok=1` 이 안 나오고,
    러너는 그것을 "판정 없음"으로 읽어 스스로 게이팅함(실측: 러너 exit 2). 얕은 중첩은
    평소대로 답함 — 한계는 실제 명령이 닿는 곳이 아님.
    """
    shallow = "$(" * 400 + "git commit -m x" + ")" * 400
    assert _classify(shallow).splitlines() == ["ok=1", "commit=1"]
    assert _classify("$(" * 4000 + "git commit -m x" + ")" * 4000) == ""


def test_classify_stays_silent_when_the_payload_carries_no_command():
    # 여기서 `ok=1` 을 내면 "읽었고 커밋이 아니다"가 되고 러너는 통과로 받음 — 페이로드가
    # 도구가 보내는 모양이 아닐 때 남는 유일한 뒷받침까지 버리는 셈임.
    repo = Path(__file__).resolve().parent.parent.parent
    for payload in ('{"tool_input": "git commit -m x"}', "{}", '{"tool_input": {}}'):
        r = run_bounded(
            [sys.executable, str(repo / "scripts" / "vdev_gate_check.py"), "--classify"],
            input=payload,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            text=True,
            encoding="utf-8",
        )
        assert r.stdout.strip() == "", (payload, r.stdout)


def test_classify_reads_a_commit_an_interpreter_is_handed():
    # 인용된 텍스트는 무언가 그것을 **실행하기 전까지만** 데이터임.
    assert "commit=1" in _classify("bash -c 'git commit -m x'")
    assert "commit=1" in _classify("printf 'git commit -m x' | bash")
    assert "merge=1" in _classify("bash <<< 'git merge --no-ff dev'")
    # 그물은 인터프리터로 시작하지 않는 명령을 넓히지 않음.
    assert _classify("grep -rn 'git commit' scripts/").splitlines() == ["ok=1"]


@requires_bash_git
def test_runner_gates_a_commit_an_interpreter_runs(tmp_path: Path):
    # 이 형태를 데이터로 읽으면 진짜 커밋이 게이트를 exit 0 으로 지나감.
    main = tmp_path / "main"
    _init_repo(main)
    (main / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "-A"], main)
    for command in ("bash -c 'git commit -m x'", "printf 'git commit -m x' | bash"):
        r = _run_runner(main, command)  # tier 마커 없음 → 미분류 차단
        assert r.returncode == fgc.BLOCK_EXIT_CODE, (command, r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_the_runner_gates_when_classify_could_not_answer(tmp_path: Path):
    # 페이로드가 도구가 보내는 모양이 아니면 --classify 는 침묵함. 그때 러너가 exit 0
    # 하면 raw stdin 뒷받침까지 사라짐 — 판정이 없을 때는 게이팅하는 쪽임.
    repo = Path(__file__).resolve().parent.parent.parent
    main = tmp_path / "main"
    _init_repo(main)
    (main / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "-A"], main)
    hook = json.dumps({"cwd": str(main), "tool_input": "git commit -m x"})  # dict 가 아님
    r = run_bounded(
        [_REPO_BASH, f"{repo.as_posix()}/scripts/precommit-runner.sh"],
        input=hook,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(main),
            "CLAUDE_PLUGIN_ROOT": repo.as_posix(),
            "VWAY_PRECOMMIT_DRYRUN": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)
