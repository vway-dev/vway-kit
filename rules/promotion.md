# Promotion Reference

> 주입되지 않음. [`risk-tiers.md`](risk-tiers.md) 가 SSOT 이고 SessionStart 훅이 그것을 통째로
> 주입함 — 여기 있는 것은 그 파일의 승격 전용 절이라, 일상 요청이 지고 다니지 않게 빼 둔
> 것. 승격 절차를 도는 [`/release-commit`](../skills/release-commit/SKILL.md) 이 이 파일을 읽음
> — `/vdev` 는 승격을 그 스킬에 통째로 위임하므로 직접 읽지 않음.

### Version bump selection (auto vs manual)

By default the bump is **auto** where the release tool derives it — semantic-release parses
the merged commits ([`commit-discipline.md`](commit-discipline.md) Commit type → version
impact). A specific release **forces** a level through a `Release-Level: <level>` trailer at
the end of the staging merge commit's body, read by the release workflow off the pushed head.
That trailer is the only level channel; the rendered workflows take no `workflow_dispatch` level.

The version is decided **once, where the rc is born (staging)**, and the
production branch only **finalizes** it — this is what makes forced bumps
survive the rc→stable hop:

- **Staging (prerelease) sets the version.** The levels a host accepts are its workflow's
  `# vway-release-levels:` declaration (`/release-commit` Step 0 reads it). With no pending rc,
  `patch`/`minor`/`major` count from the last stable tag and cut `-rc.1`; `auto` — declared only
  where the tool derives versions — or no trailer leaves it to the commit types. A tool that
  derives nothing takes `continue` on a pending rc and `patch` without one, so every staging push
  cuts an rc.
- **Re-promotion continues or re-bases the pending rc.** A pending rc is an `X.Y.Z-rc.N` tag with
  no `vX.Y.Z` yet and a base above the last stable tag, judged from the tag list. `continue`
  cuts `X.Y.Z-rc.(N+1)`; `patch`/`minor`/`major` raise **that base** and cut its `-rc.1` (from
  `v1.1.0-rc.2`: `v1.1.1-rc.1`, `v1.2.0-rc.1`, `v2.0.0-rc.1`). Staging is back-merged into
  integration first, so the rc bump commits reach integration before the next review.
- **A level the workflow cannot use fails the run** — a word outside the vocabulary, or
  `continue` with no pending rc. A typo falling through to the no-trailer default would read as
  the level that was chosen.
- **Production (stable) finalizes the rc.** It does **not** recompute or
  re-force — it deterministically drops `-rc.N` (`X.Y.Z-rc.N → X.Y.Z`) off the rc reachable from
  it, and ignores any trailer. PSR cannot finalize a force-diverged rc (`auto` recomputes from the
  last stable tag; a forced level double-bumps off the rc), so the workflow runs a deterministic
  finalize step on the stable branch, and applies forced rc levels deterministically as well. A
  promotion therefore needs **no level on production** — the plain `--no-ff` merge triggers the
  finalize.
- **An rc a hotfix overtook does not ship as itself.** A hotfix skips staging, so it can release
  `X.Y.Z` or a higher base while `X.Y.Z-rc.N` waits. What the workflow does then follows from where
  it reads the rc. A tool whose version lives in a file (PSR, and this repo) finalizes that file's
  rc and fails the run rather than duplicate or downgrade a tag. A tool reading the tag
  list finds no pending rc — the base shipped — and releases the last stable plus `patch`, which is
  monotone but is not the level anyone chose. Both are caught before the merge:
  [`/release-commit`](../skills/release-commit/SKILL.md) Release item 1 stops when `pending:` does
  not name the rc being merged. Re-promote staging with `patch` or higher, then release.
- **Production with no reachable rc releases directly** — a `hotfix/*` landing. The trailer's
  `patch`/`minor`/`major` picks the level; with no trailer a tool that derives versions takes
  `auto` and the rest take `patch`.
- **Promotion ordering — production must wait for the rc to exist.** When
  promoting integration → staging → production in one pass, the finalize
  depends on the rc **already being on staging**: wait for the staging
  release workflow to **complete and push its version-bump commit**,
  `git fetch` so local staging carries the `X.Y.Z-rc.N`, and only then
  `--no-ff` merge staging → production. Merging before the rc lands makes
  finalize see **no `-rc.N` reachable** → it takes the direct-release path and
  **releases a different version** (a patch off the last stable tag, not the
  intended finalized rc). The rc must be real and fetched before production.
