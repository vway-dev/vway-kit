# Recoble 상위/하위 상태 전파

| 절 | 누가 읽나 |
|---|---|
| 판정 | [`alm-fetch`](../../alm-fetch/SKILL.md) 와 부모 폴백 — 둘이 같은 답을 내야 함 |
| 쓰기·보고 | 부모([`task-sync`](../SKILL.md) R6)만 |

[`task-sync`](../SKILL.md) R6 이 호출. `alm.recoble.propagate.enable` 이 true 일 때만 실행.
도구 이름은 전부 R0 이 해석한 접두 뒤에 붙음(`<접두>list_entity_links`).

## 판정

### 방향

**하위 → 상위 한 방향.** 상위를 닫으면 아직 검증하지 않은 하위까지 닫히고, 그러면 그 보드는 못 믿음.
상위는 하위가 말해주는 것만 반영.

### 상위·하위를 찾는 법

`propagate.links` 가 켠 경로만 사용. `parent` 를 뺀 나머지는 `list_link_types` 의 `code` 이고,
`list_entity_links(entityType="task", entityId=<id>)` 가 링크마다 `linkTypeId`·`source`·`target` 제공.
`forwardLabel` 이 **target 쪽 이름**이므로 방향은 추측 없이 결정.

| `links` 값 | 경로 | 어느 쪽이 상위인가 |
|---|---|---|
| `parent` | 항목의 `parentTaskId` | 그 값이 상위 |
| `hierarchy` | `parent_of` (forward=하위) | **source 가 상위**, target 이 하위 |
| `derives` | `derives` (forward=도출) | source 가 상위 |
| `verifies` | `verifies` (forward=검증) | **target 이 상위** — 검증하는 쪽(source)이 끝나야 검증받는 쪽이 닫힘 |

`relates_to` 는 이 표에 없음 — 전파 경로가 아니라서임. 회차가 그 링크로만 붙는 이유가 그것.

**기능 설계 계층(`feature_design`) 항목은 상위도 하위도 아님.** 기능마다 하나인 설계서를 여러
요구사항·작업이 공유해서임 — 상위로 닫거나 하위로 세면 한 요구사항의 완료가 설계를 공유한 다른
요구사항을 닫음. 작업은 요구사항에 직접 도출 링크로도 걸려 있으므로(`direct_from`) 전파는 그
링크로 오름. 판정은 아래 「계층을 찾는 절차」로 하고, **상위 후보에도** 적용함.

유형 id 하드코딩 금지 — `list_link_types` 에서 `code` 로 조회. 못 찾은 code 는 그 경로를 버리고 경고.

`hierarchy` 가 보드를 넘는 체인의 배선. 그래서 한 상위의 하위가 여러 보드에 흩어져 있고 같은 항목이
여러 경로로 들어옴 — **항목 id 로 중복 제거**. `parent` 만 켠 설정으로는 전파가 한 건도 안 도는
스페이스 존재: 실측 체인은 두 보드에 걸쳐 전부 `parent_of` 로 걸려 있었고 `parentTaskId` 는 모두 null.

**하위는 열거해야 나옴.** `get_workboard_item` 의 `children`·`subtasks` 는 `null` 로 오므로 하위집합은
두 갈래를 합쳐 직접 구성: `parent` 는 상위가 속한 보드(`projectId`)를 `list_workboard_items` 로 나열해
`parentTaskId` 가 그 상위인 것을 선택(항목이 많은 보드는 응답 크기 때문에 `limit` 으로 좁혀야 하는데,
**좁히면 하위를 놓쳐 비율이 틀림** — 한 페이지에 안 들어오면 그 상위는 판정하지 말고 경고),
`hierarchy`·`derives`·`verifies` 는 상위의 `list_entity_links` 에서 방향으로 선택. 한 항목에 대한
`list_entity_links` 호출 하나가 그 항목이 source 인 링크와 target 인 링크를 **모두** 반환하므로 방향
판별에 추가 호출 불요.

하위집합이 **비면 판정 금지** — 비율이 `0/0`. 정상 경로에서는 시드가 그 상위의 하위이므로 최소 1개지만,
열거가 실패하면(위 페이지 초과·권한) 빈 집합 가능. 그 상위는 건너뛰고 경고.

### 상태 키

