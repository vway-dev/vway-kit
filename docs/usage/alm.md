# ALM 연동

`/vdev` 가 작업을 ALM 항목과 잇습니다. provider 는 `vdev-config.alm.provider`(`recoble` | `teamer` |
`none`, 또는 `[recoble, teamer]`)이고, 요청이 한 곳을 지목하면("Teamer 연동") 그 하나로 좁혀집니다.
`alm.auto: true` 면 시작 시 항목을 만들고 끝날 때 요약·상태를 올립니다. **ALM 실패는 게이트가 아닙니다**
— 그 단계만 건너뜁니다.

## Recoble

### 서버 등록

`/vdev-init` 이 스페이스 이름과 MCP 주소를 물어 `alm.recoble.spaces` 에 적고, 스페이스마다 등록 명령을
찍어 줍니다. 자기 터미널에 붙여넣고 `<PAT>` 에 Recoble 개인 액세스 토큰을 채웁니다:

```bash
claude mcp add -t http recoble-labs \
  https://mcp.recoble.com/s/<uuid>/mcp \
  -H "Authorization: Bearer <PAT>"
```

- 저장 위치는 `~/.claude.json` 의 **이 저장소 경로 밑**(local 스코프) — 저장소·모델 컨텍스트에 안 들어갑니다.
  worktree 는 경로가 달라 각각 등록합니다.
- 저장소 `.mcp.json` 은 쓰지 않습니다 — 팀 공유 파일이라 사람마다 다른 PAT 를 못 담고, git 에 실리면 토큰이 샙니다.
- 다음 `/vdev-init` 은 등록 상태(`type`·`url`·`Authorization` 헤더 존재)를 **읽어** 맞으면 건너뛰고,
  어긋나면 `claude mcp remove` + `add` 를 보여줍니다. 헤더 값은 읽지 않습니다.
