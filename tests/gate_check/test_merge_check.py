"""`--merge-check` 판정 — 규칙이 요구·금지하는 플래그를 실제로 막는가.

명령 하나에 머지가 여럿이면 **전부** 판정. 축약 플래그도 세고, 플래그와 그 부정이
함께 서면 승자를 모르므로 require·forbid 양쪽에서 막음.
"""

import json
import sys
import time
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import (
    ABBREVIATED_FLAGS,
    MERGE_SPELLINGS,
    _run_merge_check,
    _write_policy,
)


@pytest.mark.parametrize("command", MERGE_SPELLINGS, ids=range(len(MERGE_SPELLINGS)))
def test_the_merge_verdict_reads_every_spelling_classify_reports(
    monkeypatch, tmp_path: Path, command: str
):
    _write_policy(tmp_path)
    assert fgc.is_invocation(command, "merge"), command  # 분류는 이미 merge 라 답함
    assert _run_merge_check(monkeypatch, tmp_path, command, "dev") == fgc.BLOCK_EXIT_CODE, command


def test_the_last_of_two_opposing_flags_wins(monkeypatch, tmp_path: Path):
    """git 은 나중에 선 철자를 택함 — 판정도 그 순서로 읽음.

    `git merge --squash --no-squash feature/x` 는 실제 git 에서 squash 가 아니라 평범한
    머지를 만듦(실측: 부모 1개) — `--squash` 를 들었다고 읽으면 require 가 헛돎. 반대 순서는
    squash 이므로 막으면 정상 명령을 오차단함.
    """
    _write_policy(tmp_path)
    for command, blocked in (
        ("git merge --squash --no-squash feature/x", True),
        ("git merge --no-squash --squash feature/x", False),
        ("git merge --squash feature/x", False),
        # fast-forward 모드 셋도 한 묶음: `--ff` 는 `--ff-only` 의 축약이 아님.
        ("git merge --no-ff --ff fix/x", False),
        ("git merge --no-ff --ff-only fix/x", False),
        ("git merge --ff-only --no-ff fix/x", True),
    ):
        code = _run_merge_check(monkeypatch, tmp_path, command, "dev")
        assert (code == fgc.BLOCK_EXIT_CODE) is blocked, command


def test_a_flag_that_takes_a_name_does_not_eat_the_source(monkeypatch, tmp_path: Path):
    """`--into-name` 을 안 건너뛰면 그 이름이 소스 자리를 먹어 규칙이 매칭되지 않음."""
    _write_policy(tmp_path)
    assert fgc.parse_merge_command("git merge --into-name dev feature/x -m m") == (
        set(),
        "feature/x",
    )
    assert (
        _run_merge_check(monkeypatch, tmp_path, "git merge --into-name dev feature/x", "dev")
        == fgc.BLOCK_EXIT_CODE
    )


@pytest.mark.parametrize("count", [800, 1600], ids=["k800", "k1600"])
def test_reading_many_merges_stays_linear(count: int):
    """`operand_words` 는 머지 **하나마다** 불림. 그때마다 구간을 처음부터 훑어 판을
    다시 만들면 `머지 × 구간` 이라 2차 — 줄이음 든 머지 1600 개(37KB)에서 924ms 대
    57.6ms 를 실측했고, 배가마다 앞은 4배 뒤는 2배. 훅에서의 2차는 타임아웃이고,
    타임아웃은 판정을 건너뛰는 것과 같음."""

    nl = chr(10)
    command = ("git merge \\" + nl + " feature/x" + nl) * count
    fgc.mask_literals(command)  # 마스크는 두 판이 공유 — 재는 것은 그 뒤
    started = time.perf_counter()
    fgc.parse_merge_commands(command)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25, f"k={count}: {elapsed:.3f}s — 선형이면 수십 ms 다"


def test_a_cd_after_the_merge_does_not_exempt_it(tmp_path: Path):
    """선행 `cd` 만 그 머지를 저쪽으로 옮김 — 뒤에 오는 `cd` 는 이 머지와 무관."""
    other = tmp_path.parent / "other-wt"
    assert fgc._points_elsewhere(f"git merge --no-ff fix/x && cd {other} && :", tmp_path) is False
    assert fgc._points_elsewhere(f"cd {other} && git merge --no-ff fix/x", tmp_path) is True


