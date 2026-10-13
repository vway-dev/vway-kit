"""Codex 렌더러와 그 원본 — 링크·하드링크로 AGENTS.md 와 같은 파일인 원본은 쓰지 않고,
깨진 원본은 render·check·remove 를 죽이지 않음.

- 무엇을 재는가: 같은 파일 판정(`samefile`·양방향 링크)·끊긴 링크·PyYAML 부재 제거·
  디코딩/권한/YAML 오류 원본의 한 줄 보고.
"""

import os
import sys
from pathlib import Path

import pytest

from scripts.harness.codex import instructions as codex
from tests._proc import run_bounded
from tests.harnesses.codex._instructions import SCRIPT, _write


def _link(link: Path, target: str) -> None:
    try:
        link.symlink_to(Path(target))  # 네이티브 구분자 — 아니면 Windows 가 끊긴 링크를 만듦
    except (OSError, NotImplementedError):
        pytest.skip("symlinks cannot be created here")


def _one_file_cases(host: Path, layout: str) -> Path:
    """AGENTS.md 와 다른 파일 하나를 한 파일로 배치(어느 방향의 링크든, 하드링크든) — 텍스트를
    담은 파일을 돌려줌. `agents-links-rule`(공유 파일이 곧 `.claude/rules/all.md`) 말고는 그 룰
    파일도 받음 — 렌더가 아니었으면 썼을 실제 내용이 있게."""
    if layout == "agents-links-claude":
        real = _write(host, "CLAUDE.md", "# Project\nroot rule\n")
        _link(host / "AGENTS.md", "CLAUDE.md")
    elif layout == "claude-links-agents":
        real = _write(host, "AGENTS.md", "# Project\nroot rule\n")
        _link(host / "CLAUDE.md", "AGENTS.md")
    elif layout == "agents-links-dot-claude":
        real = _write(host, ".claude/CLAUDE.md", "# Project\nroot rule\n")
        _link(host / "AGENTS.md", ".claude/CLAUDE.md")
    elif layout == "agents-links-rule":
        real = _write(host, ".claude/rules/all.md", "always true\n")
        _link(host / "AGENTS.md", ".claude/rules/all.md")
        return real
    elif layout == "agents-links-module-claude":
        real = _write(host, "pkg/CLAUDE.md", "module notes\n")
        _link(host / "AGENTS.md", "pkg/CLAUDE.md")
    elif layout == "hardlink-module":
        real = _write(host, "pkg/CLAUDE.md", "module notes\n")
        try:
            (host / "AGENTS.md").hardlink_to(real)
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("hard links cannot be created here")
    else:
        real = _write(host, "CLAUDE.md", "# Project\nroot rule\n")
        try:
            (host / "AGENTS.md").hardlink_to(real)
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("hard links cannot be created here")
    _write(host, ".claude/rules/all.md", "always true\n")
    return real


@pytest.mark.parametrize(
    "layout",
    [
        "agents-links-claude",
        "claude-links-agents",
        "agents-links-dot-claude",
        "agents-links-rule",
        "agents-links-module-claude",
        "hardlink-module",
        "hardlink",
    ],
)
def test_one_file_for_both_harnesses_is_never_written(tmp_path, layout):
    real = _one_file_cases(tmp_path, layout)
    before = real.read_bytes()
    for _ in range(3):
        lines = codex.render(tmp_path)
        assert len(lines) == 1 and "[!]" in lines[0], lines
    ok, reason = codex.check(tmp_path)
    assert ok and "[!]" in reason, (ok, reason)
    assert "[=]" in codex.remove(tmp_path)
    assert real.read_bytes() == before
    cmd = [sys.executable, str(SCRIPT), "render", "--check", "--host", str(tmp_path)]
    assert run_bounded(cmd).returncode == 0


def test_a_dangling_agents_link_into_claude_md_is_not_followed(tmp_path):
    _link(tmp_path / "AGENTS.md", "CLAUDE.md")
    _write(tmp_path, ".claude/rules/all.md", "always true\n")
    lines = codex.render(tmp_path)
    assert len(lines) == 1 and "[!]" in lines[0], lines
    assert not (tmp_path / "CLAUDE.md").exists()


def test_a_rule_file_linking_to_agents_md_is_never_written(tmp_path):
    """위 경우의 반대 방향 — AGENTS.md 가 실제 파일이고 `.claude/rules/` 의 룰이 그것을 가리킴.
    AGENTS.md 에 쓰면 밑에서 같은 파일인 그 룰도 바뀜."""
    real = _write(tmp_path, "AGENTS.md", "shared text\n")
    before = real.read_bytes()
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    _link(tmp_path / ".claude/rules/x.md", "../../AGENTS.md")
    linked = tmp_path / ".claude/rules/x.md"
    for _ in range(3):
        lines = codex.render(tmp_path)
        assert len(lines) == 1 and "[!]" in lines[0], lines
    ok, reason = codex.check(tmp_path)
    assert ok and "[!]" in reason, (ok, reason)
    assert "[=]" in codex.remove(tmp_path)
    assert real.read_bytes() == before
    assert linked.read_bytes() == before


