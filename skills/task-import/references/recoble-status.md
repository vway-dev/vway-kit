# Recoble 상태 키와 전이 판정

항목 상태를 바꾸는 모든 자리가 따르는 절차. 도구 이름은 [recoble-server](recoble-server.md) 가
해석한 접두 뒤에 붙음.

## 키

| 키 | 레벨 | 뜻 |
|---|---|---|
| `status_start` | 스페이스 | 착수 — [task-import](../SKILL.md) 가 마커를 쓰는 시점 |
| `status_review` | 스페이스 + 보드 | 구현 완료(검토). 부재 시 후보 체인이 다음으로 넘어감 |
| `status_done` | 스페이스 + 보드 | 검증 완료 |

시작 전에 해당하는 키 없음 — `create_workboard_item` 에서 `status` 를 생략하면 `isEntry: true`
상태로 앉음. 플랫폼이 이미 하는 일에 키를 얹으면 그 쓰기가 실패한 항목만 갈림.

스페이스 레벨 키는 `alm.recoble.spaces[<space>].status_start` 같은 자리, 보드 레벨 키는
`alm.recoble.spaces[<space>].boards[<보드 id 또는 이름>].status_review` — 이름으로 적은 보드 키도
받음. 항목이 실제로 속한 보드(`get_workboard_item` 의 `projectId`)가 먼저, 스페이스가 폴백.

**이름 키가 그 스페이스에서 유일하지 않으면 그 항목을 통째로 건너뛰고 경고**, 스페이스 폴백으로
감. 보드 이름은 스페이스 안에서 유일하지 않고, 같은 이름 둘 중 어느 쪽 상태 키인지 config 만
보고는 정할 수 없음 — 남의 보드 키로 전이를 시도하면 실재하지 않는 키가 되어 그 전이가 조용히
빠짐. 그 보드를 정말 겨냥하려면 키를 보드 id 로 적음.

## 보드에서 파생하는 것

`list_workboard_statuses` 가 상태마다 `key`·`done`·`statusGroup`·`sortOrder`·`isEntry` 제공.

```
done 상태   = done: true (없으면 statusGroup == "DONE")
진행 상태   = statusGroup == "IN_PROGRESS" 중 sortOrder 최소
시작 전     = statusGroup == "TODO" (isEntry 인 것이 기본값)
```

**이름으로 추론 금지.** 같은 `QA` 키가 어느 보드에서는 `TODO`, 어느 보드에서는 `IN_PROGRESS`.
플래그만 신뢰.

검토는 파생 불가 — `statusGroup: IN_PROGRESS` · `done: false` 라 진행 중과 플래그가 같음.
`status_review` 가 유일한 출처이고, 없으면 그 자리는 빔.

## 등급

이름 있는 역할 넷만 서열을 가짐.

```
0 = statusGroup == "TODO"
1 = 파생 진행 상태 (statusGroup == "IN_PROGRESS" 중 sortOrder 최소)
2 = status_review 가 가리키는 상태
3 = done 상태 (done: true, 없으면 statusGroup == "DONE")
```

`sortOrder` 로 서열을 만들지 않음 — 한 보드의 `IN_PROGRESS` 그룹에 진행 중·검토와 함께
보류·QA 가 사는 것이 실제 모양이고, 그 둘의 `sortOrder` 는 워크플로 순서가 아니라 배치 순서.
서열을 매기면 보류(4)에 선 항목을 검토(2)로 **강등**시킴.

**넷 중 어디에도 안 잡히는 상태는 판정하지 않음** — 그 항목의 전이를 건너뛰고, 사람이 옮겨야
한다는 사유를 경고에 실음. 보류·QA 에 세워 둔 항목을 자동 전이가 끌어가지 않는 지점.
`statusGroup` 이 셋 밖인 상태도 같음.

## 전이 판정

전이 직전 그 보드의 상태 목록을 읽어 셋을 확인.

1. 목표를 config 키가 지목하는가 — 지목하는데 그 키가 config 에 없으면 그 전이를 생략(경고
   불요, 설정하지 않은 것이 뜻). 보드에서 파생하는 목표(진행 상태·done)는 config 키를 안 거치므로
   이 검사 대상이 아님.
2. 목표 상태가 이 보드에 실재하는가 — 없으면 건너뛰고 경고.
3. 현재 상태에서 목표 상태가 등급상 전진인가 — 후퇴·동률이면 건너뜀. 후퇴만 경고.

후보가 여럿인 자리(task-sync R5 · 전파의 `ratio == 1`)는 후보 순서대로 1·2 를 물어 **둘 다
만족하는 첫 키**를 씀 — 실재하지 않는 후보는 경고하고 다음으로 넘김. 후보가 하나뿐인 자리
(착수)는 거기서 끝. 실재하지 않는 키를 다른 키로 조용히 바꿔 치지 않음.

config 키 이름을 열거해 가드를 세우면 그 키를 안 쓰는 호스트에서 가드가 통째로 빠짐 —
사람이 검토로 올려둔 항목을 재실행이 진행 중으로 되돌리는 경로가 그것.
`status_start` 가 `TODO` 그룹을 가리키는 설정도 이 검사에 걸림.

상태 목록을 못 읽으면 판정 불가 — 그 전이를 건너뜀. 틀린 키로 실패하느니 그냥 둠.
읽기 실패가 **비율 계산**에 걸리는 경우는 더 셈: 모르는 하위를 done 아님으로 세면 상위가 영영
안 닫히므로, 그 상위 전체를 건너뜀([recoble-propagation](../../task-sync/references/recoble-propagation.md)).

## 항목 제목

형식 `[분류] 내용`. 내용은 개조식([doc-style](../../../rules/doc-style.md)).

- `분류` = 유형(`category` 필드) 안의 세부 분류. 유형 자체를 제목에 다시 적는 것은 중복 — 금지.
- 어휘는 그 보드 기존 항목 제목의 `[...]` 접두에서 수집해 맞춤. `list_workboard_items` 응답을
  그대로 읽음 — 추가 호출 없음.
- 수집된 어휘에 없는 분류가 필요하면 제안하고 승인받은 뒤 씀.

## 항목 본문

독자·자기완결·형식 규칙은 [item-body](item-body.md) 가 SSOT.
