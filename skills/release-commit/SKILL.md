---
name: release-commit
description: >-
  Use when promoting integration to staging or staging to production, cutting a release
  candidate, or finalizing a release — including bare asks like "stage로 올려줘", "릴리즈 해",
  "main 승격", "promote to main", "cut an rc"; and when a promotion produced no release
  candidate and you need to know why. Generic git-flow habit cuts no release candidate, and
  nothing reports it.
argument-hint: "[staging | release | hotfix]"
# Every rule below matches a command spelled out in the body. Exact marker paths, no trailing
# glob: a glob's `*` crosses path separators including `..`. `git commit` and `git merge` are
# deliberately absent — the commit prompt is the mechanical backstop behind the gate, and this
# skill's whole subject is which merge shape the release CI needs. Scripts run from
# `${CLAUDE_PLUGIN_ROOT}`: a relative rule pre-approves whatever file the working repo puts there.
allowed-tools: Bash(git fetch origin) Bash(git fetch --tags origin) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_version.py" state) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/changelog_section.py" pending) Bash(mkdir -p .claude/vway-kit/.vdev) Bash(touch .claude/vway-kit/.vdev/review.done) Bash(touch .claude/vway-kit/.vdev/bump.done) Bash(touch .claude/vway-kit/.vdev/security.done)
---

# Release Commit — integration → staging → production

One promotion end to end: the gates it records, the level the release CI needs, the merge shape
that carries it, and the back-merge that closes the cycle.

**Source of truth**: [risk-tiers.md](../../rules/risk-tiers.md) owns the policy — the gate
glossary. The SessionStart hook injects it, so it is already in context. Four parts of it are
injected by nothing and are read where they apply: the message format in
[commit-discipline.md](../../rules/commit-discipline.md), read before any commit here; the
promotion-only one — Version bump selection, Merge commit messages, Back-merge after
release, 검증 회차 — in [promotion.md](../../rules/promotion.md), read at the top of a
promotion; the branch-flow table in
[merge-strategy.md](../../rules/merge-strategy.md), read at a merge; gate behaviour in
[gate-mechanics.md](../../rules/gate-mechanics.md), read when one blocks. This skill is the
procedure that applies all five and does not restate them. Where a rule and this skill
disagree, follow the rule and report that this skill has drifted.
[vdev-tiers.yaml](../../vdev-tiers.yaml) carries the per-tier gate list the commit hook
enforces — read it, nothing injects it.

Branch names come from `vdev-config.branches` (`integration` / `staging` / `production`).

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Input

- **$ARGUMENTS** — `staging` (integration → staging), `release` (staging → production) or
  `hotfix` (a `hotfix/*` branch whose Dev-tier commit is written → production). With none, ask
  the user which promotion this is.

## Which gates need a marker

A promotion is gated at the **commit on the target branch** — the branch drives it, so no tier
marker is written. `precommit`, `security-scan`, `wiki` and `doc-style` are runtime gates the
commit hook runs itself: no marker to write, no skill behind them. The gates needing a recorded
marker are `review` and `bump` (Staging), `security` alone (Release) — Release runs no code
review at all, for the reason [promotion.md](../../rules/promotion.md) Release gives.

## 검증 회차 — 조건부 런타임 단계

Both promotions run it, and it is **not** a tier gate: a host that declares no `run: true`
layer passes it with no output, the way `wiki` and `doc-style` do on an unconfigured
repository. A marker gate could not do that — it sees only whether a file exists, so every
consumer who does not use an ALM would find their promotion blocked with nothing to unblock it.

1. **Run the suite** — Invoke skill `integration` — 그 스킬의 §3.3–3.4 로 돌림(이 스킬이
   `npx playwright test` 를 직접 발행하지 않는 이유 — 도구 집합은 그쪽 것). The build under test
   is the **pre-merge** `origin/<integration>` deployment (Release: `origin/<staging>`, the rc).
   The merge stops before its commit, so the tree verified and the tree promoted differ by the
   rc bump alone.
2. **Record the round** — integration §3.5. `scope`·`build`·`environment`·`result`.
3. **Judge against the host's exit criteria** — `promotion_verification.exit_criteria` in
   `vdev-config.yaml`: `scope` names the suites that must have run, `allow_blocked` says whether
   a `BLOCKED` case still counts as met. No key → suite-wide PASS is the criterion. Without this
   the step measures only "a round exists", never "enough of it ran".
