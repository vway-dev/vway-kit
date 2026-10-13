"""git 이 받는 머지 철자를 전략 판정이 git 처럼 읽는가 — 축약된 긴 옵션, 반대 옵션 중
나중 것, 명령줄 `-c merge.ff`, 전체 ref 로 댄 소스, 인용이 쪼갠 서브커맨드, 그리고
`git pull` 이 하는 머지.

판정은 fail-CLOSED 예외(Invariant 1 ③)라 git 보다 좁게 읽는 철자 하나가 그 행을 조용히
끔. git 동작에 기대는 행은 실제 git(2.47)으로 잰 것.
"""

import json
import os
import sys
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from tests._proc import run_bounded
from tests.gate_check._helpers import (
    _init_repo,
    _rg,
    _run_merge_check,
    _run_runner,
    _write_policy,
    requires_bash_git,
)
from tests.skill_docs._helpers import _spawns_the_gate

# ── 플래그 하나를 git 이 읽는 대로 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "command,flag,present",
    [
        ("git merge --no-f fix/x", "--no-ff", True),
        ("git merge --squas feature/x", "--squash", True),
        ("git merge --sq feature/x", "--squash", True),
        # 반대 옵션 둘이면 나중 것이 이김
        ("git merge --squash --no-squash feature/x", "--squash", False),
        ("git merge --no-squash --squash feature/x", "--squash", True),
        ("git merge --no-ff --ff fix/x", "--no-ff", False),
        ("git merge --no-ff --ff-only fix/x", "--no-ff", False),
        ("git merge --ff --no-ff fix/x", "--no-ff", True),
        # `--ff` 는 자기 옵션이지 `--ff-only` 의 축약이 아님
        ("git merge --ff fix/x", "--ff-only", False),
        # config 는 뒤에 선 명시 플래그가 없을 때만 그 플래그를 대신함
        ("git -c merge.ff=false merge fix/x", "--no-ff", True),
        ("git -c Merge.FF=no merge fix/x", "--no-ff", True),
        ("git -c merge.ff=false merge --ff fix/x", "--no-ff", False),
        ("git -c merge.ff=true merge fix/x", "--no-ff", False),
        ("git -c merge.ff=only merge fix/x", "--ff-only", True),
    ],
)
def test_a_flag_is_read_the_way_git_reads_it(command, flag, present):
    merges = fgc.parse_merge_commands(command)
    assert merges, command
    assert fgc._carries(merges[0][0], flag) is present, (command, merges)


@pytest.mark.parametrize(
    "command",
    [
        "git mer''ge --no-ff fix/x",
        'git mer""ge --no-ff fix/x',
        "git m\\erge --no-ff fix/x",
        "git -C /tmp/wt mer''ge --no-ff fix/x",
    ],
)
def test_a_quote_split_merge_is_parsed(command):
    assert fgc.parse_merge_commands(command) == [({"--no-ff"}, "fix/x")], command


@pytest.mark.parametrize(
    "source",
    ["refs/heads/feature/x", "refs/remotes/origin/feature/x", "remotes/origin/feature/x"],
)
def test_a_full_ref_matches_its_branch_rule(source):
    assert fgc._branch_matches("feature/*", source, {})


def test_a_full_ref_matches_a_configured_branch():
    assert fgc._branch_matches("integration", "refs/heads/dev", {"integration": "dev"})


def test_a_checkout_of_a_full_ref_is_no_target():
    """`git checkout refs/heads/dev` 는 HEAD 를 떼어 놓음 — 접두를 벗겨 dev 로 읽으면 들어간
    적 없는 integration 행으로 심사함."""
    assert fgc._target_from_command("git checkout refs/heads/dev && git merge f/x") is None


# ── git pull ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command,source,squash",
    [
        ("git pull origin feature/x", "feature/x", False),
        ("git pull --squash origin feature/x", "feature/x", True),
        ("git pull --no-rebase origin feature/x", "feature/x", False),
        ("git pull --rebase=false origin feature/x", "feature/x", False),
        ("git pull origin +feature/x:feature/x", "feature/x", False),
        ("git pull -s ort origin feature/x", "feature/x", False),
    ],
)
def test_a_pull_naming_a_branch_is_a_merge_of_it(command, source, squash):
    pulls = fgc.parse_pull_commands(command)
    assert pulls and pulls[0][1] == source, (command, pulls)
    assert ("--squash" in pulls[0][0]) is squash


