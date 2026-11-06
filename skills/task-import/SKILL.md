---
name: task-import
description: The ALM-import sub-step /vdev invokes when a task is linked to an ALM — pulls a Recoble workboard item or Teamer item's context, or opens a new one, and scaffolds the task doc. Not usually invoked directly.
argument-hint: "[task_id]"
---

# /task-import - import ALM context and scaffold the task file / usage: [task_id]

## Purpose
Attach the task to an ALM item and create a skeleton task file — Content filled,
analysis and plan left as placeholders for a downstream step to complete.

`/vdev` Phase 0 already decided **which providers** to invoke this skill for
(`alm.auto` or an explicit link request) — by the time task-import runs, linkage is
decided. Its only job here is choosing pull vs push per provider; the deliverable is
the same either way, only where Content comes from differs.

A `recoble` space with `layers` declared routes to
[`alm-trace`](../alm-trace/SKILL.md) instead — [`/vdev` Phase 0](../vdev/SKILL.md)
makes that call. This document stays the marker format's SSOT either way.

**호스트 규약 문서를 먼저 읽음.** `vdev-config` 의 `issue_tracker_guide` 가 가리키는 파일이 있으면
읽고, 그 안의 프로젝트 고유 사실(보드 구분 · 라벨 옵션 규약 · 항목 제목 규약)을 이 문서의
일반론보다 우선함 — `commit` 스킬이 `commit_guide` 를 쓰는 것과 같은 꼴. 키가 없거나 파일이
없으면 그대로 진행(정상 경로). 기계가 판정에 쓰는 값은 그 문서가 아니라 config 가 듦.

**Provider is a list, even when it holds one entry.** Run the branch below once per
provider, in the order given, and append one marker line per success. A provider that
reports and stops costs you that provider and nothing else — the others still run,
and the work proceeds regardless.

| Mode | When | What it does |
|---|---|---|
| **pull** | the request **asks to fetch** and names an item (e.g. "DEV-0952 Teamer 에서 가져와") | read that item, fill Content from it |
| **push** | anything else — `/vdev` already decided to link, so there is nothing left to gate on | **Recoble only**: create a new item from the request text. **Teamer is pull-only** — it reports one line and is skipped, so a `[recoble, teamer]` push links Recoble alone (see the Teamer branch) |

`/vdev DEV-0952` — an id-shaped token with no "fetch" ask — is **push**. Treating
the shape alone as a fetch trigger is exactly the behaviour this skill dropped.

## Arguments
- `$ARGUMENTS` : the request text (free text, or an item id when pulling).
  Prompt the user if omitted.

Provider and space come from `vdev-config.alm`, resolved by
[`/vdev` Phase 0](../vdev/SKILL.md). When invoked directly, resolve them the same
way.

## Execution

### Recoble (provider = `recoble`)

1. **Resolve the space** — `alm.recoble.spaces[<space>]`. Missing space key → report
   one line and stop (no marker written). Its MCP server is `recoble-<space>`, so every
   tool below is `mcp__recoble-<space>__<tool>` — **unless that name does not exist on
   this host**, which is a connector setup, not an absence:
   [`references/recoble-server.md`](references/recoble-server.md) resolves the real tool
   prefix before the first call, and a run it cannot resolve stops this provider there.
2. **Resolve the workboard** — call `list_workboards` and match
   `alm.recoble.spaces[<space>].workboard` against the id, then the name.
   - A `401`/unauthorized error means the server is not signed in: name the fix for
     the path that resolved it ([`references/recoble-server.md`](references/recoble-server.md)
     "401"), then stop.
   - No match → report the configured value and the available names, then stop.
   - **More than one board carries that name → stop too**, showing both ids and asking
     for the id in `workboard`. Nothing makes a board name unique inside a space, and
     picking either one puts the item on a board the user never chose — silently,
     because both runs look successful.
