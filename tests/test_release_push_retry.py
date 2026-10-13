"""워크플로가 직접 하는 릴리스 push 가 일시 거부를 견디는지 — 실제 bash 와 bare 원격으로 잼.

- 릴리스 뒤 push(pin marketplace sha · sync uv.lock): 태그 push 뒤라 재실행으로 복구 못 함 —
  재실행은 `released=false` 로 스텝을 건너뜀. 움직인 원격 위로 rebase 하며 재시도.
- 릴리스 커밋·태그 push: 태그 없이 브랜치만 오르면 다음 실행이 같은 버전을 다시 계산함. rebase 없이
  재시도하고(버전·노트가 push 전 트리에서 나옴), 커밋을 올리는 곳은 `--atomic` 으로 둘을 묶음.
"""

import os
import re
from pathlib import Path

import pytest
import yaml

from tests._bash import BASH
from tests._proc import run_bounded

ROOT = Path(__file__).resolve().parent.parent
_RETRIED_PUSH_STEPS = ("Pin both marketplaces", "Sync uv.lock")
_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]


def _push_loop(step_prefix: str) -> str:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    steps = yaml.safe_load(text)["jobs"]["release"]["steps"]
    run = next(s["run"] for s in steps if s.get("name", "").startswith(step_prefix))
    m = re.search(r"^ *for attempt in .*?^ *done$", run, re.M | re.S)
    assert m, f"{step_prefix}: push 를 감싼 재시도 루프 없음"
    assert run.count("git push") == m.group(0).count("git push") == 1, (
        f"{step_prefix}: 루프 밖 push 는 거부 한 번에 릴리스를 실패시킴"
    )
    return m.group(0)


def _git(*args: str) -> None:
    run_bounded([*_GIT, *args], check=True)


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    _git("-C", str(repo), "add", name)
    _git("-C", str(repo), "commit", "-qm", name)