- **Agent-driven promotion**: when an agent (e.g. Claude) performs the
  promotion, it **asks the user for the bump level** from the declared set at the
  **staging** step, before cutting the rc. This is
  **gate-enforced** — the `staging` tier's `bump` gate (`vdev-tiers.yaml`)
  blocks the staging commit until `.vdev/bump.done` is recorded, so the
  decision cannot be silently skipped. Production then only finalizes.
- Node `semantic-release` has no forced-level support (commit types only)
  — so no divergence, and its prerelease→stable finalize is native (no
  custom step). Use another tool when manual selection is needed.
- **A workflow that takes a `workflow_dispatch` level and reads no trailer** is flagged by
  `/vdev-init`'s release-workflow migration, which re-renders it with consent;
  `/release-commit` stops on such a host rather than drive the old channel.
- **Release CI auth**: the release workflow authenticates with a
  repo-scoped fine-grained PAT secret **`RELEASE_TOKEN`** (Contents:
  **Read and write**); if it is unset it **falls back to the built-in
  `GITHUB_TOKEN`** (`${{ secrets.RELEASE_TOKEN || github.token }}` with
  `permissions: contents: write`). Either path needs a one-time **admin**
  setup — register the secret (Settings → Secrets), **or** set Settings →
  Actions → Workflow permissions to "Read and write" for the built-in
  token. A write-only contributor can do neither, but once set anyone with
  write can trigger releases. The preflight verifies write with a
  **non-destructive write-probe** — a bad-`sha` `PUT /contents` (403 = no
  write). **Do not** gate on `.permissions.push`: it reflects the user's
  role, not the fine-grained token's Contents scope, so it false-OKs a
  read-only token. On failure (and on any commit/push failure) it prints
  both setup paths; the detailed steps live in vway-kit's
  `docs/usage/promotion-and-release.md` / the generated
  `commit-versioning-guide` (SSOT).

### Merge commit messages (promotion merges)

Both promotion rows — integration → staging and staging → production —
make a `--no-ff` merge commit. Its **title MUST start with a capital
`Merge`** — gitlint recognizes a commit as a merge only when the title
begins with capital `Merge`, and only then exempts it from the
type/50-char checks, which is also the exemption `/commit` applies.

- `Merge <source>: <headline>` — put the merge summary in the
  **body**, not the title.
- Never use lowercase `merge ...` — full-checked as a normal commit.
- Never use `chore(release): ...` — that prefix is the auto-release
  bot's namespace.

Do not attach a Conventional type to a merge commit. The version is
decided by semantic-release parsing the **individual merged commits**.

### Back-merge after release (production → integration)

semantic-release writes the version bump (`plugin.json` / `pyproject`)
and the marketplace sha pin **only on `production`** (as `[skip ci]`
`chore(release)` commits). They never reach integration on their own,
so integration's `plugin.json` drifts to a stale version.

After every production release, **back-merge** the release commits
production → integration (and → staging), so those commits and the
reachable stable tag return to the day-to-day branches. The commands are
[`/release-commit`](../skills/release-commit/SKILL.md)'s End state.

Fast-forward when the branch is strictly behind — the normal case right
after a release, since nothing lands on integration/staging while the
promotion runs.

On **integration**, reach for `--no-ff` only when FF is refused because the
branch has moved on; taking it by preference adds a commit carrying no
content and hides that check.

**`staging` is `--ff-only` and nothing else.** A refused fast-forward there
is a **skip** — the next integration → staging promotion carries the release
commits forward on its own. A merge commit written on staging lifts staging
out of integration's ancestry, so that promotion is no longer a descendant
merge and conflicts on the version file.

This is standard git-flow, **not optional**: without it semantic-release
miscomputes the next version (the released tag is unreachable from
integration/staging). It is needed because Explicit-version gating
forces the version into a **committed file** (not a tag-only release,
which would never drift).

### 승격의 절차 단계 — 검증 회차 (게이트 아님)

[`risk-tiers.md`](risk-tiers.md) Hard gates 가 기계로 강제하는 두 지점(미분류 커밋 차단·승격
브랜치의 게이트 강제)과 달리 기계가 강제하지 않음. `run: true` ALM 계층을 선언한 호스트에서만
[`release-commit`](../skills/release-commit/SKILL.md) 이 스위트를 돌리고 회차 항목을 남기며,
미선언 호스트는 무출력으로 지나감. `vdev-tiers.yaml` 의 `gates` 목록에 **없고** 마커도 없어
커밋 훅이 읽지 않음 — 승격을 세우는 것은 그 단계 자신의 판정 둘뿐(스위트 FAIL,
`promotion_verification.exit_criteria` 미충족). 여기 적는 이유는 승격을 막는 조건이 정책
문서에 하나도 안 적혀 있으면 스킬이 표류해도 대조할 자리가 없기 때문.

