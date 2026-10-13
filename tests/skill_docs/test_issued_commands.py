"""출하 문서가 발행하는 git 명령은 게이트에 닿아야 함.

스킬이 적어 놓은 `git commit`·`git merge` 는 사람이 그대로 실행함. 훅은 셸 확장 **전**
텍스트를 받으므로 플래그는 리터럴로, 공백 든 인자는 따옴표로 적혀 있어야 함 —
역방향 의무.
"""

import re
import sys
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

import scripts._vway_paths as vway_paths

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
    CONTINUED,
    GH_WORKFLOW_RUN,
    GIT_DOC_IDS,
    GIT_DOCS,
    REPO,
    _is_invocation,
    _issued_gh_commands,
    _issued_git_commands,
    _mentions_subcommand,
    _path_listing_commands,
    _spawns_the_gate,
    body,
)


@pytest.mark.parametrize("doc", GIT_DOCS, ids=GIT_DOC_IDS)
def test_the_git_commands_a_shipped_doc_issues_reach_the_gate(doc: Path):
    """The bug this guard exists for shipped once: `git ${WT:+-C "$WT"} commit -F -`.

    The hook matches the command TEXT, before any shell expansion, so every token between
    `git` and the subcommand has to be a literal flag. A variable standing where the flag
    belongs is not an invocation to the one grammar that decides. The command then reads as
    "not a commit": `--classify` says neither, `precommit-runner.sh` exits 0, and every gate
    behind it — the unclassified-commit block, the `.done` markers, the module pre-checks, the
    wiki check, and on a merge the `merge_strategy` verdict — is skipped without a word. A
    variable used as a flag's *argument* is fine; it is the flag that has to be literal.
    CLAUDE.md Invariant 7 states both directions.

    A line continuation is NOT one of these any more: the mask joins the two lines exactly as
    the shell does, so a continued invocation is read whole. No shipped doc currently issues
    one, so this guard has nothing to say about it — `REAL_INVOCATIONS` carries the continued
    form instead, where both layers are measured against it.


    Every shipped doc, not only `commit`: nothing else in the suite reads these commands, so
    the form could regress in any of them while the rest of the suite stayed green — which is
    exactly how it got in.
    """
    where = doc.relative_to(REPO).as_posix()
    for command in _issued_git_commands(doc.read_text(encoding="utf-8")):
        flat = CONTINUED.sub(" ", command)
        # pull 도 — 브랜치를 대는 pull 은 머지라 같은 판정에 닿아야 함.
        for word in ("commit", "merge", "pull"):
            if not _mentions_subcommand(word, flat):
                continue
            assert _is_invocation(word, command), (
                f"{where}: issues {command.strip()!r}, which the gate's one invocation grammar "
                f"does NOT read as a {word} — `--classify` says neither, the hook exits 0 and "
                f"every tier gate is skipped in silence. Spell the flags out; never build "
                f"`git`'s options from a variable — and if this line only NAMES {word} in a "
                f"flag value rather than calling it, move it out of the runnable block instead "
                f"of widening the gate."
            )
            assert _spawns_the_gate(command), (
                f"{where}: issues {command.strip()!r}, which the runner's coarse filter drops "
                f"before it can be judged. The filter must never be narrower than the grammar."
            )


def test_the_guard_above_has_something_to_measure():
    """`GIT_DOCS` is a glob and `_issued_git_commands` is a filter, so the guard is equally
    quiet when it collects nothing. The merge half is the thin one — two documents feed it,
    and unevenly. `skills/release-commit/SKILL.md` issues six; `rules/merge-strategy.md`
    issues one, plus one the collector picks up from prose (`git -C <wt> merge …`, the
    fail-open case its blockquote warns about, matched by the inline `-C` rule). So the
    merge subject survives one of those documents losing its ```bash fences, and this guard
    only bites when both go — which is exactly when the corpus stops describing merges.
    """
    commands = [
        c for doc in GIT_DOCS for c in _issued_git_commands(doc.read_text(encoding="utf-8"))
    ]
    for word in ("commit", "merge"):
        assert any(_mentions_subcommand(word, c) for c in commands), (
            f"no shipped doc issues a `git {word}` the guard can measure any more — the "
            f"{word} half of the self-filter guard is now checking nothing"
        )


QUOTE_PATH_OFF = "core.quotePath=false"


