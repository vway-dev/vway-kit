---
name: alm-docs
description: Use when the repo's SRS and the Recoble requirement board may have drifted — it reports which requirements were never uploaded, which mappings point at nothing, which items exist only on the board, and which titles differ, then moves one direction only (--pull board→repo, --push repo→board). Not a gate — it never blocks a commit.
argument-hint: "[--pull | --push]"
---

# /alm-docs - SRS 와 requirement 계층의 왕복 / usage: [--pull | --push]

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Purpose

`docs/srs` 의 FR·C 와 Recoble `requirement` 계층 보드를 대조해 어긋남을 보임. 기본 동작은
리포트이고, 옮기는 것은 사람이 고른 **한 방향**뿐임. 자동 양방향 머지는 없음 — 두 쪽이
동시에 달라진 경우 기계가 고르지 않음.

**축은 그대로** — 텍스트는 repo, 상태·승인은 Recoble. 이 스킬은 상태·진행률·커버리지를
옮기지 않고(`task-sync` 소유) `derives`·`verifies` 링크도 긋지 않음(`alm-trace` 소유). 두
스킬이 같은 간선을 그으면 정본이 사라짐.

**게이트 아님.** 실패는 전부 경고 한 줄이고 종료 코드가 판정에 실리지 않음.

## Arguments

- `$ARGUMENTS` : 없으면 리포트까지. `--pull` 이면 보드 → repo, `--push` 면 repo → 보드.
  둘을 함께 받으면 어느 쪽이 정본인지 묻는 것이 되므로 ask the user (structured choice) 로 하나만 고름.

## Execution

### 0. 계층·보드·접두를 해석

이 실행의 스페이스는 **하나가 아니라 집합** — `alm.recoble.spaces` 중 `layers` 를 선언한
키 전부:

```bash
python3 -X utf8 -c "import pathlib, sys, yaml
cfg = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')) or {}
spaces = ((cfg.get('alm') or {}).get('recoble') or {}).get('spaces') or {}
print(' '.join(k for k, v in spaces.items() if isinstance(v, dict) and v.get('layers')))" \
  "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml"
```

`$ARGUMENTS` 가 스페이스를 이름으로 대면 그 하나로 좁힘. 집합이 비면 한 줄 알리고 종료 —
이 호스트는 계층을 쓰지 않음.

한 스페이스만 해석하면 안 되는 이유는 2·3단계가 이미 여럿을 전제하는 것 — 빠진 스페이스는
판정도 안 되고 표에 뜨지도 않아, **안 본 것과 어긋남 없는 것이 같아 보임**.

계층 선언은 스페이스마다 한 번. `alm_layers.py` 는 `--space` 하나만 받음:

```bash
SPACES=           # ← 위가 찍은 키들 (공백 구분, 예: dev3 labs)
[ -n "${SPACES:-}" ] || { echo "SPACES 미확정 — 스페이스를 먼저 해석하라"; exit 1; }
for SPACE in $SPACES; do
  echo "== $SPACE"
  python "${CLAUDE_PLUGIN_ROOT}/scripts/alm_layers.py" \
    "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/config/vdev-config.yaml" --space "$SPACE"
done
```

가드가 한 줄을 버는 이유는 빈 `--space` 가 `alm.recoble.default` 로 떨어지는 것 — 그런
호스트는 `configured: false` 를 돌려주고, 실행은 보지도 않은 스페이스에 대해 "계층을
추적하지 않는 호스트" 라고 보고하게 됨.

스페이스마다 판정하고, 빠지는 것은 **그 스페이스만** 빼고 나머지로 계속함:

- **`configured: false`** → 그 스페이스를 뺌.
- **`errors` 비지 않음** → 그 줄을 그대로 보이고 그 스페이스를 뺌.
- `layers` 가 **하나뿐이면 그것이 곧 요구사항 계층**(루트) — `alm_layers.py` 가 정상으로
  판정하는 최소 구성이고 이 스킬이 필요로 하는 전부임. 여기에 루트 규칙을 겹쳐 물으면
  `requirement` 하나만 선언한 호스트가 통째로 빠짐.
- 둘 이상이면 **루트** 하나를 고름 — 루트가 무엇인지는
  [`alm-trace`](../alm-trace/SKILL.md) 4단계가 SSOT. 루트가 0개면 요구사항을 소유하는
  계층이 없는 것이므로 그 스페이스를 뺌, 2개 이상이면 ask the user (structured choice) 로 고름.

도구 접두는 [`task-import/references/recoble-server.md`](../task-import/references/recoble-server.md)
절차 그대로 **스페이스마다** 한 번(이름 조립 금지, `mcp_url` uuid 대조로만 채택). 그다음
스페이스마다 `list_workboards` **한 번**으로 루트 계층의 `workboard` 를 `{id}` 로 품. 이름이
안 맞거나 둘이면 그 사실을 보이고 그 스페이스를 뺌 — 보드를 만들지 않음.

`401` 은 미인증 — 접두를 해석한 경로의 고치는 법을 대고 그 스페이스를 뺌.

