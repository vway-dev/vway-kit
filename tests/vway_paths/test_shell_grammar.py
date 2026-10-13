"""셸 문법 읽기 — 낱말의 끝, 명령 자리, 그리고 셸이 **돌리는** 인용 텍스트.

인용된 텍스트는 무언가 그것을 실행하기 전까지만 데이터임. 치환·인터프리터의 `-c`·
확장이 켜진 heredoc 본문은 리터럴이 아니라 명령으로 읽음.
"""

import pytest

import scripts._vway_paths as vp
from tests.vway_paths._helpers import (
    RUN_BY_THE_MASK,
)


def test_a_dollar_quoted_string_is_literal_text():
    # `$'…'` 안은 리터럴이고 `\` 이스케이프가 살아 있음. 구간으로 안 끊으면 그 안의 명령
    # 모양이 호출로 세어져 모호 판정이 발동하고, 워크트리 재지정이 사라짐.
    assert vp._parse_git_dash_c("echo $'git -C /b commit' && git -C /a commit -m x") == "/a"
    # `$'…'` 를 일반 따옴표로 읽으면 **이스케이프된** 따옴표에서 구간이 일찍 닫히고, 남은
    # 짝 없는 따옴표가 뒤를 통째로 삼켜 진짜 커밋 호출이 사라짐 — 재지정이 조용히
    # 없어지고, main 이 깨끗하면 러너가 아무것도 안 하고 exit 0(실측).
    assert vp._parse_git_dash_c(r"echo $'don\'t' ; git -C /wt commit -m y") == "/wt"


def test_a_comment_is_literal_text_even_when_it_holds_an_apostrophe():
    # 주석의 아포스트로피(`don't`)를 따옴표로 읽으면 거기서 구간이 열려 뒤 명령을 통째로
    # 삼킴. 한국어 주석에도, 영어 축약형에도 흔한 모양임.
    assert vp._parse_git_dash_c("# don't\ngit -C /a commit -m x") == "/a"


def test_a_dash_heredoc_strips_only_tabs_from_its_terminator():
    # `<<-` 는 종결자의 선행 **탭만** 벗김. 공백까지 벗기는 것으로 읽으면 들여쓴 유사 줄에서
    # 본문이 일찍 끝나고 나머지 본문이 명령으로 읽힘 — 본문의 `-C` 가 채택됨.
    dash = "\n".join(
        ["msg=$(cat <<-EOF", "\t- git -C /evil commit", "\tEOF", ")", "git -C /a commit -F -"]
    )
    assert vp._parse_git_dash_c(dash) == "/a"
    # 맨 `<<` 는 줄이 정확히 일치해야 함. 탭으로 들여쓴 `EOF` 는 종결자가 아니므로 본문이
    # 계속되고, 본문의 `-C /evil` 은 여전히 텍스트임.
    plain = "\n".join(
        ["msg=$(cat <<EOF", "\t- git -C /evil commit", "\tEOF", ")", "git -C /a commit -F -"]
    )
    assert vp._parse_git_dash_c(plain) == "/a"
    # 그 본문이 어디서 끝나느냐는 **치환이 끝나는 자리** — 의도한 divergence. bash 는
    # 종결자를 못 만난 본문을 치환 밖까지 삼켜 이 입력에서 아무것도 실행하지 않음(실측:
    # git 셰임에 아무 호출도 안 남음). 치환 안을 명령으로 스캔하는 대가이고, 방향은
    # 게이팅 쪽이라 안전함. 최상위의 미종결 본문은 여전히 끝까지 감(아래 테스트).


def test_an_unterminated_heredoc_body_runs_to_the_end():
    # 셸이 그렇게 소비함. "본문 없음"으로 돌리면 메시지가 구문으로 파서에 넘어가 그 안의
    # 명령 모양이 호출로 세어짐. 여기서 None 은 FAIL-OPEN 방향임.
    assert vp._parse_git_dash_c("cat <<EOF\ngit -C /evil commit\n") is None


def test_a_here_string_is_not_a_heredoc():
    # `<<<` 는 본문이 없음. heredoc 으로 읽으면 뒤 명령 전부가 본문으로 덮여 진짜 커밋 호출이
    # 사라짐 — 워크트리 재지정이 조용히 없어짐.
    assert vp._parse_git_dash_c("cat <<<'x'\ngit -C /a commit -m y") == "/a"


