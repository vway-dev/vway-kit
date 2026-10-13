"""저장소는 /vdev-init 에게 믿을 수 없는 입력 — 설치자가 쓰는 자리에 커밋된 링크가 그
쓰기를 호스트 밖으로 실어 나르면 안 됨.

재는 것: 플러그인 소유 쓰기가 자기 경로에 선 링크는 **교체**하고, 호스트 밖으로 풀리는
디렉터리 링크 앞에서는 **거절**하며 그 사실을 `[!]` 로 남기는가. 호스트 소유 파일의
제자리 편집(settings.json·hooks.json·.gitignore·CLAUDE.md·release.yml)은 호스트 밖으로 풀리는
링크를 거부하는가."""

import json
import os
from pathlib import Path

import pytest
import yaml

from scripts.harness.codex import install as codex_install
from scripts.vdev_init_setup import (
    GATE_ENTRY,
    RULES_DEST,
    TIERS_FILENAME,
    VERSION_MARKER_PATH,
    _render_one,
    append_gitignore,
    apply_migrations,
    check_precommit,
    copy_artifacts,
    migrate_legacy_paths,
    register_gate,
    register_marketplace,
    remove_claude_md_block,
    remove_gitignore_lines,
    remove_rules,
    render_deploy_workflows,
    render_unit_test_workflow,
    render_workflow,
    run_setup,
    seed_host_templates,
    unregister_gate,
    wire_release_deploy,
)
from tests.deploy._helpers import _RELEASE_OK, _write_deploy_config
from tests.vdev_init._helpers import PLUGIN, _mk_host_config
from tests.vdev_init._template_helpers import _junction

VICTIM_TEXT = "victim\n"


def _link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):
        pytest.skip("이 호스트에서 심볼릭 링크를 만들 수 없음")


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    host, outside = tmp_path / "host", tmp_path / "outside"
    host.mkdir()
    outside.mkdir()
    return host, outside


def _victim(outside: Path) -> Path:
    victim = outside / "victim"
    victim.write_text(VICTIM_TEXT, encoding="utf-8")
    return victim


def test_rule_cleanup_unlinks_a_rules_dir_linked_outside(tmp_path):
    host, outside = _layout(tmp_path)
    victim = _victim(outside)
    _link(host / RULES_DEST, outside)
    remove_rules(host)
    assert victim.read_text(encoding="utf-8") == VICTIM_TEXT
    assert not (host / RULES_DEST).exists()
    assert not (host / RULES_DEST).is_symlink()


def test_rule_cleanup_unlinks_a_rules_dir_junctioned_outside(tmp_path):
    """정션은 `is_symlink()` 를 통과함 — 그 자리에서 rmtree 가 돌면 너머의 남의 파일이 지워짐."""
    host, outside = _layout(tmp_path)
    victim = _victim(outside)
    (host / RULES_DEST).parent.mkdir(parents=True)
    _junction(host / RULES_DEST, outside)
    remove_rules(host)
    assert victim.read_text(encoding="utf-8") == VICTIM_TEXT
    assert not (host / RULES_DEST).exists()


def test_rule_cleanup_refuses_a_rules_parent_linked_outside(tmp_path):
    """셋업이 재동기화마다 이것을 돌리므로, 커밋된 `.claude/rules` 링크가 그 너머에 선 `vway-kit`
    디렉터리의 rmtree 로 바뀌면 안 됨."""
    host, outside = _layout(tmp_path)
    victim = outside / "vway-kit" / "victim"
    victim.parent.mkdir()
    victim.write_text(VICTIM_TEXT, encoding="utf-8")
    _link(host / ".claude" / "rules", outside)
    report = remove_rules(host)
    assert victim.read_text(encoding="utf-8") == VICTIM_TEXT
    assert "[!]" in report


def test_copy_artifacts_replaces_symlinked_script_and_policy(tmp_path):
    host, outside = _layout(tmp_path)
    victim = _victim(outside)
    script = host / ".claude/vway-kit/scripts/_vway_paths.py"
    policy = host / ".claude/vway-kit/config/vdev-tiers.yaml"
    _link(script, victim)
    _link(policy, victim)
    copy_artifacts(PLUGIN, host)
    assert victim.read_text(encoding="utf-8") == VICTIM_TEXT
    assert not script.is_symlink() and not policy.is_symlink()
    assert policy.read_bytes() == (PLUGIN / "vdev-tiers.yaml").read_bytes()


def test_copy_artifacts_refuses_a_scripts_dir_linked_outside(tmp_path):
    host, outside = _layout(tmp_path)
    _link(host / ".claude/vway-kit/scripts", outside)
    copy_artifacts(PLUGIN, host)
    assert list(outside.iterdir()) == []