@pytest.mark.parametrize("command", ["git pull", "git pull --ff-only", "git pull origin"])
def test_a_pull_that_names_no_branch_is_not_judged(command):
    assert fgc.parse_pull_commands(command) == []


@pytest.mark.parametrize(
    "command",
    [
        "git pull --rebase --no-ff origin fix/x",
        "git pull --reb --no-ff origin fix/x",
        "git pull -r --no-ff origin fix/x",
        "git pull --rebase=interactive --no-ff origin fix/x",
        "git -c pull.rebase=true pull --no-ff origin fix/x",
    ],
)
def test_a_rebasing_pull_still_brings_its_branch_in(command):
    """rebase 하는 pull 도 그 브랜치를 target 에 들임 — target 이 소스 위로 올라가거나
    fast-forward 됨(실측). 머지 커밋이 없으므로 머지 플래그는 없음으로 읽음."""
    assert fgc.parse_pull_commands(command) == [(set(), "fix/x")]


@pytest.mark.parametrize("command", ["git pull origin feature/x", "git pu''ll origin feature/x"])
def test_a_pull_reaches_the_gate_and_is_read_as_a_merge(command):
    """러너 필터가 띄우고 `--classify` 가 merge 로 답해야 판정에 닿음 — 둘 중 하나만 빠져도
    판정은 조용히 없음."""
    assert _spawns_the_gate(command)
    assert fgc.parse_pull_commands(command)


# ── 판정 ──────────────────────────────────────────────────────────────────────


@requires_bash_git
@pytest.mark.parametrize(
    "command",
    [
        "git pull origin stage",
        "git merge --no-f origin/stage --ff",
        "git mer''ge refs/heads/stage",
    ],
)
def test_the_runner_hands_every_spelling_to_the_verdict(tmp_path: Path, command):
    """실제 러너로: 필터가 pull 에도 분류기를 띄우고 분류기가 merge 로 답해야 함. 출하 정책은
    main 으로의 머지에 `--no-ff` 를 요구함."""
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
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)
    assert "--no-ff" in r.stdout + r.stderr


