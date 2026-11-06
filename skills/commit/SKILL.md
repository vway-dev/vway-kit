---
name: commit
description: "Use when a commit message has to be written or a commit issued — the Conventional Commits type, subject, body, staging, or a subject that is too long. A freehand message misses the 50/72 limit and the rule that a consumer-facing `.md` is `feat`/`fix`, never `docs`/`chore`. It never stands in for /vdev on a development request."
argument-hint: "[tier · what changed]"
---

# Commit — author and issue one commit

**Source of truth**: [`commit-discipline.md`](../../rules/commit-discipline.md) owns the
message format, the type-to-version table, and the language rule. Nothing injects it — read it
before Step 1. This skill does not restate it; it is the procedure that applies it to one
concrete commit.

## Input

- **$ARGUMENTS** — the tier and a hint at what changed. Everything else is derivable: with
  no arguments, read `git status` and the diff.

## Host commit guide (optional, and it wins on stack facts)

`vdev-config.commit_guide` names the host's own commit/versioning document — `/harness-init`
generates one at `docs/operations/commit-versioning-guide.md`. When that file exists, read it
and take its **project-specific facts** over this skill's generic ones: the scope vocabulary
this repo uses, its 0.x policy, and whether its release tool derives the bump from
the commit types at all — with one that does not, the type this commit carries moves no
version and the level comes from the staging `Release-Level:` trailer instead. Its remaining
subject — which files carry the version, how the changelog is filtered — belongs to the release
CI, not to writing a commit.

```bash
guide=$(python3 -X utf8 -c "import pathlib,yaml
p = pathlib.Path('.claude/vway-kit/config/vdev-config.yaml')
print((yaml.safe_load(p.read_text(encoding='utf-8')) or {}).get('commit_guide', '') if p.exists() else '')" 2>/dev/null)
if [ -n "$guide" ] && [ -f "$guide" ]; then cat "$guide"; else echo "no host guide"; fi
```

No config, no slot, or no such file → `no host guide`, which is a normal answer, not a
failure: `commit-discipline.md` alone then governs. The `if` is what makes it one — a `&&` chain
exits 1 on the common no-config path and reads as a broken step. The host guide never
relaxes the format either way: the 50/72 rule and the type table stay as written there.

## Step 1 — Stage only what this commit is about

```bash
git -c core.quotePath=false status --short
```

Stage the affected paths by name. Never `git add -A` or `git add .` — one unrelated file swept
in makes the subject a lie about the diff, and the gate reads the same staged set you do.
`.claude/vway-kit/.vdev/` is gitignored evidence; it never belongs in a commit.

A commit finishing an **open merge** has nothing to select here: `git merge --no-ff --no-commit`
already staged the whole merged set, `git add` only adds to that, and git refuses a
`git commit <pathspec>` mid-merge. Add only what a gate demanded on top — a rebuilt `graph.yaml`.

## Step 2 — Pick the type

The type-to-version table in `commit-discipline.md` decides. Two traps cost a release when
missed:

- **A consumer-facing `.md` change is `feat` or `fix`, never `docs`.** `docs` and `chore` do not
  bump the version, so they never propagate to a consumer. Only developer-only docs stay `docs`.
- **A squash merge carries the highest-priority type** among the commits it bundles.

## Step 3 — Draft

`type(scope): description`, a blank line, `-` bullets one sentence each, a blank line, footers.
Scope comes from the host guide's vocabulary when it has one, otherwise the module or area the
diff touches. The body says what and why; the commit *is* the history entry, so it carries no
account of earlier rounds of the same work.

## Step 4 — Verify, then issue

One block: a heredoc cannot survive into a second one, and a check the agent runs *after*
committing is a check that changed nothing.