@pytest.mark.skipif(not BASH, reason="실제 bash 필요")
@pytest.mark.parametrize("step", _RETRIED_PUSH_STEPS)
def test_post_release_push_retries_over_a_moved_remote(step, tmp_path):
    """checkout 과 push 사이에 원격이 움직이면 push 가 한 번 거부됨 — 루프가 그 위로 rebase 해
    커밋을 올리고 릴리스를 실패시키지 않음."""
    remote, work, other = tmp_path / "remote.git", tmp_path / "work", tmp_path / "other"
    _git("init", "-q", "--bare", str(remote))
    _git("clone", "-q", str(remote), str(work))
    _commit(work, "base")
    _git("-C", str(work), "push", "-q", "origin", "HEAD:main")
    _commit(work, "ours")
    _git("clone", "-q", str(remote), str(other))
    _commit(other, "theirs")
    _git("-C", str(other), "push", "-q", "origin", "HEAD:main")

    loop = _push_loop(step).replace("sleep ", ": ")
    env = {
        **os.environ,
        "GITHUB_REF_NAME": "main",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    result = run_bounded([BASH, "-ec", loop], cwd=work, env=env, text=True)
    assert result.returncode == 0, result.stderr
    log = run_bounded(
        ["git", "-C", str(remote), "log", "--format=%s", "main"], text=True, check=True
    ).stdout.split()
    assert log[:2] == ["ours", "theirs"], log


# 워크플로가 `git push` 를 직접 쓰는 파일 전부. 도구 내부 push(PSR `--push` 등)는 범위 밖.
_RELEASE_WORKFLOWS = (
    ".github/workflows/release.yml",
    "github/release.python-semantic-release.workflow.example.yml",
    "github/release.gitversion.workflow.example.yml",
    "github/release.sbt-ci-release.workflow.example.yml",
)
_LOOP_RE = re.compile(r"^ *for attempt in .*?^ *done$", re.M | re.S)
_TAG_RE = re.compile(r'git push\b[^\n]*"(?:v\$\w+|\$\w*TAG)"')
_ENV = {
    "GITHUB_REF_NAME": "main",
    "V": "1.0.0",
    "NEXT": "1.0.0",
    "STABLE": "1.0.0",
    "TAG": "v1.0.0",
    "GIT_TAG": "v1.0.0",
}


def _loops(rel: str) -> list[str]:
    return _LOOP_RE.findall((ROOT / rel).read_text(encoding="utf-8"))


def _release_loops() -> list[tuple[str, str]]:
    return [
        (rel, loop) for rel in _RELEASE_WORKFLOWS for loop in _loops(rel) if _TAG_RE.search(loop)
    ]


def test_every_direct_push_file_is_covered():
    """새 템플릿이 `git push` 를 직접 쓰기 시작하면 이 목록 밖에서 재시도 없이 남음."""
    files = [
        ROOT / ".github" / "workflows" / "release.yml",
        *sorted((ROOT / "github").glob("*.yml")),
    ]
    pushing = {
        p.relative_to(ROOT).as_posix()
        for p in files
        if re.search(r"^(?! *#).*\bgit push\b", p.read_text(encoding="utf-8"), re.M)
    }
    assert pushing == set(_RELEASE_WORKFLOWS)


@pytest.mark.parametrize("rel", _RELEASE_WORKFLOWS)
def test_every_release_push_is_retried_without_rebase(rel):
    """릴리스 커밋·태그 push 의 일시 실패는 브랜치만 릴리스되고 태그가 빠진 상태를 남김. push 마다
    재시도하고, 태그 루프는 rebase 하지 않음 — 버전·노트가 push 전 트리에서 계산됨."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    spans = [m.span() for m in _LOOP_RE.finditer(text)]
    # 줄 머리가 아니라 줄 어디든: `git tag "v$X"; git push …` 는 한가운데에 숨음.
    for m in re.finditer(r"^(?! *#).*?\bgit push\b.*$", text, re.M):
        assert any(a <= m.start() < b for a, b in spans), f"{rel}: 재시도 없음 {m.group(0).strip()}"
    tag_loops = [loop for loop in _loops(rel) if _TAG_RE.search(loop)]
    assert tag_loops, f"{rel}: 재시도하는 태그 push 없음"
    for loop in tag_loops:
        assert "--rebase" not in loop, f"{rel}: 태그 push 루프가 릴리스 커밋을 rebase 함"
        if "HEAD:" in loop:
            assert "--atomic" in loop, f"{rel}: --atomic 없이는 브랜치와 태그가 따로 오를 수 있음"


def _seed(tmp_path: Path, reject_first: bool) -> tuple[Path, Path]:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    _git("init", "-q", "--bare", str(remote))
    _git("clone", "-q", str(remote), str(work))
    _commit(work, "base")
    _git("-C", str(work), "push", "-q", "origin", "HEAD:main")
    _commit(work, "release")
    _git("-C", str(work), "tag", "v1.0.0")
    if reject_first:
        hook = remote / "hooks" / "pre-receive"
        hook.write_text(
            '#!/bin/sh\n[ -f "$GIT_DIR/rejected" ] && exit 0\ntouch "$GIT_DIR/rejected"\nexit 1\n',
            encoding="utf-8",
            newline="\n",
        )
        hook.chmod(0o755)
    return remote, work


def _run_loop(loop: str, work: Path):
    script = loop.replace("sleep ", ": ")
    return run_bounded([BASH, "-ec", script], cwd=work, env={**os.environ, **_ENV}, text=True)


def _remote_refs(remote: Path) -> set[str]:
    out = run_bounded(
        ["git", "-C", str(remote), "for-each-ref", "--format=%(refname)"], text=True, check=True
    ).stdout
    return set(out.split())


@pytest.mark.skipif(not BASH, reason="실제 bash 필요")
@pytest.mark.parametrize(("rel", "loop"), _release_loops())
def test_release_push_survives_one_rejection(rel, loop, tmp_path):
    remote, work = _seed(tmp_path, reject_first=True)
    result = _run_loop(loop, work)
    assert result.returncode == 0, f"{rel}: {result.stderr}"
    assert "refs/tags/v1.0.0" in _remote_refs(remote), rel


@pytest.mark.skipif(not BASH, reason="실제 bash 필요")
@pytest.mark.parametrize(("rel", "loop"), [r for r in _release_loops() if "HEAD:" in r[1]])
def test_release_push_over_a_moved_remote_fails_and_lands_nothing(rel, loop, tmp_path):
    """checkout 뒤 움직인 원격은 일시 장애가 아님 — 릴리스가 그 커밋 없이 계산됨. 루프는 포기하고,
    --atomic 이 브랜치와 함께 태그도 원격에 못 오르게 함."""
    remote, work = _seed(tmp_path, reject_first=False)
    other = tmp_path / "other"
    _git("clone", "-q", str(remote), str(other))
    _commit(other, "theirs")
    _git("-C", str(other), "push", "-q", "origin", "HEAD:main")
    result = _run_loop(loop, work)
    assert result.returncode != 0, rel
    assert "refs/tags/v1.0.0" not in _remote_refs(remote), f"{rel}: 브랜치 없이 태그만 오름"
