---
name: doc-sync
description: "Use when a code or doc change may have left the documentation stale, inconsistent, or contradicting itself; when docs need updating after a change; when a module is missing its local CLAUDE.md; or when the /vdev doc-sync gate runs."
# 앞의 둘은 §3 의 게이트 마커 — fork 는 프롬프트를 못 받으므로 사전승인이 없으면
# 자기 증거를 못 남김. 가운데 넷은 Mode W 가 매번 부르는 wiki 조회/생성 명령, 그다음은
# §2 의 보존 대조, 마지막 둘은 §2b 의 Codex 지침 렌더.
# 전부 정확 일치, 뒤에 glob 없음(`*` 는 `..` 를 포함해 경로 구분자를 넘으므로,
# 접두 매칭 규칙 하나가 디스크 어느 경로든 사전승인해 버림).
# 스크립트는 `${CLAUDE_PLUGIN_ROOT}` 의 플러그인 사본 — 상대경로 규칙은 작업 저장소가 그 자리에
# 둔 아무 파일이나 묻지 않고 실행시킴.
# `--neighbors <id>`·`--derive-id <경로들>` 은 인자 자리를 `*` 로 끝냄: Claude Code 는 `a && b`
# 의 서브커맨드를 하나씩 따로 매칭하므로 그 `*` 가 넓히는 것은 wiki_graph.py 가 읽는 인자뿐.
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --neighbors *) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --derive-id *) Bash(mkdir -p .claude/vway-kit/.vdev) Bash(touch .claude/vway-kit/.vdev/doc-sync.done) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --build) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --verify) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --stale) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --unmapped) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doc_invariants.py" --changed) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness/codex/instructions.py" render) Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness/codex/instructions.py" render --check)
argument-hint: "[preview | 무엇이 왜 바뀌었는지]"
# 몇 줄을 고치려고 문서 집합 전체를 읽는 스킬 — 그 읽기가 비용이고, 작업이 아니라 스킬을 부른
# 쪽 컨텍스트에 얹힘. fork 가 그것을 옮김. 네 필드가 각각 무엇을 사는지는
# [authoring-spec.md](../harness-authoring/references/authoring-spec.md) 가 SSOT. 여기엔 이
# 스킬 고유분만 — fork 는 대화 이력을 못 받으므로 아래 0단계가 부른 쪽 의도가 본문에 닿는
# **유일한** 통로이고, `preview` 도 거기 삼.
context: fork
agent: general-purpose
model: sonnet
background: false
---

# doc-sync

Analyze **both code and documentation changes**, update the related docs, and
harmonize the whole doc set for consistency.

## When

- Called by `/vdev` at the **Docs gate** (doc-only changes) and the **Dev
  gate** (after superpowers completes) → on pass, record
  `.claude/vway-kit/.vdev/doc-sync.done`.
- Whenever you need to verify documentation consistency after a code/doc change.

## 0. Read the caller's note

`$ARGUMENTS` is everything the caller said. This skill runs in a forked subagent with no
conversation history, so nothing else carries their intent in — an empty value is normal
and means the change itself is the whole brief.

Two things it can carry, and they are exclusive. A value that is **exactly** `preview`
means plan only. Anything else — including a sentence with the word *preview* somewhere in
it — is context for Mode A: what changed and why, which the diff shows the *what* of but
never the *why*, so a caller who names the intent narrows the keyword extraction step 1 of
Mode A would otherwise derive from the diff alone. Match the whole value, never a
substring: "프리뷰 창을 갈아엎었어, 문서 확인해줘" is a request to sync, and reading it as
the mode would answer a sync with a plan and leave no marker — this skill declining to run
without saying so.

Plan only means the tree is left as found. No Edit, and none of the writes that are not
Edits either: no `git add`, and no `wiki_graph.py --build`, which overwrites `graph.yaml`
and is pre-approved above so nothing will stop you. Skip §3's marker, and say in the Report
that you skipped it.

## 1. Determine the change scope

```bash
git -c core.quotePath=false diff HEAD
git -c core.quotePath=false diff --name-only HEAD
git -c core.quotePath=false ls-files --others --exclude-standard
```

Classify changed files into two tracks (if both, run **A → B** in order):

- **Code changes** (`.py` / `.js` / `.ts` / config / router …) → **Mode A**
- **Doc changes** (`.md`: the index doc, the doc dirs, the rule dir) → **Mode B**
- 프로젝트에 wiki 가 있으면 **A → B → W** 순.

