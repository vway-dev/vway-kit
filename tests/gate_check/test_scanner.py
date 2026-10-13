"""스캐너의 성능·정확도 계약 — 인용·heredoc·주석과 선형 시간.

훅 타임아웃은 **조용히 건너뛴 게이트**다. 그래서 정규식이 2차로 폭발하지 않는지를
실측으로 측정 — `search` 는 첫 매치에서 반환하므로 시간 가드가 루프도 재야 함.
"""

import time
from pathlib import Path

import scripts.vdev_gate_check as fgc


def test_parse_merge_ignores_a_merge_written_in_a_heredoc_body():
    # skills/commit 이 출하하는 커밋은 메시지를 heredoc 으로 만들어 파이프함 — 본문 전체가
    # 진짜 호출보다 **앞에** 옴. 이 repo 의 커밋 메시지는 머지 규율을 상시 인용하므로
    # 본문의 `git merge --no-ff <브랜치>` 가 호출로 읽히면, 커밋이 merge_strategy 로 심사돼
    # 일어나지도 않은 머지 때문에 차단됨(fail-CLOSED 오차단).
    command = "\n".join(
        [
            "msg=$(cat <<'EOF'",
            "fix(gate): x",
            "",
            "git merge --no-ff stage 를 쓰지 마라.",
            "EOF",
            ")",
            'printf %s "$msg" | git -C /a/b commit -F -',
        ]
    )
    assert fgc.parse_merge_command(command) == (set(), None)


def test_parse_merge_reads_the_invocation_not_a_word_in_an_operand():
    # `git merge` 는 인용되지 않은 **낱말**로도 나옴(`echo git merge …`). 그걸 호출로 세면
    # 첫 매치가 이기므로 엉뚱한 소스·플래그로 심사돼, 실제로는 규율을 지킨 머지가 차단됨.
    assert fgc.parse_merge_command(
        "echo git merge feature/wrong && git merge --squash feature/right"
    ) == ({"--squash"}, "feature/right")
    assert fgc.parse_merge_command(
        "npm run x; echo git merge origin/stage; git -C /wt merge --no-ff feature/right"
    ) == ({"--no-ff"}, "feature/right")


def test_merge_dash_c_ignores_a_dash_c_inside_a_quoted_option_value():
    # `-C` 가 디렉터리인 것은 옵션일 때뿐임. 옵션 **값** 안의 `-C` 를 채택하면 merge 가
    # 남의 트리에서 도는 것으로 판정돼 게이트가 통째로 FAIL-OPEN 함. 그래서 자리는
    # 마스크에서 찾음 — 원본에서 찾으면 값 안의 `-C` 가 그대로 걸림(실측).
    assert fgc._merge_dash_c("git -c 'x= -C /evil' merge --squash feature/x") is None
    assert fgc._merge_dash_c('git -c "x= -C /evil" merge --squash feature/x') is None
    # 진짜 옵션은 계속 읽음.
    assert fgc._merge_dash_c("git -C /wt merge --squash feature/x") == "/wt"


def test_points_elsewhere_reads_the_real_invocation_not_a_comment():
    # 주석의 `-C` 를 채택하면 진짜 머지가 도는 트리 대신 남의 트리로 판정해, 머지 게이트가
    # 통째로 FAIL-OPEN 함 — 전략 위반 머지가 그대로 나감. 미끼는 반드시 `merge` 여야
    # 함: `_merge_dash_c` 는 `git … merge` 의 옵션 영역만 읽으므로 주석 속 `commit` 은
    # 어떤 구현에서도 후보가 아니고, 그 미끼로는 이 가드를 재지 못함.
    command = "# git -C /other/wt merge --squash feature/y\ngit -C . merge --squash feature/x"
    assert fgc._points_elsewhere(command, Path(".")) is False
    # heredoc 본문도 같음.
    body = "\n".join(
        [
            "msg=$(cat <<'EOF'",
            "git -C /other/wt merge --no-ff stage",
            "EOF",
            ")",
            'git -C . merge --squash feature/x -m "$msg"',
        ]
    )
    assert fgc._points_elsewhere(body, Path(".")) is False


