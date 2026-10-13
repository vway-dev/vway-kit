---
name: vdev-uninstall
description: Remove vway-kit's host-side wiring from a repo — the inverse of /vdev-init. Run BEFORE /plugin uninstall.
disable-model-invocation: true
---

# Vdev-Uninstall — Remove host-side wiring

Undo what [`/vdev-init`](../vdev-init/SKILL.md) installed in the host repo.
`/plugin uninstall vway-kit` removes only the **cache** (the plugin outside the
host); everything vdev-init wrote **into** the host repo stays unless removed here.

> **Run this BEFORE `/plugin uninstall`.** The cleanup runs the plugin's
> `vdev_init_setup.py --uninstall`, which is reachable only while the plugin is
> still installed (`${CLAUDE_PLUGIN_ROOT}`). If the plugin is already gone, fall
> back to the manual steps in
> [update-and-removal.md](../../docs/usage/update-and-removal.md#수동-정리-플러그인을-먼저-지웠을-때).

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Path conventions

```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
PLUGIN="${CLAUDE_PLUGIN_ROOT}"
```

## Execution

1. **Confirm (destructive)** — deleting `.claude/vway-kit/` removes host-owned
   files too: `vdev-config.yaml`, **webhooks**
   (`teams-webhooks.json` is git-tracked/team-shared), the **host's own templates** under
   `templates/` with any edits made to them, and gate evidence. List what will be removed —
   saying the templates can be copied out first — and ask the user (structured choice) to
   confirm (default: **no**). Stop if declined. (Teamer 자격증명은 OS keyring(`vway-kit-teamer`)에
   있어 파일 삭제로는 미삭제 — 필요하면 사용자가 키체인에서 직접 제거.)

2. **Run the cleanup** (idempotent — match-then-skip, the inverse of `/vdev-init`):
   ```bash
   python3 "${PLUGIN}/scripts/vdev_init_setup.py" --uninstall
   ```
   **Read its exit status before relaying.** A non-zero exit means a gate hook is
   still in `.claude/settings.json` or `.codex/hooks.json` while the scripts it names have
   been deleted —
   every Bash command in that host then runs a file that is not there. Relay the closing
   line verbatim and tell the user to remove the hook by hand; do not call the cleanup
   done. Relay its report. It:
   - **Unregisters** the commit gate and the `vway` marketplace from
     `.claude/settings.json` (preserves any other hooks), and deletes the file when nothing
     else is left in it.
   - **Unregisters** the Codex commit gate from `.codex/hooks.json` whenever that file
     exists, whatever `vdev-config.harnesses` lists now (preserves the host's own Codex
     hooks, and deletes the file only when nothing else is left in it). The closing line
     names which file still holds a gate hook — `settings.json`, `.codex/hooks.json`, or
     both, or that `.codex/hooks.json` could not be checked — and a non-zero
     exit covers each.
   - **Strips** the managed block from the root `AGENTS.md`, whether or not `codex` is
     still listed under `harnesses`.
   - **Reports** the `recoble-*` MCP servers registered for this repo in `~/.claude.json`
     under a `[Recoble MCP]` heading and prints `claude mcp remove <key>` for each, and
     names any left in the repo's own `.mcp.json` by an install old enough to have written
     one. Neither is **deleted** — the first file is Claude Code's, the second may hold
     servers the user added by hand, and nothing tells them apart.
   - **Strips** the vway-kit `.gitignore` lines — keeping `teamer_account.md` and
     `.teams-webhooks.local.json`, which may still guard a secret — and the `CLAUDE.md`
     `vway-kit:teams` managed block.
   - **Deletes** `.claude/vway-kit/` (scripts, config, evidence, webhooks, and the
     host's own templates — that path is outside gitignore, so the report names them and
     git restores whatever was committed; a seeded file never committed is gone) and
     `.claude/rules/vway-kit/` (the plugin's rules an older `/vdev-init` may have copied in —
     the host's own rules stay).

3. **Relay the manual follow-ups** the script prints (it does **not** do these —
   they're destructive to user-owned files):
   - `.pre-commit-config.yaml`'s `teams-notify-push` / static-analysis hooks are
     left in place (team customizations / comments). Remove by hand if desired.
   - The workflows it names under `.github/workflows/`, read from the files there:
     - the ones calling the deleted `.claude/vway-kit/` **without a guard fail** —
       `wiki-verify.yml` on every push, and `release.yml` from every release tool but
       `semantic-release` on each push to a release branch;
     - `doc-style.yml` and `srs-verify.yml` guard their script and exit 0, verifying
       nothing while each still spends a runner on every push;
     - self-contained renders (`branch-naming.yml`, `entropy-check.yml`, `unit-test.yml`,
       `api-contract.yml`, `e2e.yml`, `deploy*.yml`, a `semantic-release` `release.yml`)
       keep running and costing runner minutes.
     Remove what is no longer wanted by hand.
     Deleting `deploy*.yml` also means deleting the deploy job in `release.yml` — left
     in place it calls the missing `deploy.yml` and the release fails. Before cleanup,
     `vdev-config.deploy.enable: false` and a `/vdev-init` re-run remove that wiring.
   - Disable the installed git hooks:
     `pre-commit uninstall --hook-type pre-commit --hook-type commit-msg --hook-type pre-push`.
   - Commit what the run changed — it names each file and directory it touched.

4. After cleanup, the user can `/plugin uninstall vway-kit` to remove the cached
   plugin.
