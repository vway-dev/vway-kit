---
name: alm-trace
description: The ALM step /vdev invokes when the host declares layer tracing — searches Recoble for a similar requirement, then creates and links only the missing layers (requirement → design → task → verification). Also entered directly with an existing item id to fill gaps under it. Not usually invoked directly.
argument-hint: "[요구사항 텍스트 | 항목 id]"
---

# /alm-trace - create the missing ALM layers and wire them together / usage: [요구사항 텍스트 | 항목 id]

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Purpose
Build the requirement → design → task → verification graph in Recoble, or fill only
the layers missing under an item that already exists. **The links are as much the
deliverable as the items** — `derives`/`verifies` is the path `task-sync`'s
propagation climbs, and a board full of unlinked items gives it nothing to walk.

A request about work that is already built is not new work: when a host declares a
`defect: true` layer, step 4 tells the two apart and routes a defect to that board with
a fix task under it, rather than opening a second requirement for a feature that
already has one.

**Boards are never created.** A layer names a board a person made beforehand, the
same rule the existing `workboard` key already carries; a typo that silently
conjured a ghost board is worse than stopping on the typo.

**Recoble only.** Teamer has no item-creation path, so on that provider report one
line and skip it — the shape [`task-import`](../task-import/SKILL.md) uses for its
pull-only branch.

## Arguments
- `$ARGUMENTS` : the requirement text, or an existing item id to fill gaps under.
  Prompt the user if omitted.

The space comes from `vdev-config.alm.recoble`, resolved by
[`/vdev` Phase 0](../vdev/SKILL.md). When invoked directly, resolve it the same way.

## Execution

### 1. Resolve the layers

```bash
SPACE=            # ← 이 실행의 Recoble 스페이스 키 (예: dev3)
[ -n "${SPACE:-}" ] || { echo "SPACE 미확정 — 스페이스를 먼저 해석하라"; exit 1; }
python "${CLAUDE_PLUGIN_ROOT}/scripts/alm_layers.py" \
  "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --space "$SPACE"
```

The guard earns its line: an unfilled `--space` falls back to `alm.recoble.default`,
and a host that has no such default answers `configured: false` — the run would then
report "this host does not trace layers" about a space it never looked at.

Read `{space, configured, errors, warnings, layers}`:

- **`errors` non-empty** → show those lines verbatim and **stop**. The host declared
  layers and the declaration does not describe a buildable graph; continuing past it
  puts items on boards nobody chose.
- **`configured: false`** → this host does not use layer tracing. Say so in one line
  and stop — [`task-import`](../task-import/SKILL.md) is that host's path.
- **`warnings`** → report and continue. Each names one thing that will not happen —
  a dropped link, a declaration nobody reads, a missing template, a host form still
  sitting at the old repo-root `templates/` — not a broken run.
- **`layers` is already topologically sorted.** Create in that order and every
  `derives_from`/`verifies` target already exists when its link is drawn.
- **`fields`** on a layer maps a role (`module`·`feature`·`latest_result`·…) to that
  board's own field key. The role names are fixed; the keys are the host's. Send values
  by looking the key up here — a role with no mapping is one this host does not track.
- **`run: true`** marks the layer where a verification round lands. It is reached only
  through the 회차 경로 below, never as a missing layer, and it carries no
  `derives`/`verifies` link — the resolver strips those and warns.
- **`feature_design: true`** marks the design layer as **one long-lived item per feature**,
  shared by every requirement and task that touches that feature. It stays linked by
  `derives` (requirement → design → task) but propagation never counts it — a shared item
  closed by one requirement's work would close every other requirement sharing it. So each
  layer deriving from it carries `direct_from`, the layer its items also link to directly;
  step 8 draws that link, and propagation climbs it. §5-1 is how the item is found or made.

### 1-1. 호스트 규약을 먼저 읽음