def test_a_line_that_opens_two_heredocs_masks_both_bodies():
    # 셸은 한 줄이 연 본문들을 **차례로** 읽음. 첫 본문만 덮으면 둘째 본문이 명령으로 읽혀,
    # git 을 하나도 돌리지 않는 명령이 거기 적힌 `-C` 로 ROOT 를 옮김.
    # 미끼를 A 본문에 두면 어느 구현에서도 덮이므로 이 가드를 재지 못함 — B 본문에 둠.
    in_a = "\n".join(["cat <<A <<B", "git -C /evil commit", "A", "B", "git -C /a commit -m y"])
    in_b = "\n".join(["cat <<A <<B", "A", "git -C /evil commit", "B", "git -C /a commit -m y"])
    assert vp._parse_git_dash_c(in_a) == "/a"
    assert vp._parse_git_dash_c(in_b) == "/a"
    # 진짜 호출이 없으면 답도 없어야 함. 둘째 본문을 놓치면 여기서 `/evil` 이 나옴(실측).
    only = "\n".join(["cat <<A <<B", "A", "git -C /evil commit -m z", "B"])
    assert vp._parse_git_dash_c(only) is None
    # 줄을 나눠 연 heredoc 둘 뒤의 진짜 호출은 계속 읽힘.
    two = "\n".join(
        [
            "msg=$(cat <<A",
            "fix: x",
            "A",
            "); n=$(cat <<B",
            "note",
            "B",
            "); git -C /real commit -F -",
        ]
    )
    assert vp._parse_git_dash_c(two) == "/real"


def test_a_backslash_delimiter_also_turns_off_expansion():
    # `<<\EOF` 는 `<<'EOF'` 와 같은 관용구. 빠뜨리면 그 본문이 통째로 명령으로 읽혀,
    # git 을 하나도 돌리지 않는 명령이 본문의 `-C` 로 ROOT 를 옮김(실측).
    command = "\n".join(["cat <<\\EOF > /tmp/m", "git -C /evil/wt commit -m x", "EOF"])
    assert vp._parse_git_dash_c(command) is None


def test_an_escaped_space_keeps_the_path_whole():
    # 셸은 `\ ` 에서 단어를 끊지 않음. 마스킹은 그렇게 읽는데 값 읽기가 원본에서 끊기면
    # 답이 반토막 나고, 그 반토막이 **실재하는 형제 worktree** 를 지목할 수 있음
    # (Windows 는 끝의 `\` 를 정규화함). 그러면 게이트는 커밋이 돌지 않는 트리의
    # status·티어 마커를 읽음 — 분류된 커밋을 막고 미분류 커밋을 통과시킴.
    assert vp._parse_git_dash_c(r"git -C /tmp/My\ P/wt commit -m x") == "/tmp/My P/wt"
    assert vp._parse_git_dash_c(r"git -C /My\ Dir/w --git-dir=/g/.git commit -m x") == "/My Dir/w"
    # 공백 아닌 `\` 는 Windows 경로 구분자로 남김.
    assert vp._parse_git_dash_c(r"git -C C:\Work\repo commit -m x") == r"C:\Work\repo"


def test_a_relative_dash_c_is_returned_as_written():
    # git 은 `-C` 를 누적 해석함(`-C /a -C sub` → `/a/sub`). 마지막만 돌려주므로 상대
    # 경로는 훅 프로세스 cwd 기준으로 풀리고 실제 대상과 어긋날 수 있음 — 문서화된 잔여.
    # 값이 조용히 바뀌면 그 잔여가 다른 것이 되므로 여기서 못박음.
    assert vp._parse_git_dash_c("git -C /a -C sub commit -m x") == "sub"


def test_the_cd_fallback_is_reached_only_when_no_invocation_carried_a_dash_c():
    # 사다리 ②는 ①이 **아무 답도 못 냈을 때**만 봄. 호출들이 서로 다른 트리를 지목하면
    # 답이 없는 것이고, 거기서 `cd` 로 흘러가면 아무 호출도 지목하지 않은 세 번째 트리를
    # ROOT 로 삼음 — 모호는 추측이 아니라 읽기 종료로 끝남(Invariant 7).
    assert vp._dir_from_command("cd /third && git commit -m x") == "/third"
    assert vp._dir_from_command("cd /third && git -C /a commit -m x") == "/a"
    assert (
        vp._dir_from_command("cd /third && git -C /a commit -m x && git -C /b commit -m y") is None
    )
    # 커밋 호출이 아예 없으면(머지 명령 등) ②가 그대로 답함.
    assert vp._dir_from_command("cd /third && git merge feature/x") == "/third"


