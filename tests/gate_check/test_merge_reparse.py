"""리다이렉션과, 인자를 다시 파싱하는 프로그램(`eval`·`watch`·`ssh`) 뒤의 머지를 전략 판정이
bash 처럼 읽는가 — 인용·백슬래시·줄이음이 쪼갠 머지를 셸이 잇는 대로 읽는가 — 그리고 그 다시
읽기가 낱말마다 한 번인가.

리다이렉션과 그 대상은 피연산자가 아니고 그 안의 `|`·`&` 는 명령을 끝내지 않음. `eval` 뒤에서는
인용된 구분자나 `#` 가 앞 머지를 끝내므로 뒤 머지의 플래그가 앞 머지 것으로 세어지지 않음.
명령 자리 밖의 `git merge` 는 다시 파싱되거나 면제를 못 받은 프로그램이 돌릴 때만 호출임.
"""

import pytest

import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import (
    _init_repo,
    _rg,
    _run_merge_check,
    _run_runner,
    _write_policy,
    requires_bash_git,
)


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        # 리다이렉션과 그 대상은 피연산자가 아니고, 그 `|`·`&` 는 아무것도 가르지 않음
        ("git merge >|o.txt --no-ff fix/x", "dev", True),
        ("git merge >| o.txt --no-ff fix/x", "dev", True),
        ("git merge > o.txt --no-ff fix/x", "dev", True),
        ("git merge >o.txt --no-ff fix/x", "dev", True),
        ("git merge 2>&1 --no-ff fix/x", "dev", True),
        ("git merge &>o.txt --no-ff fix/x", "dev", True),
        ("git merge >&2 --no-ff fix/x", "dev", True),
        ("git merge <o.txt --no-ff fix/x", "dev", True),
        ("git merge --no-ff fix/x <<<hi", "dev", True),
        ("git merge feature/x >|o.txt --squash", "dev", False),
        ("git mer''ge >|o.txt --no-ff fix/x", "dev", True),
        ("git mer''ge 2>&1 --no-ff fix/x", "dev", True),
        # 인용된 `>` 는 리다이렉션이 아니라 인자
        ("git merge -m '>' --no-ff fix/x", "dev", True),
        # `eval` 뒤에서는 인용된 구분자가 그 앞 머지를 끝냄
        ("eval git merge feature/a ';' git merge --squash feature/x", "dev", True),
        ("eval git merge feature/a \\; git merge --squash feature/x", "dev", True),
        ("eval git merge feature/a 'x;' git merge --squash feature/x", "dev", True),
        ("eval >|o git merge feature/a ';' git merge --squash feature/x", "dev", True),
        ("eval git mer''ge feature/a ';' git mer''ge --squash feature/x", "dev", True),
        ("eval git switch main ';' git merge stage", "dev", True),
        ("eval git switch main \\; git merge --no-ff stage", "dev", False),
        # 다시 파싱하는 프로그램이 없으면 인용된 `;` 는 인자로 남음
        ("env git merge -m ';' --no-ff fix/x", "dev", True),
        ("watch -x git merge -m 'a;b' --no-ff fix/x", "dev", True),
        ("watch --exec git merge -m 'a;b' --no-ff fix/x", "dev", True),
        ("find . -name eval -exec git merge -m 'a;b' --no-ff fix/x \\;", "dev", True),
        ("sudo -u eval git merge -m 'a;b' --no-ff fix/x", "dev", True),
        ("timeout -s eval 5 git merge -m 'x;y' --no-ff fix/x", "dev", True),
        ("sudo eval git merge feature/a ';' git merge --squash feature/x", "dev", True),
        ("eval git merge -m 'a;b' --no-ff fix/x", "dev", False),
        # 두 번째 파싱도 첫 파싱처럼 리다이렉션을 빼고 주석에서 끝남
        ("eval git merge '2>&1' --no-ff fix/x", "dev", True),
        ("eval git merge '&>o' --no-ff fix/x", "dev", True),
        ("eval git merge '>|o' --no-ff fix/x", "dev", True),
        ("ssh h git merge '2>&1' --no-ff fix/x", "dev", True),
        ("eval git switch main '2>&1' ';' git merge stage", "dev", True),
        ("eval git merge feature/x '#;' --squash", "dev", True),
        ("eval git merge feature/x '#' --squash", "dev", True),
        # 인용이 쪼갠 철자도 두 번째 파싱을 같게 읽음
        ("eval git mer''ge feature/x '#' --squash", "dev", True),
        ("eval git mer''ge '2>&1' --no-ff fix/x", "dev", True),
        ("watch -x git mer''ge -m 'a#' --no-ff fix/x", "dev", True),
        # 두 낱말에 걸친 인용, 두 번째 `eval`, `builtin eval`
        ("eval git merge -m \"'a\" \"b'\" feature/x ';' --squash", "dev", True),
        ("eval eval git merge feature/x \"';'\" --squash", "dev", True),
        ("builtin eval git merge feature/x ';' --squash", "dev", True),
        ("watch eval git merge feature/x \"';'\" --squash", "dev", True),
        # `ssh` 다음 낱말은 이름이 무엇이든 호스트
        ("ssh eval git merge -m \"'a;b'\" --no-ff fix/x", "dev", True),
    ],
)
def test_a_merge_is_read_as_bash_reparses_it(monkeypatch, tmp_path, command, branch, blocked):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        # 인용이 쪼갠 머지도 인용된 `;`·`>`·`|`·`(` 를 인자로 둠
        ("git mer''ge -m ';' --no-ff fix/x", "dev", True),
        ("git mer''ge -m '>' --no-ff fix/x", "dev", True),
        ("git mer''ge -m 'a|b' --no-ff fix/x", "dev", True),
        ("git mer''ge -m '(' --no-ff fix/x", "dev", True),
        ("git mer''ge " + chr(92) + chr(10) + " --no-ff fix/x", "dev", True),
        # 치환은 낱말 하나이고, 그 안의 머지도 판정함
        ("git mer''ge feature/x $(true; false) --squash", "dev", False),
        ("echo $(git mer''ge --no-ff fix/x)", "dev", True),
        ("git mer''ge feature/x $(git mer''ge --no-ff fix/y) --squash", "dev", True),
        # 마스크가 머지 하나를 보이는 단계에도 인용이 쪼갠 머지가 더 있을 수 있음
        ("eval git merge --squash feature/x ';' git mer''ge --no-ff fix/x", "dev", True),
        ("git mer''ge --no-ff fix/x & git merge --squash feature/y", "dev", True),
        ("git mer''ge --squash feature/x & git merge --no-ff fix/y", "dev", True),
        # 이름 붙은 fd 와 heredoc 연산자는 자기 리다이렉션에 딸림
        ("git merge {fd}>o --no-ff fix/x", "dev", True),
        ("git merge <<EOF --no-ff fix/x\nx\nEOF\n", "dev", True),
        ("git merge <<-EOF --no-ff fix/x\nx\nEOF\n", "dev", True),
        ("git merge <<'E O' --no-ff fix/x\nx\nE O\n", "dev", True),
        ("git merge --no-ff fix/x <<EOF\ngit merge feature/y\nEOF\n", "dev", True),
        # `watch`·`ssh` 의 옵션과 `ssh` 의 호스트를 건너뜀
        ("watch -n 1 eval git merge feature/x \"';'\" --squash", "dev", True),
        ("ssh h eval git merge feature/x \"';'\" --squash", "dev", True),
        ("ssh -p 22 user@h eval git merge feature/x \"';'\" --squash", "dev", True),
        ("ssh -o X=1 -p22 h eval git merge feature/x \"';'\" --squash", "dev", True),
        ("watch -x eval git merge feature/x ';' --squash", "dev", False),
    ],
)
def test_a_quote_split_merge_is_read_as_bash_joins_it(
    monkeypatch, tmp_path, command, branch, blocked
):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