4. **근거는 회차 항목이 듦** — `build` 필드에 검증한 sha 가 들어가므로, 나중에 "이 릴리스가 무엇을
   통과했나" 는 그 sha 로 회차를 조회해 답함. `.done` 마커도 커밋 트레일러도 쓰지 않음: 마커는
   그 티어 `gates` 목록에 이름이 있을 때만 훅이 읽으므로 여기서는 쓰기 전용이 되고, 워크플로가
   읽는 트레일러는 `Release-Level` 하나뿐이라 회차 트레일러는 읽는 곳이 없음.

네 결과, 승격을 세우는 것은 둘:

| 결과 | 무엇이 남나 |
|---|---|
| 스위트 PASS + 기준 충족 + ALM 기입 성공 | 회차 항목(`build` = 검증한 sha) |
| 스위트 PASS + 기준 충족 + ALM 기입 실패 | 사람에게 **알리고 계속/중단을 물음**. 계속하면 승격 커밋 **본문에** "검증 회차 미기록(ALM 기입 실패)" 한 줄 — 트레일러는 읽는 워크플로가 없으므로 본문에 두고, 이력에 남아 백스톱이 우회와 기입 실패를 가름 |
| 스위트 PASS + **exit criteria 미충족** | 승격 중단. 기준을 선언한 호스트에게 미충족은 곧 실패이고, 통과로 읽으면 그 선언이 장식이 됨 |
| 스위트 FAIL · **실행된 케이스 0개** | 승격 중단. 한 건도 안 돈 실행은 통과가 아니라 실행 실패이고, 그것을 통과로 세면 텅 빈 회차의 sha 가 릴리스 근거로 남음 |

Only a failing suite blocks, so "ALM 실패는 게이트가 아니다" holds: an expired MCP token costs
the evidence, not the release.

**Missing-round backstop (warning only).** At the start of a promotion, check whether any round
exists since the previous release tag. 회차가 없는 원인은 둘이고 보고가 그것을 갈라야 함 — 그
구간 승격 커밋 본문에 "검증 회차 미기록" 줄이 있으면 **기입 실패**, 없으면 이 단계를 **우회**한
승격. 어느 쪽이든 보고 후 계속함. Blocking now would not fix a release that already shipped, and repository
state is a warning path.

## Step 0 — Read the host's release model

The level reaches CI one way: a `Release-Level:` trailer on the staging merge commit, read by the
push it rides on. Which levels a host accepts is the workflow's own declaration — a
`# vway-release-levels:` comment line the templates carry. Ask the rendered artifact rather than a
template list: a hand-written `release.yml` earns the same answer from the same question, because
the subject is the workflow that runs. **Run this from the repo root** — the path is relative to
the working directory:

```bash
python3 -c "import pathlib, re, yaml
p = pathlib.Path('.github/workflows/release.yml')
if not p.exists():
    print('no-release-workflow'); raise SystemExit(0)
text = p.read_text(encoding='utf-8')
try:
    doc = yaml.safe_load(text)
except yaml.YAMLError:
    doc = None
if not isinstance(doc, dict):
    print('unreadable-release-workflow'); raise SystemExit(0)
m = re.search(r'^# vway-release-levels:(.*)$', text, re.M)
if m:
    print('trailer ' + ' '.join(m.group(1).split())); raise SystemExit(0)
if 'Release-Level' in text:
    print('trailer-undeclared'); raise SystemExit(0)
# YAML 1.1 reads a bare on: as the boolean True, so both spellings are asked for.
on = doc.get('on', doc.get(True)) or {}
d = (on.get('workflow_dispatch') or {}) if isinstance(on, dict) else {}
i = (d.get('inputs') or {}) if isinstance(d, dict) else {}
print('legacy-dispatch' if isinstance(i, dict) and 'level' in i else 'auto-only')"
```

- **`trailer <levels>`** — the workflow reads the trailer and names the levels it takes. Those
  words are Staging's options, and nothing outside them is offered: `auto` appears only where a
  push without a trailer still derives an rc from the commit types.