def test_a_directory_prefix_names_git_but_a_different_program_does_not():
    # `/usr/bin/git` 은 같은 프로그램임. 러너의 self-filter 는 앵커가 없어 이미 그것을
    # 커밋으로 넘기므로, 파이썬 쪽만 떨어뜨리면 게이트는 돌면서 ROOT 가 main 에 남음 —
    # 깨끗한 main 에서 조기 종료하며 미분류 커밋이 통과함(실측).
    assert vp._parse_git_dash_c("/usr/bin/git -C /a/wt commit -m x") == "/a/wt"
    assert vp._parse_git_dash_c("sudo /usr/bin/git -C /a/wt commit -m x") == "/a/wt"
    assert vp._parse_git_dash_c(r"C:\Git\bin\git -C /a/wt commit -m x") == "/a/wt"
    # 접두는 **구분자로 끝나야** 함. 그게 다른 프로그램 이름이 `git` 낱말에 닿는 것을 막음:
    # `foo.git` 은 git 이 아니고, 그 명령의 `-C` 를 채택하면 게이트가 엉뚱한 트리를 검사함.
    assert vp._parse_git_dash_c("foo.git -C /a/wt commit -m x") is None
    assert vp._parse_git_dash_c("mygit -C /a/wt commit -m x") is None
    assert vp._parse_git_dash_c("gitfoo -C /a/wt commit -m x") is None
    # 인용 밖 낱말은 여전히 호출 아님.
    assert vp._parse_git_dash_c("echo /tmp/git commit done && git -C /a commit -m x") == "/a"


@pytest.mark.parametrize(
    "unit",
    ["-a 'x y' ", "-a $'x\\'y' ", "-C /a\\ b/c ", "-a <<\\X ", "-a #z ", '-a "x y" '],
    ids=["sq", "dollarsq", "path-esc", "heredoc-bs", "hash", "dq"],
)
def test_reading_a_long_command_stays_linear(unit: str):
    """긴 명령에서 **2차**로 자라면 안 됨 — 훅에서의 2차는 타임아웃이고, 타임아웃은 판정을
    건너뛰는 것과 같음(조용한 미강제).

    이 저장소가 실제로 겪은 회귀: `git` 앞 디렉터리 접두를 선택적 그룹으로 **정규식에**
    넣었더니 매 위치마다 되감아, 17KB 명령이 6.6초가 됨(접두 판정을 `at_command_start` 로
    옮기자 5ms). 그래서 경계는 선형 실측치의 수백 배로 헐겁게 두고, 2차만 잡음 — 느린
    기계에서도 흔들리지 않음.

    병리 입력은 **커밋 메시지 텍스트**로도 넣음. 이 repo 는 본문에 셸 명령을 상시 인용함.
    """
    import time

    body = "git " + unit * 1600 + "nope"
    command = 'git -C /wt commit -m "' + body + '"'
    assert len(command) > 9_000
    started = time.perf_counter()
    vp._parse_git_dash_c(command)
    vp.mask_literals(command)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"{unit!r}: {elapsed:.3f}s — 선형이면 수 ms 다(2차 회귀 의심)"


def test_a_line_continuation_does_not_end_the_word():
    # 셸은 `\`+개행에서 두 줄을 **한 명령으로 이음**. 그 자리를 NUL 로 덮으면 토큰 경계가
    # 생겨 이어진 호출이 두 낱말로 갈리고, 그러면 커밋이 "커밋 아님"으로 읽힘 — 러너가
    # 게이트를 돌리기도 전에 exit 0 하는 방향(게이트 전체 스킵, 실측).
    command = "git -C /wt \\\n  commit -m x"
    assert vp._parse_git_dash_c(command) == "/wt"
    masked = vp.mask_literals(command)
    assert next(vp.git_invocations(masked, vp._GIT_COMMIT_RE), None) is not None
    # 이은 자리는 **공백**이어야 함. NUL 은 `\s` 가 아니라 문법이 낱말이 끝난 것으로 읽음.
    assert "\x00" not in masked


def test_an_arithmetic_left_shift_is_not_a_heredoc_introducer():
    # 산술 안의 `<<` 는 왼쪽 시프트. heredoc 도입부로 읽으면 그 뒤 전부가 본문으로
    # 덮이는데, 그 "본문"은 게이트가 읽으려던 진짜 명령임.
    # 세 철자 전부 bash 로 실측 — 뒤의 `git commit` 은 셋 다 **실행됨**.
    command = "echo $((1 << 2))\ngit -C /wt commit -m x"
    assert vp._parse_git_dash_c(command) == "/wt"
    # 중첩 괄호도 닫는 자리를 옳게 찾아야 함.
    assert vp._parse_git_dash_c("echo $(( (1 << 2) + 3 ))\ngit -C /wt commit -m x") == "/wt"
    # 산술 **명령**. `$((` 만 다루면 이건 남고, HEAD 가 차단하던 커밋이 통과함(실측).
    assert vp._parse_git_dash_c("(( 1 << 2 ))\ngit -C /wt commit -m x") == "/wt"
    assert vp._parse_git_dash_c("if (( 1 << 2 )); then :; fi\ngit -C /wt commit -m x") == "/wt"
    assert vp._parse_git_dash_c("for ((i=0;i<(1<<2);i++)); do :; done\ngit -C /wt commit") == "/wt"
    # 확장이 든 시프트도 같은 자리. 넓힌 구분자 낱말이 `$n` 을 받으므로, 산술을 건너뛰지
    # 않으면 여기서만 HEAD 보다 나빠짐.
    assert vp._parse_git_dash_c("(( 1 << $n ))\ngit -C /wt commit -m x") == "/wt"
    # 옛 산술 철자.
    assert vp._parse_git_dash_c("echo $[1 << 2]\ngit -C /wt commit -m x") == "/wt"
    # `let x=1<<2` 는 bash **자신이** heredoc 으로 읽음 — 여기서 건너뛰면 셸과 갈림.
    assert vp._parse_git_dash_c("let x=1<<2\ngit -C /wt commit -m x") is None


