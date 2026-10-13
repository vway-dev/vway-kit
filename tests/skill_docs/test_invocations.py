"""출하 문서가 무엇을 부른다고 적었는가.

문서가 낱말로만 적은 `commit` 은 호출이 아님. 추출기는 게이트와 **같은 방식으로**
주석을 읽어야 함 — 다르게 읽으면 한쪽만 보는 명령이 생김.

호출을 **어떻게** 적었는지도 같은 분류: 자동 라우팅의 근거, 디스패치가 지목하는 모델.
지시가 조용히 빠져도 산문은 멀쩡히 읽히므로 문서만 보고는 못 가림.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

# `scripts/` must not linger on sys.path after this import: scripts/teams_alert.py (and
# friends) resolve `_vway_paths` with `try: import _vway_paths / except ImportError:
# import scripts._vway_paths` (see that module's docstring) so tests can `import
# scripts.xxx` as a package. A `scripts/` dir left on sys.path for the rest of the
# session flips that try-branch for every test file collected afterward (alphabetically,
# that is most of them), loading `_vway_paths` a SECOND time under a different module
# identity — `scripts.teams_alert._host_root is scripts._vway_paths.host_root` then
# reads False even though both come from the same file.
sys.path.pop(0)


from tests.skill_docs._helpers import (
    REPO,
    _is_invocation,
    _issued_git_commands,
    _spawns_the_gate,
)
from tests.skill_docs._invocations import (
    MERE_MENTIONS,
    MODEL_NAMES,
    PROPAGATE_MODE,
    R6_CHECK,
    REAL_INVOCATIONS,
    ROUND_END,
    SCAN_DISPATCH,
    TASK_SYNC_DOC,
    section,
)


def test_vdev_does_not_auto_route_on_a_task_id_shape():
    """`^[A-Z]+-\\d+$` 매칭만으로 ALM 을 치는 동작은 금지. 문서가
    슬쩍 되돌아오면 사용자가 요청하지 않은 외부 호출이 다시 살아남."""
    text = (REPO / "skills" / "vdev" / "SKILL.md").read_text(encoding="utf-8")
    assert "^[A-Z]+-" not in text, "task-id 모양 자동 라우팅이 되살아났다"
    assert "vdev-config.alm" in text, "provider 해석의 근거가 config 라는 것이 명시되어야 한다"


@pytest.mark.parametrize("command", REAL_INVOCATIONS)
def test_every_real_invocation_reaches_the_gate(command: str):
    """진짜 호출은 **판정에 닿아야** 함: 거친 필터가 spawn 하고, 문법이 호출로 읽음.

    러너의 필터는 게이트가 **도는지**만, 문법은 그것이 무엇인지를 정함. 필터가 문법보다
    좁으면 조용히 꺼진 게이트 — 셸이 떨어뜨리면 훅이 아예 발화하지 않음. 두 셸 패턴을
    서로 비교하는 가드는 둘이 **함께** 어긋나는 것을 못 잡고, 경로 붙은 `git` 과 이스케이프된
    따옴표가 그렇게 초록인 채 통과함. 그래서 corpus 가 스펙.
    """
    assert _is_invocation("commit", command), (
        f"{command!r} 는 진짜 호출인데 문법이 더는 호출로 읽지 않는다. "
        f"corpus 가 스펙이다 — corpus 가 아니라 문법을 넓혀라."
    )
    assert _spawns_the_gate(command), (
        f"{command!r} 는 러너의 거친 필터가 떨어뜨리는 진짜 호출이다: 훅이 exit 0 하고 뒤의 "
        f"모든 게이트가 조용히 건너뛰어진다. 필터는 문법보다 좁을 수 없다."
    )


@pytest.mark.parametrize("command", MERE_MENTIONS)
def test_a_command_that_merely_says_the_word_is_not_an_invocation(command: str):
    """읽기 전용 명령이 미분류 커밋이라는 이유로 차단되면 안 됨.

    거친 필터가 이것들을 넘기는 것은 **정상** — 비용은 python spawn 하나. 판정은
    문법이 하고, 여기서 아니라고 해야 러너가 조용히 멈춤.
    """
    assert not _is_invocation("commit", command)
    assert not _is_invocation("merge", command)


def test_the_extractor_reads_comments_the_way_the_gate_does():
    """이 추출기가 명령을 어디서 끊는지가 위 가드들의 입력을 정함.

    `" #"` 로 자르면 따옴표 **안**의 `#` 에서도 끊김: `-m "fix #123"` 이 `-m "fix` 가 되고,
    그러면 따옴표가 안 닫힌 것으로 읽혀 뒤 줄들이 한 명령으로 붙음. 그렇게 붙은 덩어리는
    문서가 실제로 지시하는 명령이 아니므로, 가드는 문서가 아니라 추출기를 재게 됨.
    """
    nl = chr(10)
    fence = "```"
    doc = nl.join([fence + "bash", 'git commit -m "fix #123"', "git status", fence, ""])
    assert _issued_git_commands(doc) == ['git commit -m "fix #123"', "git status"]
    # 진짜 주석은 — 줄 전체든 꼬리든 — 명령에서 빠짐.
    doc = nl.join(
        [fence + "bash", "# git commit -m x", "git merge feature/x  # --squash", fence, ""]
    )
    commands = _issued_git_commands(doc)
    assert len(commands) == 1
    assert commands[0].split() == ["git", "merge", "feature/x"]


def test_the_filter_is_not_narrower_where_a_quote_is_the_separator():
    """인용 지운 판에서는 따옴표가 구분자가 됨.

    `eval 'git'commit` 을 셸은 `gitcommit` 하나로 읽지만 게이트의 두 번째 판은 `git commit`
    으로 읽음 — **과다 매칭**이고, 그 방향은 안전함(언급이 게이팅될 뿐, 커밋이 놓치지
    않음). 그러면 러너의 필터도 그것을 넘겨야 함: 낱말 앞 공백을 앵커로 삼으면 여기서
    필터가 문법보다 좁아지고, 그건 조용히 꺼진 게이트.
    """
    command = "eval 'git'commit"
    assert _is_invocation("commit", command)
    assert _spawns_the_gate(command)


def test_the_similarity_scan_dispatch_names_a_model():
    """스캔 에이전트의 모델은 §4 디스패치가 정함.

    선언이 없으면 에이전트가 부모 모델을 물려받고, 보드 원문 전체가 그 단가로 청구됨 —
    후보 표는 똑같이 돌아오므로 아무도 그 사실을 못 봄. 어느 모델인지는 재지 않음:
    올리고 내리는 것이 이 선언의 용도이고, 값을 박으면 그 되돌리기를 테스트가 막음.
    """
    section = SCAN_DISPATCH
    assert any(m in section for m in MODEL_NAMES), (
        "§4 디스패치가 스캔 에이전트의 모델을 지목해야 한다"
    )


def test_the_scan_procedure_does_not_restate_the_model():
    """모델은 디스패치의 성질이지 절차의 입력이 아님 — §4 한 곳에만 삶.

    절차 파일이 따라 적으면 두 곳이 갈리고, 한쪽만 고친 다음 사람이 어느 쪽이 도는지
    문서로는 못 가림(rules/doc-style.md 9 — 한 사실 한 곳).
    """
    procedure = (REPO / "skills" / "alm-trace" / "references" / "similarity-scan.md").read_text(
        encoding="utf-8"
    )
    named = [m for m in MODEL_NAMES if m in procedure]
    assert not named, f"절차 파일이 모델을 다시 적었다: {named}"


def test_a_vanished_heading_stops_the_section_from_widening():
    """헤딩이 개명되면 조각이 조용히 파일 전체가 되는 것을 막음.

    가드가 없으면 그 조각을 재는 테스트 둘이 다른 절의 낱말로 초록을 유지하고,
    정작 디스패치가 비어도 아무도 못 봄.
    """
    text = "### 4. 있음\n본문\n### 5. 다음\n"
    assert section(text, "### 4. ", "### 5. ") == "있음\n본문\n"
    for start, end in (("### 4) ", "### 5. "), ("### 4. ", "### 5) ")):
        with pytest.raises(AssertionError, match="헤딩이 사라짐"):
            section(text, start, end)


def test_the_propagate_mode_turns_the_status_axis_off():
    """`--propagate` 는 사실만 씀 — 상태를 올리면 사람을 안 거친 PASS 가 요구사항을 옮김.

    그 보장은 fork 에 넘기는 `propagate.status` 를 `off` 로 바꾸는 한 문장에 삶. 문장이
    빠져도 모드 절은 멀쩡히 읽히므로 문서만 보고는 못 가림.
    """
    assert re.search(r"`status`\s*를\s*`off`", PROPAGATE_MODE), (
        "전파 전용 모드가 fork 의 propagate.status 를 off 로 넘긴다고 적어야 한다"
    )


def test_the_argument_hint_advertises_the_propagate_mode():
    """호출자(`integration` §3.6)가 쓰는 플래그가 자동완성과 본문에 함께 있어야 함."""
    assert re.search(r"^argument-hint:.*--propagate", TASK_SYNC_DOC, re.M), (
        "task-sync argument-hint 에 --propagate 가 없다"
    )
    assert "--propagate" in PROPAGATE_MODE


def test_a_verification_round_that_wrote_results_calls_the_propagate_mode():
    """FAIL 회차는 `--verified` 제안이 없으니 이 호출이 리그레션이 상위에 닿는 유일한 길.

    문장이 빠지면 §3.6 은 PASS 제안만 남아 멀쩡히 읽히고, `coverage_status` 는 리그레션 뒤에도
    `COVERED` 로 남음.
    """
    assert (
        "/task-sync" in ROUND_END and "--propagate" in ROUND_END and "판정과 무관" in ROUND_END
    ), "§3.6 이 결과를 적은 회차마다 /task-sync --propagate 를 부른다고 적어야 한다"


def test_the_r6_check_blocks_a_status_in_the_propagate_mode():
    """두 번째 방어선 — 모드 절의 fork 오버라이드와 떨어진 자리라, 한 군데 빠져도 다른 쪽이 막음."""
    assert "--status-off" in R6_CHECK, "R6 검산 명령이 --status-off 를 붙인다고 적어야 한다"


def _classifier_corpora() -> list[tuple[str, str]]:
    from tests.vway_paths._helpers import (
        CONTINUED_LINES,
        NET_INVOCATIONS,
        QUOTE_JOINED,
        SPELLED_WITH_QUOTES,
    )

    return [*SPELLED_WITH_QUOTES, *QUOTE_JOINED, *NET_INVOCATIONS, *CONTINUED_LINES]


@pytest.mark.parametrize("command,word", _classifier_corpora())
def test_every_invocation_the_classifier_reads_reaches_the_gate(command: str, word: str):
    """필터는 이 파일의 corpus 만이 아니라 문법이 못 박힌 모든 corpus 에서 문법보다 거칠어야
    함 — 문법만 받는 철자는 꺼진 게이트."""
    assert _is_invocation(word, command), command
    assert _spawns_the_gate(command), command