키 해석·파생·등급·**전이 판정**은 [recoble-status](../../task-import/references/recoble-status.md)
가 SSOT — 상위에 상태를 쓰는 것도 전이라 전진 판정을 그대로 받음. 보류·QA 처럼 서열 밖에 선
상위는 그래서 자동으로 안 움직임.

**보드는 항목마다 다름.** 하위가 여러 보드에 흩어지므로 키는 하위마다 그 항목의 보드
(`projectId`)로 해석. 링크로만 얻은 하위는 상태도 보드도 안 딸려 오므로 `get_workboard_item`
으로 채움 — `list_workboard_items` 로 나열한 하위는 응답이 이미 들고 있음.

그 상태 목록을 못 읽으면 **그 상위 전체를 건너뜀** — 모르는 하위를 done 아님으로 세면 비율이
낮게 나와 상위가 영영 안 닫힘.

### 완료 판정

상위 `X` 의 하위집합 = 위 경로로 찾은 `X` 의 하위 전부.

끝난 하위 = 상태가 그 보드의 `status_review` 이거나 `status_done` 이거나 done 상태
(`done: true`, 없으면 `statusGroup == "DONE"`)인 것.
사람이 검토에서 완료로 옮긴 항목도 세야 함.

#### 계층이 선언된 스페이스

`layers` 를 선언한 스페이스에서는 하위마다 판정 근거가 다름. 선언이 없는 스페이스는 위 규칙
그대로(하위호환).

**계층을 찾는 절차** — 계층 선언의 `workboard` 는 이름 문자열이고 항목이 주는 것은 `projectId`
라, 그 둘을 잇는 단계가 먼저 있어야 함:

1. 계층 선언을 받음 — fork 는 부른 쪽이 건넨 것을 그대로 씀. 부모(폴백 시)는
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/alm_layers.py" <config> --space <space>` 로 직접 해석
2. `list_workboards` **한 번**으로 이름·id 표를 받아 각 계층의 `workboard` 를 id 로 해석
   (`alm-trace` step 2 와 같은 해석 — 이름이 중복이면 그 계층은 못 품)
3. 상위 후보와 하위 항목의 `projectId` 로 그 표를 찾아 계층 판정

이 해석이 실패하면 **계층 인식을 포기하고 경고** 후 위의 상태 규칙으로 감. 조용히 폴백하면
명세 승인만으로 요구사항이 닫히는 바로 그 일이 일어남.
단 `feature_design` 계층이 선언된 스페이스는 폴백하지 않고 **전파를 멈추고 경고**함 — 상태
규칙으로 떨어지면 설계 항목이 다시 상위·하위로 섞임.

| 하위가 앉은 계층 | 끝났나 |
|---|---|
| `fields.latest_result` 를 선언한 계층(케이스) | **그 필드가 `PASS`** — 상태 아님 |
| `run: true` 계층(회차) | **하위집합에 넣지 않음** |
| `feature_design: true` 계층(기능 설계) | **하위집합에 넣지 않음** |
| 그 외 | 위의 상태 규칙 |

케이스를 상태로 세면 안 되는 이유가 둘. 케이스 상태축은 명세 수명주기(초안→승인)라 승인만으로
상위가 닫히고, 그 축은 전진 전용이라 다음 회차의 PASS → FAIL 을 못 적음. 판정은 필드가 듦.

**기준은 지정 회차**. 케이스별 최신값을 각각 비교하면 케이스 A 는 회차 5, 케이스 B 는 회차 3
에서 통과해도 둘 다 PASS 로 읽혀, 그 회차에서 돌지도 않은 케이스가 그 회차의 근거가 됨. 회차가
지정된 판정에서 그 회차의 `scope` 에 들었으나 결과가 없는 케이스는 `NOT_RUN` — 분모에 남음.

`latest_result` 를 못 읽으면(필드 미선언·미생성·권한) **그 상위 전체를 건너뛰고 경고** — 상태
목록을 못 읽을 때와 같은 방향. PASS 로 폴백하면 한 번도 안 돌린 케이스 위에서 요구사항이 닫힘.

보류·QA 처럼 서열 밖에 선 하위는 **끝나지 않은 것으로 셈** — 분모에 남아 그 상위가 검토로 못 감.
SSOT 의 "판정하지 않음" 은 그 항목에 **쓰는 것**을 막을 뿐 비율에서 빼라는 뜻이 아님. 사람이
보류를 풀어야 상위가 움직임.

