"""출하 문서가 소비자에게 지는 계약 — 문체가 아니라 **구조**와 규칙의 실재.

`test_prose.py` 가 어떻게 썼는지를 재는 자리라면, 여기는 쓰인 것이 읽히는 모양인지와,
읽는 쪽이 의존하는 규칙이 아직 문서에 남아 있는지를 잼. 둘 다 페이지가 멀쩡히 읽히는 채로
깨지는 축이라 눈으로는 안 보임.
"""

import re

import pytest

from scripts.doc_style_check import markdown_prose
from tests.skill_docs._helpers import REPO, SKILL_IDS, body

# 중첩된 단계는 들여쓰기를 가지며, 한 단 아래라고 모양이 덜 깨지지 않음. 대소문자를 안 가리는
# 이유도 같음. 펜스 블록은 markdown_prose 가 이미 뺐음 — 그 안의 깨진 모양은 단계가 아니라 예시.
_SUBSTEP_MARKER = re.compile(r"^[ \t]*\d+[a-z]+[.)]\s", re.IGNORECASE)


@pytest.mark.parametrize("skill", SKILL_IDS)
def test_no_skill_numbers_a_step_in_a_shape_commonmark_rejects(skill: str):
    """CommonMark 는 숫자 뒤에 `.` 또는 `)` 만 목록 마커로 읽음 — `1b.` 로 번호 붙은 단계는
    목록 항목이 아니라 위 단계의 lazy continuation 으로 흡수되고, 자기 이어지는 줄(하위 불릿)
    까지 데려감. 페이지는 그대로 읽혀서 살아남은 결함이고, 사라지는 것은 구조뿐임."""
    text = (REPO / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    hits = [line for _, line in markdown_prose(text) if _SUBSTEP_MARKER.match(line)]
    assert not hits, (
        f"{skill}/SKILL.md 가 단계를 {hits} 로 번호 붙임 — 목록을 재번호할 것. "
        "CommonMark 는 저 모양을 목록 항목이 아니라 문단으로 읽음"
    )


def test_the_commit_skill_bans_a_ci_skip_marker_in_the_message():
    """GitHub 은 푸시된 head 커밋 메시지의 **어디서든**(본문 포함) 그 마커를 읽고 그 푸시에
    워크플로 실행을 하나도 만들지 않음. CI 층 전부가 꺼지는데 실행이 없다는 사실은 아무것도
    보고하지 않으므로, 규칙이 문서에서 빠지면 그 다음 실패는 조용함."""
    guardrails = body(REPO / "skills/commit/SKILL.md").split("## Guardrails", 1)
    assert len(guardrails) == 2, "commit 스킬의 Guardrails 절이 개명됨"
    assert "skip ci" in guardrails[1].lower(), (
        "commit 스킬 Guardrails 가 커밋 메시지의 CI-skip 마커를 금지하지 않음 — "
        "설명하려고 토큰을 본문에 인용한 커밋이 그 푸시의 워크플로 실행을 0개로 만듦"
    )
