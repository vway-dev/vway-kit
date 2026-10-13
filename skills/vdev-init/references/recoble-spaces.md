# Recoble 스페이스 수집 · MCP 등록 안내

`/vdev-init` 이 `alm.recoble.spaces` 를 채우고, 사람이 실행할 MCP 등록 명령을 낼 때 따르는 절차.
SKILL.md 본문이 이 파일을 가리킴.

**vway-kit 은 MCP 서버를 등록하지 않음.** 저장소 `.mcp.json`(project 스코프)은 팀 공유라
사람마다 다른 PAT 를 못 담고 git 에 실리면 토큰이 샘. 서버는 사람이 자기 터미널에서
`claude mcp add`(local 스코프 — `~/.claude.json` 의 프로젝트 경로 밑)로 넣고,
`/vdev-init` 은 그 상태를 **읽기만** 해 정상이면 건너뛰고 어긋나면 고칠 명령을 보여줌.

## 1. 수집 (Step 1 — `vdev-config.yaml` 작성 중)

1. Ask the user (structured choice) — "Recoble 워크보드를 ALM 으로 쓰나요?" (예 / 아니오 / 나중에).
   - **아니오** → `alm.provider` 를 `none` 으로 두고 `recoble` 블록 비움. 이후 단계 생략.
   - **나중에** → example 의 블록을 주석 처리해 삽입, 이후 단계 생략.
2. 스페이스마다 두 값 수집. 하나 받을 때마다 "스페이스를 더 추가할까요?" 질문.
   - **이름(슬러그)** — `^[a-z0-9-]+$` 만 허용. 어긋나면 사유를 말하고 재질문.
     이 값이 MCP 서버 키(`recoble-<이름>`)이자 툴 이름(`mcp__recoble-<이름>__…`)이 되므로,
     대문자·공백·점이 들어가면 Claude Code 가 `_` 로 치환해 스킬이 부르는 이름과 어긋남 —
     그 뒤 모든 실행이 [서버 해석](../../task-import/references/recoble-server.md) 우회로 감
     (호출 몇 번을 더 쓰고, `mcp_url` uuid 가 맞아야만 살아남음).
   - **`mcp_url`** — Recoble 웹의 MCP 연결 화면에서 복사한 `https://mcp.recoble.com/s/<uuid>/mcp`.
     추측 금지. URL 자체는 자격증명이 아님(인증 없이 붙으면 401).
3. 스페이스가 둘 이상이면 ask the user (structured choice) 로 `default` 선택. 하나뿐이면 그것이 `default`.
4. `workboard`(이름 또는 id)와 선택값 `status_start`/`status_review`/`status_done` 질문.
   **workboard 는 사람이 Recoble 에서 미리 생성** — `/vdev-init` 은 생성하지 않음.
   상태 키를 모르면 비워 두게 함(비면 그 전이 없음). 키의 뜻과 미실재 키 처리는
   [recoble-status](../../task-import/references/recoble-status.md) 가 SSOT.
   보드 이름이 그 스페이스에서 중복이면 **id 로 적게** 함 — 실행 시점의 해석은 중복을
   보는 순간 멈추므로([task-import](../../task-import/SKILL.md) 2단계), 여기서 id 를 받아
   두는 것이 그 중단을 미리 없애는 유일한 자리.
5. **계층 추적** — Ask the user (structured choice) "요구사항·설계·작업·검증을 각각 항목으로 남기고
   링크로 이을까요?"(예 / 아니오, 기본 **아니오**).
   - **아니오** → `layers` 를 안 씀. 항목 하나만 다루는
     [task-import](../../task-import/SKILL.md) 경로가 그 호스트의 ALM 이고 그것이 기본.
   - **예** → 계층마다 아래를 받아 `alm.recoble.spaces[<스페이스>].layers` 에 기록.
     example 주석의 네 계층(requirement·design·task·verification)을 출발점으로 보여주되
     **계층 키도 보드 이름도 그 팀 어휘로** 받음 — 스킬은 키 이름을 해석하지 않고
     `derives_from`·`verifies`·`marker`·`feature_design` 선언만 읽음
     ([alm-trace](../../alm-trace/SKILL.md)).
     - **보드**(이름 또는 id) — 사람이 미리 만들어 둔 것. 없으면 만들고 오게 안내.
       두 계층이 같은 보드를 가리키면 앵커 판정이 갈리지 못해 실행이 멈춤 — 계층마다
       다른 보드를 받음.
     - **관계** — 무엇에서 도출되는지(`derives_from`) 또는 무엇을 검증하는지(`verifies`).
       루트 계층은 둘 다 없음. 가리키는 계층 이름은 같은 선언 안에 있어야 함.
     - **marker** — `/vdev` 마커에 실릴 계층 **하나**(보통 작업 계층). 정하지 않으면 작업
       문서도 `task-sync` 도 돌지 않음을 고지하고 확인받음.
     - **feature_design** — 설계 계층을 기능마다 항목 하나로 둘지(`feature_design: true`).
       켜면 설계 항목이 여러 요구사항·작업에 공유되어 전파에서 빠지고, 작업은 요구사항에 직접
       도출 링크로도 걸림. 기본 **예**를 권함 — 끄면 설계가 변경마다 흩어짐.
     - **defect** — 결함이 앉을 계층 **하나**(`defect: true`). 이 선언이 결함 진입을 켬:
       요청이 이미 있는 작업의 결함이면 그 보드에 결함 항목을 만들고 어긴 요구사항·작업에
       `verifies` 로 걸며, 고칠 작업을 marker 계층에 만들어 `derives` 로 이음. 안 켜면 모든
       요청이 신규 요구사항으로 감. **테스트케이스 계층과 같은 보드를 쓰지 않게** 함 —
       수명주기가 다르고(테스트는 릴리스마다 재실행, 결함은 한 번 닫힘), 한 보드면 상태 키와
       진행률을 둘이 공유해 요구사항의 완료 비율이 둘을 섞어 셈.
     - 선택값 `status`·`category` 는 묻되 모르면 비움(비면 그 값을 안 보냄).
     - `template` 은 **묻지 않음** — 생략하면 `alm/<계층키>.md` 를 찾고, 구조를 바꾸려는
       팀은 `.claude/vway-kit/templates/alm/<계층키>.md` 를 둠. 계층 키가 출하 이름
       (requirement·design·task·verification·run·defect)이면 선언 직후 셋업을 다시
       돌릴 때 고칠 파일이 놓이고, 그 밖의 키는 출하본이 없어 사람이 직접 씀.
   - 선언은 **스페이스별**. 계층을 쓸 스페이스마다 반복.