@requires_bash_git
@pytest.mark.parametrize("key", ["pull.rebase", "branch.main.rebase"])
def test_the_runner_judges_a_pull_config_turns_into_a_rebase(tmp_path: Path, key):
    """config 가 rebase 로 바꾸는 pull 도 막음: stage 를 main 위로 들이는 rebase 는 `--no-ff`
    머지 커밋이 없는 승격임(실측: main 이 stage 로 fast-forward). 저장소 config 는 읽지
    않으므로 명령이 철자한 머지로 판정됨."""
    main = tmp_path / "main"
    _init_repo(main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  integration: dev\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    _rg(["config", key, "true"], main)
    r = _run_runner(main, "git pull origin stage")
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        ("git merge --no-f fix/x", "dev", True),
        ("git -c merge.ff=false merge fix/x", "dev", True),
        ("git mer''ge --no-ff fix/x", "dev", True),
        ("git merge --no-ff --ff fix/x", "dev", False),
        ("git merge --squash --no-squash feature/x", "dev", True),
        ("git merge --squas feature/x", "dev", False),
        ("git merge refs/heads/feature/x", "dev", True),
        ("git merge --squash refs/heads/feature/x", "dev", False),
        ("git pull origin feature/x", "dev", True),
        ("git pull --squash origin feature/x", "dev", False),
        ("git pull --no-ff origin fix/x", "dev", True),
        # rebase 하는 pull 은 squash 도 머지 커밋도 없이 소스를 들임
        ("git pull --rebase origin feature/x", "dev", True),
        ("git pull --rebase --no-ff origin fix/x", "dev", False),
        ("git switch dev && git pull origin feature/x", "feature/x", True),
        ("git pull --ff-only", "dev", False),
        # 다른 worktree 의 브랜치는 여기서 알 수 없으므로 그 pull 은 판정하지 않음
        ("git -C /elsewhere pull origin feature/x", "dev", False),
        ("git -C /elsewhere mer''ge --no-ff fix/x", "dev", False),
        # pull 에서는 pull.ff 가 merge.ff 를 이김
        ("git -c pull.ff=false pull origin dev", "stage", False),
        ("git -c merge.ff=false -c pull.ff=true pull origin fix/a", "dev", False),
        # 값을 받는 옵션의 축약은 다음 플래그가 아니라 자기 값을 먹음
        ("git pull --strategy-o theirs --no-ff origin dev", "stage", False),
        ("git merge --cleanup strip feature/x", "dev", True),
        # `-r` 을 든 짧은 묶음은 rebase — 머지 커밋이 없으니 `--no-ff` 를 요구하는 행에 걸림
        ("git pull -rmerges origin dev", "stage", True),
        ("git pull -qr origin dev", "stage", True),
        ("git pull -qr --no-ff origin fix/x", "dev", False),
        # `-S` 는 키를 붙여 받음: r 은 키이고 이 pull 은 머지함
        ("git pull -Sr origin stage", "main", True),
        # `-j` 는 값을 붙여서만 받음
        ("git pull -j . feature/x", "dev", True),
        # 마지막 플래그에 붙은 파이프·리다이렉션은 그 플래그를 끝냄
        ("git mer''ge dev --no-ff|cat", "stage", False),
        ("git mer''ge dev --no-ff>log", "stage", False),
        # 보이는 머지 옆, 치환 안의 쪼갠 머지도 읽힘
        ("git merge --squash a | git mer''ge feature/y", "dev", True),
        ("echo $(git mer''ge feature/y)", "dev", True),
        # 설정값은 git 처럼 읽음: 다듬지 않고, 정수는 값으로
        ("git -c 'merge.ff= false' merge fix/a", "dev", False),
        ("git -c merge.ff=00 merge fix/a", "dev", True),
    ],
)
def test_the_strategy_verdict_reads_every_spelling(monkeypatch, tmp_path, command, branch, blocked):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        ("git pull && git switch main && git merge stage", "dev", True),
        ("git pull && git switch dev && git merge stage", "main", False),
        ("git mer''ge dev && git switch stage", "dev", False),
        ("git pu''ll origin feature/x && git switch dev", "feature/x", False),
        # 머지 사이의 switch 는 뒤 머지의 target — 첫 머지 것으로 심사하지도, 빼지도 않음
        ("git merge --squash feature/a && git switch main && git merge stage", "dev", True),
        (
            "git switch dev && git merge --squash feature/a"
            " && git switch main && git merge --no-ff stage",
            "x",
            False,
        ),
    ],
)
def test_each_merge_is_judged_against_the_switch_before_it(
    monkeypatch, tmp_path, command, branch, blocked
):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


COMMIT_SKILL_BODY = (
    "msg=$(cat <<'EOF'\nfix: x\n\n- then git merge feature/x\nEOF\n)\n"
    "printf '%s\n' \"$msg\" | git commit -F -"
)


@pytest.mark.parametrize(
    "command",
    [
        COMMIT_SKILL_BODY,
        "git commit -F - <<'EOF'\nfix: x\n\n- then git merge feature/x\nEOF",
        "git commit -m x  # then git mer''ge feature/x",
        "git commit -m x  # then git pu''ll origin feature/x",
    ],
)
def test_a_merge_a_commit_message_mentions_is_not_parsed(command):
    assert fgc.parse_merge_commands(command) == []
    assert fgc.parse_pull_commands(command) == []


def test_a_commit_whose_message_mentions_a_merge_is_not_blocked(monkeypatch, tmp_path):
    _write_policy(tmp_path)
    assert _run_merge_check(monkeypatch, tmp_path, COMMIT_SKILL_BODY, "dev") == 0


