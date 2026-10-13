"""공통 release-notes 블록 — 릴리스 템플릿 여섯과 이 저장소 자신의 release.yml, 총 일곱이 같은
글자로 갖고, 실제 셸로 돌림.

블록은 정식 절이 있으면 릴리스 본문을 그 절로 바꾸고, 없으면 만들어진 본문을 그대로 둠.
절 부재·스크립트 부재·`gh` 실패가 전부 통과여야 함 — 태그를 이미 민 뒤의 스텝이라 여기서
멈추면 반쯤 릴리스된 상태로 붉어짐.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests._proc import run_bounded
from tests.gate_check._helpers import _REPO_BASH

PLUGIN = Path(__file__).resolve().parent.parent
BEGIN, END = "# >>> vway-release-notes", "# <<< vway-release-notes"
_WORKFLOWS = [
    f"github/release.{tool}.workflow.example.yml"
    for tool in (
        "python-semantic-release",
        "semantic-release",
        "gitversion",
        "cargo-release",
        "jreleaser",
        "sbt-ci-release",
    )
] + [".github/workflows/release.yml"]

requires_bash = pytest.mark.skipif(not _REPO_BASH, reason="실제 bash 필요")


def _block(rel: str) -> list[str]:
    lines = (PLUGIN / rel).read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(BEGIN))
    end = next(i for i, line in enumerate(lines) if line.strip().startswith(END))
    return [line.strip() for line in lines[start : end + 1]]


def test_every_release_workflow_carries_the_same_block():
    blocks = {rel: _block(rel) for rel in _WORKFLOWS}
    first = blocks[_WORKFLOWS[0]]
    assert len(first) > 2
    for rel, block in blocks.items():
        assert block == first, f"{rel}: release-notes 블록이 다름 — 한 곳을 고쳤으면 나머지도."


@pytest.mark.parametrize("rel", _WORKFLOWS)
def test_the_block_runs_on_the_stable_branch_with_a_tag(rel: str):
    """rc 에서 돌면 프리릴리스 본문이 정식 절로 바뀌고, 태그 없는 실행은 남의 태그를 고침."""
    text = (PLUGIN / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    step = text.split("- name: 정식 릴리스 노트 — CHANGELOG 절", 1)[1].split("run: |")[0]
    stable = "'main'" if rel.startswith(".github") else "'__VWAY_STABLE__'"
    assert f"github.ref_name == {stable}" in step, rel
    assert "steps.released.outputs.tag != ''" in step, rel
    assert "VWAY_SCRIPTS:" in step and "GH_TOKEN:" in step, rel


@pytest.mark.parametrize("rel", _WORKFLOWS)
def test_every_step_reference_names_a_step_that_exists(rel: str):
    """`steps.<id>.outputs` 가 없는 id 를 가리키면 그 표현식은 빈 문자열 — 조건이 조용히 거짓이
    되어 스텝이 영영 안 돎. 글자 단언만으로는 안 보임(그 조건은 그대로 적혀 있음)."""
    import yaml

    doc = yaml.safe_load((PLUGIN / rel).read_text(encoding="utf-8")) or {}
    for job_name, job in (doc.get("jobs") or {}).items():
        steps = job.get("steps") or []
        ids = {s.get("id") for s in steps if s.get("id")}
        text = yaml.safe_dump(job, allow_unicode=True)
        used = set(re.findall(r"steps\.([A-Za-z0-9_-]+)\.outputs", text))
        assert used <= ids, f"{rel} [{job_name}]: 없는 스텝을 가리킴 — {sorted(used - ids)}"


CHANGELOG = """# CHANGELOG

<!-- version list -->

## v1.1.0 (2026-09-24)

### Features

- **x**: 요약 한 줄


## v1.1.0-rc.1 (2026-09-20)

- 접기 전 rc 줄
"""


def _run(tmp_path: Path, tag: str, changelog: str | None, scripts: Path, gh_exit: int = 0):
    work, bin_dir = tmp_path / "work", tmp_path / "bin"
    work.mkdir()
    bin_dir.mkdir()
    if changelog is not None:
        (work / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    log, notes = tmp_path / "gh.log", tmp_path / "notes.md"
    gh = bin_dir / "gh"
    gh.write_text(
        f'#!/usr/bin/env bash\necho "$*" >> "{log.as_posix()}"\n'
        f'cp "${{@: -1}}" "{notes.as_posix()}"\nexit {gh_exit}\n',
        encoding="utf-8",
        newline="\n",
    )
    gh.chmod(0o755)
    script = tmp_path / "block.sh"
    # `python3` 은 Windows 에서 스토어 별칭일 수 있음 — bash 가 보는 PATH 앞에 스텁 디렉터리.
    script.write_text("\n".join(_block(_WORKFLOWS[0])), encoding="utf-8", newline="\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "VWAY_SCRIPTS": str(scripts),
        "RUNNER_TEMP": str(tmp_path),
        "TAG": tag,
    }
    r = run_bounded([_REPO_BASH, script.as_posix()], cwd=str(work), env=env, text=True, timeout=60)
    return r, (log.read_text(encoding="utf-8") if log.exists() else ""), notes


@requires_bash
def test_a_stable_section_replaces_the_release_notes(tmp_path: Path):
    r, calls, notes = _run(tmp_path, "v1.1.0", CHANGELOG, PLUGIN / "scripts")
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls.startswith("release edit v1.1.0 --notes-file")
    body = notes.read_text(encoding="utf-8")
    assert "요약 한 줄" in body and "접기 전 rc 줄" not in body


@requires_bash
@pytest.mark.parametrize(
    ("tag", "changelog", "scripts"),
    [
        ("v1.2.0", CHANGELOG, "scripts"),  # 그 버전의 정식 절이 없음
        ("v1.1.0", None, "scripts"),  # CHANGELOG 자체가 없음
        ("v1.1.0", CHANGELOG, "missing"),  # 호스트 사본이 없음(옛 /vdev-init)
    ],
)
def test_nothing_to_read_keeps_the_notes(tmp_path: Path, tag, changelog, scripts):
    root = PLUGIN if scripts == "scripts" else tmp_path
    r, calls, _ = _run(tmp_path, tag, changelog, root / scripts)
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls == "", r.stdout


@requires_bash
def test_a_failed_edit_warns_and_passes(tmp_path: Path):
    r, calls, _ = _run(tmp_path, "v1.1.0", CHANGELOG, PLUGIN / "scripts", gh_exit=1)
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls and "::warning::" in r.stdout