- **`trailer-undeclared`** — the workflow reads a trailer and declares nothing (a hand-written or
  sister-plugin workflow). Offer **patch / minor / major** alone; `continue` and `auto` are
  promises nothing in the file backs.
- **`auto-only`** — no trailer and no level input; the prerelease push derives `X.Y.Z-rc.N` from
  the commit types (Node `semantic-release`). Skip the level question; the rc still gets cut.
- **`legacy-dispatch`** — the level still arrives through a `workflow_dispatch` `level` input and
  no trailer is read. **Stop** and tell the user to re-run `/vdev-init`: its release-workflow
  migration re-renders the file with their consent. This skill does not drive that channel.
- **`no-release-workflow`** — no release CI is installed. Stop and tell the user to run
  `/vdev-init`.
- **`unreadable-release-workflow`** — the file is there and its YAML does not parse. Nothing
  about the release model can be read off it, so the promotion would be guessing at the one
  question it exists to answer. Stop and ask the user to fix the workflow first.

PyYAML is safe to reach for: the commit gate already requires it fail-closed, so a host that
runs the gate has it.

**Detection is the aid; the outcome check is the substance.** A declaration can drift from the
shell beside it, and a hand-written workflow may read the trailer differently. Staging's last
step confirms the rc whatever the class, and that is what catches a wrong read.

## Staging (integration → staging)

**0. Re-promotion — back-merge staging first.** Ask the same script the release workflow asks,
so the skill and CI cannot disagree on what is pending — it reads the tag list, not the branch.
Without an argument it lists the tags itself, the one form `allowed-tools` can pre-approve:

```bash
git fetch --tags origin
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_version.py" state
```

The first line is `pending: vX.Y.Z-rc.N` or `pending: none`; the rest name the version each level
would cut, or why it cannot. On `none` go to item 1. On a pending rc, bring staging back into
integration before anything else — the rc bump commits then sit on integration, and item 1's pair
lists only the work this re-promotion adds:

```bash
git switch <integration>
git merge --ff-only origin/<staging>
git push origin <integration>
```

`--no-ff` where the fast-forward is refused (integration has moved on — the usual reason for a
re-promotion). Keep the printed lines: item 3 labels its options with them.

**1. Regression review.** An independent **`general-purpose`** agent (separate context, runs
its own shell commands), judged against `vdev-config.review_checklist` plus the callers of every
changed public symbol. A promotion starts on a clean working tree, so the file list comes from
this promotion's own pair rather than from the workspace:

```bash
git fetch origin
git -c core.quotePath=false diff --name-only "origin/<staging>..origin/<integration>"
```

Use the freshly fetched `origin/` refs — a stale local ref shrinks the reviewed set with no sign
that it did. Two dots, not three: `git diff` reads that as a two-endpoint diff, so a commit
sitting on staging alone still surfaces — inverted, as a deletion this merge will not make.
Staging is the only promotion that reviews at all; Release has no pair to carry this one into.

