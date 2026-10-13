"""SKILL.md 앞머리와 링크 — 스펙에 있는 필드만, 끊어진 링크 없이.

`description` 은 목록 표시 상한을 넘으면 잘려서 호출 판정을 잃음. 스펙 밖 필드는
오타이거나 command 시절 잔재라 아무 일도 하지 않음 — 조용히 죽는 설정.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

# `scripts/` must not linger on sys.path after this import: scripts/teams_alert.py (and
# friends) resolve `_vway_paths` with `try: import _vway_paths / except ImportError:
# import scripts._vway_paths` (see that module's docstring) so tests can `import
# scripts.xxx` as a package. A `scripts/` dir left on sys.path for the rest of the
# session flips that try-branch for every test file collected afterward (alphabetically,
# that is most of them), loading `_vway_paths` a SECOND time under a different module
# identity — `scripts.teams_alert._host_root is scripts._vway_paths.host_root` then
# reads False even though both come from the same file.
sys.path.pop(0)


from tests.skill_docs._helpers import (
    _MD_LINK,
    _TRIGGER,
    DESCRIPTION_CAP,
    REFERENCE_IDS,
    REFERENCES,
    SKILL_IDS,
    SKILL_LINE_CAP,
    SKILLS,
    SPEC_FIELDS,
    _dead_links,
    bash_blocks,
    body,
    frontmatter,
    tool_declaration_problem,
)


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_frontmatter_parses_and_only_uses_spec_fields(skill: Path):
    data = frontmatter(skill)
    unknown = set(data) - SPEC_FIELDS
    assert not unknown, f"{skill.parent.name}: fields absent from the official spec: {unknown}"


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_name_and_description_are_present_and_named_for_the_directory(skill: Path):
    data = frontmatter(skill)
    assert isinstance(data.get("description"), str) and data["description"].strip()
    assert data.get("name") == skill.parent.name, (
        f"name={data.get('name')!r} but the directory (and therefore the /command) "
        f"is {skill.parent.name!r}"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_description_fits_the_listing_cap(skill: Path):
    data = frontmatter(skill)
    combined = len(data["description"]) + len(str(data.get("when_to_use", "")))
    assert combined <= DESCRIPTION_CAP, f"{skill.parent.name}: {combined} chars > {DESCRIPTION_CAP}"


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_relative_links_resolve(skill: Path):
    dead = _dead_links(body(skill), skill.parent)
    assert not dead, f"{skill.parent.name}: dead link → {dead}"


@pytest.mark.parametrize("ref", REFERENCES, ids=REFERENCE_IDS)
def test_reference_relative_links_resolve(ref: Path):
    dead = _dead_links(ref.read_text(encoding="utf-8"), ref.parent)
    assert not dead, f"{ref.parent.parent.name}/{ref.name}: dead link → {dead}"


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_skill_stays_under_the_line_cap(skill: Path):
    """A SKILL.md loads into context whole, so past ~500 lines it crowds out the work it
    is meant to guide — the detail belongs in references/ (Progressive Disclosure).
    vdev-init sits at 485, so this ceiling is live, not theoretical."""
    lines = len(skill.read_text(encoding="utf-8").splitlines())
    assert lines <= SKILL_LINE_CAP, (
        f"{skill.parent.name}: {lines} lines > {SKILL_LINE_CAP} — move detail into "
        f"references/ (Progressive Disclosure)"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_shipped_commands_have_no_unrunnable_placeholders(skill: Path):
    """A `<placeholder>` in command position runs into an empty result rather than an
    error, so the agent reads a silent zero as a real answer."""
    for block in bash_blocks(body(skill)):
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            m = re.match(r"(find|cat|ls|grep\s+-\w+)\s+[\"']?(<[^>]+>)", stripped)
            assert not m, f"{skill.parent.name}: command reads a placeholder literally → {stripped}"


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_argument_hint_is_justified(skill: Path):
    """`argument-hint` is the autocomplete hint for expected arguments. Two ways it
    misleads: the literal string "(none)" shows verbatim in the / menu (drop the field
    instead), and a hint on a skill that never consumes an argument promises input that
    goes nowhere. vway-kit consumes arguments two valid ways — the `$ARGUMENTS` token
    and a `{named}` placeholder (task-import/task-sync) — so either satisfies the check.
    """
    hint = frontmatter(skill).get("argument-hint")
    if hint is None:
        return
    assert hint != "(none)", (
        f"{skill.parent.name}: drop argument-hint instead of '(none)' — the literal "
        f"string shows in the / autocomplete menu"
    )
    text = body(skill)
    # Bind the check to the argument the hint declares. "does the body contain any
    # {word}" passes on unrelated placeholders like {username}, so a deleted
    # {task_id} would slip through — the exact silent pass this file exists to catch.
    names = re.findall(r"[\[{]([a-z_][a-z0-9_]*)[\]}]", str(hint))
    consumes = "$ARGUMENTS" in text or any(f"{{{name}}}" in text for name in names)
    assert consumes, (
        f"{skill.parent.name}: argument-hint {hint!r} promises an argument the body "
        f"never reads (no $ARGUMENTS token and no {{{'|'.join(names) or 'name'}}} "
        f"placeholder)"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_model_invocable_descriptions_state_when_to_use(skill: Path):
    """A model-invocable description is the only thing deciding whether the skill fires,
    so it must say WHEN to use it, not only what it does. `disable-model-invocation`
    skills are exempt — their description serves the human reading the / menu."""
    data = frontmatter(skill)
    if data.get("disable-model-invocation") is True:
        return
    desc = data["description"]
    assert desc.startswith("MANDATORY") or _TRIGGER.search(desc), (
        f"{skill.parent.name}: description says what the skill does but not when to use "
        f"it — agents cannot decide to load it. Got: {desc[:80]!r}"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_intra_file_section_references_resolve(skill: Path):
    """`§3.1` pointing at a section renumbered away sends the agent nowhere. A `§` on a
    line carrying a same-line markdown link to a `.md` is a cross-file citation, owned by
    the test below; every other `§` — including one on the line after an unrelated `.md`
    link — is checked HERE, not there."""
    text = body(skill)
    headings = {h.rstrip(".") for h in re.findall(r"^#+\s+([\d.]+)", text, re.M)}
    if not headings:
        return
    lines = text.splitlines()
    for line in lines:
        if _MD_LINK.search(line):
            continue
        for ref in re.findall(r"§(\d+(?:\.\d+)?)", line):
            assert ref in headings, (
                f"{skill.parent.name}: §{ref} has no matching heading. Sections: {sorted(headings)}"
            )


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_cross_file_section_references_resolve(skill: Path):
    """`web-playwright.md (§10.7)` when that file stops at §6 sends the agent hunting. A
    citation is attributed to a `.md` link only when both sit on the SAME line — vway-kit
    has no wrapped cross-file citations, and its tables put an unrelated `.md` cell one
    line above a `§` cell, which the sister repo's look-back window mis-attributes."""
    for line in body(skill).splitlines():
        targets = set(re.findall(r"\]\(([^)]+\.md)[^)]*\)", line))
        refs = re.findall(r"§(\d+(?:\.\d+)?)", line)
        if len(targets) != 1 or not refs:
            continue
        target = (skill.parent / targets.pop()).resolve()
        if not target.exists():
            continue  # test_relative_links_resolve owns that failure
        headings = {
            h.rstrip(".")
            for h in re.findall(r"^#+\s+([\d.]+)", target.read_text(encoding="utf-8"), re.M)
        }
        for ref in refs:
            assert ref in headings, (
                f"{skill.parent.name}: cites {target.name} §{ref}, which has {sorted(headings)}"
            )


