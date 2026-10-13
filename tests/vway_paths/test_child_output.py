"""자식 출력 디코딩 — git 이 내는 UTF-8 을 로캘 코드페이지로 읽지 않는가.

`force_utf8_io()` 는 표준 스트림과 자식 환경만 바꿈. 이 프로세스의 로캘 인코딩은 시작 때
정해져서, `text=True` 는 `encoding=` 이 없으면 여전히 그것(한국어 Windows 는 cp949)으로 디코드함.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts._vway_paths as vp
from tests._non_utf8 import non_utf8_env
from tests.vway_paths._helpers import _repo_with_worktree

SCRIPTS = Path(vp.__file__).resolve().parent

# 자식을 띄우는 subprocess 함수 — 이 저장소는 전부 `subprocess.<이름>` 으로 부름.
_SPAWNERS = {"run", "Popen", "check_output", "check_call", "call"}


def test_working_root_follows_a_worktree_under_a_korean_path(tmp_path: Path):
    """재지정은 git 질의 둘(common-dir·toplevel)의 문자열 비교로 정해짐. 둘이 똑같이 깨지면
    비교는 통과하고 없는 경로로 재지정됨 — 게이트가 존재하지 않는 트리를 검사함."""
    base = tmp_path / "한글"
    base.mkdir()
    main, wt = _repo_with_worktree(base)
    code = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "import _vway_paths as v; "
        "cmd = 'git -C \"' + sys.argv[3] + '\" commit -m x'; "
        "got = v.working_root(project_dir=Path(sys.argv[2]), command=cmd); "
        "sys.stdout.buffer.write(str(got).encode('utf-8', 'surrogateescape'))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(SCRIPTS), str(main), str(wt)],
        env=non_utf8_env(),
        capture_output=True,
        check=True,
    )
    got = Path(out.stdout.decode("utf-8"))
    assert got.exists(), f"없는 경로로 재지정됨: {got!r}"
    assert os.path.samefile(got, wt)


@pytest.mark.skipif(os.name == "nt", reason="NTFS 는 비UTF-8 바이트 이름을 못 만듦")
def test_host_root_keeps_a_non_utf8_byte_path_intact(tmp_path: Path):
    """POSIX 의 git 은 파일 이름의 원시 바이트를 냄. UTF-8 로 읽고 `replace` 하면 없는 경로가 되고,
    그 밑의 config·양식·평문 계정 파일(`teamer_api setup` 의 이전 대상)을 통째로 놓침."""
    raw = os.path.join(os.fsencode(tmp_path), b"caf\xe9")
    try:
        os.mkdir(raw)
    except OSError:
        pytest.skip("이 파일시스템은 비UTF-8 바이트 이름을 거절함")
    host = Path(os.fsdecode(raw))
    (host / "sub").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=host, check=True)
    code = (
        "import os, sys; sys.path.insert(0, sys.argv[1]); import _vway_paths as v; "
        "sys.stdout.buffer.write(os.fsencode(str(v.host_root())))"
    )
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    out = subprocess.run(
        [sys.executable, "-c", code, str(SCRIPTS)],
        # 하위 디렉터리에서 — 폴백(cwd)이 답과 겹치면 git 의 답을 못 잼.
        cwd=host / "sub",
        env=env,
        capture_output=True,
        check=True,
    )
    assert os.path.exists(out.stdout), f"없는 경로: {out.stdout!r}"
    assert os.path.samefile(out.stdout, raw)


def _text_mode_without_encoding(path: Path) -> list[int]:
    """`text=`·`universal_newlines=` 를 켜고 `encoding=` 은 안 적은 자식 호출의 줄 번호."""
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _SPAWNERS:
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        turned_on = [
            v
            for v in (kw.get("text"), kw.get("universal_newlines"))
            if v is not None and not (isinstance(v, ast.Constant) and v.value in (False, None))
        ]
        if turned_on and "encoding" not in kw:
            lines.append(node.lineno)
    return lines


def test_every_text_mode_child_in_scripts_names_its_encoding():
    """위 테스트와 `alm_layers` CLI 테스트는 아는 자리만 잼 — 새 `text=True` 호출은 둘 다 모름.
    `scripts/` 는 호스트로 복사돼 훅에서 도는 SOURCE 라, 한 자리의 누락이 게이트의 조용한
    FAIL-OPEN 이 됨(Invariant 2)."""
    offenders = [
        f"{p.name}:{line}"
        for p in sorted(SCRIPTS.glob("*.py"))
        for line in _text_mode_without_encoding(p)
    ]
    assert not offenders, (
        f"encoding 없는 text 모드 자식 호출: {offenders} — 텍스트는 "
        '`encoding="utf-8", errors="replace"`, 루트를 정하는 경로는 `_GIT_PATH_ENCODING` '
        "(근거는 _vway_paths)"
    )
