"""면제의 사정거리 — 원소 경계와 git 의 조건부 면제.

면제는 명령 리스트 **원소** 단위로 물음. 파이프도, heredoc 도입부와 본문 사이도,
치환 안도 원소 경계가 아님. `git` 면제는 자기 인자를 명령으로 돌리는 철자가 서면
취소됨.
"""

import pytest

import scripts._vway_paths as vp
from tests.vway_paths._helpers import (
    GIT_RUNS_A_COMMAND,
    PAIRED_HEREDOCS,
    READ_ONLY_GIT,
    REVIEW_REGRESSIONS,
    ROUND2_REGRESSIONS,
    ROUND3_REGRESSIONS,
    STORED_HEREDOCS,
)


@pytest.mark.parametrize("command,word", REVIEW_REGRESSIONS, ids=range(len(REVIEW_REGRESSIONS)))
def test_a_stage_that_names_no_reader_never_wins_an_exemption(command: str, word: str):
    assert vp.is_invocation(command, word), command


@pytest.mark.parametrize("command,word", ROUND2_REGRESSIONS, ids=range(len(ROUND2_REGRESSIONS)))
def test_a_heredoc_body_belongs_to_the_element_that_opened_it(command: str, word: str):
    assert vp.is_invocation(command, word), command


@pytest.mark.parametrize("command,word", ROUND3_REGRESSIONS, ids=range(len(ROUND3_REGRESSIONS)))
def test_the_program_at_every_command_decides_the_exemption(command: str, word: str):
    assert vp.is_invocation(command, word), command


def test_a_separator_inside_a_substitution_is_not_an_element_boundary():
    """치환 안은 명령 **하나** — 거기서 자르면 꼬리가 리더만 든 원소가 되어 면제를 받음."""
    command = "$(cat /dev/null; echo git commit -m x)"
    assert len(vp._list_elements(command, vp.mask_literals(command))) == 1
    # 치환이 닫힌 **뒤**의 구분자는 여전히 경계.
    outside = "$(date); echo ok"
    assert len(vp._list_elements(outside, vp.mask_literals(outside))) == 2


@pytest.mark.parametrize("command", STORED_HEREDOCS, ids=range(len(STORED_HEREDOCS)))
def test_a_heredoc_body_that_is_only_stored_stays_data(command: str):
    for word in ("commit", "merge"):
        assert not vp.is_invocation(command, word), (command, word)
    # 같은 본문을 면제 밖 프로그램에 주면 스크립트 — 판을 가르는 것은 **면제**이지 본문도,
    # 인터프리터 목록에 그 이름이 있는지도 아님.
    assert vp.is_invocation("bash <<EOF\ngit commit -m x\nEOF", "commit")
    assert vp.is_invocation("nodemon <<EOF\ngit commit -m x\nEOF", "commit")


def test_a_reader_after_the_introducer_does_not_exempt_the_body():
    """면제는 본문을 연 원소가 받아야 하고, 그 원소는 인터프리터를 돌림."""
    masked = vp.mask_literals("bash <<EOF && echo ok\ngit commit -m x\nEOF")
    spans = vp._list_elements("bash <<EOF && echo ok\ngit commit -m x\nEOF", masked)
    assert len(spans) == 1, spans  # `&&` 는 도입부와 본문 사이라 경계가 아님
    # 도입부가 없으면 `&&` 는 여전히 경계.
    assert len(vp._list_elements("echo a && echo b", vp.mask_literals("echo a && echo b"))) == 2


def test_git_itself_is_exempt_for_a_different_reason_than_the_readers():
    """`git` 은 읽기 전용이 아님 — `-c alias.x='!cmd' x` 로 셸 명령을 돌림. 그런데도
    면제하는 근거는 **그 철자가 없으면 인자가 데이터**라는 것이고, 그래서 면제가 조건부
    (`_GIT_RUNS_A_COMMAND_RE`). 두 집합을 갈라 두지 않으면 `_READS_ONLY` 의 이름이 곧
    "돌릴 방법이 없다"라는 뜻이 아니게 되고, 다음 사람이 그 기준으로 이름을 더함."""
    assert vp._EXEMPT_BEYOND_READERS == {"git"}
    assert "git" not in vp._READS_ONLY
    assert vp._EXEMPT == vp._READS_ONLY | vp._EXEMPT_BEYOND_READERS


