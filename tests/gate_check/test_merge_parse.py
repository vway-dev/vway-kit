"""머지 명령 읽기 — 소스를 지목하는 머지를 문자열에서 찾아내는 일.

훅은 셸 확장 **전** 텍스트를 받음. 그래서 인용·이스케이프·줄이음·주석을 직접 읽어야
하고, 피연산자처럼 생긴 메시지 안의 낱말에 속으면 안 됨. `-C`·선행 `cd` 로 다른
디렉터리를 가리키는 머지는 판정에서 빠짐(FAIL-OPEN).
"""

import time
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from scripts.vdev_gate_check import (
    _target_from_command,
    load_merge_strategy,
    parse_merge_command,
)
from tests.gate_check._helpers import (
    _DOC_IDIOM,
    _SEPS,
)


def test_merge_strategy_loads_rules(tmp_path: Path):
    tiers = tmp_path / "vdev-tiers.yaml"
    tiers.write_text(
        "tiers:\n  dev:\n    gates: [review]\n"
        "merge_strategy:\n"
        '  - source: "feature/*"\n'
        "    target: integration\n"
        '    require: "--squash"\n'
        "    warn_unless_rebased: true\n",
        encoding="utf-8",
    )
    rules = load_merge_strategy(tiers)
    assert len(rules) == 1
    assert rules[0]["source"] == "feature/*"
    assert rules[0]["require"] == "--squash"
    assert rules[0]["warn_unless_rebased"] is True


def test_merge_strategy_absent_key_is_empty(tmp_path: Path):
    tiers = tmp_path / "vdev-tiers.yaml"
    tiers.write_text("tiers:\n  dev:\n    gates: [review]\n", encoding="utf-8")
    assert load_merge_strategy(tiers) == []


def test_merge_strategy_missing_file_is_empty(tmp_path: Path):
    assert load_merge_strategy(tmp_path / "absent.yaml") == []


def test_merge_strategy_parse_error_is_empty(tmp_path: Path):
    tiers = tmp_path / "vdev-tiers.yaml"
    tiers.write_text("merge_strategy: [unclosed\n", encoding="utf-8")
    assert load_merge_strategy(tiers) == []


def test_merge_strategy_non_list_is_empty(tmp_path: Path):
    tiers = tmp_path / "vdev-tiers.yaml"
    tiers.write_text("merge_strategy:\n  feature: squash\n", encoding="utf-8")
    assert load_merge_strategy(tiers) == []


def test_parse_merge_plain():
    assert parse_merge_command("git merge feature/x") == (set(), "feature/x")


def test_parse_merge_squash():
    flags, src = parse_merge_command("git merge --squash feature/x")
    assert flags == {"--squash"}
    assert src == "feature/x"


def test_parse_merge_worktree_dash_c():
    # `git -C <dir> merge X` — -C 인자를 소스로 오인하면 안 됨
    flags, src = parse_merge_command("git -C /tmp/wt merge --squash feature/x")
    assert flags == {"--squash"}
    assert src == "feature/x"


def test_parse_merge_worktree_dash_c_with_a_space_in_the_path():
    # 공백 있는 경로는 Windows 에서 흔함. 전역 옵션 영역이 따옴표 인자를 한 토큰으로 읽지
    # 못하면 `"C:/My` 에서 끊겨 merge 가 파싱되지 않고, 셸이 머지라고 판정해 넘긴 명령이
    # 소스도 플래그도 없이 돌아와 merge_strategy 판정이 통째로 fail-open 됨.
    for quoted in ('"C:/My Project/wt"', "'C:/My Project/wt'"):
        flags, src = parse_merge_command(f"git -C {quoted} merge --squash feature/x")
        assert flags == {"--squash"}, quoted
        assert src == "feature/x", quoted


