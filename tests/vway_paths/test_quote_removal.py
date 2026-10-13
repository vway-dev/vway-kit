"""bash 그대로의 인용 제거와, 다시 훑지 않는 문법 검색.

인용 제거 판은 인용이 쪼갠 낱말을 bash 가 돌리는 낱말로 다시 이음. 아래 철자는 인자를
찍는 스텁 `git` 으로 bash 에 대 본 것."""

import random
import re
import shlex
import time

import pytest

import scripts._vway_paths as vp

BS = chr(92)


@pytest.mark.parametrize(
    "text,value",
    [
        ("com''mit", "commit"),
        ('com""mit', "commit"),
        (f"c{BS}ommit", "commit"),
        (f"co{BS}\nmmit", "commit"),
        (f"co{BS}\r\nmmit", "commit"),
        # 큰따옴표 안의 백슬래시는 $ ` " \ 개행만 인용함
        (f'"C:{BS}Git{BS}git.exe"', f"C:{BS}Git{BS}git.exe"),
        (f'"a{BS}$b{BS}"c{BS}{BS}d"', f'a$b"c{BS}d'),
        (f'"co{BS}\nmmit"', "commit"),
        # 작은따옴표는 모든 글자를 그대로
        (f"'C:{BS}Git'", f"C:{BS}Git"),
        # ANSI-C 문자열은 이스케이프를 풀고, $"…" 는 큰따옴표 문자열
        (f"$'{BS}x63ommit'", "commit"),
        (f"$'{BS}143ommit'", "commit"),
        (f"$'{BS}u0063ommit'", "commit"),
        (f"$'{BS}U00000063ommit'", "commit"),
        (f"$'{BS}t{BS}n{BS}{BS}{BS}''", f"\t\n{BS}'"),
        (f"$'{BS}cA'", chr(1)),
        (f"$'{BS}q'", f"{BS}q"),
        (f"$'{BS}xZ'", f"{BS}xZ"),
        # 어떤 글자도 아닌 코드 포인트는 적힌 그대로
        (f"$'{BS}U7FFFFFFF'", f"{BS}U7FFFFFFF"),
        (f"$'{BS}ud800'", f"{BS}ud800"),
        # 본문은 백슬래시가 안 데려간 첫 따옴표에서 끝남 — `\c` 가 그 너머로 못 감
        (f"$'{BS}c' x", f"{BS}c x"),
        (f"$'a{BS}'b'", "a'b"),
        # `$` 와 따옴표 사이의 줄이음은 따옴표를 읽기 전에 사라짐
        (f"${BS}\n'{BS}x63ommit'", "commit"),
        ('$"commit"', "commit"),
        # 닫히지 않은 따옴표는 끝까지
        ("'commit", "commit"),
        ('"commit', "commit"),
        (f"{BS}", BS),
    ],
)
def test_quote_removal_matches_bash(text: str, value: str):
    assert vp._remove_quotes(text) == value


@pytest.mark.parametrize(
    "text,words",
    [
        (f"git $'{BS}x63ommit' -m x", ["git", "commit", "-m", "x"]),
        (f"git $'it{BS}'s' x", ["git", "it's", "x"]),
        ('git $"commit"', ["git", "commit"]),
        # 다른 인용 안의 `$'` 는 텍스트
        ("echo \"$'x'\"", ["echo", "$'x'"]),
        ("echo '$'x", ["echo", "$x"]),
        (
            f"git merge -m $'{BS}U7FFFFFFF' --no-ff dev",
            ["git", "merge", "-m", f"{BS}U7FFFFFFF", "--no-ff", "dev"],
        ),
    ],
)
def test_ansi_c_strings_reach_shlex_as_the_words_they_decode_to(text: str, words: list[str]):
    assert shlex.split(vp.requote_ansi_c(text)) == words


