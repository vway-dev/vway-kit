"""`mask_examples` — 예시를 덮되 좌표는 남기는가.

`srs_check._strip_examples` 와 제외 대상은 같고 다른 점이 하나임: 앵커가 몇째 줄
몇째 칸인지 보고해야 하는 소비자를 위해 길이를 보존함. 그 보존이 깨지면 `alm_docs`
가 보고하는 줄 번호가 조용히 어긋남.
"""

import scripts._md_anchors as ma


def test_a_fence_keeps_its_line_count():
    text = "a\n```\nx\ny\n```\nb\n"
    masked = ma.mask_examples(text)
    assert masked.splitlines() == ["a", "   ", " ", " ", "   ", "b"]


def test_an_anchor_after_a_fence_keeps_its_line_number():
    text = '```\n<a id="fr-x-001"></a>\n```\n<a id="fr-x-002"></a>\n'
    masked = ma.mask_examples(text).splitlines()
    assert ma._ANCHOR_ID_RE.findall(masked[1]) == []
    assert ma._ANCHOR_ID_RE.findall(masked[3]) == ["fr-x-002"]


def test_an_anchor_inside_an_html_comment_is_masked():
    text = '<!-- <a id="fr-x-001"></a> -->\n'
    assert ma._ANCHOR_ID_RE.findall(ma.mask_examples(text)) == []


def test_a_comment_at_the_end_of_a_real_line_leaves_the_anchor_standing():
    text = '<a id="fr-x-001"></a>**FR-X-001** 결제함. <!-- alm: dev3/REQ-1 -->\n'
    masked = ma.mask_examples(text)
    assert ma._ANCHOR_ID_RE.findall(masked) == ["fr-x-001"]
    assert "alm:" not in masked


def test_a_multiline_comment_keeps_its_line_count():
    text = "a\n<!--\nx\n-->\nb\n"
    assert len(ma.mask_examples(text).splitlines()) == 5