@pytest.mark.parametrize(
    ("unit", "reps"),
    [('-a "-x -y" ', 24), ("-c -b ", 22), (r"-a\ ", 24)],
    ids=["quoted", "flags", "escaped"],
)
def test_parse_merge_does_not_blow_up_on_repeated_options(unit: str, reps: int):
    # 전역 옵션 문법에 갈래가 남으면 같은 입력에 파싱이 둘 생기고 반복마다 곱해짐.
    # 갈래는 각각 실측됨: 따옴표 토큰을 조각내는 쪽(24쌍 5.7초), 이스케이프한 공백에서
    # 단어를 끝낼지 넘어갈지 갈리는 쪽(24쌍 3.5초), 그리고 `-b` 를 앞 플래그의 인자로도
    # 읽는 쪽(22쌍 1.4초). 마지막 갈래는 반복 단위가 인자를 받는 옵션으로 시작해야
    # 도달 — `-a -b` 로는 그 분기에 들어가지도 못해 재는 것이 없음. 훅에서의 폭주는
    # 느려지는 게 아니라 타임아웃으로 죽는 것이고, 그러면 merge 판정이 조용히 건너뛰어짐.
    # 반복 횟수는 갈래마다 다름 — 고친 문법에서는 둘 다 0.02ms 지만, 회귀했을 때 이 수에서
    # 몇 초 안에 **끝나야** 함. 더 키우면 실패 대신 매달려 진단이 어려워짐.
    # 임계 0.2초는 이 저장소 기준 두 갈래의 회귀 여유를 각각 9배·30배로 맞춘 값.
    # 1.0초로 두면 flags 갈래의 여유가 1.9배뿐이라 빠른 머신에서 회귀가 통과해 버림.
    command = "git " + unit * reps + "zzz"
    started = time.perf_counter()
    assert parse_merge_command(command) == (set(), None)
    assert time.perf_counter() - started < 0.2, "전역 옵션 정규식이 다시 지수 시간이 됐다"


def test_parse_merge_steps_over_a_backslash_escaped_space():
    # 셸은 `\ ` 로 이어 붙인 것을 토큰 하나로 줌. 옵션 영역이 거기서 끊기면 merge 가
    # 파싱되지 않고, 셸 self-filter 는 이 명령을 머지로 넘기므로 fail-CLOSED 여야 할
    # merge_strategy 판정이 통째로 사라짐.
    for opt in (
        "--git-dir=/tmp/My\\ P/.git",
        "--work-tree=/tmp/My\\ P",
        "--namespace=a\\ b",
    ):
        flags, src = parse_merge_command(f"git {opt} merge --squash feature/x")
        assert flags == {"--squash"}, opt
        assert src == "feature/x", opt


def test_parse_merge_ends_the_word_at_an_escaped_backslash():
    # 앞 테스트의 짝이자 반대 방향. `\\` 는 이스케이프된 백슬래시라 **그 다음 공백은
    # 진짜 구분자**이고, bash 는 `git -c a=\\ merge --squash feature/x` 를
    # `<-c> <a=\> <merge> …` 로 가름(스크립트 파일로 넘겨 실측). 뒤 `\` 를 이스케이프한
    # 공백으로 읽으면 단어가 `merge` 를 삼켜 서브커맨드가 사라지고, 셸 self-filter 는
    # 이 명령을 머지로 넘기므로 fail-CLOSED 여야 할 merge_strategy 판정이 꺼짐.
    flags, src = parse_merge_command("git -c a=\\\\ merge --squash feature/x")
    assert flags == {"--squash"}
    assert src == "feature/x"


def test_parse_merge_survives_an_unpairable_quote_in_an_option_value():
    # 셸이 멀쩡히 실행하는 명령 — 백슬래시·홑따옴표가 그 `"` 를 보호함. 조각에
    # 최후수단이 없으면 짝 없는 따옴표 하나가 옵션 영역 전체를 죽여 merge 가 파싱되지
    # 않고, fail-CLOSED 여야 할 판정이 통째로 사라짐. 셸 self-filter 는 이 명령을
    # 머지로 넘기므로 레이어가 어긋남.
    for opt in (
        r"-c core.editor=\"",
        r"-c user.name=O\'Brien",
        r"--git-dir=/x\"y/.git",
    ):
        flags, src = parse_merge_command(f"git {opt} merge --squash feature/x")
        assert flags == {"--squash"}, opt
        assert src == "feature/x", opt


