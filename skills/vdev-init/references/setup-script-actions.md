# Step 2 — 기계적 셋업 스크립트가 하는 일

[`/vdev-init`](../SKILL.md) Step 2 가 읽음. relay 하는 것은 스크립트 자신이 찍는 리포트이고,
여기 목록은 그 각 줄이 **무엇을 뜻하는지**와 **어느 config 키가 그 단계를 켜는지**임.

스크립트가 멱등으로 수행하는 것:

- **Copies** `vdev_gate_check.py`, `precommit-runner.sh`, `teams_alert.py`,
  `notify-push.sh`, and `check-deps.sh` into `.claude/vway-kit/scripts/`, and the
  `vdev-tiers.yaml` policy into `.claude/vway-kit/config/` (copied — not symlinked —
  so a host `settings.json` hook can run the scripts by `${CLAUDE_PROJECT_DIR}` path;
  the gate resolves `vdev-tiers.yaml` from its sibling `config/` directory). Each copied
  `.sh` is marked executable — pre-commit and the push hook run them as scripts. That
  order is a contract, not a listing: the runner routes on what `vdev_gate_check.py
  --classify` answers, so the answerer is copied first — mid-sync the host then holds
  an old runner and a new script, where the compat alias still answers. The other way
  round leaves a new runner asking an old script, and a runner that reads no verdict
  gates nothing.
- **Removes** `.claude/rules/vway-kit/` if an older `/vdev-init` left it there: Claude Code
  loads every file under `.claude/rules/` in full each session, so the rule reaches a session
  only through the SessionStart hook's short prose summary. A link or junction there is
  removed, never followed, and a parent that resolves outside the host is refused. The
  `AGENTS.md` render skips this directory while it remains.