def test_copy_artifacts_refuses_a_scripts_dir_junctioned_outside(tmp_path):
    """정션은 `is_symlink()` 가 False — 관리자 권한 없이 만들어져 Windows 에서 더 흔한 꼴."""
    host, outside = _layout(tmp_path)
    (host / ".claude/vway-kit").mkdir(parents=True)
    _junction(host / ".claude/vway-kit/scripts", outside)
    copy_artifacts(PLUGIN, host)
    assert list(outside.iterdir()) == []


def test_copy_artifacts_makes_no_directory_outside(tmp_path):
    host, outside = _layout(tmp_path)
    _link(host / ".claude/vway-kit", outside)
    report = copy_artifacts(PLUGIN, host)
    assert list(outside.iterdir()) == []
    assert any("[!]" in ln for ln in report)


def test_setup_makes_no_directory_outside(tmp_path):
    """단계 하나가 거절해도 뒤 단계가 같은 자리에 쓰면 소용없음 — 셋업 전체로 잼."""
    host, outside = _layout(tmp_path)
    _link(host / ".claude/vway-kit", outside)
    run_setup(host, PLUGIN)
    assert list(outside.iterdir()) == []


def test_legacy_migration_deletes_nothing_behind_a_linked_vway_dir(tmp_path):
    host, outside = _layout(tmp_path)
    keep = outside / TIERS_FILENAME
    keep.write_text(VICTIM_TEXT, encoding="utf-8")
    _link(host / ".claude/vway-kit", outside)
    report = migrate_legacy_paths(host)
    assert keep.read_text(encoding="utf-8") == VICTIM_TEXT
    assert any("[!]" in ln for ln in report)


@pytest.mark.parametrize("name", ["flow_gate_check.py", TIERS_FILENAME])
def test_legacy_cleanup_deletes_nothing_behind_a_linked_scripts_dir(tmp_path, name):
    """`.claude/vway-kit` 은 실제 디렉터리이고 그 아래 `scripts/` 만 밖을 가리키는 꼴."""
    host, outside = _layout(tmp_path)
    keep = outside / name
    keep.write_text(VICTIM_TEXT, encoding="utf-8")
    _link(host / ".claude/vway-kit/scripts", outside)
    report = migrate_legacy_paths(host)
    assert keep.read_text(encoding="utf-8") == VICTIM_TEXT
    assert any("[!]" in ln for ln in report)


def test_legacy_move_sends_nothing_behind_a_linked_config_dir(tmp_path):
    host, outside = _layout(tmp_path)
    legacy = host / "teams-webhooks.json"
    legacy.write_text("{}\n", encoding="utf-8")
    _link(host / ".claude/vway-kit/config", outside)
    report = migrate_legacy_paths(host)
    assert legacy.is_file()
    assert list(outside.iterdir()) == []
    assert any("[!]" in ln for ln in report)


def test_legacy_move_never_lands_through_a_dangling_link(tmp_path):
    """끊긴 링크는 `exists()` 가 False — 그 자리로 옮기면 `shutil.move` 가 링크를 따라 씀."""
    host, outside = _layout(tmp_path)
    legacy = host / "teams-webhooks.json"
    legacy.write_text("{}\n", encoding="utf-8")
    target = outside / "created.json"
    _link(host / ".claude/vway-kit/config/teams-webhooks.json", target)
    migrate_legacy_paths(host)
    assert not target.exists()
    assert legacy.is_file()


def test_legacy_cleanup_still_runs_past_a_dangling_config_link(tmp_path):
    """`config/` 하나가 막혀도 나머지 정리는 계속 — 단계 전체가 멈추면 안 됨."""
    host, outside = _layout(tmp_path)
    _link(host / ".claude/vway-kit/config", outside / "missing")
    orphan = host / ".claude/vway-kit/scripts/flow_gate_check.py"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("x\n", encoding="utf-8")
    migrate_legacy_paths(host)
    assert not orphan.exists()
    assert not (outside / "missing").exists()


def test_tier_marker_translation_writes_nothing_behind_a_linked_vdev_dir(tmp_path):
    host, outside = _layout(tmp_path)
    (outside / "tier").write_text("fast:x", encoding="utf-8")
    _link(host / ".claude/vway-kit/.vdev", outside)
    report = migrate_legacy_paths(host)
    assert (outside / "tier").read_text(encoding="utf-8") == "fast:x"
    assert any("[!]" in ln for ln in report)


def test_seed_never_lands_through_a_dangling_link(tmp_path):
    host, outside = _layout(tmp_path)
    target = outside / "created"
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _link(host / ".claude/vway-kit/templates/handoff/summary.md", target)
    seed_host_templates(host, PLUGIN)
    assert not target.exists()


def test_precommit_example_never_lands_through_a_dangling_link(tmp_path):
    host, outside = _layout(tmp_path)
    target = outside / "created"
    _link(host / ".pre-commit-config.yaml", target)
    check_precommit(PLUGIN, host)
    assert not target.exists()


