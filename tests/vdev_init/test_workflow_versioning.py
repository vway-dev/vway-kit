"""버저닝 워크플로 렌더와 구 방식 release.yml 진단.

언어별 도구(python-semantic-release·jreleaser·GitVersion·cargo-release·sbt-ci-release)를
vdev-config 가 지목하고, 모르는 도구는 렌더하지 않고 AI 에 맡김 — 이미 있는 release.yml
을 덮지 않는 것이 그 계약의 절반임.
"""

from pathlib import Path

import yaml as _yaml

from scripts.vdev_init_setup import (
    detect_legacy_release_workflow,
    report_legacy_release_workflow,
)
from tests.vdev_init._helpers import (
    PLUGIN,
    _mk_host_release_wf,
)


def test_detect_legacy_release_workflow_absent(tmp_path: Path):
    host = tmp_path / "host"
    host.mkdir()
    diag = detect_legacy_release_workflow(host)
    assert diag["present"] is False
    assert diag["legacy"] is False


def test_detect_legacy_release_workflow_legacy(tmp_path: Path):
    # GITHUB_TOKEN 사용 + RELEASE_TOKEN 미참조 → 구 방식.
    host = tmp_path / "host"
    _mk_host_release_wf(host, "token: ${{ secrets.GITHUB_TOKEN }}\n")
    diag = detect_legacy_release_workflow(host)
    assert diag["present"] is True
    assert diag["legacy"] is True


def test_detect_legacy_release_workflow_new(tmp_path: Path):
    # RELEASE_TOKEN 참조 → 신 방식(GITHUB_TOKEN 이 함께 있어도 legacy 아님).
    host = tmp_path / "host"
    _mk_host_release_wf(host, "token: ${{ secrets.RELEASE_TOKEN }}\n")
    diag = detect_legacy_release_workflow(host)
    assert diag["present"] is True
    assert diag["legacy"] is False


def test_report_legacy_release_workflow_warns(tmp_path: Path):
    host = tmp_path / "host"
    _mk_host_release_wf(host, "token: ${{ secrets.GITHUB_TOKEN }}\n")
    out = report_legacy_release_workflow(host)
    assert any("[!]" in ln for ln in out)
    assert any("RELEASE_TOKEN" in ln for ln in out)
    assert any("Contents: Read and write" in ln for ln in out)


def test_report_legacy_release_workflow_ok(tmp_path: Path):
    host = tmp_path / "host"
    # has_tag_output=True·release-notes 블록 있음이어야 다른 진단이 끼어들지 않음.
    _mk_host_release_wf(
        host,
        "token: ${{ secrets.RELEASE_TOKEN }}\noutputs:\n  tag: ${{ steps.released.outputs.tag }}\n"
        "# >>> vway-release-notes\n",
    )
    out = report_legacy_release_workflow(host)
    assert out == ["  [=] release 워크플로 RELEASE_TOKEN 방식 (OK)"]


def test_a_workflow_without_the_release_notes_step_is_reported(tmp_path: Path):
    """옛 렌더는 dispatch 입력이 없어도 노트 스텝이 없음 — 승인받은 CHANGELOG 절을 아무도
    싣지 않는데 아무 신호도 없으면 그대로 굳음."""
    host = tmp_path / "host"
    _mk_host_release_wf(
        host,
        "token: ${{ secrets.RELEASE_TOKEN }}\noutputs:\n  tag: ${{ steps.released.outputs.tag }}\n",
    )
    assert detect_legacy_release_workflow(host)["no_release_notes"] is True
    out = report_legacy_release_workflow(host)
    assert any("[!]" in ln and "vway-release-notes" in ln for ln in out)


def test_report_legacy_release_workflow_absent_skip(tmp_path: Path):
    host = tmp_path / "host"
    host.mkdir()
    assert report_legacy_release_workflow(host) == ["  [=] release 워크플로 없음 (skip)"]


