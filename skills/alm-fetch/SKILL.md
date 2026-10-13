---
name: alm-fetch
description: The propagation-walking sub-step /task-sync invokes when Recoble propagation is enabled — walks the parent chain read-only, judges each parent's subset, and returns a change plan as a file. It writes nothing to the board. Not usually invoked directly.
context: fork
model: sonnet
background: false
disallowed-tools: Edit, Bash, WebFetch, WebSearch
---

# /alm-fetch - walk the propagation graph and return a change plan / usage: [접두 · 시드 · 경로]

## Purpose

전파 연쇄를 **쓰지 않고** 끝까지 밟아 변경 계획을 파일로 냄. 보드에 아무것도 안 씀 — 판정과
쓰기는 부른 쪽 몫.

## Arguments

- **도구 접두** — 아래 도구 이름은 전부 그 접두 뒤에 붙음(`<접두>list_entity_links`).
  부른 쪽이 해석해 넘긴 값만 사용, **이름 조립 금지**
- **시드 집합** — 부른 쪽이 넘긴 항목 id 들(정의는 [`task-sync`](../task-sync/SKILL.md) R6)
- **`propagate` 블록** — `links`·`depth`·`progress`·`status`
- **계층 선언** — 부른 쪽이 `alm_layers.py` 로 해석한 것
- **출력 경로** — `.claude/vway-kit/.vdev/fetch/<space>.json`
- **전파 문서 경로** — 규칙의 SSOT, 부른 쪽이
  `${CLAUDE_PLUGIN_ROOT}/skills/task-sync/references/recoble-propagation.md` 로 건넴. 여기서 읽음
- **스키마 문서 경로** — 부른 쪽이 `${CLAUDE_PLUGIN_ROOT}/skills/alm-fetch/references/plan-schema.md`
  로 건넴

## Execution

1. 전파 문서와 스키마 문서를 읽음.
2. 그 문서의 「판정」 절을 **그대로** 밟음(자기 예측을 자기 순회에 반영하는 것 포함). 더
   똑똑하게 해석하지 않음 — 부른 쪽의 폴백 경로와 다른 답이 나옴.
3. 「판정」의 방문 상한(「연쇄」)에서 멈추고 그 사실을 계획에 기록.
4. 스키마대로 계획을 출력 경로에 씀.

`get_workboard_item` 결과는 실행 내내 캐시함 — 같은 항목이 여러 상위의 하위집합에 드는 것이
정상임.

## 금지

- `create_*`·`update_*`·`delete_*`·`create_entity_link` 호출 금지. 이 스킬은 읽기만 함
- 지정된 출력 경로 밖 어디에도 쓰지 않음
- 도구 이름을 조립하지 않음 — 넘겨받은 접두만 씀
- 열거가 한 페이지에 안 들어온 상위는 **판정하지 않음**. `proposed: null` 과 사유를 적음
- 수치를 지어내지 않음 — `mcp_calls`·`pages` 는 실제로 센 값

## 반환

표 하나 — 계획 경로 · 방문 수 · MCP 호출 수 · 상한에 걸렸는가. **본문은 응답에 싣지 않음**:
요약이 숫자를 조용히 바꾸면 부른 쪽이 못 알아봄.
