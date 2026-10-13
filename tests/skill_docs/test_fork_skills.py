"""`context: fork` 스킬이 실제로 도는 모양인가.

fork 는 대화가 없는 서브에이전트에서 돎 — 사람에게 못 묻고, 기본값 background 는
도구셋이 좁음. 둘 다 실패가 조용함: 물어보는 절차는 문서에만 남고, 좁은 도구셋은
Read·Write 가 빠진 채 스킬이 아무것도 못 하고 끝남.

네 필드가 서로 맞는지도 같은 이유로 여기서 잼 — `agent`·`background` 는 `context: fork`
없이는 불활성이고, `context` 의 다른 값과 없는 `agent` 이름은 오류가 아니라 무시·폴백임.
넷 다 스펙 필드라 `test_frontmatter.py` 의 철자 검사를 그대로 통과함.
"""

from pathlib import Path

import pytest

from tests.skill_docs._helpers import (
    SKILL_IDS,
    SKILLS,
    body,
    fork_body_problem,
    fork_frontmatter_problem,
    frontmatter,
)


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_fork_skills_declare_background_false(skill: Path):
    problem = fork_frontmatter_problem(frontmatter(skill))
    assert problem is None, f"{skill.parent.name}: {problem}"


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_fork_skills_do_not_ask_the_user(skill: Path):
    problem = fork_body_problem(frontmatter(skill), body(skill))
    assert problem is None, f"{skill.parent.name}: {problem}"


def test_the_guards_reject_a_fork_skill_that_breaks_them():
    """코퍼스에 fork 스킬이 없으면 위 둘은 공짜로 초록임 — 판정 자체를 여기서 잼."""
    assert fork_frontmatter_problem({"context": "fork"}) is not None
    assert fork_frontmatter_problem({"context": "fork", "background": True}) is not None
    assert fork_frontmatter_problem({"context": "fork", "background": False}) is None
    assert fork_body_problem({"context": "fork"}, "AskUserQuestion 으로 묻는다") is not None
    vocabulary_ask = "Ask the user\n(structured choice) 로 묻는다"
    assert fork_body_problem({"context": "fork"}, vocabulary_ask) is not None
    assert fork_body_problem({"context": "fork"}, "묻지 않는다") is None


def test_the_guards_ignore_a_skill_that_does_not_fork():
    """인라인 스킬은 물어도 되고 background 를 선언할 이유도 없음."""
    assert fork_frontmatter_problem({"name": "vdev"}) is None
    assert fork_body_problem({"name": "vdev"}, "AskUserQuestion 으로 확인") is None


def test_the_dependent_fields_are_rejected_without_the_fork_declaration():
    """`agent`·`background` 는 `context: fork` 없이는 아무 일도 안 함.

    둘 다 스펙 필드라 철자 검사는 통과하고, 선언한 쪽은 그것이 걸린다고 읽음 —
    `background: false` 만 단 스킬은 아무것도 안 막으면서 막는 것처럼 보임."""
    assert fork_frontmatter_problem({"agent": "general-purpose"}) is not None
    assert fork_frontmatter_problem({"background": False}) is not None


def test_a_context_value_other_than_fork_is_rejected():
    """스펙이 정의하는 `context` 값은 `fork` 하나 — 다른 값은 조용히 무시됨.

    두 꼴을 다 재는 이유: 딸린 필드가 함께 서도 `context` 값 쪽이 범인으로 지목돼야 함 —
    `context: Fork` 오타가 "background 가 불활성" 으로 보고되면 고칠 자리를 못 댐."""
    assert fork_frontmatter_problem({"context": "inline"}) is not None
    # `is not None` 로는 부족함 — 딸린 필드 분기가 먼저 나도 초록이라 재정렬이 무방비.
    # 부분문자열 `"context"` 로도 부족함 — 그쪽 메시지가 `context: fork` 를 담고 있음.
    problem = fork_frontmatter_problem({"context": "inline", "background": False})
    assert problem and problem.startswith("context=")


def test_the_agent_must_name_one_that_exists():
    """없는 agent 이름은 오류가 아니라 **기본 agent 로 폴백** — 저자가 고르지 않은 곳에서 돎."""
    assert (
        fork_frontmatter_problem(
            {"context": "fork", "background": False, "agent": "general_purpose"}
        )
        is not None
    )
    assert (
        fork_frontmatter_problem({"context": "fork", "background": False, "agent": "Explore"})
        is None
    )
    assert (
        fork_frontmatter_problem(
            {"context": "fork", "background": False, "agent": "vway-kit:harness-critic"}
        )
        is None
    )


def test_a_plugin_agent_is_named_with_its_plugin_prefix():
    """플러그인 에이전트의 이름은 `<plugin>:<agent>` — 접두 없는 파일명은 아무것도 지목하지 않음."""
    assert (
        fork_frontmatter_problem(
            {"context": "fork", "background": False, "agent": "harness-critic"}
        )
        is not None
    )
