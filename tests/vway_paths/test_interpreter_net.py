"""그물 — 정밀한 읽기가 놓치는 자리를 덮되, 아무것도 안 도는 명령을 넓히면 안 됨.

**그물은 이름 목록을 안 봄**: 면제를 못 받은 원소는 전부 스크립트로 다시 읽히므로, 여기
이름 하나가 빠져도 탐지는 그대로임. `_RUNS_TEXT` 가 지금 정하는 것은 탐지가 아니라
**마스크**이고, 그 차이를 재는 것은 아래 `..._keeps_the_mask_readable` 하나임.
"""

import pytest

import scripts._vway_paths as vp
from tests.vway_paths._helpers import (
    DELIBERATE_OVER_GATES,
    NET_INVOCATIONS,
    NET_MUST_NOT_FIRE,
)


@pytest.mark.parametrize("command,word", NET_INVOCATIONS, ids=[c for c, _ in NET_INVOCATIONS])
def test_text_an_interpreter_runs_is_read_as_the_invocation_it_is(command: str, word: str):
    assert vp.is_invocation(command, word)


@pytest.mark.parametrize("command,word", NET_INVOCATIONS, ids=[c for c, _ in NET_INVOCATIONS])
def test_every_net_case_is_one_the_precise_reading_misses(command: str, word: str):
    """아니면 corpus 에 그물을 한 번도 안 건드리는 항목이 쌓이고, 그물을 지워도 초록."""
    masked = vp.mask_literals(command)
    assert next(vp.git_invocations(masked, vp.git_subcommand_re(word)), None) is None


def test_the_programs_a_host_actually_runs_text_with_are_all_named():
    """아래 테스트가 이 튜플을 읽으므로, 이름 하나가 빠지면 그 케이스도 함께 사라짐.
    그래서 여기서는 철자를 적음. 잃는 것은 **탐지가 아니라 판정**임(실측):
    `bash -c 'cd /a; git merge --squash dev'` 은 이름이 있으면 `--squash` 를 읽히지만,
    없으면 그 span 이 통째로 NUL 이 되어 전략 판정이 fail-open 으로 떨어짐 — 그 판정은
    Invariant 1 이 fail-open 을 금지한 셋 중 하나. `-C` 로 트리를 지목하는 커밋도 같음."""
    spelled = {
        "sh",
        "ash",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "eval",
        "source",
        "perl",
        "python",
        "python2",
        "python3",
        "ruby",
        "node",
        "pwsh",
        "powershell",
        "cmd",
        "busybox",
    }
    for name in spelled:
        assert name in vp._RUNS_TEXT, name
    # 목록 전체를 적음. 부분집합만 적으면, 빠진 이름을 지워도 그 이름의 파라미터 케이스가
    # 함께 사라져 스위트가 초록인 채로 통과 — 이 테스트가 막으려는 바로 그 공허함.
    assert set(vp._RUNS_TEXT) == spelled, set(vp._RUNS_TEXT) ^ spelled


@pytest.mark.parametrize("name", vp._RUNS_TEXT)
def test_every_program_that_runs_text_keeps_the_mask_readable(name: str):
    """이름당 한 케이스. 탐지가 아니라 **마스크**를 잼 — 탐지는 이 목록과 무관해졌고,
    목록을 탐지로 재면 아무 이름이나 넣어도 초록인 공허한 단언이 됨(실측: `nodemon` 도
    탐지는 됨). 이름이 있으면 `-c` 인자의 명령 자리가 마스크에 살아 정밀한 읽기가 전략
    플래그와 `-C` 를 읽고, 없으면 그 span 이 NUL 이라 둘 다 사라짐."""
    import scripts.vdev_gate_check as gc

    assert gc.parse_merge_commands(f"{name} -c 'cd /a; git merge --squash dev'") == [
        ({"--squash"}, "dev")
    ]
    assert vp._dir_from_command(f"{name} -c 'true; git -C /wt commit -m x'") == "/wt"
    # 목록 밖 이름은 그 둘을 못 줌 — 탐지만 남음(그물은 그래도 물음).
    assert gc.parse_merge_commands("nodemon -c 'cd /a; git merge --squash dev'") == []
    assert vp.is_invocation("nodemon -c 'git commit -m x'", "commit")


