---
name: task-sync
description: The final sub-step /vdev invokes after an ALM-linked task completes — summarizes the task doc back to its Recoble workboard item or Teamer item. Not usually invoked directly.
argument-hint: "[task_id…] [--verified | --propagate]"
---

# /task-sync - sync the task document summary back to its ALM item / usage: [task_id…] [--verified | --propagate]

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Purpose
Read the task document (step 0 resolves it by item id across `docs/tasks/*/`),
generate handoff content, and write it back to the ALM item the task is linked to.

## Arguments
- `$ARGUMENTS` : task id (optional). The authoritative source is the marker
  `.claude/vway-kit/.vdev/alm`, whose format
  [`task-import`](../task-import/SKILL.md) ("Both providers" step 1) defines — read
  it there rather than assuming. No marker and no argument → tell the user nothing
  is linked and stop.
- `issue_tracker_guide` : `vdev-config` 가 가리키는 호스트 규약 문서. 있으면 읽고 그 안의
  프로젝트 고유 사실을 이 문서의 일반론보다 우선함(`commit_guide` 와 같은 꼴). 없으면 그대로 진행.
- `--verified` : the verification-complete mode, Recoble only. Skips step 0's marker and
  task-document resolution and R1–R5b, and runs **검증 완료 모드** below, nothing else. It
  exists because 완료 lands long after the commit — neither the marker nor this run's
  summary work is in play by then. **Takes one id or many** — a release closes every item
  it carried, and asking per item is what makes a person skip the step entirely.
- `--propagate` : the propagation-only mode, Recoble only. Skips step 0's marker, task-document
  resolution and R1–R5b, and runs **전파 전용 모드** below. A verification round that wrote case
  results calls it with those case ids — **one id or many** — so a regression reaches the
  parents' `progress`·`coverage_status` even when nothing is being closed.

## Execution

**Route first.** `--verified` or `--propagate` among the arguments → resolve the provider from
`vdev-config.alm` the way `/vdev` Phase 0 does. No `recoble` in it → report that the mode
is Recoble-only and stop, **before** R0, which has no server to resolve on a Teamer-only
host. Both flags at once → report that the two modes exclude each other and stop — which one
was meant is unknowable. Otherwise run R0 for the tool prefix and go straight to **검증 완료
모드** (`--verified`) or **전파 전용 모드** (`--propagate`) in the Recoble branch. Step 0's
marker and document resolution and R1–R5b do not run: reading them in either mode re-posts a
summary comment the item already carries.