3. **Get the item.**
   - **pull**: `list_workboard_items` on that workboard — **always narrowed**, since
     the tool's own description warns that a large board fails on response size.
     There is no name/id filter, so narrow by recency: `sort: "created"` (newest
     first) with `limit: 30`, and match the id **or name** the user gave in the
     returned page.
     **A miss is not "no such item"** — the item may be older than the page.
     Walk back with `createdBefore` = the oldest returned item's creation timestamp
     and repeat, at most twice. Still not found → say exactly that (id, workboard,
     how many items were scanned), ask the user to confirm the id or give the item's
     approximate date, and stop — do not fall back to push, and write no marker.
     Content = the matched item's `description`.
   - **push**: `create_workboard_item` with `workboardId`, `name` = a one-line
     summary of the request, `description` = the full request text. **No `status`** —
     an item created without one lands on the board's entry status (= 시작 전).
     Title format:
     [`references/recoble-status.md`](references/recoble-status.md) "항목 제목".
     Content = the request text verbatim, no template. Failure → report one
     line and stop (no marker written).
4. **Resolve `{username}`** — `get_connection_info` returns `user.email`; take the
   local part (before `@`). `bsyu@vwaycorp.com` → `bsyu`. A `401` here means the
   same as step 2 — not signed in.
5. **Move to 착수** — `update_workboard_item(itemId, status=status_start)`, pull and push
   alike. Key resolution, existence check and the forward-only judgement live in
   [`references/recoble-status.md`](references/recoble-status.md) "전이 판정" — a backward
   move is skipped with one warning. That is what keeps a re-run from dragging an item a
   person moved to 검토 or 완료 back to 진행 중. A failed transition does not stop this
   provider — the item is already secured.

Then continue with "Both providers" below.

### Teamer (provider = `teamer`)

0. **Mode check — Teamer is pull-only.** It has no create path here: the only call
   this branch makes is `search --text <item-id>`, which needs an id the request
   did not give. So in **push** mode (no fetch ask / no item id), report one line —
   `Teamer 는 pull 전용입니다 — 가져올 항목 id 를 함께 주세요 (예: "DEV-0952 티머에서
   가져와"). Teamer 연동만 건너뜁니다.` — and **stop this provider without writing a
   marker line**. Do not create an item, and do not fall back to Recoble; the remaining
   providers still run, and if none links, `/vdev` Phase 4 skips the sync naturally.
   (ALM never blocks the work — the request proceeds with whatever linked.)
1. **자격증명 확인 (keyring)** — Teamer 자격증명은 OS 키체인(keyring)에서 스크립트가
   직접 읽음(평문 파일·모델 컨텍스트 노출 금지). 스킬은 id/pw 미취급.
   미설정이면 다음 단계의 `search` 가 안내 메시지를 출력하므로, 사용자에게 터미널에서
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" setup` 을 실행하도록 안내하고
   중단.
2. **Teamer 검색** — `vdev-config.alm.teamer` 의 `project_no` / `workitem_no` 를 읽어
   스크립트 직접 호출(구 config 는 최상위 `teamer:` 를 읽음):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" search \
     --project-no <project_no> --workitem-no <workitem_no> --text <item-id>
   ```
   출력은 최소 JSON 배열 `[{item_no,item_id,item_title,item_content,status_name}]`.
   자격증명 미설정 안내가 출력되면 1단계 안내 후 중단. 결과가 비었으면 알리고 중단.
   (Teamer 는 pull 전용 — 새 항목 생성 안 함.)
3. Extract `Item ID`, `Title` and `Content`.
4. **Resolve `{username}`** — `python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" whoami`
   의 `{"username": "..."}` 를 파싱해 씀. 스크립트가 keyring id 의 로컬파트를
   반환하므로 스킬은 전체 id·비밀번호·토큰 미취급.

Then continue with "Both providers" below.

### Both providers

Reached only when the branch above secured an item. Its own numbering — a branch
that reported and stopped never gets here, and writes nothing.

**Step 1 runs per provider; steps 2–4 run once, after every provider is done.** The
marker collects a line per linked item, but there is exactly one task document for the
work — running the scaffold twice would write it under two `{username}` directories
(the Recoble email local part and the Teamer keyring local part need not match) or
overwrite the first pass and append the handoff sections twice.