_DISPATCH_LEVEL_WF = """\
name: release
on:
  push:
    branches: [main, stage]
  workflow_dispatch:
    inputs:
      level:
        type: choice
        options: [patch, minor, major]
jobs:
  release:
    runs-on: ubuntu-latest
    outputs:
      tag: ${{ steps.released.outputs.tag }}
    steps:
      - run: echo "${{ secrets.RELEASE_TOKEN }}"
"""


def _write_release_wf(host: Path, text: str) -> None:
    wf = host / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "release.yml").write_text(text, encoding="utf-8")


def test_dispatch_level_without_trailer_is_a_stale_level_channel(tmp_path: Path):
    """옛 템플릿(dispatch level, 트레일러 없음)은 /release-commit 이 멈추는 호스트 — 재실행이 그것을
    드러내야 사람이 승격 날이 아니라 지금 재렌더함."""
    _write_release_wf(tmp_path, _DISPATCH_LEVEL_WF)
    assert detect_legacy_release_workflow(tmp_path)["stale_level_channel"] is True
    out = report_legacy_release_workflow(tmp_path)
    assert any("[!]" in ln and "Release-Level" in ln for ln in out), out
    assert any("/vdev-init" in ln for ln in out), out


def test_a_workflow_reading_the_trailer_is_not_stale(tmp_path: Path):
    """dispatch 를 함께 둔 손작성 워크플로라도 트레일러를 읽으면 /release-commit 이 다룰 수 있음."""
    _write_release_wf(tmp_path, _DISPATCH_LEVEL_WF + "      - run: echo Release-Level\n")
    assert detect_legacy_release_workflow(tmp_path)["stale_level_channel"] is False


def test_no_dispatch_level_is_not_stale(tmp_path: Path):
    """레벨 입력이 없는 워크플로(커밋 타입 자동 전용)는 바꿀 레벨 채널이 없음."""
    text = _DISPATCH_LEVEL_WF.replace(
        "  workflow_dispatch:\n    inputs:\n      level:\n        type: choice\n"
        "        options: [patch, minor, major]\n",
        "",
    )
    _write_release_wf(tmp_path, text)
    assert detect_legacy_release_workflow(tmp_path)["stale_level_channel"] is False


def test_unparseable_workflow_is_not_stale(tmp_path: Path):
    """판단 불가는 경보 사유가 아님(FAIL-OPEN) — 깨진 YAML 을 옛 채널로 읽지 않음."""
    _write_release_wf(tmp_path, "on: [\nworkflow_dispatch:\n  inputs: {level: {}}\n")
    assert detect_legacy_release_workflow(tmp_path)["stale_level_channel"] is False