- Codex 는 등록 위치(global 스코프)와 인증(토큰을 담은 환경 변수 이름)이 달라 명령도 따로입니다 —
  `harnesses` 에 `codex` 가 있으면 `/vdev-init` 이 그 명령도 판정해 찍습니다([Codex](codex.md#recoble-mcp-등록)).
- workboard 는 Recoble 웹에서 **미리 만들어 두세요** — vway-kit 은 보드를 만들지 않습니다.

### 항목 상태

`시작 전 → 진행 중 → 검토 → 완료`. `/vdev` 가 항목을 가져오거나 만들면 **진행 중**, 구현이 끝나
`task-sync` 가 돌면 **검토**입니다. **완료는 자동으로 찍히지 않습니다** — 검증 통과 뒤
`/task-sync <항목…> --verified` 로 확인 질문에 답해야 넘어갑니다.

- 상태 키는 보드마다 달라 `status_start`·`status_review`·`status_done` 에 적습니다. 보드에 없는 키는 무시되고 경고만 남습니다.
- `status_review` 가 비면 검토 없이 `status_done` 으로 갑니다. 검증 규율을 원하면 반드시 채우세요.
- 사람이 손으로 검토에 올려 둔 항목은 전이를 건너뜁니다.
- 판정 규칙의 SSOT 는 [recoble-status.md](../../skills/task-import/references/recoble-status.md).
- `propagate.enable: true` 면 끝난 항목의 **상위**까지 완료 비율로 굴립니다(상위는 **검토**까지만).

### 계층 추적 — `layers`

스페이스에 `layers`(요구사항 → 설계 → 작업 → 검증)를 선언하면 `/vdev` 가 `task-import` 대신
`alm-trace` 로 가서 계층 그래프를 만들고 `derives`·`verifies` 로 잇습니다. 계층마다 **실재하는**
workboard 를 적습니다:

```yaml
alm:
  recoble:
    spaces:
      labs:
        layers:
          requirement: { workboard: "요구사항" }
          design:      { workboard: "설계", derives_from: requirement, feature_design: true }
          task:        { workboard: "dev-board", derives_from: design, marker: true }
          defect:      { workboard: "결함 관리", verifies: requirement, defect: true }
```

전체 키(`template`·`status`·`category`·`fields`·`run`·`runs` 등)는 example 의 `layers` 주석이 SSOT 이고,
모르는 키는 경고로 나옵니다.

- **`marker: true`** — `/vdev` 마커에 실릴 계층(많아야 하나).
- **`feature_design: true`** — 설계를 기능마다 항목 하나로 둡니다. 새 작업은 그 기능의 설계 항목을 찾아
  잇고, 없으면 조사해 만듭니다. 여러 요구사항·작업이 공유하므로 상태 전파에서 빠지고, 작업은 요구사항에
  직접 도출 링크로도 걸립니다. 작업이 끝나면 `task-sync` 가 그 설계 본문을 확정 내용으로 다시 씁니다.
- **`defect: true`** — 요청이 이미 만든 것에 대한 것이면 결함으로 처리합니다.
  1. 작업·요구사항 보드를 함께 훑어 후보를 등급과 함께 제시 — 등급은 스캔한 LLM 의 확신도이고
     `high` 는 묻지 않고 연결, `medium` 은 물어서 연결, `low` 는 보고에 이름만 남김
  2. **재사용 / 결함 / 신규 / 중단** 중 선택
  3. 결함이면 결함 항목 생성 → 어긴 요구사항·작업에 `verifies` → `marker` 계층에 수정 작업 생성 →
     결함에서 `derives` → 마커는 그 수정 작업. 걸 요구사항이 없으면 요구사항을 새로 만듭니다.
  4. 신규·재사용이면 결함 계층을 세지 않습니다 — 빈 결함이 `verifies` 로 매달리면 요구사항이 영영 안 닫힙니다.

  결함 보드는 검증(테스트케이스) 보드와 나누세요 — 수명주기가 달라 한 보드면 상위 완료 비율이 섞입니다.
- **`run: true`** — 테스트 실행이 회차 항목(scope × build × environment)으로 남습니다. 승격 검증은 PASS 여도
  만들고, 개발서버 확인은 결함이 났을 때만 만듭니다. 회차는 `relates_to` 로만 붙어 전파 분모 밖입니다.
  회차가 결과를 적으면 판정과 무관하게 `/task-sync <케이스…> --propagate` 가 요구사항의 진행률·
  `coverage_status` 를 갱신합니다. 상태는 옮기지 않으므로, 완료된 요구사항도 케이스가 깨지면 `NOT_COVERED`
  가 되어 리그레션이 보드에 남습니다.
- **`fields`** — 판정에 쓰는 값의 자리를 역할 이름(`module`·`result`·`latest_result`·`coverage_status` 등)으로
  선언하고 오른쪽에 보드의 필드 key 를 적습니다.
- **`issue_tracker_guide`** — 보드 규약처럼 사람이 읽는 산문은 그 문서가, 기계 판정 값은 config 가 가집니다.
- **`promotion_verification.exit_criteria`** — 승격 검증 PASS 기준. 없으면 스위트 전체 PASS.

### SRS 대조 — `/alm-docs`

`docs/srs` 의 FR·C 와 `requirement` 계층이 어긋났는지 리포트합니다. 옮기는 것은 사람이 고른 한 방향뿐
(`--pull` 보드 → repo, `--push` repo → 보드)이고 게이트가 아닙니다. 매칭 키는 앵커 줄 끝의 주석입니다:

```markdown
<a id="fr-payment-001"></a>**FR-PAYMENT-001** 카드·간편결제를 지원함. <!-- alm: labs/REQ-118 -->
```

| 갈래 | 뜻 | 자동 처리 |
|---|---|---|
| 한 번도 안 올림 | 앵커에 주석 없음 | `--push` |
| 끊긴 매핑 | 주석의 id 가 보드에 없음 | 없음 — 사람이 판단 |
| 보드에만 있음 | 어느 앵커도 안 가리킴 | `--pull` |
| 제목 다름 | 양쪽 제목이 다름 | 방향에 따라 |
| 중복 매핑 | 두 앵커가 같은 항목을 가리킴 | 없음 — 사람이 판단 |

- 주석에 스페이스를 함께 적는 것은 스페이스가 다르면 같은 id 도 다른 항목이기 때문입니다. 스페이스가 둘이면
  주석도 둘입니다.
- `--pull` 로 들어온 문장은 **(확인 필요)** 를 달고 옵니다. `--push` 는 링크를 긋지 않습니다(`alm-trace` 소유).
- 보드 열거가 상한에 잘리면 「보드에만 있음」「끊긴 매핑」은 세지 않고 그 사실을 보고합니다.
- 범위는 SRS 의 FR·C 뿐입니다. SDS ↔ `design` 계층과 NFR·CON·ROLE 축은 아직입니다.

## Teamer

- **계정** — 터미널에서 1회 `python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" setup`. 자격증명은 OS
  키체인(keyring)에 저장되고 평문 파일·대화에 남지 않습니다. 옛 `teamer_account.md` 가 있으면 이관 후
  삭제합니다. `keyring` 이 없으면 `python3 -m pip install keyring`.
- **번호** — `alm.teamer` 의 `project_no`·`workitem_no`·`workflow_no`.
- **가져오기** — 항목을 검색해 `feature/{번호}-{english-title}` 브랜치와 `docs/tasks/{사용자}/{번호}_{제목}.md`
  문서(`## Content` 만 채움)를 만듭니다.
- **동기화** — 요약을 미리보기로 확인받은 뒤 기존 내용을 보존하며 쓰고, 상태를 **검토**로 옮깁니다.

## 인수인계 — `handoff`

`task-sync` 가 ALM 필드에 쓸 내용을 **종류별로** 정의합니다(기본 AI 요약도 `summary` 한 종류).
`handoff` 가 아예 없으면 기본 AI 요약이 동작합니다. 설정은 있는데 어떤 종류도 그 provider 를 겨냥하지
않으면 그쪽에는 **아무것도 쓰지 않습니다**(조용한 no-op).

```yaml
handoff:
  summary:
    enable: true
    author: AI              # AI/LLM/Agent → AI 대필, 그 외 → 사람 이름
    AskUserQuestion: false
    field: item_content     # 문자열 = Teamer 필드. Recoble 은 댓글
  qa:
    enable: false           # 새 종류는 enable: true 라야 켜짐
    author: AI
    AskUserQuestion: true
    instruction: "QA 인수인계 — 테스트 범위, 재현 절차, 리스크 포인트"
    field:                  # 매핑 = provider 별. 없는 키는 그 provider 에 안 보냄
      teamer: col22
      recoble: "custom:impl_note"
```

| author | AskUserQuestion | 내용 출처 |
|--------|:---------------:|-----------|
| AI | false | 작업 문서로 **자동 생성** |
| AI | true | 입력한 **작성 지침**대로 대필 |
| 사람 | true | 실행 시 **즉석 입력** |
| 사람 | false | 작업 문서의 `## Handoff (<종류>)` 그대로 |

| provider | 쓸 수 있는 대상 |
|---|---|
| Teamer | `item_content`(뒤에 추가) · `colXX`(덮어쓰기) |
| Recoble | `comment`(기본) · `description`(본문 뒤에 추가) · `custom:<필드-key>` · `priority`·`startDate`·`endDate`·`category` |

- **쓰기 모드** — `append: true|false`, 생략하면 대상별 기본(`item_content`·`comment`·`description` 은 추가).
- **literal** — `value` 를 가진 종류는 댓글 폴백을 타지 않습니다. Recoble 에도 쓰려면 매핑으로 대상을 명시하세요.
- **Recoble 필드 제약** — 긴 글은 `RICH_EDITOR` 타입에만 들어가고, `LABELS`/`DROPDOWN` 에 선택지 밖 값을 넣으면 건너뛰고 경고합니다.
- **템플릿** — 본문은 provider 와 무관하게 Markdown 하나입니다. `template` 을 생략하면
  `handoff/<종류>.md` 를 찾고(종류 이름의 `/`·`\` 는 `_`), `.claude/vway-kit/templates/` 밑 같은 경로의
  파일이 출하본보다 우선합니다. `/vdev-init` 은 **선언한** 종류·계층의 출하본만 시드하고(이미 있으면 둠),
  `template` 값은 그 디렉터리 **안**이어야 합니다(`..`·절대경로는 기본값으로).
- AI 대필 내용 끝에는 `_Author: 이름 (날짜)_` 한 줄이 붙습니다(`author` 가 비면 없음).
- Teamer 필드에는 Markdown 이 평문으로 들어가므로, HTML 로 렌더하는 필드에서는 `##`·`_` 가 그대로 보입니다.

## Worklog

`alm.worklog: true` 면 task-sync 가 summary 끝에 착수·완료 시각과 **AI Agent 활동** 시간을
붙입니다(기본 `false`).

- 착수 = task 문서 `**Created:**`(로컬 `YYYY-MM-DD HH:MM`), 완료 = sync 시각.
- 활동 시간(`HH:MM`)은 이 작업 브랜치에서 Claude Code·Codex 세션이 일한 시간입니다.
  - 에이전트가 실행 중인 시간은 전부 셉니다 — 백그라운드 작업이 끝나기를 기다린 시간 포함.
  - 사람을 기다린 시간(턴 사이, 질문, 권한 승인)은 한 번에 15분까지만 셉니다.
  - limit·인증 오류로 멈춘 뒤 다시 시작하기까지는 세지 않습니다.
  - 브랜치는 저장소 reflog 의 전환 기록으로 가릅니다. `/vdev` 시작부터 작업 브랜치로 옮기기까지,
    작업 브랜치에서 통합 브랜치로 옮긴 뒤 sync 까지도 이 작업입니다.
- 셀 수 없는 것: Claude·Codex 밖에서 한 일, Codex 의 권한 승인 대기(15분 상한 없이 셈), 세션 기록·reflog 보존 기간을 넘긴 구간.
- git 2.36 미만이면 worktree 목록을 못 읽어 저장소 안에 중첩된 다른 worktree 의 세션까지 섞여 셉니다(경고가 뜸).

착수일·완료일을 보드 날짜 필드에 쓰려면 handoff 종류 `start_date`(`value: "${started}"`)·
`end_date`(`value: "${today}"`)를 켜고 `field` 에 보드의 필드를 적습니다.
