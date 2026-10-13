"""추출은 이동, 재작성이 아님 — 증거는 두 모듈 표면의 일치.

`harness_scaffold` 는 재정의가 아니라 재노출. 재정의면 어느 한쪽만 고쳐도 갈라지고,
둘 다 자기 테스트를 통과하므로 드리프트가 조용함.
"""

import scripts._md_anchors as ma
import scripts.harness_scaffold as hs


def test_harness_scaffold_reexports_the_moved_names():
    for name in ("_slugify", "_has_anchor", "_strip_frontmatter", "_strip_code"):
        assert getattr(hs, name) is getattr(ma, name), name


def test_module_defines_no_second_copy():
    src = (ma.__file__, hs.__file__)
    assert src[0] != src[1]
    body = open(hs.__file__, encoding="utf-8").read()
    for name in ("def _slugify", "def _has_anchor", "def _strip_frontmatter", "def _strip_code"):
        assert name not in body, f"{name} 가 harness_scaffold 에 아직 정의돼 있음"


def test_slugify_still_handles_the_hard_cases():
    assert ma._slugify("Step 1 — Classify the task") == "step-1--classify-the-task"
    assert ma._slugify("vdev_gate_check") == "vdev_gate_check"
    assert ma._slugify("Map<K,V>") == "mapkv"


def test_has_anchor_reads_an_explicit_id():
    assert ma._has_anchor('<a id="fr-payment-001"></a>**FR-PAYMENT-001**', "fr-payment-001")
    assert not ma._has_anchor("# Heading\n", "fr-payment-001")


def test_setext_heading_with_crlf_is_an_anchor():
    """Invariant 2 — 정규화되지 않은 CRLF 개행에서도 앵커 인식."""
    assert ma._has_anchor("Title\r\n=====\r\n", "title")


def test_heading_inside_code_fence_is_not_a_definition():
    """코드 펜스 안 `#` 은 예시 — 앵커 정의 대상에서 제외."""
    assert not ma._has_anchor("```\n# Not A Heading\n```\n", "not-a-heading")
