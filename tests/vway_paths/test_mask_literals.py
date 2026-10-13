"""`mask_literals` — 인용·이스케이프·주석·heredoc 을 읽는 **유일한** 자리.

인덱스 정렬이 계약(마스크된 사본과 원본의 같은 자리가 같은 글자여야 함).
커밋 메시지 안의 명령처럼 생긴 텍스트는 데이터고, 스캐너는 거기 속으면 안 됨.
"""

import pytest

import scripts._vway_paths as vp


def test_mask_literals_reads_a_quote_inside_the_other_quote_as_text():
    # 따옴표 문자마다 따로 짝을 세면 안 됨. `'…'` 안의 `"` 는 리터럴 한 글자이고,
    # `python3 -c '… "x" …'` 는 이 repo 스킬이 실제로 내는 모양 — 따로 세면 그
    # 뒤의 명령 전부가 따옴표 안으로 읽혀 진짜 커밋이 보이지 않음.
    text = """python3 -c 'print("x")' && git commit -m y"""
    masked = vp.mask_literals(text)
    # 인터프리터의 `-c` 인자는 리터럴이 아니라 그 인터프리터가 돌리는 **명령**이라, 구분자는
    # 공백이 되고 내용은 명령으로 스캔됨 — `bash -c 'git commit'` 의 커밋이 사라지지 않는
    # 것과 같은 이유. 안의 `"x"` 도 `(` 뒤라 명령 자리이므로 같은 취급을 받음.
    assert masked == "python3 -c  print( x )  && git commit -m y"
    # 어느 쪽이든 뒤 명령은 손대지 않은 채로 남아 호출로 읽힘.
    assert vp.is_invocation(text, "commit")
    # 실행되지 않는 인자에서는 span 이 통째로 덮임.
    assert vp.mask_literals("""echo 'print("x")'""") == "echo '" + "\x00" * 10 + "'"
    # 짝이 없는 따옴표는 문자열 끝까지 덮음 — 셸도 거기서 인용이 끝나지 않음.
    assert vp.mask_literals('git commit -m "abc') == 'git commit -m "' + "\x00" * 3


def test_parse_git_dash_c_ignores_a_git_commit_quoted_inside_the_message():
    # 메시지는 인자. 그 안에 적힌 `git -C <dir> commit` 은 텍스트이지 호출이 아님.
    # 이걸 실행 디렉터리로 읽으면 ROOT 가 커밋이 돌지 않는 트리를 가리켜, 그 트리의 티어
    # 마커·스테이징 파일을 읽음 — 분류된 커밋을 새로 막고 미분류 커밋을 통과시킴.
    assert vp._parse_git_dash_c('git -C /a commit -m "do not git -C /evil commit"') == "/a"
    assert vp._parse_git_dash_c('echo "git -C /b commit" && git -C /a commit -m x') == "/a"
    assert vp._parse_git_dash_c("echo 'git -C /b commit' && git -C /a commit -m x") == "/a"


def test_parse_git_dash_c_survives_a_body_that_says_commit_before_the_git():
    # commit 스킬은 메시지를 heredoc 으로 만들어 파이프함 — 본문 전체가 git 호출보다
    # **앞에** 옴. 본문은 게이트 명령 형태를 자주 인용하므로(Invariant 7 이 그러함)
    # 거기 적힌 `-C` 를 채택하면 안 되고, 진짜 호출의 `-C` 는 놓치면 안 됨.
    command = "\n".join(
        [
            "msg=$(cat <<'EOF'",
            "fix(gate): x",
            "",
            "- self-filter 는 `git -C /other/wt commit` 을 반드시 잡는다.",
            "EOF",
            ")",
            'printf %s "$msg" | git -C /a/b commit -F -',
        ]
    )
    assert vp._parse_git_dash_c(command) == "/a/b"