def test_spec_fields_covers_the_fork_skill_frontmatter():
    """`context: fork` 스킬이 쓰는 네 필드가 허용 집합에 있어야 함.

    `SPEC_FIELDS` 는 공식 레퍼런스를 그대로 옮긴 것이라 적혀 있고, 빠진 필드는 그 스킬을
    통째로 못 싣게 만듦 — 오타가 아니라 실재하는 설정인데 가드가 거절함."""
    fork_fields = {"context", "agent", "background", "model"}
    assert fork_fields <= SPEC_FIELDS, (
        f"fork 스킬 필드 중 {sorted(fork_fields - SPEC_FIELDS)} 가 SPEC_FIELDS 에 없음 — "
        f"공식 레퍼런스에 있는 필드를 가드가 오타로 읽음"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=SKILL_IDS)
def test_no_tool_is_both_allowed_and_disallowed(skill: Path):
    """허용과 금지에 함께 적힌 도구는 **제거**됨 — 저자가 필요하다고 적은 것이 사라짐.

    실패가 조용함: frontmatter 는 그 도구를 쓸 작정이라 말하는데 스킬은 그것을 부르는
    자리에서 아무것도 못 하고 돌아오고, 어느 검사도 그 모순을 안 봄."""
    problem = tool_declaration_problem(frontmatter(skill))
    assert problem is None, f"{skill.parent.name}: {problem}"


def test_the_tool_declaration_guard_rejects_a_real_contradiction():
    """코퍼스가 깨끗하면 위 검사는 공짜로 초록임 — 판정 자체를 여기서 잼."""
    assert tool_declaration_problem({"allowed-tools": "Read, Write"}) is None
    assert tool_declaration_problem({"disallowed-tools": "Bash"}) is None
    assert (
        tool_declaration_problem({"allowed-tools": "Read, Write", "disallowed-tools": "Bash"})
        is None
    )
    assert (
        tool_declaration_problem({"allowed-tools": "Read, Write", "disallowed-tools": "Write"})
        is not None
    )
    assert (
        tool_declaration_problem({"allowed-tools": ["Read"], "disallowed-tools": ["Read"]})
        is not None
    )
    # 이 저장소가 실제로 출하하는 표기 둘 — 공백 구분과 괄호 안 공백(`doc-sync`·
    # `release-commit`). 쉼표로만 쪼개면 여기서 판정이 통째로 빠짐.
    assert (
        tool_declaration_problem({"allowed-tools": "Read Write", "disallowed-tools": "Write"})
        is not None
    )
    assert (
        tool_declaration_problem(
            {"allowed-tools": "Bash(git fetch origin) Read", "disallowed-tools": "Bash(git push)"}
        )
        is None
    )
    assert (
        tool_declaration_problem(
            {
                "allowed-tools": "Bash(git fetch origin)",
                "disallowed-tools": "Bash(git fetch origin)",
            }
        )
        is not None
    )
