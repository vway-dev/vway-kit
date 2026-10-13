"""`tests/_proc.py::run_bounded` — 자식의 멈춤이 스위트의 멈춤이 되지 않는가.

지키는 것은 하나: 시간이 다 되면 손자가 살아 있어도 돌아옴. 나머지는 `subprocess.run` 에서
옮겨 온 호출부가 기대하는 의미(텍스트 디코드·개행·입력·check)가 그대로인지 잼. 마지막 가드는
`_GUARDED` 폴더가 이 헬퍼만 쓰는지 — 직접 호출 하나가 파이프를 다시 들여오면 그 테스트가
멈춤의 문이 됨.
"""

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._bash import BASH
from tests._proc import run_bounded

REPO = Path(__file__).resolve().parent.parent
_PY = sys.executable


@pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
def test_a_grandchild_holding_the_output_does_not_outlast_the_timeout():
    """bash 가 손자를 띄우고 기다림. 시간이 다 되면 bash 만 죽고 `sleep` 은 출력 핸들을 쥔 채
    남음 — 파이프였다면 Windows 의 `run` 은 그 핸들이 닫힐 때까지(20초) 다시 읽음."""
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([BASH, "-c", "sleep 20 & wait"], timeout=1)
    assert time.monotonic() - start < 10


def test_text_output_is_decoded_as_utf8_with_newlines_folded():
    """호출부는 `text=True` 로 받은 줄을 `splitlines`·`==` 로 비교함. 로캘로 디코드하면 cp949
    호스트에서 한글이 깨지고(Invariant 2), CRLF 를 그대로 두면 Windows 에서만 비교가 틀어짐."""
    code = "import sys; sys.stdout.buffer.write('한글\\r\\nok\\n'.encode('utf-8'))"
    assert run_bounded([_PY, "-c", code], text=True).stdout == "한글\nok\n"


def test_input_reaches_stdin_byte_for_byte():
    """`bash -s` 호출부는 스크립트를 stdin 으로 넘김 — CR 하나가 끼면 bash 가 그것을 명령의
    일부로 읽음."""
    echo = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
    assert run_bounded([_PY, "-c", echo], input=b"a\nb\n").stdout == b"a\nb\n"


def test_without_input_the_child_reads_end_of_file_rather_than_waiting():
    """입력 없는 호출이 테스트 프로세스의 stdin 을 물려받으면, 자식이 stdin 을 읽는 순간 사람이
    칠 때까지 멈춤."""
    read = "import sys; print(len(sys.stdin.buffer.read()))"
    assert run_bounded([_PY, "-c", read], text=True, timeout=10).stdout.strip() == "0"


def test_check_raises_with_the_output_attached():
    code = "import sys; print('out'); sys.exit(3)"
    with pytest.raises(subprocess.CalledProcessError) as info:
        run_bounded([_PY, "-c", code], text=True, check=True)
    assert info.value.returncode == 3
    assert info.value.stdout.strip() == "out"


# ── 가드: 이 폴더들은 run_bounded 로만 띄움 ──────────────────────────────────────

_GUARDED = ("tests/gate_check", "tests/skill_docs", "tests/doc_style")
_SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}


def _direct_spawns(source: str) -> list[int]:
    """`subprocess` 의 프로세스 생성 함수를 부르는 줄. `import subprocess as sp` 와
    `from subprocess import run` 도 셈 — 철자 하나만 보면 별칭이 가드를 지나감."""
    tree = ast.parse(source)
    modules, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.asname or a.name for a in node.names if a.name == "subprocess"}
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            names |= {a.asname or a.name for a in node.names if a.name in _SPAWNERS}
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _SPAWNERS:
            if isinstance(func.value, ast.Name) and func.value.id in modules:
                lines.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id in names:
            lines.append(node.lineno)
    return sorted(lines)


def test_the_spawn_scanner_sees_every_spelling():
    """스캐너가 아무것도 못 보면 아래 가드는 늘 초록 — 가드 자체를 먼저 잼."""
    source = (
        "import subprocess\nimport subprocess as sp\nfrom subprocess import run as r\n"
        "subprocess.run([])\nsp.Popen([])\nr([])\nsubprocess.DEVNULL\n"
    )
    assert _direct_spawns(source) == [4, 5, 6]


def test_the_guarded_folders_spawn_only_through_run_bounded():
    offenders = []
    for folder in _GUARDED:
        files = sorted((REPO / folder).rglob("*.py"))
        assert files, f"{folder}: no Python files — the guard would pass on nothing"
        for path in files:
            for line in _direct_spawns(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(REPO).as_posix()}:{line}")
    assert not offenders, (
        "direct subprocess spawn — a pipe a grandchild can hold turns a hang into a stalled "
        f"suite; use tests._proc.run_bounded: {offenders}"
    )