def test_parse_git_dash_c_reads_the_command_the_commit_skill_ships():
    # skills/commit Step 4 가 출하하는 블록 그대로: heredoc 메시지 → 길이 검사
    # python3 -c '…' → 파이프 → 워크트리 커밋. 본문은 이 repo 가 실제로 쓰는 대로
    # 게이트 명령 형태를 인용하고 홀수 개의 따옴표를 담음. 본문을 데이터로 끊지 않으면
    # 둘 다 무너뜨림 — 인용된 `git -C` 가 호출로 읽히고, 짝 없는 따옴표가 뒤 명령의
    # 따옴표와 짝지어져 구간 해석을 밀어 버림.
    command = "\n".join(
        [
            "msg=$(cat <<'EOF'",
            "fix(gate): 실행 디렉터리를 호출 하나에서 읽는다",
            "",
            '- `git -C "/other/wt" commit` 이 메시지 본문에 있으면 그걸 채택했다.',
            "- don't 처럼 홑따옴표 하나가 본문에 남아도 구간이 밀리지 않는다.",
            "EOF",
            ")",
            "python3 -c 'import sys",
            "t = sys.argv[1].splitlines()",
            'bad = ["still the template"] if not t else []',
            "if bad:",
            '    sys.exit("REWRITE")\' "$msg"   && printf \'%s',
            '\' "$msg" | git -C "C:/My Work/wt" commit -F -',
        ]
    )
    assert vp._parse_git_dash_c(command) == "C:/My Work/wt"


def test_mask_literals_keeps_every_index_aligned():
    # 마스킹은 같은 길이여야 함 — 길이가 바뀌면 마스크에서 찾은 오프셋으로 원본을 읽는
    # `dash_c_value` 가 엉뚱한 자리를 읽음.
    command = "cat <<'EOF'\nbody 'x' here\nEOF\ngit -C /a commit -m y"
    masked = vp.mask_literals(command)
    assert len(masked) == len(command)
    assert "body" not in masked
    # 본문 안의 개행도 덮임 — 본문의 줄바꿈은 명령 구분자가 아님. 여는 줄과 종결자
    # 줄의 개행은 본문 밖이라 남음.
    assert masked.count("\n") == 2
    assert masked.endswith("EOF\ngit -C /a commit -m y")


def test_mask_literals_finds_a_heredoc_terminator_on_a_crlf_line():
    # Windows 호스트가 보내는 명령은 CRLF 일 수 있고, 그러면 종결 줄이 `EOF\r`.
    # 못 찾으면 본문이 문자열 끝까지 간 것으로 보고 **진짜 호출까지** 덮어 버림 —
    # 워크트리 재지정이 조용히 사라짐(Invariant #2 가 노리는 부류의 Windows 사각).
    lf = "msg=$(cat <<'EOF'\nfix: x\nEOF\n)\nprintf %s \"$msg\" | git -C /wt commit -F -"
    assert vp._parse_git_dash_c(lf) == "/wt"
    assert vp._parse_git_dash_c(lf.replace("\n", "\r\n")) == "/wt"


def test_parse_git_dash_c_needs_an_actual_commit_subcommand():
    # 옵션 영역은 **커밋 호출**에 묶임. 체인의 다른 명령이 든 `-C` 를 실행 디렉터리로
    # 읽으면 커밋은 cwd 에서 도는데 게이트는 남의 트리를 검사함.
    assert vp._parse_git_dash_c("git -C /a log") is None
    assert vp._parse_git_dash_c("git -C /a log && git commit -m x") is None
    # `commit-graph`·`commitfoo` 는 커밋이 아님(셸 self-filter 와 같은 종결 규칙).
    assert vp._parse_git_dash_c("git -C /a commit-graph write") is None


def test_parse_git_dash_c_gives_up_only_when_the_tree_is_really_ambiguous():
    # 진짜 모호한 것은 **서로 다른 트리를 가리키는** 커밋 호출이 둘일 때뿐임.
    assert vp._parse_git_dash_c("git -C /a commit -m x && git -C /b commit -m y") is None
    # 하나는 -C 를 들고 하나는 cwd 에서 도는 경우 — 이것도 모호함.
    assert vp._parse_git_dash_c("git -C /a commit -m x ; git commit --amend --no-edit") is None
    # 같은 트리를 가리키는 호출이 여럿인 것은 모호하지 않음. 이걸 None 으로 만들면
    # ROOT 가 main 으로 떨어져, main 이 더러우면 오차단하고 깨끗하면 게이트가 통째로
    # 건너뛰어짐 — 미분류 커밋이 그대로 통과함(실측).
    assert vp._parse_git_dash_c("git -C /wt add . && git -C /wt commit -m x") == "/wt"
    assert (
        vp._parse_git_dash_c("git -C /wt commit -m x && git -C /wt commit --amend --no-edit")
        == "/wt"
    )