`vdev-config` 의 `issue_tracker_guide` 가 가리키는 문서가 있으면 읽고, 그 안의 프로젝트 고유
사실(보드를 그렇게 나눈 이유 · 라벨 옵션 규약 · suite 이름 규약 · 결함 승격 기준)을 이 문서의
일반론보다 **우선**함. `commit_guide` 를 `commit` 스킬이 쓰는 것과 같은 꼴. 키가 없거나 파일이
없으면 그대로 진행 — 정상 경로임.

```bash
python3 -X utf8 -c "import pathlib, yaml
p = pathlib.Path('.claude/vway-kit/config/vdev-config.yaml')
print((yaml.safe_load(p.read_text(encoding='utf-8')) or {}).get('issue_tracker_guide', ''))"
```

기계가 판정에 쓰는 값(`layers`·`fields`·보드 이름·상태 키)은 그 문서가 아니라 config 가 듦 —
산문에 둔 값은 파서가 없어 판정에서 통째로 빠짐.

### 1-2. 묻기 전에 조회

**항목이든 필드든 라벨 옵션이든, 만들지 묻기 전에 이미 있는지 먼저 조회.** 질문은 조회
결과를 담아 나감 — "만들까요" 가 아니라 "이것이 있는데 재사용할까요, 새로 만들까요".

조회 없이 물으면 같은 요구사항·기능·케이스가 이름만 달리해 두 번 생김. 중복은 보드에서
지우기 어렵고, 링크가 갈라져 커버리지 판정이 조용히 틀림. 대상은 요구사항 · 설계의
모듈·기능 라벨 옵션(`list_workboard_fields`) · 케이스 · 결함 · 커스텀 필드.

### 2. Resolve the boards

Resolve the tool prefix first, once
([`task-import/references/recoble-server.md`](../task-import/references/recoble-server.md)) —
`mcp__recoble-<space>__…` when that server exists, the connector's prefix when it does
not, and a stop when neither can be matched to the space's `mcp_url` uuid.

Then call `list_workboards` **once**, and resolve every layer's `workboard` out of that
single response into `{id, taskKey}`. One call, because the next step needs the whole
`taskKey` set at the same time.

- Match on `id` first, then `name`.
- No match → show the layer key, the value it was configured with, and the board
  names that do exist, then **stop**. Do not call `create_workboard`.
- **Two boards with that name → also stop**, showing the layer key and both ids, and
  ask for the id in that layer's `workboard`. A name is not unique inside a space, and
  here the wrong pick also mislabels every `derives`/`verifies` link drawn from it.
- **Two layers resolving to the same `taskKey` → stop** as well: step 3 reads an
  id-shaped token through that key, so a shared key makes the anchor unknowable.
- `401` is not-signed-in: name the fix for the path that resolved the prefix
  ([`task-import/references/recoble-server.md`](../task-import/references/recoble-server.md)
  "401"), then stop.

### 3. Decide the anchor

**The evidence is the `taskKey` set from step 2, not the token's shape.**

| `$ARGUMENTS` | reading |
|---|---|
| a single token matching `^<declared layer's taskKey>-<digits>$` | that layer's existing item is the anchor |
| such a token embedded in longer text | Ask the user (structured choice) — anchor, or a new requirement that merely quotes one? |
| matches no declared board's taskKey | free text |

This is why acting on an id-shaped argument does not revive "a task-id shape alone
calls the ALM": the keys come from this space's real boards, read a moment ago. A
token shaped like an id in a space whose boards do not use that key is text and nothing more.

### 4. Similarity scan — free text only

Skip it entirely when step 3 fixed the anchor by id; there is nothing to deduplicate
against a decision already made.

**Two boards are scanned, not one** — the `marker` layer's (what is already being
built) and a **root layer**'s (what was already asked for). A root is a layer with
neither `derives_from` nor `verifies`, that another layer derives from. Scanning only
the requirements board cannot tell a defect from a new requirement: a request about
behaviour that already has a task is a defect in that work, and it reads as a brand
new requirement to a scan that never looked at the task board.

Layer keys are free text, so either board can be absent:

- **0 roots** → nothing owns requirements here. Still scan the `marker` board; a hit
  there is what separates a defect from new work, which is the one judgement left.
