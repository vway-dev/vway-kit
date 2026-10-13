"""머지의 피연산자 사이에 선 치환·백틱과, 다른 명령의 인자로 적힌 머지를 전략 판정이
셸처럼 읽는가 — 그리고 그 읽기가 명령 길이에 선형인가.

판정은 fail-CLOSED 예외(Invariant 1 ③)라 셸보다 좁게 읽는 모양 하나가 그 행을 조용히 끔.
치환은 한 낱말이고, 이스케이프한 백틱은 아무것도 열지 않으며, 머지·pull·switch·checkout 의
인자로 적힌 `git merge` 는 돌지 않음.
"""

import time
from pathlib import Path

import pytest

import scripts._vway_paths as vp
import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import (
    _init_repo,
    _rg,
    _run_merge_check,
    _run_runner,
    _write_policy,
    requires_bash_git,
)

# ── 치환은 피연산자 낱말 하나 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        # 소스 뒤의 치환이 그 뒤 플래그를 떼어 내지 않음
        ("git merge fix/a `true` --no-ff", "dev", True),
        ("git merge fix/a $(true) --no-ff", "dev", True),
        ("git merge fix/a $(true; false) --no-ff", "dev", True),
        ("git merge feature/x $(echo '#') --squash", "dev", False),
        ('git merge stage -m "Release $(date +%F)"', "main", True),
        ('git merge --no-ff stage -m "Release $(date +%F)"', "main", False),
        ('git merge feature/x "$(date)"', "dev", True),
        ("git merge feature/x -m \"$(printf 'a\\nb')\" --squash", "dev", False),
        # 이스케이프한 백틱은 아무것도 안 엶 — 머지의 낱말은 `;` 에서 끝남
        ("git merge feature/x \\`; echo --squash \\`", "dev", True),
        ("git merge --no-ff fix/a \\`; echo --ff \\`", "dev", True),
        ("git merge feature/x \\`; git merge --squash feature/y \\`", "dev", True),
        # 진짜 백틱과 짝을 지으면 그 뒤 플래그가 치환 안으로 숨음(bash argv: `--no-ff` 있음)
        ("git merge stage \\`x `true` --no-ff", "main", False),
        # 머지 낱말 너머의 shlex 가 못 가르는 텍스트도 그 낱말을 못 읽게 하지 않음
        ("git merge feature/x -m $(cat <<EOF\nit's\nEOF\n)", "dev", True),
        ("git merge feature/x $(echo hi # don't\n)", "dev", True),
        ('git merge feature/x $(true) -m "a $(echo b c)"', "dev", True),
        ("git merge feature/x <<'E O'\nx\nE O\n", "dev", True),
        # switch 인자 안의 머지는 그 switch 보다 먼저, 앞 switch 위로 돎
        ("git switch main && git switch -c $(git merge stage)", "dev", True),
        ("git switch main && git switch -c `git merge --no-ff stage`", "dev", False),
        ("git switch main $(git merge feature/x)", "dev", True),
    ],
)
def test_a_substitution_is_one_operand_word(monkeypatch, tmp_path, command, branch, blocked):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


def test_a_closing_backtick_ends_the_command_it_encloses():
    assert fgc.parse_merge_commands("git switch `git merge a` && git merge b") == [
        (set(), "a"),
        (set(), "b"),
    ]


def test_a_substitution_names_no_switch_target():
    """치환이 출력하는 브랜치는 이름을 댈 수 없음 — 체인을 불명확으로 만듦."""
    assert fgc._target_from_command("git switch $(echo dev) && git merge feature/x") is None


@requires_bash_git
@pytest.mark.parametrize(
    "command,blocked",
    [
        ('git merge stage -m "Release $(date +%F)"', True),
        ("git merge stage $(true) --no-ff", False),
        ("git merge stage `true` --no-ff", False),
        ("git merge stage \\`x `true` --no-ff", False),
        ("git merge stage \\`; echo --no-ff \\`", True),
        ("git switch dev git merge stage", False),
        ("eval $(true) git merge --no-ff stage $(echo ';') git merge stage", True),
    ],
)
def test_the_runner_reads_a_substitution_as_one_word(tmp_path: Path, command, blocked):
    """실제 러너로 — 필터·분류기·판정을 다 거침. HEAD 는 main 이고 출하 정책은 main 으로의
    머지에 `--no-ff` 를 요구함."""
    main = tmp_path / "main"
    _init_repo(main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  integration: dev\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, command)
    assert (r.returncode == fgc.BLOCK_EXIT_CODE) is blocked, (command, r.returncode, r.stdout)