def test_parse_git_dash_c_counts_only_invocations_at_a_command_position():
    # `git commit` 이라는 **낱말**은 호출이 아님. 인자 자리·주석·다른 명령의 피연산자로
    # 흔히 나오고, 그걸 두 번째 호출로 세면 위 "모호" 판정이 발동해 게이트가 꺼짐.
    assert vp._parse_git_dash_c("git -C /wt commit -m x  # git commit again") == "/wt"
    assert vp._parse_git_dash_c("git -C /wt commit -m x && echo git commit done") == "/wt"
    # 반대로 진짜 명령 자리는 놓치면 안 됨 — 놓치면 모호 판정이 발동해 재지정을 잃고,
    # main 이 깨끗하면 러너가 아무것도 안 하고 exit 0 함(= 게이트 꺼짐, 실측).
    for opener in (
        'printf %s "$m" | git -C /wt commit -F -',
        "cd /x && git -C /wt commit -m y",
        "false || git -C /wt commit -m y",
        "true ; git -C /wt commit -m y",
        "true\ngit -C /wt commit -m y",
        "true\r\ngit -C /wt commit -m y",
        "out=$(git -C /wt commit -m y)",
        "out=`git -C /wt commit -m y`",
        "{ git -C /wt commit -m y; }",
        "if true; then git -C /wt commit -m y; fi",
        "for f in a; do git -C /wt commit -m y; done",
        "time git -C /wt commit -m y",
        "env GIT_X=1 git -C /wt commit -m y",
        "\tgit -C /wt commit -m y",
    ):
        assert vp._parse_git_dash_c(opener) == "/wt", opener


def test_the_option_word_splits_words_where_bash_splits_them():
    # bash 실측(스크립트 파일로 넘겨 확인): `git -c a=\\ commit -m x` 는 `<a=\> <commit>`
    # 으로 갈림 — `\\` 가 이스케이프된 백슬래시라 그 다음 공백이 진짜 구분자. 뒤 `\` 를
    # 이스케이프한 공백으로 읽으면 단어가 서브커맨드를 삼켜 명령이 통째로 안 보임.
    assert vp._parse_git_dash_c("git -c a=\\\\ -C /wt commit -m x") == "/wt"
    assert vp._parse_git_dash_c("git -c a=\\\\ commit -m x") is None  # 커밋이되 -C 가 없음
    # 반대로 `\` + 공백 하나는 이스케이프한 공백이라 단어가 이어짐. bash 는
    # `git -c a=\ commit -m x` 를 `<a= commit> <-m> <x>` 로 가름 — 서브커맨드가 없음.
    assert vp._parse_git_dash_c("git -c a=\\ commit -m x") is None


def test_parse_git_dash_c_returns_the_last_dash_c():
    # git 은 `-C` 를 누적 해석하므로 실효 디렉터리는 마지막이 좌우함. 첫 번째를
    # 돌려주면 커밋이 돌지 않는 트리를 가리킴.
    assert vp._parse_git_dash_c("git -C /a -C /b commit -m x") == "/b"
    assert vp._parse_git_dash_c("git -c k=v -C /a -C /b commit -m x") == "/b"


def test_mask_literals_hides_a_command_shaped_line_inside_a_message():
    # 여러 줄 커밋 메시지 한 줄이 통째로 `git -C … commit` 인 경우. 개행이 명령 구분자
    # 이므로 `_at_command_start` 만으로는 진짜 호출과 구분되지 않음 — 인용 구간 판정이
    # 그걸 데이터로 끊어 줌.
    assert vp._parse_git_dash_c('git -C /a commit -m "line1\ngit -C /b commit\nline3"') == "/a"