@pytest.mark.parametrize("doc", GIT_DOCS, ids=GIT_DOC_IDS)
def test_a_shipped_doc_that_names_paths_turns_off_c_quoting(doc: Path):
    r"""경로 이름을 출력에 싣는 출하 명령은 `-c core.quotePath=false` 를 달아야 함.

    기본값에서 git 은 비ASCII 경로를 C-인용해(`"\355\225\234…"`) 내보냄. 그것을 받은
    사람·모델은 그 이름의 파일을 **없는 것**으로 읽음 — 리뷰 대상에서 빠지고, 스테이징에서
    빠지고, 티어 분류에서 빠짐. 실패 방향이 전부 "덜 본다" 라서 아무 신호도 안 남김.
    `-z` 가 아닌 이유는 읽는 쪽이 사람이기 때문 — NUL 은 화면에서 사라짐.

    전체 diff 도 대상. `diff --git a/… b/…` 헤더가 그 hunk 가 어느 파일 것인지 대는 유일한
    자리라, 인용되면 뒤의 hunk 들이 이름 없는 변경이 됨."""
    where = doc.relative_to(REPO).as_posix()
    for command in _path_listing_commands(doc.read_text(encoding="utf-8")):
        assert QUOTE_PATH_OFF in command, (
            f"{where}: issues {command!r} — 비ASCII 경로가 C-인용돼 나와 그 파일이 목록에 "
            f"없는 것처럼 읽힘. `git -c {QUOTE_PATH_OFF} …` 로 적을 것."
        )


def test_the_quote_path_guard_has_something_to_measure():
    """위 가드도 glob + 필터라 아무것도 못 걷으면 똑같이 조용함. 세 꼴을 모두 요구하는 이유는
    하나가 산문으로 옮겨져도 나머지가 초록을 유지하기 때문. 셋 중 전체 diff 는 출처가
    `skills/doc-sync/SKILL.md` 하나뿐이라, 그 펜스 하나가 라벨을 잃으면 그 몫이 통째로
    사라짐 — 목록형 둘은 여러 문서가 대므로 그만큼은 덜 취약함."""
    commands = [
        c for doc in GIT_DOCS for c in _path_listing_commands(doc.read_text(encoding="utf-8"))
    ]
    for form in ("--name-only", "ls-files", "diff HEAD"):
        assert any(form in c for c in commands), (
            f"어떤 출하 문서도 `{form}` 로 경로 이름을 내지 않음 — 그 몫이 아무것도 안 잼"
        )


@pytest.mark.parametrize("doc", GIT_DOCS, ids=GIT_DOC_IDS)
def test_no_shipped_doc_issues_a_gh_workflow_run(doc: Path):
    """출하 문서는 `gh workflow run` 을 발행하지 않음 — 릴리스 레벨은 staging 머지 커밋의
    `Release-Level:` 트레일러 하나로 흐름.

    `gh workflow run` 도 웹 Actions 탭도 저장소 **기본 브랜치**를 기본 ref 로 씀 — 이
    저장소들에서 그것은 production 임. dispatch 를 받는 옛 워크플로에서는 ref 없는 실행 하나가
    계획에 없던 프로덕션 릴리스를 발행했음 — 되돌릴 수 없는 실패 모드라 그 채널을 문서가 다시
    꺼내지 않게 막음. 훅은 `git` 만 보므로 이 형태를 지키는 것은 이 가드뿐임.
    """
    where = doc.relative_to(REPO).as_posix()
    issued = [
        c
        for c in _issued_gh_commands(doc.read_text(encoding="utf-8"))
        if GH_WORKFLOW_RUN.search(CONTINUED.sub(" ", c))
    ]
    assert not issued, (
        f"{where}: issues {issued[0].strip()!r} — release levels travel as the staging merge "
        f"commit's Release-Level trailer, and a dispatch defaults to the production branch."
    )