def test_parse_merge_reads_a_path_glued_from_a_quoted_and_a_bare_piece():
    # `git -C "$WT"/wt merge` 는 셸에서 평범한 형태. 인자를 통짜 대안(따옴표 전체 또는
    # 맨몸 전체)으로 읽으면 어느 쪽에도 안 걸려 merge 가 파싱되지 않고, 셸 self-filter 는
    # 이 명령을 머지로 넘기므로 fail-CLOSED 여야 할 판정이 통째로 fail-open 됨.
    for path in ('"$WT"/wt', '"$HOME"/proj', "'$WT'/wt", 'pre"mid"post'):
        flags, src = parse_merge_command(f"git -C {path} merge --squash feature/x")
        assert flags == {"--squash"}, path
        assert src == "feature/x", path


def test_parse_merge_survives_a_merge_word_inside_a_quoted_global_option():
    # 따옴표 인자 안의 `merge` 는 서브커맨드가 아님. 대안이 배타가 아니면 `\S+` 가 앞의
    # 따옴표 토큰 앞부분에서 멈춰 커서가 그 안의 `merge` 에 놓이고, 거기서 split 된 꼬리는
    # 따옴표가 깨져 shlex 가 던짐 — 뒤에 오는 진짜 머지가 판정 없이 통과함.
    flags, src = parse_merge_command(
        'git -C "C:/My Project/wt" -c "core.editor=x merge y" status'
        " && git merge --squash feature/x"
    )
    assert flags == {"--squash"}
    assert src == "feature/x"


def test_parse_merge_message_arg_not_source():
    # -m 의 따옴표 인자를 소스 브랜치로 오인하면 안 됨
    flags, src = parse_merge_command('git merge --no-ff -m "Merge stage: headline" origin/stage')
    assert flags == {"--no-ff"}
    assert src == "origin/stage"


def test_parse_merge_gpg_sign_keeps_source():
    # -S 는 keyid 를 붙여서 받음(-Skeyid). 인자-소비 플래그로 취급하면 소스를 삼킴.
    _flags, src = parse_merge_command("git merge -S feature/x")
    assert src == "feature/x"


def test_parse_merge_strategy_flags_still_take_an_argument():
    # -s/-X 는 실제로 다음 토큰을 인자로 받음 — 소스는 그 뒤의 피연산자
    _flags, src = parse_merge_command("git merge -s recursive -X theirs feature/x")
    assert src == "feature/x"


def test_parse_merge_ff_only():
    flags, src = parse_merge_command("git merge --ff-only origin/main")
    assert flags == {"--ff-only"}
    assert src == "origin/main"


def test_parse_merge_base_is_not_a_merge():
    # `git merge-base` / `git merge-file` 는 merge 로 감지되면 안 됨
    assert parse_merge_command("git merge-base --is-ancestor a b") == (set(), None)
    assert parse_merge_command("git merge-file a b c") == (set(), None)


def test_parse_merge_not_a_merge_command():
    assert parse_merge_command("git commit -m 'x'") == (set(), None)


def test_parse_merge_unbalanced_quote_fails_open():
    assert parse_merge_command('git merge -m "unclosed feature/x') == (set(), None)


def test_parse_merge_no_source():
    # 인자 없는 `git merge` (진행 중인 머지 계속)
    assert parse_merge_command("git merge") == (set(), None)


def test_parse_merge_backslash_newline_continuation():
    # `\`+개행으로 접힌 단일 머지. shlex 는 `\`+개행을 리터럴 개행 토큰으로 만드는데,
    # 그것이 -로 시작하지 않아 소스 자리로 새면(source='\n') 어떤 규칙도 매칭 안 돼
    # 게이트가 조용히 꺼짐. 에이전트가 긴 명령을 이렇게 접는 것은 흔함.
    flags, src = parse_merge_command("git merge \\\n  feature/x")
    assert src == "feature/x"


def test_parse_merge_operand_region_stops_at_a_separator():
    # `git merge X && git commit …` 의 정규 관용구: `&&` 뒤 단어를 소스로 삼키지 않음.
    flags, src = parse_merge_command('git merge --squash feature/x && git commit -m "x"')
    assert flags == {"--squash"}
    assert src == "feature/x"


def test_parse_merge_ignores_a_merge_word_before_the_real_git_merge():
    # 앞쪽에 독립 단어 `merge`(커밋 메시지·다른 명령)가 있어도, 진짜 `git merge` 를 찾아야
    # 함. git 앵커가 없으면 아무 곳의 `merge` 에서 분할돼 뒤 꼬리가 깨지고 검사가 꺼짐.
    for cmd in (
        'git commit -m "prepare merge" && git switch dev && git merge feature/x',
        "npm run merge && git merge feature/x",
        "git fetch && echo merge && git merge feature/x",
    ):
        _flags, src = parse_merge_command(cmd)
        assert src == "feature/x", cmd


