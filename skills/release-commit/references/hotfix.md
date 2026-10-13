# Hotfix (hotfix/* → production)

The `hotfix` argument of [`release-commit`](../SKILL.md). A hotfix reaches production without
staging and still ships a release: the push with no reachable rc takes the release workflow's
direct path.

**1. Record the baseline before merging** — production's current tag, which item 4 compares
against, and the `pending:` line, which item 5 reads:

```bash
git fetch origin
git fetch --tags origin
git describe --tags --abbrev=0 origin/<production>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_version.py" state
```

Write both into the run's output literally — each Bash call is a fresh shell.

**2. Security review, then the marker.** The squash commit lands on production, so the commit
hook gates it as Release: `/security-review` over the hotfix branch's changes, then

```bash
mkdir -p .claude/vway-kit/.vdev
touch .claude/vway-kit/.vdev/security.done
```

**3. Squash the hotfix into production** — [merge-strategy.md](../../../rules/merge-strategy.md)
blocks this merge without `--squash`:

```bash
git switch <production>
git merge --ff-only origin/<production>
git merge --squash hotfix/<name>
```

Invoke skill `commit` to write it as a `fix:` commit — never `[skip ci]`: this push is what fires
the release. Its level is a patch unless the user asks otherwise; then pass it, and the body ends
with `Release-Level: minor` or `major`. Then push:

```bash
git push origin <production>
```

**4. Confirm the release** — same check as
[Staging item 8](../SKILL.md#staging-integration--staging) against item 1's tag, except the new tag
has to be a stable `vX.Y.Z`.

A hotfix folds no changelog section ([`changelog.md`](changelog.md) is Release's): with none in
the file the release keeps the notes its tool generated.

**5. Close the cycle** — [End state](../SKILL.md#end-state)'s back-merge and marker clearing. When
item 1 printed a pending rc whose base this hotfix reached or passed, that rc can no longer ship as
itself — the release it triggers is a failed run or a plain patch, never the level that was chosen
([promotion.md](../../../rules/promotion.md)). Tell the user the next Staging promotion must choose
`patch` or higher, which `state` now shows.
