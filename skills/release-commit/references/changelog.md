# The stable changelog section

> Read at [`SKILL.md`](../SKILL.md) Release item 5, with the production merge open and its commit
> not yet written.

The release workflow replaces a stable release's notes with the `## vX.Y.Z` section of
`CHANGELOG.md` when one exists. Without it the notes are whatever the tool generated: the rc
sections repeated as they were cut, or GitHub's raw commit list — and after a re-promotion that
raised the base, the abandoned rc's commits are missing from them. This step writes that
section: a summary, not a concatenation.

**1. Read what the release folds in.**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/changelog_section.py" pending
```

The first line, `since: vA.B.C`, is the last stable tag. Every rc section above it follows, a
series a re-promotion abandoned included.

Then read the commits themselves — the authority, and on a host whose release tool writes no
changelog the only input. Write `vA.B.C` from the `since:` line:

```bash
git -c core.quotePath=false log --no-merges --format='- %h %s%n%b' vA.B.C..origin/<staging>
```

**2. Draft the section body.**

- Group under the headings the file already uses — `### Breaking Changes`, `### Features`,
  `### Bug Fixes`, `### Performance Improvements` on a PSR host — and only the groups that have
  entries.
- One bullet per change a consumer notices: `- **scope**: what changed`. Commits fixing the same
  thing become one bullet. A change and its revert both drop. A fix to a feature this same
  release introduces folds into that feature's bullet.
- Leave out what the host's changelog configuration excludes — a PSR host's
  `exclude_commit_patterns` — and every `chore(release)` commit; with no such list, leave out
  `chore`, `ci`, `test`, `refactor`, `style` and `build`.
- The fact in force, in the language the changelog is already written in. No heading line: the
  script writes it.

**3. Show the draft to the user** — ask the user (structured choice): use it, or edit it.
Consumers read this text; nothing is written before the answer.

**4. Fold it in.** Write the approved body to `.claude/vway-kit/.vdev/release-notes.md`, then,
with `X.Y.Z` the base of Release item 1's `pending:` rc:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/changelog_section.py" fold --version X.Y.Z --body-file .claude/vway-kit/.vdev/release-notes.md
git add CHANGELOG.md
```

`fold` removes every rc section `pending` printed, writes one `## vX.Y.Z (date)` section at the
top of the release list — where PSR inserts its next one — and keeps every older section. It
creates `CHANGELOG.md` when there is none. Exit 2 names its reason: `v… 절이 이미 있음` on a
rerun (leave it), or an empty body.

The staged file joins the open merge, so Release item 6's commit carries it.

**Not here:**

- A hotfix folds nothing ([`hotfix.md`](hotfix.md)). A host whose tool writes the stable section
  itself — PSR's `auto` path — gets that one, and the release step reads it.
- A Node host running `@semantic-release/changelog` writes its own section above this one, and
  the release step reads the first. Tell the user once: dropping the plugin keeps this summary as
  the release notes.
