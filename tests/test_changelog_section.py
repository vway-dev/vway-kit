"""`scripts/changelog_section.py` — 릴리스가 rc 절들을 접어 넣는 정식 절.

이 절이 GitHub Release 본문이 되므로, 여기 틀리면 소비자가 읽는 텍스트가 rc 조각의 나열이나
남의 버전이 됨. 워크플로 배선(그 절을 실제로 싣는 공통 블록)은 `test_release_notes_block.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scripts import changelog_section as cs
from scripts.changelog_section import extract, fold, pending_sections
from tests._proc import run_bounded

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "changelog_section.py"

PSR = """# CHANGELOG

<!-- version list -->

## v0.5.0-rc.1 (2026-09-23)

### Features

- **release**: rc 절을 접어 넣음

## v0.4.1-rc.1 (2026-09-22)

### Bug Fixes

- **gate**: 워킹트리를 읽음


## v0.4.0-rc.1 (2026-09-12)

### Features

- **docs**: USAGE 를 나눔
"""
TAGS = ["v0.4.0-rc.1", "v0.4.0", "v0.4.1-rc.1", "v0.5.0-rc.1"]


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def test_pending_sections_are_the_rc_sections_above_the_last_stable_tag():
    assert [s.splitlines()[0] for s in pending_sections(PSR, TAGS)] == [
        "## v0.5.0-rc.1 (2026-09-23)",
        "## v0.4.1-rc.1 (2026-09-22)",
    ]


def test_fold_replaces_every_pending_rc_section_with_one_stable_section():
    out = fold(PSR, "0.5.0", "### Features\n\n- **release**: 요약 한 줄\n", TAGS, "2026-09-24")
    assert _headings(out) == ["## v0.5.0 (2026-09-24)", "## v0.4.0-rc.1 (2026-09-12)"]
    assert out.startswith("# CHANGELOG\n\n<!-- version list -->\n\n## v0.5.0 (2026-09-24)\n\n")
    assert "워킹트리를 읽음" not in out
    # 정식이 난 v0.4.0 의 rc 절은 이번 릴리스가 접는 것이 아니라 이력 — 남아야 함.
    assert "- **docs**: USAGE 를 나눔" in out


def test_fold_refuses_what_would_produce_a_wrong_section():
    """빈 본문·제목 든 본문·`X.Y.Z` 아닌 버전·이미 있는 절·마지막 정식 이하는 전부 거부 —
    그대로 쓰면 절이 중간에서 끊기거나 남의 릴리스 본문이 됨."""
    with pytest.raises(ValueError, match="비었음"):
        fold(PSR, "0.5.0", "  \n", TAGS, "2026-09-24")
    with pytest.raises(ValueError, match="제목"):
        fold(PSR, "0.5.0", "## Features\n\n- a\n", TAGS, "2026-09-24")
    for version in ("1.4", "v0.5.0", "0.5.0-rc.1"):
        with pytest.raises(ValueError, match="맨 `X.Y.Z`"):
            fold(PSR, version, "- a\n", TAGS, "2026-09-24")
    with pytest.raises(ValueError, match="이하"):
        fold(PSR, "0.4.0", "- a\n", TAGS, "2026-09-24")
    once = fold(PSR, "0.5.0", "- a\n", TAGS, "2026-09-24")
    with pytest.raises(ValueError, match="이미 있음"):
        fold(once, "0.5.0", "- b\n", TAGS, "2026-09-24")


def test_fold_refuses_a_changelog_with_conflict_markers():
    """열린 승격 머지에서 도는 단계 — 충돌한 CHANGELOG 를 접으면 표시 절반만 지워진 파일이
    승격 커밋에 실리고 릴리스 노트는 멀쩡해 보임."""
    conflicted = PSR.replace(
        "## v0.5.0-rc.1 (2026-09-23)",
        "<<<<<<< HEAD\n## v0.5.0-rc.1 (2026-09-23)\n=======\n>>>>>>> origin/stage",
    )
    with pytest.raises(ValueError, match="충돌"):
        fold(conflicted, "0.5.0", "- a\n", TAGS, "2026-09-24")


def test_fold_creates_a_changelog_the_tool_can_keep_updating():
    out = fold("", "1.0.0", "- 첫 릴리스\n", [], "2026-09-24")
    assert out == "# CHANGELOG\n\n<!-- version list -->\n\n## v1.0.0 (2026-09-24)\n\n- 첫 릴리스\n"


def test_extract_prints_the_stable_section_body_only():
    text = fold(PSR, "0.5.0", "### Features\n\n- a\n", TAGS, "2026-09-24")
    assert extract(text, "0.5.0") == "### Features\n\n- a"


def test_extract_ignores_rc_sections_of_the_same_base():
    """rc 절을 정식 절로 읽으면 접기 전 조각이 릴리스 본문이 됨."""
    assert extract(PSR, "0.5.0") is None
    assert extract("## v1.3.0-beta (2026-09-24)\n\n- b\n", "1.3.0") is None


NODE = """# Changelog

