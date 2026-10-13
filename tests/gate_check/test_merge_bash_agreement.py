"""merge 경로가 읽은 호출과 bash 가 실제로 돌린 호출의 일치.

각 명령을 기록만 하는 스텁 `git`·`ssh`·`watch`·`sudo` 아래 bash 로 돌리고, 게이트가 찾은
merge 경로 호출(`_live_calls`)이 bash 가 실행한 것과 같아야 함 — 손으로 쓴 기대값이 아니라.
치환의 출력은 게이트가 모르므로, 게이트 쪽의 불투명 낱말과 bash 쪽의 빈 낱말은 둘 다
비교에서 빠짐. `git checkout` 은 게이트처럼 `switch` 로 셈."""

import os
import shutil
from collections import Counter
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from scripts._vway_paths import OPAQUE_CH, mask_literals
from tests._proc import run_bounded
from tests.gate_check.bash_corpus import CORPUS, KNOWN_GAPS

BASH = shutil.which("bash") if os.name != "nt" else None
pytestmark = pytest.mark.skipif(BASH is None, reason="오라클은 POSIX 의 bash 로 돎")

_GIT_GLOBAL_WITH_ARG = frozenset(
    ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env")
)
_MERGE_PATH_WORDS = {"merge": "merge", "pull": "pull", "switch": "switch", "checkout": "switch"}

_STUBS = {
    "git": r"""#!/usr/bin/env bash
# one write per record: a git running in a process substitution logs at the same time
record="$(printf '%s' "${REMOTE:-0}"; printf '\x1f%s' "$@"; printf '\x1e')"
printf '%s' "$record" >>"$ORACLE_LOG"
# drain a process substitution's pipe, so whatever runs in it has logged before this exits
for arg in "$@"; do case "$arg" in /dev/fd/*) cat "$arg" >/dev/null ;; esac; done
""",
    "ssh": r"""#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  case "$1" in
    -[BbcDEeFIiJLlmOoPpQRSWw]) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
shift
REMOTE=1 exec bash -c "$*"
""",
    "watch": r"""#!/usr/bin/env bash
direct=0
while [ $# -gt 0 ]; do
  case "$1" in
    -x|--exec) direct=1; shift ;;
    -n|--interval|-q|--equexit) shift 2 ;;
    -[!-]*x*) direct=1; shift ;;
    -*) shift ;;
    *) break ;;
  esac
done
[ "$direct" -eq 1 ] && exec "$@"
exec sh -c "$*"
""",
    "sudo": r"""#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  case "$1" in
    -[ugCDhprtTU]) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
exec "$@"
""",
}


def _normalized(words) -> tuple[str, ...]:
    # 통째로 치환 출력인 낱말은 어느 쪽도 이름 댈 수 없음. 일부만 그런 낱말은 게이트가 잘못
    # 읽은 낱말이라 남김
    return tuple(w for w in words if w.strip(OPAQUE_CH))


def _key(word, global_opts, operands, mode):
    operands = _normalized(operands)
    if mode == "flags":
        operands = tuple(w for w in operands if w.startswith("-"))
    return (word, tuple(global_opts), operands)


def _bash_reads(command: str, tmp_path: Path, mode: str) -> Counter:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in _STUBS.items():
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    log = tmp_path / "log"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ORACLE_LOG": str(log)}
    # 프로세스 치환은 백그라운드로 돎: 기다리지 않으면 그 git 이 읽은 뒤에 기록할 수 있음
    run_bounded(
        [BASH, "--noprofile", "--norc", "-c", command + "\nwait"], cwd=work, env=env, timeout=20
    )
    found = Counter()
    raw = log.read_bytes().decode("utf-8", "replace") if log.exists() else ""
    for record in filter(None, raw.split("\x1e")):
        remote, *argv = record.split("\x1f")
        i = 0
        while i < len(argv) and argv[i].startswith("-"):
            i += 2 if argv[i] in _GIT_GLOBAL_WITH_ARG else 1
        if i >= len(argv) or argv[i] not in _MERGE_PATH_WORDS:
            continue
        word = _MERGE_PATH_WORDS[argv[i]]
        if remote == "1" and word == "switch":
            continue  # 원격 HEAD 를 옮길 뿐, 이쪽 HEAD 는 아님
        found[_key(word, argv[:i], argv[i + 1 :], mode)] += 1
    return found


def _gate_reads(command: str, mode: str) -> Counter:
    masked = mask_literals(command)
    found = Counter()
    for word, calls in fgc._live_calls(command, masked).items():
        for call in calls:
            global_opts, operands = fgc._call_words(command, masked, call)
            found[_key(word, global_opts, operands, mode)] += 1
    return found


def _row(entry):
    return (entry, "full") if isinstance(entry, str) else entry


@pytest.mark.parametrize("command,mode", [_row(e) for e in CORPUS])
def test_the_gate_reads_what_bash_runs(tmp_path, command, mode):
    assert _gate_reads(command, mode) == _bash_reads(command, tmp_path, mode), command


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(c, marks=pytest.mark.xfail(strict=True, reason=r))
        for c, r in KNOWN_GAPS.items()
    ],
)
def test_a_known_gap_still_disagrees_with_bash(tmp_path, command):
    assert _gate_reads(command, "full") == _bash_reads(command, tmp_path, "full"), command