@pytest.mark.parametrize(
    "command,branch,blocked",
    [
        # 다시 파싱되면 인용된 리다이렉션은 다음 낱말을 대상으로 가져감
        ("eval git merge feature/x '>' --squash", "dev", True),
        ("eval eval git merge feature/x '>' --squash", "dev", True),
        ("eval git merge feature/x '2>' --squash", "dev", True),
        ("eval git merge feature/x '>>' --squash", "dev", True),
        ("eval git merge feature/x '<' --squash", "dev", True),
        ("eval git merge feature/x '>|' --squash", "dev", True),
        ("eval git merge feature/x '&>' --squash", "dev", True),
        ("eval git merge feature/x \\> --squash", "dev", True),
        ("eval git mer''ge feature/x '>' --squash", "dev", True),
        ("sudo eval git mer''ge feature/x '>' --squash", "dev", True),
        ("ssh h git mer''ge feature/x '>' --squash", "dev", True),
        ("watch -n1 eval git mer''ge feature/x '>' --squash", "dev", True),
        ("eval git merge feature/x '>o' --squash", "dev", False),
        # here-string·heredoc 연산자는 `<` 여럿이 아니라 연산자 하나
        ("eval git merge feature/x '<<<' --squash", "dev", True),
        ("eval git merge feature/x '<<' --squash", "dev", True),
        ("eval git merge feature/x '<<-' --squash", "dev", True),
        ("git merge feature/x <<<hi --squash", "dev", False),
        ("eval eval git merge feature/x \"'<<<'\" --squash", "dev", True),
        ("ssh h eval git merge feature/x \"'<<<'\" --squash", "dev", True),
        ("ssh h git merge feature/x '<<<' --squash", "dev", True),
        # 낱말 안의 줄이음은 그 낱말을 이음
        ("git merge --no" + chr(92) + chr(10) + "-ff fix/x", "dev", True),
        ("git merge fi" + chr(92) + chr(10) + "x/x --no-ff", "dev", True),
        ("git mer" + chr(92) + chr(10) + "ge --no-ff fix/x", "dev", True),
        ("git switch ma" + chr(92) + chr(10) + "in && git merge stage", "dev", True),
        ("eval eval git merge -m 'a" + chr(92) + chr(10) + "b' --no-ff fix/x", "dev", True),
        ('eval eval git merge -m "a' + chr(92) + chr(10) + 'b" --no-ff fix/x', "dev", True),
        ("watch -n 1 eval git merge -m 'a" + chr(92) + chr(10) + "b' --no-ff fix/x", "dev", True),
        ('watch -n 1 eval git merge -m "a' + chr(92) + chr(10) + 'b" --no-ff fix/x', "dev", True),
        ("ssh h eval git merge -m 'a" + chr(92) + chr(10) + "b' --no-ff fix/x", "dev", True),
        ('ssh h eval git merge -m "a' + chr(92) + chr(10) + 'b" --no-ff fix/x', "dev", True),
        ("ssh -p 22 h eval git merge -m 'a" + chr(92) + chr(10) + "b' --no-ff fix/x", "dev", True),
        ('ssh -p 22 h eval git merge -m "a' + chr(92) + chr(10) + 'b" --no-ff fix/x', "dev", True),
        ('git merge -m "a' + chr(92) + chr(10) + 'b" --no-ff fix/x', "dev", True),
        ('git merge "fi' + chr(92) + chr(10) + 'x/x" --no-ff', "dev", True),
        ("git mer''ge \"fi" + chr(92) + chr(10) + 'x/x" --no-ff', "dev", True),
    ],
)
def test_a_redirection_and_continuation_parsed_again(
    monkeypatch, tmp_path, command, branch, blocked
):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, command, branch)
    assert (code == fgc.BLOCK_EXIT_CODE) is blocked, (command, code)