def test_the_grammar_reads_a_quoted_path_as_one_token():
    """A worktree path with a space is the ordinary case on Windows, and `commit` tells the
    agent to write that path out literally. If the option region broke at `"C:/My`, the
    command would read as "not a commit" and following the skill's own instruction would turn
    the whole gate off. The grammar states no opinion about quoting — it reads the mask, where
    a quoted span is already one whitespace-free token — so every one of these is one form.
    """
    hyphenated = {"commit": "commit-graph write", "merge": "merge-base a b"}
    for word, sibling in hyphenated.items():
        assert _is_invocation(word, f'git -C "C:/My Project/wt" {word} -m x')
        assert _is_invocation(word, f"git -C C:/plain/wt {word} -m x")
        # 따옴표 조각과 맨몸 조각이 붙은 셸 단어.
        assert _is_invocation(word, f'git -C "C:/My Project"/wt {word} -m x')
        # 따옴표가 플래그 토큰 안에서 열리는 형태.
        assert _is_invocation(word, f'git --git-dir="C:/My Big Project/.git" {word} -m x')
        # 짝지을 수 없어 보이는 `"` — `'…'` 안이라 리터럴 한 글자임.
        assert _is_invocation(word, f"""git -c a='b"c' {word} -m x""")
        # 온전한 낱말 종결자는 어떤 인용에서도 살아남아야 함.
        assert not _is_invocation(word, f"git {sibling}")
        assert not _is_invocation(word, f'git -C "C:/My Project/wt" {sibling}')
        assert _is_invocation(word, f"git -C 'C:/My Project/wt' {word} -m x")
        # 이 형태들은 전부 러너의 거친 필터도 통과해야 함 — 아니면 판정에 닿지 못함.
        assert _spawns_the_gate(f'git -C "C:/My Project/wt" {word} -m x')


def test_the_commit_skill_keeps_a_worktree_form_the_gate_can_resolve():
    """`--resolve-worktree` reads the same command text the self-filter does, and it looks for
    a literal `git -C <dir>`. Without one the commit lands in the worktree while the gate reads
    the main repo — status, tier marker and module lint all judge the wrong tree.

    Separate from the guard above: that one asks whether the hook fires at all, this one asks
    whether it fires on the right tree.
    """
    text = (REPO / "skills/commit/SKILL.md").read_text(encoding="utf-8")
    commands = [c for c in _issued_git_commands(text) if _mentions_subcommand("commit", c)]
    assert commands, "no `git … commit` command left in the commit skill — it issues nothing"
    worktree = [c for c in commands if "-C" in c]
    assert worktree, "the worktree form is gone — a worktree commit would be gated on the main repo"
    for command in worktree:
        assert vway_paths._parse_git_dash_c(command), (
            f"{command.strip()!r} carries no `git -C <dir>` the gate can parse, so "
            f"--resolve-worktree leaves the gate checking the main repo (Invariant 7)"
        )


def test_the_skill_editing_rule_still_fires_on_skills():
    """`.claude/rules/skill-authoring.md` is path-scoped (paths: skills/**) — that is
    why it costs nothing, and also how it dies silently: a glob that stops matching
    takes the rule out of context without failing anything. A rule takes only `paths`."""
    rule = REPO / ".claude/rules/skill-authoring.md"
    assert rule.exists(), "the skill-editing rule is gone; CLAUDE.md still links it"
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", rule.read_text(encoding="utf-8"), re.DOTALL)
    assert m, "rule has no frontmatter, so it loads unconditionally into every session"
    data = yaml.safe_load(m.group(1))
    assert set(data) == {"paths"}, f"a rule takes only `paths`; got {sorted(data)}"
    targets = [p.relative_to(REPO).as_posix() for p in REPO.glob("skills/**/*.md")]
    for pattern in data["paths"]:
        assert any(fnmatchcase(t, pattern) for t in targets), (
            f"glob {pattern!r} matches no skill file — the rule would never load"
        )


def test_scaffold_keeps_a_ts_signal_beyond_tsconfig():
    """`@playwright/test` ships its own TypeScript, so a TS Playwright project routinely
    has neither tsconfig.json nor a typescript dependency — keying the language on only
    those two drops a .js spec into a .ts suite. vway-kit's Step 2 keeps `@playwright/test`
    as the extra signal; this guards against someone removing it."""
    step = re.search(
        r"^## Step 2 — testDir·언어 감지$(.*?)^---$",
        body(REPO / "skills/playwright-scaffold/SKILL.md"),
        re.M | re.DOTALL,
    )
    assert step, "playwright-scaffold: the testDir/language-detection step was renamed"
    assert "@playwright/test" in step.group(1), (
        "playwright-scaffold decides .ts vs .js without @playwright/test as a signal, so "
        "a TS project with no tsconfig and no typescript dep gets a .js spec"
    )
