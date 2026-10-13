"""산문 문체 검사기의 판정 — 무엇을 산문으로 읽고, 무엇을 위반으로 부르는가.

이 검사기의 값은 규칙 목록이 아니라 **오탐률**에 있음. 코드 블록 한 줄이나 조사 하나를
위반으로 부르면 CI 가 아무도 고칠 수 없는 이유로 붉어지고, 그 다음부터 이 잡은 전부 무시됨.
그래서 테스트의 절반은 "이건 위반이 아니다"를 고정 — 펜스 안·front matter·인라인 코드·
URL·합쇼체·조사가 그것.

한글 보정이 이 repo 고유 부분. 상류 정규식 `[가-힣]다`는 vway-kit 실측에서 합쇼체
285건과 조사 `마다`·`보다` 11건을 오탐으로 잡음([doc-style.md](../../rules/doc-style.md)
규칙 1 이 README·USAGE 합쇼체를 명시 예외로 두므로 그 285건은 규칙상 위반이 아님).
아래 테스트가 그 경계를 고정.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.doc_style_check import (
    BANNED,
    KOREAN_ENDING,
    SILENCED_BY_ITS_CONDITIONS,
    lint_text,
    markdown_prose,
    prose_of,
    python_prose,
    shell_prose,
)


def codes(path: str, text: str) -> list[str]:
    """`path` 이름으로 읽은 `text` 의 위반 코드 목록(줄 순서)."""
    return [code for _sev, _line, code, _msg in lint_text(Path(path), text)]


# ---------- 산문 추출 ----------


def test_markdown_skips_front_matter_and_fences():
    text = "\n".join(
        [
            "---",
            "name: previously-named",  # front matter 는 산문이 아님
            "---",
            "본문 한 줄.",
            "```bash",
            "echo previously",  # 펜스 안은 산문이 아님
            "```",
            "끝.",
        ]
    )
    got = [line for _n, line in markdown_prose(text)]
    assert "본문 한 줄." in got
    assert "끝." in got
    assert not any("previously" in line for line in got)


def test_markdown_reads_indented_fence_as_a_block():
    """목록 안의 펜스는 들여쓰기가 붙음. 이걸 산문으로 읽으면 코드가 위반이 됨."""
    text = "\n".join(
        [
            "- 항목:",
            "  ```python",
            "  x = 'just actually'",
            "  ```",
            "- 다음 항목",
        ]
    )
    got = [line for _n, line in markdown_prose(text)]
    assert not any("just actually" in line for line in got)


def test_markdown_deeper_fence_inside_a_block_is_content():
    """4-백틱 블록 안의 3-백틱은 내용임. 닫는 것으로 읽으면 그 아래 문서가 통째로 샘."""
    text = "\n".join(
        [
            "````markdown",
            "```bash",
            "echo just",
            "```",
            "````",
            "바깥 산문.",
        ]
    )
    got = [line for _n, line in markdown_prose(text)]
    assert "바깥 산문." in got
    assert not any("just" in line for line in got)


def test_python_prose_is_comments_and_every_docstring():
    text = (
        '"""모듈 독스트링."""\n\n\n# 주석 하나\ndef f():\n    """함수 독스트링."""\n    return 1\n'
    )
    got = [line for _n, line in python_prose(text)]
    assert "모듈 독스트링." in got
    assert "주석 하나" in got
    assert "함수 독스트링." in got
    assert "return 1" not in got


def test_python_type_comment_is_not_prose():
    got = [line for _n, line in python_prose("x = 1  # type: int\n")]
    assert got == []


def test_shell_prose_skips_shebang_and_directives():
    text = "#!/usr/bin/env bash\n# shellcheck disable=SC2086\n# 진짜 주석\necho hi\n"
    got = [line for _n, line in shell_prose(text)]
    assert got == ["진짜 주석"]


def test_unknown_suffix_has_no_prose():
    assert prose_of(Path("a.txt"), "previously broken") == []


# ---------- 마스킹: 코드·URL·링크는 산문이 아님 ----------


def test_inline_code_and_url_are_masked():
    assert codes("a.md", "설정 키는 `just` 임") == []
    assert codes("a.md", "https://example.com/simply/actually 참고") == []


def test_link_target_is_masked_for_every_rule_but_plan():
    # 링크 목적지의 `simply` 는 경로이지 산문이 아님.
    assert codes("a.md", "[문서](docs/simply/x.md) 참고") == []
    # 그런데 plans/ 로의 링크는 PLAN 이 금지하는 그 포인터 자체임.
    assert codes("a.md", "[플랜](docs/superpowers/plans/x.md) 참고") == ["PLAN"]


def test_backticked_plan_path_names_the_pattern_and_is_not_a_pointer():
    assert codes("a.md", "`docs/superpowers/plans/` 아래는 검사 대상 아님") == []


# ---------- 규칙 ----------


def test_hist_flags_history_narration_both_languages():
    assert codes("a.md", "This was previously wrong") == ["HIST"]
    assert codes("a.md", "이전에는 다른 값이었음") == ["HIST"]


def test_hist_does_not_flag_the_passive_of_use():
    assert codes("a.md", "This value is used to key the cache") == []
    assert codes("a.md", "It used to be a list") == ["HIST"]


def test_sha_flags_a_commit_sha_but_not_a_number_or_a_word():
    assert codes("a.md", "커밋 4cd7259 참고") == ["SHA"]
    assert codes("a.md", "빌드 20240115 기준") == []
    assert codes("a.md", "deadbeef 라는 낱말") == []
    assert codes("a.md", "Built from abc1234-dirty.") == ["SHA"]
    assert codes("a.md", "Tagged release-abc1234 for the demo.") == ["SHA"]


@pytest.mark.parametrize(
    "prose",
    [
        "Request 3f2b9c1a-7d4e-4b1a-9c2d-1e5f6a7b8c9d returned 404.",
        "If something went wrong, rerun with --verbose.",
        "A date in the past is rejected.",
        "과거에 만든 파일도 읽음",
    ],
)
def test_ordinary_prose_passes(prose: str):
    """UUID 의 묶음은 sha 가 아니고, 과거를 가리키는 낱말은 현재를 말할 때도 쓰임."""
    assert codes("a.md", prose) == []


def test_front_matter_behind_a_byte_order_mark_is_still_front_matter():
    assert codes("a.md", "﻿---\nauthor: Jane Doe\n---\n\n# Title\n") == []


def test_plan_flags_a_checklist_item():
    assert codes("a.md", "- [ ] 남은 단계") == ["PLAN"]
    assert codes("a.md", "- 남은 단계") == []


def test_filler_flags_connectives_only_when_they_join_sentences():
    assert codes("a.md", "However, this fails") == ["FILLER"]
    assert codes("a.md", "however small the input") == []


def test_claim_flags_a_hedged_magnitude_both_languages():
    assert codes("a.md", "This is approximately 3 times the cost") == ["CLAIM"]
    assert codes("a.md", "roughly the same shape") == ["CLAIM"]
    assert codes("a.md", "30% faster than the loop") == ["CLAIM"]
    assert codes("a.md", "대략 그 정도 크기") == ["CLAIM"]
    assert codes("a.md", "약 3배 크기") == ["CLAIM"]
    assert codes("a.md", "2배 빠름") == ["CLAIM"]


def test_claim_is_a_warning_and_leaves_bare_numbers_alone():
    """맨 숫자는 추측만큼이나 자주 경계값·측정값임 — 어느 쪽인지는 패턴이 못 가름.

    그 판정은 `rules/doc-style.md` 가 사람에게 맡긴 것이고, 여기서 세면 상한·타임아웃·
    스키마 경계를 적은 문서가 전부 붉어짐."""
    found = lint_text(Path("a.md"), "roughly 2x")
    assert [sev for sev, _l, code, _m in found if code == "CLAIM"] == ["warning"]
    assert codes("a.md", "타임아웃 상한 30초") == []
    assert codes("a.md", "reps 5 에서 0.76 (n=25)") == []


def test_claim_reads_the_irregular_conjugation_of_fast():
    """르불규칙(빠르다→빨라)이 한국어에서 제일 흔한 활용인데 어간만 보면 통째로 미탐."""
    assert codes("a.md", "3배 빨라짐") == ["CLAIM"]
    assert codes("a.md", "1.5배 느려짐") == ["CLAIM"]


def test_claim_is_silent_on_a_line_that_carries_its_own_conditions():
    """규칙이 명시적으로 허용하는 꼴 — 「누군가 잰 수치, 그것을 낸 조건과 함께」.

    이 트리의 성능 주석은 실측 곡선을 적은 뒤 `배수마다 약 4배` 로 요약함. 그 줄까지 세면
    영구히 켜진 경고가 되고, 영구히 켜진 경고는 신호가 아님."""
    assert codes("a.md", "16KB 2.7초·32KB 7.1초였음(실측, 배수마다 약 4배)") == []
    assert codes("a.md", "roughly a third, measured at 6/25") == []
    # 조건 없이 선 같은 크기는 그대로 걸림 — 침묵의 근거는 같은 줄의 측정뿐임.
    assert codes("a.md", "배수마다 약 4배") == ["CLAIM"]


def test_the_silencer_tokens_do_not_leak_into_neighbouring_words():
    """`n`·`measured` 에 경계가 없으면 측정과 무관한 줄이 조용해짐 — 그중 하나는 자멸적임:
    `unmeasured` 를 실은 줄이 바로 그 규칙에서 면제됨."""
    assert codes("a.md", "len=3 이면 roughly 절반") == ["CLAIM"]
    assert codes("a.md", "plan=3 에서 약 4배") == ["CLAIM"]
    assert codes("a.md", "This is an unmeasured 30% faster claim") == ["CLAIM"]
    # 진짜 조건은 그대로 침묵시킴.
    assert codes("a.md", "reps 3 에서 0.76 (n=15) — 약 4배") == []
    assert codes("a.md", "measured at 6/25, roughly a third") == []


def test_the_silencer_reaches_no_rule_but_claim():
    """침묵기는 CLAIM 전용 — 다른 규칙이 같은 줄에서 면제되면 `실측` 한 낱말이 문체 검사
    전체의 우회로가 됨."""
    assert set(SILENCED_BY_ITS_CONDITIONS) == {"CLAIM"}
    assert codes("a.md", "실측: 이전에는 다른 값이었음") == ["HIST"]
    assert codes("a.md", "measured 4cd7259 커밋 참고") == ["SHA"]


@pytest.mark.parametrize("unit", [".", "0.", "1.", "0.0", "가", " "], ids=lambda u: f"unit-{u!r}")
def test_every_banned_pattern_stays_linear(unit: str):
    """검사기 정규식은 커밋 게이트 안에서 돎 — 훅 타임아웃은 조용히 건너뛴 판정임.

    `CLAIM` 이 이 가드를 받기 전 `[0-9.]+` 가 앵커(`%`·`배`) 뒤에 있어 `search` 가 시작
    위치마다 숫자 런 전체를 다시 훑었음: 32KB 에서 19.8초, 96KB 에서 171.6초(실측,
    배가마다 4배). 나머지 다섯 규칙은 같은 입력에서 수 ms 였음."""
    import time

    line = unit * (16000 // len(unit))
    for code, _sev, pattern, _msg in BANNED:
        # 단위가 어떤 패턴에 매치되면 `search` 가 첫 매치에서 반환해 가드가 공허해짐 —
        # 재는 것이 되돌아가기(backtracking)이지 매치가 아니므로 병리 입력은 조용해야 함.
        assert pattern.search(unit * 3) is None, f"{code} 가 {unit!r} 에 매치 — 가드가 빔"
        started = time.perf_counter()
        pattern.search(line)
        elapsed = time.perf_counter() - started
        # 자매 가드(`tests/vway_paths/test_linearity.py`)와 같은 0.2초. 0.5 로 두면 상수가
        # 작은 2차가 이 길이에서 0.248초로 통과함(실측).
        assert elapsed < 0.2, f"{code} on {unit!r}: {elapsed:.3f}s — 선형이면 수 ms 다"


def test_claim_leaves_words_that_merely_end_in_the_hedge_syllable():
    """한국어엔 낱말 경계가 없음 — `약` 앞의 lookbehind 가 없으면 `계약 3건` 이 헤지로 읽힘."""
    assert codes("a.md", "계약 3건") == []
    assert codes("a.md", "요약 2줄") == []
    assert codes("a.md", "절약 1회") == []


def test_long_is_a_warning_and_tables_are_exempt():
    long_prose = "가" * 101
    assert [sev for sev, _l, code, _m in lint_text(Path("a.md"), long_prose) if code == "LONG"] == [
        "warning"
    ]
    assert "LONG" not in codes("a.md", "| " + "가" * 101 + " |")


# ---------- 한글 종결 보정 (vway-kit 고유) ----------


@pytest.mark.parametrize(
    "line",
    [
        "게이트가 커밋을 막는다.",
        "마커는 편집마다 지워진다.",
        "이것은 정책이다.",
        "그런 경로는 없다.",
        "티어는 둘로 갈린다",  # 마침표 없이 줄 끝
        "산출물이 스스로 말하지 못하는 것만 쓴다 — 생성하는 모든 주석에 적용",  # 문장 중간
        "무해하게 wiki 밖에 머문다). -->",  # 닫는 괄호 앞
    ],
)
def test_ending_flags_declarative_endings(line):
    assert codes("a.md", line) == ["ENDING"]


@pytest.mark.parametrize("line", ["게이트가 막는다면 재커밋함", "값이 없다는 뜻임"])
def test_ending_does_not_flag_connective_stems(line):
    """금지 대상은 종결이지 어간이 아님 — `~다면`·`~다는` 은 문장을 이음."""
    assert codes("a.md", line) == []


@pytest.mark.parametrize(
    "line",
    [
        "이 값을 설정합니다.",  # 합쇼체 — doc-style.md 규칙 1 예외
        "게이트가 커밋을 막습니다.",
        "여기서 설치됩니다",
        "변경 파일마다 대조함",  # 조사 `-마다`
        "예상보다 느림",  # 조사 `-보다`
        "세션마다",
        "과다 매칭 비용은 spawn 하나",  # 명사 `과다`
        "어쩌다 키가 없으면 최상위 절로 삽입",  # 부사 `어쩌다`
        "람다 함수를 쓰면 됨",  # `-다` 로 끝나는 외래어 명사
        "AWS 람다 기반 배포",
    ],
)
def test_ending_does_not_flag_polite_style_or_particles(line):
    assert codes("a.md", line) == []


def test_ending_still_flags_anida_despite_the_polite_exception():
    """`아니다` 는 `니다` 로 끝나지만 합쇼체가 아니라 서술형 종결임."""
    assert codes("a.md", "그건 게이트가 아니다.") == ["ENDING"]


def test_ending_reads_python_docstrings_too():
    assert codes("a.py", '"""이 함수는 경로를 돌려준다."""\n') == ["ENDING"]


def test_a_declarative_ending_before_a_colon_is_caught():
    """콜론 앞 종결 — 열거를 여는 문장이 서술형으로 끝나는 가장 흔한 자리.

    후행 문자 집합에서 `:` 가 빠진 동안 저장소에 34건이 살아 있었고, 그중 하나도 다른
    규칙에 안 걸렸음. 종결 판정을 **따라오는 문자**로 하는 설계라 빠진 문자 하나가 곧
    빠진 자리 하나임.
    """
    assert KOREAN_ENDING.search("아래 순서로 처리한다:")
    assert KOREAN_ENDING.search("소유권이 다르다: vdev-config 는")
    # 조사·명사의 끝은 그대로 빠짐 — 집합을 넓힌 것이지 제외를 푼 것이 아님.
    assert not KOREAN_ENDING.search("파일마다: 하나씩")
    assert not KOREAN_ENDING.search("람다: 함수")