def test_target_from_command_ignores_a_switch_that_is_only_a_word():
    # `git switch` 도 인용되지 않은 낱말로 나옴. 그걸 호출로 세면 아무도 서지 않은
    # 브랜치를 target 으로 잡아, 규칙 매칭이 바뀌고 오차단으로 이어짐.
    assert fgc._target_from_command("npm run git switch stage; git merge --squash f/x") is None


def test_target_from_command_ignores_a_switch_inside_a_message():
    # 메시지 본문의 `git switch <브랜치>` 를 채택하면 머지가 아무도 서지 않은 브랜치 기준으로
    # 심사됨. 여기서 잘못 고른 target 은 규칙 매칭을 바꾸므로 오차단으로 이어짐.
    command = (
        'git commit -m "먼저 git switch stage 하라"'
        " && git switch dev && git merge --squash feature/x"
    )
    assert fgc._target_from_command(command) == "dev"


def test_target_from_command_ignores_an_unclear_switch_quoted_in_a_message():
    # 더 나쁜 쪽이 이것임. 인용된 switch 가 **불명확**하면(`-c`, pathspec) "불명확한 switch
    # 하나가 체인 전체를 무효화한다" 규칙이 발동해 target 이 None 이 되고, 호출측은 switch 가
    # 있다는 이유로 HEAD 폴백도 쓰지 않고 exit 0 함 — merge 게이트가 통째로 꺼짐.
    # 명령 자리 판정만으로는 못 막음: 여러 줄 메시지 안의 그 줄은 개행 뒤에 서 있어 명령
    # 자리로 보임(실측). 리터럴 마스킹만이 끊음. 이 repo 의 커밋 메시지는 risk-tiers 의
    # 머지 블록을 실제로 인용하므로 지어낸 모양이 아님.
    quoted = (
        'git commit -m "규율:\ngit switch -c feature/y\n"'
        " && git switch dev && git merge --squash feature/x"
    )
    assert fgc._target_from_command(quoted) == "dev"
    pathspec = (
        'git commit -m "복원:\ngit checkout dev -- a/b.py\n"'
        " && git switch dev && git merge --squash feature/x"
    )
    assert fgc._target_from_command(pathspec) == "dev"
    body = "\n".join(
        [
            "msg=$(cat <<'EOF'",
            "fix: x",
            "",
            "git switch -c feature/y",
            "EOF",
            ")",
            'printf %s "$msg" | git commit -F - && git switch dev && git merge --squash feature/x',
        ]
    )
    assert fgc._target_from_command(body) == "dev"


def test_the_merge_path_reading_stays_linear_on_a_long_command():
    """merge 쪽도 같은 경계에 묶음 — `_target_from_command`·`_points_elsewhere` 는
    마스크를 다시 만들고 매치를 훑으므로, 커밋 쪽만 재면 회귀가 여기로 숨음.
    (실측 회귀: 정규식에 넣은 디렉터리 접두 때문에 17KB 명령이 6.6초.)"""

    body = "git " + "-a 'x y' " * 1600 + "nope"
    command = 'git -C /wt merge --squash feature/x -m "' + body + '"'
    started = time.perf_counter()
    fgc.parse_merge_command(command)
    fgc._target_from_command(command)
    fgc._points_elsewhere(command, Path("."))
    elapsed = time.perf_counter() - started
    assert elapsed < 1.5, f"{elapsed:.3f}s — 선형이면 수 ms 다(2차 회귀 의심)"