- **2+ roots** → ask the user (structured choice) to pick which root's board to scan; the token
  named no owner, so a person does.
- **no `marker` layer** → scan the root board alone, and drop 결함 from the choices
  below: a defect's fix has no board to land on.

Dispatch one `general-purpose` agent **per board**, in a single message so they run
concurrently, each at **`sonnet`** and following
[`references/similarity-scan.md`](references/similarity-scan.md) with the request
text, **the tool prefix step 2 resolved**, that board's id, and what the board holds
(요구사항 / 작업) so its 유사 근거 column judges against the right thing. The prefix
is handed over rather than re-derived: the agent has no config to match a `mcp_url`
uuid against, so it would have to guess a server name.

A whole board's raw text is the largest input this skill pulls, which is both why the
scan is an agent — in this context it would crowd out the work that follows — and why
the model is named. A session above `sonnet` pays that text at its own rate for a
verdict the grade table already bounds; below it the grading thins, and what this scan
fails to surface is what nobody sees. Moving it either way is an edit to that one word.
A dedicated `agents/` file would only add a second place to record it, and could not
narrow `tools:` either — `mcp__…recoble…__…` names exist only once a host picks a
space.

Then ask the user (structured choice) — **기존 재사용 / 결함 / 신규 요구 / 중단**, with both boards'
candidates in the question, each labelled by which board it came from. Put an agent's
end-of-board verdict in there too whenever it did not finish: zero candidates from a
truncated scan is not the same answer as zero candidates from a complete one, and
treating them alike is how a duplicate requirement gets created.

**결함 is offered only when a layer declares `defect: true`** (step 1's output carries
it). Without that declaration the host has no board for defects, so offering the choice
would collect an answer nothing can act on.

**That answer is what fixes the anchor**, since free text arrives without one:

- **재사용** → the chosen candidate is the anchor.
- **결함** → the 결함 경로 below. Skip step 5 (§5-1 still runs).
- **신규 요구** → no anchor. Skip step 5 and take every declared layer **except the
  `defect: true` and `run: true` ones** as missing at step 6. A `feature_design` layer is
  not counted missing here — §5-1 decides whether its item exists.
- **중단** → end here, nothing created.

#### 결함 경로

Runs instead of step 5, then rejoins at §5-1 (step 6 when no layer is
`feature_design`). Two items are always created —
**결함** on the `defect: true` layer's board and **수정 작업** on the `marker` layer's
board, which carries the marker because it is what this run implements. Both take their
board, `template`, `status` and `category` from their own layer's declaration, so
step 7 creates them the same way it creates every other layer's item.

**What the defect attaches to comes from the scan, and one defect may attach to
several things.** A defect can violate more than one requirement and can span more
than one existing task, so the attachment set is a set, not a pick-one:

- **`high` candidates attach automatically**, all of them, from either board. The scan
  already produced a one-line 유사 근거 for each; re-asking about evidence that clear
  turns every defect into a questionnaire.
- **`medium` candidates are the ambiguous ones** — one question, ask the user (multi-select),
  naming the `high` ones in the question text as already attached so the person sees
  what they are adding to. **A question takes at most 4 options**, so when more
  than four candidates are `medium`, offer the four with the strongest 유사 근거 and name
  the rest in the question text. Nothing is attached without being either offered or
  named.
- **`low` candidates are neither offered nor attached** — step 11 lists them by name.
  A low is a board neighbour, not a claim, and putting one in the question spends the
  person's attention on the weakest evidence the run produced.
- **The requirement side is counted on its own.** When the attachment set ends up with
  no root-layer item — no `high` there and none chosen there — **create a requirement**
  and attach to that, however many task-board items were attached. Task hits are not a
  substitute: propagation reaches a requirement only through what hangs under it, so a
  defect that indicts three tasks and no requirement leaves that requirement free to
  close while the defect is still open.

Existing items are never duplicated or moved: a requirement from the scan is used as
it stands, and a `marker`-board candidate is the work that **broke**, not the 수정 작업.
Say that in step 6's table so nobody expects the old task to change.

Links (step 8 draws them, direction table cited there):