def test_render_versioning_python(tmp_path):
    from scripts import vdev_init_setup as m

    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    # SOURCE 템플릿 배치
    (plugin / "github").mkdir(parents=True)
    (plugin / "github" / "release.python-semantic-release.workflow.example.yml").write_text(
        "on:\n  push:\n    branches: [__VWAY_STABLE__, __VWAY_PRERELEASE__]\n",
        encoding="utf-8",
    )
    (plugin / "github" / "branch-naming.workflow.example.yml").write_text(
        "name: branch-naming\n", encoding="utf-8"
    )
    ent_tmpl = (
        'on:\n  schedule:\n    - cron: "__VWAY_ENTROPY_SCHEDULE__"\npaths: __VWAY_ENTROPY_PATHS__\n'
    )
    (plugin / "github" / "entropy-check.workflow.example.yml").write_text(
        ent_tmpl, encoding="utf-8"
    )
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: true\n  release_tool: python-semantic-release\n"
        "  branches: {stable: main, prerelease: stage}\n"
        "  branch_naming: {enable: true}\n"
        '  entropy: {enable: true, schedule: "0 0 * * 5", paths: ["src/"]}\n',
        encoding="utf-8",
    )
    m.render_versioning_workflows(host, plugin)
    rel = (host / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "[main, stage]" in rel and "__VWAY_" not in rel
    assert (host / ".github" / "workflows" / "branch-naming.yml").exists()
    ent = (host / ".github" / "workflows" / "entropy-check.yml").read_text(encoding="utf-8")
    assert "0 0 * * 5" in ent and "src/" in ent


def test_render_versioning_jreleaser(tmp_path):
    from scripts import vdev_init_setup as m

    host = tmp_path / "host"
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: true\n  release_tool: jreleaser\n"
        "  branches: {stable: main, prerelease: stage}\n",
        encoding="utf-8",
    )
    out = m.render_versioning_workflows(host, PLUGIN)
    assert any("release.yml" in ln and "생성" in ln for ln in out)
    text = (host / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    assert "[main, stage]" in text
    assert "JRELEASER_PROJECT_VERSION" in text
    _yaml.safe_load(text)


def test_render_versioning_gitversion(tmp_path):
    from scripts import vdev_init_setup as m

    host = tmp_path / "host"
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: true\n  release_tool: gitversion\n"
        "  branches: {stable: main, prerelease: stage}\n",
        encoding="utf-8",
    )
    out = m.render_versioning_workflows(host, PLUGIN)
    assert any("release.yml" in ln and "생성" in ln for ln in out)
    text = (host / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    assert "[main, stage]" in text
    assert "dotnet build" in text
    assert "gitversion/execute" not in text  # GitVersion 액션은 호출하지 않는다(설계 정정)
    _yaml.safe_load(text)


def test_render_versioning_cargo_release(tmp_path):
    from scripts import vdev_init_setup as m

    host = tmp_path / "host"
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: true\n  release_tool: cargo-release\n"
        "  branches: {stable: main, prerelease: stage}\n",
        encoding="utf-8",
    )
    out = m.render_versioning_workflows(host, PLUGIN)
    assert any("release.yml" in ln and "생성" in ln for ln in out)
    text = (host / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    assert "[main, stage]" in text
    assert "cargo release" in text
    _yaml.safe_load(text)


def test_render_versioning_sbt_ci_release(tmp_path):
    from scripts import vdev_init_setup as m

    host = tmp_path / "host"
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: true\n  release_tool: sbt-ci-release\n"
        "  branches: {stable: main, prerelease: stage}\n",
        encoding="utf-8",
    )
    out = m.render_versioning_workflows(host, PLUGIN)
    assert any("release.yml" in ln and "생성" in ln for ln in out)
    text = (host / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    assert "[main, stage]" in text
    assert "sbt ci-release" in text
    _yaml.safe_load(text)


def test_render_versioning_disabled(tmp_path):
    from scripts import vdev_init_setup as m

    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: false\n", encoding="utf-8"
    )
    m.render_versioning_workflows(host, plugin)
    assert not (host / ".github" / "workflows" / "release.yml").exists()


def test_render_versioning_unknown_tool_defers_to_ai(tmp_path):
    # release_tool 이 알려진 템플릿에 없으면(Go/C++ 등) 스크립트는 추측해 만들지
    # 않고 [?] 로 AI 저작이 필요하다고만 보고함 — release.yml 은 생성되지 않음.
    from scripts import vdev_init_setup as m

    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: true\n  release_tool: goreleaser\n"
        "  branches: {stable: main, prerelease: stage}\n",
        encoding="utf-8",
    )
    out = m.render_versioning_workflows(host, plugin)
    assert not (host / ".github" / "workflows" / "release.yml").exists()
    assert any("[?]" in ln and "goreleaser" in ln for ln in out)


def test_render_versioning_unknown_tool_preserves_existing_release_yml(tmp_path):
    # 이미 release.yml 이 있으면(사람이나 이전 AI 저작) 알 수 없는 도구여도 건드리지 않음.
    from scripts import vdev_init_setup as m

    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    wf_dir = host / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "release.yml").write_text("name: custom\n", encoding="utf-8")
    (host / ".claude" / "vway-kit" / "config").mkdir(parents=True)
    (host / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "versioning:\n  enable: true\n  release_tool: goreleaser\n"
        "  branches: {stable: main, prerelease: stage}\n",
        encoding="utf-8",
    )
    out = m.render_versioning_workflows(host, plugin)
    assert (wf_dir / "release.yml").read_text(encoding="utf-8") == "name: custom\n"
    assert any("이미 있어" in ln for ln in out)