## Mode A — code → doc sync

Reflect code changes into the related docs.

1. **Extract keywords**: class names, field names, type annotations,
   `Field(description=...)`, env-var names/defaults, route paths, function names,
   `summary`.
2. **Find related docs**: Grep `**/*.md` by keyword (`files_with_matches`). Keep a
   hit only if the doc **states the changed fact** (documents that field/route/env
   var), not merely mentions the word.
3. **Update**: Read each file → locate the target section (`#### Request Body`,
   env table, etc.) → replace via Edit to match the code change.

## Mode B — doc → doc harmonization

When docs change, harmonize **the consistency of the whole doc set**.

### Reference targets (read from `vdev-config.doc_sync`)

Resolve the targets to check from the project's
`.claude/vway-kit/config/vdev-config.yaml`, not from a hardcoded list:

- **`doc_sync.index`** — the documentation index / SSOT (e.g. the root
  `CLAUDE.md`): the service-map table + the `Auto-loaded Rules` table. Links fan
  out from here to each service/rule doc.
- **`doc_sync.service_docs`** (glob) — the per-service local docs linked from the
  index.
- **`doc_sync.dirs`** (globs) — the guide / operations / standards doc dirs and
  the auto-loaded rule dir.

Check every target; track the index by following its links.

### Check items

1. **Cross-reference integrity** — does every file/link/rule a doc points to
   exist (including paths/anchors broken by the change)?
2. **Factual consistency (SSOT)** — do two docs record the same value (model
   name, port, path, policy, version) differently? Keep the value in a single
   source of truth and reduce the rest to links.
   **Which one is the source is not a vote.** The artifact the system reads at
   runtime wins over every document describing it — the code, then the config it
   loads (`.env.example`, a settings file), then the index, then the per-service
   doc. Two docs agreeing against the code are two stale docs, not a majority.
   And correcting the code to match the docs is never the fix here: this skill's
   subject is the documentation.
3. **Index sync** — does the index's rule/service tables match the actual file
   set (the rule dir, the service dirs)?
4. **Hierarchy consistency** — do the per-service docs contradict the index's
   higher-level rules?
5. **Module CLAUDE.md template compliance** — take the module dirs from
   `vdev-config.modules[].path` (the authoritative module list — same one used
   for per-module pre-checks) that fall under the `service_docs` glob's
   directory (e.g. `services/*/`), since the glob itself only matches files
   that already exist and can't surface a *missing* one.
   - If harness is **not** installed for this project (no `docs/code-style/`
     dir and no sibling module already has a local `CLAUDE.md` — the same
     signal [`vdev-init`](../vdev-init/SKILL.md) uses to decide "harness
     installed"), do **not** create one — creating it here would falsely trip
     that detection for a project that never ran `/harness-init`. Note the
     gap in the Report and move to the next check item — this branch ends
     check 5, not the skill; §2 and the marker still run.
   - Otherwise, if a module has **no** local `CLAUDE.md`, generate one from
     [`module-claude-md-template.md`](references/module-claude-md-template.md)
     by reading the module's actual code (entry points, build/test/lint
     commands, key deps) to fill each section — do not leave placeholders
     unfilled.
   - If a module **already has** one, audit it against that reference's quality
     criteria (commands work, architecture explained, gotchas captured,
     concise, current, actionable) and fix only what falls short — preserve
     existing project-specific content, do not rewrite wholesale.

### Action

On a mismatch, harmonize the related docs via Edit and record **what changed and
why** in the Report. If a new rule/doc was added but is missing from the index,
add the index row. A newly generated module `CLAUDE.md` also gets an index row
(service-map table) if the index doesn't already list that module.

## Mode W — wiki 동기화

프로젝트에 LLM Wiki 가 있을 때만 실행(`vdev-config.wiki` 있고 `enable: true`). 없으면 모드 전체
스킵 — 아래 명령들은 아무것도 안 하고 exit 0.

