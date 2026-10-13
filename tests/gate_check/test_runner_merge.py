"""셸 러너 e2e — 머지 경로.

`git merge` 는 `git status` 조기 종료 **앞에서** 분기함(깨끗한 트리에서도 판정해야
함). 커밋과 머지가 한 명령에 함께 서면 둘 다 게이트에 닿아야 함.
"""

import json
import os
from pathlib import Path

import scripts.vdev_gate_check as fgc
from tests._proc import run_bounded
from tests.gate_check._helpers import (
    _REPO_BASH,
    _classify_worktree_module,
    _init_repo,
    _merge_repo,
    _rg,
    _run_runner,
    requires_bash_git,
)

# 이 저장소가 실제로 배포하는 vdev-tiers.yaml 의 merge_strategy 에 기댄다(staging → production
# 은 --no-ff 필수 — rules/merge-strategy.md 참조). _run_runner 가 CLAUDE_PLUGIN_ROOT 를
# 이 저장소로 가리키고, tiers_path() 가 CLAUDE_PLUGIN_ROOT/vdev-tiers.yaml 을 호스트 config
# 사본보다 우선하므로, 실제 정책이 e2e 로 검증된다(dogfooding).


@requires_bash_git
def test_runner_merge_gate_survives_clean_tree(tmp_path: Path):
    # `git status` 조기 종료 함정의 회귀 방어: 머지는 정의상 **깨끗한** 트리에서 돌기 때문에,
    # merge 분기가 그 조기 종료 뒤에 있거나 아예 없으면 차단 대신 아무 출력 없이 exit 0 됨.
    main = tmp_path / "main"
    _init_repo(main)  # 브랜치 "main", 깨끗한 트리
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    # config 를 커밋해 머지 직전 트리를 진짜로 깨끗하게 만듦(실팀도 그러함 — vdev-config.yaml
    # 은 /vdev-init 규약상 git 추적됨). untracked 로 두면 트리가 더러워져 무관한 게이트가
    # 먼저 막고, merge 분기가 실제로 조기 종료 앞에서 도는지가 가려짐.
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, "git merge origin/stage")  # 필수 --no-ff 누락
    assert r.returncode == fgc.BLOCK_EXIT_CODE
    assert "--no-ff" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_survives_a_switch_after_the_merge(tmp_path: Path):
    # 머지 **뒤**에 붙은 switch 는 이 머지의 target 이 아님. 그런데 "불명확한 switch 가 있으면
    # HEAD 폴백을 쓰지 않는다" 규칙의 범위를 명령 전체로 두면, 뒤에 switch 하나 붙이는 것만으로
    # merge 전략 판정이 통째로 exit 0 함 — merge 전략 위반은 fail-CLOSED 예외(Invariant #1
    # 예외 3)인데도 조용히 열림. 단위 테스트는 `_target_from_command` 가 None 이라는 것까지만
    # 재므로, 그 다음에도 판정이 도는지는 러너를 실제로 돌려야 보임.
    main = tmp_path / "main"
    _init_repo(main)  # 브랜치 main = production
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    for tail in ("&& git switch main", "&& git checkout -b tmp", "; git checkout -- ."):
        r = _run_runner(main, f"git merge origin/stage {tail}")  # 필수 --no-ff 누락
        assert r.returncode == fgc.BLOCK_EXIT_CODE, (tail, r.returncode, r.stdout, r.stderr)
        assert "--no-ff" in (r.stdout + r.stderr), tail