0. **Read the marker** — `.claude/vway-kit/.vdev/alm` holds **one line per linked
   item**, each giving the provider, the space and the item id (format:
   [`task-import`](../task-import/SKILL.md)). It describes the run that wrote it and
   nothing else — `/vdev` Phase 0 clears any leftover before importing, so what is
   here belongs to the work that has finished.
   **Run the matching branch once per line**, in order: `recoble` → the Recoble
   branch below, `teamer` → the Teamer branch (steps 1–8, unchanged). A branch that
   fails costs you that line only; report one line and continue with the next.
   **No marker but an argument was given** (direct re-sync after `/vdev` cleaned
   up): resolve the provider from `vdev-config.alm` the same way `/vdev` Phase 0
   does, and treat a list the same way — one pass per provider. `teamer` can proceed
   — its steps search by the argument. `recoble` tries `get_workboard_item` once with the
   id in the document's file name, and on a miss follows
   [`task-import`](../task-import/SKILL.md) pull's board search. Candidates that do not
   narrow to one → show the item name, its board and its current status, and let the user
   settle it — by naming the item, or by re-linking through `/vdev`.

   **Find the task document here, once, before any branch runs.** `task-import` wrote
   exactly **one** document for the work — named after the **first** marker line's item
   id, under that provider's `{username}` ([`task-import`](../task-import/SKILL.md)
   "Both providers" step 2). Re-deriving that location inside each branch is what broke
   multi-provider sync: the Recoble email local part and the Teamer keyring local part
   need not match, so every branch after the first globbed a directory and an id that do
   not exist, hit its "not found" stop, and the second target silently never received
   its summary. Glob across the user directories by the **first line's** id instead —
   the id is enough, and nothing here needs a `{username}` at all.

   Read that id (its own call — a marker line's id may itself contain `:`, so take
   everything from the third field on):

   ```bash
   head -1 .claude/vway-kit/.vdev/alm | cut -d: -f3-
   ```

   Then fill it in below. `DOC_ID` is written out rather than piped in because a shell
   variable does not survive into the next call, and an empty one would glob
   `docs/tasks/*/_*.md` and report "no document" for a document that is there:

   ```bash
   DOC_ID=            # ← 위 출력. 마커가 없는 직접 re-sync 면 사용자가 준 task id.
   [ -n "$DOC_ID" ] || { echo "MISSING: DOC_ID 미확정 — 위 명령의 출력이나 인자로 채운다"; exit 1; }
   ls docs/tasks/*/"${DOC_ID}"_*.md || { echo "MISSING: docs/tasks/*/${DOC_ID}_*.md"; exit 1; }
   ```

   Exactly one path → that is **the** document for every branch below. Several → report
   them and stop; picking one writes another task's summary onto the item. `MISSING:` →
   tell the user and stop, and do **not** retry with a later marker line's id: the
   document is named after the first line, so a hit on a later id is a *previous* run's
   document and writing its summary here is the same mistake as guessing among several.

   **Each branch keeps its own `{task_id}`** — the item id on **that branch's own marker
   line**, not the document's name. They differ whenever the providers were linked to
   different ids, which is exactly the multi-provider case: searching Teamer with the
   Recoble item id finds nothing and stops the branch, which is the same defect one step
   further along. With no marker (direct re-sync) there is one id, the argument.

   **Worklog** — once per run, after the document is resolved and before any branch:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/worklog.py" measure --task-doc "<위에서 찾은 문서 경로>"
   ```

   Work that lived in a `git worktree` adds `--root <그 worktree 경로>` — the default root is
   the shell's tree, and the work branch's transcripts and reflog belong to the worktree.
   Keep the JSON for every branch below; relay each `warnings` line and continue — it never
   stops the sync.
   - `started` (present whenever the document carries `**Created:**`) feeds the
     `${started}` token.
   - `enabled: true` — `alm.worklog` is on. Add `**Completed:** <completed>` and
     `**AI Agent 활동:** <active>` under the document's `## Overview`, and the summary
     carries the Worklog section (step 4). `alm.worklog` 가 없거나 false 면 `enabled: false`
     — no section, no Overview lines.

### Recoble branch

- R0. **Resolve the tool prefix**, once per line's space —
  [`task-import/references/recoble-server.md`](../task-import/references/recoble-server.md).
  The marker records the space, not the server, so the host may have moved between the
  local-scope server and a claude.ai connector since the import. Unresolvable → report
  one line, skip this line, continue with the next.
- R1. **The task document** is the one step 0 already resolved. Do **not** re-derive it
  from `get_connection_info`'s `user.email` — that lookup is what made this branch abort
  whenever another provider's line came first.