@pytest.mark.parametrize(
    "command,word",
    [
        # 큰따옴표 안 백슬래시는 남으므로 인용한 Windows 경로도 git — 바깥의 이스케이프한 것도
        (f"\"C:{BS}Program Files{BS}Git{BS}bin{BS}git.exe\" com''mit -m x", "commit"),
        (f"\"C:{BS}Git{BS}bin{BS}git.exe\" com''mit -m x", "commit"),
        (f"C:{BS}{BS}Git{BS}{BS}bin{BS}{BS}git.exe com''mit -m x", "commit"),
        (f"\"C:{BS}Git{BS}bin{BS}git.exe\" mer''ge --no-ff dev", "merge"),
        # ANSI-C 이스케이프는 낱말을 읽기 전에 풂
        (f"git $'{BS}u0063ommit' -m x", "commit"),
        (f"$'{BS}x67it' commit -m x", "commit"),
        (f"git $'{BS}x6derge' --no-ff dev", "merge"),
        # `$` 와 따옴표 사이의 줄이음도 ANSI-C 문자열을 엶
        (f"git ${BS}\n'{BS}x63ommit' -m x", "commit"),
        (f"git ${BS}\r\n'{BS}x63ommit' -m x", "commit"),
        # `\c` 는 닫는 따옴표를 제어 문자로 삼지 않음
        (f"git -c x=$'{BS}c' c{BS}ommit", "commit"),
        # 인터프리터용 인용에 감싼 스크립트는 그 인용도 벗긴 뒤 읽음
        ("eval 'git com\"\"mit'", "commit"),
        (f"bash -c 'git c{BS}ommit -m x'", "commit"),
        ("bash -c \"git com''mit -m x\"", "commit"),
        (f'sh -c "git c{BS}{BS}ommit"', "commit"),
        ("ssh host 'git com\"m\"it'", "commit"),
        ("bash -c 'git mer\"\"ge --no-ff dev'", "merge"),
        # eval 마다 백슬래시가 반으로 — 벗기는 횟수를 넘는 중첩은 지우는 읽기가 받음
        ("eval eval eval eval git c" + BS * 16 + "ommit", "commit"),
        # 인터프리터가 잇는 `$'` 가 인용으로 갈라져 있음
        (f'bash -c "git "{BS}$"\'{BS}x63ommit\'"', "commit"),
        # sh 가 큰따옴표와 백슬래시 하나를, eval 이 작은따옴표와 나머지 하나를 벗김
        (f"sh -c \"eval 'git c{BS}{BS}ommit'\"", "commit"),
        # `${…}` 안의 구분자는 명령을 끝내지 않음 — 거기서 끊으면 서브커맨드에 못 닿음
        (f"g{BS}it -c x=${{y:-a;b}} commit -m x", "commit"),
        (f"g{BS}it -c x=${{y//;/,}} commit -m x", "commit"),
        (f"g{BS}it -c x=${{y:-a&&b}} commit -m x", "commit"),
        # 확장되는 heredoc 본문은 `\$` 를 `$` 로 바꾼 뒤 ANSI-C 를 풂
        (f"bash <<E\ngit {BS}$'{BS}143'ommit -m x\nE", "commit"),
        (f"bash <<E\ngit m{BS}$'{BS}x65'rge stage\nE", "merge"),
        (f"cat <<E | bash\ngit {BS}$'{BS}x63'ommit -m x\nE", "commit"),
        # 그 안의 큰따옴표 겹 — 지운 판은 `$'…'` 를 문맥 없이 전부 풂
        (f"bash <<E\nbash -c \"git {BS}{BS}$'{BS}143'ommit -m x\"\nE", "commit"),
        (f"bash <<E\neval \"git {BS}{BS}$'{BS}143'ommit -m x\"\nE", "commit"),
        (f"cat <<E | bash\nbash -c \"git {BS}{BS}$'{BS}x6d'erge stage\"\nE", "merge"),
        (f"sh <<E\nbash -c \"git {BS}{BS}{BS}$'{BS}143'ommit -m x\"\nE", "commit"),
        # 앞의 `'…$'` 가 뒤 `$'…'` 의 해독을 어긋나게 해도 — 필요조건이 판정을 떨구면 안 됨
        (f"grep 'foo$' x; git $'{BS}x63ommit' -m x", "commit"),
        (f"echo \"$'\"; git $'{BS}x63ommit' -m x", "commit"),
        (f"grep -E '^v[0-9]+$' tags; git $'{BS}x6d'erge stage", "merge"),
        (f"X='a$'\ngit $'{BS}143'ommit -m x", "commit"),
        # 안쪽 겹의 짝수 백슬래시 — 한 번의 해독으로는 철자가 안 됨
        (f"eval \"git {BS}$'{BS}{BS}x63ommit' -m x\"", "commit"),
        (f"bash -c \"git {BS}$'{BS}{BS}143ommit' -m x\"", "commit"),
        (f"bash -c 'git $'{BS}''{BS}x63ommit'{BS}'''", "commit"),
        # 바깥 겹이 벗긴 뒤에야 안쪽 겹의 인용이 되는 글자 — 로캘 문자열과 줄이음
        (f'bash -c "git com${BS}"{BS}"mit -m x"', "commit"),
        (f'eval "git com{BS}${BS}"{BS}"mit -m x"', "commit"),
        (f"bash -c 'git com{BS}'\"\nmit -m x\"", "commit"),
        (f"bash -c 'git mer{BS}'\"\nge x\"", "merge"),
    ],
)
def test_the_unquoted_readings_find_the_invocation(command: str, word: str):
    assert vp.is_invocation(command, word)


