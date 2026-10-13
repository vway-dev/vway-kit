"""프롬프트가 전제하는 프로젝트와 그 증거 — 픽스처 대조표.

프롬프트가 '이 저장소의' 무언가를 전제하는데 측정이 그 프로젝트 밖에서 돌면, 모델은
스킬을 안 부른 것이 아니라 부를 수가 없었던 것. 표가 그 모순을 미리 잡음.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from evals.runner import config, session
from scripts import skill_sandbox

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
# freezes into the baseline.
#
# This table is a claim about LANGUAGE, not a restatement of the corpus, and that is what
# stops the test below from being the vacuous one it replaces. Several rows currently match
# nothing (`Next.js`, `Cypress`, `Electron`, `Django`, a component file) precisely because
# those prompts were moved to `fixture: null` or rewritten -- they are the rows that fire if
# the fix is reverted. Each row is (pattern, what it presumes, any-of evidence).
#
# Matched against the fixture's file PATHS and its file CONTENTS together: "does this
# project have pytest" is answered by a test file or by a dependency, and which one is an
# accident of the scenario rather than something a prompt author should have to know.
PRESUPPOSES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (r"pytest", "a Python test suite", ("pytest", "test_", "_test.py", "conftest.py")),
    (r"[Nn]ext\.?js", "a Next.js project", ('"next"',)),
    (r"[Cc]ypress", "a Cypress suite", ("cypress",)),
    (r"[Ee]lectron", "an Electron app", ("electron",)),
    (r"[Vv]ite", "a Vite project", ("vite",)),
    (r"[Rr]eact 앱|React app", "a React project", ("react",)),
    (r"[Pp]laywright", "Playwright installed", ("playwright",)),
    (r"[Dd]jango", "Django installed", ("django", "settings.py", "manage.py")),
    (r"컴포넌트", "a component file", (".jsx", ".tsx", ".vue", ".svelte", "components/")),
    # The one finding 3 turned on: an EXPLAIN plan or a load test needs something running,
    # which no static fixture supplies. `perf-n-plus-one` goes further than not supplying it
    # -- its own `reject` list names "reporting measured latency from static analysis alone"
    # as the wrong answer, so a prompt demanding a plan pushes the agent toward it.
    (
        r"실행계획.{0,6}(떠|뜨)|EXPLAIN|부하.{0,4}(걸|측정)",
        "a running backend or database to execute against",
        ("settings.py", "manage.py", "DATABASES", "docker-compose", "openapi", ".sql"),
    ),
    (
        r"기존 e2e|기존 Playwright|케이스 전부|스펙 전부|스위트에",
        "an existing spec suite",
        (".spec.",),
    ),
    # Concrete referents. A prompt naming a path is asserting it exists, and an agent that
    # cannot find it spends turns before it ever judges whether the skill applies.
    (r"app/server\.py", "app/server.py", ("app/server.py",)),
    (r"app/models\.py", "app/models.py", ("app/models.py",)),
    (r"docs/", "a docs/ directory", ("docs/",)),
    (r"playwright\.config\.ts", "playwright.config.ts", ("playwright.config.ts",)),
    (r"index\.html", "index.html", ("index.html",)),
    (r"README", "a README", ("README",)),
    (r"requirements\.txt", "requirements.txt", ("requirements.txt",)),
    (r"pyproject\.toml", "pyproject.toml", ("pyproject.toml",)),
    (r"app 디렉터리", "an app/ directory", ("app/",)),
    # Git state, which the file-contents blob cannot show. Added after `commit-dirty-tree`
    # shipped three prompts its own fixture refuted -- "the staged change" against an empty
    # index, "squash the last three commits" against a single seed commit, "the .md under
    # rules/" against a project with neither. A prompt that names git state is asserting it
    # the same way a prompt naming a path is.
    (r"스테이징(한|된|해)|staged", "a staged change", ("#git:has-staged",)),
    (
        r"squash|커밋 (세 개|3개|여러 개)|커밋 히스토리를? (정리|재작성)",
        "more than one commit of history",
        ("#git:has-history",),
    ),
    (r"rules/|rules 밑|rules 아래", "a rules/ directory", ("rules/",)),
)

# The mirror image, and the direction that corrupts a score most quietly. A prompt claiming
# a project has NO specs, measured where specs exist, does not merely waste turns: for
# playwright-scaffold it makes scaffolding the CORRECT answer, so `false_fire` rises for a
# reason that has nothing to do with the description being greedy.
PRESUPPOSES_ABSENCE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        r"케이스가 (하나도 없|0개)|spec 파일이 하나도 없|e2e 가 아예 없|no specs yet",
        "no spec files at all",
        (".spec.",),
    ),
    (r"CLAUDE\.md 가 없", "no CLAUDE.md", ("CLAUDE.md",)),
)


def _fixture_evidence(scenario: str, root: Path) -> str:
    """Everything a fixture puts on disk, as one searchable blob of paths plus contents.

    BUILT, not read off `skill_sandbox.SCENARIOS`. The dict is what the scenario intends;
    `build()` is what the session gets, and spec 4.5 is explicit that this check
    is worthless done from the listing ("파일을 열어 확인해야 한다"). Building also covers
    `dirs`, which exist on disk and appear in no file mapping -- `empty-web`'s empty
    `tests/` is exactly such a case and exactly what one prompt is about.
    """
    built = skill_sandbox.build(skill_sandbox.BY_NAME[scenario], root)
    parts: list[str] = []
    for path in sorted(built.rglob("*")):
        rel = path.relative_to(built).as_posix()
        # `.git/` is skipped, not decoded. A `git: True` fixture seeds a real repository,
        # and its object database is binary -- `read_text` raised UnicodeDecodeError the
        # first time such a fixture reached this helper. Nothing in there is a referent a
        # prompt can name either, so including it could only manufacture a match.
        if rel == ".git" or rel.startswith(".git/"):
            continue
        parts.append(rel + ("/" if path.is_dir() else ""))
        if path.is_file():
            # errors="replace": a future fixture may ship a real binary (an image, a
            # wheel), and a decode error there would read as a bug in this test rather
            # than in the fixture. A mangled byte satisfies no pattern in the tables above.
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    # Derived git facts, as text lines the tables above can require. `.git/` itself is
    # skipped (binary, and no prompt names a path inside it), but "is there a repo", "is
    # anything staged" and "is there history to rewrite" ARE things a prompt presupposes --
    # `commit-dirty-tree` shipped with prompts saying "the staged change" and "squash the
    # last three commits" against a fixture with an empty index and one commit, and the
    # table could not see it because the evidence was file contents only.
    if (built / ".git").is_dir():
        parts.append("#git:repo")
        for flag, argv in (
            ("#git:has-staged", ["git", "diff", "--cached", "--name-only"]),
            ("#git:has-history", ["git", "log", "--oneline", "--skip=1"]),
        ):
            try:
                out = subprocess.run(argv, cwd=built, capture_output=True, text=True, check=True)
            except (OSError, subprocess.CalledProcessError):
                continue  # no git here; the build already warned and the fixture is void
            if out.stdout.strip():
                parts.append(flag)
    return "\n".join(parts)


def _arm_kwargs(tmp_path: Path, **overrides: object) -> dict:
    return {
        "skill_id": "vway-kit:vdev",
        "reps": 1,
        "workspace": session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        "binary": "stub-claude",
        "max_turns": config.DEFAULT_MAX_TURNS,
        "model": config.MODEL,
        "label": "happy",
        **overrides,
    }


# --------------------------------------------------------- what ships to consumers
#
# `evals/` is development tooling: a prompt corpus, a committed baseline, and a runner that
# spends this developer's rate-limit budget. None of it belongs in a consumer's install.


MANIFESTS = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json")


def _manifest_strings(node: object):
    """Every key and string value anywhere in a decoded manifest."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _manifest_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _manifest_strings(item)
    elif isinstance(node, str):
        yield node
