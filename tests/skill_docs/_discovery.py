"""Playwright 케이스 탐색 명령 — 출하 문서가 적어 둔 그대로 돌림.

이 명령이 '이 프로젝트에 이미 테스트가 있는가'를 정함. 틀리면 이미 있는 스위트 위에
starter smoke 를 덮어씀. 채워지지 않은 `TESTDIR=` 는 조용한 폴백이 아니라 hard error.
"""

import re
import sys
from pathlib import Path

import pytest

from tests._bash import BASH
from tests._proc import run_bounded
from tests.skill_docs._helpers import REPO

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


# -------------------------------------------------------------------------- behavioural
#
# The case-discovery command decides "does this project already have tests?". A wrong
# answer scaffolds a starter smoke over a suite that already exists. These tests run the
# command the skills ship. vway-kit's shipped shape is a `TESTDIR=` fill-in the
# agent must populate, behind two guards: `[ -n "$TESTDIR" ]` so an *unfilled* run
# hard-errors instead of silently falling back to `tests`, and `[ -d "$TESTDIR" ]` so a
# testDir that does not exist is NAMED rather than collapsing into "0 cases".

CASE_DISCOVERY_FILES = [
    "skills/integration/SKILL.md",
    "skills/integration/references/web-playwright.md",
    "skills/playwright-scaffold/SKILL.md",
]


# The four lines as ONE contiguous, ordered block. Matching them independently and
# reassembling in canonical order would test a command the file does not contain: a
# `[ -d ]` guard relocated to end-of-file — where it guards nothing, because the `find`
# above has already run — still yields four matches that stitch back into a correct-
# looking command. Adjacency is the property that makes "extracted from the shipped
# skill" true rather than "assembled from four lines that happen to be present".
_DISCOVERY_BLOCK = re.compile(
    r"^(TESTDIR=.*)\n"
    r'(\[ -n "\$TESTDIR" \].*)\n'
    r'(\[ -d "\$TESTDIR" \].*)\n'
    r'(find "\$TESTDIR" .*)$',
    re.M,
)


def _discovery_lines(rel: str) -> tuple[str, str, str, str]:
    """The four shipped lines of the case-discovery command, RAW and IN SHIPPED ORDER:
    the `TESTDIR=` fill-in, the `[ -n ]` guard, the `[ -d ]` guard, and the `find`.

    Order and adjacency are load-bearing, not tidiness: each guard only guards what runs
    AFTER it, so a guard that has drifted out of the block is a guard that does nothing.
    Requiring one contiguous match is what makes that drift RED instead of invisible."""
    text = (REPO / rel).read_text(encoding="utf-8")
    m = _DISCOVERY_BLOCK.search(text)
    assert m, (
        f"{rel}: no complete TESTDIR fill-in discovery command found — it needs the "
        f"`TESTDIR=` fill-in, BOTH the `[ -n ]` and `[ -d ]` guards, and the `find`, on "
        f"four ADJACENT lines in that order (a guard outside the block guards nothing)"
    )
    return m.group(1), m.group(2), m.group(3), m.group(4)


def shipped_discovery_command(rel: str) -> str:
    """The command exactly as shipped — trailing consumer and all.

    A pipeline's exit status is its LAST stage's, so the consumer decides what a failing
    `find` looks like to the agent. Any test about a FAILURE mode must run this, not the
    normalized form, or it certifies a property the shipped skill does not have."""
    return "\n".join(_discovery_lines(rel))


def case_discovery_command(rel: str) -> str:
    """The same four lines NORMALIZED, so the three files' SEMANTIC command can be
    compared.

    Three parts legitimately differ per file and are normalized away: the inline comment
    on `TESTDIR=`, the guidance message inside the `[ -n ]` guard's `echo` (each file
    points the agent at its own prior step — §3.1 / playwright.config / Step 2, so
    unifying them would be *wrong*), and the trailing consumer on `find` (`| wc -l` vs
    `| head -1`, pinned per file by test_each_file_keeps_its_own_trailing_consumer).

    The `[ -d ]` guard is deliberately NOT normalized: it is byte-identical across the
    three files, and passing it through un-normalized is what makes
    test_all_three_files_agree_on_the_discovery_command prove that identity rather than
    assume it. Its message names the directory instead of a per-file next step, so there
    is nothing file-specific to strip.

    What must agree — and what this returns — is the fill-in, both guards, and the `find`
    matcher (what counts as a case)."""
    assign, nonempty, isdir, search = _discovery_lines(rel)
    assign_core = re.sub(r"\s*#.*$", "", assign).rstrip()  # drop comment
    nonempty_core = re.sub(r'echo "[^"]*"', "echo MSG", nonempty)  # drop message
    # Strip only a trailing consumer. Splitting on "|" would cut the `-o` alternation
    # inside the find's `\( ... \)` group and hand bash a syntax error.
    search_core = re.sub(r"\s*\|\s*(wc -l|head -\d+)\s*$", "", search).strip()
    return "\n".join([assign_core, nonempty_core, isdir, search_core])


def _filled(command: str, testdir: str) -> str:
    """Fill the `TESTDIR=` blank so the guarded command searches."""
    return re.sub(r"^TESTDIR=.*$", f'TESTDIR="{testdir}"', command, count=1, flags=re.M)


