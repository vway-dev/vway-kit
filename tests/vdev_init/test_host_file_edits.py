"""/vdev-init 이 만들거나 제자리 편집하는 호스트 파일에 남기는 것 — 호스트가 쓴 deploy.yml 엔
release 배선을 걸지 않고, 복사한 스크립트는 실행 가능하고, 편집한 파일은 줄끝을 지키고, 호스트가
다르게 적은 같은 무시 규칙은 두 번 들어가지 않음."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.vdev_init_setup import (
    ORCHESTRATOR_HEADER,
    _orchestrator_is_ours,
    append_gitignore,
    copy_artifacts,
    remove_claude_md_block,
    remove_gitignore_lines,
    render_deploy_workflows,
    wire_release_deploy,
)
from tests.deploy._helpers import _write_deploy_config, _write_release
from tests.vdev_init._helpers import PLUGIN

DEPLOY = {"enable": True, "targets": [{"name": "p", "target": "pypi", "auth": "oidc"}]}


# ── deploy.yml 이 생성본이 아님 ────────────────────────────────────────────────


def test_turning_deploy_off_unwires_release_beside_a_hand_written_deploy_yml(tmp_path):
    """배선을 지우는 쪽은 아무것도 부르지 않으므로 호스트의 deploy.yml 은 상관이 없음."""
    _write_deploy_config(tmp_path, DEPLOY)
    release = _write_release(tmp_path)
    before = release.read_text(encoding="utf-8")
    render_deploy_workflows(tmp_path, PLUGIN)
    wire_release_deploy(tmp_path)
    assert release.read_text(encoding="utf-8") != before
    (release.parent / "deploy.yml").write_text("name: my own deploy\non: push\n", encoding="utf-8")
    _write_deploy_config(tmp_path, {"enable": False})
    report = wire_release_deploy(tmp_path)
    assert release.read_text(encoding="utf-8") == before
    assert report == ["  [-] release.yml 의 deploy 배선 제거 (deploy 미구성)"]


def test_a_deploy_yml_that_cannot_be_read_is_not_ours(tmp_path, monkeypatch):
    wf = tmp_path / "deploy.yml"
    wf.write_text("anything\n", encoding="utf-8")

    def refuse(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    assert _orchestrator_is_ours(wf) is False


def test_release_is_not_wired_to_a_hand_written_deploy_yml(tmp_path):
    """호출 job 은 재사용 워크플로에 `tag` 를 넘김 — 그 입력이 없는 호스트 파일이면 GitHub 이
    release.yml 을 통째로 거부함."""
    _write_deploy_config(tmp_path, DEPLOY)
    release = _write_release(tmp_path)
    before = release.read_bytes()
    (release.parent / "deploy.yml").write_text("name: my own deploy\non: push\n", encoding="utf-8")
    report = wire_release_deploy(tmp_path)
    assert release.read_bytes() == before
    assert any("release.yml" in line and "[!]" in line for line in report)


def test_a_deploy_yml_that_is_not_utf8_withholds_the_wiring(tmp_path):
    _write_deploy_config(tmp_path, DEPLOY)
    release = _write_release(tmp_path)
    before = release.read_bytes()
    (release.parent / "deploy.yml").write_bytes(b"name: \xff\n")
    report = wire_release_deploy(tmp_path)
    assert release.read_bytes() == before
    assert any("[!]" in line for line in report)


def test_a_generated_deploy_yml_saved_with_a_bom_is_still_wired(tmp_path):
    _write_deploy_config(tmp_path, DEPLOY)
    render_deploy_workflows(tmp_path, PLUGIN)
    release = _write_release(tmp_path)
    deploy = release.parent / "deploy.yml"
    assert deploy.read_text(encoding="utf-8").startswith(ORCHESTRATOR_HEADER)
    deploy.write_bytes(b"\xef\xbb\xbf" + deploy.read_bytes())
    wire_release_deploy(tmp_path)
    assert "uses: ./.github/workflows/deploy.yml" in release.read_text(encoding="utf-8")


# ── 실행 비트 ──────────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 엔 POSIX 모드 비트 없음")
def test_copied_shell_scripts_are_executable(tmp_path):
    copy_artifacts(PLUGIN, tmp_path, ["claude", "codex"])
    shells = sorted((tmp_path / ".claude" / "vway-kit" / "scripts").rglob("*.sh"))
    assert shells, ".sh 를 하나도 복사하지 않음 — 이 테스트가 묻는 것이 없음"
    for sh in shells:
        assert sh.stat().st_mode & stat.S_IXUSR, f"{sh.name} 이 실행 가능하지 않음"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 엔 POSIX 모드 비트 없음")
def test_a_re_sync_restores_a_lost_executable_bit(tmp_path):
    copy_artifacts(PLUGIN, tmp_path)
    runner = tmp_path / ".claude" / "vway-kit" / "scripts" / "precommit-runner.sh"
    os.chmod(runner, 0o644)
    copy_artifacts(PLUGIN, tmp_path)
    assert runner.stat().st_mode & stat.S_IXUSR


# ── 바이트코드 ─────────────────────────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("git") is None, reason="git 필요")
@pytest.mark.parametrize("sub", ["", "harness/", "harness/codex/"])
def test_gitignore_covers_the_bytecode_the_copied_scripts_produce(tmp_path, sub):
    """Codex 렌더러는 평탄 사본보다 한 패키지 아래인 scripts/harness/codex/ 에서 돎."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    append_gitignore(tmp_path)
    pyc = f".claude/vway-kit/scripts/{sub}__pycache__/m.cpython-312.pyc"
    (tmp_path / pyc).parent.mkdir(parents=True)
    (tmp_path / pyc).write_bytes(b"")
    r = subprocess.run(["git", "check-ignore", "-q", pyc], cwd=tmp_path)
    assert r.returncode == 0, f"{pyc} 가 무시되지 않음"