def test_reading_many_switches_and_comments_stays_linear():
    """`operand_end` 는 merge 앞 switch **하나마다** 불림. 그때마다 주석 구간을 처음부터
    훑으면 주석이 K 개인 명령에서 K² 가 됨 — 이 저장소가 실제로 겪은 회귀. 훅에서의
    2차는 타임아웃이고, 타임아웃은 판정을 건너뛰는 것과 같음(조용한 미강제).

    입력 크기는 **재서** 고름. 이 명령(243KB)에서 지금 0.56s 이고, 주석 구간을 매번 다시
    계산하면 9.2s. 이분탐색을 뺀 값은 무엇으로 바꾸느냐에 따라 배 이상 갈려 적지 않음 —
    그래서 경계의 근거는 수치 비교가 아니라 아래 항목임. 앞선 판(122KB, 1.5s)은 두 회귀 중
    하나가 통과해 그것을 재지 못함.

    **최선값으로 잼.** 단일 측정으로는 스위트 부하에서 선형이 임계를 넘음(실측: 단독 0.45s,
    전량 실행 중 1.0s 초과로 붉어짐). 2차는 어느 회차에서도 느리므로 최선값이 그것을 놓치지
    않음. 경계 1.4s 는 선형 위이면서 두 회귀 아래 — 여유가 어느 쪽으로 얼마인지는 무엇을
    회귀로 놓느냐에 따라 달라지므로, 판정은 비율이 아니라 **두 회귀가 실제로 죽는지**로 함
    (변이 배터리).
    """

    nl = chr(10)
    command = ("git switch dev # c" + nl) * 12800 + "git merge feature/x"
    assert len(command) > 200_000

    runs = []
    for _ in range(3):
        started = time.perf_counter()
        fgc._target_from_command(command)
        fgc.parse_merge_command(command)
        runs.append(time.perf_counter() - started)
    assert min(runs) < 1.4, f"{min(runs):.3f}s — 선형이면 0.5s 대다(2차 회귀 의심): {runs}"


def test_parse_merge_survives_a_separator_inside_the_message():
    # 피연산자 영역을 **원본**에서 잘라 내면 메시지 안의 `;`·`|`·개행이 따옴표 한가운데를
    # 끊고, shlex 가 터져 merge 판정 전체가 FAIL-OPEN 함 — 그 명령은 merge_strategy 를
    # 통째로 건너뜀. 이 repo 의 승격 머지가 바로 다중 줄 `-m` 임(실측).
    assert fgc.parse_merge_command('git merge -m "step 1; step 2" feature/x') == (
        set(),
        "feature/x",
    )
    assert fgc.parse_merge_command('git merge -m "a|b" --no-ff feature/x') == (
        {"--no-ff"},
        "feature/x",
    )
    assert fgc.parse_merge_command('git merge --no-ff -m "line one\nline two" dev') == (
        {"--no-ff"},
        "dev",
    )


def test_parse_merge_ignores_a_flag_written_in_a_trailing_comment():
    # 주석은 셸이 실행하지 않는 텍스트임. 거기 적힌 `--squash` 를 세면, 그 플래그를 **요구**
    # 하는 정책 행이 아무것도 하지 않은 명령에 만족됨 — fail-CLOSED 여야 할 자리가 열림.
    assert fgc.parse_merge_command("git merge feature/x  # --squash 나중에") == (
        set(),
        "feature/x",
    )


def test_parse_merge_stops_at_the_next_command():
    # 뒤 명령의 플래그가 이 머지 것으로 합쳐지면 안 됨.
    assert fgc.parse_merge_command("git merge feature/x && rm -rf /tmp/x") == (
        set(),
        "feature/x",
    )


def test_target_from_command_reads_a_switch_followed_by_a_comment():
    # 주석까지 피연산자로 읽으면 "피연산자 정확히 하나" 검사가 깨져 **불명확한 switch** 가
    # 되고, 불명확 하나가 체인 전체를 무효화해 호출측이 HEAD 폴백을 포기함 — merge 전략
    # 게이트가 조용히 꺼지는 방향임(실측).
    assert fgc._target_from_command("git switch dev  # go to --dev\ngit merge feature/x") == "dev"