- R2. **Resolve the handoff kinds for Recoble** —
  `python "${CLAUDE_PLUGIN_ROOT}/scripts/handoff_resolve.py" "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --provider recoble`.
  Output is `{provider, configured, kinds, warnings}`; each element of `kinds` is
  `{kind, provider, author, field, value, source_mode, write_mode, template_path,
  instruction}` — `value` is what a `literal` kind writes verbatim. Relay every
  `warnings` line to the user and continue: it names a host template still sitting at
  the old repo-root `templates/`, which means the shipped structure is going out
  instead of theirs until `/vdev-init` runs again.
  **`kinds` empty means two different things — `configured` tells them apart.**
  `configured: false` (no `handoff` config at all) → the legacy behaviour: one `summary`
  kind with `field: comment`, following the shipped `templates/handoff/summary.md`
  (or the host's copy under `.claude/vway-kit/templates/`, which wins).
  `configured: true` with empty `kinds` → no kind targets Recoble: either each names
  another provider (`field: {teamer: …}`), or each is a `literal` whose string `field` is
  Teamer vocabulary. **Write nothing** and say so — both are the user declaring Recoble is
  not a target, and posting a summary anyway writes where they forbade it. Name which of
  the two it was, so a user who only enabled `done_flag`/`done_date` is not told their
  config points somewhere else.
- R3. **Generate content per kind** by `source_mode` — the Teamer branch's step 4
  verbatim, markup and author line and template included. Only R4's write differs.
- R4. **Write each kind to its target.** Show a preview of every kind and ask for
  confirmation before the first write. **Call `get_workboard_item(itemId)` first** —
  every non-comment target needs something from it (the current body, the existing
  `customFields`, and `projectId`, which is the `workboardId` the field lookup needs;
  the configured `spaces[<space>].workboard` is the item-creation board and is the
  wrong one whenever the item lives elsewhere).

  | `field` | call | notes |
  |---|---|---|
  | `comment` | `create_workboard_item_comment(itemId, content)` | Always effectively append — a comment is new every time |
  | `description` | `update_workboard_item(itemId, description=…)` | The API **replaces the whole body**, so append means concatenating onto what the read returned. Skipping the read destroys the existing body. Format is [item-body](../task-import/references/item-body.md) |
  | `custom:<필드-key>` | `list_workboard_fields(projectId)` → `update_workboard_item(itemId, customFields=…)` | The suffix is the field **`key`**, not its `id`. Only the keys you send are kept, so merge the item's existing `customFields` in |
  | `priority` · `startDate` · `endDate` · `category` | `update_workboard_item(itemId, <name>=…)` | `literal` source only — an AI-written paragraph in a date field is not a value |

  `custom:` needs the field's `type` checked first: long prose goes only into
  `RICH_EDITOR`. `LABELS`/`DROPDOWN` hold values from `options`, and anything outside
  that list becomes a ghost value the UI dropdown cannot show — **skip that kind and
  warn**. An unrecognized `field` is a config error, not a target: report the kind and
  the value, skip it, and continue with the rest.

  `progress` is **not** a usable target here — R5 sets it to 100 unconditionally, so a
  kind aiming at it would be overwritten moments later. Say that and skip it.
- R5. **Move to 구현 완료** — `update_workboard_item` with `itemId`, `progress: 100`, and
  `status` = the first of `status_review`, `status_done` that is both configured **and**
  present on that item's board — a configured key the board does not carry is warned about
  and passed over, never silently swapped. Key resolution and the forward-only judgement
  live in
  [`task-import/references/recoble-status.md`](../task-import/references/recoble-status.md).
  The board is R4's `get_workboard_item` `projectId` — when R2 wrote nothing and R4 never
  ran, call it here. Neither key configured → send no `status` at all — a wrong status key
  is worse than an unchanged one.
- R5b. **기능 설계 본문 갱신** — 이 스페이스에 `feature_design` 계층이 선언됐을 때만. 설계 항목은
  기능마다 하나라, 이번 작업의 확정 내용이 여기 모여야 저장소 밖 독자가 설계를 읽음.

  계층부터 해석함(R6 은 자기 출력 파일을 따로 씀):

  ```bash
  SPACE=            # ← R0 이 해석한 이번 실행의 Recoble 스페이스 키
  [ -n "${SPACE:-}" ] || { echo "SPACE 미확정 — 스페이스를 먼저 해석하라"; exit 1; }
  python "${CLAUDE_PLUGIN_ROOT}/scripts/alm_layers.py" \
    "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --space "$SPACE"
  ```

  `errors` 가 있으면 그 줄을 R7 에 싣고 R5b 를 건너뜀. `feature_design: true` 인 계층이 없거나
  그 계층의 `template` 이 `null` 이면 건너뜀 — 절을 모르면 무엇이 큰 틀인지 판정할 수 없고,
  판정 없이 묻지 않는 전체 교체를 하면 사람이 쓴 설계를 날림.

  1. **큰 틀부터 찾음** — `list_link_types` 에서 `code` 가 `derives` 인 타입 id, 그다음
     `list_entity_links(entityType="task", entityId=<이 분기의 {task_id}>)`. 작업이 **target** 인
     derives 링크의 source 가 후보 — 요구사항·결함도 같은 모양이라 링크만으로는 못 가름.
  2. `list_workboards` 한 번으로 **모든** 계층의 `workboard` 를 풂 — `alm-trace` §2 와 같은 해석
     (id 먼저, 그다음 이름). 설계 계층의 이름이 둘 이상의 보드에 걸리거나 설계 계층의 보드가
     다른 계층의 보드와 같으면 **못 품** — R5b 를 건너뛰고 경고. 보드로 가르지 못하면 요구사항·
     결함 항목이 필터를 통과해 설계 본문으로 덮임. 풀리면 후보마다 `get_workboard_item` 의
     `projectId` 가 설계 보드인 것만 설계 항목으로 남김.
  3. 설계 항목마다 현재 본문을 읽음. 그 계층 `template` 의 절이 없거나 비었으면 — 옛 변경 단위
     본문 포함 — **큰 틀이 없는 것**: 기능 조사부터 함. 항목마다 `general-purpose` 에이전트
     하나를 한 메시지에 모아 띄움, **`sonnet`**, 지시는
     [`alm-trace/references/feature-survey.md`](../alm-trace/references/feature-survey.md).
     넘기는 것: 기능·모듈 이름(그 항목의 `fields.feature`·`fields.module` 라벨 값, 없으면 제목
     `[모듈] 기능명`) · 설계 계층 `template` 경로 · 호스트 저장소 루트 · 현재 본문. 기능 이름을
     못 정하면 그 항목을 건너뜀 — 엉뚱한 기능의 조사가 확인 없이 본문을 덮음. 돌아온 `---`
     위가 새 본문의 뼈대.
  4. 이번 작업이 바꾼 레이어 절만 새로 씀. 근거 순서: 호스트 설계 문서(`docs/sds/`)의 그 기능
     부분 → 작업 문서의 확정 내용(구현 계획·구현 결과). 바뀌지 않은 절은 그대로 둠. 규칙은
     [`task-import/references/item-body.md`](../task-import/references/item-body.md) — 저장소
     문서를 링크하지 않고 내용을 담음.
  5. `update_workboard_item(itemId, description=…)` 로 **전체 교체** — API 가 본문 전체를 바꿈.
     R4 의 append 와 달리 이어붙이지 않음: 설계서는 누적 기록이 아니라 현재 모습.

  묻지 않음 — `alm.auto` 무인 흐름에 프롬프트가 생기면 안 됨. 바뀐 절 안에서는 보드에서 사람이
  고친 문장도 덮일 수 있음. 실패는 그 항목만 건너뛰고 R7 에 실음.
- R6. **Propagate to the parents** — `alm.recoble.propagate.enable` 이 true 일 때만.
  규칙은 [`references/recoble-propagation.md`](references/recoble-propagation.md).

  **시드는 이번 실행에서 끝남 판정을 새로 적은 항목 전부**, 집합으로. 상태가 `status_review`
  이상으로 옮겨진 항목과, 이번 실행이 `latest_result` 를 **적은** 케이스 계층 항목 — 값 무관.
  PASS 뿐 아니라 PASS → FAIL·BLOCKED 도 끝남 판정이 바뀐 것이고, 적었다는 사실로 가르면 이전
  값을 먼저 읽을 필요가 없음. 케이스 쪽이 빠지면 케이스만 처리한 실행에서 전파가 통째로 안 돎 —
  케이스는 상태 전이를 안 받고 필드만 쓰는데 상위 ratio 를 바꾸는 근거가 그 필드임.
  `--propagate` 는 인자 id 가 곧 그 케이스들.

  순회는 위임함. 계층 해석과 잔재 비움을 먼저 하고 — `rm -rf && mkdir -p` 가 `fetch/` 뿐 아니라
  그 부모 `.vdev/` 도 만듦(`-p`), 그래서 그다음 줄의 `layers.json` 리다이렉션이 `/vdev` Phase 4
  가 `.vdev` 를 통째로 지운 뒤에도 실패하지 않음:

  ```bash
  SPACE=            # ← R0 이 해석한 이번 실행의 Recoble 스페이스 키
  [ -n "${SPACE:-}" ] || { echo "SPACE 미확정 — 스페이스를 먼저 해석하라"; exit 1; }
  rm -rf "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/.vdev/fetch" \
    && mkdir -p "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/.vdev/fetch"
  python "${CLAUDE_PLUGIN_ROOT}/scripts/alm_layers.py" \
    "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --space "$SPACE" \
    > "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/.vdev/layers.json"
  ```

  그다음 invoke skill `alm-fetch` — 인자는 R0 이 해석한 **도구 접두**, 시드 집합, `propagate` 블록,
  계층 선언 경로, 출력 경로 `.claude/vway-kit/.vdev/fetch/<space>.json`, 전파 문서 경로
  `${CLAUDE_PLUGIN_ROOT}/skills/task-sync/references/recoble-propagation.md`, 스키마 문서 경로
  `${CLAUDE_PLUGIN_ROOT}/skills/alm-fetch/references/plan-schema.md`. 디렉터리를 여기서 만드는
  이유는 fetch 에 `Bash` 가 없어서임.

  돌아오면 검산함. **계획 파일이 아니라 이 출력을 읽음** — 계획을 읽으면 위임이 없앤
  원본을 다시 들이는 것과 같음:

  ```bash
  python "${CLAUDE_PLUGIN_ROOT}/scripts/alm_plan_check.py" \
    "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/.vdev/fetch/<space>.json" \
    --layers "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/.vdev/layers.json" \
    --config "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml"
  ```

  전파 전용 모드면 이 명령 끝에 `--status-off` 를 붙임 — config 의 `status` 가 무엇이든 상태
  제안이 든 계획을 `3` 으로 막음(fork 가 `off` 를 어겼거나 인자에서 빠진 경우).

  종료 코드 `0` 이면 진행하고 stderr 경고(fork 값과 도출값의 불일치)는 R7 보고에 옮김,
  `3` 이면 **중단**하고 사유를 보고함 — 계획이 틀렸다는 것은 무엇이 맞는지 모른다는 뜻이라 같은
  그래프를 다시 읽어도 근거가 없음. 그 밖의 비영 코드는
  내부 오류이므로 경고하고 **`recoble-propagation.md` 의 「판정」 절을 직접 밟는 기존 경로로
  폴백**함. fetch 가 죽거나 계획 파일이 없거나 필수 최상위 키를 못 갖췄어도 같은 폴백임 —
  `entries: []` 뿐인 스키마 완전 계획은 폴백이 아니라 정상 종료(할 일 없음).

  `propagate.status: ask` 일 때만 ask the user (structured choice) 로 승인받음 — 바뀔 항목을 전부 모아 한
  번에 보여줌. `all-done` 은 묻지 않음 — `alm.auto` 무인 흐름에 프롬프트가 생기면 안 됨.

  승인 뒤 쓰기는 `depends_on` 위상 순으로 **아래부터**. 순서를 안 지키면 "상위 닫힘 / 하위
  열림" 이 남고, 그것이 전파가 하위→상위 한 방향인 이유임. **쓰기 직전 `get_workboard_item`
  으로 `current` 를 재대조**함 — 전진 판정의 근거는 쓰기 직전 상태이고 계획의 값은 순회 시점
  것이라, 그 사이 사람이 항목을 옮겼으면 강등이 써짐. **재대조가 어긋나거나 쓰기 응답이
  `proposed` 와 어긋나면 그 쓰기를 실패로 세고 건너뛰고, `depends_on` 을 타고 그 위를 버림.**
- R7. Report the item name, the new status, and **which server R0 adopted**, plus each
  design item R5b rewrote with the sections it changed, or why it was skipped. A run that
  stopped at 검토 reports the next step with it — 완료 comes after verification, through
  the `--verified` mode below. Without that line 검토 becomes the terminus. A `401`
  means that server is not signed in: name the fix for the path it came from
  ([`task-import/references/recoble-server.md`](../task-import/references/recoble-server.md)
  "401") and stop this line — other marker lines still run.

The `handoff` config is shared, but the field vocabulary is not: `colXX`/`item_content`
are Teamer's, so a bare string `field` reads as Teamer's while Recoble takes its
default target (a comment) — except for a `literal` (a kind carrying `value`), which does
**not** take that fallback: it says put this value in that field, not say this out loud, so
reaching Recoble at all needs a `field: {recoble: …}` naming the target.
`handoff_resolve.py --provider` is what flattens the two;
the config shape lives in [`vdev-config.example.yaml`](../../vdev-config.example.yaml).

#### 검증 완료 모드 (`--verified`)

Recoble only — a Teamer-only host is turned away by the routing above, before R0. Runs
after an E2E/UI verification PASS. Two things — the
`status_done` transition and R6 propagation. **No re-run of R2–R4**: a comment is always
an append, so each verification would leave another summary behind. R5b does not run
either — a verification changes no design.

- R0 still runs — it is what resolves the tool prefix. The space is the one the argument's
  item belongs to; when that cannot be settled, `alm.recoble.default`.
- The items come from the argument's ids — `get_workboard_item` hands back each one's
  board (`projectId`) and current status in one call. A miss there falls to step 0's own Recoble
  recovery (board search, then the user settling it); the task document is not consulted.
- No 완료 without evidence. Evidence is this session's
  [`integration`](../integration/SKILL.md) §3.4 verdict, or a verification result the user
  states. Projects with no machine verdict (Electron main process · non-web · a Docs-tier
  change) have only the second — do not refuse the mode for want of the first.
- Approval required — ask the user (structured choice) carrying every item's name, board and current
  status **in one question**. The one place a person catches a resolution that picked the
  wrong item; one list beats N questions, and N questions is what gets skipped.
- **A case-layer item takes no status transition.** Where the space declares layers and
  the item sits on a layer whose `fields` map `latest_result`, write that field (and
  `latest_run` with the round's key — the round this session's
  [`integration`](../integration/SKILL.md) §3.5 created in this session; no round, no
  `latest_run`)
  instead of moving the status. The status axis is
  forward-only, so a case that moves PASS → FAIL on a later round cannot record it there —
  the field is the only place a regression survives.
- **필드가 없으면 세 갈래**: 만들고 계속(`create_workboard_field`, 승인 필요) / 없이 계속
  (그 항목의 판정은 안 남고 그 사실을 보고) / 중단. 보드 스키마는 팀 전체에 보이므로 조용한
  생성 금지.
- Same forward-only judgement as every other transition. A skipped transition changes
  nothing, so R6 does not run either. A person asked for this one, so say why nothing
  moved — `status_done` unset counts as a reason worth reporting here, unlike an
  automatic transition.
- Report as R7 does, **한 줄이 아니라 목록** — 항목마다 이름·새 상태(케이스는 쓴 필드 값), 그리고
  R0 이 채택한 서버. 일괄로 받았으니 보고도 일괄이어야 무엇이 안 움직였는지가 보임.

#### 전파 전용 모드 (`--propagate`)

Recoble only — 라우팅은 `--verified` 와 같음. 검증 회차가 케이스 결과를 적은 뒤
[`integration`](../integration/SKILL.md) §3.6 이 부름. **사실만 씀** — 상위의 `progress`·
`coverage_status`.

- R0 → R6 → R7. step 0 마커·작업 문서 해석·R1–R5b 없음 — 요약 댓글을 다시 달지 않고, 인자
  항목의 상태도 안 옮김. R0 의 스페이스는 **검증 완료 모드**와 같은 규칙.
- 인자 id 는 호출자가 방금 `latest_result` 를 적은 케이스 — 여럿 받음. 그 집합이 R6 시드.
- R6 을 그대로 밟되 `alm-fetch` 에 넘기는 `propagate` 블록의 `status` 를 `off` 로 바꿔 넘김 —
  상태 제안도, 그 제안에 기댄 자기 예측도 없음. 검산은 R6 이 `--status-off` 를 붙여 돌림 —
  fork 가 `off` 를 어겨도 거기서 막힘. 폴백 경로에서도 상태는 안 씀.
- 묻는 단계 없음 — 옮길 상태가 없어 `propagate.status: ask` 게이트가 설 자리가 없음. 케이스
  `latest_result` 는 [`integration`](../integration/SKILL.md) §3.4 의 기계 판정이고 사람 승인이
  명시된 것은 회차 `result` 뿐이라, 상태를 올리는 일은 사람이 고른 항목을 받는 `--verified` 몫.
- `propagate.enable` 이 false 면 R6 이 원래대로 건너뛰므로 그 사실만 보고.
- 보고는 R7 처럼 **목록** — 항목마다 이름·새 progress·새 `coverage_status`, 그리고 R0 이 채택한
  서버.

### Teamer branch

1. **자격증명 확인 (keyring)**
   - Teamer 자격증명은 OS 키체인(keyring)에서 스크립트가 직접 읽음(평문 파일·모델 컨텍스트 노출 금지). 스킬은 id/pw 미취급.
   - 6·8단계의 스크립트가 미설정 시 안내를 출력하면, 사용자에게 터미널에서 `python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" setup` 실행을 안내하고 중단.

2. **Task document and `{task_id}`** — the document is the one step 0 resolved. Do
   **not** re-derive it from `teamer_api.py whoami`: the Teamer keyring local part and the
   Recoble email local part need not match, so that lookup aborted this branch whenever
   Recoble's line came first. (`whoami` is still the right call wherever the Teamer *user*
   is what is needed.) **`{task_id}` for steps 6 and 8 is this marker line's item id** —
   the Teamer one — and not the document's name, which carries the *first* line's id and
   would search Teamer for a Recoble item. No marker and an argument instead → that
   argument is the id; no id at all → ask the user.

