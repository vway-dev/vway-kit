"""산문 ↔ 코드 대응 — 스킬 문서가 말하는 절차와 구현이 같은가.

둘이 어긋나면 사람은 문서대로 하고 게이트는 다르게 판정함.
"""

import re

import pytest

from scripts import wiki_graph
from tests.wiki._helpers import (
    _ARROW_EXAMPLE_RE,
    _EXAMPLES,
    _FENCE_CASES,
    _FENCE_RE,
    _LITERAL_ID_TEMPLATES,
    _REPO,
    _TABLE_ROW_RE,
    _step5_section,
)


def test_wiki_init_step5_table_is_parity_tested():
    # 표가 곧 테스트 케이스 — 산문 예제가 구현과 어긋나거나 표가 조용히 줄면 여기서 걸림.
    text = (_REPO / "skills" / "wiki-init" / "SKILL.md").read_text(encoding="utf-8")
    rows = _TABLE_ROW_RE.findall(_step5_section(text))
    # 짝이 안 맞는 펜스 하나면 비탐욕 페어링이 그것을 다음 절의 여는 펜스와 묶어 그 사이의
    # 표까지 삼키는데, `## 5.` 헤딩은 살아남아 위 블록 가드가 침묵함. 그러면 빈 표가 아래
    # 중복 단언을 공허하게 지나고 실패는 마지막 줄에서 "표가 구현과 어긋난다"로만 드러남.
    assert rows, "§5 표를 못 찾았다 — 펜스 짝을 확인하라"
    # dict 로 접기 전에 셈 — 같은 경로가 두 줄이면 접힌 뒤에는 흔적이 없어, 표가 늘었다고
    # 믿는 동안 케이스는 그대로. SKILL.md 는 Markdown 이라 중복 행을 잡아줄 린터가 없음.
    assert len({path for path, _ in rows}) == len(rows), "§5 표에 경로가 중복된 행이 있다"
    assert dict(rows) == _EXAMPLES


@pytest.mark.parametrize(
    ("doc", "expected"),
    [(doc, expected) for doc, expected, _ in _FENCE_CASES],
    ids=[label for _, _, label in _FENCE_CASES],
)
def test_fence_stripping_leaves_exactly_the_rows_outside_fences(doc, expected):
    assert [path for path, _ in _TABLE_ROW_RE.findall(_FENCE_RE.sub("", doc))] == expected


def test_template_literal_ids_are_parity_tested():
    # 맵을 손으로 들지 않고 **템플릿 집합에서 파생**함: 리터럴 id 템플릿이 새로 생기면
    # 여기서 먼저 걸림 (바로 아래 주석 테스트가 경계하는 무음 표류와 같은 실패 모드).
    tpl_dir = _REPO / "skills" / "harness-authoring" / "templates"
    literal = {}
    for tpl in sorted(tpl_dir.glob("*.template.md")):
        m = re.search(r"^wiki_id: (\S+)$", tpl.read_text(encoding="utf-8"), re.MULTILINE)
        if m is not None and m.group(1) != "{{ID}}":
            literal[tpl.name] = m.group(1)
    assert set(literal) == set(_LITERAL_ID_TEMPLATES), (
        f"리터럴 wiki_id 템플릿 집합이 바뀌었다 — 출력 경로를 맵에 등록하라: {sorted(literal)}"
    )
    for name, wid in literal.items():
        assert wiki_graph.derive_wiki_id(_LITERAL_ID_TEMPLATES[name], "docs") == wid, name


def test_template_comment_examples_are_parity_tested():
    # harness-authoring 템플릿 YAML 주석의 워크드 예제 (docs/x.md -> id 또는 → 표기)도 같은
    # 규칙. 템플릿별로 개별 단언함 — 합계에 바닥값만 걸면, {{ID}} 를 쓰는 템플릿 중 하나가
    # 예제를 잃어도 다른 템플릿의 예제 수가 바닥을 채워 조용히 통과함(재현: sds 템플릿의
    # `->` 를 `→` 로만 바꿔도 예전 정규식으로는 합계가 3→2 로 줄어 바닥값 2를 여전히 넘김).
    tpl_dir = _REPO / "skills" / "harness-authoring" / "templates"
    id_templates = [
        tpl
        for tpl in sorted(tpl_dir.glob("*.template.md"))
        if "{{ID}}" in tpl.read_text(encoding="utf-8")
    ]
    assert id_templates, "{{ID}} 를 쓰는 템플릿이 없다"
    for tpl in id_templates:
        matches = _ARROW_EXAMPLE_RE.findall(tpl.read_text(encoding="utf-8"))
        assert matches, f"{tpl.name}: wiki_id 워크드 예제가 사라졌다"
        for path, expected in matches:
            assert wiki_graph.derive_wiki_id(path, "docs") == expected, tpl.name
