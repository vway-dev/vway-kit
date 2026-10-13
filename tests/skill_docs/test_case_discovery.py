"""Playwright 케이스 탐색 — 세 파일이 같은 명령에 합의하는가.

탐색 명령이 문서마다 다르면 사람이 보는 것과 하네스가 세는 것이 갈림. 이식 가능한
`find` 술어만 쓰고, 채워지지 않은 testdir 은 조용한 0 이 아니라 비영 종료.
"""

import os
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


from tests._proc import run_bounded
from tests.skill_docs._discovery import (
    _EXPECTED_CONSUMER,
    _NON_POSIX_FIND_PREDICATES,
    CASE_DISCOVERY_FILES,
    _bash,
    _discovery_lines,
    _filled,
    case_discovery_command,
    make_project,
    run_discovery,
    shipped_discovery_command,
)


def test_all_three_files_agree_on_the_discovery_command():
    """integration, its reference, and playwright-scaffold each decide what counts as an
    existing case. Disagreement means one of them scaffolds over a real suite."""
    commands = {rel: case_discovery_command(rel) for rel in CASE_DISCOVERY_FILES}
    assert len(set(commands.values())) == 1, f"discovery commands diverge: {commands}"


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_finds_cases_under_a_filled_testdir(rel: str, tmp_path: Path):
    """The regression this file was written for: a suite under a non-default testDir must
    be found once TESTDIR is filled from the config."""
    make_project(tmp_path, "./e2e", ["checkout.spec.ts", "auth.test.tsx"])
    assert len(run_discovery(rel, tmp_path, "./e2e")) == 2


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_ignores_files_that_are_not_playwright_cases(rel: str, tmp_path: Path):
    """Playwright's `testMatch` defaults to `**/*.@(spec|test).?(c|m)[jt]s?(x)`. A broader
    glob counts `notes.spec.md` as a case, and "a case exists" is exactly what stops
    playwright-scaffold generating the starter smoke — so a stray doc file silently
    denies a genuinely empty project its smoke test."""
    make_project(tmp_path, "./e2e", ["notes.spec.md", "readme.test.txt"])
    assert run_discovery(rel, tmp_path, "./e2e") == []


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_matches_every_playwright_extension(rel: str, tmp_path: Path):
    """The narrowed matcher must still accept the full documented extension set —
    narrowing it too far would swing the bug the other way and miss real cases. Plain
    `.js`/`.jsx` are covered explicitly: a JavaScript-only Playwright project is the
    common case, and without them a regression dropping non-TypeScript support would
    read as "0 cases" and get scaffolded over. `.mts`/`.cts` cover the `[cm]ts` branch
    that `.mjs`/`.cjs` alone leave untested."""
    make_project(
        tmp_path,
        "./e2e",
        [
            "a.spec.ts",
            "b.spec.tsx",
            "c.test.mjs",
            "d.spec.cjs",
            "e.spec.js",
            "f.test.jsx",
            "g.test.mts",
            "h.spec.cts",
        ],
    )
    assert len(run_discovery(rel, tmp_path, "./e2e")) == 8


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_finds_a_case_reached_through_a_symlink(rel: str, tmp_path: Path):
    """A symlinked spec is a case Playwright collects, so the matcher must not drop it.

    `-type f` — added to stop a directory NAMED `pages.spec.ts` counting as a case — also
    excluded symlinks, and this is the direction that costs: a shared suite linked into
    `e2e/` read as "0 cases", the exact reading that authorises scaffolding a starter
    smoke over a real suite. `! -type d` keeps the directory out and lets the symlink in.
    """
    make_project(tmp_path, "./e2e", [])
    real = tmp_path / "shared"
    real.mkdir()
    (real / "shared.spec.ts").write_text("// case\n", encoding="utf-8", newline="")
    try:
        os.symlink(Path("..") / "shared" / "shared.spec.ts", tmp_path / "e2e/shared.spec.ts")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"host cannot create symlinks (needs Developer Mode/admin on Windows): {exc}")
    assert len(run_discovery(rel, tmp_path, "./e2e")) == 1, (
        f"{rel}: a symlinked spec was not discovered — a linked-in suite reads as "
        f"'0 cases' and gets scaffolded over"
    )


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_ignores_a_directory_named_like_a_case(rel: str, tmp_path: Path):
    """The other side of the same predicate: a DIRECTORY named `pages.spec.ts` is not a
    case. Pinned so a future widening of `! -type d` cannot swing the bug back — "a case
    exists" is what stops playwright-scaffold generating the starter smoke."""
    make_project(tmp_path, "./e2e", [])
    (tmp_path / "e2e/pages.spec.ts").mkdir()
    assert run_discovery(rel, tmp_path, "./e2e") == []


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_uses_only_portable_find_predicates(rel: str):
    """The agreement test pins that the three files match each other, not that any of
    them runs on a Mac — three identical GNU-only commands agree perfectly and fail
    identically. Pin portability separately."""
    find_line = _discovery_lines(rel)[3]
    used = [flag for flag in _NON_POSIX_FIND_PREDICATES if f" {flag} " in f"{find_line} "]
    assert not used, (
        f"{rel}: find uses GNU-only predicate(s) {used} — on BSD/macOS find this errors, "
        f"2>/dev/null hides it, and the agent reads the empty result as 'no cases'"
    )


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_signals_a_missing_testdir_as_a_nonzero_exit(rel: str, tmp_path: Path):
    """Pins, against the command AS SHIPPED (consumer included), that an absent testDir
    produces BOTH a non-zero exit AND a `MISSING:` line naming the directory.

    A pipeline's exit status is its LAST stage's, so before the `[ -d ]` guard this held
    for exactly one of the three files: web-playwright (no consumer) exited 1, while
    integration's `| wc -l` printed `0` and exited 0 and playwright-scaffold's `| head -1`
    exited 0. "Config points nowhere" was indistinguishable from "no cases here" — the
    reading that authorises scaffolding over a real suite. The previous version of this
    test passed only because it ran the consumer-STRIPPED command, certifying a property
    the shipped skills lacked; running the shipped form is the whole point.

    The output assertion is not decoration: the agent acts on what it reads, so the state
    has to be named in stdout, not merely encoded in an exit code it may never inspect."""
    make_project(tmp_path, "./e2e", None)  # config says ./e2e; the directory is absent
    script = _filled(shipped_discovery_command(rel), "./e2e")
    proc = run_bounded(
        [_bash(), "-s"],
        input=script.encode("utf-8"),
        cwd=tmp_path,
        check=False,
    )
    stdout = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode != 0, (
        f"{rel}: a missing testDir must not look like success (rc=0, stdout={stdout!r})"
    )
    assert "MISSING: ./e2e" in stdout, (
        f"{rel}: the missing directory must be NAMED in the output the agent reads — got {stdout!r}"
    )


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_each_file_keeps_its_own_trailing_consumer(rel: str):
    """Each consumer is load-bearing and file-specific: integration reports a COUNT
    (`| wc -l`), playwright-scaffold only asks "is there any case at all?" (`| head -1`),
    and the reference lists the files themselves (no consumer). A swap changes what the
    agent reads without changing what the command finds, so it fails silently."""
    tail = _discovery_lines(rel)[3].split("2>/dev/null", 1)[1].strip()
    assert tail == _EXPECTED_CONSUMER[rel], (
        f"{rel}: trailing consumer is {tail!r}, expected {_EXPECTED_CONSUMER[rel]!r}"
    )


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_reports_empty_for_a_genuinely_empty_project(rel: str, tmp_path: Path):
    """Zero must stay reachable — it is what legitimately triggers the starter smoke."""
    make_project(tmp_path, "./e2e", [])
    assert run_discovery(rel, tmp_path, "./e2e") == []


@pytest.mark.parametrize("rel", CASE_DISCOVERY_FILES, ids=lambda r: Path(r).parent.name)
def test_discovery_hard_errors_when_testdir_is_unfilled(rel: str, tmp_path: Path):
    """vway-kit's contract: an unfilled `TESTDIR=` must exit non-zero, never fall back to
    `tests`. The `[ -n "$TESTDIR" ]` guard is what stops a real e2e/ suite reading as
    "0 cases" and being scaffolded over. Run AS SHIPPED, for the same reason as the
    missing-testDir test: a failure mode must be pinned against the real pipeline, since
    the trailing consumer is what decides the exit status the caller sees."""
    make_project(tmp_path, "./e2e", ["checkout.spec.ts"])
    command = shipped_discovery_command(rel)  # left unfilled: TESTDIR=
    proc = run_bounded(
        [_bash(), "-s"],
        input=command.encode("utf-8"),
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode != 0, f"{rel}: unfilled TESTDIR did not hard-error"