def test_render_never_lands_through_a_dangling_link(tmp_path):
    host, outside = _layout(tmp_path)
    target = outside / "created"
    dest = host / ".github/workflows/e2e.yml"
    _link(dest, target)
    _render_one(host, PLUGIN / "github/e2e.workflow.example.yml", dest, {})
    assert not target.exists()


def test_render_refuses_a_workflows_dir_linked_outside(tmp_path):
    host, outside = _layout(tmp_path)
    _link(host / ".github/workflows", outside)
    report = _render_one(
        host, PLUGIN / "github/e2e.workflow.example.yml", host / ".github/workflows/e2e.yml", {}
    )
    assert list(outside.iterdir()) == []
    assert any("[!]" in ln for ln in report)


def test_deploy_orchestrator_replaces_a_symlinked_file(tmp_path):
    """`dest.is_file()` 은 링크를 따라가 victim 을 보므로, 교체가 존재 판정보다 먼저여야 함."""
    host, outside = _layout(tmp_path)
    _mk_host_config(
        host, "deploy:\n  enable: true\n  targets:\n    - name: pypi\n      target: pypi\n"
    )
    orch = host / ".github/workflows/deploy.yml"
    target = outside / "created"
    _link(orch, target)
    render_deploy_workflows(host, PLUGIN)
    assert not target.exists()
    assert not orch.is_symlink() and orch.is_file()


def test_version_marker_replaces_a_symlinked_file(tmp_path):
    host, outside = _layout(tmp_path)
    victim = _victim(outside)
    marker = host / VERSION_MARKER_PATH
    _link(marker, victim)
    apply_migrations(host, PLUGIN, registry={})
    assert victim.read_text(encoding="utf-8") == VICTIM_TEXT
    assert not marker.is_symlink() and marker.is_file()


@pytest.mark.parametrize(
    ("render", "block"),
    [
        (render_workflow, {"contract_test": {"enable": True}}),
        (
            render_unit_test_workflow,
            {"unit_test": {"enable": True, "jobs": [{"name": "py", "test": "pytest"}]}},
        ),
    ],
)
def test_config_renders_refuse_a_workflows_dir_linked_outside(tmp_path, render, block):
    host, outside = _layout(tmp_path)
    _mk_host_config(host, yaml.safe_dump(block))
    _link(host / ".github/workflows", outside)
    report = render(host, PLUGIN)
    assert list(outside.iterdir()) == []
    assert any("[!]" in ln for ln in report)


# ── 제자리 편집: 다시 쓰는 호스트 파일이 호스트를 떠나는 링크면 안 됨 ──

BARE_SETTINGS = '{"permissions": {"allow": []}}\n'
GATED_SETTINGS = json.dumps({"hooks": {"PreToolUse": [GATE_ENTRY]}}) + "\n"


@pytest.mark.parametrize(
    ("step", "body"),
    [
        (register_gate, BARE_SETTINGS),
        (register_marketplace, BARE_SETTINGS),
        (unregister_gate, GATED_SETTINGS),
    ],
)
def test_settings_steps_refuse_a_settings_file_linked_outside(tmp_path, step, body):
    """`~/.claude/settings.json` 을 가리키는 커밋된 `.claude/settings.json` 은 그 사용자의 모든
    프로젝트에 게이트를 넣음."""
    host, outside = _layout(tmp_path)
    victim = outside / "settings.json"
    victim.write_text(body, encoding="utf-8")
    _link(host / ".claude" / "settings.json", victim)
    report = step(host)
    assert victim.read_text(encoding="utf-8") == body
    assert (host / ".claude" / "settings.json").is_symlink()
    assert "[!]" in report


def test_unregister_empties_a_linked_settings_file_instead_of_unlinking_it(tmp_path):
    """링크를 지우면 다른 경로로 여전히 읽히는 그 대상이, uninstall 이 지우는 스크립트를 이름 대는
    게이트를 쥔 채 남음."""
    host, _outside = _layout(tmp_path)
    shared = host / "shared" / "settings.json"
    shared.parent.mkdir()
    shared.write_text(GATED_SETTINGS, encoding="utf-8")
    _link(host / ".claude" / "settings.json", shared)
    assert "[-]" in unregister_gate(host)
    assert (host / ".claude" / "settings.json").is_symlink()
    assert json.loads(shared.read_text(encoding="utf-8")) == {}


def test_unregister_never_deletes_a_settings_file_through_a_claude_dir_linked_outside(tmp_path):
    host, outside = _layout(tmp_path)
    victim = outside / "settings.json"
    victim.write_text(GATED_SETTINGS, encoding="utf-8")
    _link(host / ".claude", outside)
    assert "[!]" in unregister_gate(host)
    assert victim.read_text(encoding="utf-8") == GATED_SETTINGS


