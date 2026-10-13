"""성능 계약 — 훅 타임아웃은 조용히 건너뛴 게이트.

앵커이면서 동시에 별표의 먹이인 글자를 별표 앞에 두지 않음. `search` 는 첫 매치에서
반환하므로 시간 가드가 **루프**도 재야 함.
"""

import pytest

import scripts._vway_paths as vp


@pytest.mark.parametrize(
    # 예약어 갈래도 앵커임 — 그 글자들이 별표의 먹이면 2차. `search` 는 첫 매치에서
    # 반환하므로 그 가드가 못 보고, 이 루프에서만 드러남(실측: 러너 wall 128KB 95초).
    "unit",
    # 접두를 걷는 걸음도 함께 잼 — 리다이렉션의 숫자 접두와 대입의 값은 별표이고,
    # 명령 시작마다 그 뒤 전체를 다시 훑으면 2차가 됨.
    ["do:", "if:", "while:", "!x", "a", "/", "x/y", "\x00", "-", "!", "1", ">", "a=", "&"],
    ids=lambda u: repr(u),
)
def test_the_program_scan_stays_linear(unit: str):
    import time

    started = time.perf_counter()
    vp._programs(unit * 16000)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2, f"{unit!r}: {elapsed:.3f}s — 선형이면 수 ms 다"


def test_the_interpreter_pattern_carries_no_star_prefix():
    """앵커이면서 동시에 별표의 먹이인 글자가 2차를 만듦 — 이 파일이 세 번 겪은 회귀.

    `{`·`}`·백틱만 뺀 판으로는 부족함: `+`·`=`·`$`·`<`·`>` 를 비롯한 17종과, 무엇보다
    **마스크의 채움 문자인 NUL** 이 그대로 남아 16K 에서 1.8초(실측). 긴 인용 인자와
    heredoc 본문은 통째로 NUL 이므로 그건 병리 입력이 아니라 평범한 명령. 나머지 패턴들은
    아래 시간 가드가 앵커 글자 하나하나에 대해 잼.
    """
    # `_GIT_TOKEN_RE` 도 같음. 먹이를 앵커 **문자 집합**의 여집합으로 파생하는 것으로는
    # 부족했음: 앵커 갈래 하나가 두 글자(`\n`·`\t`·`\r`)라 그 첫 글자인 백슬래시가 여집합
    # 안에 그대로 남아 양쪽에 들었고, `\n`×32000 에서 16.5초였음(실측). 그래서 접두를
    # 별표가 아니라 폭 없는 lookbehind 로 받음.
    assert "*" not in vp._GIT_TOKEN_RE.pattern, vp._GIT_TOKEN_RE.pattern
    # 명령 시작과 프로그램 이름도 같음 — 디렉터리 접두를 별표로 적으면 **예약어 갈래**가
    # 그 먹이가 됨(실측: 러너 wall 128KB 95초). 접두는 `_program_name` 이 파이썬에서
    # 벗기고, 그쪽은 매치된 토큰 위에서만 돌아 O(토큰).
    assert "*" not in vp._COMMAND_START_RE.pattern, vp._COMMAND_START_RE.pattern
    assert "*" not in vp._PROGRAM_NAME_RE.pattern, vp._PROGRAM_NAME_RE.pattern


@pytest.mark.parametrize(
    # 명령 시작 앵커 **전부**(자동으로 따라옴)에 더해, 마스크의 채움 문자와 그때 2차로
    # 남아 있던 글자들. 앵커가 늘면 이 가드도 함께 늘어남.
    "unit",
    sorted(set(vp._CMD_START_CHARS) | set("\x00+=$<>'\"./\\ a")),
    ids=lambda ch: f"u{ord(ch):04x}",
)
def test_every_scanner_regex_stays_linear(unit: str):
    """훅에서의 2차는 타임아웃이고, 타임아웃은 판정을 건너뛰는 것과 같음."""
    import time

    for name in (
        "_GIT_TOKEN_RE",
        "_COMMAND_START_RE",
        "_COMMAND_PREFIX_RE",
        "_PROGRAM_TOKEN_RE",
        "_PROGRAM_NAME_RE",
        "_RESERVED_TAIL_RE",
        "_SUBSTITUTION_RE",
        "_LIST_SEPARATOR_RE",
        "_CD_PREFIX_RE",
        # 창(`_EXECUTES_NEXT_WINDOW`)이 실제 지연을 막고 있었지만, 창이 넓어지는 순간
        # 살아나는 잠복 결함(백틱 16K 에서 1.9초, 실측). 규칙 쪽을 고치고 여기서 잼.
        "_EXECUTES_NEXT_RE",
    ):
        pattern = getattr(vp, name)
        started = time.perf_counter()
        pattern.search(unit * 16000)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.2, f"{name} on {unit!r}: {elapsed:.3f}s — 선형이면 수 ms 다"