3. **Resolve handoff kinds**
   - Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/handoff_resolve.py" "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --provider teamer`
   - Result is `{provider, configured, kinds, warnings}`; each element of `kinds` is
     `{kind, provider, author, field, value, source_mode, write_mode, template_path, instruction}`.
     Relay every `warnings` line and continue (same meaning as R2's).
   - **`kinds` empty means two different things — `configured` tells them apart.**
     `configured: false` (no `handoff` config) → legacy behavior: generate the AI
     summary using the structure in the shipped `templates/handoff/summary.md` — or the
     host's copy under `.claude/vway-kit/templates/`, which wins — and append to
     `item_content` (same as before). `configured: true` with empty `kinds` → every
     kind is aimed at another provider. **Write no content** and say so — a
     `field: {recoble: …}` is the user declaring that Teamer is not a content target.
     Skip step 4, but **still run 6–8**: the item is this task's either way, and the
     workflow status is not handoff content. Pass an **empty** `--content-file` —
     `append_item_content` concatenates it onto the existing body, so an empty one
     leaves `item_content` byte-identical while the status transition goes through.

4. **Generate content per handoff kind**
   For each resolved kind, produce Markdown content by `source_mode`:
   - `ai_auto`: AI generates content from the task document. If `template_path` is set, read that file and follow its structure; otherwise apply `instruction`. If **both** are absent (e.g., template file missing so `template_path` is null and no `instruction` configured), warn the user and fall back to a generic task-document summary. (summary kind lands here — `handoff_resolve.py` auto-discovers `handoff/summary.md` — the host's copy under `.claude/vway-kit/templates/` first, else the shipped one — as `template_path` even when `template:` is omitted in config, so summary always has a structure. A `template:` written in config wins over that.)
     For the `summary` kind with step 0's Worklog `enabled: true`, end the content with the
     template's `Worklog` section filled verbatim from step 0's Worklog — `started`,
     `completed`, `active` — and drop its `AI Agent 활동` line when `active` is absent;
     never compute a time yourself.
   - `ai_guided`: ask the user for guidance (free text), e.g. "이 handoff 에서 강조할 내용이나 추가 지침을 입력해 주세요." Then AI generates following `template_path`/`instruction` + the guidance. If both `template_path` and `instruction` are absent, warn the user and fall back to a generic task-document summary before applying the guidance.
   - `human_ask`: ask the user for the content text directly (free text), e.g. "이 handoff ({kind}) 에 들어갈 인수인계 내용을 입력해 주세요." Use the input verbatim.
   - `human_doc`: read the `## Handoff (<Kind>)` section's **Content** from the task document; use it verbatim (from the `**Content:**` line to the next `##` heading or end of file, excluding `**Author:**`). (`<Kind>` is the config kind uppercased, e.g. `qa` → `QA`; match the header case-insensitively.) If the section is missing, warn and skip this kind.
   - `literal`: skip AI generation, the question and the template entirely. Use the resolved `value` verbatim. Replace the token `${today}` with the execution date in `YYYY-MM-DD` format and `${started}` with the first 10 characters of step 0's Worklog `started` — no `started` means that kind is skipped with one warning, never a guessed date; leave any other text as-is. **Do NOT add the author line** — literal values (dates, flags) must be the raw value so ALM field types are not broken by extra text.
   - Close every generated content (ai_auto / ai_guided / human_ask / human_doc — NOT literal) with the author line, on its own last line:
     ```markdown
     _Author: {author} ({YYYY-MM-DD})_
     ```
   - If `author` is empty, omit the line entirely (do not render `_Author:  (date)_`).
   - Show a preview of all kinds to the user and ask for confirmation.

