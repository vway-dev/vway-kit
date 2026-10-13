"""릴리스 템플릿의 버전 스텝 배선 — 공통 머리의 동일성과 실제 셸 동작.

버전 규칙은 `scripts/release_version.py`(`test_release_version.py`)가 쥐고, 템플릿은 그 답을
받아 finalize·출력으로 나눔. 그 갈래가 셸 안에 있어 텍스트 단언으로는 `set -e`·
`git describe` 결함이 안 보이므로, 스텝을 YAML 에서 뽑아 git 픽스처(태그 목록 + HEAD 커밋
메시지 + 스크립트 호스트 사본)에서 실제 bash 로 돌려 잼. PSR 템플릿은 auto 갈래가
semantic-release 호출이라 머리 동일성만 봄. 같은 도구인 이 저장소 자신의 `release.yml` 은
결정적 갈래(강제 레벨·finalize·가드)만 bare origin 픽스처에서 돌림.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from tests._proc import run_bounded
from tests.gate_check._helpers import _REPO_BASH, _git_ok

PLUGIN = Path(__file__).resolve().parent.parent

_START = "# >>> vway-release-version"
_END = "# <<< vway-release-version"
# 템플릿 → 버전을 싣는 출력 키.
_STEP_TEMPLATES = {
    "release.gitversion.workflow.example.yml": "version",
    "release.cargo-release.workflow.example.yml": "version",
    "release.jreleaser.workflow.example.yml": "version",
    "release.sbt-ci-release.workflow.example.yml": "tag",
}
_TEMPLATES = (*_STEP_TEMPLATES, "release.python-semantic-release.workflow.example.yml")

requires_bash_git = pytest.mark.skipif(
    not (_REPO_BASH and _git_ok()), reason="저장소를 볼 수 있는 bash + git 필요"
)


def _runs(name: str):
    doc = yaml.safe_load((PLUGIN / "github" / name).read_text(encoding="utf-8"))
    for job in (doc.get("jobs") or {}).values():
        yield from job.get("steps") or []


def _prologue(name: str) -> str | None:
    for step in _runs(name):
        lines = (step.get("run") or "").splitlines()
        starts = [n for n, line in enumerate(lines) if line.strip().startswith(_START)]
        if starts:
            i = starts[0]
            j = next(n for n, line in enumerate(lines) if line.strip() == _END)
            indent = len(lines[i]) - len(lines[i].lstrip())
            return "\n".join(line[indent:] for line in lines[i : j + 1])
    return None


def test_every_forcing_template_asks_the_script_the_same_way():
    blocks = {name: _prologue(name) for name in _TEMPLATES}
    missing = [name for name, b in blocks.items() if b is None]
    assert not missing, f"vway-release-version 머리가 없음: {missing}"
    assert len(set(blocks.values())) == 1, (
        "다섯 템플릿의 vway-release-version 머리가 서로 다름 — 한 곳을 고쳤다면 나머지 넷에 "
        "같은 글자로 옮겨라."
    )


def test_semantic_release_never_creates_the_github_release():
    """뒤 스텝의 `gh release create` 는 `semantic-release version` 이 그 태그로 이미 만든
    Release 에서 실패함. 템플릿은 매니페스트를 이름으로 스테이징 — `git add -A` 는 빌드가 트리에
    남긴 것까지 릴리스 커밋에 쓸어 담음."""
    tmpl = (PLUGIN / "github" / "release.python-semantic-release.workflow.example.yml").read_text(
        encoding="utf-8"
    )
    own = (PLUGIN / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for text in (own, tmpl):
        calls = [ln for ln in text.splitlines() if "semantic-release version" in ln]
        assert calls and all("--no-vcs-release" in ln for ln in calls), calls
    assert "git add -A" not in tmpl


def _step(name: str, ref: str) -> str:
    for step in _runs(name):
        if step.get("id") == "ver":
            return (
                step["run"]
                .replace("${{ github.ref_name }}", ref)
                .replace("__VWAY_PRERELEASE__", "stage")
                # Windows 의 `python3` 은 스토어 별칭일 수 있음 — 이 인터프리터로 고정.
                .replace('python3 "$RV"', f'"{Path(sys.executable).as_posix()}" "$RV"')
            )
    raise AssertionError(f"{name}: id=ver 스텝 없음")


def _git(repo: Path, env: dict, *args: str) -> None:
    run_bounded(["git", *args], cwd=str(repo), env=env, check=True)


def _run_step(
    tmp_path: Path,
    name: str,
    ref: str,
    tags: list[str],
    message: str,
    *,
    copy: bool = True,
    unreachable: tuple[str, ...] = (),
    tag_head: str = "",
):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    _git(repo, env, "init", "-q")
    # 태그마다 커밋 하나 — 목록 순서가 곧 이력 순서(`git describe` 는 마지막 것을 집음).
    for tag in tags:
        _git(repo, env, "commit", "-q", "--allow-empty", "-m", tag)
        _git(repo, env, "tag", tag)
    # 승격되지 않은 staging 에만 있는 태그 — HEAD 에서 도달 불가.
    if unreachable:
        _git(repo, env, "switch", "-q", "-c", "side")
        for tag in unreachable:
            _git(repo, env, "commit", "-q", "--allow-empty", "-m", tag)
            _git(repo, env, "tag", tag)
        _git(repo, env, "switch", "-q", "-")
    _git(repo, env, "commit", "-q", "--allow-empty", "-m", message)
    if tag_head:
        _git(repo, env, "tag", tag_head)
    if copy:
        scripts = repo / ".claude" / "vway-kit" / "scripts"
        scripts.mkdir(parents=True)
        for rel in ("release_version.py", "_vway_paths.py"):
            shutil.copy(PLUGIN / "scripts" / rel, scripts / rel)
    outputs = tmp_path / "gh_output"
    outputs.write_text("", encoding="utf-8")
    script = tmp_path / "step.sh"
    script.write_text(_step(name, ref), encoding="utf-8", newline="\n")
    env["GITHUB_OUTPUT"] = outputs.as_posix()
    r = run_bounded([_REPO_BASH, script.as_posix()], cwd=str(repo), env=env, text=True, timeout=30)
    pairs = dict(
        line.split("=", 1) for line in outputs.read_text(encoding="utf-8").splitlines() if line
    )
    return r.returncode, pairs, r.stdout + r.stderr


def _expected(name: str, version: str) -> dict:
    """템플릿별 출력 계약 — sbt 는 `tag=v…`, cargo 는 rc·직접 릴리스가 `action=bump`."""
    key = _STEP_TEMPLATES[name]
    action = "bump" if "cargo" in name else "release"
    return {key: f"v{version}" if key == "tag" else version, "action": action}


_PENDING = ["v1.0.4", "v1.1.0-rc.1", "v1.1.0-rc.2"]
_MSG_CONTINUE = "Merge dev: x\n\nRelease-Level: continue\n"


@requires_bash_git
@pytest.mark.parametrize("name", sorted(_STEP_TEMPLATES))
@pytest.mark.parametrize(
    ("ref", "tags", "message", "version"),
    [
        ("stage", _PENDING, "Merge dev: x\n\nRelease-Level: continue\n", "1.1.0-rc.3"),
        # 트레일러 없음: 대기 rc 가 있으면 continue, 없으면 patch(`--auto-level patch`).
        ("stage", _PENDING, "Merge dev: x\n\nplain body\n", "1.1.0-rc.3"),
        ("stage", ["v1.0.4"], "Merge dev: x\n\nplain body\n", "1.0.5-rc.1"),
        ("main", ["v1.0.4"], "fix: hotfix\n", "1.0.5"),
        ("main", ["v1.0.4"], "fix: hotfix\n\nRelease-Level: minor\n", "1.1.0"),
    ],
)
def test_version_step(tmp_path: Path, name, ref, tags, message, version):
    rc, pairs, out = _run_step(tmp_path, name, ref, tags, message)
    assert rc == 0, out
    assert pairs == _expected(name, version), out


@requires_bash_git
@pytest.mark.parametrize("name", sorted(_STEP_TEMPLATES))
def test_stable_finalizes_a_reachable_rc_and_ignores_the_trailer(tmp_path: Path, name):
    """production 에 머지된 rc 는 트레일러와 무관하게 접미사만 뗌 — 레벨은 staging 에서
    한 번 정함."""
    rc, pairs, out = _run_step(
        tmp_path, name, "main", _PENDING, "Merge stage: x\n\nRelease-Level: major\n"
    )
    assert rc == 0, out
    if "cargo" in name:
        assert pairs == {"action": "finalize"}, out
    else:
        assert pairs == _expected(name, "1.1.0"), out


@requires_bash_git
@pytest.mark.parametrize("name", sorted(_STEP_TEMPLATES))
def test_stable_finalizes_the_pending_rc_a_hotfix_shipped_past(tmp_path: Path, name):
    """hotfix 가 `v1.0.5` 를 먼저 냈어도 머지된 rc 는 그 rc 로 정식화됨.

    `git describe` 로 갈래를 정하면 그 hotfix 태그가 가장 가까워 stable 직행으로 떨어지고,
    고른 minor 가 patch 로 나감 — 이력 순서(rc 먼저, hotfix 나중)가 그 결함을 재현함."""
    rc, pairs, out = _run_step(
        tmp_path, name, "main", ["v1.0.4", "v1.1.0-rc.1", "v1.0.5"], "Merge stage: x\n"
    )
    assert rc == 0, out
    if "cargo" in name:
        assert pairs == {"action": "finalize"}, out
    else:
        assert pairs == _expected(name, "1.1.0"), out


@requires_bash_git
@pytest.mark.parametrize("name", sorted(_STEP_TEMPLATES))
def test_stable_releases_directly_when_the_pending_rc_is_not_merged(tmp_path: Path, name):
    """hotfix push — rc 는 staging 에만 있음. 도달하지 않는 rc 를 정식화하면 production 에
    없는 코드의 버전이 나감."""
    rc, pairs, out = _run_step(
        tmp_path, name, "main", ["v1.0.4"], "fix: x\n", unreachable=("v1.1.0-rc.1",)
    )
    assert rc == 0, out
    assert pairs == _expected(name, "1.0.5"), out


@requires_bash_git
@pytest.mark.parametrize("name", sorted(_STEP_TEMPLATES))
@pytest.mark.parametrize(
    ("ref", "message", "copy"),
    [
        ("stage", "Merge dev: x\n\nRelease-Level: pach\n", True),
        ("main", "fix: x\n\nRelease-Level: continue\n", True),
        ("stage", "Merge dev: x\n\nRelease-Level: patch\n", False),
    ],
)
def test_unusable_input_fails_the_step(tmp_path: Path, name, ref, message, copy):
    """어휘 밖 레벨·stable 의 continue·호스트 사본 부재는 실패로 드러나야 함 — 조용히 넘어가면
    승격이 끝난 것처럼 보이고 rc 는 없음."""
    rc, pairs, out = _run_step(tmp_path, name, ref, ["v1.0.4"], message, copy=copy)
    assert rc != 0, out
    assert "action" not in pairs, out


@requires_bash_git
@pytest.mark.parametrize("name", sorted(_STEP_TEMPLATES))
@pytest.mark.parametrize(
    ("ref", "message", "tag_head"),
    [
        # cargo-release 의 bump 커밋 — `[skip ci]` 없이 push 되어 워크플로를 다시 띄움.
        ("stage", "chore: Release 1.0.5-rc.1\n", "v1.0.5-rc.1"),
        # End state 의 production → staging 백머지 push — 태그가 승격 머지 커밋에 얹혀 있음.
        ("stage", "Merge stage: x\n", "v1.1.0"),
        # 같은 재진입이 production 쪽에서 — 이미 정식화한 커밋을 또 릴리스하면 안 됨.
        ("main", "Merge stage: x\n", "v1.1.0"),
    ],
)
def test_a_tagged_head_cuts_nothing(tmp_path: Path, name, ref, message, tag_head):
    """태그가 얹힌 커밋은 이미 릴리스된 커밋 — 여기서 또 rc 를 내면 아무도 고르지 않은 시리즈가
    staging 에 생기고, 다음 승격이 그 유령 base 위에서 계속됨."""
    rc, pairs, out = _run_step(tmp_path, name, ref, ["v1.0.4"], message, tag_head=tag_head)
    assert rc == 0, out
    assert pairs == {"action": "skip"}, out


def _run_own(tmp_path: Path, ref: str, tags: list[str], version: str, message: str):
    """이 저장소 `release.yml` 의 `sr` 스텝 — pyproject·plugin.json 을 올리고 bare origin 에
    push."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    origin, repo = tmp_path / "origin", tmp_path / "repo"
    run_bounded(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
    repo.mkdir()
    _git(repo, env, "init", "-q")
    _git(repo, env, "remote", "add", "origin", str(origin))
    (repo / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "plugin.json").write_text(
        f'{{\n  "version": "{version}"\n}}\n', encoding="utf-8"
    )
    (repo / "scripts").mkdir()
    for rel in ("release_version.py", "_vway_paths.py"):
        shutil.copy(PLUGIN / "scripts" / rel, repo / "scripts" / rel)
    _git(repo, env, "add", "-A")
    for tag in tags:
        _git(repo, env, "commit", "-q", "--allow-empty", "-m", tag)
        _git(repo, env, "tag", tag)
    _git(repo, env, "commit", "-q", "--allow-empty", "-m", message)
    _git(repo, env, "push", "-q", "--tags", "origin", f"HEAD:{ref}")
    doc = yaml.safe_load((PLUGIN / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    run = next(s for s in doc["jobs"]["release"]["steps"] if s.get("id") == "sr")["run"]
    py = Path(sys.executable).as_posix()
    run = (
        run.replace("${{ github.ref_name }}", ref)
        .replace('python3 "$RV"', f'"{py}" "$RV"')
        .replace("python -c", f'"{py}" -c')
    )
    script, outputs = tmp_path / "step.sh", tmp_path / "gh_output"
    script.write_text(run, encoding="utf-8", newline="\n")
    outputs.write_text("", encoding="utf-8")
    env.update(GITHUB_OUTPUT=outputs.as_posix(), GITHUB_REF_NAME=ref)
    r = run_bounded([_REPO_BASH, script.as_posix()], cwd=str(repo), env=env, text=True, timeout=60)
    pushed = run_bounded(["git", "tag", "--list"], cwd=str(origin), text=True).stdout.split()
    plugin = (repo / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    return r.returncode, outputs.read_text(encoding="utf-8"), pushed, plugin, r.stdout + r.stderr


@requires_bash_git
@pytest.mark.parametrize(
    ("ref", "tags", "version", "message", "tag"),
    [
        ("stage", _PENDING, "1.1.0-rc.2", _MSG_CONTINUE, "v1.1.0-rc.3"),
        ("main", _PENDING, "1.1.0-rc.2", "Merge stage: x\n", "v1.1.0"),
        ("main", ["v1.0.4"], "1.0.4", "fix: x\n\nRelease-Level: minor\n", "v1.1.0"),
    ],
)
def test_own_release_applies_a_computed_version(tmp_path: Path, ref, tags, version, message, tag):
    """plugin.json 이 재설치 게이팅 SSOT — 태그만 오르고 그 파일이 남으면 소비자에 안 닿음."""
    rc, _, pushed, plugin, out = _run_own(tmp_path, ref, tags, version, message)
    assert rc == 0, out
    assert tag in pushed, out
    assert f'"version": "{tag[1:]}"' in plugin, out


@requires_bash_git
def test_own_release_refuses_an_rc_a_hotfix_overtook(tmp_path: Path):
    rc, outputs, pushed, _, out = _run_own(
        tmp_path, "main", ["v1.0.4", "v1.0.5", "v1.0.5-rc.1"], "1.0.5-rc.1", "Merge stage: x\n"
    )
    assert rc != 0, out
    assert "이미 있음" in out, out
    assert "released=true" not in outputs, out
