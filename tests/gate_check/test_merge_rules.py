"""브랜치 흐름 → 머지 전략 규칙 매칭.

`vdev-config.branches` 의 키와 `feature/*` 류 glob 이 규칙의 양끝을 지목함.
`origin/` 접두는 벗겨 읽고, 어느 규칙에도 안 걸리면 판정하지 않음(FAIL-OPEN).
"""

from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from scripts.vdev_gate_check import (
    _branch_matches,
    match_merge_rule,
    parse_merge_command,
)
from tests.gate_check._helpers import (
    BRANCHES,
    MULTI_MERGE,
    RULES,
    _run_merge_check,
    _write_policy,
)


def test_branch_matches_prefix_glob():
    assert _branch_matches("feature/*", "feature/merge-gate", BRANCHES) is True
    assert _branch_matches("feature/*", "fix/typo", BRANCHES) is False


def test_branch_matches_config_key():
    assert _branch_matches("integration", "dev", BRANCHES) is True
    assert _branch_matches("integration", "stage", BRANCHES) is False
    assert _branch_matches("production", "main", BRANCHES) is True


def test_branch_matches_strips_origin_prefix():
    assert _branch_matches("staging", "origin/stage", BRANCHES) is True


def test_branch_matches_unknown_key_is_false():
    assert _branch_matches("nonesuch", "dev", BRANCHES) is False


def test_match_rule_feature_to_integration():
    rule = match_merge_rule(RULES, "feature/x", "dev", BRANCHES)
    assert rule is not None
    assert rule["require"] == "--squash"


def test_match_rule_staging_to_production():
    rule = match_merge_rule(RULES, "origin/stage", "main", BRANCHES)
    assert rule is not None
    assert rule["require"] == "--no-ff"


def test_match_rule_fix_to_integration():
    rule = match_merge_rule(RULES, "fix/typo", "dev", BRANCHES)
    assert rule is not None
    assert rule["forbid"] == "--no-ff"


def test_match_rule_integration_to_staging():
    rule = match_merge_rule(RULES, "dev", "stage", BRANCHES)
    assert rule is not None and rule.get("require") == "--no-ff"


def test_match_rule_no_match_returns_none():
    # main → dev 백머지에는 규칙이 없음
    assert match_merge_rule(RULES, "main", "dev", BRANCHES) is None


def test_match_rule_empty_rules_returns_none():
    assert match_merge_rule([], "feature/x", "dev", BRANCHES) is None


@pytest.mark.parametrize("command,expected", MULTI_MERGE, ids=[c for c, _ in MULTI_MERGE])
def test_every_merge_that_names_a_source_is_parsed(command: str, expected: list):
    assert fgc.parse_merge_commands(command) == expected
    # 옛 단수 API 는 첫 번째를 돌려줌 — 호출측 계약이 바뀌지 않음.
    assert parse_merge_command(command) == expected[0]


def test_a_merge_operand_survives_a_line_continuation_and_a_quoted_message():
    # 마스크는 줄이음을 이은 것으로 읽지만, 원본 조각을 그대로 shlex 에 넘기면 리터럴 개행이
    # 토큰이 되어 소스 자리로 샘.
    joined = "git merge " + chr(92) + chr(10) + "  --no-ff stage"
    assert parse_merge_command(joined) == ({"--no-ff"}, "stage")
    # 메시지 안의 플래그는 이 머지의 플래그가 아님.
    assert parse_merge_command("git merge -m 'merge --no-ff' stage") == (set(), "stage")
    # 주석에 적힌 플래그도 아님.
    assert parse_merge_command("git merge stage # --no-ff") == (set(), "stage")


def test_operand_words_reads_the_words_the_shell_splits():
    from scripts import _vway_paths as vp

    command = 'git merge -m "a; b" feature/x && echo done'
    masked = vp.mask_literals(command)
    at = command.index("-m")
    end = vp.operand_end(command, masked, at)
    assert vp.operand_words(command, masked, at, end) == ["-m", "a; b", "feature/x"]
    # 짝 없는 따옴표는 예외가 아니라 빈 목록임 — 예외가 새면 "여기 merge 없음"으로 읽혀
    # fail-CLOSED 판정이 통째로 사라짐.
    broken = 'git merge -m "unbalanced'
    assert vp.operand_words(broken, vp.mask_literals(broken), 10, len(broken)) == []


def test_merge_check_blocks_the_second_merge_when_the_first_one_passes(
    monkeypatch, tmp_path: Path, capsys
):
    """정책이 허용하는 머지가 앞에 서도 그 뒤가 판정됨 — 한 줄로 게이트를 끄는 자리."""
    _write_policy(tmp_path)
    code = _run_merge_check(
        monkeypatch, tmp_path, "git merge --squash feature/x && git merge origin/stage", "main"
    )
    assert code == fgc.BLOCK_EXIT_CODE
    assert "--no-ff" in capsys.readouterr().out


