"""셸 러너 e2e — 커밋 경로를 실제 bash 로 구동.

러너의 stdin 사전 필터는 **띄울지만** 정함. 그래서 진짜 문법보다 좁아질 수 없고,
길이 상한을 넘는 입력은 필터를 건너뛰고 그냥 띄움. 워크트리 재지정도 여기서 측정.
"""

import os
import time
from pathlib import Path

import pytest

import scripts._vway_paths as vp
import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import (
    _classify_worktree_module,
    _init_repo,
    _rg,
    _run_runner,
    requires_bash_git,
    requires_git,
)


@requires_git
def test_is_rebased_real_git(tmp_path: Path):
    # 두 호출 지점이 모두 monkeypatch 로 스텁하므로 실호출을 직접 고정함(docstring 신뢰 근거).
    repo = tmp_path / "r"
    _init_repo(repo)  # main, README 커밋 1개
    _rg(["checkout", "-b", "feature/x"], repo)
    (repo / "f.txt").write_text("y", encoding="utf-8")
    _rg(["add", "-A"], repo)
    _rg(["commit", "-m", "feat"], repo)
    # feature/x 는 main 위에 있음 → main 이 feature/x 의 조상 → rebase 됨
    assert fgc._is_rebased(repo, "feature/x", "main") is True
    # main 은 feature/x 위에 있지 않음 → rebase 안 됨
    assert fgc._is_rebased(repo, "main", "feature/x") is False
    # 없는 ref: git 은 예외가 아니라 non-zero(128) → False(경고가 뜸, docstring 참조)
    assert fgc._is_rebased(repo, "nosuchref", "alsonosuch") is False


@requires_bash_git
def test_runner_gates_worktree_commit_via_git_dash_c(tmp_path: Path):
    # e2e: `git -C <wt> commit` 은 (1) `git` 과 `commit` 사이의 `-C <dir>` 에도 불구하고 커밋
    # self-filter 를 통과해야 하고, 그 다음 (2) ROOT=W 로 재지정되어 모듈 사전검사가 worktree 의
    # staged 파일을 읽어야 함. 둘 중 하나만 깨져도 W 의 `echo LINT_RAN` 이 나오지 않음(DRYRUN).
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    r = _run_runner(main, f"git -C {wt} commit -m x")
    assert "echo LINT_RAN" in (r.stdout + r.stderr)  # 게이트가 W 를 검사함