@pytest.mark.parametrize("command", NET_MUST_NOT_FIRE, ids=range(len(NET_MUST_NOT_FIRE)))
def test_the_net_does_not_widen_a_command_that_runs_no_commit(command: str):
    for word in ("commit", "merge"):
        assert not vp.is_invocation(command, word), (command, word)


@pytest.mark.parametrize("command", DELIBERATE_OVER_GATES, ids=range(len(DELIBERATE_OVER_GATES)))
def test_a_program_that_is_not_a_reader_gates_even_when_nothing_runs(command: str):
    assert vp.is_invocation(command, "commit"), command


def test_the_grammar_reads_the_program_a_host_spells_and_ends_at_a_token():
    # `git.exe` 는 Windows 의 네이티브 이름. 못 읽으면 그 호스트에서 게이트가 꺼짐.
    assert vp.is_invocation("git.exe commit -m x", "commit")
    assert vp.is_invocation("C:/Git/bin/git.exe -C /a/wt commit -m x", "commit")
    # 서브커맨드는 **토큰 경계**에서 끝나야 함. 아니면 `git -c commit.gpgsign=false log` 가
    # 커밋으로 읽혀 읽기 전용 명령이 미분류로 차단됨(fail-CLOSED 오작동).
    assert not vp.is_invocation("git -c commit.gpgsign=false log --oneline", "commit")
    assert not vp.is_invocation("git -c merge.ff=false log", "merge")
    # `/` 도 서브커맨드를 끝내지 않음. 안 그러면 정규식 리터럴 안의 낱말이 호출로 읽혀
    # `sed`·`awk` 로 소스를 훑는 읽기 전용 작업이 통째로 차단됨(실측: 상류는 통과).
    assert not vp.is_invocation("sed -n '/git commit/p' README.md", "commit")
    assert not vp.is_invocation("awk '/git commit/{print}' f", "commit")
    assert not vp.is_invocation("sed -n 's/git merge/X/p' f", "merge")
    # 잃으면 안 되는 것: 진짜 호출의 종결 모양들. 리다이렉션·확장·줄이음이 붙는 철자를
    # 빠뜨리기 쉬움 — 종결자를 `(?=$|[\s;&|)])` 로 좁히면 아래 넷이 통째로 게이트를
    # 빠져나감(bash 로 실행을 확인한 진짜 커밋들).
    for command in (
        "git commit",
        "git commit;",
        "git commit -m x",
        "(git commit)",
        "git commit>/dev/null",
        "git commit>>log.txt",
        "git commit<in",
        "git commit$EMPTY -m x",
        "git commit\\",
    ):
        assert vp.is_invocation(command, "commit"), command
    assert vp.is_invocation("git merge>/dev/null dev", "merge")
    assert not vp.is_invocation("git commit-graph write", "commit")


@pytest.mark.parametrize(
    "unit",
    ["}", "`", "sh/", "do ", "a", "sh "],
    ids=["brace", "backtick", "dirprefix", "prefixword", "token", "names"],
)
def test_the_interpreter_net_stays_linear(unit: str):
    """접두를 정규식에 넣으면 2차가 됨 — 이 파일이 이미 두 번 겪은 회귀.

    처음 판은 `(?:^|[;&|(){}`\\n])[ \\t]*(?:[^\\s;&|()'"]*[/\\\\])?` 였다. `{`·`}`·`` ` ``
    가 앵커이면서 동시에 별표 대상이라, 앵커마다 구분자를 만날 때까지 갔다가 `[/\\\\]` 를
    찾으며 되감음 — **공백 없는** 연속에서만 드러남(`}` 16K 에서 2.3초, 배수마다 ×4,
    실측). 그래서 단위에 공백을 넣지 않음: 공백이 끼면 매 걸음이 한 글자에서 끝나 병리
    입력이 아니게 되고, 이 가드는 자기가 이름 붙인 회귀를 못 잡음(실측).
    훅에서의 2차는 타임아웃이고, 타임아웃은 판정을 건너뛰는 것과 같음. 지금 판정은
    `at_command_start` 가 파이썬으로 왼쪽을 걸어서 함.
    """
    import time

    command = unit * 16000 + " bash -c 'git commit -m x'"
    assert len(command) > 16_000
    vp._shell_regions.cache_clear()
    started = time.perf_counter()
    vp.is_invocation(command, "commit")
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"{unit!r}: {elapsed:.3f}s — 선형이면 수십 ms 다(2차 회귀 의심)"