def test_target_from_command_switch_and_checkout():
    assert _target_from_command("git switch dev && git merge feature/x") == "dev"
    assert _target_from_command("git checkout dev && git merge feature/x") == "dev"
    # 문서화된 3단계 블록, 그대로
    assert (
        _target_from_command("git switch dev && git pull --ff-only && git merge --squash feature/x")
        == "dev"
    )


def test_target_from_command_takes_the_last_switch_before_the_merge():
    cmd = "git switch stage && git switch dev && git merge feature/x"
    assert _target_from_command(cmd) == "dev"


def test_target_from_command_ignores_a_switch_after_the_merge():
    assert _target_from_command("git merge feature/x && git switch main") is None


def test_target_from_command_none_when_unclear():
    # switch 가 아예 없거나, 피연산자가 명백한 브랜치가 아닌 형태 → 훅 시점 브랜치를 유지
    # (FAIL-OPEN: target 을 지어내지 않음)
    assert _target_from_command("git merge feature/x") is None
    assert _target_from_command("git switch -c feature/y && git merge feature/x") is None
    assert _target_from_command("git checkout -- some/file && git merge feature/x") is None


def test_target_from_command_checkout_with_a_pathspec_is_unclear():
    # `git checkout <branch> -- <path>` 는 그 브랜치에서 파일을 복원함. HEAD 는 그대로.
    # 선행 `-` 만 거르는 토큰 규칙은 여기서 `dev` 를 읽어, 명령이 들어간 적도 없는 브랜치로의
    # 머지를 차단함.
    assert _target_from_command("git checkout dev -- a/b.py && git merge feature/x") is None


def test_target_from_command_one_unclear_switch_voids_the_whole_chain():
    # HEAD 는 실제로 feature/y 에서 끝남. 마지막 *매칭되는* switch 를 찾으면 불명확한 `-c`
    # 형태를 건너뛰고 낡은 `dev` 를 채택해, 일어나지도 않는 flow 의 규칙이 발동함.
    cmd = "git switch dev && git switch -c feature/y && git merge feature/x"
    assert _target_from_command(cmd) is None
    # …순서를 바꿔도 같음: 명확한 switch **앞**의 불명확한 switch 도 여전히 불명확.
    # 뒤의 명확한 것이 앞의 실행 여부에 조건 지어져 있을 수 있기 때문.
    assert _target_from_command("git switch --detach && git switch dev && git merge f/x") is None


def test_target_from_command_origin_ref_is_unclear():
    # `git checkout origin/dev` 는 dev 가 아니라 **detached HEAD** 로 감 — 그런데
    # _branch_matches 가 `origin/` 을 벗기므로, 이를 target 으로 채택하면 integration 규칙에
    # 매칭돼 차단됨.
    assert _target_from_command("git checkout origin/dev && git merge feature/x") is None


@_SEPS
def test_target_from_command_reads_the_documented_block_under_any_separator(sep):
    # 정책이 스스로 규정한 관용구. Claude Code 는 이를 **한 번의** Bash 호출로 보내고,
    # 3단계 블록의 자연스러운 표현은 3**줄** — 이 모양이 integration 브랜치로 해석되지
    # 않으면, 문서화된 절차가 바로 게이트를 걸어서 통과하는 모양이 됨.
    assert _target_from_command(sep.join(_DOC_IDIOM)) == "dev"
    assert _target_from_command(sep.join(["git switch dev", "git merge feature/x"])) == "dev"


def test_target_from_command_reads_the_documented_block_with_crlf():
    # Windows 에서 작성된 heredoc 은 `\r\n` 을 실음. 구분자 클래스에서 `\r` 이 빠지면
    # 피연산자가 `dev\r` 로 남는데 이는 토큰 하나라 "명확"으로 파싱됨 — 그래서 요란하게
    # 실패하지 않고, 어떤 규칙과도 매칭되지 않는 브랜치명을 조용히 지목하며 흘러감.
    assert _target_from_command("\r\n".join(_DOC_IDIOM)) == "dev"


