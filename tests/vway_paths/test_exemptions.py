"""면제는 목록이고 게이팅이 기본.

`_READS_ONLY` 에 이름이 오른 프로그램만 면제를 얻음. 이름을 못 댄 자리는 빼지 않고
`None` — 빼면 모르는 프로그램을 두고 면제가 정해짐. 면제는 명령 자리마다
프로그램을 읽어 정하고, 걸음은 **하나**.
"""

import pytest

import scripts._vway_paths as vp
from tests.vway_paths._helpers import (
    NET_ELEMENTWISE,
)


def test_the_readers_that_earn_an_exemption_are_all_named():
    """목록 전체를 적음. 부분집합만 적으면 이름 하나를 지워도 스위트가 초록 —
    그리고 여기서 이름이 늘어나는 것은 게이트가 **약해지는** 방향이므로, 늘어난 것이
    눈에 보여야 함."""
    spelled = {
        "cat",
        "cut",
        "diff",
        "dirname",
        "du",
        "echo",
        "egrep",
        "false",
        "fgrep",
        "file",
        "grep",
        "head",
        "ls",
        "printf",
        "pwd",
        "rg",
        "shellcheck",
        "sort",
        "stat",
        "tail",
        "tr",
        "tree",
        "true",
        "type",
        "uniq",
        "wc",
        "whereis",
        "which",
    }
    assert set(vp._READS_ONLY) == spelled, set(vp._READS_ONLY) ^ spelled
    # 자기 인자에 적힌 명령을 돌릴 방법이 있는 이름은 여기 있으면 안 됨. 전부 실제로
    # 커밋을 돌리는 철자가 있음(`awk` 의 `system`, `sed` 의 GNU `e`, `find` 의 `-exec`,
    # `ack`·`ag` 의 `--pager`).
    for name in ("awk", "sed", "find", "ack", "ag", "xargs", "ssh", "make", "sudo"):
        assert name not in vp._READS_ONLY, name
    # 자기 **환경**이 지목하는 명령을 돌리는 이름도 안 됨 — 그쪽은 명령에 흔적이 없어
    # 사용자도 게이트도 볼 수 없음. `LESSOPEN`(대부분 배포판이 login profile 에서 설정)이
    # 그것이고, `less 'git commit -m x'` 가 실제로 커밋을 돌림(실측). `more` 는 여러
    # 호스트에서 같은 프로그램이라 함께 뺌.
    for name in ("less", "more"):
        assert name not in vp._READS_ONLY, name


def test_the_shell_words_that_are_not_programs_are_all_named():
    """셸의 목록이라 닫혀 있음. 하나가 빠지면 그 낱말이 프로그램으로 세어져, 그 원소는
    읽기 전용 면제를 영영 못 받고 루프 몸통의 인용된 언급이 전부 차단됨."""
    assert set(vp._RESERVED_WORDS) == {
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "function",
        "if",
        "in",
        "select",
        "then",
        "time",
        "until",
        "while",
    }


@pytest.mark.parametrize(
    "element,expected",
    [
        # 예약어는 프로그램이 아니라 **그 뒤** 명령이 시작되는 자리. 그 낱말을 이름으로
        # 내놓으면 그것이 여는 프로그램을 영영 못 보고, `do` 안의 `grep` 이 사라짐.
        ("if grep -q x f", ["grep"]),
        (" do grep x", ["grep"]),
        ("then echo yes", ["echo"]),
        ("while read l", ["read"]),
        # 인덱스 0 의 예약어도 마찬가지여야 함.
        # `for`·`in` 뒤에 서는 것은 프로그램이 아니라 이름과 낱말 목록이므로 명령 자리가
        # 아님(`_NAMES_A_WORD`). 이름이 하나도 없는 원소는 면제를 못 받아 안전한 쪽으로 감.
        ("for f in a b", []),
        # `case` 갈래를 여는 `)` 뒤가 명령 자리. 패턴 `a` 를 프로그램으로 세면
        # `case $x in a) echo 'git commit';; esac` 이 미분류 커밋으로 막힘(실측).
        ("case $x in a) echo hi", ["echo"]),
        # 디렉터리 접두는 같은 프로그램을 부르고, 호스트의 `.exe` 는 벗김.
        ("/usr/bin/grep x", ["grep"]),
        ("C:/Git/bin/bash.exe -c x", ["bash"]),
        # 명령이 프로그램 앞에 지닐 수 있는 것들. 이름이 아니므로 넘어가되, 걸음은 **그 뒤의**
        # 자리까지 감 — 거기서 멈추면 그 자리가 면제 판정에서 통째로 빠짐.
        # `!` 는 정밀한 읽기도 넘어가는 유일한 접두라, 그 뒤는 이름 그대로.
        ("! grep x f", ["grep"]),
        ("cat f & ! grep x f", ["cat", "grep"]),
        # 리다이렉션·대입 뒤는 이름을 **못 대는** 자리. 정밀한 읽기가 그 자리를 명령 자리로
        # 안 보므로(`at_command_start`), 이름을 대면 조건부 `git` 면제가 아무도 안 읽는
        # 호출을 덮음 — `> /dev/null git commit -m x` 가 실제로 커밋을 돌림(실측).
        ("> /dev/null grep x f", [None]),
        ("2>&1 grep x f", [None]),
        ("cat f & > /dev/null env x", ["cat", None]),
        # 이름을 읽을 수 없는 자리도 **빼지 않고 그렇다고 알림**. 빼면 그 프로그램을
        # 모르는 채로 면제가 결정됨 — 이 게이트가 틀리면 안 되는 방향. 마스크는 인용된
        # 리터럴의 **따옴표를 남기므로**(NUL 은 그 사이뿐) 이것이 실제 모양임.
        ("cat f & '\x00\x00\x00' commit", ["cat", None]),
        # 맨몸 NUL 은 그것과 다름 — heredoc **본문**의 텍스트이고, 본문을 여는 개행을 타고
        # 명령 자리로 떨어짐. `_list_elements` 가 그 span 을 이미 한 원소로 묶으므로 거기서
        # 시작하는 명령은 없고, 자리 하나를 지어내면 본문을 단지 저장하는 판독기가 면제를 잃음.
        ("cat f\n\x00\x00\x00", ["cat"]),
        # 대입은 프로그램도 그 인자도 아니고 프로그램 **안**으로 들어감.
        ("LC_ALL=C grep x f", [None]),
        ("sort=1 env x", [None]),
    ],
)
def test_the_program_scan_reads_the_program_at_every_command(
    element: str, expected: list[str | None]
):
    assert vp._programs(element) == expected