# ── git 이 머지하는데 판정이 비켜 가기 쉬운 철자 ──────────────────────────────────


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        # 빈 값은 false — `=` 없는 `-c <key>` 만 true
        ("git -c merge.ff= merge fix/x", "dev", True),
        ("git -c merge.ff merge --no-ff fix/x", "dev", True),
        ("git -c merge.ff merge fix/x", "dev", False),
        ("git -c pull.rebase= pull --no-ff origin fix/x", "dev", True),
        ("git -c pull.rebase pull --no-ff origin fix/x", "dev", False),
        ("git pull --rebase= --no-ff origin fix/x", "dev", True),
        ("git -c pull.rebase= pull --squash origin feature/x", "dev", False),
        ("git -c pull.rebase pull --squash origin feature/x", "dev", True),
        ("git pull --rebase= --squash origin feature/x", "dev", False),
        # 짧은 묶음 끝의 값 받는 글자는 다음 낱말을 먹음
        ("git merge -qm msg --no-ff fix/x", "dev", True),
        ("git merge -ns ort --no-ff fix/x", "dev", True),
        ("git merge -qX theirs stage", "main", True),
        ("git merge -mmsg --no-ff fix/x", "dev", True),
        ("git merge -qm msg --squash feature/x", "dev", False),
        ("git merge -qF msg.txt feature/x", "dev", True),
        ("git merge -nX theirs --squash feature/x", "dev", False),
        ("git merge -qmmsg feature/x", "dev", True),
        ("git merge -qS feature/x", "dev", True),
        # 인용이 쪼갠 switch 도 target 을 정함
        ("git sw''itch main && git merge stage", "dev", True),
        ("git chec''kout main && git merge stage", "dev", True),
        # 리비전 접미도 그 브랜치에서 온 커밋
        ("git merge stage^0", "main", True),
        ("git merge stage~1", "main", True),
        ("git merge --no-ff stage^0", "main", False),
        ("git merge stage@{1}", "main", True),
        ("git merge --no-ff stage^{commit}", "main", False),
        # 인용한 Windows 경로의 git — 큰따옴표 안 백슬래시는 bash 가 남김
        ("\"C:\\Git\\bin\\git.exe\" mer''ge --no-ff fix/x", "dev", True),
        ("\"C:\\Program Files\\Git\\bin\\git.exe\" mer''ge --no-ff fix/x", "dev", True),
        ("C:\\\\Git\\\\bin\\\\git.exe mer''ge --no-ff fix/x", "dev", True),
        # 인용이 쪼갠 프로그램 이름, 낱말 한가운데의 줄이음 — 피연산자 자리가 밀리면 안 됨
        ('"g"it merge --no-ff fix/x', "dev", True),
        ("'g'it merge --no-ff fix/x", "dev", True),
        ("git mer\\\nge --no-ff fix/x", "dev", True),
        ("git $\\\n'merge' --no-ff fix/x", "dev", True),
        ("gi\\\nt merge stage", "main", True),
        ("git merge stag\\\ne", "main", True),
        ("git merge --no-ff fix\\\n/x", "dev", True),
        ("git pull origin sta\\\nge", "main", True),
        # 낱말 사이에 홀로 선 줄이음은 공백일 뿐 — 낱말 하나로 세면 소스가 `merge` 가 됨
        ("git \\\n merge stage", "main", True),
        ("git \\\r\n merge stage", "main", True),
        ("git -c a=b \\\n merge stage", "main", True),
        ("git -C . \\\n merge stage", "main", True),
        ("git --no-pager \\\n merge stage", "main", True),
        ("git \\\n  merge \\\n  stage", "main", True),
        ("git \\\n switch main && git merge stage", "dev", True),
        ("git switch \\\n main && git merge stage", "dev", True),
        # ANSI-C 문자열이 서브커맨드·플래그·switch 피연산자를 철자
        ("git $'\\x6derge' --no-ff fix/x", "dev", True),
        ("git merge $'--no-\\x66f' fix/x", "dev", True),
        ("git switch $'d\\x65v' && git merge feature/x", "feature/x", True),
        # 어떤 글자도 아닌 코드 포인트는 적힌 그대로 — 예외면 머지의 낱말이 통째로 빔
        ("git merge --no-ff -m $'\\U7FFFFFFF' fix/x", "dev", True),
    ],
)
def test_spellings_git_merges_by(monkeypatch, tmp_path, command, branch, blocked):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


def test_a_short_bundle_hands_its_value_to_the_option():
    """`-qs ort` 의 `ort` 는 `-s` 의 값 — 소스·원격 자리로 읽으면 피연산자가 한 칸씩 밀림."""
    assert fgc.parse_pull_commands("git pull -qs ort origin feature/x") == [(set(), "feature/x")]
    assert fgc.parse_pull_commands("git pull -qrs origin feature/x") == [(set(), "feature/x")]
    assert fgc.parse_merge_commands("git merge -qm msg feature/x") == [(set(), "feature/x")]