## Promotion events (Staging / Release)

These are **not** per-task classifications — they are git-flow
promotion gates run once over the accumulated work. They sit on
their own axis: the Docs → Dev escalation ladder in
[`risk-tiers.md`](risk-tiers.md) Principle is the day-to-day one, and
each promotion's gate set is chosen for that promotion rather than
stacked on Dev's.

### Staging — integration → staging branch (QA / rc cut)

The release candidate enters QA/staging. Gates:
`precommit, review, bump, security-scan, wiki, doc-style`
넷의 정의는 [`risk-tiers.md`](risk-tiers.md) Gates 용어집. Performance·integration 은 게이트가
아니라 독립 스킬이고, `/security-review` LLM 리뷰는 Release 에서 더해짐.
승격 절차는 [`/release-commit`](../skills/release-commit/SKILL.md) 이 보유 — 사용자에게
`bump` 레벨을 묻는 것도 그 스킬.

### Release — staging → production branch

One entry point: the staging → production promotion (official release),
or a production deploy (e.g., an air-gapped offline deploy). Gates:
`precommit, security-scan, security, wiki, doc-style`.
`bump` 없음 — 레벨은 staging 에서 한 번 정해지고 production 은 그 rc 를 확정만 함
(위 Version bump selection).

**A dangerous change does not escalate into this tier.** A single change
that hits an irreversible/large data migration, a **performance-critical
path** (search/embedding/GPU/inference config), or a security surface
(auth/authz, secrets, gateway rate-limiting) stays at **Dev** and adds
`/security-review` before the merge. Release carries no `review`, so
escalating into it would buy a security pass by giving up the domain
review — the wrong trade for the one change that needs both. Nothing
stops it mechanically: the gate reads the tier marker's label and checks
only that its branch matches, so a hand-written `release:feature/x` does
select this set. That security pass is therefore discipline, not a gate.

## Promotion steps

### Staging (integration → staging)

1. Regression review — the [domain review](../skills/vdev/references/dev-overlays.md)
   over **this promotion's own branch pair**, never the workspace form (a
   promotion starts on a clean tree, so that form lists nothing) → record `review`.
   `precommit`·`security-scan`·`wiki`·`doc-style` 은
   precommit-runner 가 승격 커밋 시 자동 실행(런타임 게이트 — 마커 불요; 넷의 정의는
   [`risk-tiers.md`](risk-tiers.md) Gates 용어집, 넷 각각의 티어별 on/off 는
   [`vdev-tiers.yaml`](../vdev-tiers.yaml) 의 그 티어 `gates` 목록이 유일한 스위치).
   승격에서는 어떤 게이트도 그래프를 **재생성 안 함**
   (`doc-sync` 는 승격 게이트가 아님) — 터미널 커밋으로 들어온 drift 가 여기서 차단으로 드러남.
2. Promote integration → staging (rc).

절차는 [`/release-commit`](../skills/release-commit/SKILL.md) — 브랜치 쌍을 뽑는 명령,
막힌 `wiki` 게이트의 그래프 재생성 복구, 승격 커밋의 순서가 거기 있음.

### Release (staging → production)

Gates: `precommit`, `security-scan`, `security`, `wiki`, `doc-style` —
Staging's set with `security` added and both `bump` and `review` dropped,
the finalize taking no level.

**Code review does not run here.** Everything this promotion carries was
read twice already — per task at Dev, as a batch at Staging — and what
staging holds beyond that is CI's `chore(release)` bump. A third pass
buys a second opinion on the same diff at the one moment where acting on
a finding means unwinding a release. Two paths it does leave unread,
both worth knowing: a `hotfix/*` → production landing never passes
through staging, so its Dev-tier `review` at commit time is the whole of
its review; and a commit made onto staging from a terminal is read by no
gate at all — Staging's pair surfaces it only inverted, as a deletion
the merge will not make, never as the change that was written, and this
was the only layer that read it the right way round.

1. Security review — `/security-review` → record `security`.
2. Stable changelog section —
   [`references/changelog.md`](../skills/release-commit/references/changelog.md) drafts one
   deduplicated summary of every rc the release folds in, the user approves it, and it folds into
   `CHANGELOG.md` as that release's `## vX.Y.Z` section, staged into the promotion merge. Every
   release workflow's shared step then replaces the GitHub Release body with that section
   (auto-notes fallback when none exists).
3. Promote staging → production and/or deploy.
