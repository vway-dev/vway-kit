# 전파 변경 계획 스키마

[`alm-fetch`](../SKILL.md) 가 쓰고 `scripts/alm_plan_check.py` 가 읽음. 키 집합의 SSOT —
스크립트가 여기 없는 키를 요구하면 fetch 가 못 만드는 것을 요구하는 것이고, 그것이 조용한
전파 중단이 됨.

## 최상위

| 키 | 형 | 무엇 |
|---|---|---|
| `space` | str | 이 실행의 Recoble 스페이스 키 |
| `depth` | int | `propagate.depth` 를 그대로 옮김. `0` 은 무제한 |
| `visit_cap_hit` | bool | 방문 상한([연쇄](../../task-sync/references/recoble-propagation.md#연쇄))에 걸려 멈췄는가 |
| `mcp_calls` | int | 이 실행이 쓴 MCP 호출 총계 |
| `boards` | obj | `projectId` → `{name, statuses[]}`. `statuses` 원소는 `list_workboard_statuses` 가 준 `key`·`done`·`statusGroup`·`sortOrder`·`isEntry` |
| `entries` | list | 아래 |

`boards` 가 있어야 스크립트가 상태 키의 실재와 전진을 판정함. 없으면 config 키 존재만
확인하게 되고, 그 키를 안 쓰는 호스트에서 가드가 통째로 빠짐.

## `entries` 원소

| 키 | 형 | 무엇 |
|---|---|---|
| `item` | obj | `{id, name, projectId}` |
| `level` | int | 시드에서 몇 단. 시드의 직상위가 `1` |
| `layer` | str·null | 계층 키. 못 정하면 `null` |
| `layer_mode` | str | `declared` 또는 `fallback`(계층 해석 실패로 상태 규칙을 씀) |
| `current` | obj | `{status, progress}` — 순회 시점 값 |
| `children` | list | `{id, projectId, layer, basis, done}`. `basis` 는 `status` 또는 `latest_result` |
| `enumeration` | obj | `{paths[], pages, complete}` |
| `ratio` | obj | `{done, total}` |
| `branch` | str | `full`(`ratio == 1`) · `partial`(`0 < ratio < 1`) · `none`(그 외) |
| `proposed` | obj·null | 아래. 판정 안 하면 `null` |
| `skip_reason` | str·null | `proposed` 가 `null` 인 사유 |

## `proposed`

| 키 | 형 | 무엇 |
|---|---|---|
| `status` | str·null | 제안 상태 키 |
| `progress` | int·null | 제안 progress |
| `coverage_status` | str·null | `COVERED`·`NOT_COVERED`·`UNCOVERED` |
| `depends_on` | obj | 필드명 → 기대는 계획 항목 id **목록** |

`progress`·`coverage_status` 는 스크립트가 근거를 쥐면 검산된 `ratio` 로 다시 도출해 내보냄 —
그때 여기 적힌 값은 대조용이고, 다르면 스크립트가 경고하고 도출값을 씀. 근거를 못 쥐면 여기
값이 그대로 감.

- `progress` 의 근거: 설정의 `progress: rollup`
- `coverage_status` 의 근거: 항목의 계층을 앎(`--layers` 가 있고 `layer_mode` 가 `declared`,
  `layer` 가 있음). 그 계층이 이 필드를 선언하지 않았으면 도출값은 `null`

`depends_on` 이 필드마다 갈리는 이유: `full` 상태 제안은 예측 하위가 **전부** 실현돼야
서고, `partial` 승격은 하나만 서도 성립하며, `progress` 는 하위 하나만 어긋나도 숫자가 틀림.

## 불변식

스크립트가 강제하는 것들.

1. `enumeration.complete == false` 이면 `proposed` 는 `null`
2. `ratio.done` 은 `children` 중 `done: true` 의 수, `ratio.total` 은 `children` 의 수
3. `branch` 가 `ratio` 와 맞음
4. `proposed.status` 는 그 항목 보드의 `statuses` 에 있는 `key`
5. `proposed.status` 는 `current.status` 보다 등급이 높음 — 둘 다 보드 플래그로 매겨질 때만
   판정(등급 정의는 [recoble-status](../../task-import/references/recoble-status.md) 「등급」,
   `sortOrder` 서열 금지도 거기 SSOT)
6. `layer_mode == "declared"` 이고 계층이 `fields.latest_result` 를 선언했으면 그 하위의
   `basis` 는 `latest_result`
7. `depends_on` 의 모든 id 가 `entries` 에 있고, 그 그래프에 순환이 없음
8. `depth != 0` 이면 모든 `level` 이 `depth` 이하
9. `propagate.depth`·`status`·`progress` 가 config 로 오면(`--config` 또는 `--propagate`)
   그것이 권위 — `depth` 는 계획의 값과 같아야 하고, 축이 `off` 면 그 축의 제안이 없어야 함
   — `--status-off` 는 불러온 블록의 `status` 만 `off` 로 덮음(task-sync 전파 전용 모드)
10. `entries` 개수는 방문 상한([연쇄](../../task-sync/references/recoble-propagation.md#연쇄))을
    넘지 않고, `visit_cap_hit` 이 `true` 면 그 개수가 정확히 그 상한과 같음
11. `--layers` 에 `feature_design` 계층이 있으면 모든 entry 의 `layer_mode` 가 `declared` 이고,
    entry 의 `layer` 와 `children` 의 `layer` 어디에도 그 계층이 없음
