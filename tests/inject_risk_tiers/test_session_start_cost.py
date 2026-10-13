"""훅이 흔한 경로에서 아무것도 fork 하지 않는지.

`$(...)` 하나가 fork 하나이고, Git Bash 의 msys 런타임에서 fork 는 수십 ms(실측치는 훅 주석).
벽시계 상한은 맞춘 플랫폼 하나에서만 버티므로, 서브셸 수를 세어 모든 플랫폼에서 비용을 못 박음.
"""

import os
import subprocess
from pathlib import Path

import pytest

from tests.inject_risk_tiers._helpers import BASH, SCRIPT, STARTUP, STYLE_BODY, _manifest


def _trace(plugin: Path, project: Path, *args: str, path: str | None = None):
    env = {
        "PATH": os.environ.get("PATH", "") if path is None else path,
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "CLAUDE_PLUGIN_ROOT": str(plugin),
        "CLAUDE_PROJECT_DIR": str(project),
        "PS4": "+${BASH_SUBSHELL}| ",
    }
    return subprocess.run(
        [BASH, "-x", str(SCRIPT), *args],
        input=STARTUP,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=30,
    )


# 경우별: 훅 인자, 그리고 프로젝트 매니페스트의 버전(None = 소비자 repo, 매니페스트 없음).
CASES = {
    "consumer": ((), None),
    "same-version": ((), "0.8.0"),
    "notice": ((), "9.9.9"),
    "codex": (("--harness", "codex"), "9.9.9"),
}


def _fixture(tmp_path: Path, project_version: str | None) -> tuple[Path, Path]:
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    (plugin / "rules" / "doc-style.md").write_text(STYLE_BODY, encoding="utf-8", newline="")
    if project_version is None:
        project = tmp_path / "consumer"
        project.mkdir()
    else:
        project = _manifest(tmp_path / "src", "vway-kit", project_version)
    return plugin, project


@pytest.mark.parametrize("case", list(CASES))
def test_no_subshell_runs(tmp_path, case):
    args, version = CASES[case]
    result = _trace(*_fixture(tmp_path, version), *args)
    assert result.returncode == 0, result.stderr
    # PS4 의 첫 글자는 간접 단계마다 한 번씩 반복됨 — 명령 치환도 마찬가지.
    traced = [line for line in result.stderr.splitlines() if line.startswith("+")]
    forked = [line for line in traced if line.startswith("++") or not line.startswith("+0|")]
    assert traced, "트레이스가 비었다 — PS4 가 먹지 않으면 이 테스트는 아무것도 안 잼"
    assert not forked, "\n".join(forked[:10])


@pytest.mark.parametrize("case", list(CASES))
def test_no_external_command_runs(tmp_path, case):
    """PATH 를 비워도 PATH 가 있을 때와 똑같이 씀 — 외부 프로그램이 필요 없는 훅이라는 뜻."""
    args, version = CASES[case]
    plugin, project = _fixture(tmp_path, version)
    with_path = _trace(plugin, project, *args)
    without = _trace(plugin, project, *args, path="")
    assert (without.returncode, without.stdout) == (0, with_path.stdout)