1. **코드 변경이 무엇을 stale 하게 만들었는지 탐색**:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --stale
```

   JSON 항목 하나하나 = 기록된 `sources` 값이 파일과 더는 안 맞는 wiki 노드 — `recorded` 와
   `current` 는 **워킹트리 blob hash**(`git hash-object`)라 히스토리 재작성(squash/rebase 승격)이
   가짜 stale 을 못 만듦. `migrated` 키가 있는 항목은 구형 커밋-sha 마커: `sources[path]` 를
   `migrated` 값으로 재작성 — 의미보존 변환(`git rev-parse <old>:<path>`)이라 본문 재독해 불요이고
   검증 게이트도 본문 편집 없는 그 재작성만은 허용. `migrated` 가 `current` 와 같으면 그 재작성이
   수정의 전부, 다르거나 `null` 이면 그 노드는 실제로도 stale — 본문 동기화 후 도장.
   `"missing": true` 인 항목은 다른 문제: 그 source **경로**가 더는 없음(이동·삭제).
   노드의 front matter 에서 경로를 고치거나 항목 삭제. sha 도장 **금지**: `--verify` 가 없는 경로
   자체를 경고하므로 새 sha 를 찍어도 문제는 그대로 남음.

2. **조화 대상 축소**. stale 노드마다 추측 말고 그래프에 이웃 질의 — 1단계 JSON 항목의 `id`
   키(문서의 `wiki_id` 가 그대로 되는 그래프 노드 id)를 넣어 노드당 한 번씩 `wiki_graph.py
   --neighbors` 실행: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --neighbors auth.jwt`.
   (일부러 복사 가능한 블록 아님: 하드코딩할 id 가 없고, 그래프가 모르는 id 는 사유를 stderr 로
   내며 비영 종료.)

   Mode A 는 모든 마크다운을 키워드로 grep 해 관련도 점수화. wiki 가 있으면 그 관계를 그래프가
   이미 보유 → 추정이 아니라 조회.

3. **본문 갱신**, **본문을 실제로 고친 노드에 한해서만** `sources[path]` 에 그 파일의 **워킹트리
   blob hash** 도장 — 1단계 JSON 의 `current` 값(= `git hash-object -- <path>`)이지 커밋 sha 가
   아님. 손대지 않은 stale 노드는 stale 인 채로 두고 리포트에 기재 — sha 도장 금지. 뒤의 코드를
   읽지 않고 찍는 순간 그 표식은 거짓이 되고, 게이트가 그걸 기계로 강제: 노드에 대한 변경이
   `sources` sha 뿐인 커밋은 `--verify` 가 **차단** — 일괄 갱신은 규율 위반에 그치지 않고 실패.
   허용되는 교체는 둘: 1단계의 `migrated` 재작성, 그리고 본문 편집이 **바로 직전 커밋**에 들어간
   도장(방금 커밋한 동기화에 도장을 찍거나 amend 로 합치는 것은 통과 — 그 커밋이 문서를 개명까지
   했어도 게이트가 따라감).
   읽어 봤더니 **여전히 정확한** stale 노드(코드 변경이 표면적이었던 경우)도 일부러 같은 취급:
   표식은 그대로 두고 "확인함, 여전히 stale" 로 리포트 — 표식은 본문 편집과 함께만 움직이고,
   다음에 본문이 실제로 바뀔 때 자연히 해소.

4. **wiki 루트 아래 새 `.md` 에 front matter 부여** — `wiki_id` 는 새 문서 전부에 대해 파생 호출
   **한 번**으로 획득, 실제 경로 전달(예: `python3
   "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --derive-id docs/auth/jwt.md
   docs/auth/session.md`; stdout 한 줄이 `경로<TAB>id` 이고, 실패는 stderr 에 경로를
   지목하며 호출이 비영 종료, 단 성공한 경로는 그대로 자기 줄을 냄 — 그 경로만 고쳐 재실행.
   근거는 [wiki-init](../wiki-init/SKILL.md) 5단계). defect 문서는 예외: 그 `wiki_id` 는
   [`defect-template.md`](../wiki-init/references/defect-template.md) 의 `defect.<슬러그>` 관례를
   따르고 이 파생 미사용. 그다음 `title` · 그 문서가 서술하는 `sources` · 설계 문서면
   `tags: [sds]` — 5단계와 `--verify` 가 그 문서를 찾는 표식이 그 태그.
   `used_by`·`defects` 는
   절대 금지 — 생성 필드. **새 노드를 자기가 속한 노드들에 연결**(어느 쪽이든
   `related`/`depends_on`) — 그래야 실제 edge 로 index 에서 도달. index 의 `related:` 에는 그
   노드가 정말 최상위 진입점일 때만 추가([wiki-init](../wiki-init/SKILL.md) 6단계). orphan 탐지는
   front matter edge 만 읽고 마크다운 링크는 절대 안 읽으므로, 아무 데도 안 이어진 노드는 어느
   본문이 아무리 링크해도 영원히 orphan 으로 보고됨.

