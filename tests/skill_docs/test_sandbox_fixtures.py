"""샌드박스 시나리오 픽스처 — 선언한 함정이 실제로 들어 있는가.

픽스처가 이름만 맞고 내용이 비면 eval 은 아무것도 재지 않으면서 녹색이 됨.
모든 스킬은 시나리오로 덮이거나 '닿지 않음'으로 등록되거나 둘 중 하나(XOR).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import skill_sandbox

# `scripts/` must not linger on sys.path after this import: scripts/teams_alert.py (and
# friends) resolve `_vway_paths` with `try: import _vway_paths / except ImportError:
# import scripts._vway_paths` (see that module's docstring) so tests can `import
# scripts.xxx` as a package. A `scripts/` dir left on sys.path for the rest of the
# session flips that try-branch for every test file collected afterward (alphabetically,
# that is most of them), loading `_vway_paths` a SECOND time under a different module
# identity — `scripts.teams_alert._host_root is scripts._vway_paths.host_root` then
# reads False even though both come from the same file.
sys.path.pop(0)


from tests._proc import run_bounded
from tests.skill_docs._discovery import (
    _DISCOVERY_SCENARIOS,
    _expected_cases,
    _scenario_testdir,
    run_discovery,
)
from tests.skill_docs._helpers import (
    REPO,
)


@pytest.mark.parametrize("scenario", _DISCOVERY_SCENARIOS, ids=lambda s: s.name)
def test_sandbox_discovery_slice_matches_the_fixture(scenario, tmp_path: Path):
    """Build the sandbox and run the shipped discovery command on it — the count derived
    from the fixture (via the documented testMatch) must be what the command returns."""
    skill_sandbox.build(scenario, tmp_path)
    testdir = _scenario_testdir(scenario)
    expected = _expected_cases(scenario, testdir)
    found = run_discovery("skills/integration/SKILL.md", tmp_path / scenario.name, testdir)
    assert len(found) == expected, (
        f"{scenario.name}: fixture implies {expected} case(s) under {testdir}, "
        f"shipped command found {found}"
    )


def test_the_discovery_slice_covers_the_playwright_scenarios():
    """A derived parametrisation that silently selects nothing still passes. Pin that the
    selection is non-empty and names the scenarios it is meant to cover."""
    names = {s.name for s in _DISCOVERY_SCENARIOS}
    assert {"custom-testdir", "empty-web", "scaffold-idempotent"} <= names, (
        f"discovery slice stopped covering the core playwright scenarios; got {sorted(names)}"
    )


def test_sandbox_perf_fixture_actually_contains_the_n_plus_one(tmp_path: Path):
    """The perf scenario's judgement is 'flag the N+1'. That is only meaningful if the
    fixture has one — assert the shape so a gutted fixture REDs."""
    target = skill_sandbox.build(skill_sandbox.BY_NAME["perf-n-plus-one"], tmp_path)
    views = (target / "app/views.py").read_text(encoding="utf-8")
    assert "for u in users" in views and "u.profile" in views, "perf fixture lost its N+1"


def test_sandbox_docsync_fixture_actually_has_the_port_drift(tmp_path: Path):
    """The doc-sync scenario's judgement is 'reconcile the port to the SSOT'. Assert the
    fixture disagrees: code says 9090, a doc says something else."""
    target = skill_sandbox.build(skill_sandbox.BY_NAME["doc-sync-drift"], tmp_path)
    server = (target / "app/server.py").read_text(encoding="utf-8")
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "9090" in server and "9090" not in readme, "doc-sync fixture lost its drift"


def test_sandbox_commit_fixture_is_a_repo_with_something_to_commit(tmp_path: Path):
    """The commit scenario's whole reason for existing. Measured 0/25 on an empty temp dir
    (2026-08-28); a hand-replay showed the agent spending its turns learning there is no
    repository. The cause is NOT isolated — the sister repo scored 6/15 on empty dirs the
    same day and this skill's `lost_to` names `vdev` — but committing happens in a
    repository either way, so that is the condition it is measured in. Assert the three
    properties that fix the answer: a repo, a dirty tree, and the unrelated file
    `git add -A` would sweep in."""
    target = skill_sandbox.build(skill_sandbox.BY_NAME["commit-dirty-tree"], tmp_path)
    status = run_bounded(
        # `-z` 는 여기서도 필요 — 없으면 비ASCII 픽스처 경로가 C-인용돼 나와 아래 부분문자열
        # 대조가 거짓이 됨. 레코드 구분만 NUL 로 바뀌고 `XY <경로>` 꼴은 그대로.
        ["git", "status", "--porcelain", "-z"],
        cwd=target,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    assert status.strip(), "commit fixture has a clean tree — there is nothing to commit"
    assert " M app/pricing.py" in status, "the bug fix is no longer an uncommitted change"
    assert "?? tests/" in status, "the new test file is tracked — 'new file' is untested"
    # The trap: an unrelated edit that must NOT reach the commit. Without it the scenario
    # cannot tell `git add -A` from staging by name, which is the guardrail under test.
    assert " M notes.txt" in status, "commit fixture lost its unrelated-file trap"


def test_sandbox_vdev_fixture_has_a_pending_source_change(tmp_path: Path):
    """`이 변경 커밋해줘.` presumes changes to commit; on a clean tree the session reads
    the tree and answers instead of routing. The golden tier is Dev only because a `.py`
    file is among the pending changes, so assert that too — a docs-only diff would make
    the right answer Docs and the scenario's `expect` wrong."""
    target = skill_sandbox.build(skill_sandbox.BY_NAME["vdev-pending-commit"], tmp_path)
    status = run_bounded(
        ["git", "status", "--porcelain", "-z"],
        cwd=target,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    assert " M sbx/cli.py" in status, "the source change is no longer pending"
    assert " M tests/test_cli.py" in status, "the test change is no longer pending"
    # newline="" keeps the fixture LF on Windows; a CRLF write would read as the whole
    # file rewritten to a git without autocrlf.
    assert b"\r\n" not in (target / "sbx/cli.py").read_bytes()


def test_sandbox_wiki_init_fixture_has_both_traps(tmp_path: Path):
    """The wiki-init scenario's judgement is "split what holds two concepts, leave what
    holds one". Both traps have to be in the fixture: backend.md with two H2s
    (stamping front matter on it without splitting passes every structural rule, so
    --verify stays silent) and deploy.md with none (splitting it would be wrong)."""
    target = skill_sandbox.build(skill_sandbox.BY_NAME["wiki-init-migration"], tmp_path)
    backend = (target / "docs/backend.md").read_text(encoding="utf-8")
    deploy = (target / "docs/deploy.md").read_text(encoding="utf-8")
    assert backend.count("\n## ") == 2, "wiki-init fixture lost backend.md's two concepts"
    assert skill_sandbox.WIKI_JWT_CLAIM in backend, "the tracked claim left the fixture"
    assert "\n## " not in deploy, "deploy.md gained an H2 — the zero-H2 branch is untested"


def test_sandbox_wiki_init_fixture_is_a_git_repo_with_the_host_script(tmp_path: Path):
    """Two setup facts the scenario's answer depends on, both silent when broken.

    The graph is built from git's index, so an unseeded directory measures the filesystem
    fallback instead of the documented path. And SKILL.md Step 8 runs wiki_graph.py by its
    literal host path — /vdev-init is what puts it there on a real host, so without the
    copy every run fails that command and the score reflects how well the agent guessed a
    substitute path rather than whether it followed the skill."""
    target = skill_sandbox.build(skill_sandbox.BY_NAME["wiki-init-migration"], tmp_path)
    # NUL 로 끊음 — 개행으로 끊으면 공백 든 경로가 쪼개지고 비ASCII 경로는 C-인용된 채로 와,
    # 그 이름의 픽스처가 생기는 날 `rel in tracked` 가 거짓이 됨.
    raw = run_bounded(
        ["git", "ls-files", "-z"],
        cwd=target,
        text=True,
        # `-z` 는 C-인용 없이 원시 UTF-8 을 냄 — cp949 가 기본인 호스트에서 인코딩을 안 적으면
        # 한글 이름 픽스처가 생기는 날 그 이름을 못 읽음(Invariant 2). `replace` 는 UTF-8 아닌
        # 이름 하나가 디코드 예외로 이 검사를 통째로 끝내지 않게 — 그 이름만 깨진 채 대조가 이어짐.
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    tracked = [rel for rel in raw.split("\0") if rel]
    assert "docs/backend.md" in tracked, "fixture is not a seeded git repo — index is empty"
    host_scripts = ".claude/vway-kit/scripts"
    for rel in (f"{host_scripts}/wiki_graph.py", f"{host_scripts}/_vway_paths.py"):
        assert (target / rel).is_file(), f"{rel} missing — Step 8's command cannot run"
        assert rel in tracked, f"{rel} untracked"


def test_sandbox_git_seed_failure_warns_instead_of_killing_the_run(tmp_path, monkeypatch, capsys):
    """`main()` builds every scenario before printing any prompt, so an exception out of the
    git block would leave `--all` with 11 fixtures on disk and zero prompts — on a machine
    with no git, the whole tool stops working. It must warn and keep going. The warning has
    to say the fixture is invalid, not merely that something failed: an unseeded fixture
    measures the filesystem fallback rather than the skill."""

    def _no_git(cmd, *a, **kw):
        raise FileNotFoundError(2, "git not found")

    monkeypatch.setattr(skill_sandbox.subprocess, "run", _no_git)
    target = skill_sandbox.build(skill_sandbox.BY_NAME["wiki-init-migration"], tmp_path)
    assert (target / "docs/backend.md").is_file(), "the fixture itself must still be built"
    err = capsys.readouterr().err
    assert "wiki-init-migration" in err and "무효" in err, f"warning not actionable: {err!r}"


def test_every_skill_is_covered_by_a_scenario_or_registered_out_of_reach():
    """The honest form of "test all skills": every skills/*/ is either covered by ≥1
    judgement scenario or listed in OUT_OF_REACH with a reason. Neither (or both) fails —
    so a new skill forces a coverage decision instead of a silent gap."""
    scenario_skills = {s.skill for s in skill_sandbox.SCENARIOS}
    registered = set(skill_sandbox.OUT_OF_REACH)
    for skill_dir in sorted(REPO.glob("skills/*/")):
        name = skill_dir.name
        covered = name in scenario_skills
        listed = name in registered
        assert covered != listed, (
            f"{name}: must be EITHER covered by a scenario OR in OUT_OF_REACH, not "
            f"{'both' if covered and listed else 'neither'}"
        )


def test_the_coverage_registry_names_only_skills_that_exist():
    """The sibling direction: registry → skills.

    The test above walks `skills/*/`, so it only ever notices a skill with no entry. A
    skill DELETED or RENAMED leaves its `OUT_OF_REACH` entry (or a `SCENARIO.skill`)
    pointing at nothing, and every assertion above still passes — the registry quietly
    describes a product that no longer exists, and the next reader trusts it. Kept
    separate rather than folded in because the failure it reports is a different one:
    that test names the uncovered skill, this one names the stale entry."""
    existing = {d.name for d in REPO.glob("skills/*/")}
    stale_registered = sorted(set(skill_sandbox.OUT_OF_REACH) - existing)
    assert not stale_registered, (
        f"OUT_OF_REACH lists skill(s) that no longer exist: {stale_registered} — delete "
        f"the entries or restore the skills"
    )
    dangling = sorted({s.skill for s in skill_sandbox.SCENARIOS} - existing)
    assert not dangling, (
        f"scenario(s) claim to cover skill(s) that no longer exist: {dangling} — the "
        f"fixtures test nothing shipped"
    )