6. 받은 값을 `vdev-config.yaml` 의 `alm.recoble` 에 기록.

## 2. 확인 (Step 2.8 — 등록 안내 출력)

Step 2 의 스크립트가 `[Recoble MCP]` 블록으로 스페이스마다 판정을 이미 출력. 그 출력을 사용자에게
그대로 보여주고 다음 안내.

판정은 넷을 봄 — 항목 존재 · `type` 이 `http` · `url` 이 config 의 `mcp_url` 과 일치 ·
`Authorization` 헤더가 `Bearer ` 로 시작하고 뒤가 비지 않음. **헤더 값은 읽지 않음.**

- `[=] <서버키> 정상 (skip)` — 할 일 없음.
- `[+] <서버키> 미등록` / `[~] <서버키> <사유>` — 스크립트가 낸 명령을 사용자가 **자기 터미널에**
  붙여넣어 실행하게 함. `[~]` 는 `claude mcp remove` 가 앞에 선다(`claude mcp add` 는 같은 이름이
  있으면 거절함).
  **토큰은 절대 묻지 않음** — 명령의 `<PAT>` 자리는 사용자가 자기 터미널에서 채움.
  질문 도구로도, 대화로도 받지 않음(Teamer 자격증명과 같은 규율).
  PAT 는 Recoble 웹의 개인 액세스 토큰 화면에서 발급받게 안내.
- `[i] 등록 상태를 확인할 수 없어…` — `~/.claude.json` 이 없거나 안 읽히는 것. 판정을 못 했을 뿐이라
  전부 안내되고, 이미 등록됐으면 `already exists` 로 거절될 뿐임. 재질문 불필요.
- 스크립트가 `[!]` 줄을 냈으면 원인별로 다르게 대응.
  - **슬러그 위반**(`스페이스 키 '<name>' 는 [a-z0-9-] 만 허용 — 건너뜀`) 또는
    **`mcp_url` 누락**(`스페이스 '<name>' 에 mcp_url 이 없음 — 건너뜀`) — 그 줄을 사용자에게
    보여주고 해당 스페이스 값 재질문.
  - **자리표시자 `mcp_url`**(`스페이스 '<name>' 의 mcp_url 이 example 자리표시자입니다
    — … (건너뜀)`) — example 의 `alm:` 블록이 값 채우기 없이 들어온 상태(§4). 그 스페이스의
    실제 URL 을 §1 처럼 재질문하고, 사용자가 아직 모르면 해당 스페이스를 config 에서 삭제하거나
    `alm.provider: none` 으로 두게 안내. **추측한 UUID 대입 금지.**
  - **모양 위반**(`스페이스 '<name>' 의 mcp_url 모양이 아닙니다 — …`) — 이 값은 사람이 자기
    터미널에 붙여넣을 명령에 실리므로 https 스킴에 셸 특수문자·공백·쿼리스트링이 없어야 함.
    Recoble 웹에서 복사한 원문을 그대로 넣게 안내하고, **손으로 다듬어 통과시키지 말 것** —
    거르는 것이 규칙이지 형식 맞추기가 목적이 아님.

local 스코프는 **cwd 경로 키**다 — `claude mcp add` 는 **저장소 루트에서** 실행해야 함을 고지
(하위 디렉터리에서 등록하면 판정이 쓰는 키와 어긋나 영원히 `[+] 미등록` 으로 보이고, 재실행은
`already exists` 로 거절돼 원인이 안 드러남). git worktree 는 경로가 달라 각각 등록 필요.
등록 해제는 `claude mcp remove <서버키>` 로 사람이 직접. `/vdev-uninstall` 도 안내만 하고 지우지 않음.