- **Migrates** any legacy layout into the new classification: root-scattered config →
  `config/` (`vdev-config.yaml`, `teams-webhooks.json`,
  `.teams-webhooks.local.json`), `.claude/.vdev/` → `.claude/vway-kit/.vdev/`, and flat
  scripts → `scripts/`. It also relocates a legacy `scripts/vdev-tiers.yaml` to
  `config/` (the policy moved there; the old copy is removed since `copy_artifacts`
  rewrites `config/`), and translates a carried-over `.vdev/tier` marker's old labels
  (`fast`/`standard`) to the current ones (`docs`/`dev`) in place — left untranslated,
  an unknown tier resolves to no required gates and silently waives the commit gate.
  Idempotent — moves only when the old path exists and nothing already sits at the new
  one (`lexists`, so a dangling link at the destination counts as already-there rather
  than being written through), so fresh installs and already-migrated repos are
  skipped. Skips the **whole** step — no move, no delete, no `config/` mkdir — when
  `.claude/vway-kit/` itself resolves outside the host through a directory link,
  reported `[!]`: letting any part through would carry a host file out of the repo (a
  move) or delete through the link into a same-named file on the far side (the
  flat-script cleanup). When `.claude/vway-kit/` is itself a real directory but a
  subdirectory the step writes into or deletes from — `config/`, `scripts/`, or
  `.vdev/` (the tier-marker rewrite's target) — resolves outside through its own
  directory link, only the move, delete, or write targeting that subdirectory is
  skipped (reported `[!]`); the rest of the step still runs.
- **Registers** the commit gate in `.claude/settings.json` `hooks.PreToolUse` (skips
  if already present; no `if` field — `precommit-runner.sh` filters on stdin, and `--classify` decides what the command is).
  The gate gets an **entry of its own**, matching `Bash` — the only tool a commit arrives
  through. A gate hook found under an entry whose matcher does not fire on Bash is not the
  gate at all, so the hook is moved out into that entry; the host's entry keeps its matcher,
  its other hooks, and itself, since rewriting the matcher would re-point every hook the host
  put there at another tool. Uninstall is the inverse — it takes the gate's **hook**, not the
  entry around it.
- **Registers** the commit gate in `.codex/hooks.json` too when `vdev-config.harnesses`
  names `codex` (Claude is always registered; Codex is opt-in, and an absent key is
  `[claude]`). Copies the Codex wrapper scripts (`harness/codex/gate.sh`·`gate.cmd`) under
  `.claude/vway-kit/scripts/`; the closing verdict checks them with the Claude gate scripts,
  so a missing or damaged wrapper fails the run the same way. Relays Codex's trust notes:
  whether Codex treats the project as trusted (it ignores `.codex/` otherwise), and that the
  hook still needs approving in Codex's `/hooks` before it runs. A `harnesses` value that is
  not a list, or a name it does not support, is reported on the `[커밋 게이트]` block and
  skipped. A host that drops `codex` from the list keeps its Codex hook — the report names it
  and points at `/vdev-uninstall`.
- **Registers** the `vway` marketplace in `.claude/settings.json`
  `extraKnownMarketplaces` with `autoUpdate: true` (adds if absent, repairs the flag
  if present). Third-party marketplaces default to *no* auto-update and the author
  cannot force it via `marketplace.json` (supply-chain boundary) — so the host opts in
  here. Committed → the whole team auto-updates the plugin at startup. (Background
  auto-update authenticates only via a `GITHUB_TOKEN` env var — see the auth note below.)
- **Checks** the static-analysis hooks: **creates** `.pre-commit-config.yaml` from the
  example if absent (the `local` hooks are Python defaults to swap); if it **already
  exists, does NOT auto-merge** (a PyYAML round-trip would strip the team's
  comments/formatting) — instead **detects missing repos/hooks by `id` and reports
  them** for the user to add manually.
- **Appends** missing `.gitignore` lines (the copied scripts' `__pycache__/` among them),
  skipping any already present — including one spelled with a leading `/` or without the
  trailing `/`, which still covers the same path — and **untracks** any `.vdev/` evidence
  already in the git index (`git rm --cached`) — a `.gitignore` line alone never
  un-tracks a file that was committed before the line existed.
- **Checks** private-repo auto-update auth and *suggests* fixes (never applies — these
  are machine-wide changes): a `GITHUB_TOKEN` env var; a **github.com credential helper**
  that feeds that token to git (git does NOT read `GITHUB_TOKEN` itself, so background
  fetch fails without it); and — if a broad `https://github.com/`→SSH `insteadOf` rewrite
  exists — a surgical identity-override exempting the marketplace repo so its HTTPS fetch
  is not rewritten to SSH. See [marketplace-auto-update.md](https://github.com/vway-dev/vway-kit/blob/main/docs/plugins/marketplace-auto-update.md).
- **Renders** `.github/workflows/api-contract.yml` from `vdev-config.contract_test`
  when `enable: true` (creates if absent; if it already exists, **does NOT overwrite** —
  reports for manual review). `.github/workflows/` is GitHub's enforced location — a
  documented exception to the `.claude/vway-kit/` rule. Skips entirely when
  `enable: false` or the section is absent.
- **Renders** `.github/workflows/release.yml` from `vdev-config.versioning.release_tool`
  **only for known templates** (`python-semantic-release` / `semantic-release` /
  `jreleaser` / `gitversion` / `cargo-release` / `sbt-ci-release` — tested baselines).
  Any other tool (Go/C++/etc.) prints `[?] release_tool=... 은 준비된 템플릿이 없습니다`
  instead of guessing — see [SKILL.md](../SKILL.md) Step 2.7.
- **Renders** `.github/workflows/unit-test.yml` from `vdev-config.unit_test` when
  `enable: true` and `jobs` is non-empty (creates if absent; if it already exists,
  **does NOT overwrite** — reports for manual review). **Pure substitution — nothing is
  derived at runtime**: the renderer never reads `modules` and never scans the codebase.
  The `jobs[]` draft is seeded/transformed from `modules` once, at setup time, in [SKILL.md](../SKILL.md) Step
  2.6b. Skips when `enable: false`, the section is absent, `jobs` is empty, or every job
  lacks a `test` command (an empty matrix is a GitHub Actions error). Individual jobs
  without a `test` command are dropped from the matrix and reported. `language` is
  matched **case-insensitively** (casefold) against the five official-setup-action keys
  and the matched value is **normalized to lowercase** in the rendered matrix entry, so
  the template's lowercase `if: matrix.language == 'python'` gates still match even if
  config wrote `language: Python`. A job whose (normalized) `language` is one of
  `python`/`node`/`java`/`go`/`rust` but omits `version` (or leaves it blank) is dropped
  and reported — an empty `version` reaching the official action suppresses its own
  default and fails. A surviving job with a blank `name` is auto-filled `job-<n>` (1-based,
  counted among surviving jobs); two surviving jobs sharing the same `name` are **not**
  dropped but produce a `[!]` warning (GitHub still creates distinct jobs, but the Actions
  UI shows duplicate labels).
- **Migrates** a repo-root override into `.claude/vway-kit/templates/`, **then** seeds what the config declares there — what moves, what is copied, what is deliberately left behind, and why the order is a contract: [host-templates.md](host-templates.md).
- **Renders** `.github/workflows/doc-style.yml` when `vdev-config.doc_style.enable` is true,
  and `e2e.yml` when `vdev-config.e2e.enable` is true — same create-if-absent /
  never-overwrite rules for both. `wiki-verify.yml` is **not** rendered here at all:
  [`/wiki-init`](../../wiki-init/SKILL.md) offers it once a graph exists to verify. What each
  flag switches — render only, or render and run — plus the `/playwright-scaffold` pointer to
  relay: [ci-workflows.md](ci-workflows.md).
- **Renders** `.github/workflows/deploy.yml` (orchestrator) and copies the target
  components `.github/workflows/deploy-<target>.yml` from `vdev-config.deploy` when
  `enable: true` and at least one target survives validation. **Pure config → workflow;
  nothing is derived at runtime** (no codebase scan). Components are copied verbatim —
  they carry no substitution tokens; the orchestrator passes parameters through
  `with:`. Skips when `enable: false`, the section is absent, or every target is
  dropped (an empty `jobs:` is a GitHub Actions error). A target is dropped and
  reported when: its `target` is unknown; `target: custom` names a `workflow:` path
  that is absolute, has a root, or contains `..` (repo-relative paths only), or that
  does not exist; `ghcr` omits `image`; `maven-central` omits `build_tool` or
  `publish`. `deploy.yml` is **generated**, not templated — if it already exists it is
  preserved and reported.
- **Reports** each `vdev-config.alm.recoble.spaces` entry's MCP registration state under
  a `[Recoble MCP]` heading and prints the `claude mcp add` command for the ones that
  need it. It **reads** `~/.claude.json` (local scope, this repo's path) and **never writes
  it** — the human runs it in their terminal so the token never enters a session. It also
  names, deleting neither, a pre-PAT install's `recoble-*` left in the repo `.mcp.json`. **Skips and `[!]`-reports** a space whose `mcp_url` is still an
  example placeholder UUID — see [`recoble-spaces.md`](recoble-spaces.md) and [SKILL.md](../SKILL.md) Step 2.8.
- **Wires** `release.yml` — inserts the `deploy:` caller job as an idempotent
  `# vway-kit:deploy BEGIN/END` marker block, computing the permission union from the
  configured targets (permissions can only be *reduced* down a reusable-workflow
  chain, so the top-level caller must grant the union). The release job's **actual id**
  is read, not assumed to be `release`. Wiring is **refused, leaving the file
  untouched**, when: `release.yml` is absent; the `# vway-kit:deploy BEGIN` marker is
  present with no matching `END` (a corrupted block — nothing is written, and the
  consumer is told to repair or remove the block by hand rather than risk truncating
  content after it); more than one job exists besides `deploy`; the release job has no
  `outputs.tag` (old template — the `pretag`/`released` steps' placement is a semantic
  judgement and is not retrofitted); `jobs:` is not the last top-level key; the
  result fails to re-parse; or `deploy.yml` does not open with the generated header (a
  hand-written one may not declare the `tag` input the call job passes — guide the user
  to delete or merge it, then re-run). Setting `deploy.enable: false` and re-running **removes**
  the block.

- **Refuses to let a committed symlink carry a plugin-owned write outside the host.** Every
  destination this script writes on its own account — the gate scripts and policy under
  `scripts/`·`config/`, the shipped rule copy, the `.pre-commit-config.yaml` example, every
  rendered `.github/workflows/*.yml`, and the `.applied-version` marker — rejects a
  **directory** link in its path that resolves outside the host (reported `[!]`, nothing
  lands on the far side) and replaces a link sitting **at the destination itself** before
  writing. Host-owned in-place edits (`.gitignore`, `CLAUDE.md`, `settings.json`,
  `.codex/hooks.json`, `release.yml`) go through the same host-boundary check (`confine`) on
  the file itself, not only its parent directory — they still follow a link that resolves
  **inside** the host (the dotfile-tooling contract: a repo-local symlink is written through
  to wherever it points) but refuse one that resolves outside it, reported `[!]` with the
  managed copy left untouched. `.gitignore`/`CLAUDE.md`/`release.yml` edits also preserve
  whichever line ending (`CRLF`/`LF`) the file already had. The `AGENTS.md` block is the one
  exception — it keeps its own symlink/shared-file detection in
  `scripts/harness/codex/instructions.py`, not this check. The template seed under
  `templates/` enforces the same boundary through its own declared-rel check (see
  [host-templates.md](host-templates.md)). The legacy migration above guards the same
  boundary at a coarser grain — see that bullet.

The same script's `--uninstall` mode (run by [`/vdev-uninstall`](../../vdev-uninstall/SKILL.md))
unregisters the Codex gate from `.codex/hooks.json` regardless of what `vdev-config.harnesses`
lists now — a host that dropped `codex` after installing it still has the hook file. A host
with no `.codex/hooks.json` gets no Codex step at all.