@pytest.mark.parametrize("command", READ_ONLY_GIT, ids=range(len(READ_ONLY_GIT)))
def test_a_read_only_git_command_that_quotes_the_word_is_not_an_invocation(command: str):
    for word in ("commit", "merge"):
        assert not vp.is_invocation(command, word), (command, word)


def test_the_exemption_does_not_survive_a_second_program_in_the_element():
    # git 면제는 그 원소가 git **만** 돌릴 때. 다른 프로그램이 끼면 그물이 그대로 읽음.
    assert vp.is_invocation("git log -1 && bash -c 'git commit -m x'", "commit")
    assert vp.is_invocation("git log --oneline | xargs -I{} git commit -m x", "commit")
    # 진짜 호출은 정밀한 읽기가 잡으므로 면제와 무관함.
    for command in ("git commit -m x", "git -C /wt commit -m x", "git merge --no-ff stage"):
        assert vp.is_invocation(command, "commit") or vp.is_invocation(command, "merge"), command


@pytest.mark.parametrize("command", GIT_RUNS_A_COMMAND, ids=range(len(GIT_RUNS_A_COMMAND)))
def test_a_git_that_can_run_its_argument_loses_the_exemption(command: str):
    """`git` 면제의 근거는 "그 철자 없이는 인자가 데이터" — 철자가 있으면 근거가 없음.

    정밀한 읽기는 이것을 잡지 못함: 인용 span 이 명령 자리가 아니라 `git` 의 인자 자리에
    있고 `git` 은 `_RUNS_TEXT` 이 아님. 그래서 둘째 읽기가 답해야 함.
    """
    assert vp.is_invocation(command, "commit"), command


def test_the_git_exemption_survives_a_flag_that_only_carries_data():
    # 철자가 있어도 커밋처럼 생긴 텍스트가 없으면 그물은 아무것도 물지 않음. `--config-env`
    # 가 그 자리 — 명령은 환경변수 **이름**만 싣고 본문은 명령 문자열에 없음.
    for command in (
        "git -c commit.gpgsign=false log --oneline",
        "git -c merge.ff=false log",
        "git --config-env=alias.x=SNEAK x",
    ):
        for word in ("commit", "merge"):
            assert not vp.is_invocation(command, word), (command, word)


@pytest.mark.parametrize("command,word", PAIRED_HEREDOCS, ids=range(len(PAIRED_HEREDOCS)))
def test_each_heredoc_introducer_pairs_with_its_own_body(command: str, word: str):
    """도입부와 본문을 **정렬해서** 짝지으면 확장되는 본문이 어긋남 — 영역 **순서**로 짝지음."""
    opening = vp._opening_spans(vp._shell_regions(command))
    assert len(opening) == 2, opening
    assert all(a < b for a, b in opening), opening
    assert vp.is_invocation(command, word), command


@pytest.mark.parametrize("count", [1024, 2048], ids=["k1024", "k2048"])
def test_list_elements_stays_linear_in_the_number_of_heredocs(count: int):
    """구분자마다 열린 구간 **전체**를 훑으면 `구분자 × heredoc` 이라 2차.

    실측: heredoc 2048 개 · 구분자 8191 개에서 1073ms 대 5.9ms, k 를 두 배로 하면 앞은
    3.8배 뒤는 1.8배. heredoc 을 여럿 여는 명령은 병리 입력이 아님 — 생성된 스크립트가 그
    모양이고, 훅에서의 2차는 타임아웃이며 타임아웃은 판정을 건너뛰는 것과 같음.

    구간 **밖**에 구분자가 있어야 재는 값이 나옴. heredoc 을 `&&` 로만 이으면 종료자 줄에
    `&&` 가 붙어 종료자가 아니게 되고, 본문 하나가 전부를 삼켜 열린 구간이 하나뿐임.
    """
    import time

    command = "\n".join(f"cat <<E{i}\nbody\nE{i}\necho a && echo b" for i in range(count))
    vp._shell_regions.cache_clear()
    masked = vp.mask_literals(command)
    assert len(vp._opening_spans(vp._shell_regions(command))) == count, "구간이 안 열렸다"
    started = time.perf_counter()
    vp._list_elements(command, masked)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.3, f"k={count}: {elapsed:.3f}s — 선형이면 수 ms 다"