```
ratio = 끝난 하위 수 / 하위 전체 수
```

- `propagate.status`:
  - `off` — 상태 미변경.
  - `all-done` — 아래 후보를 제안, 부모가 묻지 않고 씀.
  - `ask` — 같은 후보를 제안, 부모가 승인 뒤 씀(「쓰기·보고」 참고).

```
ratio == 1            → 상위 보드에서 status_review → status_done → 파생 done 순으로 첫 후보.
                        앞의 둘은 config 설정 + 보드 실재를, 파생 done 은 실재만 물음.
                        아무 후보도 못 서면 미변경
0 < ratio < 1         → X 가 시작 전일 때만 진행 상태로 승격
ratio == 0            → 미변경
X 가 이미 done        → 미변경 (강등 금지)
```

`status_review` 가 선 보드에서는 하위가 전부 완료여도 상위는 검토까지 — 상위 자신의 검증이
미실행. 그 키가 없는 보드는 체인이 완료까지 보냄(하위호환). 폴백이 없으면 상위가 아무 상태도
못 받고 정지하므로 세 단을 다 둠.

- `propagate.progress: rollup` 이면 `progress = ⌊done×100/total + ½⌋` 제안(0.5 는 올림, 예:
  1/8 → 13 · 1/3 → 33 — 파이썬 `round` 는 은행가 반올림이라 1/8 에 12 를 냄), `off` 면 제안 없음.
  하위가 없으면(`total == 0`) 제안 없음.
- `coverage_status` — 상위 계층이 `fields.coverage_status` 를 선언했으면 `ratio == 1` 이면
  `COVERED`, 하위가 하나라도 안 끝났으면 `NOT_COVERED`, 하위집합이 비었으면 `UNCOVERED` 를
  제안. 상태는 강등이 없어 한 번 완료된 상위가 리그레션 뒤에도 완료로 남으므로, 보드가 거짓을
  말하지 않게 하는 것이 이 필드임. 선언이 없으면 제안 없음.

```
seed    = 부른 쪽이 넘긴 시드 집합(정의는 task-sync R6)
visited = 빈 집합
queue   = [(항목, 0) for 항목 in seed]

queue 가 빌 때까지:
    (item, level) = queue 에서 하나 꺼낸다
    depth 가 0 이 아니고 level >= depth 면 이 항목은 더 올라가지 않는다
    item 의 상위들 각각에 대해:
        상위가 feature_design 계층이면 건너뛴다
        상위 id 가 visited 에 있으면 건너뛴다
        visited 에 넣는다
        위 판정으로 제안을 정한다
        status_review 이상으로 바뀌었거나 그렇게 제안했으면 (상위, level + 1) 을 queue 에 넣는다
```

**자기 예측을 자기 순회에 반영함.** 어떤 상위를 검토로 올릴 것이라 제안했으면, 그 상위의
상위를 볼 때 그것을 끝난 것으로 셈 — 즉시 쓰기와 같은 답이 그렇게 나옴. 의사코드를
**그대로** 밟음 — 더 똑똑하게 해석하면 부모 폴백과 다른 답이 나옴.

### 연쇄

`propagate.depth` = seed 에서 몇 단계까지 올라갈지. `1` 이면 직상위까지, `2` 면 그 상위까지,
`0` 이면 제한 없음.

`visited` 가 순환 차단. 그래도 그래프가 크면 호출이 폭주하므로, 판정한 상위가 100 에 닿았는데
아직 볼 상위가 남았으면 거기서 멈추고 **`visit_cap_hit: true`** + 경고 — 남은 상위는 다음 작업의
전파가 자연히 수거.

## 쓰기·보고

### 쓰기

- 제안된 `progress`·`coverage_status` 를 `update_workboard_item` 으로 씀 — 어느 쪽이든 제안이
  `null` 이면 그 축은 안 건드림.
- `propagate.status` 의 `ask` — 바뀔 항목을 전부 모아 한 번에 보여주고 ask the user (structured choice) 로 승인받은 뒤 적용.

### 보고

바꾼 항목을 한 줄씩 보고: 항목 이름, 새 progress, 새 `coverage_status`·status(바뀐 경우). 건너뛴 것은 이유와 함께.
아무것도 안 바꿨으면 그대로 보고.