def make_project(root: Path, test_dir: str, cases: list[str] | None) -> None:
    """`cases=None` means the test directory itself is absent."""
    (root / "playwright.config.ts").write_text(
        f'export default {{ testDir: "{test_dir}" }};\n', encoding="utf-8", newline=""
    )
    if cases is None:
        return
    target = root / test_dir
    target.mkdir(parents=True, exist_ok=True)
    for name in cases:
        (target / name).write_text("// case\n", encoding="utf-8", newline="")


def _bash() -> str:
    """The interpreter these tests run scripts through, or a skip. Named by absolute path
    because `subprocess` on Windows resolves a bare name through CreateProcess, which
    searches System32 before PATH — and `System32\\bash.exe` is the WSL stub, which takes
    the stdin these tests write and never returns (see `tests/_bash.py`)."""
    if BASH is None:
        pytest.skip("no usable bash on this host")
    return BASH


def run_discovery(rel: str, cwd: Path, testdir: str) -> list[str]:
    """Run the skill's own command (TESTDIR filled) in a throwaway project.

    Three Windows hazards, all of them corrupting the run before bash sees the script:
    * the interpreter is named by ABSOLUTE PATH (`tests/_bash.py`), never `"bash"` —
      CreateProcess searches System32 ahead of PATH, so the WSL stub wins and hangs on
      stdin forever;
    * the script goes in on stdin (`bash -s`), not `-c` — CreateProcess escapes embedded
      double quotes and Git Bash reads them back as literal backslashes;
    * it goes in as bytes, unchanged — a text-mode newline rewrite (\\n to \\r\\n, as
      subprocess's text mode does on Windows) leaves a stray \\r that bash reads as part
      of the command; `run_bounded` passes input byte for byte.
    """
    script = _filled(case_discovery_command(rel), testdir)
    proc = run_bounded([_bash(), "-s"], input=script.encode("utf-8"), cwd=cwd, check=False)
    stderr = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, f"{rel}: command failed (rc={proc.returncode}) → {stderr}"
    return [ln for ln in proc.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]


# GNU findutils extensions. macOS ships BSD `find`, which ERRORS on these — and the
# shipped `2>/dev/null` swallows the message, so `| wc -l` prints `0` and the agent reads
# "no cases" for a directory full of them: a false green that authorises scaffolding over
# a real suite. These skills run on users' machines, so POSIX-only predicates are the
# contract, not a preference.
_NON_POSIX_FIND_PREDICATES = ("-regextype", "-regex", "-iregex", "-printf", "-iname")


# What each file does with the find's output. The agreement test normalizes these away,
# so without this nothing notices one being dropped or swapped.
_EXPECTED_CONSUMER = {
    "skills/integration/SKILL.md": "| wc -l",
    "skills/integration/references/web-playwright.md": "",
    "skills/playwright-scaffold/SKILL.md": "| head -1",
}


# ---------------------------------------------------------------- deterministic slices
#
# The judgement layer (does the AGENT reason right) is scored by a fresh agent. But each
# sandbox fixture has a deterministic slice a machine can check: build the fixture and
# assert the shipped discovery command returns the case count the scenario is built
# around, or that the fixture has the shape the scenario claims. A broken fixture REDs in
# CI before anyone runs the judgement prompt.

# Expected values are DERIVED from each scenario's own fixture, never hand-listed beside
# the test. A hand-kept table is the same duplicate these tests exist to catch: add a spec
# file to a scenario and the table silently disagrees with the fixture it claims to
# describe. Deriving also makes the comparison meaningful rather than circular — the
# expected count comes from Playwright's DOCUMENTED testMatch, while the actual count
# comes from the shipped `find`. If the shipped regex drifts from the documented
# testMatch, the two disagree and this REDs.

_TEST_MATCH = re.compile(r"\.(spec|test)\.(c|m)?[jt]sx?$")


def _scenario_testdir(scenario) -> str:
    """Read testDir out of the scenario's own playwright.config — the same place the
    skill reads it. Playwright's default when the key is absent is `tests`."""
    config = scenario.files.get("playwright.config.ts", "")
    m = re.search(r"""testDir:\s*['"]([^'"]+)['"]""", config)
    return m.group(1) if m else "tests"


def _fixture_prefix(testdir: str) -> str:
    return testdir.lstrip("./").rstrip("/")


def _expected_cases(scenario, testdir: str) -> int:
    prefix = _fixture_prefix(testdir)
    return sum(
        1 for rel in scenario.files if rel.startswith(f"{prefix}/") and _TEST_MATCH.search(rel)
    )


def _testdir_exists_in_fixture(scenario, testdir: str) -> bool:
    prefix = _fixture_prefix(testdir)
    return prefix in [d.rstrip("/") for d in scenario.dirs] or any(
        rel.startswith(f"{prefix}/") for rel in scenario.files
    )


# misconfigured-testdir is deliberately excluded: its config points at a directory the
# fixture does not create, so the shipped command exits non-zero by design. That state is
# pinned by test_discovery_signals_a_missing_testdir_as_a_nonzero_exit; here it would only
# assert the fixture is broken, which is the scenario's whole point.
_DISCOVERY_SCENARIOS = [
    s
    for s in skill_sandbox.SCENARIOS
    if "playwright.config.ts" in s.files and _testdir_exists_in_fixture(s, _scenario_testdir(s))
]