5. **한 번도 못 받은 `sources` 채우기**:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --unmapped
```

   코드가 안 매핑된 `sds` 노드 전부 — 키 부재, 값 없는 키, 코드가 있기 전에
   실려 나간 그린필드 설계의 `sources: {}`. `--verify` 는 앞의 둘만 경고하고 셋째에는
   침묵하므로, 셋을 다 담는 목록이 이것뿐. 각각의 모듈 개요를 읽고 실제 코드 경로를
   기록, `sha` 는 `null` 로 — 다음 본문 동기화에서 3단계가 찍음. 이걸 채우는 다른
   주체가 없음: 1단계는 기록된 경로에서 목록을 만들고, 4단계는 이번 변경이 만든 문서만
   건드리며, `/wiki-init` 은 `wiki_id` 를 이미 가진 문서를 재방문하지 않음. 코드가
   여전히 없으면 `sources: {}` 를 두고 그 사실을 리포트에 기재 — 경로를 지어내는 것이
   이 단계가 막는 바로 그것.

6. **`max_lines` 초과 노드 분할**. `--verify`(아래)가 경고하지만 그 경고에 행동하는 주체가 없음 —
   `/wiki-init` 은 `wiki_id` 를 이미 가진 문서를 재제안하지 않으므로 이전 마법사도 그 문서를 다시
   찾지 않음. [`wiki-init`](../wiki-init/SKILL.md) 4-5단계 지시대로 H2 0개·1개 분기를 포함해 분할 —
   H2 분할이 늘 적용된다고 가정 금지. 결과는 리포트에 기재.

   **SRS 문서는 예외** — 기계 분할 안 함. 아래 [이 스킬이 소유하지 않는
   것](#이-스킬이-소유하지-않는-것) 참조.

7. **새 문서 스테이징 후 빌드·검증**. 문서는 git 에 있음으로써 wiki 에 들어옴 — 그래프는
   파일시스템이 아니라 인덱스에서 만들어지므로, 미스테이징 새 `.md` 는 아직 노드가 아니고
   재빌드가 그것을 누락. 새 문서를 먼저 `git add` 후:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --build
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_graph.py" --verify
```

   게이트 마커를 쓰기 전에 `--verify` 가 exit 0 이어야 함 — 커밋 게이트가 같은 명령을 돌리고
   아니면 차단. 구조 위반(`wiki_id` 형식·중복 · `title` 누락 · 매달린 `depends_on` · 순환 ·
   `wiki_id` 를 달고 있으면서 파싱 실패한 front matter)은 `--build` 로 안 고쳐짐 — 문서의 front
   matter 를 고쳐야 함.
   `--verify` 는 **워킹트리**를 읽으므로 `docs/graph/graph.yaml` 을 그것을 만들어낸 문서들과 함께
   스테이징 필수 — 아니면 커밋에는 새 front matter 옆에 옛 그래프가 기록되고, 다른 사람의 다음
   세션 커밋까지 아무도 그 drift 를 못 잡음. 머지가 `graph.yaml` 에 충돌 마커를 남겼으면 절대 손으로
   풀지 말 것 — 아무 쪽이나 취한 뒤 `--build` 재실행([wiki-init](../wiki-init/SKILL.md) 8단계).

### 이 스킬이 소유하지 않는 것

구조는 **코드 전에** `/vdev` 의 Dev 증분 단계가 기록 — 모듈 개요·Mermaid 노드·통합 지점
계약·FR 역추적 링크. 이 스킬은 **코드 뒤에** 돌며 정합만 맞춤 — `sources` sha·stale 해소·
분할·orphan. 한 사실 한 곳 — 설계 결정을 여기서 적으면 두 번 기록됨.

**SRS 문서는 기계 분할 금지.** 6단계의 H2 분할이 걸리면 SDS 가 거는 앵커(`#nfr-perf`·
`#c-003`)가 깨져 모든 FR 참조가 죽은 링크. `max_lines` 초과 시 한 절을 통째로 제 파일로
승격하고 링크를 함께 고치는 **명시적 이주**로 처리.

## 2. 내용 보존 대조 (편집 후, 마커 전)