def test_merge_check_still_blocks_when_a_sourceless_merge_comes_first(monkeypatch, tmp_path: Path):
    """`--abort` 는 소스를 지목하지 않음. 그 하나가 뒤 머지 전체를 미판정으로 만듦."""
    _write_policy(tmp_path)
    code = _run_merge_check(
        monkeypatch, tmp_path, "git merge --abort && git merge origin/stage", "main"
    )
    assert code == fgc.BLOCK_EXIT_CODE


def test_a_switch_after_the_merges_does_not_silence_the_verdict(monkeypatch, tmp_path: Path):
    """머지 **뒤**의 switch 는 그 머지의 target 이 아님 — 판정을 끄지 않음.

    끄면 `git merge X && git merge Y && git switch dev` 한 줄로 전략 게이트가
    통째로 꺼짐 — `_switch_targets` 의 독스트링이 금지하는 바로 그 경로이고, 머지가
    둘이라는 것 말고는 다를 게 없음(실측: 러너 exit 2 → 0). merge 전략 위반은 fail-CLOSED
    예외(Invariant #1 예외 3)다.
    """
    _write_policy(tmp_path)
    for command in (
        "git merge feature/x && git merge feature/y && git switch dev",
        "git merge feature/x && git merge main && git checkout dev",
        "git merge feature/x && git switch dev",
        "git merge feature/x",
    ):
        assert _run_merge_check(monkeypatch, tmp_path, command, "dev") == fgc.BLOCK_EXIT_CODE, (
            command
        )


def test_a_switch_between_merges_sets_only_the_later_target(monkeypatch, tmp_path: Path):
    """머지 **사이**의 switch 뒤 머지는 target 이 그 switch 임. 앞 머지의 target 으로 심사하면
    정책에 없는 flow 를 차단하며 틀린 해법까지 지시함(실측). 앞 머지는 자기 target 으로
    그대로 판정함."""
    _write_policy(tmp_path)
    # 앞 머지는 정책을 만족하고, 뒤 머지(feature/y → stage)는 규칙이 없음 → 통과.
    assert (
        _run_merge_check(
            monkeypatch,
            tmp_path,
            "git switch dev && git merge --squash feature/x"
            " && git switch stage && git merge feature/y",
            "dev",
        )
        == 0
    )
    # 앞 머지가 위반이면 뒤 머지와 무관하게 차단됨.
    assert (
        _run_merge_check(
            monkeypatch,
            tmp_path,
            "git merge feature/x && git switch stage && git merge feature/y",
            "dev",
        )
        == fgc.BLOCK_EXIT_CODE
    )
    # switch 가 없으면 둘 다 같은 target 이므로 둘 다 판정함.
    assert (
        _run_merge_check(
            monkeypatch, tmp_path, "git merge --squash feature/x && git merge feature/y", "dev"
        )
        == fgc.BLOCK_EXIT_CODE
    )


def test_a_sourceless_merge_does_not_move_the_merge_head(monkeypatch, tmp_path: Path):
    """머리를 고르는 **모든** 자리가 "소스를 지목하는 첫 머지" 하나를 씀.

    `_judged` 가 그 기준인데 switch 를 읽는 쪽·
    `_target_from_command`·`_points_elsewhere` 가 "첫 머지 매치"였을 때, 소스 없는 머지
    (`--abort`·`--continue`)가 앞에 서면 그 뒤의 진짜 switch 가 "merge 앞"에서 밀려남.
    그러면 target 을 명령에서 못 읽고 **낡은 훅 시점 HEAD** 로 심사함.

    훅 시점 HEAD 는 반드시 **소스** 브랜치로 스텁함 — switch 가 옮겨 갈 브랜치로 스텁하면
    "명령에서 읽었다"와 "낡은 HEAD 가 우연히 같았다"를 구별하지 못함(그래서 통과함).
    """
    _write_policy(tmp_path)
    # ① 판정이 통째로 사라지던 쪽: 실측 러너 exit 2 → 0.
    for command in (
        "git merge --abort && git switch dev && git merge --no-ff feature/x",
        "git merge --continue && git checkout dev && git merge feature/x",
    ):
        code = _run_merge_check(monkeypatch, tmp_path, command, "feature/x")
        assert code == fgc.BLOCK_EXIT_CODE, command
    # switch 가 없으면 target 은 훅 시점 HEAD — 그 경로도 소스 없는 머지에 안 가려짐.
    assert (
        _run_merge_check(monkeypatch, tmp_path, "git merge --abort && git merge feature/x", "dev")
        == fgc.BLOCK_EXIT_CODE
    )
    # ② 같은 결함의 반대 부호: 규칙 없는 flow 를 낡은 HEAD 로 심사해 **오차단**함.
    #    stage → dev 를 관장하는 행이 없으므로 통과해야 함.
    assert (
        _run_merge_check(
            monkeypatch, tmp_path, "git merge --abort && git switch dev && git merge stage", "main"
        )
        == 0
    )