def test_a_module_claude_md_linking_to_agents_md_is_never_written(tmp_path):
    """같은 반대 방향 — 링크가 룰이 아니라 모듈 `CLAUDE.md`."""
    real = _write(tmp_path, "AGENTS.md", "shared text\n")
    before = real.read_bytes()
    (tmp_path / "pkg").mkdir(parents=True)
    _link(tmp_path / "pkg/CLAUDE.md", "../AGENTS.md")
    linked = tmp_path / "pkg/CLAUDE.md"
    for _ in range(3):
        lines = codex.render(tmp_path)
        assert len(lines) == 1 and "[!]" in lines[0], lines
    ok, reason = codex.check(tmp_path)
    assert ok and "[!]" in reason, (ok, reason)
    assert "[=]" in codex.remove(tmp_path)
    assert real.read_bytes() == before
    assert linked.read_bytes() == before


def test_an_undecodable_source_does_not_hide_a_link_to_agents_md(tmp_path):
    """렌더 뒤 생긴 AGENTS.md 로의 룰 링크 옆에 디코딩 못 하는 룰 — 링크 판정은 파일 동일성만
    비교하므로 여전히 링크를 찾고 AGENTS.md 를 건드리지 않음."""
    _write(tmp_path, "CLAUDE.md", "# Project\nroot rule\n")
    assert any("[+]" in line for line in codex.render(tmp_path))
    before = (tmp_path / "AGENTS.md").read_bytes()
    link = tmp_path / ".claude/rules/link.md"
    link.parent.mkdir(parents=True)
    _link(link, "../../AGENTS.md")
    (tmp_path / ".claude/rules/bad.md").write_bytes(b"\x80\n")
    result = codex.remove(tmp_path)
    assert result.startswith("  [=]") and "link.md" in result, result
    assert (tmp_path / "AGENTS.md").read_bytes() == before and link.is_file()


def test_remove_without_pyyaml_still_deletes_an_emptied_agents_md(tmp_path, monkeypatch):
    import scripts.harness as package
    import scripts.harness.instructions  # noqa: F401 — 아래 setattr 이 읽는 속성을 보장

    _write(tmp_path, "CLAUDE.md", "# Project\nroot rule\n")
    codex.render(tmp_path)
    monkeypatch.setattr(package, "instructions", package.instructions)
    monkeypatch.delitem(sys.modules, "scripts.harness.instructions", raising=False)
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert "삭제" in codex.remove(tmp_path)
    assert not (tmp_path / "AGENTS.md").exists()


def test_remove_still_deletes_an_emptied_agents_md_when_every_source_was_read(tmp_path):
    _write(tmp_path, "CLAUDE.md", "# Project\nroot rule\n")
    codex.render(tmp_path)
    assert "삭제" in codex.remove(tmp_path)
    assert not (tmp_path / "AGENTS.md").exists()


def test_a_dangling_module_claude_md_is_skipped_like_a_dangling_rule(tmp_path):
    from scripts.harness import instructions as model

    _write(tmp_path, "CLAUDE.md", "# Project\nroot rule\n")
    (tmp_path / "pkg").mkdir()
    _link(tmp_path / "pkg/CLAUDE.md", "missing.md")
    assert [d.source for d in model.collect(tmp_path)] == ["CLAUDE.md"]
    lines = codex.render(tmp_path)
    assert len(lines) == 1 and "[+]" in lines[0], lines
    assert codex.check(tmp_path) == (True, "")


# --- 회귀 묶음: 깨진 원본이 render·check·remove 를 죽이면 안 됨 ---------------------------
#
# - render·check 는 `_plan` 에서 원본을 전부 파싱. 읽거나 디코딩 못 한 원본은 한 줄
#   `[!] ... 실패(...)` 보고로 떨어져야 하고(traceback 금지), 원본 내용을 읽지 않는 `remove` 는
#   절대 멈추지 않아야 함.
# - 다섯 모양 중 둘(invalid UTF-8·읽기 불가)은 `_collect` 의 오류 경계에 닿음. 나머지 셋(잘못된
#   YAML·룰 이름의 디렉터리·끊긴 symlink 룰)은 무관한 기존 가드가 먼저 걸러 냄
#   (`_split_frontmatter` 의 YAML 오류 처리·`harness/instructions.py` `sources` 의 `is_file()`).
#   조용히 빠지는 것도 주장이므로 둘 다 여기 고정.
_COLLECT_ERROR_KINDS = frozenset({"invalid-utf8", "unreadable"})