@pytest.mark.parametrize(
    "piece",
    [
        "git switch dev && git merge --squash feature/x",
        "git merge --squash feature/x",
        "git pull --squash origin feature/x",
    ],
)
def test_the_verdict_stays_linear_in_the_number_of_merges(monkeypatch, tmp_path, piece):
    """머지마다 앞 switch 전부나 명령 처음부터의 `cd` 를 다시 읽으면 `머지 × 길이` 라 2차임 —
    100KB 에서 3~22초, 50KB 의 네 배 남짓이었음(실측). 지금은 0.4초 안팎.
    부하 아래 단일 측정이 튀므로 최선값으로 잼(2차는 어느 측정에서도 느림)."""
    import time

    import scripts._vway_paths as vp

    _write_policy(tmp_path)
    command = " && ".join([piece] * (100_000 // (len(piece) + 4)))
    runs = []
    for _ in range(3):
        vp._shell_regions.cache_clear()
        vp._blanked_view.cache_clear()
        fgc._cd_chain.cache_clear()
        started = time.perf_counter()
        assert _run_merge_check(monkeypatch, tmp_path, command, "dev") == 0
        runs.append(time.perf_counter() - started)
    assert min(runs) < 2.0, f"{piece!r}: {min(runs):.2f}s — 선형이면 1초 안쪽: {runs}"


@pytest.mark.parametrize("spec", ["main~0", "main^0", "main@{1}"])
def test_a_checkout_of_a_revision_is_no_target(monkeypatch, tmp_path, spec):
    """리비전으로 checkout 하면 HEAD 가 떨어져 나가 main 에 머지하지 않음 — 접미를 벗겨 main
    으로 읽으면 stage → main 행으로 오차단함(실측: 실제 git 은 detached HEAD 에서 ff)."""
    _write_policy(tmp_path)
    command = f"git checkout {spec} && git merge stage"
    assert _run_merge_check(monkeypatch, tmp_path, command, "dev") == 0


def _python_less_bash(tmp_path: Path) -> tuple[str, str] | None:
    """(bash, PATH) — python3 이 안 보이는 셸. 못 만들면 None.

    Windows 는 Git 의 `usr/bin/bash.exe` 를 직접 띄움: `bin/bash.exe` 래퍼는 PATH 앞에
    `/usr/bin` 을 다시 얹어 스텁을 가림. POSIX 는 러너가 의존성 검사 전에 쓰는 도구만
    링크한 디렉터리를 PATH 로 줌."""
    import shutil

    if sys.platform == "win32":
        bash = r"C:\Program Files\Git\usr\bin\bash.exe"
        path = "/usr/bin"
        if not Path(bash).exists():
            return None
    else:
        bash = shutil.which("bash")
        if not bash:
            return None
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for tool in ("timeout", "cat"):
            found = shutil.which(tool)
            if not found:
                return None
            (bin_dir / tool).symlink_to(found)
        path = str(bin_dir)
    probe = run_bounded(
        [bash, "--noprofile", "--norc", "-c", "command -v python3"],
        env={**os.environ, "PATH": path},
    )
    return None if probe.returncode == 0 else (bash, path)


@pytest.mark.parametrize(
    "command,code",
    [
        ("git pull origin stage", 0),
        ("git merge --no-ff stage", fgc.BLOCK_EXIT_CODE),
        ("git commit -m x", fgc.BLOCK_EXIT_CODE),
        # `$` 옆 백슬래시는 분류기를 띄우지만 의존성 차단에는 안 걸림 — 흔한 모양이라
        ('printf "$HOME\\n"', 0),
        ("git $'\\x63ommit' -m x", fgc.BLOCK_EXIT_CODE),
    ],
)
def test_a_pull_is_not_blocked_on_a_host_without_python(tmp_path, command, code):
    """python3 없는 호스트에서 의존성 차단은 커밋·머지(`$'…'` 포함)에만 — pull 낱말이나 `$`
    옆 백슬래시만 든 명령까지 걸면 그 호스트의 `git pull`·`printf` 가 전부 막힘(실측: 이
    갈래 전 러너 exit 2)."""
    shell = _python_less_bash(tmp_path)
    if shell is None:
        pytest.skip("python3 이 안 보이는 bash 를 만들 수 없음")
    bash, path = shell
    runner = Path(__file__).resolve().parents[2] / "scripts" / "precommit-runner.sh"
    payload = json.dumps({"tool_input": {"command": command}})
    r = run_bounded(
        [bash, "--noprofile", "--norc", runner.as_posix()],
        input=payload,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PATH": path},
    )
    assert r.returncode == code, (r.returncode, r.stdout, r.stderr)