# ── 다른 명령의 인자로 적힌 머지 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        # 머지 경로 명령의 인자로 적힌 git merge 는 돌지 않음
        ("git switch dev git merge feature/x", "dev", False),
        ("FOO=1 git switch dev git merge feature/x", "dev", False),
        ("git sw''itch dev git mer''ge feature/x", "dev", False),
        # 앞 호출이 프로그램이 아니면 버리지 않음 — eval 은 치환 출력의 구분자로 다시 가름
        ("eval $(true) git merge --squash feature/a $(echo ';') git merge feature/x", "dev", True),
        ("eval `true` git merge --squash feature/a `echo '&&'` git merge feature/x", "dev", True),
        (
            "eval $(true) git merge --squash feature/a $(echo '&&') git merge --no-ff fix/y",
            "dev",
            True,
        ),
        ("sudo git switch dev git merge feature/x", "dev", False),
        # 대입·접두 낱말 앞에 eval 이 서도 프로그램 자리가 아님 — bash 가 뒤 머지를 돌림
        ("eval A=1 git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        ("eval command git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        ("eval time git merge y `echo '&&'` git merge --no-ff fix/x", "dev", True),
        ("eval >/dev/null git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        ("eval A=1 git merge y $(echo ';') git merge feature/a", "dev", True),
        ("eval A=1 git switch dev $(echo ';') git merge --no-ff fix/x", "dev", True),
        # 리다이렉션 안의 `&`·`|` 는 명령 경계가 아님 — `eval` 이 lead 에 남음
        ("eval >&A=1 git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        ("eval >|A=1 git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        ("eval >& A=1 git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        ("eval 2>|A=1 git merge y $(echo ';') git merge feature/a", "dev", True),
        ("eval >|time git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        ("eval >& nohup git merge y $(echo ';') git merge --no-ff fix/x", "dev", True),
        # 남긴 호출은 뒤 호출 머리에서 끊지 않음 — 치환 출력의 따옴표가 뒤 호출을 `-m` 값으로
        # 삼키면 bash 는 `--no-ff` 까지 한 머지로 돌림
        ("eval `true` git merge fix/a `echo '-m\"'` git switch y `echo '\"'` --no-ff", "dev", True),
        ("eval `true` git merge fix/a `echo '-m\"'` git merge y `echo '\"'` --no-ff", "dev", True),
        (
            "eval `true` git merge fix/a `echo '-m\"'` git checkout y `echo '\"'` --no-ff",
            "dev",
            True,
        ),
        ("eval `true` git merge fix/a `echo '-m\"'` git pull o y `echo '\"'` --no-ff", "dev", True),
        (
            "eval $(true) git merge fix/a $(echo '-m\"') git switch y $(echo '\"') --no-ff",
            "dev",
            True,
        ),
        # 마스크가 치환을 일찍 닫았을 수 있으면 버리지 않음 — 셸은 그 머지를 돌림
        ("git switch dev $(case x in x) git merge feature/x;; esac)", "dev", True),
    ],
)
def test_a_merge_among_another_commands_arguments(monkeypatch, tmp_path, command, branch, blocked):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


# ── 길이에 선형 ───────────────────────────────────────────────────────────────

BUDGET_SECONDS = 3.0


def _verdict_inputs(command: str) -> None:
    """판정이 읽는 모든 것 — 머지·pull 전부와 그 target."""
    masked = vp.mask_literals(command)
    judged = fgc._judged(command, masked)
    fgc._switch_targets(command, masked, [j.call for j in judged])


def _clear_caches() -> None:
    for fn in (vp._shell_regions, vp._blanked_view, vp._comment_starts, fgc._cd_chain):
        fn.cache_clear()
    for name in ("_word_table", "_substitution_tree", "_levels", "_children", "_unblanked_view"):
        cached = getattr(vp, name, None)
        if cached is not None:
            cached.cache_clear()


@pytest.mark.parametrize(
    "unit",
    [
        "git switch dev `git merge --squash feature/x` ",
        "git switch dev $(git merge --squash feature/x) ",
        "git switch dev && git merge --squash feature/x; ",
        "git commit -m x `git merge a` ",
        "git merge --squash feature/x `true` ",
        "git merge feature/x 'x y' \"p q\" ",
        "git merge --squash feature/x git switch dev ",
        "git -c a=b merge feature/x ",
        "git pull origin feature/x -c ",
        "git mer''ge --squash feature/x ",
        "git switch dev $(case x in x) git merge a;; esac) ",
    ],
)
def test_many_invocations_in_one_command_cost_the_verdict_little(unit):
    """한 단순 명령에 선 호출들은 저마다 명령 끝까지 가는 피연산자 영역을 가질 수 있음 —
    호출마다 다시 가르면 길이의 제곱이고, 훅 타임아웃은 머지를 통과시킴. 부하 아래 단일
    측정이 튀므로 최선값으로 잼(2차는 어느 측정에서도 느림)."""
    command = unit * 2000
    runs = []
    for _ in range(2):
        _clear_caches()
        started = time.perf_counter()
        _verdict_inputs(command)
        runs.append(time.perf_counter() - started)
    assert min(runs) < BUDGET_SECONDS, f"{len(command)} chars: {runs}"


# 훅 타임아웃(`gate_spec` 600초)의 1/20.
UNPARSED_CHAIN_BUDGET_SECONDS = 30.0


@pytest.mark.parametrize(
    "unit", ["echo `x` git merge a ", "eval $(true) git merge --squash feature/a "]
)
def test_calls_behind_a_non_program_word_stay_far_under_the_hook_timeout(unit):
    """프로그램이 아닌 낱말 뒤에 늘어선 호출은 버리지도 끊지도 않아 저마다 명령 끝까지 읽음
    — 길이의 제곱인 의도된 잔여(`runs_among_operands`). 2000 단위(84KB)가 이 예산 안이면
    타임아웃에 닿는 것은 수백 KB 짜리 명령뿐."""
    command = unit * 2000
    _clear_caches()
    started = time.perf_counter()
    _verdict_inputs(command)
    elapsed = time.perf_counter() - started
    assert elapsed < UNPARSED_CHAIN_BUDGET_SECONDS, f"{len(command)} chars: {elapsed}"


def test_the_verdict_grows_linearly_with_backtick_chains():
    """크기를 두 배로 하면 시간도 두 배 남짓 — 2차면 네 배."""
    unit = "git switch dev `git merge --squash feature/x` "
    times = []
    for n in (1000, 2000):
        runs = []
        for _ in range(2):
            _clear_caches()
            started = time.perf_counter()
            _verdict_inputs(unit * n)
            runs.append(time.perf_counter() - started)
        times.append(min(runs))
    assert times[1] < 3.2 * max(times[0], 0.05), times