Mode A/B/W 의 편집은 전부 산문 재작성 — 링크 하나·헤딩 하나·펜스 하나·front matter 키 하나가
조용히 빠져도 문서는 그대로 읽힘. 편집을 끝냈으면 무엇이 사라졌는지 기계로 확인:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doc_invariants.py" --changed
```

HEAD blob ↔ 워킹트리를 대조해 `[!]`(손실)·`[~]`(경고)·`[=]`(보존)로 보고. **게이트가 아님** —
문서를 정당하게 줄인 편집(중복 삭제·SSOT 통합)은 반드시 여기 걸림. `[!]` 각각을 **의도한
삭제인지 확인**하고, 의도가 아니면 되살린 뒤 재실행. 판정 결과는 4의 리포트에 한 줄씩 기재
(의도한 삭제는 사유와 함께 — 그래야 다음 사람이 같은 줄을 다시 안 뒤짐).

`[~]` 는 참고용: 펜스 안 줄 변경·불릿 감소·헤딩 순서. 문장을 다시 쓴 편집에선 정상.

이 대조는 문체가 아니라 이번 재작성이 무엇을 잃었는지를 물으므로 `vdev-config.doc_style` 을
읽지 않음 — doc-style 을 켠 적 없는 저장소도 돌림.

산문 자체는 [`doc-style.md`](../../rules/doc-style.md) 를 따름. 그 규칙의 절반은 패턴이고
절반은 판단이라 프로젝트 문체 범위 안에서 **이 변경이 건드린 모든 파일**에 양쪽을 다 돌림 —
범위가 코드를 부르면 주석·독스트링도(기본이 그렇고, `doc_style` 이 꺼졌거나 없어도 같음).
Invoke skill `prose-review` — 경로 없이: 변경 목록을 git 에서 직접 읽고 좁힘. 무엇을 고칠지
보고해 오므로, 살아남은 것을 **마커 전에** 적용할 것: 마커 뒤의 편집은 마커를 무효로 만듦.

## 2b. Codex 용 지침 사본

`.claude/vway-kit/config/vdev-config.yaml` 의 `harnesses` 에 `codex` 가 있을 때만.
Codex 는 `CLAUDE.md` 도 `.claude/rules/` 도 읽지 않고, 그 둘로 만든 루트 `AGENTS.md` 의 블록만
읽음 — 둘 중 하나라도 고쳤으면 블록을 다시 만들고 일치를 확인:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness/codex/instructions.py" render
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness/codex/instructions.py" render --check
```

`--check` 의 0 아닌 종료는 finding — 그 줄을 `[B]` 로 보고. 블록은 손으로 고치지 말 것(다음
렌더가 덮어씀).

## 3. Gate marker

Unless §0 asked for a preview, leave the gate evidence — the commit is blocked without
it, and "was I called by `/vdev`?" is not a question a fork can answer, so it is not asked:
the marker records that doc-sync passed on this tree, which is true whoever called it.

```bash
mkdir -p .claude/vway-kit/.vdev && touch .claude/vway-kit/.vdev/doc-sync.done
```

## 4. Report

```
doc-sync result:
- [A] services/<svc>/README.md — added priority field to env table
- [B] <index> ↔ services/<svc>/CLAUDE.md — harmonized model-name mismatch (SSOT: .env.example)
- [B] <index> rule index — missing risk-tiers.md row → added
- [B] services/<svc>/CLAUDE.md — generated from module-claude-md-template.md (Commands/Architecture/Gotchas filled from source); added to index service map
- fixed 1 cross-reference (broken link)
- [W] docs/auth/jwt.md — sources sha 갱신; graph.yaml 재생성 (노드 12개)
- [W] docs/auth/session.md — 여전히 stale, 본문 미갱신 (사람 판단 필요)
- [W] docs/api/auth.md — max_lines 초과로 H2 기준 3노드로 분할; 원본은 역링크를 가진 노드로 유지
- [INV] docs/guide.md — 링크 1건 사라짐 → 의도한 통합(SSOT 를 docs/index.md 로), 유지
- [INV] docs/ops.md — 펜스 1개 사라짐 → 실수, 되살림
```

## Tips

- To preview the plan only, pass `preview` as the argument (§0) — the word has to reach
  `$ARGUMENTS`, since a fork never sees the sentence it was asked in.
- The module template ([`module-claude-md-template.md`](references/module-claude-md-template.md))
  covers only a single module's usage info (commands/architecture/gotchas). It
  is a different artifact from the harness root
  `CLAUDE.md`(`skills/harness-authoring/templates/claude-md.template.md`),
  which carries project-wide baseline principles managed by `/harness-init` —
  do not conflate the two or generate baseline-principle content here.
