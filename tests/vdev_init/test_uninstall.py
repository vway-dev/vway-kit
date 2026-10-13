"""uninstall 이 남기는 것 — 남은 워크플로 보고 · 비밀 보호 라인 · 비워진 settings.json.

- 워크플로 보고는 고정 목록이 아니라 호스트 `.github/workflows/` 를 읽어 셋으로 가름:
  가드 없이 삭제된 스크립트를 불러 실패 · 가드가 exit 0 해 아무것도 검증 못 함 · 계속 돎.
- `.gitignore` 의 bare 비밀 패턴은 VWAY_DIR 밖도 막을 수 있어 남김.
- 제거가 비운 settings.json 은 지우되, 링크·읽기 전용 파일은 지우지 않음.
- 커밋 안내는 이 실행이 실제로 바꾼 파일·디렉터리만 이름 댐.
"""

import json
from pathlib import Path

import pytest

from scripts.vdev_init_setup import (
    CLAUDE_MD_BEGIN,
    CLAUDE_MD_END,
    GITIGNORE_KEEP,
    append_gitignore,
    register_gate,
    register_marketplace,
    remove_gitignore_lines,
    run_uninstall,
    unregister_gate,
    unregister_marketplace,
)
from tests.vdev_init._helpers import PLUGIN

# 릴리스 렌더별 기대 — release_version.py 블록은 부재에 exit 1, semantic-release 는 가드된
# CHANGELOG 노트 블록만 가져 스크립트 없이도 돎.
RELEASE_FAILS = {
    "cargo-release": True,
    "gitversion": True,
    "jreleaser": True,
    "python-semantic-release": True,
    "sbt-ci-release": True,
    "semantic-release": False,
}


def _workflow(host: Path, name: str, body: str) -> None:
    wf = host / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / name).write_text(body, encoding="utf-8")


def test_the_release_table_covers_every_release_template():
    shipped = {
        p.name[len("release.") : -len(".workflow.example.yml")]
        for p in (PLUGIN / "github").glob("release.*.workflow.example.yml")
    }
    assert shipped == set(RELEASE_FAILS)


@pytest.mark.parametrize("tool", sorted(RELEASE_FAILS))
def test_uninstall_tells_whether_a_release_workflow_breaks(tmp_path: Path, capsys, tool):
    """어느 도구가 렌더했든 release.yml 이 안내에 나오고, 실패 여부는 그 본문이 정함."""
    template = (PLUGIN / "github" / f"release.{tool}.workflow.example.yml").read_text(
        encoding="utf-8"
    )
    _workflow(tmp_path, "release.yml", template)
    run_uninstall(tmp_path)
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "release.yml" in ln)
    assert ("실패" in line) is RELEASE_FAILS[tool], out
    if not RELEASE_FAILS[tool]:
        assert "계속 돕니다" in line, out


def test_uninstall_names_the_unguarded_wiki_verify_as_failing(tmp_path: Path, capsys):
    """wiki-verify 템플릿은 스크립트 존재를 묻지 않고 바로 부름 — 남기면 push 마다 CI 가 빨개짐."""
    template = (PLUGIN / "github" / "wiki-verify.workflow.example.yml").read_text(encoding="utf-8")
    _workflow(tmp_path, "wiki-verify.yml", template)
    run_uninstall(tmp_path)
    line = next(ln for ln in capsys.readouterr().out.splitlines() if "wiki-verify.yml" in ln)
    assert "실패" in line, line


@pytest.mark.parametrize("name", ["doc-style", "srs-verify"])
def test_uninstall_names_a_guarded_render_as_verifying_nothing(tmp_path: Path, capsys, name):
    template = (PLUGIN / "github" / f"{name}.workflow.example.yml").read_text(encoding="utf-8")
    _workflow(tmp_path, f"{name}.yml", template)
    run_uninstall(tmp_path)
    line = next(ln for ln in capsys.readouterr().out.splitlines() if f"{name}.yml" in ln)
    assert "exit 0" in line and "실패" not in line, line


def test_uninstall_tells_a_guarded_check_from_a_failing_one(tmp_path: Path, capsys):
    _workflow(tmp_path, "doc-style.yml", "run: python3 .claude/vway-kit/scripts/x.py\n")
    _workflow(tmp_path, "release.yml", "run: python3 .claude/vway-kit/scripts/y.py\n")
    run_uninstall(tmp_path)
    lines = capsys.readouterr().out.splitlines()
    guarded = next(ln for ln in lines if "doc-style.yml" in ln)
    assert "release.yml" not in guarded and "exit 0" in guarded, lines


def test_uninstall_names_the_rendered_workflows_that_keep_running(tmp_path: Path, capsys):
    """자기완결 렌더는 이 실행이 지우는 것을 부르지 않아 push 마다 러너를 씀 — 호스트 자신의
    워크플로는 이 실행의 몫이 아님."""
    names = (
        "branch-naming.yml",
        "entropy-check.yml",
        "unit-test.yml",
        "api-contract.yml",
        "e2e.yml",
        "deploy.yml",
        "deploy-pypi.yml",
    )
    for name in names:
        _workflow(tmp_path, name, "on: push\n")
    _workflow(tmp_path, "ci.yml", "on: push\n")
    run_uninstall(tmp_path)
    out = capsys.readouterr().out
    keeps = next(ln for ln in out.splitlines() if "branch-naming.yml" in ln)
    for name in names:
        assert name in keeps, out
    assert "ci.yml" not in out