def test_shell_regions_step_over_a_backslash_escaped_quote():
    # 셸은 따옴표 밖과 `"…"` 안에서 `\` 를 이스케이프로 읽음. 모르고 짝을 세면
    # 구간이 엉뚱한 데서 닫히고, 진짜 커밋 호출이 "따옴표 안"으로 분류되거나 반대로
    # 메시지 조각이 호출로 세어져 실행 디렉터리를 잃음.
    assert vp._parse_git_dash_c(r'git -C /a commit -m "he said \"run git commit now\" ok"') == "/a"
    assert vp._parse_git_dash_c(r"echo don\'t ; git -C /wt commit -m x ; echo it\'s") == "/wt"
    # `'…'` 안에는 이스케이프가 없음 — `\` 는 리터럴이고 구간은 다음 `'` 에서 닫힘.
    assert vp._shell_regions(r"a 'b\' c") == ((3, 5, "quote"),)


@pytest.mark.parametrize(
    ("unit", "reps"),
    [
        ("-a ", 40),
        ('-a "-x -y" ', 24),
        (r"-a\ ", 24),
        ("-c -b ", 22),
        # 아래 셋이 실제로 폭주하던 계열: `\` 뒤에 **공백이 둘 이상**이면 이스케이프
        # 조각으로 넘어갈지 맨몸 조각으로 `\` 만 먹고 단어를 끊을지 두 갈래가 살아 있어
        # 반복마다 곱해짐. 위 넷은 그 갈래에 닿지 못해 전부 0초를 재고 있었고, 그동안
        # 24회 = 13초(줄이음+들여쓰기는 커밋 메시지에 흔한 모양).
        (r"-a\  ", 24),
        ("-a" + "\\" + "\n  ", 24),
        ("-c a=1" + "\\" + "\n    ", 24),
    ],
    ids=["plain", "quoted", "escaped", "argslot", "esc2sp", "esc-nl", "esc-nl-cfg"],
)
def test_parse_git_dash_c_does_not_backtrack_exponentially(unit: str, reps: int):
    # 훅에서의 폭주는 느려지는 게 아니라 타임아웃이고, 타임아웃은 판정을 건너뛰는 것과
    # 같음 — 즉 조용한 미강제. 실패하는(=끝까지 되감는) 입력으로 잼.
    import time

    started = time.perf_counter()
    assert vp._parse_git_dash_c("git " + unit * reps + "nope") is None
    assert time.perf_counter() - started < 0.2, (unit, reps)


def test_the_option_word_stays_deterministic_inside_a_commit_message():
    # `_parse_git_dash_c` 는 명령 전체를 훑으므로 병리 입력이 **커밋 메시지 텍스트**로도
    # 들어옴. 이 repo 는 본문에 셸 명령을 상시 인용 — 319자짜리 메시지가 훅을
    # 13초 멈추던 실측 모양이 이것.
    import time

    body = "git " + ("-c a=1" + "\\" + "\n    ") * 24 + "nope"
    started = time.perf_counter()
    vp._parse_git_dash_c('git -C /wt commit -m "' + body + '"')
    assert time.perf_counter() - started < 0.2


def test_a_dash_c_inside_a_comment_is_not_an_option():
    # 주석은 셸이 실행하지 않는 텍스트. 거기 적힌 `-C` 를 채택하면 ROOT 가 커밋이 돌지
    # 않는 트리를 가리켜, 그 트리의 티어 마커·스테이징 파일을 검사함. 이 repo 의 커밋
    # 명령은 주석으로 자기 형태를 설명하는 일이 잦음.
    assert (
        vp._parse_git_dash_c("# git -C /other/wt commit\ngit -C /c/real commit -m x") == "/c/real"
    )
    assert (
        vp._parse_git_dash_c("git -C /c/real commit -m x  # git -C /other/wt commit") == "/c/real"
    )


def test_an_escaped_backtick_opens_no_substitution():
    """이스케이프한 백틱을 여는 것으로 읽으면 뒤의 진짜 백틱과 짝을 지어, 그 사이를 감싼
    명령으로 읽고 거기서 피연산자를 끝냄 — 뒤의 플래그가 머지에서 떨어짐."""
    command = "git merge stage \\`x `true` --no-ff"
    masked = vp.mask_literals(command)
    opener = command.index("`true")
    assert vp._substitutions(masked) == [(opener, opener + len("`true`"))]