@pytest.mark.parametrize(
    "shape",
    [
        "tee docs/notes.md <<'EOF'\n{body}\nEOF",
        "gh pr create --body-file - <<'EOF'\n{body}\nEOF",
        "gh pr create --body '{body}'",
        "curl -d '{body}' https://example.test  # git commit",
        "bash -c '{body}'",
    ],
    ids=["heredoc", "gh-file", "gh-quote", "curl", "bash-c"],
)
def test_a_long_ordinary_command_is_classified_in_milliseconds(shape: str):
    """평범한 명령 — 16KB 본문에서 2초, 32KB 에서 8초, 64KB 에서 64초(실측).
    그 곡선을 외삽하면 훅 timeout 600초 = 실측 약 196KB 부터 판정이 아예 없음."""
    import time

    command = shape.format(body="x" * 32000)
    vp._shell_regions.cache_clear()
    started = time.perf_counter()
    vp.is_invocation(command, "commit")
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5, f"{elapsed:.3f}s — 선형이면 수십 ms 다"


@pytest.mark.parametrize(
    # 한 글자 단위로는 **두 글자짜리 앵커**를 철자할 수 없어, 위 가드가 그것을 영영 못 봄.
    # `\n`·`\t`·`\r` 이스케이프가 그 앵커이고, 그 첫 글자인 백슬래시는 Windows 경로 구분자라
    # 흔함 — 병리 입력이 아니라 `printf 'a\nb\nc' | xargs` 의 평범한 모양임.
    "unit",
    [chr(92) + "n", chr(92) + "t", chr(92) + "r", chr(92) + "n" + chr(92), "x" + chr(92), "a/"],
    ids=["esc-n", "esc-t", "esc-r", "esc-n-bs", "x-bs", "dirsep"],
)
def test_the_token_scanners_stay_linear_on_a_two_character_anchor(unit: str):
    r"""앵커가 두 글자면 그 첫 글자가 별표의 먹이 안에 남기 쉬움 — 문자 집합의 여집합으로
    먹이를 파생해도 안 빠짐. 실측 16.5초(`\n`×32000)를 낸 회귀가 그것이었고, 한 글자 단위만
    재던 가드는 통과했음."""
    import time

    # 단위 목록이 **실제 갈래 전부**를 덮는지 못 박음 — 갈래가 늘면 여기서 걸림.
    # `_TOKEN_BOUNDARY` 는 `[문자집합]|<두 글자 갈래>` 꼴이고, 두 글자짜리는 지금 하나뿐임.
    # 문자 집합이 닫히는 `]|` 에서 가름 — `rsplit("|")` 은 **마지막** 갈래만 못 박아,
    # 앞에 끼워 넣은 새 갈래가 그대로 통과함(실측). 갈래 전체를 봐야 목록이 뒤처진 것이 걸림.
    assert vp._TOKEN_BOUNDARY.split("]|", 1)[1] == r"\\[ntr]", vp._TOKEN_BOUNDARY

    text = unit * 16000
    started = time.perf_counter()
    vp._GIT_TOKEN_RE.search(text)
    vp._standalone_word(text, "commit")
    vp._CD_PREFIX_RE.match("cd " + text)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2, f"{unit!r}: {elapsed:.3f}s — 선형이면 수 ms 다"


def test_each_operand_token_is_split_once(monkeypatch):
    """겹마다 한 번 만든 판이 선형을 지킴 — 가르기 횟수는 토큰 수를 따라가지, 토큰 × 그
    토큰을 덮는 호출 수를 따라가지 않음. 백틱 연쇄는 닫는 백틱 뒤의 `git` 이 저마다 명령
    끝까지 가는 영역을 가져, 영역마다 새로 가르면 길이의 제곱이었음(실측: 400 단위 2.9초)."""
    import scripts.vdev_gate_check as fgc

    calls = []
    real = vp._Level.split
    monkeypatch.setattr(vp._Level, "split", lambda self, *a: calls.append(a) or real(self, *a))
    for n in (50, 100):
        command = "git switch dev `git merge --squash feature/x` " * n
        calls.clear()
        for cached in (vp._levels, vp._substitution_tree, vp._children, fgc._live_calls):
            cached.cache_clear()
        masked = vp.mask_literals(command)
        judged = fgc._judged(command, masked)
        fgc._switch_targets(command, masked, [j.call for j in judged])
        assert len(judged) == n
        assert len(calls) <= 2 * len(command.split()), (n, len(calls))