- 결함 --`verifies`--> each attached item — the same link the verification layer uses,
  because a defect is a verification that failed. Requirements and existing tasks take
  the same link; what the defect indicts does not change the relation.
- 결함 --`derives`--> 수정 작업 — defect above, fix below, so closing the fix rolls the
  defect up. Reversing it (`verifies`) would say the fix verifies the defect and the
  defect could then never close.

#### 회차 경로

`run: true` 계층을 선언한 호스트에서만, 그리고 **결함이 났을 때만** 회차 항목 생성.
통과한 개발서버 확인은 릴리스 근거가 아니라 재현 맥락이라 아무것도 안 남김.
승격 검증의 회차는 이 스킬이 아니라
[`integration`](../integration/SKILL.md)·[`release-commit`](../release-commit/SKILL.md)
경로의 것 — 그쪽은 PASS 여도 만듦.

- `category` 로 유형 구분. 기본값은 회차 계층의 `category` 선언(보통 `승격검증`)이고, 이
  경로만 `개발검증` 으로 덮음 — 한 계층이 두 유형을 가지는 유일한 자리. **두 값 모두 보드
  옵션에 있어야** 하므로 1-2 대로 먼저 조회하고, 없으면 덮지 말고 선언값 그대로 보냄.
- `fields` 의 `build`·`environment`·`scope`·`result` 를 실음. `scope` 가 커버리지 분모라,
  비우면 그 회차는 무엇을 덜 돌았는지 못 답함.
- 결함 --`relates_to`--> 회차. `derives`/`verifies` 아님 — 회차는 전파 분모 밖이고, 이 링크가
  답하는 것은 "그 결함이 어느 실행에서 나왔나" 하나.
- 사후 요청 텍스트("이거 안 돼요")로 들어온 결함은 회차 없음 — 실행한 사실이 없으므로 기록할
  회차도 없음.

### 5. Read the existing graph

From the anchor, `list_entity_links(entityType="task", entityId=<anchor id>)`. A
single call returns the links where it is `source` and where it is `target`, so both
directions come out of one call. Which side is which is owned by
[recoble-propagation](../task-sync/references/recoble-propagation.md)'s direction
table — read it there.

Walk out to each declared layer **except the `defect: true` and `run: true` ones**
and record present / absent. Several items in one layer → show them and ask whether another
is wanted. A `feature_design` layer is the exception either way: several items there are normal
(one per feature), and none is not "absent" — do not ask and do not count it missing; §5-1
settles which feature items this work touches.

**The `defect: true` and `run: true` layers are reached only through their own
paths** — 결함 경로 and 회차 경로. Neither belongs to the
requirement→design→task→verification chain, so counting either as "missing" here —
or at step 6 on the 신규 요구 path — creates an item for something that did not
happen: an empty 회차 for a round nobody ran, and an empty 결함 for work that broke
nothing. The 결함 one is the worse of the two — created, it would hang
off the requirement by `verifies` and hold it open forever, since propagation
closes a requirement only when everything under it is done.

**Fill in both directions.** A design item as anchor with no requirement above it
gets that requirement created too. Layers that already have items are left alone —
only a missing *link* between them is drawn.

### 5-1. 기능 설계 큰 틀

`feature_design` 계층이 선언됐을 때만, 그리고 **경로와 무관하게**(§5 를 건너뛴 신규 요구·결함
경로 포함). 없으면 건너뜀 — 설계는 §5·§6 의 계층 하나로 남음.

**설계를 쓰기 전에 큰 틀(기능 분류)부터 찾음.** 기능 설계 항목은 기능마다 하나이므로, 먼저
찾지 않으면 같은 기능의 설계가 둘로 갈라지고 설계 내용이 흩어짐.

1. 1-2 대로 조회함 — 설계 보드의 `fields.feature`·`fields.module` 라벨 옵션
   (`list_workboard_fields`)과 그 보드 항목.
