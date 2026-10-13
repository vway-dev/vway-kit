# Recoble MCP 서버 해석

[`task-import`](../SKILL.md)·[`task-sync`](../../task-sync/SKILL.md)·[`alm-trace`](../../alm-trace/SKILL.md)
가 Recoble 도구를 처음 부르기 전 1회. 확정한 **도구 접두**를 그 실행 내내 재사용.

호스트가 스페이스에 붙는 길이 둘이라 도구 이름이 하나가 아님 — 사람이 `claude mcp add` 로 넣은
local 스코프 서버, 또는 claude.ai 커넥터(접두를 호스트가 정함). 세션에 노출된 도구 목록에서
서버 이름 `recoble-<스페이스>` 로 찾음 — **도구 이름 모양은 하네스마다 다름**(Claude Code 실측:
`mcp__<server>__<tool>`, 커넥터는 `mcp__claude_ai_recoble-<슬러그>__…`; 다른 하네스는 미실측).
그래서 절차는 이름 모양이 아니라 행동으로 적음 — **세션의 도구 목록에서 찾기**, 목록에 이름만
있고 로드 안 된 도구는 호스트의 도구 탐색 프리미티브로 먼저 로드. 판정(스페이스 키 매칭 →
`get_connection_info` 호출 → uuid 대조)은 하네스와 무관하게 같음.

## 절차

1. 도구 목록에서 서버 `recoble-<space>` 의 `get_connection_info` 를 찾아 호출(로드가 필요하면
   먼저 로드). 성공 → 그 도구 이름에서 `get_connection_info` 앞부분을 접두로 확정, 끝.
2. 그 도구가 없거나 호출이 "도구 없음" 으로 실패하면, 도구 목록에서 이름에 `recoble` 이 들고
   `get_connection_info` 로 끝나는 도구를 전부 후보로 열거.
   **이름 조립 금지** — 접두는 호스트가 정하므로 지어낸 `mcp__claude_ai_recoble-<space>__…` 는
   없는 이름을 부르거나(실패) 슬러그가 겹치는 남의 스페이스를 침.
3. 후보마다 `get_connection_info` 호출. 채택 조건은 **`space.id` == `alm.recoble.spaces[<space>].mcp_url`
   경로의 uuid**(`https://mcp.recoble.com/s/<uuid>/mcp`) 하나뿐 — 둘은 같은 값(커넥터 실측).
   서버 이름이 스페이스 키와 닮은 것은 근거 아님 — 커넥터 이름은 claude.ai 에서 사람이 붙임.
4. 채택한 후보의 도구 이름에서 `get_connection_info` 앞부분을 그대로 떼어 접두로 씀. 이후 도구는
   전부 그 접두 + 도구명 — 단 **세션이 실제로 보여준 이름만** 부름(조립 금지는 여기에도 적용).
5. **일치 0 → 한 줄 보고 후 그 provider 중단**(마커 미기록). 보고에 본 후보 이름을 적어 사람이
   커넥터를 붙이거나 `mcp_url` 을 고치게 함. `mcp_url` 이 없거나 example 자리표시자면 대조 근거가
   없으므로 같은 중단 — uuid 없이 채택하면 어느 스페이스에 쓰는지 모르고 씀.
6. 일치 둘 이상 → 같은 스페이스에 붙은 중복 연결. 첫 후보 채택, 나머지 이름은 경고 한 줄.

## 결과 보고

**어느 서버로 붙었는지 그 실행의 보고에 한 줄** — 스페이스 키와 채택한 접두. 2단계로 붙은 실행은
사람이 고른 적 없는 서버를 쓴 것이라, 적지 않으면 나중에 항목이 어디로 갔는지 못 되짚음.

마커(`.claude/vway-kit/.vdev/alm`)에는 넣지 않음 — 형식이 `<provider>:<space>:<item_id>` 이고
`task-sync` 가 `cut -d: -f3-` 로 항목 id 를 읽음(4번째 필드는 id 를 오염시킴). `task-sync` 도
이 절차를 다시 돌려 접두를 얻음.

## 401

미인증. local 스코프 경로는 등록된 `Authorization` 헤더의 PAT 가 없거나 만료된 것 — 사람이
터미널에서 `claude mcp remove` 후 새 PAT 로 `claude mcp add` 를 다시 해야 함(`/vdev-init` 재실행이
그 명령을 다시 찍어 줌). **커넥터 경로는 그 방법으로 못 고침** — claude.ai 커넥터 설정에서
인증해야 하고, 세션 안에서 진행 불가.