5. **Classify by field/write_mode**
   - `field == item_content`: queue for `item_content` (the update script always appends item_content; for an `item_content` replace, the col path is N/A — item_content is append-only at the API layer).
   - else with `write_mode == replace`: write the content/value to a temp file and add `--col-override <field>=<tmpfile>`.
   - else with `write_mode == append`: write the content/value to a temp file and add `--col-append <field>=<tmpfile>`.
   - **Note:** a single field should not be targeted by both replace and append in one sync — if it is, the append (based on the GET original value) takes effect and the replace is discarded.

6. **Teamer 항목 검색**
   - `vdev-config.alm.teamer` 의 `project_no` / `workitem_no`(구 config 는 최상위
     `teamer:`)를 읽어 호출:
     ```bash
     python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" search \
       --project-no <project_no> --workitem-no <workitem_no> --text {task_id}
     ```
   - 출력 `[{item_no,item_id,item_title,item_content,status_name}]` 에서 `item_no`·`item_title`·`status_name` 추출.
   - 결과가 여러 개면 사용자 선택. 없으면 알리고 중단.
   - **필드 보존·item_content append 는 8단계의 `update` 스크립트가 내부 수행**(스킬은 보존 로직 미취급).

7. **Determine workflow status**
   - If current `status_name` is "진행" (Progress): auto-set to "검토" (Review) — pass `--target-status-name 검토` to the update script (8단계) which resolves the actual status_no via workflow API.
   - Otherwise: show current status to user and ask whether to change