@pytest.mark.parametrize(
    "command",
    [
        f"git log --grep=$'{BS}x63ommit'",
        f"git log --grep=$'{BS}U7FFFFFFF'",
        f"grep -rn \"C:{BS}Git{BS}bin{BS}git.exe com''mit\" .",
    ],
)
def test_a_decoded_argument_is_not_an_invocation(command: str):
    assert not vp.is_invocation(command, "commit")


def _corpus(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    pieces = [
        "git",
        "/usr/bin/git",
        "git.exe",
        "-C",
        "-",
        "-c",
        "x",
        "-a",
        "commit",
        "merge",
        ";",
        "&&",
        "|",
        "(",
        ")",
        "`",
        "a=b",
        "--no-ff",
        "mygit",
        "log",
        "\n",
        "'q'",
        "\x00",
    ]
    return [
        "".join(rng.choice(pieces) + rng.choice([" ", "", "  "]) for _ in range(rng.randint(1, 14)))
        for _ in range(count)
    ]


@pytest.mark.parametrize("word", ["commit", "merge", "(?:switch|checkout)"])
def test_the_linear_search_finds_what_the_regex_finds(word: str):
    """검색이 대체한 정규식 하나와, 생성한 명령에서 대조: 같은 span, 같은 옵션 영역, 시작
    자리를 준 검색까지."""
    grammar = vp.git_subcommand_re(word)
    plain = re.compile(grammar.pattern)
    for text in _corpus(7, 4000):
        want = [(m.span(), m.span(1)) for m in plain.finditer(text)]
        got = [(m.span(), m.span(1)) for m in grammar.finditer(text)]
        assert got == want, text
        for pos, end in ((1, len(text)), (0, len(text) // 2)):
            want = [(m.span(), m.span(1)) for m in plain.finditer(text, pos, end)]
            got = [(m.span(), m.span(1)) for m in grammar.finditer(text, pos, end)]
            assert got == want, (text, pos, end)


@pytest.mark.parametrize(
    "command",
    [
        "make " + "-a git " * 16000 + "; commit",
        "make " + "g''it -a " * 8000,
        "x " + "-a git " * 16000 + "-m commit",
        "python x " + "`a" * 20000 + " commit",
        "git log " + "a`" * 20000,
    ],
    # id 가 PYTEST_CURRENT_TEST 가 되고, Windows 는 그것을 32767자로 자름
    ids=["chain-then-separator", "split-git-chain", "chain-into-a-value", "backticks", "ticks"],
)
def test_a_chain_naming_git_does_not_stall_the_gate(command: str):
    """연쇄 속 `git` 마다 나머지를 다시 훑으면 안 됨 — 훅 타임아웃을 넘기면 판정이 없고,
    Invariant 1 이 그것을 게이트 없이 통과한 커밋으로 만듦(실측: 28KB 에서 7.7초)."""
    start = time.perf_counter()
    vp.is_invocation(command, "commit")
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"{len(command)} chars took {elapsed:.2f}s"


def test_a_program_that_cannot_be_git_is_not_peeled(monkeypatch):
    """벗긴 판의 프로그램 낱말은 지운 판의 것에 인용 글자를 더한 것뿐 — git 으로 안 끝나는
    프로그램마다 판을 벗기면 상수배가 네 배였음(실측: `gitv=$a`×25000 에서 10초 대 2초)."""
    peeled = []
    real = vp._remove_quotes
    monkeypatch.setattr(vp, "_remove_quotes", lambda t: peeled.append(t) or real(t))
    command = "gitv='$a' " * 200
    pattern = vp.git_subcommand_re("commit")
    assert not vp._joined_at_command_starts(command, vp.mask_literals(command), pattern)
    assert peeled == []


def test_a_run_of_separated_gits_does_not_stall_the_gate():
    """shlex 는 `;` 에서 낱말을 안 가름 — 자리마다 다음 구분자에서 끊지 않으면 `git;`×k 가
    남은 꼬리를 낱말 하나로 읽어 2차였음(실측: 32KB 에서 88초)."""
    command = "git;" * 8000
    start = time.perf_counter()
    vp.is_invocation(command, "commit")
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"{len(command)} chars took {elapsed:.2f}s"


def test_quoted_gits_without_the_word_stay_cheap_on_the_commit_path():
    """커밋 경로는 원소마다 `is_invocation` 을 물음 — 낱말이 아예 없는 원소까지 판을 다 만들면
    `"g"it;`×k 가 기준선의 두 배를 넘었음(실측: 200KB 에서 3.1초)."""
    command = '"g"it;' * 33000
    start = time.perf_counter()
    vp.commit_tree_unresolved(command)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"{len(command)} chars took {elapsed:.2f}s"
