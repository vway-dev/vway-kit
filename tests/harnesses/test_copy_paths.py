"""호스트 복사의 목적지 규칙 — `scripts/` 아래 상대 경로를 보존해 두 하네스가 같은 basename
을 실어도 안 겹치는지, 그리고 claude 전용 호스트(기본값)는 `COPY_FILES` 평탄 목적지만 받는지 잼.

- 평탄 `COPY_FILES` 항목은 basename 으로, 하네스별 항목은 하위 경로 그대로 내려앉음(`_dest_rel`).
- `gate_files(harnesses)` 는 켜진 하네스의 게이트 스크립트만 `GATE_FILES` 에 덧붙임.
"""

from pathlib import Path

import scripts.vdev_init_setup as vis
from tests.vdev_init._helpers import PLUGIN

DEST = Path(".claude/vway-kit/scripts")


def test_flat_files_keep_their_destination(tmp_path: Path):
    vis.copy_artifacts(PLUGIN, tmp_path)
    for rel in vis.COPY_FILES:
        assert (tmp_path / DEST / Path(rel).name).is_file(), rel


def test_claude_only_host_gets_exactly_the_flat_copy_set(tmp_path: Path):
    """claude 전용 호스트의 `scripts/` 는 `COPY_FILES` 평탄 목적지와 정확히 같은 집합."""
    vis.copy_artifacts(PLUGIN, tmp_path, harnesses=("claude",))
    got = {p.relative_to(tmp_path / DEST).as_posix() for p in (tmp_path / DEST).rglob("*")}
    assert got == {Path(rel).name for rel in vis.COPY_FILES}


def test_claude_only_report_lines_are_the_flat_basenames(tmp_path: Path):
    report = vis.copy_artifacts(PLUGIN, tmp_path)
    copied = [line for line in report if line.startswith("  [+] 복사: ")]
    assert copied[: len(vis.COPY_FILES)] == [
        f"  [+] 복사: {Path(rel).name}" for rel in vis.COPY_FILES
    ]


def test_claude_only_host_gets_no_harness_tree(tmp_path: Path):
    vis.copy_artifacts(PLUGIN, tmp_path)
    assert not (tmp_path / DEST / "harness").exists()


def test_codex_files_keep_their_subpath(tmp_path: Path):
    report = vis.copy_artifacts(PLUGIN, tmp_path, harnesses=("claude", "codex"))
    assert (tmp_path / DEST / "harness" / "codex" / "gate.sh").is_file()
    assert (tmp_path / DEST / "harness" / "codex" / "gate.cmd").is_file()
    assert "  [+] 복사: harness/codex/gate.sh" in report


def test_answering_script_is_still_copied_before_the_runner(tmp_path: Path):
    """COPY_FILES 주석의 순서 계약 — 하네스 파일이 붙어도 `vdev_gate_check.py` 가 러너보다 먼저."""
    report = vis.copy_artifacts(PLUGIN, tmp_path, harnesses=("claude", "codex"))
    assert report.index("  [+] 복사: vdev_gate_check.py") < report.index(
        "  [+] 복사: precommit-runner.sh"
    )


def test_dest_rel_strips_only_the_scripts_prefix():
    assert vis._dest_rel("scripts/foo.py") == Path("foo.py")
    assert vis._dest_rel("scripts/harness/codex/gate.sh") == Path("harness/codex/gate.sh")
    assert vis._dest_rel("vdev-tiers.yaml") == Path("vdev-tiers.yaml")


def test_gate_files_include_codex_wrappers_only_when_enabled():
    claude_only = vis.gate_files(("claude",))
    both = {rel for rel, _ in vis.gate_files(("claude", "codex"))}
    assert claude_only == vis.GATE_FILES
    codex_dest = f"{DEST.as_posix()}/harness/codex"
    assert {f"{codex_dest}/gate.sh", f"{codex_dest}/gate.cmd"} <= both