```bash
msg=$(cat <<'EOF'
<type>(<scope>): <subject, replacing this whole heredoc>

- <what changed, and the reason it had to>
EOF
)
python3 -c 'import sys
t = sys.argv[1].splitlines()
sub = t[0] if t else ""
is_merge = sub.startswith("Merge")
bad = ["the heredoc is still the template"] if not t or "<" in sub else []
bad += [f"subject is {len(sub)} chars > 50"] if len(sub) > 50 and not is_merge else []
bad += [f"line {n} is {len(x)} chars > 72" for n, x in enumerate(t[1:], 2) if len(x) > 72]
if bad:
    sys.exit("REWRITE — " + "; ".join(bad))' "$msg"   && printf '%s
' "$msg" | git commit -F -
```

From a **worktree**, change only that last line of the same block, spelling the path out:
`| git -C /absolute/path/to/worktree commit -F -`, **quoted** if it holds a space — a bare
space ends the token and the gate then reads the line as "not a commit", skipping every gate
behind it. It stays inside the one block — `$msg` is a shell variable and a second ```bash
call is a fresh shell where it is empty, which would send git an empty message.

Two literal forms rather than one line that builds the `-C` from a variable. The commit gate
matches the command **text**, before the shell expands anything: its invocation grammar reads
what sits between `git` and the subcommand as flags, each starting with `-` and taking at most
one argument, so a `git ${...} commit` reads as *not a commit*, `--classify` says neither, the
hook exits 0, and every gate behind it — unclassified-commit blocking, the `.done` markers,
the module pre-checks, the wiki check — is skipped in silence. The same read is what finds the
`git -C` naming the worktree, so it finds none either. Both failures are the incident CLAUDE.md
Invariant 7 exists to prevent, and a run that bypasses the gate looks exactly like a run that
passed it.

Three things block here, all in the one block on purpose. A template subject still carrying
`<` aborts — left runnable it would pass the length check, satisfy gitlint, and land as a real
commit, and this binds a `Merge` subject too. Over 50 means rewrite the subject — except a
subject beginning with capital `Merge`, already exempt from the 50-char and type checks by
[`promotion.md`](../../rules/promotion.md) Merge commit messages. Everywhere else the limit
stands, and a non-ASCII character counts as one, which is what Python's `len` already measures.
The 72-char body limit binds a `Merge` subject's body the same as any other.

The commit prompt itself is deliberately left unapproved — it is the mechanical backstop behind
the tier gate.

## Step 5 — Release commits only: the `Release-Level` trailer

Two commits take one, each only when `/release-commit` hands a level: the **staging** promotion
commit (the release workflow reads it off the pushed head to cut the rc) and a **hotfix squash**
onto production (no rc is reachable there, so the workflow releases the level it names —
[`hotfix.md`](../release-commit/references/hotfix.md)). The body ends with a blank line and
`Release-Level: <level>`, the level taken verbatim from `$ARGUMENTS`
([`promotion.md`](../../rules/promotion.md) Version bump selection). No level in the arguments
means no trailer — `auto`, a hotfix left at patch, or a host whose workflow reads none.

Never pick the level here, and never add the trailer on your own: it is the user's answer to
`/release-commit`, and a trailer the workflow cannot use fails the run and cuts no rc. The
**production promotion merge** never takes one — finalize is deterministic and ignores it. No
release commit carries `[skip ci]`: the push is what fires the release.

## Guardrails

1. **Never `--no-verify`.** A blocked commit is the gate working. Read its reason and satisfy
   it; bypassing it is what the gate exists to prevent.
2. **One commit, one subject.** If the staged set needs two subjects, it is two commits.
3. **This skill never issues the merge.** The Merge strategy belongs to `/vdev` for the
   day-to-day rows and to `/release-commit` for a promotion, several of them hook-enforced. A
   promotion reaches Step 4 with its merge already open (`--no-ff --no-commit`), so the commit
   issued there is what writes that merge commit — do not abort it to write a plain one.
4. **Never spell a CI-skip marker the message does not mean.** GitHub reads `[skip ci]`
   anywhere in the pushed head commit's message, body included, and creates **no workflow
   run** for that push: every CI layer is off for the change, and the absence of a run
   reports as nothing at all. So a message that has to *discuss* one names it in prose —
   "a skip-ci marker". No message this skill writes carries the literal: a release commit's
   push is what fires the release (Step 5), and the `chore(release)` commits that do carry it
   are the release workflow's own.
