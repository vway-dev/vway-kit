---
name: vdev
description: MANDATORY first step for ALL development work — invoke BEFORE starting any code change, feature, fix, or free-text dev request (also accepts an ALM task-id like SDAL-0091). Skipping it leaves the commit unclassified and the commit gate blocks it.
argument-hint: "[free-text request | ALM task-id]"
---

# Vdev — Risk-Tiered Workflow Router

Classify the incoming work by risk, confirm the tier, run the matching workflow,
and record gate evidence under `.claude/vway-kit/.vdev/` so the `git commit` hook
enforces the tier's required gates.

**Source of truth**: [`risk-tiers.md`](../../rules/risk-tiers.md) (criteria, skill
gate, gates) and [`vdev-tiers.yaml`](../../vdev-tiers.yaml) (tier→gates the
commit hook enforces). Read them first; do not duplicate their content.

Branch names referenced below come from `vdev-config.branches`
(`integration` / `staging` / `production`). Domain-review items come from
`vdev-config.review_checklist`, per-module pre-checks from `vdev-config.modules`,
and the ALM provider/space from `vdev-config.alm`.

Four tiers, two axes:
- **Day-to-day task** (this command's main job): **Docs** (no code) or
  **Dev** (any code).
- **Promotion** (run when cutting a release): **Staging** (integration → staging)
  and **Release** (staging → production) — see "Promotion" below.

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Input

- **$ARGUMENTS** — the request text. If empty, ask the user what the task is.
- A token shaped like an ALM id (`DEV-0952`) is **text and nothing more**. It does not, on
  its own, make anything talk to an ALM.

## Phase 0 — Resolve the request and the ALM provider

**Preamble — run this first, before anything writes evidence.** The ALM marker
below is the first file to land in `.vdev/`, so the ignore rule has to precede it:

```bash
# 증거 디렉터리가 git 에 절대 노출되지 않게 보장(멱등). /vdev-init 선행 없이도 안전하고,
# 첫 증거 파일을 쓰기 *전에* 무시 규칙을 둬 untracked 노출 창을 닫음. (이미 추적 중인
# 증거는 /vdev-init 의 untrack 단계가 git rm --cached 로 정리.) `tr` 은 CRLF .gitignore 의
# 줄 끝 CR 을 지움 — 남으면 `-x` 가 영영 매치하지 못해 실행마다 줄을 덧붙임.
tr -d '\r' 2>/dev/null < .gitignore | grep -qxF '.claude/vway-kit/.vdev/' || printf '\n.claude/vway-kit/.vdev/\n' >> .gitignore
mkdir -p .claude/vway-kit/.vdev
# 중단된 이전 실행이 남긴 ALM 마커 제거 — 마커는 **이번 실행만** 기술.
# (`.vdev/` 는 성공한 Phase 4 끝에만 지워지므로, 중단된 실행의 마커가 남으면 다음 실행의
# Phase 4 가 이번 요약을 *지난* 항목에 달고 progress:100 으로 닫아 버림.)
rm -f .claude/vway-kit/.vdev/alm
```

Read `vdev-config.alm` and resolve the provider **list** — first match wins, and the
first two narrow a configured list down to the one the request named:

1. The request names Teamer ("Teamer 연동", "티머에 올려줘") → `[teamer]`
2. The request names a Recoble space ("client-a 보드에") → `[recoble]` + that space
3. Otherwise → `alm.provider` (ships as `recoble`); a scalar reads as a one-entry
   list, a list keeps its order. Space = `alm.recoble.default`
4. Drop `none` and anything that is neither `recoble` nor `teamer` from the resulting
   list — but **report a dropped unknown in one line**, since `recobel` is a typo, not a
   decision, and silently losing the ALM step is how it stays one. (`none` is a disabled
   entry, not a provider; treating it as one sends the run down a branch that does not
   exist, so it is dropped without comment.) Nothing left — `provider: none`, an empty
   list, a list that was all `none`, or no `alm` block and no legacy top-level `teamer:`
   → **no ALM step at all**.

A request that names one provider means "to that one", not "to that one as well" —
naming a provider is how a user overrides a `[recoble, teamer]` config for this run.

(Legacy config: a top-level `teamer:` with no `alm:` reads as `provider: teamer`,
`auto: false`.)

**A promotion entry skips the ALM step entirely** (integration → staging /
staging → production — see "Promotion" below): a release cut is not an ALM item
the user asked for, so `alm.auto` does not apply to it. Day-to-day tasks only:

When the resolved list is **non-empty** **and** either `alm.auto` is true or the
request asks for ALM linkage ("이 작업 보드에도 올려줘", "ALM 항목이랑 연결해줘"),
resolve each provider in the list:

- **`recoble` with `layers` declared for that space** → invoke
  [`alm-trace`](../alm-trace/SKILL.md) instead of `task-import`, with the request text
  (free text or an id anchor — `alm-trace` reads either). Check the declaration, not the
  request's wording: a model guessing "does this read like a requirement" turns a false
  positive into an item on the wrong board. Self-contained check:
  ```bash
  SPACE=            # ← 이 실행의 Recoble 스페이스 키 (예: dev3)
  [ -n "${SPACE:-}" ] || { echo "SPACE 미확정 — 스페이스를 먼저 해석하라"; exit 1; }
  python "${CLAUDE_PLUGIN_ROOT}/scripts/alm_layers.py" \
    "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --space "$SPACE"
  ```
  Same guard, same reason as [`alm-trace`](../alm-trace/SKILL.md) step 1 — an unfilled
  `--space` falls back to `alm.recoble.default`, not the space the request named.
  `configured: true` → `alm-trace`. `configured: false` → `task-import` below.
- **Every other provider** (`teamer`, or `recoble` with no `layers`) → invoke skill
  [`task-import`](../task-import/SKILL.md) with the request
  text. It scaffolds the task doc (Content filled; analysis/plan left as placeholders)
  and, on success, writes the `.claude/vway-kit/.vdev/alm` marker —
  [`task-import`](../task-import/SKILL.md) ("Both providers" step 1) is the one place
  that defines its format; do not restate it here. Use the scaffolded doc as the request.

Because the preamble's `rm -f` ran first, a marker seen later in this run was written
**by this run**, regardless of which of the two skills wrote it.

Pass the resolved **list**; each provider runs once, through whichever of the two
skills its declaration selects, and appends one marker line per success. A provider
that fails — in either skill — costs you that provider only; the rest still run.

**ALM never blocks the work.** An unauthenticated MCP server, a missing
workboard, or an unknown space key costs you that provider's step and nothing else —
`task-import`/`alm-trace` report one line per failure and return. Every provider
failing is the same as no ALM: no marker, and Phase 4 skips the sync.

Carry the **resolved request text** forward as *the task* for every later step — the
task Phase 3 hands to `superpowers:using-superpowers`, and the reference for the commit scope.

## Phase 1 — Classify the task (Docs or Dev)

**A promotion is not a day-to-day task.** A request to promote a branch, cut a release
candidate, or release — integration → staging, staging → production, or a finished `hotfix/*`
landing on production — has no tier to classify: the target branch decides it. Invoke skill
`release-commit` (with `hotfix` for the last) and stop here.
The rubric below is the wrong instrument for that ask.

The line is simple: **code, or no code.** Inspect the real change, do not guess:

```bash
git -c core.quotePath=false diff --name-only HEAD                 # already-changed files
git -c core.quotePath=false ls-files --others --exclude-standard  # new files
```

- **No source code** (`.md` / docs / comments / pure config-text only) → **Docs**.
- **Any** change to `.py` / `.js` / `.ts` … (however small), or new feature / DB
  schema / cross-service shared package / business logic·node·workflow·validator /
  dependency change / 2+ services → **Dev**. (Full rubric in
  [`risk-tiers.md`](../../rules/risk-tiers.md).)

Output the verdict — tier, reason, gates (from [`vdev-tiers.yaml`](../../vdev-tiers.yaml)):

```
## Tier Classification
- Tier: DEV
- Reason: changes src/*.py (source code)
- Gates: precommit, review, doc-sync, wiki, doc-style
```

## Phase 2 — Confirm the tier & switch to a work branch (human gate)

Ask the user (structured choice) to confirm the tier, allowing an override. **Do not start
before confirmation.** When uncertain, default one tier up.

**Then ensure you are on a work branch — before writing the marker.** Day-to-day
work (Docs *and* Dev) lives on `feature/*` / `fix/*`, never directly on an
integration/staging/production branch (`vdev-config.branches`):

```bash
cur=$(git branch --show-current)
case "$cur" in
  feature/*|fix/*|hotfix/*) ;;                       # already a work branch — stay (idempotent)
  *)
    # On integration/staging/production → cut a work branch. Prefix follows the
    # Conventional type (feat → feature/, fix → fix/); <slug> from the task, English.
    # Confirm the branch name with the user first.
    if git diff --quiet && git diff --cached --quiet; then
      git fetch origin                                # clean tree → branch off fresh integration
      git switch -c <feature|fix>/<slug> "origin/<integration-branch>"
    else
      git switch -c <feature|fix>/<slug>              # uncommitted changes → carry them off current HEAD
    fi
    ;;
esac
```

Record the tier marker **after** switching, so it binds to the work branch (the
commit gate is branch-bound). When the work lives in a git worktree, the gate reads every
marker from that worktree, while this marker, each `.done` and every relative path below land
in the shell's directory. A worktree inside the project directory: `cd` into it first and stay
there. One outside it: the shell returns to the project directory after each call, so put the
worktree's path in front of every marker path and of `.gitignore` instead.

```bash
# 무시 규칙·디렉터리는 Phase 0 preamble 이 이미 보장했다(멱등이므로 다시 확인해도 무해).
mkdir -p .claude/vway-kit/.vdev
echo "<tier>:$(git branch --show-current)" > .claude/vway-kit/.vdev/tier   # docs | dev
```

**On Codex, the session hooks come first.** The Codex plugin carries no lifecycle hook;
`/vdev-init` registers them in `.codex/hooks.json`. When that file does not name
`vway-kit/hooks/invalidate-gate-markers.sh`, stop and have the user run `$vdev-init`:
without that hook an edit after a review leaves the review's evidence standing, and the
commit passes on it.

## Phase 3 — Dispatch

Record each completed gate as `.claude/vway-kit/.vdev/<gate>.done`. `precommit`
and `security-scan` are **timing buckets** the commit hook runs directly — no
marker. Each executes the `modules[].checks` whose timing matches (`precommit`
→ `every-commit` / changed modules, `security-scan` → `promotion` / all
modules); `checks` accepts arbitrary custom checks beyond the conventional
lint/static/import_lint/test/security keys, as a string or `{run, when}` (see
[`gate-mechanics.md`](../../rules/gate-mechanics.md)). Both are ordinary `gates`
entries; removing one from a tier's list in
[`vdev-tiers.yaml`](../../vdev-tiers.yaml) disables it for that tier. **`wiki`** and
**`doc-style`** are two more runtime gates needing no marker — neither is a timing
bucket; the hook's gate script runs them in-process, `wiki_graph.py --verify` whenever
`vdev-config.wiki` is enabled and the prose check whenever `vdev-config.doc_style` is
(no-op otherwise, and `doc-style` only ever warns). Do **not** `touch
.claude/vway-kit/.vdev/wiki.done` or `doc-style.done`, and do not go looking for a gate
skill for either — none exists; the hook runs both checks itself.

> **Precondition (Dev)** — the `superpowers` plugin must
> be installed. If `superpowers:using-superpowers` is **not** among the available
> skills, **STOP**: tell the user to install it
> (`superpowers@claude-plugins-official`, e.g. via `/plugin`) and re-run `/vdev`.
> Do **not** fall back to manual implementation.

### Docs — no code (`superpowers` OFF)

1. Make the edit directly. Do **not** invoke `superpowers`. precommit not needed
   (no code).
2. Invoke the `doc-sync` skill to harmonize the doc set (index `CLAUDE.md` + per-service docs +
   rule dirs from `vdev-config.doc_sync`; also reconciles code↔doc drift). On pass
   → `touch .claude/vway-kit/.vdev/doc-sync.done`.
3. Commit through the `commit` skill — invoke skill `commit` with the tier and what
   changed; it stages, picks the type, and applies the 50/72 rule (Critical rule 4).
   Then merge **applying the documented Merge strategy** (Critical rule 3 — not a plain
   merge). (The commit hook blocks until `doc-sync.done` exists.)

### Dev — any code (`superpowers` ON)

1. **Load the wiki context first** (skip silently when there is no wiki — both
   commands print nothing and exit 0): name the files you are about to change to
   `python3 .claude/vway-kit/scripts/wiki_graph.py --nodes-for <paths…>`, then
   for each printed id run
   `python3 .claude/vway-kit/scripts/wiki_graph.py --neighbors <id>` and **read
   the documents it lists** before planning. An empty result is a normal answer (the
   code is undocumented) — proceed without it.
   When that produces nothing — no wiki, or no node owns the paths — read
   `docs/sds/README.md` and `docs/srs/README.md` directly if they exist
   ([`harness-rules.md`](../../rules/harness-rules.md) 8 fixes those locations). Neither
   existing is normal — proceed. **Docs tier skips this**: reading a design document to
   change a paragraph is the process-to-risk mismatch the tiers exist to prevent.

2. **Record a new requirement in the SRS first** — skip silently when `docs/srs/` is
   absent (the command prints nothing and exits 0). This runs only for a **new
   customer requirement**; implementing an existing one, a bug, or a refactor skips it.
   Route with `python3 .claude/vway-kit/scripts/srs_check.py --areas`, then take the
   number from `--next-id docs/srs/<area>.md --kind FR` and add the FR to that file, plus
   a `C-NNN` in `docs/srs/README.md` (`--next-id docs/srs/README.md --kind C`) when the
   request names a customer need the SRS does not yet carry. **You judge two things
   only** — whether this is a new requirement, and which area it belongs to; the number
   comes from `--next-id`, the integrity from `--verify`. FAIL-OPEN: a failure here warns
   and does not block the commit — the `srs-verify` workflow holds the verdict.

   A **new** area file is the one part of this that is fail-CLOSED — it is a wiki node.
   Where the host has a wiki, give it front matter: `wiki_id` from
   `python3 .claude/vway-kit/scripts/wiki_graph.py --derive-id docs/srs/<area>.md`, a
   `title`, and a `related` edge to the index — its id comes from the **same** derive call
   (`--derive-id docs/srs/README.md`), never from a spelling written here: the wiki root
   decides it. Add that edge only once `docs/srs/README.md` carries front matter of its
   own — an edge to a document that is no node dangles and blocks, where the orphan it
   spares you only warns. Then rebuild with
   `python3 .claude/vway-kit/scripts/wiki_graph.py --build` and stage `graph.yaml`
   alongside it. Skip the rebuild after adding front matter and the commit gate's
   `--verify` blocks, its reason naming the graph rather than this step that wrote
   the file. Skip the front matter itself and the file is not a node at all —
   `--verify` passes silently, so this step is the only guard against that gap.

3. **Invoke skill `superpowers:using-superpowers`** — **injected
   context is a reminder, not execution.** Its full text is already in context
   (the superpowers plugin injects it every SessionStart), but that does NOT mean
   the pipeline ran: it starts only on the actual skill invocation, and from there each
   stage self-chains to the next (`using-superpowers` routes the entry skill by
   task, so do not hardcode brainstorm/debug here). Never open `brainstorming` or any
   other stage yourself before it.
   Feed the resolved request from Phase 0 in as the task. If Phase 0 scaffolded a
   task doc via [`task-import`](../task-import/SKILL.md) or [`alm-trace`](../alm-trace/SKILL.md),
   fill its placeholder sections (Codebase Analysis / Implementation Sequence /
   Implementation Plan) from the imported ALM content as `superpowers` analyzes and plans.
4. Apply the project overlays `superpowers` does not know about:
   - **Spec and plan commit as Docs, the code as Dev** — before the first code edit, commit
     the spec and plan under a `docs:<branch>` marker (`doc-sync` → `commit`), then write
     `dev:<branch>` back. Under `dev` that commit waits on a review of code not yet written.
     The swap is mechanical: the tier stays the one confirmed in Phase 2, so never ask the
     user again whether to keep Dev.
   - **Implementation minimalism** — right after the plan, before writing code,
     climb the reuse-before-build ladder (YAGNI → codebase → stdlib → native →
     dependency → one line → minimum code) and stop at the earliest rung. Detail
     and non-negotiable floor in [`dev-overlays.md`](references/dev-overlays.md).
   - **Record the design before the code** — right after the plan, alongside the reuse
     ladder: a new module, an integration-point contract, or a structural change goes
     into `docs/sds/` now, with its `구현 요구사항` linking the FR anchors it
     satisfies. This is the structure half; `doc-sync` reconciles the rest (sources ·
     stale · orphans) after the code. Placed after `doc-sync` instead, the
     `PostToolUse` hook would delete `doc-sync.done` and `review.done` on that edit, so
     both would have to run again — a loop.
   - **Selective TDD** — only business logic / core nodes / validators / workflow
     orchestration (see [`dev-overlays.md`](references/dev-overlays.md)), not
     every change.
   - **Worker safety** — a change touching a long-running worker process: check it for
     in-flight tasks and get the user's approval before restarting it.
   - **invoke the `doc-sync` skill** (not part of `superpowers`) → `touch .claude/vway-kit/.vdev/doc-sync.done`.
   - **Domain review** — dispatch subagent (general) as an independent review agent
     (separate context; it runs shell commands). `git` is the authority on the
     changed-file list — **every** file is reviewed and the count is reported —
     judged against `vdev-config.review_checklist` (regression, cross-service
     contract, DB/migration & transactions, async task idempotency, API errors),
     plus the callers of every changed public symbol. **Read
     [`dev-overlays.md`](references/dev-overlays.md) Domain review before dispatching**
     and hand the reviewer its ① commands verbatim — without `core.quotePath=false` a
     non-ASCII path reads as absent.
     On pass → `touch .claude/vway-kit/.vdev/review.done`.
     **Every edit after that pass voids it** — the fixes the review itself asked
     for included. A `PostToolUse` hook deletes `review.done` **and**
     `doc-sync.done` the moment a file changes, so passing is a fixpoint: both
     recorded, nothing edited since. A fix therefore re-runs doc-sync and then
     this review, over a recomputed changed-file list. An edit the hook never
     saw (a terminal command, another tool) leaves the markers standing —
     `rm -f .claude/vway-kit/.vdev/review.done .claude/vway-kit/.vdev/doc-sync.done`.
5. Commit through the `commit` skill — invoke skill `commit` with the tier and what
   changed (Critical rule 4) → merge **applying the documented Merge strategy**
   (Critical rule 3 — not a plain merge).
   (The commit hook blocks until `review.done` and `doc-sync.done`.)

## Promotion — Staging (integration → staging) / Release (staging → production)

Promotions are gated at the **commit on the target branch**, so they need no tier marker —
the branch drives it. The procedure itself lives in
[`release-commit`](../release-commit/SKILL.md): which bump-level mechanism the host's release
CI is on, the gates and their markers, the merge shape each promotion takes, and the end state
the branches settle into. Invoke skill `release-commit` rather than restating any of it
here — one fact, one place.

## Phase 4 — Finalize

After the commit/merge completes:

1. **If `.claude/vway-kit/.vdev/alm` exists**, invoke skill [`task-sync`](../task-sync/SKILL.md) — it reads that marker **line by line** for the provider, space and item, and syncs each. The marker can only describe **this** run (Phase 0's preamble deleted any leftover before resolving anything). No marker means no ALM was linked (or every link failed); skip this step.
2. Clear the vdev state:
   ```bash
   rm -rf .claude/vway-kit/.vdev
   ```

This phase runs for the day-to-day workflows only — a promotion never reaches it, so
`release-commit` clears its own evidence markers in its End state instead.

## Critical rules

1. **Record gate evidence honestly** — `touch .claude/vway-kit/.vdev/<gate>.done` only
   after the gate genuinely passes. A marker is a forcing function, not a stamp.
   It is a plain file that outlives the commit that used it, so **a gate whose
   subject changed after it passed is no longer recorded honestly**. The
   `PostToolUse` hook enforces that for `review` and `doc-sync` — any edit
   deletes both — so what is left to you is the edit it cannot see (a terminal
   command, another tool): delete the marker yourself and earn it again.
2. **Worktree commits target the worktree explicitly** — when the work lives in
   a `git worktree` created inside a main-repo session, issue the commit as a
   **single command** `git -C <worktree> commit …` (or `cd <worktree> && git
   commit …`) — the `-C` names the tree in the command itself, even with the shell
   already inside it (Phase 2), since the hook's cwd is only a guess at it. The commit
   gate resolves the committing worktree from this and checks that tree's
   status/lint/tier marker — the markers Phase 2 wrote into the worktree; a bare
   `git commit` after a separate `cd` may leave the gate on the main repo. The `commit` skill issues it
   that way (rule 4), and owns "never `--no-verify`" and "stage only affected files"
   with it.
3. **Apply the documented Merge strategy** — direct commit + merge (no PR), but
   **do not default to a plain / `--no-ff` merge**. For every merge, look up its
   branch-flow row in [`merge-strategy.md`](../../rules/merge-strategy.md) and follow
   it (e.g. `feature/*` → integration is rebase → integration-test gate → squash, NOT a
   `--no-ff` merge). Several rows of **that** table are **enforced by the hook**: a merge
   whose flags violate the strategy is blocked (exit 2), so a plain merge is not merely
   off-procedure — it fails. Commit types and the 50/72 rule are a different file's
   subject — [`commit-discipline.md`](../../rules/commit-discipline.md).
4. **Every commit goes through the `commit` skill** — invoke skill `commit`, which
   owns staging, the type choice, and the 50/72 rule so this skill does not restate
   them. It inherits the pre-commit gate like any other commit: never `--no-verify`.