def test_a_heredoc_delimiter_is_one_word_however_its_pieces_are_quoted():
    # 구분자는 조각을 이은 **낱말 하나**(`<<'EO'F` → `EOF`). 맨몸 토큰 하나로 읽으면
    # 종결자를 영영 못 만나 본문이 문자열 끝까지 가고, 진짜 호출까지 덮임.
    body = ["cat <<'EO'F", "git -C /evil/wt commit -m x", "EOF", "git -C /wt commit -m y"]
    assert vp._parse_git_dash_c("\n".join(body)) == "/wt"
    # 백슬래시로 인용한 조각도 같은 낱말임.
    body = ["cat <<E\\OF", "git -C /evil/wt commit -m x", "EOF", "git -C /wt commit -m y"]
    assert vp._parse_git_dash_c("\n".join(body)) == "/wt"


def test_a_backslash_quotes_only_what_needs_quoting():
    # 다음 글자를 **무조건** 인용으로 보면, 이 게이트가 도는 호스트의 실제 경로가 망가짐:
    # `C:\Git\bin\git` 에서 `git` 낱말이 사라지고, 철자할 수 없는 프로그램은 안 도는 게이트.
    assert vp._parse_git_dash_c(r"C:\Git\bin\git -C /a/wt commit -m x") == "/a/wt"
    assert vp._parse_git_dash_c(r"git -C C:\Work\repo commit -m x") == r"C:\Work\repo"
    # 공백·따옴표·자기 자신은 여전히 인용함.
    assert vp._parse_git_dash_c(r"git -C /tmp/My\ P/wt commit -m x") == "/tmp/My P/wt"


def test_operand_end_stops_at_the_next_command_and_at_a_comment():
    # 명령의 낱말은 다음 명령이 시작되는 자리, 또는 주석에서 끝남. 끝까지 읽으면 뒤 명령의
    # 플래그가 이 명령 것으로 합쳐지고, 주석에 적힌 플래그가 정책 행을 만족시킴.
    command = "git merge feature/x && rm -rf /tmp/x"
    masked = vp.mask_literals(command)
    at = command.index("feature/x")
    assert command[at : vp.operand_end(command, masked, at)] == "feature/x "
    command = "git merge feature/x  # --squash 나중에"
    masked = vp.mask_literals(command)
    at = command.index("feature/x")
    assert command[at : vp.operand_end(command, masked, at)] == "feature/x  "
    # 구분자는 **마스크**에서 찾음 — 메시지 안의 `;` 는 아무것도 끝내지 않음.
    command = 'git merge -m "a; b" feature/x'
    masked = vp.mask_literals(command)
    at = command.index("-m")
    assert command[at : vp.operand_end(command, masked, at)] == '-m "a; b" feature/x'


@pytest.mark.parametrize("command", RUN_BY_THE_MASK, ids=range(len(RUN_BY_THE_MASK)))
def test_the_mask_reads_text_the_shell_runs_as_the_command_it_is(command: str):
    masked = vp.mask_literals(command)
    assert next(vp.git_invocations(masked, vp.git_subcommand_re("commit")), None) is not None, (
        f"{command!r} 는 셸이 진짜로 돌리는 커밋인데 마스크가 데이터로 덮었다"
    )


def test_a_quoted_heredoc_delimiter_still_turns_expansion_off():
    # 확장이 꺼진 본문은 텍스트임. 여기서 켜면 이 repo 의 커밋 메시지가 자기를 짓는 커밋의
    # 두 번째 호출로 읽힘.
    assert not vp.is_invocation("cat <<'EOF'\n$(git commit -m x)\nEOF", "commit")
    body = "git commit -F- <<'EOF'\nsubject\n\ngit merge --no-ff stage\nEOF"
    assert vp.is_invocation(body, "commit")
    assert not vp.is_invocation(body, "merge"), "메시지 본문의 merge 가 전략 판정에 걸린다"