def test_uninstall_removes_the_bytecode_ignore_line(tmp_path):
    append_gitignore(tmp_path)
    remove_gitignore_lines(tmp_path)
    gi = tmp_path / ".gitignore"
    assert "__pycache__" not in (gi.read_text(encoding="utf-8") if gi.exists() else "")


# ── 다르게 적은 같은 무시 규칙 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "existing",
    ["/.claude/vway-kit/.vdev/", ".claude/vway-kit/.vdev", ".claude/vway-kit/.vdev/  "],
)
def test_an_equivalent_evidence_rule_is_not_added_again(tmp_path, existing):
    (tmp_path / ".gitignore").write_text(existing + "\n", encoding="utf-8")
    append_gitignore(tmp_path)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".claude/vway-kit/.vdev/" not in lines


def test_an_anchored_webhook_rule_does_not_stand_for_the_bare_one(tmp_path):
    """`/x` 는 루트 파일만 무시함 — 맨 규칙은 모든 깊이를 잡으려고 있음."""
    (tmp_path / ".gitignore").write_text("/.teams-webhooks.local.json\n", encoding="utf-8")
    append_gitignore(tmp_path)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".teams-webhooks.local.json" in lines


def test_a_directory_only_rule_does_not_stand_for_a_file_rule(tmp_path):
    (tmp_path / ".gitignore").write_text(".teams-webhooks.local.json/\n", encoding="utf-8")
    append_gitignore(tmp_path)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".teams-webhooks.local.json" in lines


def test_a_negated_rule_does_not_count_as_present(tmp_path):
    (tmp_path / ".gitignore").write_text("!.claude/vway-kit/.vdev/\n", encoding="utf-8")
    append_gitignore(tmp_path)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".claude/vway-kit/.vdev/" in lines


# ── 줄끝 ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("eol", ["\r\n", "\n"])
def test_append_gitignore_keeps_the_files_line_endings(tmp_path, eol):
    gi = tmp_path / ".gitignore"
    gi.write_bytes(f"node_modules/{eol}dist/{eol}".encode())
    append_gitignore(tmp_path)
    raw = gi.read_bytes().decode()
    assert raw.startswith(f"node_modules/{eol}dist/{eol}")
    assert raw.count(eol) == len(raw.splitlines())
    if eol == "\n":
        assert "\r" not in raw


@pytest.mark.parametrize("eol", ["\r\n", "\n"])
def test_remove_gitignore_lines_keeps_the_files_line_endings(tmp_path, eol):
    gi = tmp_path / ".gitignore"
    gi.write_bytes(f"node_modules/{eol}.claude/vway-kit/.vdev/{eol}dist/{eol}".encode())
    remove_gitignore_lines(tmp_path)
    assert gi.read_bytes().decode() == f"node_modules/{eol}dist/{eol}"


@pytest.mark.parametrize("eol", ["\r\n", "\n"])
def test_remove_claude_md_block_keeps_the_files_line_endings(tmp_path, eol):
    cm = tmp_path / "CLAUDE.md"
    body = ["# Host", "<!-- vway-kit:teams BEGIN -->", "x", "<!-- vway-kit:teams END -->"]
    cm.write_bytes((eol.join([*body, "tail"]) + eol).encode())
    remove_claude_md_block(tmp_path)
    assert cm.read_bytes().decode() == f"# Host{eol}tail{eol}"


@pytest.mark.parametrize("eol", ["\r\n", "\n"])
def test_release_deploy_wiring_keeps_the_files_line_endings(tmp_path, eol):
    _write_deploy_config(tmp_path, DEPLOY)
    release = _write_release(tmp_path)
    release.write_bytes(release.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", eol.encode()))
    wire_release_deploy(tmp_path)
    raw = release.read_bytes().decode()
    assert "uses: ./.github/workflows/deploy.yml" in raw
    assert raw.count(eol) == len(raw.splitlines())
    if eol == "\n":
        assert "\r" not in raw