2. 요청이 닿는 기능을 정함 — 결함 경로면 결함이 난 기능. 기능마다 설계 항목을 찾음: feature
   라벨 값이 같은 항목, 없으면 제목 `[모듈] 기능명`. 제목으로도 판단이 안 서면 §4 와 같은
   방식으로 스캔 에이전트를 띄움 — [`references/similarity-scan.md`](references/similarity-scan.md),
   보드 종류 **기능 설계**, **`sonnet`**.
3. **있으면** 재사용 — 항목은 안 고치고 §8 에서 링크만 그음. 본문 갱신은 마무리 때
   [`task-sync`](../task-sync/SKILL.md) R5b 몫.
4. **없으면** 조사한 뒤 만듦 — 기능마다 `general-purpose` 에이전트 하나를 한 메시지에 모아 띄움,
   **`sonnet`**, 지시는 [`references/feature-survey.md`](references/feature-survey.md). 넘기는 것:
   기능·모듈 이름, 설계 계층의 `template` 경로, 호스트 저장소 루트. 돌아온 본문의 `---` 위가
   §7 의 `description` 이고 아래 근거 목록은 §11 보고에만 씀. 코드를 이 맥락에 들이면 뒤따르는
   작업을 밀어내므로 에이전트로 뺌.
5. 라벨 옵션에 그 기능·모듈이 없으면 §7 규칙 그대로 — 옵션은 사람이 넣고, 그때까지 그 역할만 비움.

기능이 여럿이면 기능마다 항목 하나. 결과는 §6 표에 기능별로 **재사용 / 조사 후 생성** 으로 실음.

### 6. Propose the decomposition

Present a table — layer, how many items, each title, a one-line gist — and get
approval before anything is created. When the `marker` layer would end up with more
than one item, this is where the user picks the one this turn is about; the marker
carries exactly one. For a `feature_design` layer, mark each feature item **재사용** or
**조사 후 생성** so the person sees whether an existing design is extended or a new one written.

### 7. Create

In `layers` order, `create_workboard_item` on that layer's resolved board id. On the
결함 경로 the order is 요구사항 → 결함 → 수정 작업 regardless of where those layers
sit in `layers`: each link needs both ends to exist, and the fix is derived from a
defect that has to be there first.
`description` comes from reading the layer's `template` (an absolute path,
host-first) and filling it in; `template: null` → write the body as prose instead.
Send `status` and `category` **only for layers that declare them** — a value pushed
at a board that never defined it is a ghost value the UI cannot show. A layer with no
declaration sends no `status` and lands on the board's entry status (= 시작 전).

**Label fields go by role.** For a layer that declares `fields`, send each mapped
role's value in `customFields` under **that board's key**, never under the role name.
설계 계층의 `module`·`feature` 가 그것 — 그 설계 항목의 모듈과 기능을 라벨로 실음(`feature_design` 이면
항목 하나가 기능 하나).
값이 그 필드의 옵션에 없으면 **보내지 않음**: 옵션 밖 값은 UI 가 못 보여주는 유령 값이고,
오타 하나가 새 기능으로 앉음. 1-2 대로 옵션을 먼저 조회하고, 없으면 ask the user (structured choice) 로
확인한 뒤 사람이 옵션을 넣을 때까지 그 역할만 비워 둠.

Title format is
[`task-import/references/recoble-status.md`](../task-import/references/recoble-status.md)
"항목 제목"; the body follows
[`task-import/references/item-body.md`](../task-import/references/item-body.md) — who reads each
layer, and why a repo link never stands in for the content.

### 8. Link

`list_link_types` → take the id of the type whose `code` is `derives` / `verifies`,
then draw each link with `create_entity_link` — the ones step 5 found missing, or the
ones the 결함 경로 named.

**With a `feature_design` layer, three links per task**, each drawn only when missing:

- requirement --`derives`--> each feature design item §5-1 settled
- each of those design items --`derives`--> the task
- the task's `direct_from` layer item --`derives`--> the task — the link propagation climbs,
  since it never counts the design item

