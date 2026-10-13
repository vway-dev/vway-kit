"""Microsoft Store 앱 실행 별칭인 python3 — 게이트와 check-deps 가 그것을 이름으로 짚는지.

별칭은 `command -v python3` 에 답하고 인터프리터는 안 돌림. 버전 검사만 보면 "너무 낡음"으로
잘못 읽혀, 고칠 방법이 틀린 안내가 나감.
"""

import os
import sys
from pathlib import Path

import pytest

from tests._proc import run_bounded
from tests.gate_check._helpers import _REPO_BASH, _init_repo, _run_runner, requires_bash_git

REPO = Path(__file__).resolve().parent.parent.parent
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PATH 의 가짜 python3")


def _stub_path(tmp_path: Path) -> str:
    """python 을 안 돌리는 python3 가 Store 이름의 디렉터리에 앞선 PATH."""
    stub = tmp_path / "WindowsApps"
    stub.mkdir()
    (stub / "python3").write_text("#!/bin/sh\nexit 9009\n", encoding="utf-8")
    (stub / "python3").chmod(0o755)
    return f"{stub}{os.pathsep}{os.environ['PATH']}"


@posix_only
@requires_bash_git
def test_the_gate_names_the_store_alias(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _init_repo(main)
    r = _run_runner(main, "git commit -m x", env_extra={"PATH": _stub_path(tmp_path)})
    assert r.returncode == 2
    assert "Microsoft Store" in r.stderr


@posix_only
def test_check_deps_names_the_store_alias(tmp_path):
    env = {**os.environ, "PATH": _stub_path(tmp_path)}
    r = run_bounded(
        [_REPO_BASH or "bash", str(REPO / "scripts" / "check-deps.sh")],
        env=env,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 1
    assert "Microsoft Store" in r.stdout + r.stderr