@requires_bash_git
def test_runner_merge_gate_sees_a_quoted_path_with_a_space(tmp_path: Path):
    # `_merge_re` 전면 되돌림을 잡는 유일한 bash 경로. test_skills 의 가드는 ERE 를 파이썬
    # 으로 번역해 재는데, POSIX 클래스는 로캘 의존이라 번역이 무손실이 아님 — 실제 셸로
    # 한 번은 재야 함.
    main = tmp_path / "My Project"
    main.mkdir()
    main = main / "repo"
    _init_repo(main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, f'git -C "{main.as_posix()}" merge origin/stage')  # --no-ff 누락
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (r.returncode, r.stdout, r.stderr)
    assert "--no-ff" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_sees_a_path_glued_from_a_quoted_piece(tmp_path: Path):
    # 셸 self-filter 는 붙은 경로의 `git -C … merge` 를 머지로 넘기는데, 파이썬 파서가 그
    # 인자를 못 읽으면 소스 없이 돌아와 조용히 exit 0 함 — 두 레이어가 어긋나면
    # fail-CLOSED 여야 할 판정이 통째로 사라짐. 레이어를 가로질러 재는 e2e.
    # 경로는 root 자신으로 resolve 되는 `"."/.` 를 씀: 다른 디렉터리를 가리키면 merge 는
    # 정의상 fail-open 이라, 이 테스트가 재려는 것이 아니라 그 규칙을 재게 됨.
    main = tmp_path / "main"
    _init_repo(main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, 'git -C "."/. merge stage')  # 필수 --no-ff 누락
    assert r.returncode == fgc.BLOCK_EXIT_CODE
    assert "--no-ff" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_reads_switch_target_from_command(tmp_path: Path):
    # `git switch <integration> && git merge feature/x` — merge-strategy 의 "Merging feature/* →
    # integration" 이 규정한 바로 그 관용구이고 Claude Code 는 이를 한 번의 Bash 호출로 보냄.
    # 훅 시점 HEAD 는 아직 feature/x 라, target 을 HEAD 에서 읽으면 어떤 규칙도 매칭되지 않아
    # 정책이 문서화한 관용구가 그대로 게이트를 통과함(exit 0).
    main = tmp_path / "main"
    _init_repo(main)
    _rg(["checkout", "-b", "feature/x"], main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text("branches:\n  integration: dev\n", encoding="utf-8")
    _rg(["add", "-A"], main)  # 실제 머지처럼 깨끗한 트리(vdev-config 는 추적 대상)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, "git switch dev && git merge feature/x")  # --squash 누락
    assert r.returncode == fgc.BLOCK_EXIT_CODE
    assert "--squash" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_reads_a_newline_separated_switch_target(tmp_path: Path):
    # 위와 같은 관용구를 merge-strategy 가 실제로 인쇄하는 모양대로: `&&` 없이 3**줄**.
    # 단위 테스트만으로는 부족했던 전례가 있어 e2e 로 둠 — merge 스위트 전체가 `&&` 로
    # 작성돼 있어서, `\n` 이 빠진 구분자 클래스가 수백 개 테스트를 통과하면서도 개행으로
    # 나뉜 모든 merge 를 게이트 밖으로 흘려보냄. 여기서는 정책이 요구하는 `--squash` 가
    # 없으므로, 침묵(exit 0)은 게이트가 머지를 보지 못했다는 뜻임.
    main = tmp_path / "main"
    _init_repo(main)
    _rg(["checkout", "-b", "feature/x"], main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text("branches:\n  integration: dev\n", encoding="utf-8")
    # 머지는 정의상 깨끗한 트리에서 돌아감. config 를 커밋하지 않으면 무관한 게이트가 먼저 막고
    # merge 판정을 가림(이 브랜치가 실제로 그것에 걸린 적이 있음).
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, "git switch dev\ngit pull --ff-only origin dev\ngit merge feature/x")
    assert r.returncode == fgc.BLOCK_EXIT_CODE
    assert "--squash" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_fires_when_command_also_commits(tmp_path: Path):
    # `git merge X && git commit -m …`(squash-merge 관용구): 명령이 커밋이기도 하다는 이유로
    # merge 검사가 스킵되면 안 됨. 커밋으로만 게이팅하면 exit 0 이 됨 — merge 판정을 아예
    # 묻지 않고, 커밋 경로는 깨끗한 트리에서 조기 종료함.
    main = tmp_path / "main"
    _init_repo(main)
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, 'git merge origin/stage && git commit -m "x"')  # --no-ff 누락
    assert r.returncode == fgc.BLOCK_EXIT_CODE
    assert "--no-ff" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_and_commit_both_reach_the_commit_gate(tmp_path: Path):
    # 같은 수정의 반대쪽: 정책을 위반하지 않는 머지는 merge 분기에서 exit 0 하지 말고 커밋
    # 게이트로 **떨어져야** 함. 여기서는 어떤 규칙도 매칭되지 않으므로(branches 미설정 →
    # fail-open) 커밋 경로가 모듈 사전검사를 계속 돌려야 함 — `echo LINT_RAN` 이 그 증거.
    main = tmp_path / "main"
    _init_repo(main)
    _rg(["checkout", "-b", "feature/x"], main)
    _classify_worktree_module(main)  # tier 마커 + 증거 + 모듈 하나, staged 파일
    r = _run_runner(main, 'git merge feature/y && git commit -m "x"')
    assert "echo LINT_RAN" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_ignores_a_checkout_pathspec(tmp_path: Path):
    # `git checkout <branch> -- <path>` 는 **파일**을 복원함. HEAD 는 움직이지 않음. 여기서
    # `dev` 를 target 으로 읽으면 일어나지도 않는 feature/* → integration flow 를 지어내
    # 정당한 명령을 차단함(exit 2 로 --squash 요구). 피연산자 형태를 불명확으로 판정해야
    # 훅 시점 브랜치(feature/x)가 유지되고, 거기엔 매칭되는 규칙이 없어 exit 0 이 됨.
    main = _merge_repo(tmp_path, branch="feature/x", config="branches:\n  integration: dev\n")
    r = _run_runner(main, "git checkout dev -- README.md && git merge feature/x")
    assert r.returncode == 0
    assert "--squash" not in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_bails_when_a_later_switch_is_unclear(tmp_path: Path):
    # `git switch dev && git switch -c feature/y && git merge feature/x` 는 HEAD 가 feature/y 로
    # 끝나고 어떤 규칙도 이를 다루지 않음. 마지막 *매칭되는* switch 를 취하면 낡은 `dev` 를
    # 채택해 정책이 관장하지도 않는 머지를 차단함 — 불명확한 switch 하나가 체인 전체를
    # 무효화해야 함.
    main = _merge_repo(tmp_path, branch="feature/x", config="branches:\n  integration: dev\n")
    r = _run_runner(main, "git switch dev && git switch -c feature/y && git merge feature/x")
    assert r.returncode == 0
    assert "--squash" not in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_fails_open_on_a_cd_into_another_worktree(tmp_path: Path):
    # `cd <worktree> && git merge X` 는 `git -C <worktree> merge X` 의 나머지 반쪽: 소스는
    # 명령어에서 오는데 target 은 **이쪽** root 에서 읽혀, 일어나지도 않는 flow 를 지목함.
    # `-C` 형태만 막으면 이쪽이 계속 차단(exit 2 로 --squash 요구)하므로 — merge 경로는
    # worktree 를 재지정할 수 없음(Invariant "worktree 재지정은 커밋 경로 전용") — fail-open 함.
    main = _merge_repo(tmp_path, branch="dev", config="branches:\n  integration: dev\n")
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "stage", str(wt)], main)
    r = _run_runner(main, f"cd {wt} && git merge feature/x")
    assert r.returncode == 0
    assert "--squash" not in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_survives_an_unrelated_dash_c(tmp_path: Path):
    # `-C` 가 디렉터리를 뜻하는 것은 git 자신의 전역 옵션일 때뿐임. 명령 어디서나 매칭하면
    # 무관한 `-C`(grep 문맥 줄, gcc, …)가 외부 디렉터리로 해석돼 merge 게이트 전체를 꺼버림 —
    # 토큰 하나로 정책 전체를 우회하는 셈임.
    main = _merge_repo(
        tmp_path, branch=None, config="branches:\n  staging: stage\n  production: main\n"
    )
    r = _run_runner(main, "grep -C 3 foo README.md && git merge origin/stage")  # --no-ff 누락
    assert r.returncode == fgc.BLOCK_EXIT_CODE
    assert "--no-ff" in (r.stdout + r.stderr)