@pytest.mark.parametrize("name", ["deploy.yml", "deploy-pypi.yml"])
def test_uninstall_tells_how_to_drop_the_deploy_wiring(tmp_path: Path, capsys, name):
    """deploy 파일만 지우면 release.yml 의 호출 job 이 없는 파일을 불러 릴리스가 깨짐."""
    _workflow(tmp_path, name, "on: push\n")
    run_uninstall(tmp_path)
    out = capsys.readouterr().out
    assert "deploy 호출 job" in out and "deploy.enable" in out, out


def test_uninstall_skips_the_deploy_note_without_a_deploy_workflow(tmp_path: Path, capsys):
    _workflow(tmp_path, "e2e.yml", "on: push\n")
    run_uninstall(tmp_path)
    assert "deploy.enable" not in capsys.readouterr().out


def test_uninstall_names_a_hosts_own_workflow_that_calls_the_deleted_scripts(
    tmp_path: Path, capsys
):
    _workflow(tmp_path, "ci.yml", "run: python3 .claude/vway-kit/scripts/y.py\n")
    run_uninstall(tmp_path)
    line = next(ln for ln in capsys.readouterr().out.splitlines() if "ci.yml" in ln)
    assert "실패" in line, line


def test_uninstall_still_reaches_its_verdict_when_the_workflow_listing_raises(
    tmp_path: Path, capsys, monkeypatch
):
    import scripts.vdev_init_setup as vis

    def boom(_host):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(vis, "report_workflows", boom)
    assert vis.run_uninstall(tmp_path) is True
    out = capsys.readouterr().out
    assert "워크플로를 직접 확인" in out and "정리 완료." in out


def test_uninstall_reads_an_uppercase_workflow_extension(tmp_path: Path, capsys):
    _workflow(tmp_path, "release.YML", "run: python3 .claude/vway-kit/scripts/y.py\n")
    run_uninstall(tmp_path)
    lines = capsys.readouterr().out.splitlines()
    assert "실패" in next(ln for ln in lines if "release.YML" in ln), lines


def _commit_reminder(out: str) -> str:
    return next((ln for ln in out.splitlines() if "커밋해야 반영" in ln), "")


def test_the_commit_reminder_names_settings_only_when_uninstall_changed_it(tmp_path, capsys):
    run_uninstall(tmp_path)
    assert "settings.json" not in _commit_reminder(capsys.readouterr().out)
    register_gate(tmp_path)
    run_uninstall(tmp_path)
    assert "settings.json" in _commit_reminder(capsys.readouterr().out)


def test_the_commit_reminder_names_every_host_file_uninstall_changed(tmp_path, capsys):
    append_gitignore(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        f"# Host\n{CLAUDE_MD_BEGIN} -->\nbody\n{CLAUDE_MD_END} -->\n", encoding="utf-8"
    )
    (tmp_path / ".claude" / "vway-kit").mkdir(parents=True)
    run_uninstall(tmp_path)
    reminder = _commit_reminder(capsys.readouterr().out)
    for name in (".gitignore", "CLAUDE.md", ".claude/vway-kit/"):
        assert name in reminder, reminder
    assert "AGENTS.md" not in reminder


def test_an_uninstall_that_changed_nothing_asks_for_no_commit(tmp_path, capsys):
    run_uninstall(tmp_path)
    assert _commit_reminder(capsys.readouterr().out) == ""


def test_the_commit_reminder_skips_a_settings_file_uninstall_left_alone(tmp_path, capsys):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"model": "opus"}\n', encoding="utf-8")
    run_uninstall(tmp_path)
    assert "settings.json" not in _commit_reminder(capsys.readouterr().out)


def test_uninstall_names_no_workflow_when_the_host_has_none(tmp_path: Path, capsys):
    run_uninstall(tmp_path)
    assert ".yml" not in capsys.readouterr().out


def test_uninstall_keeps_the_ignore_lines_that_guard_secrets(tmp_path: Path):
    """bare 비밀 패턴은 어느 깊이든 매칭해 삭제 대상 밖의 비밀도 막을 수 있고, 호스트가
    /vdev-init 전부터 가졌을 수 있음."""
    (tmp_path / ".gitignore").write_text(".teams-webhooks.local.json\nnode_modules/\n")
    append_gitignore(tmp_path)
    report = remove_gitignore_lines(tmp_path)
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert gi[:2] == [".teams-webhooks.local.json", "node_modules/"], gi
    assert set(gi) == GITIGNORE_KEEP | {"node_modules/"}, gi
    for line in GITIGNORE_KEEP:
        assert line in report, report


def test_an_emptied_settings_file_that_cannot_be_deleted_is_reported(tmp_path: Path, monkeypatch):
    register_gate(tmp_path)

    def refuse(self, *_args, **_kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", refuse)
    assert unregister_gate(tmp_path).startswith("  [!] settings.json 삭제 실패")


def test_uninstall_deletes_the_settings_file_it_emptied(tmp_path: Path):
    register_gate(tmp_path)
    register_marketplace(tmp_path)
    unregister_gate(tmp_path)
    assert "삭제" in unregister_marketplace(tmp_path)
    assert not (tmp_path / ".claude" / "settings.json").exists()


def test_uninstall_leaves_only_the_hosts_own_settings(tmp_path: Path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    register_gate(tmp_path)
    register_marketplace(tmp_path)
    unregister_gate(tmp_path)
    unregister_marketplace(tmp_path)
    assert json.loads(settings.read_text(encoding="utf-8")) == {"model": "opus"}