def test_register_gate_refuses_a_claude_dir_linked_outside(tmp_path):
    """복사는 이 디렉터리를 거부하므로, 여기에 등록하면 스크립트 없는 훅이 남음."""
    host, outside = _layout(tmp_path)
    _link(host / ".claude", outside)
    report = register_gate(host)
    assert list(outside.iterdir()) == []
    assert "[!]" in report


def test_codex_register_refuses_a_hooks_file_linked_outside(tmp_path):
    host, outside = _layout(tmp_path)
    victim = outside / "hooks.json"
    victim.write_text("{}\n", encoding="utf-8")
    _link(host / ".codex" / "hooks.json", victim)
    report = codex_install.register(host)
    assert victim.read_text(encoding="utf-8") == "{}\n"
    assert "[!]" in report


def test_codex_unregister_never_deletes_through_a_dir_linked_outside(tmp_path):
    host, outside = _layout(tmp_path)
    victim = outside / "hooks.json"
    victim.write_text(
        json.dumps({"hooks": {"PreToolUse": [codex_install.GATE_ENTRY]}}) + "\n", encoding="utf-8"
    )
    _link(host / ".codex", outside)
    report = codex_install.unregister(host)
    assert victim.exists()
    assert "[!]" in report


CODEX_GATED = json.dumps({"hooks": {"PreToolUse": [codex_install.GATE_ENTRY]}}) + "\n"


def test_codex_unregister_empties_a_linked_hooks_file_instead_of_unlinking_it(tmp_path):
    """링크를 지우면 다른 경로로 여전히 읽히는 그 대상이, uninstall 이 지우는 스크립트를 이름 대는
    게이트를 쥔 채 남음. 비운 모양은 Codex 가 로드하는 `{"hooks": {}}`."""
    host, _outside = _layout(tmp_path)
    shared = host / "shared" / "hooks.json"
    shared.parent.mkdir()
    shared.write_text(CODEX_GATED, encoding="utf-8")
    _link(host / ".codex" / "hooks.json", shared)
    assert "[-]" in codex_install.unregister(host)
    assert (host / ".codex" / "hooks.json").is_symlink()
    assert json.loads(shared.read_text(encoding="utf-8")) == {"hooks": {}}


def test_codex_unregister_keeps_a_hooks_file_that_holds_a_key_of_the_hosts(tmp_path):
    hooks = tmp_path / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    body = {"description": "team hooks", "hooks": {"PreToolUse": [codex_install.GATE_ENTRY]}}
    hooks.write_text(json.dumps(body), encoding="utf-8")
    assert "[-]" in codex_install.unregister(tmp_path)
    assert json.loads(hooks.read_text(encoding="utf-8")) == {
        "description": "team hooks",
        "hooks": {},
    }


def test_codex_unregister_refuses_a_read_only_hooks_file(tmp_path):
    hooks = tmp_path / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(CODEX_GATED, encoding="utf-8")
    hooks.chmod(0o444)
    try:
        if os.access(hooks, os.W_OK):  # 쓰기 비트가 소유자를 막지 못하는 호스트
            pytest.skip("읽기 전용이 강제되지 않는 호스트")
        assert "[!]" in codex_install.unregister(tmp_path)
        assert hooks.read_text(encoding="utf-8") == CODEX_GATED
    finally:
        hooks.chmod(0o644)


def _report(out) -> str:
    return "\n".join(out) if isinstance(out, list) else out


@pytest.mark.parametrize(
    ("name", "edit", "body"),
    [
        (".gitignore", append_gitignore, VICTIM_TEXT),
        (".gitignore", remove_gitignore_lines, ".claude/vway-kit/.vdev/\n"),
        (
            "CLAUDE.md",
            remove_claude_md_block,
            "<!-- vway-kit:teams BEGIN -->\nx\n<!-- vway-kit:teams END -->\n",
        ),
    ],
)
def test_in_place_edits_refuse_a_file_linked_outside(tmp_path, name, edit, body):
    host, outside = _layout(tmp_path)
    victim = outside / name
    victim.write_text(body, encoding="utf-8")
    _link(host / name, victim)
    report = _report(edit(host))
    assert victim.read_text(encoding="utf-8") == body
    assert "[!]" in report


def test_release_deploy_wiring_refuses_a_release_file_linked_outside(tmp_path):
    host, outside = _layout(tmp_path)
    _write_deploy_config(host, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    victim = outside / "release.yml"
    victim.write_text(_RELEASE_OK, encoding="utf-8")
    _link(host / ".github/workflows/release.yml", victim)
    report = _report(wire_release_deploy(host))
    assert victim.read_text(encoding="utf-8") == _RELEASE_OK
    assert "[!]" in report