On the 결함 경로 the fix task also takes design --`derives`--> fix task, for the feature the
defect sits in: that link is how [`task-sync`](../task-sync/SKILL.md) R5b finds the design to
rewrite. The defect --`derives`--> fix task link stays the propagation path.
회차 경로가 긋는 **결함 --`relates_to`--> 회차** 도 같은 방법으로 — `code` 가 `relates_to` 인
타입의 id 를 받아 source 를 결함, target 을 회차로 검. 이 타입은 대칭이라 방향이 판정을 안 바꾸고
[recoble-propagation](../task-sync/references/recoble-propagation.md) 방향표에도 없음(전파 경로가
아니라서). 그것이 회차를 그 링크로 붙이는 이유임.

**Never hardcode a type id**: the system defaults look fixed, but a space can carry
custom types and `list_link_types` is the only thing that knows. Direction: the table
[recoble-propagation](../task-sync/references/recoble-propagation.md) owns, the same
one step 5 reads. A `code` that is absent → skip that one link, warn, and keep the
item — an item without a link can still be linked by hand, a deleted item cannot.

### 9. Task document

Only when the `marker` layer has an item — from step 7's creation or step 6's
existing link. No `marker` layer → skip this step and step 10; `/vdev` Phase 4 then
skips the sync, same as an unlinked run.

Follow [`task-import`](../task-import/SKILL.md) ("Both providers" steps 2–4)
unchanged — same path `docs/tasks/{username}/{taskid}_{title}.md`, English
kebab-case title, same template, same `handoff_resolve.py --provider recoble`
sections. Two things are this skill's own: the item that opens the document is the
`marker` layer's rather than one `task-import` pulled or pushed, and `{username}`
still comes from that same step 4's `get_connection_info` local part. A document
already at that path (an interrupted earlier run) is left alone — the same rule
that leaves created items and links standing (실패 처리, below).

### 10. Marker

Only when a layer declares `marker: true`. The line's format **and** the
clear-before-run rule are owned by [`task-import`](../task-import/SKILL.md) ("Both
providers" step 1) and apply here unchanged — this skill writes the same one line.

Writing the marker is the moment of 착수 — apply [`task-import`](../task-import/SKILL.md)
Recoble branch step 5 to the `marker` layer's item, including an item **this skill's**
step 6 reused rather than created. The forward-only judgement blocks a demotion, so a
re-run is safe.

```bash
tr -d '\r' 2>/dev/null < .gitignore | grep -qxF '.claude/vway-kit/.vdev/' || printf '\n.claude/vway-kit/.vdev/\n' >> .gitignore
mkdir -p .claude/vway-kit/.vdev
printf '%s\n' 'recoble:labs:ITEM-123' >> .claude/vway-kit/.vdev/alm   # 값은 실제 해석 결과로
```

No `marker` layer → do not run this block. `/vdev` Phase 4 then skips the sync the
same way it does for an unlinked run, which is the intended outcome for a host that
tracks requirements and designs but not tasks.

### 11. Report

A table of what was created (layer · itemKey · title) and what was linked — each feature
design marked 재사용 or 조사 후 생성, with the survey's evidence lines under it — followed
by every warning from step 1 and every link skipped in step 8. On the 결함 경로, add the
`low` candidates by itemKey and title — they were never offered, so this line is the
only place a person learns the scan saw them and passed. Naming one back at `/alm-trace`
attaches it.

## 실패 처리

**부분 실패 롤백 금지.** 셋을 만들고 넷째가 실패하면 만든 것을 그대로 두고
실패 지점 보고.

근거는 둘. 자동 삭제는 사람이 이미 손댄 항목까지 삭제 — 항목이 만들어진 순간
그것은 보드에 있고, 누군가 본문을 고쳤을 수 있음. 그리고 되돌릴 이유도 없음:
재실행하면 5단계가 앵커에서 이미 만들어진 것들을 찾아내고 남은 하나만 만듦.
결손만 채우는 설계라서 중단된 실행이 곧 다음 실행의 입력.

같은 이유로 ALM 실패는 작업을 막지 않음. 어느 단계에서 멈추든 한 줄 보고하고
빠질 뿐이고, 마커가 없으면 `/vdev` Phase 4 가 sync 를 건너뜀.