def test_a_merge_elsewhere_does_not_exempt_its_siblings(monkeypatch, tmp_path: Path):
    """저쪽 디렉터리 판정은 **머지마다**임 — 명령 하나로 답하면 앞의 하나가 뒤를 다 면제함.

    `-C` 는 그 호출만의 전역 옵션이라 뒤 머지는 여전히 이쪽 root 에서 돎(실측: exit 2 → 0).
    선행 `cd` 는 그 뒤 전부에 걸리므로 그때는 둘 다 면제되는 것이 맞음.
    """
    _write_policy(tmp_path)
    other = tmp_path.parent / "other-wt"
    assert (
        _run_merge_check(
            monkeypatch, tmp_path, f"git -C {other} merge feature/x && git merge stage", "main"
        )
        == fgc.BLOCK_EXIT_CODE
    )
    # 선행 cd 뒤의 머지는 전부 저쪽 → FAIL-OPEN.
    assert (
        _run_merge_check(
            monkeypatch, tmp_path, f"cd {other} && git merge feature/x && git merge stage", "main"
        )
        == 0
    )
    # 이쪽 머지만 남으면 그것만 판정.
    assert (
        _run_merge_check(
            monkeypatch, tmp_path, f"git merge stage && git -C {other} merge feature/x", "main"
        )
        == fgc.BLOCK_EXIT_CODE
    )


@pytest.mark.parametrize(
    "command,branch,blocked", ABBREVIATED_FLAGS, ids=[c for c, _b, _x in ABBREVIATED_FLAGS]
)
def test_an_abbreviated_flag_counts_as_the_flag(
    monkeypatch, tmp_path: Path, command: str, branch: str, blocked: bool
):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


def test_a_reserved_word_before_the_merge_does_not_lose_the_verdict(monkeypatch, tmp_path: Path):
    """`if`·`case` 갈래 안의 머지도 판정 — 피연산자를 온전히 읽을 수 있음."""
    _write_policy(tmp_path)
    for command in (
        "if git merge --no-ff fix/x; then :; fi",
        "case x in x) git merge --no-ff fix/x;; esac",
        "while git merge --no-ff fix/x; do break; done",
        "git merge \\\r\n --no-ff fix/x",
    ):
        assert _run_merge_check(monkeypatch, tmp_path, command, "dev") == fgc.BLOCK_EXIT_CODE, repr(
            command
        )


def test_merge_check_blocks_missing_squash(monkeypatch, tmp_path: Path, capsys):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge feature/x", "dev")
    assert code == fgc.BLOCK_EXIT_CODE
    # 차단 사유는 stdout — 셸이 인터프리터 오류(stderr)와 격리해 캡처한다(H3)
    assert "--squash" in capsys.readouterr().out


def test_merge_check_allows_squash(monkeypatch, tmp_path: Path):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge --squash feature/x", "dev")
    assert code == 0


def test_merge_check_blocks_missing_no_ff(monkeypatch, tmp_path: Path):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge origin/stage", "main")
    assert code == fgc.BLOCK_EXIT_CODE


def test_merge_check_allows_no_ff(monkeypatch, tmp_path: Path):
    _write_policy(tmp_path)
    code = _run_merge_check(
        monkeypatch, tmp_path, 'git merge --no-ff -m "Merge stage: x" origin/stage', "main"
    )
    assert code == 0


def test_merge_check_blocks_switch_then_merge(monkeypatch, tmp_path: Path, capsys):
    # HEAD 는 아직 **소스** 브랜치(feature/x) — target 은 명령어에서 와야 함.
    _write_policy(tmp_path)
    code = _run_merge_check(
        monkeypatch, tmp_path, "git switch dev && git merge feature/x", "feature/x"
    )
    assert code == fgc.BLOCK_EXIT_CODE
    assert "--squash" in capsys.readouterr().out


def test_merge_check_allows_switch_then_squash_merge(monkeypatch, tmp_path: Path):
    _write_policy(tmp_path)
    code = _run_merge_check(
        monkeypatch, tmp_path, "git switch dev && git merge --squash feature/x", "feature/x"
    )
    assert code == 0


