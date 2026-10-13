"""매 세션 주입되는 룰이 지고 다니는 것 — 일상 요청이 승격 상세를 내지 않는가.

`hooks/inject-risk-tiers.sh` 는 `rules/risk-tiers.md` 를 **통째로** 세션 앞에 붙임. 그래서
그 파일의 바이트는 이 저장소의 어떤 문서와도 다른 값을 가짐: 특정 상황에서만 쓰는 절 하나가
거기 있으면 그 상황과 무관한 요청 전부가 그 값을 뭄. 승격 전용은 `rules/promotion.md`,
머지 전용은 `rules/merge-strategy.md`, 게이트가 막았을 때만 읽는 상세는
`rules/gate-mechanics.md`, 커밋 한 건을 쓸 때만 읽는 메시지 형식은 `rules/commit-discipline.md`
로 빠지고 주입에서 제외되며, 이 파일이 그 분리를 되돌릴 수 없게 함.

FIRST-action 명령문 뒤에 붙은 문장도 여기서 잼: 상류 harness-tier 가 같은 자리의 두 줄을
빼자 스킬 호출률이 0.55 에서 0.82 로 올랐음(설명문 바이트는 동일, 2026-09-08 실측). 명령문
문단이 명령으로 끝나야 하는 이유가 그것이고, 근거가 측정이라 규칙으로 남길 값이 있음.

빼는 **방식**도 측정이 정함: 포인터 스텁을 남긴 226줄 분리는 없애려던 분량보다 오히려 나빴고
(0.33), 스텁을 하나도 안 남긴 255줄 분리는 값을 지켰음(0.80 → 0.76, 양쪽 n=25). 절은 통째로
옮기고 "X 로 옮김" 제목은 남기지 않음 — 포인터뿐인 절이 그것이 대신한 본문보다 비쌈.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RULE = REPO / "rules" / "risk-tiers.md"
PROMOTION = REPO / "rules" / "promotion.md"
HOOK = REPO / "hooks" / "inject-risk-tiers.sh"

# 주입에서 빠진 절 → 그것을 대신 지고 있는 파일. 제목 그대로 — 부분 문자열이 아니라
# heading 이라야 산문 속 언급(다른 절이 "Back-merge" 를 참조하는 줄)이 이 가드를 조용히
# 만족시키지 못함. 모두 같은 근거로 빠짐: 그 절을 읽을 일이 없는 요청이 대다수임.
DEFERRED = [
    ("### Version bump selection (auto vs manual)", "promotion.md"),
    ("### Merge commit messages (promotion merges)", "promotion.md"),
    ("### Back-merge after release (production → integration)", "promotion.md"),
    ("### 승격의 절차 단계 — 검증 회차 (게이트 아님)", "promotion.md"),
    ("## Promotion events (Staging / Release)", "promotion.md"),
    ("## Promotion steps", "promotion.md"),
    ("### Merging `feature/*` → integration (integration-test gate)", "merge-strategy.md"),
    ("### PR workflow", "merge-strategy.md"),
    ("### Feature branch base", "merge-strategy.md"),
    ("## Message format (Conventional Commits)", "commit-discipline.md"),
    ("## Commit type → version impact", "commit-discipline.md"),
]

# 주입된 룰이 가리켜야 하는, 주입되지 않는 파일들.
REFERENCES = ["promotion.md", "merge-strategy.md", "gate-mechanics.md", "commit-discipline.md"]

# 옮긴 자리에 남은 "X 로 옮김" 제목 — 본문을 지웠는데 값이 오히려 나빠지는 경로(0.33 실측).
# 제목 문자열 자체가 앵커라, 같은 이름의 절이 다시 서면 그 줄이 돌아옴.
POINTER_STUBS = ["### Promotion-only sections", "### Merge strategy"]

# gate-mechanics 로 간 것은 heading 이 아니라 불릿이라, 각 절이 실제로 지고 있는 문장을
# 지목함 — heading 을 새로 판 파일에서는 그것이 유일한 앵커.
GATE_MECHANICS_ONLY = [
    "비차단 품질 경고(orphan",
    "`--lint-config` 와 **같은 함수**가 읽으므로",
    "**Fail-open on errors**",
    "**Air-gapped limit**",
]


def _section(text: str, heading: str) -> str:
    """heading 부터 같은 깊이의 다음 heading 직전까지. 없으면 빈 문자열."""
    lines = text.splitlines()
    depth = len(heading) - len(heading.lstrip("#"))
    try:
        start = lines.index(heading)
    except ValueError:
        return ""
    for i in range(start + 1, len(lines)):
        stripped = lines[i].lstrip("#")
        if lines[i].startswith("#") and len(lines[i]) - len(stripped) <= depth:
            return "\n".join(lines[start:i])
    return "\n".join(lines[start:])


@pytest.mark.parametrize(("heading", "reference"), DEFERRED)
def test_the_injected_rule_carries_no_deferred_section(heading: str, reference: str):
    assert heading not in RULE.read_text(encoding="utf-8"), (
        f"{heading!r} 이 주입되는 룰에 있음 — 그 절을 읽을 일 없는 요청 전부가 이 바이트를 뭄. "
        f"rules/{reference} 로 **통째로** 옮기고, risk-tiers.md 에는 제목도 남기지 마세요."
    )


@pytest.mark.parametrize("stub", POINTER_STUBS)
def test_the_injected_rule_leaves_no_pointer_stub(stub: str):
    assert stub not in RULE.read_text(encoding="utf-8"), (
        f"{stub!r} 이 포인터 스텁으로 돌아왔음 — 상류 실측에서 스텁을 남긴 분리는 0.33 으로 "
        f"본문을 그대로 둔 것보다 나빴고, 스텁 없는 분리만 값을 지켰습니다(0.76, n=25). "
        f"파일을 가리키는 줄은 그 규율을 실제로 쓰는 절 안에 두세요."
    )


@pytest.mark.parametrize(("heading", "reference"), DEFERRED)
def test_the_deferred_reference_carries_them_instead(heading: str, reference: str):
    # 옮긴 절이 어느 쪽에도 없으면 위 가드는 그대로 녹색이면서 규율만 사라짐.
    assert heading in (REPO / "rules" / reference).read_text(encoding="utf-8"), (
        f"{heading!r} 이 risk-tiers.md 에서 빠졌는데 {reference} 에도 없음 — 규율이 삭제됨."
    )


@pytest.mark.parametrize("sentence", GATE_MECHANICS_ONLY)
def test_the_injected_rule_carries_no_gate_mechanics_detail(sentence: str):
    assert sentence not in RULE.read_text(encoding="utf-8"), (
        f"{sentence!r} 이 주입되는 룰로 돌아왔음 — 게이트가 막았을 때만 읽는 상세라 "
        f"rules/gate-mechanics.md 가 지고, risk-tiers 는 용어집 한 줄만 둡니다."
    )


@pytest.mark.parametrize("sentence", GATE_MECHANICS_ONLY)
def test_gate_mechanics_carries_them_instead(sentence: str):
    text = (REPO / "rules" / "gate-mechanics.md").read_text(encoding="utf-8")
    assert sentence in text, (
        f"{sentence!r} 이 risk-tiers.md 에서 빠졌는데 gate-mechanics.md 에도 없음 — 규율이 삭제됨."
    )


@pytest.mark.parametrize("reference", REFERENCES)
def test_the_injected_rule_points_at_every_deferred_reference(reference: str):
    # 주입된 텍스트만 보는 세션이 나머지 절반을 찾을 길은 이 포인터뿐.
    assert reference in RULE.read_text(encoding="utf-8")


@pytest.mark.parametrize("reference", REFERENCES)
def test_the_hook_injects_the_rule_but_no_deferred_reference(reference: str):
    hook = HOOK.read_text(encoding="utf-8")
    assert "rules/risk-tiers.md" in hook
    assert reference not in hook, (
        f"훅이 {reference} 를 주입하면 분리가 무의미해짐 — 바이트는 그대로 매 세션에 실림."
    )


def test_the_first_action_mandate_paragraph_ends_with_the_mandate():
    """명령문 문단이 승격 축 설명으로 끝나면 명령의 무게가 그리로 새어 나감(실측)."""
    principle = _section(RULE.read_text(encoding="utf-8"), "## Principle")
    assert principle, "## Principle 절을 못 찾음 — 제목이 바뀌었으면 이 가드도 같이 옮기세요."
    assert "their own axis" not in principle, (
        "승격 축 설명이 FIRST-action 명령문 옆으로 돌아왔음 — 상류 실측에서 이 두 줄이 "
        "호출률을 0.82 에서 0.55 로 떨어뜨렸습니다. promotion.md 로 옮기세요."
    )


def test_the_promotion_axis_note_survives_in_the_deferred_reference():
    heading = "## Promotion events (Staging / Release)"
    events = _section(PROMOTION.read_text(encoding="utf-8"), heading)
    assert "their own axis" in events, (
        "승격 축 설명이 Principle 에서 빠지면서 아예 사라짐 — 옮기는 것이지 지우는 것이 아님."
    )