1. **Write the marker.** This is the **single definition** of the marker's format;
   `/vdev` Phase 0 · Phase 4 and [`task-sync`](../task-sync/SKILL.md) point here
   rather than restate it. **One line per linked item**, `<provider>:<space>:<item_id>`
   — `<provider>` is `recoble` or `teamer`, and `<space>` is the Recoble space key or
   `-` for Teamer (it has no spaces). A single-provider run writes one line; a
   multi-provider run appends one line per provider that succeeded, so a marker with
   fewer lines than providers is the normal record of a partial link.
   Self-contained, and it does not assume the directory exists:
   ```bash
   tr -d '\r' 2>/dev/null < .gitignore | grep -qxF '.claude/vway-kit/.vdev/' || printf '\n.claude/vway-kit/.vdev/\n' >> .gitignore
   mkdir -p .claude/vway-kit/.vdev
   printf '%s\n' 'recoble:labs:ITEM-123' >> .claude/vway-kit/.vdev/alm   # 값은 실제 해석 결과로
   ```
   `>>` is deliberate — each provider appends its own line. Its absence is how `/vdev`
   Phase 4 knows to skip the sync, so **never** write it speculatively. The marker
   describes **one run only**: `/vdev` Phase 0 deletes any leftover before invoking this
   skill — when invoked directly, `rm -f` it yourself **once, before the first
   provider**, so a stopped import cannot leave a previous run's item to be closed.
2. **Resolve the naming inputs** — the task file name is **English**; translate a
  Korean title to concise English kebab-case (e.g. `DEV-0952_requirement-improvement`).
  For a push-mode item with no ALM id, use the item id Recoble returned. With more than
  one provider linked, name the document after the **first** marker line and use that
  provider's `{username}` — one document, one location.
  The **work branch is not cut here** — `/vdev` Phase 2 cuts it after the tier is
  confirmed. The task doc is
  untracked, so `git switch` carries it over.
3. Create the skeleton task file at `docs/tasks/{username}/{taskid}_{title}.md`
   using the template below — fill only `## Content`, leave the three `<!-- TODO -->`
   sections as placeholders, and create directories as needed.
   - Do not analyze the codebase or write a plan — task-import stops after writing
     the skeleton.
   - `**Created:**` is the local time in exactly `YYYY-MM-DD HH:MM` — `worklog.py` reads it
     as the task's start; any other shape costs the Worklog section and `${started}`. Take
     it from `date '+%Y-%m-%d %H:%M'` run now, never from memory: the context carries the
     date but not the time, and a guessed hour moves the whole measured window.
4. **Handoff sections**: run the resolver **once per linked provider** and take the
   **union** of the kinds by name —
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/handoff_resolve.py" "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --provider <provider>`
   (the output is `{provider, configured, kinds, warnings}` — relay each `warnings` line
   and continue). A kind targeted at only one provider
   still needs its section here: the section is where a **person** writes, and skipping
   it leaves `task-sync` hunting for a `## Handoff` block that was never created — that
   handoff can then never be delivered. For each kind with `source_mode == "human_doc"`,
   append a section to the task file:
   ```markdown
   ## Handoff ({Kind})
   **Author:** [작성 주체]
   **Content:**
   <!-- {instruction if present} -->
   ```
   (`{Kind}` = config kind rendered uppercase, e.g. `qa` → `QA`)
   Skip kinds whose `source_mode` is not `human_doc` (AI-written kinds and kinds that ask the user need no document section).

## Task File Template
File path: `docs/tasks/{username}/{taskid}_{title}.md`

```markdown
# Task: [task_id] - [Title]

## Overview
**Created:** [YYYY-MM-DD HH:MM]
**Author:** [username]
**Branch:** [/vdev Phase 2 가 확정 — 그때 채운다]

## Content
[Content from Teamer]

## Codebase Analysis
<!-- TODO: filled by a downstream step. Related existing code, reusable
     components (e.g., shared/common packages), duplication risk areas, and the
     SOLID/DRY application plan go here. -->

## Implementation Sequence
<!-- TODO: filled by a downstream step. Mermaid sequence diagram or flowchart of
     the implementation flow (component interactions, data flow, dependencies). -->

## Implementation Plan
<!-- TODO: filled by a downstream step. The detailed implementation plan. -->

## References
- **Source:** [Teamer Item URL]

<!-- ## Handoff (QA)  ← human_doc 종류가 config 에 있으면 task-import 가 삽입 -->

## Notes
[Additional observations]
```