def test_merge_check_other_worktree_fails_open(monkeypatch, tmp_path: Path):
    # worktree 가 `stage` 에 있는 채로 `git -C <wt> merge feature/x`: 소스는 명령어에서 오지만
    # target 은 **이쪽** root(dev)에서 읽혀, 규칙조차 없는 flow(feature/* → stage)에 대해
    # feature/* → dev 위반을 지어냄. FAIL-OPEN 불변식이 **차단 방향**으로 깨지는 유일한
    # 지점이므로, 무관한 -C 디렉터리는 exit 0 이어야 함.
    _write_policy(tmp_path)
    code = _run_merge_check(
        monkeypatch, tmp_path, f"git -C {tmp_path / 'other-wt'} merge feature/x", "dev"
    )
    assert code == 0


def test_merge_check_dash_c_on_this_root_still_enforced(monkeypatch, tmp_path: Path):
    # …하지만 게이트가 도는 root 자신을 가리키는 `-C` 는 다른 worktree 를 지목하지 않음 —
    # 여기서 읽은 브랜치가 곧 merge target 이므로 강제를 통째로 내주면 안 됨.
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, f"git -C {tmp_path} merge feature/x", "dev")
    assert code == fgc.BLOCK_EXIT_CODE


def test_merge_check_unclear_switch_before_merge_fails_open(monkeypatch, tmp_path: Path):
    # `git switch -c feature/y && git merge feature/x`: 훅 시점 HEAD 는 dev 지만, 명령이
    # feature/y 를 새로 만들어 거기로 옮긴 뒤 머지함. 그 flow 를 다루는 규칙은 없음. 불명확한
    # switch 로 target 을 못 읽었다고 stale HEAD(dev)로 폴백하면 일어나지도 않는 머지를 차단.
    _write_policy(tmp_path)
    code = _run_merge_check(
        monkeypatch, tmp_path, "git switch -c feature/y && git merge feature/x", "dev"
    )
    assert code == 0


def test_merge_check_blocks_a_plain_promotion_to_staging(monkeypatch, tmp_path: Path, capsys):
    """강제 범프의 `[skip ci]` 는 머지 커밋에만 앉을 수 있음 — rebase·FF 승격은 그 자리를
    만들지 않아 CI 가 auto 로 발화하고 고른 레벨이 사라짐."""
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge dev", "stage")
    assert code == 2
    assert "--no-ff" in capsys.readouterr().out


def test_merge_check_allows_a_no_ff_promotion_to_staging(monkeypatch, tmp_path: Path):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge --no-ff dev", "stage")
    assert code == 0


def test_merge_check_no_rule_fails_open(monkeypatch, tmp_path: Path):
    # main → dev 백머지에는 규칙이 없음
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge main", "dev")
    assert code == 0


def test_merge_check_absent_policy_fails_open(monkeypatch, tmp_path: Path):
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-tiers.yaml").write_text("tiers:\n  dev:\n    gates: []\n", encoding="utf-8")
    code = _run_merge_check(monkeypatch, tmp_path, "git merge feature/x", "dev")
    assert code == 0


def test_merge_check_detached_head_fails_open(monkeypatch, tmp_path: Path):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge feature/x", None)
    assert code == 0


def test_merge_check_not_a_merge_fails_open(monkeypatch, tmp_path: Path):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge-base --is-ancestor a b", "dev")
    assert code == 0


def test_merge_check_warns_when_not_rebased(monkeypatch, tmp_path: Path, capsys):
    import io

    _write_policy(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(fgc, "_current_branch", lambda root: "dev")
    monkeypatch.setattr(fgc, "_is_rebased", lambda root, source, target: False)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"tool_input": {"command": "git merge --squash feature/x"}})),
    )
    with pytest.raises(SystemExit) as exc:
        fgc.merge_check_output()
    assert exc.value.code == 0  # 경고는 절대 차단하지 않음
    # 경고는 stdout 의 systemMessage — 러너가 사용자에게 보이는 유일한 필드로 넘김
    assert "rebase" in json.loads(capsys.readouterr().out)["systemMessage"]