**1-1. 검증 회차** — 위 [검증 회차](#검증-회차--조건부-런타임-단계) 절을 여기서 실행. `run: true`
계층 미선언 호스트는 무출력으로 지나가므로 이 항목이 서 있어도 그 호스트의 절차는 안 늘어남.
회차가 없으면 뒤 항목이 무엇을 통과했는지 말할 근거가 없음.

**2. Compute a recommended level.** The commit types over the promoted range decide it — the
mapping lives in [commit-discipline.md](../../rules/commit-discipline.md) Commit type → version
impact — together with the host's 0.x policy, under which `1.0.0` arrives by an explicit
decision alone.
With a pending rc the recommendation is **`continue`**: the rc series goes on unless the new work
needs a higher base.

**3. Ask the user — the class from Step 0 fixes the options.** Ask the user (structured choice),
defaulting to the recommendation, which never stands in for the answer: **always ask** where
there is anything to ask.

- **`trailer <levels>`** — the declared levels, each labelled with the version item 0's `state`
  printed for it; a level `state` marks as impossible (`continue` with nothing pending) is not
  offered. From a pending `v1.1.0-rc.2`: `continue` → `v1.1.0-rc.3`, `patch` → `v1.1.1-rc.1`,
  `minor` → `v1.2.0-rc.1`, `major` → `v2.0.0-rc.1`. `auto` carries no version — the tool
  derives it.
- **`trailer-undeclared`** — **patch / minor / major**.
- **`auto-only`** — no question; nothing there reads a level, so an answer would change nothing.

When the current version is `0.x` and the choice is `major`, warn that it jumps straight to
`1.0.0`. Every class records `bump.done` in item 4 — the gate is fail-closed on that file — and
on `auto-only` the recommendation is what the promotion reports.

**4. Record the markers**, one command per line — a brace form matches neither the exact
`allowed-tools` rules nor a reader's eye:

```bash
mkdir -p .claude/vway-kit/.vdev
touch .claude/vway-kit/.vdev/review.done
touch .claude/vway-kit/.vdev/bump.done
```

**5. Stand on the target branch, bring it up to origin, then merge integration into it, leaving
the commit unwritten:**

```bash
git fetch origin
git describe --tags --abbrev=0 origin/<staging>
git switch <staging>
git merge --ff-only origin/<staging>
git merge --no-ff --no-commit origin/<integration>
```

Keep the tag `git describe` prints — item 8 compares against it, and nothing else records it.

The `--ff-only` line is not ceremony. The promotion merge has to sit on what the remote holds:
off a stale local branch the `precommit` and `security-scan` runtime gates judge a tree nobody
will push, the markers are consumed on it, and the rejection arrives only at push time.

The switch is what makes the rest of this section true. Run the merge while still on
`<integration>` and git answers "Already up to date." — a no-op that reads as success — and the
commit hook resolves the tier from the branch it finds, so the promotion loses the tier the
markers were recorded for and is blocked as unclassified.

`--no-ff` is gate-enforced on this row ([vdev-tiers.yaml](../../vdev-tiers.yaml)
`merge_strategy`), and the reason is the release rather than the history: the merge commit is the
one the push puts on top, and the trailer has to ride on it.

**6. Write that pending merge** — invoke skill `commit`, **passing the chosen level** — the only
channel it has, since `bump.done` is an empty marker. The subject is
`Merge <integration>: <headline>` — capital `Merge`, no Conventional type
([promotion.md](../../rules/promotion.md) Merge commit messages). The body ends with
`Release-Level: <level>`; `auto` and `auto-only` pass no level and the commit takes no trailer.
The trailer is a line of its own, flush left — an indented one is body text, and CI reads the
level as absent.
**No `[skip ci]`** on any class: the push is what cuts the rc.

**Merge first, commit second.** CI reads the top commit of the push alone
(`git log -1`). Write the commit first and merge after, and the trailer sits one commit back: the
run finds none and takes the no-trailer default — `auto` where the host declares it, otherwise
`continue` on a pending rc and `patch` without one — and the chosen level is gone with nothing to
say so.

**7. Push — this is what cuts the rc:**

```bash
git push origin <staging>
```

**8. Confirm the rc appeared — every class, `auto-only` included.** Wait for the staging release
workflow to finish, then hold the remote against item 5's baseline. Write that tag in literally:
each Bash call is a fresh shell, so nothing survives from the earlier block.

```bash
TAG_BEFORE=<tag-from-item-5>
git fetch origin
TAG_AFTER="$(git describe --tags --abbrev=0 origin/<staging>)"
echo "before=$TAG_BEFORE after=$TAG_AFTER"
```

`after` has to be **the version item 3 offered for the chosen level** — on a `trailer` host,
where `state` named one. That is stricter than a new rc on purpose: a trailer that did not
register (an indented line, a body one commit back) still cuts an rc, at the host's no-trailer
level, and only the version says so. Where no version was offered (`auto`, `trailer-undeclared`,
`auto-only`), `after` has to be an `X.Y.Z-rc.N` **and differ from** `before`. The shape alone
proves nothing:
`git describe` walks back to the newest reachable tag, so a promotion that cut no rc still
prints the *previous* cycle's rc — the exact failure this step exists to catch, wearing the
shape the step is looking for. Two equal values, or a stable tag, mean **no rc was cut and the
promotion is not finished** — report that rather than moving on. Three causes account for nearly
all of it: the trailer did not land on the pushed head, the run failed on a level it cannot use
(its log names the trailer as the reason), or the release token could not push. This step
is the net under Step 0's detection, which matters most where the detection has nothing to read —
a hand-written workflow declares no levels.

A run that stops at the rc goes to End state from here, the ordinary case with the release
following days later.

## Release (staging → production)

**1. Fetch, and confirm staging carries the rc.**

```bash
git fetch origin
git fetch --tags origin
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_version.py" state
```

`origin/<staging>` must sit at `X.Y.Z-rc.N`, the version bump the rc CI pushed — merged before it
lands, finalize finds no rc to strip and takes the hotfix path, releasing a patch instead — and
`pending:` must name that rc. `none` or another rc means a hotfix shipped `X.Y.Z` or a higher base
first, and the release would not be the one chosen: a host that reads the rc from a version file
fails the run instead of tagging (`vX.Y.Z 이 이미 있음`, or `… 보다 낮음`), and one that reads the
tag list releases a plain `patch` off the last stable. **This check is the only thing that catches
the second kind**, so do not skip it. Stop, and re-promote staging through the Staging section
choosing `patch` or higher.

**2. Security review** — `/security-review` over this promotion. It is the only review layer
here; do not add a code-review pass back.

**2-1. 검증 회차** — 위 [검증 회차](#검증-회차--조건부-런타임-단계) 절. 대상 빌드는
`origin/<staging>`(rc). Staging 의 회차가 그대로 근거가 되지 않는 이유는 승격되는 트리가 다르기
때문 — rc bump 가 이미 얹혀 있음.

**3. Record the marker:**

```bash
mkdir -p .claude/vway-kit/.vdev
touch .claude/vway-kit/.vdev/security.done
```

One marker, not two. A `review.done` sitting here is **Staging's**, left behind by a run that
stopped at the rc — clear it (the End state's `rm -f` covers it) rather than reading it as
evidence for anything on this tier.

**4. Stand on the target branch, bring it up to origin, then merge the freshly fetched staging
into it, leaving the commit unwritten:**

```bash
git fetch origin
git switch <production>
git merge --ff-only origin/<production>
git merge --no-ff --no-commit origin/<staging>
```

Same reasons as Staging item 5: off the target branch the merge is a no-op or lands on the wrong
branch and the commit hook reads the tier off the branch it finds, and off a stale local branch
the runtime gates judge a tree nobody will push.

**5. Fold the rcs into one stable changelog section** — with the merge open and nothing
committed yet. The release workflow puts that section into the GitHub Release body, so without it
the notes are the rc sections as they were cut. The procedure — read what folds in, draft, have
the user approve it, `fold`, stage `CHANGELOG.md` — is
[references/changelog.md](references/changelog.md). Read it whole; nothing is written before the
user approves.

**6. Write that pending merge** — invoke skill `commit`; no level, no trailer, and **no
`[skip ci]`**. The non-skip subject is what fires finalize, and finalize is deterministic: it
strips the rc token off the version staging already carries and ignores any trailer. A trailer
on the production branch only matters where no rc is reachable — a `hotfix/*` landing, which
releases the level it names and a patch without one. Same subject form as Staging
(`Merge <staging>: <headline>`), and the same fixed order, for the same reason.

**7. Push — this is what fires finalize:**

```bash
git push origin <production>
```

Deploy is project-specific and not gated; the production-branch commit is the gate.

## Hotfix (hotfix/* → production)

A hotfix reaches production without staging and still ships a release, so End state's
back-merge is owed after it too. The procedure — baseline and `state`, security marker, squash
as a `fix:` commit, confirm the stable tag, close the cycle — is
[references/hotfix.md](references/hotfix.md). Read it whole before the first merge.

## When the `wiki` gate blocks the promotion commit

`doc-sync` is the only gate that rebuilds `graph.yaml`, and it is not a promotion gate — so
graph drift that reached the integration branch through a terminal commit surfaces here, as a
blocked promotion commit. Rebuilding it by hand is what this step is
([`gate-mechanics.md`](../../rules/gate-mechanics.md) names every such place). Resolve it in
place:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --build
```

Stage the rebuilt `graph.yaml` into the promotion commit. A failure naming a **structure**
violation instead — `wiki_id` format or duplicate, missing `title`, dangling `depends_on`, a
cycle, front matter that carries a `wiki_id` and does not parse — is a document's front matter
to fix; `--build` cannot resolve those.

## End state

**Every run ends here** — both promotions, a run that stopped at the rc, and a hotfix. The
back-merge is owed after a production release (Release and Hotfix); the marker clearing is every
run's.

**Back-merge production → integration → staging (Release and Hotfix, not optional).** Once the
release CI has pushed its `chore(release)` version-bump and marketplace-sha-pin commits to
production:

```bash
git fetch origin
git switch <integration> && git merge --ff-only origin/<production>
git push origin <integration>
git switch <staging>     && git merge --ff-only origin/<production>
git push origin <staging>
```

`integration` takes `--no-ff` where the fast-forward is refused.
`staging` takes **`--ff-only` and nothing else**: a merge commit written there lifts staging out
of integration's ancestry, so the promotion after it is no longer a descendant merge and the
version file conflicts. A refused fast-forward on staging is therefore a skip, and the next
integration → staging promotion carries the release commits forward.

A fast-forward leaves all three branches on one commit, which is how the back-merge is confirmed
to have landed: `git rev-parse` on the three returns a single sha.

**Clear the promotion's evidence markers**, whichever this run recorded — `rm -f` is silent on
the ones it did not. The commit hook is fail-closed on them: it **blocks** the promotion commit
until each marker its tier requires exists. That is what makes a marker a forcing function
rather than a stamp — and what makes one left behind read to the *next* promotion as its own
passing evidence. A run that ended at Staging is where that bites: nothing else deletes
`bump.done`, so the next rc satisfies its fail-closed `bump` gate with no one choosing a level.

```bash
rm -f .claude/vway-kit/.vdev/review.done .claude/vway-kit/.vdev/bump.done .claude/vway-kit/.vdev/security.done
```

Deleting evidence stays a deliberate prompt: no `allowed-tools` rule covers that `rm`.

## Failure modes

Each of these produces a release that looks finished and is not.

1. **A promotion merge left unpushed** — the merge sits on the local branch, CI never sees a
   push, no rc is cut, and Release's precondition that `origin/<staging>` carries `X.Y.Z-rc.N`
   can never be met.
2. **A merge run off the target branch** — git answers "Already up to date." and nothing lands,
   or the merge lands on the branch the session happened to be on. The commit hook reads the
   tier off the current branch either way, so the promotion is blocked as unclassified.
3. **The trailer one commit below the head** — the commit written before the merge, so the
   pushed head carries no trailer: the run takes the no-trailer default (`auto` where declared,
   else `continue` or `patch`), and the chosen level is gone.
4. **A level the workflow cannot use** — a word outside its declaration, or `continue` with no
   pending rc. The run fails and cuts nothing.
5. **`[skip ci]` on a promotion merge** — CI never runs: no rc at staging, and at production
   finalize never strips `-rc.N`.
6. **A re-promotion without the staging back-merge** — the review pair lists the rc bump commits
   as deletions, and integration keeps a stale version file.
7. **Merging a stale local staging ref** — finalize sees no pending rc and takes the hotfix path
   instead: a patch off the last stable tag, not the rc that was chosen.
8. **A skipped back-merge** — the released tag is unreachable from integration and the next
   version is computed wrong.
9. **A `--no-ff` back-merge into staging** — staging leaves integration's ancestry and the
   promotion after it conflicts in the version file.
10. **Evidence markers left in place** — the next promotion reads someone else's `review.done`,
    `bump.done` and `security.done` as its own pass.
11. **A merge flag spelled through a variable** — the hook receives the command text before the
    shell expands it, reads it as "not a merge", and every merge-strategy check switches off in
    silence (CLAUDE.md Invariant 7).

## Never

- **Never offer a level the workflow does not declare** — Step 0's list is the whole menu.
- **Never drive a `legacy-dispatch` host** — send the user to `/vdev-init` instead.
- **Never call a promotion done without confirming the rc** (Staging item 8).
- **Never put `[skip ci]` in a promotion merge.**
- **Never put a `Release-Level:` trailer on the production merge** — finalize ignores it, and a
  reader takes it for a level that applied.
- **Never spell a merge flag through a variable.** Write every flag literally.