# [1.3.0-rc.2](https://x/compare/v1.3.0-rc.1...v1.3.0-rc.2) (2026-09-22)

- rc 둘

# [1.3.0-rc.1](https://x/compare/v1.2.1...v1.3.0-rc.1) (2026-09-21)

- rc 하나

## [1.2.1](https://x/compare/v1.2.0...v1.2.1) (2026-09-10)

- patch

# [1.2.0](https://x/compare/v1.1.0...v1.2.0) (2026-09-01)

- minor
"""
NODE_TAGS = ["v1.2.0", "v1.2.1", "v1.3.0-rc.1", "v1.3.0-rc.2"]


def test_node_headings_are_sections_too():
    """conventional-changelog-angular 는 minor·major 를 `# [x.y.z]` 로 씀 — 한 단계 제목도 절."""
    assert len(pending_sections(NODE, NODE_TAGS)) == 2
    out = fold(NODE, "1.3.0", "- 요약\n", NODE_TAGS, "2026-09-24")
    assert out.startswith("# Changelog\n\n## v1.3.0 (2026-09-24)\n\n- 요약\n")
    assert "# [1.2.0]" in out and "rc 하나" not in out
    assert extract(NODE, "1.2.0") == "- minor"


def _run(*args, cwd):
    """cp949 stdout 을 강제 — 한글 절이 인코딩 오류로 죽으면 릴리스 본문이 통째로 빔."""
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp949"}
    return run_bounded([sys.executable, str(SCRIPT), *args], cwd=str(cwd), env=env)


def test_cli_fold_then_extract_round_trips_through_crlf(tmp_path: Path):
    (tmp_path / "CHANGELOG.md").write_bytes(PSR.replace("\n", "\r\n").encode("utf-8"))
    (tmp_path / "notes.md").write_text("- 요약 — 한 줄\n", encoding="utf-8")
    tags = "\n".join(TAGS)
    r = _run("fold", "--version", "0.5.0", "--body-file", "notes.md", "--tags", tags, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    raw = (tmp_path / "CHANGELOG.md").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    r = _run("extract", "--version", "0.5.0", cwd=tmp_path)
    assert r.returncode == 0
    assert r.stdout.decode("utf-8").strip() == "- 요약 — 한 줄"


def test_cli_extract_exits_1_silently_when_there_is_no_section(tmp_path: Path):
    """워크플로가 이 종료 코드로 '있는 본문 유지' 를 판정 — stderr 를 쓰면 릴리스가 붉어짐."""
    assert _run("extract", "--version", "0.5.0", cwd=tmp_path).returncode == 1
    (tmp_path / "CHANGELOG.md").write_text(PSR, encoding="utf-8")
    r = _run("extract", "--version", "0.5.0", cwd=tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (1, b"", b"")
    (tmp_path / "CHANGELOG.md").write_bytes(b"\xff\xfe not utf-8")
    assert _run("extract", "--version", "0.5.0", cwd=tmp_path).returncode == 1


def test_cli_pending_names_the_base_and_prints_the_sections(tmp_path: Path):
    (tmp_path / "CHANGELOG.md").write_text(PSR, encoding="utf-8")
    r = _run("pending", "--tags", "\n".join(TAGS), cwd=tmp_path)
    assert r.returncode == 0
    out = r.stdout.decode("utf-8")
    assert out.splitlines()[0] == "since: v0.4.0"
    assert "## v0.5.0-rc.1" in out and "## v0.4.1-rc.1" in out
    assert "## v0.4.0-rc.1" not in out


def test_cli_pending_reads_git_tags_when_none_are_given(tmp_path, monkeypatch, capsys):
    """인자 없는 형태만 `allowed-tools` 가 사전승인함."""
    (tmp_path / "CHANGELOG.md").write_text(PSR, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cs, "git_tags", lambda: TAGS)
    assert cs.main(["pending"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "since: v0.4.0"


def test_cli_fold_exits_2_with_a_reason(tmp_path: Path):
    (tmp_path / "CHANGELOG.md").write_text(PSR, encoding="utf-8")
    (tmp_path / "notes.md").write_text("", encoding="utf-8")
    r = _run("fold", "--version", "0.5.0", "--body-file", "notes.md", "--tags", "", cwd=tmp_path)
    assert r.returncode == 2
    assert b"changelog_section: " in r.stderr


def test_the_script_is_copied_to_the_host():
    from scripts.vdev_init_setup import COPY_FILES

    assert "scripts/changelog_section.py" in COPY_FILES