@pytest.mark.parametrize(
    "element,exempt",
    [
        ("grep 'x' f", True),
        ("if grep -q x f", True),
        (" do grep x", True),
        # 이름이 아예 없는 원소는 면제가 아님 — 맨 대입은 뒤에서 실행될 스크립트를 담음.
        ("MSG=x", False),
        ("", False),
        # 치환이 돌리는 것은 그 출력이지 안에 적힌 리더가 아님. **자리를 묻지 않음** —
        # 자리를 물으면 명령이 지닐 수 있는 접두를 전부 알아야 하고, 하나만 빠져도 면제가
        # 되돌아옴.
        ("$(echo x)", False),
        ("`echo x`", False),
        ("cat `echo x`", False),
        ("echo $(date)", False),
        ("awk '{print}' f", False),
        ("bash -c x", False),
        # 대입을 든 원소도 면제가 아님 — 대입은 이름이 벌어 준 면제 **안**으로 들어감.
        ("LC_ALL=C grep x f", False),
        # 접두 뒤의 자리가 면제를 정함. `cat` 하나가 원소 전체를 리더로 만들지 않음.
        ("cat f & > /dev/null env x", False),
        # 리다이렉션 뒤는 이름을 못 대는 자리라 리더도 면제를 못 얻음 — 이식 전과 같음.
        ("cat f & > /dev/null cat x", False),
        # `!` 뒤는 정밀한 읽기도 명령 자리로 보므로 이름 그대로.
        ("! grep x f", True),
    ],
)
def test_only_an_element_whose_every_program_reads_is_exempt(element: str, exempt: bool):
    assert vp._reads_only(element) is exempt


@pytest.mark.parametrize("command", NET_ELEMENTWISE, ids=range(len(NET_ELEMENTWISE)))
def test_an_interpreter_in_another_element_does_not_gate_this_one(command: str):
    assert not vp.is_invocation(command, "commit"), command


def test_program_spans_carry_the_name_and_its_argument_range():
    """자리를 읽는 판독기는 **하나**. 실행 플래그 판정이 자기 걸음을 따로 만들면 두 답이
    갈리고, 그때 어느 쪽이 면제를 정하는지가 우연이 됨 — `-v` 가 어느 프로그램 것인지는
    이름이 아니라 자리가 정함."""
    element = "printf -v x | rg -v y"
    spans = vp._program_spans(element)
    assert [n for n, _s, _e in spans] == ["printf", "rg"]
    assert element[spans[0][1] : spans[0][2]].strip() == "-v x"
    assert element[spans[1][1] : spans[1][2]].strip() == "-v y"
    assert vp._programs(element) == ["printf", "rg"]  # 이름만 내는 포장은 그대로


@pytest.mark.parametrize(
    "element,by_flag",
    [
        # 값이 이름이 될 수 있으면 무언가 돎.
        ("rg --pre git x commit", True),
        ("sort --compress-program=bash f", True),
        ("sort --co bash f", True),
        ("printf -v c 'git commit -m x'", True),
        ("printf -vc 'git commit -m x'", True),
        # 값이 공백을 담으면 존재할 수 없는 이름 — 면제 유지.
        ("rg --pre 'git commit' pattern .", False),
        ("sort --compress-program='git commit -m x' f", False),
        # 값이 아예 없어도 같음.
        ("rg --pre", False),
        # `--pre-glob` 은 `--pre` 가 아니고, `-v` 는 `rg` 의 평범한 반전 플래그.
        ("rg --pre-glob '*.md' 'git commit' .", False),
        ("printf x | rg -v y", False),
        # 확장이 남아 있으면 그것이 플래그가 될 수 있음 — 오차단 쪽으로 틀림.
        ("printf -v 'a[$(git commit -m x)]' 1", True),
    ],
    ids=range(11),
)
def test_an_exec_flag_withdraws_the_readers_exemption(element: str, by_flag: bool):
    assert vp._runs_by_flag(element, vp.mask_literals(element)) is by_flag