def _malformed_rule(host: Path, kind: str) -> None:
    """깨진 `.claude/rules/bad.md` 하나(또는 끊긴 symlink 변형)를 배치.

    - 이 플랫폼이 의도한 조건을 못 만들면 건너뜀: 파일 소유자에게 `PermissionError` 가 보장되지
      않고(특히 `chmod` 가 POSIX 처럼 읽기를 막지 않는 Windows), symlink 는 권한이 필요할 수 있음.
    """
    rules = host / ".claude" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    if kind == "invalid-utf8":
        (rules / "bad.md").write_bytes(b'---\npaths: ["**/*.py"]\n---\n\x80\n')
    elif kind == "invalid-yaml":
        (rules / "bad.md").write_bytes(b"---\npaths: [oops\n---\nbody\n")
    elif kind == "unreadable":
        p = rules / "bad.md"
        p.write_bytes(b"normal content\n")
        try:
            os.chmod(p, 0o000)
        except OSError:
            pytest.skip("cannot restrict this file's permissions on this filesystem")
        try:
            p.read_bytes()
        except PermissionError:
            pass
        else:
            os.chmod(p, 0o644)
            pytest.skip("the file's own owner can still read it despite chmod 000 here")
    elif kind == "directory-rule":
        (rules / "bad.md").mkdir()
    elif kind == "dangling-rule":
        _link(rules / "dangling.md", "missing-target.md")
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind", ["invalid-utf8", "invalid-yaml", "unreadable", "directory-rule", "dangling-rule"]
)
def test_a_malformed_source_never_crashes_render_check_or_remove(tmp_path, kind):
    outside = b"# Team notes\nkeep me\n"
    (tmp_path / "AGENTS.md").write_bytes(outside)
    _write(tmp_path, "CLAUDE.md", "# Project\nroot rule\n")
    lines = codex.render(tmp_path)
    assert any("[+]" in line for line in lines), lines
    before = (tmp_path / "AGENTS.md").read_bytes()
    assert before.startswith(outside)

    try:
        _malformed_rule(tmp_path, kind)

        # render: traceback 금지 — 진짜 수집 오류면 아무것도 쓰지 않음.
        lines = codex.render(tmp_path)
        assert len(lines) == 1, lines
        if kind in _COLLECT_ERROR_KINDS:
            assert "[!]" in lines[0], lines
            assert (tmp_path / "AGENTS.md").read_bytes() == before
        after_render = (tmp_path / "AGENTS.md").read_bytes()
        assert after_render.startswith(outside)

        # check: traceback 금지 — `ok` 는 원본을 수집할 수 있었는지를 따르고, 어느 쪽이든 쓰지 않음.
        ok, reason = codex.check(tmp_path)
        if kind in _COLLECT_ERROR_KINDS:
            assert ok is False and reason, (ok, reason)
        assert (tmp_path / "AGENTS.md").read_bytes() == after_render

        # remove: 룰 상태와 무관하게 자기 블록 제거는 늘 성공 — (최선 노력) 역방향 판정 아래로는
        # AGENTS.md 자신의 바이트만 읽고 룰·모듈 내용은 읽지 않음.
        result = codex.remove(tmp_path)
        assert "[!]" not in result, result
        assert (tmp_path / "AGENTS.md").read_bytes() == outside

        # 단독 CLI(doc-sync·harness-init 이 직접 부르는 것)도 같아야 함: 깔끔한 한 줄과 정해진
        # 종료 코드, stderr 에 Python traceback 금지.
        cmd = [sys.executable, str(SCRIPT), "render", "--check", "--host", str(tmp_path)]
        cli = run_bounded(cmd, text=True)
        assert cli.returncode in (0, 1), cli
        assert "Traceback" not in cli.stderr, cli.stderr
        assert "Traceback" not in cli.stdout, cli.stdout
    finally:
        bad = tmp_path / ".claude" / "rules" / "bad.md"
        if bad.exists():
            try:
                os.chmod(bad, 0o644)
            except OSError:
                pass


@pytest.mark.parametrize("call", ["render", "check"])
def test_render_and_check_list_the_sources_once(tmp_path, monkeypatch, call):
    # 나열은 호스트 트리 전체를 걷고 `git check-ignore` 를 띄움 — 링크 판정과 파싱이 같은
    # 목록을 읽음.
    from scripts.harness import instructions as model
    from tests.harnesses.codex._instructions import _sample

    _sample(tmp_path)
    calls = []
    real = model.sources
    monkeypatch.setattr(model, "sources", lambda host: calls.append(host) or real(host))
    monkeypatch.setattr(codex, "_model", lambda: model)
    getattr(codex, call)(tmp_path)
    assert len(calls) == 1