@pytest.mark.parametrize(
    "command,passes",
    [
        # 한 번 더 파싱 — 마스크 판독기 혼자 읽음
        ("eval " + "git merge --squash feature/x " * 50, 1),
        # 두 번 더 — 단계에 인용이 있어 두 판독기가 다 읽음
        ("eval eval git merge --squash feature/x \"';'\" " * 50, 4),
        ("ssh -p 22 h eval git merge --squash feature/x \"';'\" " * 50, 4),
    ],
)
def test_a_chain_behind_eval_parses_each_word_again_once(monkeypatch, command, passes):
    """머지마다 다시 파싱하면 머지 연쇄가 길이의 제곱을 치름."""
    import scripts._vway_paths as hp

    calls = []
    real = hp._reread
    monkeypatch.setattr(hp, "_reread", lambda w: calls.append(w) or real(w))
    assert len(fgc.parse_merge_commands(command)) == 50
    assert len(calls) <= passes * len(command.split())


def test_a_quoted_separator_parsed_again_is_an_argument():
    """명령 자리의 마스크는 인용된 낱말을 벗기므로 그 `;` 를 드러내면 안 됨."""
    import scripts._vway_paths as hp

    assert hp._reread(("';'",)) == ((";",), False)
    assert hp._reread((";",)) == ((), True)


@requires_bash_git
@pytest.mark.parametrize(
    "command,code",
    [
        ("eval git merge stage", 2),
        ("git merge >|o.txt stage", 2),
        ("eval git merge --no-ff stage", 0),
        ("echo git merge stage", 0),
        ("ssh h git merge '2>&1' stage", 2),
        ("eval git mer''ge stage", 2),
        ("find . -exec git merge stage \\;", 2),
        ("git merge {fd}>o.txt stage", 2),
        ("eval git merge stage '>' --no-ff", 2),
        ("ssh -p 22 h eval git merge stage \"';'\" --no-ff", 2),
    ],
)
def test_the_runner_judges_a_merge_bash_runs(tmp_path, command, code):
    """러너 경로 그대로 — main 위에서 stage 를 `--no-ff` 없이 들이는 머지는 막힘."""
    _init_repo(tmp_path)
    _write_policy(tmp_path)
    _rg(["branch", "stage"], tmp_path)
    r = _run_runner(tmp_path, command)
    assert r.returncode == code, (r.stdout, r.stderr)