남은 스페이스가 0개면 여기서 종료. 뺀 스페이스는 뺀 사유와 함께 6단계 보고에 실음.

### 1. repo 측을 스캔

중간 산출물 자리를 비우고 다시 만듦(지난 실행의 JSON 이 이번 판정에 섞이지 않게):

```bash
rm -rf "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/.vdev/alm-docs" \
  && mkdir -p "${CLAUDE_PROJECT_DIR}/.claude/vway-kit/.vdev/alm-docs"
python3 .claude/vway-kit/scripts/alm_docs.py --scan \
  --out .claude/vway-kit/.vdev/alm-docs/repo.json
```

출력이 없고 파일도 안 생기면 이 저장소에 `docs/srs` 가 없는 것 — 한 줄 알리고 종료.

### 2. 보드를 열거

스페이스마다 `general-purpose` 에이전트 하나, **`sonnet`**, 여럿이면 한 메시지에 담아
동시에 띄움. 지시는
[`references/board-enumeration.md`](references/board-enumeration.md), 넘기는 것은 0단계가
해석한 **도구 접두**, 보드 id, 스페이스 키, 출력 경로
`.claude/vway-kit/.vdev/alm-docs/board-<스페이스>.json`.

보드 원문이 이 경로에서 제일 큰 입력이라 메인 컨텍스트에 들이지 않음 — `alm-trace` 유사
스캔과 같은 근거. 접두를 다시 유도하지 않고 건네는 이유는 에이전트에 `mcp_url` uuid 를
맞춰 볼 config 가 없는 것 — 그쪽은 이름을 지어낼 수밖에 없음.

### 3. 대조

```bash
python3 .claude/vway-kit/scripts/alm_docs.py --diff \
  --repo .claude/vway-kit/.vdev/alm-docs/repo.json \
  --board .claude/vway-kit/.vdev/alm-docs/board-*.json \
  --json .claude/vway-kit/.vdev/alm-docs/diff.json
```

표를 그대로 보고함. 판정은 이 스크립트가 쥠 — 표를 다시 해석하지 않음.
`잘린 열거` 줄이 서면 그 사실을 보고에 실음: 그 스페이스의 「보드에만 있음」·「끊긴 매핑」은
세지 않았다는 뜻임. `버린 입력` 줄도 그대로 실음 — 그 건수는 아래 갈래별 건수의 분모 밖이라
0건이 어긋남 없음을 뜻하지 않음.

입력이 없거나 JSON 으로 안 읽히면 스크립트가 경로를 대는 `[!]` 한 줄을 내고 종료 0 —
앞 단계가 안 돌았다는 뜻이므로 그 줄을 보고에 싣고 그 단계부터 다시 봄.

**끊긴 매핑과 중복 매핑은 여기서 끝** — 지워진 항목을 되살릴지 주석을 지울지는 의도의
문제라 기계가 고르지 않음. 이름만 보고에 남김.

인자가 없으면 여기서 끝.

### 4. `--pull` (보드 → repo)

대상은 「보드에만 있음」 + 「제목 다름」(보드가 정본). 쓰기 단계는 3단계의 JSON 을 입력으로
받고 문서를 다시 파싱하지 않음.

1. 무엇을 몇 건 건드릴지 표로 보이고 ask the user (structured choice) — 전체 / 고른 것만 / 중단.
2. 항목마다 영역을 고름. 후보는 `python3 .claude/vway-kit/scripts/srs_check.py --areas`,
   선택지에 「새 영역」 포함. C 는 영역을 묻지 않고 `README.md` 로 감.
3. 새 영역이면 파일을 먼저 만듦. **호스트에 wiki 가 있으면** front matter 를 함께 넣음 —
   `python3 .claude/vway-kit/scripts/wiki_graph.py --derive-id docs/srs/<영역>.md` 로
   `wiki_id`, 그리고 `title`, 인덱스로 가는 `related` 엣지 — 그 id 도 같은 파생 호출
   (`--derive-id docs/srs/README.md`)로 뽑고 철자를 여기 적지 않음(wiki 루트가 정함).
   그 엣지는 `docs/srs/README.md` 가 자기 front matter 를 갖게 된 뒤에만 넣을 것 —
   노드가 아닌 문서로 가는 엣지는 dangling 이고, 그것이 면해 주는 orphan 은 경고에
   그치는 반면 dangling 은 커밋을 막음. 그다음
   `python3 .claude/vway-kit/scripts/wiki_graph.py --build` 하고 `graph.yaml` 을 함께
   스테이징. [`/vdev` Dev 2](../vdev/SKILL.md) 와 같은 규율이고 조건도 같음 — wiki 없는
   호스트에서 `--build` 는 조용히 0 을 돌려주므로, 무조건으로 적으면 아무도 안 읽는 front
   matter 와 없는 경로를 가리키는 `git add` 가 남음.
   **파일 생성은 이 단계의 일** — 되쓰기 스크립트는 없는 파일을 만들지 않고 건너뜀.