@requires_bash_git
def test_runner_merge_gate_fails_open_when_gate_script_is_missing(tmp_path: Path):
    # 깨진 CLAUDE_PLUGIN_ROOT → `python3 <없는경로>/vdev_gate_check.py` 가 "can't open file"
    # 로 exit 2 를 냄. 그 인터프리터 오류가 차단 사유가 되면 Invariant #1(내부 오류는
    # 게이트를 막지 않음) 위반임. 차단 사유는 stdout, 인터프리터 오류는 stderr 이므로
    # 사유 채널(stdout)이 비어 fail-open 해야 함. 대조: 커밋 경로는 이미 이렇게 동작함.
    repo = Path(__file__).resolve().parent.parent.parent
    main = _merge_repo(tmp_path, branch="dev", config="branches:\n  integration: dev\n")
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(main),
        "CLAUDE_PLUGIN_ROOT": (tmp_path / "nonexistent-plugin").as_posix(),
        "VWAY_PRECOMMIT_DRYRUN": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    hook = json.dumps({"cwd": str(main), "tool_input": {"command": "git merge feature/x"}})
    r = run_bounded(
        [_REPO_BASH, f"{repo.as_posix()}/scripts/precommit-runner.sh"],
        input=hook,
        env=env,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, f"인터프리터 오류가 차단이 됐다: {r.stdout} {r.stderr}"


@requires_bash_git
def test_runner_does_not_deny_a_read_only_command_that_merely_says_commit(tmp_path: Path):
    # 옵션 토큰이 공백을 넘으면(한 문자열의 닫는 따옴표가 뒤 문자열의 여는 따옴표와 짝지어짐)
    # `git … log` 가 커밋으로 읽혀 미분류라는 이유로 차단됨 — 읽기 전용 명령에 대한
    # fail-CLOSED 오작동임. 두 레이어를 가로질러 실제 exit 코드로 측정.
    main = tmp_path / "main"
    _init_repo(main)
    (main / "dirty.py").write_text("x = 1\n", encoding="utf-8")  # 트리를 더럽혀 조기 종료를 지남
    _rg(["add", "-A"], main)
    dq = chr(34)
    read_only = f"git -c a='b{dq}c' log && echo {dq}please commit{dq}"
    r = _run_runner(main, read_only)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_does_not_judge_a_commit_message_as_a_merge(tmp_path: Path):
    # skills/commit 이 출하하는 커밋은 메시지를 heredoc 으로 만들어 파이프하고, 이 repo 의
    # 메시지는 머지 규율을 상시 인용함. 본문의 `git merge origin/stage` 를 호출로 읽으면
    # 커밋이 merge_strategy(staging → production 은 --no-ff 필수)로 심사돼, 일어나지도 않은
    # 머지 때문에 차단됨. 셸 self-filter 는 ERE 라 이 명령을 계속 머지로 넘기므로, 판정을
    # 끊는 곳은 파이썬 파서뿐임 — 그래서 레이어를 가로질러 재야 함.
    main = tmp_path / "main"
    _init_repo(main)  # 브랜치 main = production
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    (main / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "-A"], main)
    command = "\n".join(
        [
            "msg=$(cat <<'EOF'",
            "fix(gate): x",
            "",
            "git merge origin/stage 를 쓰지 마라.",
            "EOF",
            ")",
            'printf %s "$msg" | git commit -F -',
        ]
    )
    r = _run_runner(main, command)
    assert "--no-ff" not in (r.stdout + r.stderr), (r.returncode, r.stdout, r.stderr)


@requires_bash_git
def test_runner_ignores_non_commit_non_merge_command(tmp_path: Path):
    # `git status` 는 커밋도 머지도 아님 — 손대지 않고 통과해야 함(exit 0, 게이트 출력 없음).
    # 두 플래그 self-filter 가 발동 범위를 넓히지 않았음을 증명함.
    main = tmp_path / "main"
    _init_repo(main)
    r = _run_runner(main, "git status")
    assert r.returncode == 0
    assert r.stdout.strip() == ""
    assert r.stderr.strip() == ""