@requires_bash_git
def test_runner_ignores_a_worktree_the_commit_message_only_talks_about(tmp_path: Path):
    # commit 스킬이 출하하는 모양은 메시지를 만들어 **파이프**하는 것이라, 본문 전체가 진짜
    # git 호출보다 앞에 옴. 이 repo 는 Invariant 7 때문에 커밋 본문에 `git -C <경로>
    # commit` 을 실제로 적음 — 그걸 실행 디렉터리로 읽으면 ROOT 가 커밋이 돌지 않는
    # 트리로 옮겨감. decoy 는 같은 repo 의 **진짜** worktree 여야 이 테스트가 묾:
    # 아무 디렉터리나 쓰면 same-repo 판정에서 기각돼 버그가 있어도 초록.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    decoy = tmp_path / "decoy"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _rg(["worktree", "add", "-b", "feature/decoy", str(decoy)], main)
    _classify_worktree_module(wt)
    r = _run_runner(
        main,
        f'printf %s "see git -C {decoy.as_posix()} commit" | git -C {wt.as_posix()} commit -F -',
    )
    assert "echo LINT_RAN" in (r.stdout + r.stderr), (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_still_gates_when_one_command_holds_two_commits(tmp_path: Path):
    # 실행 디렉터리를 "커밋 호출이 정확히 하나일 때만" 읽으면 `git -C <wt> commit … &&
    # git -C <wt> commit --amend` 같은 평범한 체인에서 재지정을 잃음. 그러면 ROOT 가 main 으로
    # 떨어져 worktree 에 있는 티어 마커·모듈 설정이 안 보이고, 분류를 마친 커밋이 "미분류"
    # 로 **새로 차단됨**(fail-CLOSED 오차단). 같은 트리를 가리키는 호출이 여럿인 것은
    # 모호하지 않음. LINT_RAN 은 게이트가 W 를 검사했다는 증거.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    p = wt.as_posix()
    r = _run_runner(main, f"git -C {p} commit -m x && git -C {p} commit --amend --no-edit")
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "echo LINT_RAN" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_blocks_an_unclassified_commit_through_a_glued_path(tmp_path: Path):
    # 커밋 경로의 짝 결함: 셸 self-filter 는 `git -C "<부모>"/wt commit` 을 커밋으로
    # 라우팅하는데, -C 값을 통짜 대안으로 읽으면 `<부모>` 만 잡고 `/wt` 를 버려 게이트가
    # 엉뚱한 트리를 봄. 그 트리가 깨끗하면 조기 종료로 exit 0 — 티어 마커도 없는 커밋이
    # 통과함(Invariant 1 예외 2 무력화). 방향이 fail-CLOSED 라 merge 쪽보다 위험.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "My Project" / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    (wt / "a.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "a.py"], wt)  # 워크트리는 더럽고 티어 마커는 없음
    # 경로에 공백을 둠: 셸 self-filter 가 통짜 대안이면 여기서 탈락해 훅이 exit 0 하고,
    # 파이썬 게이트는 아예 실행되지 않음 — 두 레이어를 한 번에 측정.
    r = _run_runner(main, f'git -C "{tmp_path.as_posix()}/My Project"/wt commit -m x')
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
@pytest.mark.parametrize(
    "command",
    [
        # 겹따옴표 안의 치환은 셸이 진짜로 돌림. span 을 통째로 덮으면 커밋이 사라지고
        # 훅이 exit 0 함(실측: 이 셋 전부).
        'echo "$(git commit -m x)"',
        # 명령 자리의 치환이 돌리는 것은 그 **출력**.
        "$(echo 'git commit -m x')",
        # 자기 인자에 적힌 명령을 돌리는 프로그램. 실행 목록을 방아쇠로 쓰면 이 이름이
        # 목록에 없어 빠짐.
        """awk 'BEGIN{system("git commit -m x")}'""",
        # 확장이 켜진 heredoc 본문이 치환으로 시작하면 본문의 시작 기록이 사라져,
        # 인터프리터와 그것이 건네받은 스크립트가 서로 다른 원소로 찢어짐.
        "bash <<EOF\n$(pwd)/setup.sh\ngit commit -m x\nEOF",
        # 파이프 뒤 단계의 리더 이름이 앞 단계를 가려 원소가 통째로 면제를 받음.
        "bash -c 'git commit -m x' | cat",
        ">out git commit -m x | cat",
        # 서브커맨드 자리의 인용은 그 낱말의 철자. 원문에 `commit` 낱말이 없어 러너의
        # 거친 필터가 문법보다 좁아지고, 판정 전에 exit 0(실측).
        "git com''mit -m x",
        "git c'ommit' -m x",
        "git 'commit' -m x",
        # 셸이 명령을 여는 자리인데 명령 자리 판정이 부정하던 낱말.
        "if git commit -m x; then :; fi",
        # git 자신의 서브커맨드가 인자를 돌림.
        "git submodule foreach 'git commit -am x'",
        # 줄이음은 CRLF 도 포함(Invariant 2).
        "git \\\r\n commit -m x",
    ],
    ids=[
        "substitution-in-quotes",
        "substitution-at-command-position",
        "awk-system",
        "heredoc-body-opening-with-a-substitution",
        "interpreter-piped-into-a-reader",
        "redirection-before-the-program",
        "subcommand-split-by-quotes",
        "subcommand-opened-by-a-quote",
        "subcommand-wholly-quoted",
        "if-opens-a-command",
        "git-subcommand-runs-its-argument",
        "crlf-line-continuation",
    ],
)
def test_runner_blocks_a_commit_the_mask_used_to_hide(tmp_path: Path, command: str):
    """실제 exit 코드로 측정 — 러너의 거친 필터부터 미분류 차단까지 두 층 전부."""
    main = tmp_path / "main"
    _init_repo(main)
    (main / "a.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "a.py"], main)  # 더럽고 티어 마커는 없음 = 미분류 커밋
    r = _run_runner(main, command)
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (command, r.returncode, r.stdout, r.stderr)


@requires_bash_git
@pytest.mark.parametrize(
    "command,blocked",
    [
        ('git commit -m "{pad}"', True),
        ("gi't' commit -m x # {pad}", True),
        ("git com''mit -m x # {pad}", True),
        ("grep -c 'git commit' README.md # {pad}", False),
        ("echo {pad}", False),
    ],
    ids=["commit", "name-side-spelling", "subcommand-spelling", "a-mention", "no-git"],
)
def test_the_filter_cap_skips_the_filter_and_not_the_gate(
    tmp_path: Path, command: str, blocked: bool
):
    """상한을 넘는 명령은 거친 필터를 건너뛰고 **게이트로** 감 — 떨어뜨리지 않음.

    필터가 넓어지는 방향이라 판정은 그대로임: 진짜 커밋은 여전히 차단되고, 언급은
    `--classify` 가 통과시킴. 상한이 `exit 0` 이 되면 이 셋 중 앞의 셋이 조용히 통과함.
    """
    main = tmp_path / "main"
    _init_repo(main)
    (main / "a.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "a.py"], main)  # 더럽고 티어 마커는 없음 = 미분류 커밋
    r = _run_runner(main, command.format(pad="'a'" * 8000))
    want = fgc.BLOCK_EXIT_CODE if blocked else 0
    assert r.returncode == want, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_the_filter_does_not_cost_the_square_of_the_quote_count(tmp_path: Path):
    """따옴표를 지운 사본은 일치마다 문자열을 새로 만듦 — 상한 없이는 2차.

    상한이 없을 때 `'a'`×k 의 러너 wall 은 32KB 753ms · 64KB 2.4초 · 128KB 7.8초 ·
    512KB 115초(실측, 배가마다 약 4배). 훅 타임아웃은 판정이 아예 없다는 뜻이고,
    긴 인용 인자는 병리 입력이 아니라 평범한 명령. 상한 뒤에는 spawn 상수가
    지배해 4배 구간이 1.2배로 내려감(실측 32KB 843ms · 128KB 1154ms).

    문턱은 4배 — 2차면 10배가 넘고, 선형이면 상수 때문에 2배를 넘지 않음.
    """
    main = tmp_path / "main"
    _init_repo(main)
    walls = []
    for chars in (32768, 131072):
        command = "echo " + "'a'" * (chars // 3)
        started = time.perf_counter()
        r = _run_runner(main, command)
        walls.append(time.perf_counter() - started)
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert walls[1] < walls[0] * 4, walls


@requires_bash_git
def test_runner_still_leaves_a_read_only_command_beside_an_interpreter_alone(tmp_path: Path):
    """그물이 원소 단위가 아니면 이런 명령이 통째로 차단됨 — 개발자가 온종일 쓰는 모양."""
    main = tmp_path / "main"
    _init_repo(main)
    (main / "a.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "a.py"], main)
    r = _run_runner(main, "python3 --version && grep 'git commit' a.py")
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_gates_a_worktree_whose_path_has_a_space(tmp_path: Path):
    # 공백 있는 경로는 Windows 에서 예외가 아니라 기본값에 가깝고(`C:/Users/x/My Project`),
    # 스킬은 워크트리 경로를 **리터럴**로 적으라고 지시 → 지시를 그대로 따른 명령이
    # 게이트를 못 깨우면 안 됨. 인용 토큰을 한 덩어리로 읽지 못하면 `-C` 뒤의 옵션 그룹이
    # `"C:/My` 에서 끊겨 self-filter 가 "커밋 아님"으로 흘려보내고, 조용히 전 게이트가 꺼짐.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "work tree"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    r = _run_runner(main, f'git -C "{wt}" commit -m x')
    assert "echo LINT_RAN" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_ignores_commit_graph_subcommand(tmp_path: Path):
    # `git -C <wt> commit-graph write` 는 커밋이 **아님** — 온전한 단어 매칭이 발동하면 안 됨.
    # 아니면 커밋도 아닌 git 명령이 게이팅됨(오차단 위험).
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    r = _run_runner(main, f"git -C {wt} commit-graph write")
    assert "echo LINT_RAN" not in (r.stdout + r.stderr)
    assert r.returncode == 0


# --- 커밋 트리를 한 곳으로 못 박는 명령(Invariant 7 의 선언된 예외) ---
# 넷 다 러너 exit 코드로 잼 — 게이트가 실제로 섰는지는 판정 함수가 아니라 이 숫자가 말함.


@requires_bash_git
def test_runner_gates_a_dot_dash_c_beside_a_bare_commit(tmp_path: Path):
    # ROOT 가 worktree(더럽고 미분류)로 가 deny 가 남는지만 잼. `.` 를 접지 않아도 rc 는 2 로
    # 남음 — 그때는 답이 둘이 되어 `unresolved=1` 이 대신 조기 종료를 막기 때문(실측). 즉 이
    # 케이스는 두 기계의 **합**을 재는 것이고, `.` 정규화 자체는
    # `test_dir_from_command_pins_the_tree_or_declines[dot-normalised]` 가 따로 못 박음.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    (wt / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], wt)
    r = _run_runner(main, f"cd {wt} && git -C . commit -m a && git commit --amend --no-edit")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_gates_cd_hopping_across_trees(tmp_path: Path):
    # 선두 트리는 깨끗하고 두 번째 트리에서 커밋이 돎 — 미해결이 조기 종료를 막아야 함.
    main = tmp_path / "main"
    _init_repo(main)
    a = tmp_path / "wta"
    b = tmp_path / "wtb"
    _rg(["worktree", "add", "-b", "feature/a", str(a)], main)
    _rg(["worktree", "add", "-b", "feature/b", str(b)], main)
    (b / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], b)
    r = _run_runner(main, f"cd {a} && git commit -m a; cd {b} && git commit -m b")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_gates_a_subshell_cd_commit(tmp_path: Path):
    # `(` 는 명령 시작이지 선두 접두가 아님 — 해석기가 못 따라가는 이동임.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    (wt / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], wt)
    r = _run_runner(main, f"(cd {wt} && git commit -m x)")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_stops_over_blocking_cd_main_from_a_worktree(tmp_path: Path):
    """재지정은 **새로 차단하면 안 됨** — `;` 로 이은 선두 `cd` 를 안 읽으면 훅 cwd 인
    worktree 가 ROOT 로 남고, 그 worktree 는 자기 브랜치에 묶인 마커가 없어 미분류로 막힘.

    마커는 `main` 에 묶고(worktree 의 브랜치 `feature/x` 가 아님), worktree 는 그 마커가
    **쓰이기도 전에** 만들어짐 — 그러니 worktree 가 자기 브랜치와 우연히 맞는 마커를
    물려받을 길이 없음. 고치기 전에는 rc 2, 고친 뒤에만 rc 0.
    """
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)  # main 이 분류되기 전에
    vdev = main / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:main", encoding="utf-8")  # main **자신의** 브랜치에 묶음
    (vdev / "review.done").touch()
    (vdev / "doc-sync.done").touch()
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text("modules: []\n", encoding="utf-8")
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "classify"], main)
    (main / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], main)
    r = _run_runner(main, f"cd {main}; git commit -m x", hook_cwd=wt)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_gates_a_leading_cd_whose_value_is_not_expanded(tmp_path: Path):
    """훅은 셸 확장 **전** 텍스트를 받으므로 `cd $WT` 의 값은 디렉터리 이름이 아님.
    그것을 이름으로 읽으면 해석기가 못 찾아 ROOT 가 깨끗한 main 에 남고, 러너가 거기서
    조기 종료해 진짜 커밋에서 게이트가 통째로 빠짐(실측: 펼친 대조군 rc 2, 이쪽 rc 0).
    """
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    (wt / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], wt)  # main 은 깨끗하고 worktree 만 더러움
    r = _run_runner(main, "cd $WT && git commit -m x")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_reads_a_tilde_in_a_leading_cd_as_the_tree_it_names(tmp_path: Path, monkeypatch):
    """`~` 는 뜻이 하나라 펼침 — 그래서 이 철자가 worktree 를 지목하고, 그 트리가 더러우면
    **전에는 안 막던 것을 막음**(실측: 러너 exit 0 → 2). Invariant 7 이 금지하는 것은 커밋이
    돌지 않는 트리를 읽어 생기는 오차단이고, 이쪽은 커밋이 떨어지는 트리를 맞게 읽는 것임 —
    `git -C ~/wt commit` 이 이미 같은 답을 냈으니 두 철자가 이제 일치함.

    홈을 `tmp_path` 로 돌려 **`~` 철자 그대로** 러너를 돌림. 펼친 경로로 돌리는 것은 이 변경
    전에도 막히던 모양이라 아무것도 못 재고, 테스트 이름이 말하는 전이를 그냥 비워 둠.
    `expanduser` 는 Windows 에서 `USERPROFILE` → `HOMEDRIVE`+`HOMEPATH` → `HOME` 순으로 보므로
    넷 다 세움. `_run_runner` 가 자식 환경을 `os.environ` 에서 짓기 때문에 같은 설정이 인프로세스
    판정과 자식 양쪽에 걸림.
    """
    main = tmp_path / "main"
    _init_repo(main)
    home = tmp_path / "home"
    home.mkdir()
    wt = home / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    (wt / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], wt)  # main 은 깨끗하고 worktree 만 더러움
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOMEDRIVE", home.drive or "")
    monkeypatch.setenv("HOMEPATH", str(home)[len(home.drive) :])
    # 구분자는 `expanduser` 가 준 대로 섞여 나옴(`…\home/wt`) — git 은 그대로 받으므로
    # 경로로 비교함. 문자열로 비교하면 이 판정이 OS 구분자에 묶임.
    assert Path(os.path.expanduser("~/wt")) == wt, "홈 치환이 안 걸렸다 — 아래 판정이 무의미"
    resolved = vp._dir_from_command("cd ~/wt && git commit -m x")
    assert resolved is not None and Path(resolved) == wt
    assert vp.commit_tree_unresolved("cd ~/wt && git commit -m x") is False  # 이름을 댔음
    r = _run_runner(main, "cd ~/wt && git commit -m x")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_the_runner_leaves_no_bytecode_beside_the_scripts(tmp_path: Path, monkeypatch):
    """스크립트는 호스트의 추적 트리에 있음 — 거기 `__pycache__` 가 생기면 트리가 영구히
    더럽고, `git add -A` 가 `.pyc` 를 커밋에 쓸어 담음."""
    import shutil

    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    repo = Path(__file__).resolve().parent.parent.parent
    plugin = tmp_path / "plugin"
    shutil.copytree(
        repo / "scripts", plugin / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    main = tmp_path / "main"
    _init_repo(main)
    _run_runner(main, "git commit -m x", plugin_root=plugin)
    assert not list(plugin.rglob("__pycache__"))


def _main_with_config(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    _init_repo(main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text("modules: []", encoding="utf-8")
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "config"], main)
    return main


@requires_bash_git
@pytest.mark.parametrize(
    "command",
    [
        "git com''mit -m x",
        "git c\\ommit -m x",
        "g''it commit -m x",
        "git $'commit' -m x",
        "echo a | git $'commit' -m x",
        "/usr/bin/git $'commit' -m x",
        "git $'\\x63ommit' -m x",
        'git "co\\\nmmit" -m x',
        # ANSI-C 이스케이프가 필터가 찾는 프로그램을 철자하거나, 그 `$'` 가 인용으로 갈라짐
        "$'\\x67it' commit -m x",
        'bash -c "git "\\$"\'\\x63ommit\'"',
        # 인용한 Windows 경로의 git — 큰따옴표 안 백슬래시는 bash 가 남김
        "\"C:\\Program Files\\Git\\bin\\git.exe\" com''mit -m x",
        "\"C:\\Git\\bin\\git.exe\" com''mit -m x",
    ],
)
def test_a_quote_split_commit_reaches_the_gate(tmp_path: Path, command: str):
    """사전 필터는 분류기를 띄울지만 정함 — 리터럴 낱말을 바라는 필터는 bash 가 돌리는 커밋을
    판정 한 번 없이 떨어뜨림. 차단이 게이트가 붙었다는 증거: 이 트리엔 tier 마커가 없음."""
    main = _main_with_config(tmp_path)
    (main / "a.txt").write_text("x", encoding="utf-8")
    _rg(["add", "a.txt"], main)
    r = _run_runner(main, command)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
@pytest.mark.parametrize("spelling", ["com''mit", "c\\ommit", "co\\\nmmit"])
def test_a_quote_split_worktree_commit_is_not_judged_by_a_clean_main(tmp_path: Path, spelling):
    """`-C` 판독기는 이 커밋이 안 보이는 마스크를 걸어 ROOT 가 main 에 남음 — 깨끗한 main 이
    게이트 전에 실행을 끝냈음. 차단이 증거: worktree 엔 tier 마커가 없음."""
    main = _main_with_config(tmp_path)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    (wt / "a.txt").write_text("x", encoding="utf-8")
    _rg(["add", "a.txt"], wt)
    r = _run_runner(main, f"git -C {wt.as_posix()} {spelling} -m x")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