4. 번호는 파일마다
   `python3 .claude/vway-kit/scripts/srs_check.py --next-id docs/srs/<영역>.md --kind FR`
   (C 는 `--next-id docs/srs/README.md --kind C`). 한 파일에 여럿을 넣을 때는 **한 건 쓰고
   다시 물음** — 번호는 파일을 읽어 정해지므로 앞의 쓰기가 다음 번호를 바꿈.
5. 계획 JSON 을 `.claude/vway-kit/.vdev/alm-docs/pull.json` 에 씀. 최상위 키는 **`writes`**
   이고 `id` 는 **SRS 채번**(4번이 `--next-id` 로 받은 값):

```json
{"writes": [{"file": "docs/srs/payment.md", "anchor": "fr-payment-002",
             "id": "FR-PAYMENT-002", "title": "정기 결제를 지원함",
             "alm": {"dev3": "REQ-204"}}]}
```

```bash
python3 .claude/vway-kit/scripts/alm_docs.py --apply-pull \
  --plan .claude/vway-kit/.vdev/alm-docs/pull.json
```

   키를 다르게 쓰면 스크립트가 그 이름을 대는 `[!]` 한 줄 — 최상위 키(`writes`)면 아무것도
   안 쓰고, 원소 키면 그 원소만 건너뜀. 그 줄이 선 자리를 고쳐 다시 부름.

   `file` 이 `--root` 를 벗어나면 자리와 값을 대는 `[!]` 한 줄로 거절하고 그 원소만
   건너뜀 — 보드에서 온 텍스트가 저장소 밖 파일을 고치지 못하게 함. 거절 집합은
   절대·드라이브·UNC·`..` 에 더해 **루트 안의 정션·심볼릭 링크**(`..` 가 없어도 링크
   너머는 남의 디렉터리). `--record` 도 같음.

   요구 문장은 보드 제목을 옮기되 스크립트가 `(확인 필요)` 를 함께 담음 — 보드 한 줄이
   측정 가능한 FR 이라는 보장이 없음. 지우는 것은 사람의 일. 줄 **말미**에 선 이 표식은
   몇 개든 「제목 다름」 비교에서 빠짐(스크립트가 벗겨냄) — 수입 직후의 상태가 곧
   드리프트로 보이면 안 됨. 문장 가운데로 옮긴 표식은 그 문장의 일부라 비교에 들어감.
6. 「제목 다름」은 그 줄의 문장만 고침(Edit). 앵커·주석은 그대로.

수입이 끝난 시점부터 그 항목의 텍스트는 로컬이 정본.

### 5. `--push` (repo → 보드)

대상은 「한 번도 안 올림」 + 「제목 다름」(repo 가 정본). 표와 확인은 4단계와 같음.

1. 새 항목은 **루트 계층(`requirement`)에만**. 본문은 그 계층 선언의 `template`, 보드·상태·
   카테고리도 그 선언에서. 본문 규칙은 [item-body](../task-import/references/item-body.md) — SRS
   앵커·파일 경로를 적지 않고 요구 내용을 풀어 씀.
2. `derives`·`verifies` 링크는 만들지 않음 — 그 그래프는 `alm-trace` 소유.
3. 「제목 다름」은 `update_workboard_item` 으로 **제목만**. 다른 필드는 안 건드림.
4. 생성에 성공한 id 를 매핑 JSON 으로 모아 되씀. 일부만 성공하면 성공한 것만. 최상위 키는
   **`records`** 이고 `item` 은 **Recoble 항목 id** — 4단계의 `id`(SRS 채번)와 이름이 다름:

```json
{"records": [{"file": "docs/srs/payment.md", "anchor": "fr-payment-001",
              "space": "dev3", "item": "REQ-118"}]}
```

```bash
python3 .claude/vway-kit/scripts/alm_docs.py --record \
  --map .claude/vway-kit/.vdev/alm-docs/record.json
```

   여기서도 같은 규율 — 최상위 키(`records`)면 되쓰기가 통째로 안 일어나고, 원소 키면 그
   원소만 빠짐.

### 6. 보고

한 줄씩 — **판정한 스페이스 목록**과 0단계에서 뺀 스페이스(뺀 사유와 함께) · 어느 서버로
붙었는지(스페이스 키와 채택한 접두) · 스캔 건수 · 스페이스별 열거 건수와 잘림 여부 ·
갈래별 건수 · 이번에 옮긴 건수 · 사람이 봐야 할 것(끊긴 매핑·중복 매핑).

목록을 싣는 이유는 빠진 스페이스가 표에 안 뜨는 것 — 목록이 없으면 한쪽만 판정받은 실행과
전부 깨끗한 실행을 읽는 쪽이 구별 못 함.

## 금지

- 보드를 만들지 않음(`create_workboard`). 오타가 조용히 유령 보드를 부르는 것보다 오타에서
  멈추는 것이 나음
- `derives`·`verifies` 링크를 만들거나 지우지 않음
- 상태·진행률·커버리지를 옮기지 않음
- 도구 이름을 조립하지 않음 — 0단계가 채택한 접두만 씀
- 한 실행에서 두 방향을 함께 적용하지 않음
