"""출하하는 스크립트가 `core.autocrlf` 와 무관하게 자기 인터프리터의 줄끝으로 체크아웃되는지.

플러그인 캐시는 소비자 머신의 git 체크아웃이고 `/vdev-init` 은 스크립트를 바이트 그대로
복사함. Git Bash 는 CRLF 스크립트를 견디지만 Linux bash 는 실패함 — 문법 오류로 죽은 게이트
훅은 0 도 2 도 아닌 코드로 끝나 게이트가 fail-open 됨. `cmd.exe` 는 LF 배치 파일의 레이블·
`goto` 를 잘못 읽음.
"""

from pathlib import Path

import pytest

from tests._proc import run_bounded

REPO = Path(__file__).resolve().parents[2]


def _git(args: list[str], stdin: str | None = None) -> str:
    return run_bounded(["git", *args], cwd=REPO, input=stdin, encoding="utf-8", check=True).stdout


@pytest.mark.parametrize(("pattern", "want"), [("*.sh", "lf"), ("*.cmd", "crlf")])
def test_every_tracked_script_checks_out_its_interpreters_eol(pattern, want):
    scripts = [s for s in _git(["ls-files", "-z", "--", pattern]).split("\0") if s]
    assert scripts, f"추적되는 {pattern} 없음 — 패턴이 트리와 더는 안 맞음"
    attrs = _git(["check-attr", "-z", "--stdin", "eol"], stdin="\0".join(scripts) + "\0")
    fields = attrs.split("\0")
    eol = {fields[i]: fields[i + 2] for i in range(0, len(fields) - 2, 3)}
    wrong = sorted(path for path in scripts if eol.get(path) != want)
    assert not wrong, f".gitattributes 에 eol={want} 가 없는 {pattern}: {wrong}"
