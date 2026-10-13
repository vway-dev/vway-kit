# Merge Strategy

> 머지할 때 읽음. 세션 컨텍스트에 주입되지 않음 — 주입되는 것은
> [`risk-tiers.md`](risk-tiers.md) 이고, 그것이 여기를 지목함.

Branch names refer to `vdev-config.branches` keys.

| Branch flow | Strategy | Gate |
|-------------|----------|------|
| `feature/*` → integration | **Rebase onto integration → integration-test gate → Squash** | ✅ enforced |
| `fix/*` / non-`feature/*` → integration | **Rebase** | ✅ `fix/*` only: `--no-ff` blocked |
| integration → staging | **`--no-ff` Merge** | ✅ enforced |
| staging → production | **`--no-ff` Merge** | ✅ enforced |
| `hotfix/*` → production | **Squash** | ✅ enforced |
| production → integration (after release) | **FF**, `--no-ff` only when FF is refused (back-merge) | — |
| production → staging (after release) | **FF only** — skip it when FF is refused (back-merge) | — |
| staging → integration (before a re-promotion) | **FF**, `--no-ff` only when FF is refused (back-merge) | — |

**Gate column** — `vdev-tiers.yaml`'s `merge_strategy`, checked by the PreToolUse hook on
`git merge` and on a `git pull` that names a branch, a rebasing one included (it brings the
branch in with no merge commit, so it reads as carrying no merge flags). ✅ = exit 2 on a
violating flag, `require` and `forbid` alike. `—` = no `merge_strategy` entry.

- The hook judges **every** merge in the command, each against the `git switch` /
  `git checkout` before it: spell the row's flags literally on the `git merge` or `git pull`
  line.
- A merge that names no target branch is judged against the branch of the tree the shell runs
  in — a worktree session merges into its own branch.
- A merge the hook lets through after an internal error, or with row 1's rebase not done,
  carries a notice saying so.
- The merges it lets through without a verdict: [gate-mechanics](gate-mechanics.md#merge-전략-판정의-fail-open).

- Row 2's ✅ names a narrower pattern than its row — enforced for that pattern only; the rest
  is unchecked discipline.
- Row 1's rebase step: **warned, not blocked** — a stale `origin` ref would false-positive.
- Scope: **agent-session (Claude Code or Codex) merges only**. A terminal merge bypasses it,
  like every layer-2 gate.

> `integration → staging` is a `--no-ff` **Merge** for the release, not for the history: a
> forced bump level travels as the `Release-Level:` trailer on the pushed head, and a merge
> commit written for the promotion is the only place it can sit. Rebase and FF make no such
> commit, so the push arrives with an ordinary commit at its head and CI finds no trailer —
> the forced choice silently discarded ([promotion.md](promotion.md) Version
> bump selection).

> `staging → production` is a `--no-ff` **Merge**, not Squash: the merge
> commit's non-`[skip ci]` title is what makes the release workflow fire
> — production then **finalizes** the pending rc (it does not parse
> commits). FF would land staging's `[skip ci]` rc commit as the head and
> skip the release. (`hotfix/*` → production stays Squash — a single
> `fix:` commit lands a non-`[skip ci]` head; with no rc reachable the
> workflow releases directly — the level of its `Release-Level:` trailer, or with none `auto`
> where the tool derives versions and `patch` elsewhere.)

### Merging `feature/*` → integration (integration-test gate)

`feature/*` → integration is NOT a one-shot squash. It is a
three-step gated flow. The integration-test confirmation is a
**human gate** — never skip it, never assume tested.

1. **Rebase first.** Rebase the feature branch onto freshly fetched
   `origin/<integration>` and resolve conflicts on the feature branch
   (keeps integration history linear, no merge commit):

   ```bash
   git fetch origin
   git rebase origin/<integration-branch>
   ```

2. **Ask the user — STOP and wait.** Before merging, ask whether they
   ran the **integration test** (real end-to-end — NOT unit tests,
   which do not satisfy this gate). Merge ONLY if the user explicitly
   confirms they tested. If unconfirmed, do not merge.

   A green `e2e.yml` in CI does not satisfy this gate. That workflow is a
   layer-3 safety net on the promotion branches — it reports **after** a
   merge, never before one, and it blocks nothing. This gate is a human
   confirmation at a different point in a different flow; dropping it
   because a signal appeared downstream is a net loss of coverage.

3. **Squash, then merge.** Choose squash granularity by change size:
   - **Small change** → collapse to **1 commit**.
   - **Larger change** → keep **one commit per category** (e.g. a
     `feat` commit + a separate `test` commit + a `docs` commit),
     rather than one giant blob. Each commit still obeys the 50/72
     rule and carries its own Conventional type.

   ```bash
   git switch <integration>
   git pull --ff-only origin <integration>
   git merge --squash feature/<name>
   ```

### PR workflow

**Not used in vway-kit projects.** Direct merge + push. Never propose
creating a PR; merge straight to the target branch and push.

### Feature branch base

`/vdev` cuts this branch in Phase 2 ([`vdev`](../skills/vdev/SKILL.md)). A **clean** tree branches from
freshly fetched `origin/<integration>`; with **uncommitted changes** it
branches off the current `HEAD` (carrying them) and rebases onto
`origin/<integration>` at merge:

```bash
git fetch origin
git switch -c feature/<name> origin/<integration-branch>
```

Branch names in English.