## 3. 계층 점검 (Step 2 — `[ALM 계층 점검]` 블록)

Step 2 의 스크립트가 스페이스마다 `layers` 해석 결과를 찍음. 계층 미선언 호스트는
`[=] ALM 계층 선언 없음 (skip)` 한 줄로 끝남 — 계층 추적은 옵트인이라 그것이 정상.

- `[=] <스페이스>: 계층 N개 (...)` — 선언이 그래프로 성립. 할 일 없음.
- `[!] <스페이스>: ...` — 선언이 깨져 `alm-trace` 가 실행을 세움(`workboard` 부재,
  `marker`·`defect` 중복, 참조 순환). 그 줄을 보여주고 해당 값을 §1 로 재질문.
- `[~] <스페이스>: ...` — 돌긴 하나 일부가 빠짐(미선언 계층을 가리키는 링크, 템플릿
  부재, `defect` 계층에 `verifies`·`marker` 가 없음). 무엇이 안 도는지 전하고, 고칠지
  그대로 둘지 사용자가 정하게 함.

`alm-trace` 는 이 판정을 실행 시점에 다시 하지만, 그때는 사람이 이미 요청을 넣고
분기를 고른 뒤라 남는 선택지가 중단뿐임. 셋업에서 한 번 보이는 것이 그 차이.

## 4. 구 스키마 이전 — 최상위 `teamer:` → `alm.teamer` (Step 2.5)

Teamer 번호는 최상위 `teamer:` 에서 `alm.teamer` 로 이동. `load_alm_config` 는 `alm:` 이
**없을 때만** 최상위 블록을 읽으므로, `alm:` 이 생기는 순간 옛 값은 조용히 사망. Step 2 스크립트의
`[폐기 필드 점검]` 이 `폐기된 최상위 teamer:` 를 보고하면 **슬롯 백필 수락 전에** 다음 수행.

1. 보고 줄에 찍힌 호스트의 실제 번호(`project_no=… , workitem_no=… , workflow_no=…`) 확보.
2. example 의 `alm:` 블록 삽입 후, `alm.teamer` 의 값을 **1의 값으로 교체**.
   example 이 들고 오는 `996` / `188180` / `164489` 는 vway 저장소의 예시 번호 — 그대로 두면
   그 팀의 Teamer 연동이 남의 프로젝트를 가리킴.
3. `alm.recoble.spaces` 의 `mcp_url` 자리표시자도 같은 삽입으로 유입. §1 로 실제 값을 받거나,
   Recoble 미사용이면 `recoble` 블록을 지우고 `alm.provider` 를 `teamer`(또는 `none`)로 설정.
   자리표시자는 `[!]` 로 걸러져 등록 안내에 나오지 않음(§2).
4. `alm.teamer` 가 채워진 것을 확인한 뒤에야 최상위 `teamer:` 블록을 **Edit 로 제거**
   (PyYAML round-trip 금지 — 주석·포맷 보존). 확인 전 삭제 금지.
5. `alm.provider` 를 사용자에게 확인. 구 스키마 호스트는 Teamer 를 쓰고 있었으므로 기본
   `recoble` 을 무조건 남기면 ALM 대상이 말없이 바뀜.

## 5. 필드 점검 (Step 2d — 계층이 `fields` 를 선언했을 때)

`[ALM 계층 점검]` 은 선언이 말이 되는지만 봄. 그 필드가 **보드에 실재하는지**는 MCP 만 알므로
스크립트가 아니라 AI 의 일.

계층마다 그 보드에 `list_workboard_fields` 를 걸어 `fields` 가 매핑한 key 와 대조, 결핍을 보임:

```
[ALM 필드 점검]
  ✓ 설계(SDS): service · feature
  ! 테스트 케이스(RTC): latest_result · latest_run 없음
  ! 테스트 실행(RTR): result · scope · build · environment 없음
```

**승인받고 생성** — `create_workboard_field`. 타입과 선택지는 역할이 정함(아래 표가 그
SSOT — 다른 문서가 이 값을 다시 적으면 실행 쪽과 갈림):

| 역할 | 타입 | 선택지 |
|---|---|---|
| `result` · `latest_result` | DROPDOWN | `PASS`·`FAIL`·`BLOCKED`·`NOT_APPLICABLE`·`NOT_RUN` |
| `coverage_status` | DROPDOWN | `COVERED`·`NOT_COVERED`·`UNCOVERED` |
| `module` · `feature` | LABELS | 호스트가 정함(다중값 — 한 변경이 여럿에 걸침) |
| `suite` · `environment` | DROPDOWN | 호스트가 정함(단일값) |
| `scope` · `build` · `latest_run` · `covers` | TEXT | — |

보드 스키마는 그 스페이스를 쓰는 팀 전체에 보이므로 조용한 생성 금지. 거절하면 그대로 두고
다음으로 — 필드가 없는 호스트는 그 판정만 건너뜀.

여기서 안 만들면 그 결핍을 다음에 만나는 자리가 승격 도중.
