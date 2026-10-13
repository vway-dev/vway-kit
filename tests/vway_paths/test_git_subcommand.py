"""자기 인자를 명령으로 돌리는 git 서브커맨드.

`submodule foreach`·`bisect run` 류는 git 이라는 이름이 벌어 준 면제를 취소함.
"""

import pytest

import scripts._vway_paths as vp
from tests.vway_paths._helpers import (
    GIT_RUNS_A_SUBCOMMAND,
)


@pytest.mark.parametrize(
    "command,word", GIT_RUNS_A_SUBCOMMAND, ids=range(len(GIT_RUNS_A_SUBCOMMAND))
)
def test_a_git_subcommand_that_runs_its_argument_loses_the_exemption(command: str, word: str):
    assert vp.is_invocation(command, word), command


@pytest.mark.parametrize(
    "text",
    [
        "git " + "--aaaaaaaaaa " * 4000,  # `-filter` 를 못 찾는 긴 플래그 열
        "git submodule " + "-a " * 4000,  # `foreach` 를 못 찾는 긴 옵션 열
        "git bisect " + "-a " * 4000,  # `run` 을 못 찾는 긴 옵션 열
        "git " + "a" * 40000,  # 공백 없는 긴 토큰
    ],
    ids=["flags", "submodule", "bisect", "one-token"],
)
def test_the_runs_a_command_pattern_stays_linear(text: str):
    """플래그 갈래는 전부 **리터럴** — `--[a-z-]+-filter` 로 적으면 `-filter` 를 못 찾는
    긴 토큰마다 되감아 2차가 됨. 서브커맨드 갈래의 `(?:\\s+-\\S+)*` 는 `_GLOBAL_OPTS` 와
    같은 모양이라 매 반복이 공백에서 결정됨 — 그래도 여기서 잼."""
    import time

    assert "[a-z" not in vp._GIT_RUNS_A_COMMAND_RE.pattern, vp._GIT_RUNS_A_COMMAND_RE.pattern
    started = time.perf_counter()
    vp._GIT_RUNS_A_COMMAND_RE.search(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2, f"{elapsed:.3f}s"