8. **Teamer 항목 업데이트**
   - 생성한 본문(append 대상)은 임시 파일에 쓰고, 각 col override 도 임시 파일로 쓴 뒤 스크립트를 호출함:
     ```bash
     python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" update \
       --project-no <project_no> --workitem-no <workitem_no> \
       --item-no <item_no> --searchtext {task_id} \
       --content-file <tmp_content.md> \
       [--col-override col22=<tmp_col22.md> ...] \
       [--col-append col33=<tmp_col33.md> ...] \
       [--target-status-name 검토 --workflow-no <alm.teamer.workflow_no>]
     ```
   - `update` 가 내부에서 GET→non-null colXX 보존→item_content append→(target-status-name 있으면)status 해석→multipart PUT 수행.
   - 출력 `{item_id,item_title,item_workflow_status_no,mode}` 로 성공 보고. 자격증명 미설정 안내가 출력되면 1단계 안내 후 중단.

## API Notes

- PUT uses **`multipart/form-data`** format (`itemVO.xxx` field names)
- **Non-ASCII encoding**: `teamer_api.py` 가 Python `urllib` 로 UTF-8 multipart 바디를 직접 만들어 보낸다(curl/Node 불필요).
- Auth: `Authorization: Bearer {token}` header + `Cookie: Admin-Token={token}` both required
- **Field preservation required**: omitted fields reset to null on PUT. Always include non-null fields from GET (especially `colXX` date/status fields)

## Summary Structure

The AI summary (summary kind, `ai_auto`) follows the structure defined in the shipped
`templates/handoff/summary.md` — one file for every target, both providers. It is the SSOT
for the 3-section structure (Implementation / Verification / Notes) and all authoring rules
(atomic item, self-contained bullet, summarize-not-enumerate, language convention, etc.),
so a rule change edits it alone. A host that keeps its own
`.claude/vway-kit/templates/handoff/summary.md` overrides the shipped one.
Who reads each section, and the rule against linking repo documents, live in
[`task-import/references/item-body.md`](../task-import/references/item-body.md).
