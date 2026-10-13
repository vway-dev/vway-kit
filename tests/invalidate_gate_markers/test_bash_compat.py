"""출하 셸 스크립트가 지켜야 할 bash 하한과, 그 하한을 붙드는 백스톱."""

import re
from pathlib import Path

from tests.invalidate_gate_markers._helpers import (
    REPO,
    SCRIPT,
    pytestmark,  # noqa: F401 — 모듈 수준 skip 은 이 이름으로만 걸림
)


def _bash_4_offenders(scripts) -> list[str]:
    """`scripts` 에서 찾은 bash 4 전용 구문 전부, `path:line: 이유 -- 코드` 모양."""
    bash_4_only = [
        (
            r"\bread\b(?:\s+(?:-[A-Za-z]+|'[^']*'|\"[^\"]*\"|[^-\s][^\s]*))*\s+-[A-Za-z]*N",
            "read -N (4.1) - `head -c` 로",
        ),
        (r"\bmapfile\b|\breadarray\b", "4.0 - 루프에서 변수로 읽을 것"),
        (
            r"\b(?:declare|typeset|local)\s+-[A-Za-z]*A",
            "연관 배열 (4.0) - 나란한 목록으로",
        ),
        (r"\bcoproc\b", "4.0"),
        (r"&>>", "4.0 - `>>file 2>&1` 로"),
        (r"\|&", "4.0 - `2>&1 |` 로"),
        (r"\$\{[A-Za-z_][A-Za-z0-9_]*\^", "대소문자 변환 (4.0)"),
        (r"\$\{[A-Za-z_][A-Za-z0-9_]*,", "대소문자 변환 (4.0)"),
    ]
    offenders = []
    for script in scripts:
        for line_no, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split(chr(35), 1)[0]
            for pattern, why in bash_4_only:
                if re.search(pattern, code):
                    rel = (
                        script.relative_to(REPO).as_posix()
                        if script.is_relative_to(REPO)
                        else script.name
                    )
                    offenders.append(f"{rel}:{line_no}: {why} -- {code.strip()}")
    return offenders


def test_no_shipped_shell_script_needs_a_bash_newer_than_macos_ships():
    """macOS 의 시스템 bash 는 3.2.57 이고, `check-deps.sh` 는 mac 사용자에게 bash 가 "기본
    제공"이라 말하며 README 는 버전 하한을 적지 않음. 4.x 전용 내장은 그곳에서 구문 오류가
    아님 — 옵션이 실행 시점에 실패하고, 채워졌어야 할 값이 빈 채로 남고, 훅은 그 빈 값대로
    움직임. 이 훅에게 그것은 편집마다 엉뚱한 트리의 증거를 무효화하는 것이고, 이 훅이 절대
    틀리면 안 되는 방향."""
    scripts = sorted(REPO.glob("hooks/*.sh")) + sorted(REPO.glob("scripts/*.sh"))
    assert scripts, "출하 셸 스크립트를 못 찾음 — 글롭이 매치를 멈춤"
    offenders = _bash_4_offenders(scripts)
    assert not offenders, "출하 스크립트의 bash 4 구문:" + chr(10) + chr(10).join(offenders)


def test_check_deps_names_the_program_the_payload_read_runs():
    """`check-deps.sh` 가 있는 이유는 셸 유틸리티 부재가 스스로 알리지 않기 때문: 필터가 비고
    게이트가 조용히 통과함. 페이로드 읽기가 훅의 유일한 외부 프로세스를 쓰고, 그 프로그램이
    없으면 페이로드가 비어 아무도 편집하지 않은 트리의 마커가 지워지고 편집된 repo 는 자기
    마커를 지킴. 그래서 두 파일이 같은 프로그램을 대야 하고, 읽기가 프로그램을 바꾸는 날
    소비자의 다음 커밋이 아니라 이것이 실패함."""
    read_line = next(
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.startswith("payload=")
    )
    program = re.search(r"\$\(\s*([A-Za-z0-9_.-]+)", read_line)
    assert program, read_line
    listed = re.search(
        r"for _u in ([^;]+); do",
        (REPO / "scripts" / "check-deps.sh").read_text(encoding="utf-8"),
    )
    assert listed, "check-deps.sh 가 도구 목록을 이름 위의 `for` 로 적지 않음"
    assert program.group(1) in listed.group(1).split(), (
        f"{program.group(1)} 이 편집마다 도는데 check-deps.sh 가 확인하지 않음: "
        f"{listed.group(1).strip()}"
    )


def test_the_bash_4_denylist_reads_an_option_list_not_a_spelling(tmp_path: Path):
    """거부 목록은 아는 철자만큼만 좋고, 다음 철자를 놓치는 백스톱은 아무도 모르는 백스톱.
    아래 각 줄은 목록이 이미 대는 내장을 사람이 적을 법한 방식으로 쓴 것."""
    spellings = (
        "IFS= read -r -N 65536 payload",
        "read -N 100 x",
        "read -rN 100 x",
        "IFS= read -d '' -r -N 20 x",
        'read -d "" -N 20 x',
        "read -t 1 -N 20 x",
        "read -u 3 -N 20 x",
        "read -d , -N 20 x",
        "declare -A seen",
        "declare -gA seen",
        "declare -Ag seen",
        "local -A seen",
        "typeset -A seen",
        "mapfile -t lines < f",
        "readarray -t lines < f",
        "coproc x { cat; }",
        "printf x &>> log",
        "cat f |& tee log",
        'echo "${name^^}"',
        'echo "${name,,}"',
        'echo "${name^}"',
        'echo "${name,}"',
    )
    for spelling in spellings:
        script = tmp_path / "probe.sh"
        script.write_text(
            "#!/usr/bin/env bash" + chr(10) + spelling + chr(10), encoding="utf-8", newline=chr(10)
        )
        assert _bash_4_offenders([script]), spelling


def test_the_bash_4_denylist_leaves_the_shapes_bash_3_allows(tmp_path: Path):
    """반대 절반: 평범한 3.2 코드에 발화하는 목록은 고쳐지지 않고 꺼짐."""
    for spelling in (
        "IFS= read -r line",
        "IFS= read -r -t 1 -d '' hook_stdin",
        "IFS=. read -r -a A <<< $a",
        "declare -r NAME=x",
        "printf x >> log 2>&1",
        "cat f 2>&1 | tee log",
        'echo "${name%%/*}"',
        'echo "${name//x/y}"',
    ):
        script = tmp_path / "probe.sh"
        script.write_text(
            "#!/usr/bin/env bash" + chr(10) + spelling + chr(10), encoding="utf-8", newline=chr(10)
        )
        assert not _bash_4_offenders([script]), spelling
