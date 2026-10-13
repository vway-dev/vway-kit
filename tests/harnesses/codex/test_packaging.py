"""Codex 는 자기 매니페스트·마켓플레이스가 따로 필요하고, 그 패키지는 라이프사이클 훅을 싣지
않음 — OpenAI 플러그인 디렉터리가 훅 든 패키지를 거부하므로 세션 훅은 호스트 것
(`scripts/harness/codex/install.py`). Codex 는 `hooks/hooks.json` 을 스스로 찾아내므로 Claude
훅 파일은 다른 자리에 둠."""

import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

from tests._bash import BASH
from tests._proc import run_bounded

REPO = Path(__file__).resolve().parents[3]
CODEX = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
CLAUDE = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def test_versions_and_names_match():
    assert CODEX["name"] == CLAUDE["name"]
    assert CODEX["version"] == CLAUDE["version"]


def test_three_way_version_parity():
    # pyproject.toml 이 release.yml sed·semantic-release version_variables 가 함께 올리는
    # 셋(pyproject·두 plugin.json) 의 기준 — 하나라도 어긋나면 재설치 게이팅이 갈라짐.
    assert PYPROJECT["project"]["version"] == CLAUDE["version"] == CODEX["version"]


def test_pyproject_version_variables_includes_codex_manifest():
    sr = PYPROJECT["tool"]["semantic_release"]
    assert ".codex-plugin/plugin.json:version" in sr["version_variables"]
    assert ".claude-plugin/plugin.json:version" in sr["version_variables"]


def test_release_yml_sed_and_add_cover_both_manifests():
    # release.yml 이 .claude-plugin/plugin.json 을 sed·git add 하는 줄마다 바로 옆(sed) 또는
    # 같은 줄(git add) 에 .codex-plugin/plugin.json 도 있는지 — 하나라도 빠지면 Codex 매니페스트가
    # 릴리스에서 버전이 안 오름(finalize_prerelease.py 가 없어 이 sed 한 줄이 유일한 쓰기 지점).
    lines = (
        (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8").splitlines()
    )
    sed_re = re.compile(r'sed -i -E .*"version".*\.claude-plugin/plugin\.json\s*$')
    sed_hits = [i for i, ln in enumerate(lines) if sed_re.search(ln)]
    assert sed_hits, "release.yml 에 .claude-plugin/plugin.json 을 sed 하는 줄이 없음"
    for i in sed_hits:
        nxt = lines[i + 1]
        assert ".codex-plugin/plugin.json" in nxt
        assert nxt.replace(".codex-plugin", ".claude-plugin") == lines[i]
    add_hits = [ln for ln in lines if "git add" in ln and ".claude-plugin/plugin.json" in ln]
    assert add_hits, "release.yml 에 .claude-plugin/plugin.json 을 git add 하는 줄이 없음"
    for ln in add_hits:
        assert ".codex-plugin/plugin.json" in ln


def test_codex_package_declares_and_discovers_no_hooks():
    assert "hooks" not in CODEX
    assert not (REPO / "hooks" / "hooks.json").exists(), "Codex 가 Claude 훅을 등록함"
    assert not (REPO / "hooks" / "codex" / "hooks.json").exists()
    assert CLAUDE["hooks"] == "./hooks/claude/hooks.json"
    assert CODEX["skills"] == "./skills/"


def test_codex_listing_fields_fit_the_directory_limits():
    ui = CODEX["interface"]
    assert len(ui["displayName"]) <= 30 and len(ui["shortDescription"]) <= 30
    assert 0 < len(ui["longDescription"]) <= 4000 and len(ui["developerName"]) <= 80
    assert len(ui["defaultPrompt"]) <= 3 and all(len(p) <= 128 for p in ui["defaultPrompt"])
    for key in ("logo", "composerIcon"):
        assert ui[key].startswith("./") and (REPO / ui[key]).is_file(), key
    assert CLAUDE["icon"] == ui["logo"]


def test_no_root_plugin_json():
    # 루트 plugin.json 이 있으면 Codex 가 Agent Plugins 로더로 바뀌어 훅이 전부 죽음.
    assert not (REPO / "plugin.json").exists()


def test_marketplace_lists_the_plugin():
    mk = json.loads((REPO / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
    (entry,) = mk["plugins"]
    assert entry["name"] == CODEX["name"]
    assert entry["policy"] == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}


def test_cmd_files_have_no_labels():
    for p in (
        REPO / "hooks" / "codex" / "run-hook.cmd",
        REPO / "scripts" / "harness" / "codex" / "gate.cmd",
    ):
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"^\s*:[A-Za-z]", text, re.M), p
        assert "goto" not in text.lower(), p


@pytest.mark.skipif(sys.platform != "win32", reason="run-hook.cmd 는 Windows 전용 wrapper")
@pytest.mark.skipif(BASH is None, reason="repo 를 볼 수 있는 bash 가 필요함")
def test_run_hook_cmd_runs_a_real_hook_script_through_cmd_exe():
    # 진짜 cmd.exe 를 거쳐(파일 모양이 아니라 end-to-end) run-hook.cmd 가 Git Bash 를 찾아
    # inject-risk-tiers.sh 를 --harness codex 로 실행해, direct bash 호출과 같은 SessionStart
    # JSON 을 내는지 잼 — CLAUDE_PLUGIN_ROOT 없이(Codex 가 명령 문자열 안 ${PLUGIN_ROOT} 를
    # 자기가 직접 치환하므로 wrapper 는 그 환경변수를 절대 못 받음).
    run_hook = REPO / "hooks" / "codex" / "run-hook.cmd"
    result = run_bounded(
        ["cmd", "/d", "/c", str(run_hook), "inject-risk-tiers.sh", "--harness", "codex"],
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "additionalContext" in out["hookSpecificOutput"]


def test_vdev_stops_a_codex_host_without_the_session_hooks():
    """플러그인이 훅을 싣던 때 셋업한 Codex 호스트는 업데이트로 그 훅을 잃음 — 모든 작업이 들어오는
    라우터만은 여전히 돌므로, 거기서 확인할 것과 고칠 방법을 댐."""
    text = (REPO / "skills" / "vdev" / "SKILL.md").read_text(encoding="utf-8")
    assert "vway-kit/hooks/invalidate-gate-markers.sh" in text and "$vdev-init" in text