@_SEPS
@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(["git checkout dev -- README.md", "git merge feature/x"], id="N1-pathspec"),
        pytest.param(
            ["git switch dev", "git switch -c feature/y", "git merge feature/x"], id="N2-switch-c"
        ),
        pytest.param(["git checkout origin/dev", "git merge feature/x"], id="M3-origin-ref"),
    ],
)
def test_target_from_command_false_positives_stay_unclear_under_any_separator(steps, sep):
    # 같은 확장의 반대 방향: 파서에게 개행을 넘어 보라고 가르치는 것이, target 을 이름 붙이면
    # false block 이 되는 세 형태에서 **이름 붙이도록** 가르쳐서는 안 됨. 각각은 모든
    # 구분자에서 None 으로 남아야 훅 시점 브랜치가 유지됨.
    assert _target_from_command(sep.join(steps)) is None


def test_points_elsewhere_ignores_a_non_git_dash_c(tmp_path: Path):
    # `-C` 가 "디렉터리 변경"인 것은 git 자신의 전역 옵션일 때뿐임. 앵커가 없으면
    # `grep -C 3` 이 디렉터리 "3" 으로 해석되고, 그것은 root 의 외부라 게이트 전체가
    # fail-open 됨.
    assert fgc._points_elsewhere("grep -C 3 foo f.txt && git merge feature/x", tmp_path) is False


def test_points_elsewhere_detects_a_non_leading_cd(tmp_path: Path):
    # `git fetch && cd <other> && git merge X`: cd 가 명령 선두가 아니라도 실행 디렉터리를
    # 옮김. .match(선두 앵커)만 쓰면 앞에 아무 명령이나 붙는 순간 감지가 사라져, 소스는
    # 명령어에서 target 은 이쪽 root 에서 읽는 불일치로 오차단이 일어남. `git fetch && cd …`
    # 는 흔한 형태.
    cmd = "git fetch && cd /other/wt && git merge feature/x"
    assert fgc._points_elsewhere(cmd, tmp_path) is True
    # 선두 cd 도 계속 감지
    assert fgc._points_elsewhere("cd /other/wt && git merge feature/x", tmp_path) is True


def test_points_elsewhere_detects_a_leading_cd(tmp_path: Path):
    # `cd <dir> && git merge X` 는 `git -C <dir>` 와 똑같이 실행 디렉터리를 지정함.
    other = tmp_path / "other"
    assert fgc._points_elsewhere(f"cd {other} && git merge feature/x", tmp_path) is True
    # root 자신은 외부가 아니므로 게이트가 계속 강제됨.
    assert fgc._points_elsewhere(f"cd {tmp_path} && git merge feature/x", tmp_path) is False


@_SEPS
def test_points_elsewhere_detects_a_leading_cd_under_any_separator(tmp_path: Path, sep):
    # 같은 구분자 사각지대의 fail-CLOSED 쪽. `cd <wt>` 를 제 줄에 쓰는 게 보통인데 `&&` 만
    # 인식하면 cd 가 아예 없는 것으로 읽혀, 소스는 명령어에서 target 은 이쪽 root 에서 읽는
    # 불일치로 일어나지도 않는 flow 를 차단함. 여기 감지는 언제나 fail-open 으로만 작용함.
    other = tmp_path / "other"
    assert fgc._points_elsewhere(sep.join([f"cd {other}", "git merge feature/x"]), tmp_path) is True
    # …root 자신은 여전히 외부가 아니라 게이트가 유지됨.
    assert (
        fgc._points_elsewhere(sep.join([f"cd {tmp_path}", "git merge feature/x"]), tmp_path)
        is False
    )


def test_points_elsewhere_resolves_a_relative_dir_against_root(tmp_path: Path):
    # merge 검사는 precommit-runner.sh 의 `cd "$ROOT"` **앞**에서 돌므로 인터프리터 cwd 는 훅
    # cwd. `.` 을 그 cwd 기준으로 풀면 `git -C .` 이 외부로 보여 게이트를 건너뜀 — root
    # 기준으로 풀어야 root 자신이라 강제가 유지됨.
    assert fgc._points_elsewhere("git -C . merge feature/x", tmp_path) is False
