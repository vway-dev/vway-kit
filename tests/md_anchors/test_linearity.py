"""성능 계약 — 앵커 스캔이 문서 길이의 제곱으로 자라지 않음.

`[^>]*` 는 `<` 를 넘으므로 `>` 가 없는 구간에서 `<a ` 시작 자리마다 남은 본문 전체를
훑고 되돌아옴(시작 자리 × 길이). 여기는 게이트 경로가 아니라 `/harness-init`·`srs_check`
에서 사람이 기다리는 시간이지만, 배가당 4배는 큰 트리에서 분 단위가 됨.
"""

import time

import pytest

import scripts._md_anchors as ma

# 반복 횟수를 크게 잡는 이유는 계수가 제일 작은 `_A_TAG_RE` — 작은 입력에서는 그것만 옛
# 패턴에서도 문턱 안에 들어(다른 둘은 이미 넘음) 고치기 전에도 초록인 테스트가 됨. 옛
# 패턴은 배가마다 네 배로 자라므로 네 배 키운 이 크기에서는 셋 다 문턱을 넘고, 새 패턴은
# 선형이라 여유가 크게 남음. 초 단위 수치는 기계·부하에 매달려 안 적음 — 문턱과 이 크기가
# 계약이고, 자라는 차수가 근거임.
_REPEAT = 4096


@pytest.mark.parametrize(
    "name",
    ["_A_TAG_RE", "_HTML_TAG_RE", "_ANCHOR_ID_RE"],
)
def test_the_tag_scan_stays_linear(name: str):
    """`>` 가 한 번도 안 닫히는 본문 — 이차성이 드러나는 유일한 모양."""
    text = ("<a " + "x" * 64 + "\n") * _REPEAT
    started = time.perf_counter()
    getattr(ma, name).findall(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2, f"{name}: {elapsed:.3f}s — 선형이면 수 ms 임"


# 문자열 부분열 매칭(`"[^<>]" in pattern`)은 취약한 패턴이 다른 자리에 `[^<>]` 를 끼워
# 넣기만 해도 속고, 같은 뜻의 다른 표현으로 선형화해도 억울하게 붉어짐 — 런타임 매치
# 결과로 봄. `_ANCHOR_ID_RE` 의 같은 성질은
# `test_an_id_on_a_following_tag_is_not_this_anchors_id` 가 이미 잼(겹쳐서 여기 안 둠).
_CROSS_CASES = {
    "_A_TAG_RE": ('<a foo <a id="x">', ['<a id="x">']),
    "_HTML_TAG_RE": ("<a foo <b>", ["<b>"]),
}


@pytest.mark.parametrize("name", list(_CROSS_CASES))
def test_the_tag_body_cannot_cross_a_new_tag(name: str):
    """`<` 를 넘는 순간 매치가 거기서 멈춤 — 옛 패턴은 두 태그를 하나로 먹었음."""
    text, expected = _CROSS_CASES[name]
    assert getattr(ma, name).findall(text) == expected


def test_an_id_on_a_following_tag_is_not_this_anchors_id():
    """`<a <b id="x">` 는 `b` 의 id — 옛 패턴은 이것을 앵커로 셌음."""
    assert ma._ANCHOR_ID_RE.findall('<a <b id="x">') == []
    assert ma._ANCHOR_ID_RE.findall('<a id="x"></a>') == ["x"]
