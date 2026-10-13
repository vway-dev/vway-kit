"""낱말 안의 인용은 데이터가 아니라 그 낱말의 철자임.

셸이 모든 낱말에 인용 제거를 하므로 `git 'commit'` 도 진짜 커밋임. 같은 문법을
낱말 단위로 한 번 더 보되, 그 문법은 **선두 고정**임.
"""

import pytest

import scripts._vway_paths as vp
from tests.vway_paths._helpers import (
    CONTINUED_LINES,
    OPENS_A_COMMAND,
    QUOTE_JOINED,
    SPELLED_WITH_QUOTES,
)


@pytest.mark.parametrize("command,word", QUOTE_JOINED, ids=range(len(QUOTE_JOINED)))
def test_a_word_split_by_quoting_is_joined_back(command: str, word: str):
    assert vp.is_invocation(command, word), command


@pytest.mark.parametrize(
    "command",
    [
        "git -C /wt com''mit -m x",
        "git -C /wt c\\ommit -m x",
        "true; cd /wt && git com''mit -m x",
        "git -C /a commit -m x && git -C /b com''mit -m y",
        "printf 'git -C /wt commit -m x' | bash",
    ],
)
def test_a_commit_only_the_net_reads_names_no_tree(command: str):
    """디렉터리 판독기는 마스크를 걸으므로 이 커밋들을 못 봄 — 해석기가 어느 트리에 닿든 그것이
    깨끗하다는 사실은 이 커밋에 대해 아무것도 말하지 않음."""
    assert vp.is_invocation(command, "commit")
    assert vp.commit_tree_unresolved(command)


@pytest.mark.parametrize("command,word", SPELLED_WITH_QUOTES, ids=range(len(SPELLED_WITH_QUOTES)))
def test_a_subcommand_spelled_with_quotes_is_still_the_subcommand(command: str, word: str):
    assert vp.is_invocation(command, word), command


def test_the_quoted_subcommand_reading_is_anchored_at_the_word():
    """문법을 **선두 고정**으로 걸어야 함 — `search` 면 인자 안의 `git` 에서 매치됨.

    `git grep 'git commit'` 류가 그 모양이고, 우회로 없이 막힘(실측 43개 중 9개).
    """

    def calls(command: str) -> list:
        return list(
            vp._spelled_with_quotes(
                command, vp.mask_literals(command), vp.git_subcommand_re("commit")
            )
        )

    assert calls("git grep 'git commit'") == []
    assert calls("git 'commit' -m x"), "인용된 서브커맨드를 못 읽었다"


@pytest.mark.parametrize("count", [1000, 4000], ids=["k1000", "k4000"])
def test_the_quoted_subcommand_reading_stays_linear(count: int):
    """`operand_words` 가 호출마다 구간을 훑으면 `호출 × 구간` 이라 2차임.

    인용 인자를 하나씩 든 원소 4000 개에서 구간 순회가 1600만 번이던 판은 790ms 였음.
    명령 자리마다 한 번씩 도는 함수라, 정규식만 재는 가드로는 보이지 않음.

    **최선값으로 잼.** 지금 선형은 그 원소 수에서 0.22s 이고 경계가 0.4s 라 여유가 좁은데,
    전량 스위트의 부하가 단일 측정을 그 위로 밀어 올림(실측: 단독 통과, 전량 실행 중
    붉어짐). 2차는 어느 회차에서도 느리므로 최선값이 그것을 놓치지 않음.
    """
    import time

    runs = []
    command = " && ".join(f"git log --grep='msg {i}'" for i in range(count))
    for _ in range(3):
        vp._shell_regions.cache_clear()
        vp._blanked_view.cache_clear()
        started = time.perf_counter()
        vp.is_invocation(command, "commit")
        runs.append(time.perf_counter() - started)
    assert min(runs) < 0.4, f"k={count}: {min(runs):.3f}s — 선형이면 원소 수에 비례한다: {runs}"


@pytest.mark.parametrize("count", [500, 2000], ids=["k500", "k2000"])
def test_many_command_starts_without_a_separator_stay_linear(count: int):
    """구분자가 없으면 명령 자리마다 피연산자 영역이 **명령 끝까지**임.

    `shlex.split` 이나 `text[start:]` 슬라이스로 읽으면 `명령자리 × 길이` 라 2차임 —
    `env git ` 을 k 번 이은 명령이 16KB 에서 7.4초, 러너 wall 로는 64KB 에서 244초
    (실측; 훅 timeout 600초 = 약 90KB 부터 판정 없음). 스트림을 seek 하고 낱말을 세어
    멈춤.
    """
    import time

    command = "env git " * count + "log --grep=commit"
    vp._shell_regions.cache_clear()
    vp._blanked_view.cache_clear()
    started = time.perf_counter()
    vp.is_invocation(command, "commit")
    elapsed = time.perf_counter() - started
    assert elapsed < 0.3, f"k={count}: {elapsed:.3f}s — 선형이면 수십 ms 다"


@pytest.mark.parametrize("command,word", OPENS_A_COMMAND, ids=range(len(OPENS_A_COMMAND)))
def test_a_reserved_word_that_opens_a_command_is_a_command_start(command: str, word: str):
    assert vp.is_invocation(command, word), command


def test_a_word_that_names_a_word_is_not_a_command_start():
    """`for f`·`case $x`·`… in a)` 뒤는 이름·패턴이지 프로그램이 아님.

    프로그램으로 세면 그 낱말이 면제 집합에 없어 원소가 면제를 못 받고, 패턴 하나 때문에
    평범한 명령이 미분류 커밋으로 막힘(실측 2건).
    """
    assert vp._NAMES_A_WORD <= vp._RESERVED_WORDS
    for command in (
        "case $x in a) echo 'git commit';; esac",
        "case $x in a) grep 'git merge' f;; esac",
        'for f in *.md; do wc -l "$f"; done',
    ):
        for word in ("commit", "merge"):
            assert not vp.is_invocation(command, word), (command, word)


@pytest.mark.parametrize("command,word", CONTINUED_LINES, ids=range(len(CONTINUED_LINES)))
def test_a_backslash_line_continuation_survives_crlf(command: str, word: str):
    assert vp.is_invocation(command, word), repr(command)
