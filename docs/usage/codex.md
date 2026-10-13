# Codex

vway-kit 의 스킬·세션 훅·커밋 게이트는 Claude Code 와 함께 OpenAI Codex CLI 에도 설치됩니다. 이 문서는
Codex 호스트가 [일반 설치](getting-started.md#2-설치-순서) 외에 더 해야 하는 것과, 동작이 달라지는 곳을
다룹니다.

## 플러그인 설치

```
codex plugin marketplace add git@github.com:vway-dev/vway-kit.git
codex plugin add vway-kit@vway
```

- 둘 다 headless 라 TUI 없이 스크립트·CI 에서도 됩니다. Codex TUI 의 `/plugins` 에서 `vway-kit` 을 설치해도
  같습니다.
- 비공개 저장소라 [SSH 준비](getting-started.md#1-저장소-접근-준비-ssh)가 Codex 에도 똑같이 필요합니다.
- `marketplace add` 는 SSH Git URL 외에 HTTPS Git URL·`owner/repo[@ref]`·로컬 경로도 받습니다. 로컬 경로는
  그 저장소의 커밋된 HEAD 를 설치합니다 — 커밋하지 않은 변경은 설치본에 없습니다.

## 프로젝트 신뢰

`.codex/` 아래 전부는 프로젝트 신뢰(trust)에 묶이고, vway-kit 의 훅은 전부 `.codex/hooks.json` 에
있습니다. 신뢰하지 않은 프로젝트는 그 디렉터리를 **경고 없이** 통째로 무시합니다 — 세션 시작 규칙 주입도,
증거 무효화도, 커밋 게이트도 없습니다.

- Codex TUI 에서 폴더를 신뢰하거나, `config.toml` 의 `[projects]` 밑에 그 경로의
  `trust_level = "trusted"` 를 적습니다.
- `/vdev-init` 은 Codex 가 이 프로젝트를 trusted 로 모르면 그렇다고 알려 줍니다.
- 신뢰와 훅 승인은 별개의 관문입니다 — 아래 승인은 신뢰한 뒤에도 필요합니다.

## 훅 승인

Codex 가 승인하지 않은 훅은 없는 것처럼 동작합니다 — 세션 시작 규칙 주입, 편집마다의 증거 무효화, 커밋
게이트가 전부 **조용히** 빠지고 아무것도 막지 않습니다. `/hooks` 를 열어 `vway-kit` 항목을 승인하세요.

- 승인은 훅의 내용(명령 문자열·이벤트·matcher·플랫폼별 변형)과 파일 안 위치에 묶입니다.
- 그래서 그 훅을 바꾼 `/vdev-init` 재동기화는 재승인이 필요합니다. 무관한 플러그인 변경은 아닙니다.
- `.codex/hooks.json` 의 항목을 옮기거나 순서를 바꿔도 재승인이 필요합니다 — 게이트 앞에 끼워 넣은 내 훅
  하나가 재승인 전까지 게이트를 끕니다.

## `/vdev-init` 으로 훅과 커밋 게이트 켜기

Codex 플러그인은 라이프사이클 훅을 싣지 않습니다 — OpenAI 플러그인 디렉터리가 훅이 든 패키지를 거부합니다.
그래서 `/vdev-init` 을 돌리기 전의 Codex 세션은 스킬만 있고 세션 시작 규칙이 없습니다.

- `/vdev-init` 이 호스트 `.codex/hooks.json` 에 `SessionStart`·`PostToolUse` 훅을 등록합니다. 훅이 돌리는
  스크립트와 `rules/` 는 `.claude/vway-kit/` 아래에 사본으로 둡니다.
- Codex 플러그인이 훅을 직접 싣던 버전으로 셋업한 호스트는 플러그인 업데이트로 그 훅을 잃습니다 —
  `$vdev-init` 을 다시 실행하세요. `$vdev` 는 그 훅이 없으면 작업 전에 멈춥니다.

- **Codex 세션에서 실행** — 묻지 않고 Codex 에도 게이트를 심습니다. Claude Code 에서 처음 설정한 호스트의
  재실행도 같습니다. Codex 에서는 스킬을 `$vdev-init` 으로 부릅니다.
- **Claude Code 에서 실행** — 첫 실행은 `.codex/` 디렉터리가 있거나 Codex 를 언급했을 때 묻습니다. 재실행은
  재설정 메뉴에서 "Codex 게이트" 를 고를 때만 더합니다.

어느 쪽이든 `vdev-config.yaml` 의 `harnesses` 에 `codex` 가 들어가고, 세션 훅이 그 옆에 등록되며, 게이트는
호스트 `.codex/hooks.json` 에 `Bash` `PreToolUse` 훅으로 등록됩니다 — Claude 쪽 `.claude/settings.json` 과는
별개의 등록입니다.

**Windows 는 Git for Windows 도 필요합니다.** 게이트의 Windows wrapper 는 Git 설치 폴더의
`bin\bash.exe` 를 찾고(PATH 의 `git` 이 속한 설치 — scoop shim 이면 scoop 의 Git, 없으면
`%ProgramFiles%\Git`), 없으면 검사 없이 통과시키지
않고 **모든 커밋·머지를 거부**합니다.

- 등록된 명령은 `$(git rev-parse --show-toplevel)` 로 게이트를 찾습니다 — Codex 가 훅을 돌리는 셸이 펼칩니다.
  `$(…)` 를 펼치지 않는 셸(3.4 전 fish, tcsh)에서는 게이트가 전혀 돌지 않습니다.
- Codex 가 열어 두는 셸 세션에 입력한 명령(`write_stdin`)은 `PreToolUse` 를 발화하지 않습니다 — 터미널 커밋처럼
  CI 가 안전망입니다.
- Linux·macOS 의 훅 동작은 Codex 소스에서 읽은 것이고 실측이 아닙니다. Windows 는 실측입니다.

## Recoble MCP 등록

Codex 는 MCP 서버를 Claude 와 다른 곳에, 다른 인증 방식으로 둡니다. `harnesses` 에 `codex` 가 있으면
`/vdev-init` 이 Claude 쪽 판정에 더해 Codex 등록 상태를 `codex mcp list --json` 으로 **읽어** 판정하고, 어긋난
스페이스의 명령만 찍습니다:

```bash
codex mcp remove recoble-labs        # 등록이 어긋났을 때만 먼저
codex mcp add recoble-labs --url https://mcp.recoble.com/s/<uuid>/mcp \
  --bearer-token-env-var RECOBLE_LABS_PAT
```

- **global 스코프** — `codex mcp add` 는 `$CODEX_HOME/config.toml`(기본 `~/.codex`)에 써서 모든 저장소가 같은
  서버를 공유합니다.
- 신뢰한 프로젝트의 `.codex/config.toml` 에 `[mcp_servers]` 가 있으면 Codex 는 그것도 읽고, 같은 이름이면 그쪽이
  global 등록을 가립니다. `codex mcp remove`·`add` 로는 그 항목을 고칠 수 없어, 그 항목이 어긋나면 `/vdev-init` 이
  명령 대신 그 파일의 `[mcp_servers.<이름>]` 을 고치라고 안내합니다.
- **토큰은 셸 환경 변수로** — Codex 는 환경 변수 **이름**만 기록합니다. PAT 는 셸 프로필 등 Codex 를 띄우는
  셸의 환경에 두세요. 세션에 붙여넣지 마세요.
- 변수 이름은 서버 이름에서 나옵니다(`recoble-labs` → `RECOBLE_LABS_PAT`).
- 판정은 transport 종류(`streamable_http`)·url·토큰 변수 지정 여부입니다. 변수의 **값**은 읽지 않습니다 —
  `/vdev-init` 프로세스의 환경은 Codex 세션의 환경과 다릅니다.
- `codex` 가 PATH 에 없거나 목록을 못 읽으면 판정 불가로 보고 전부 안내합니다 — 같은 이름으로 다시
  `add` 하면 거절 없이 덮어씁니다.
- `config.toml` 은 Codex 소유라 vway-kit 은 쓰지 않습니다.

Teamer 는 `teamer_api.py`(keyring, 터미널 CLI) 경로라 Codex 에서도 [그대로](alm.md#teamer)입니다.

## Claude Code 와 다른 점

- **질문**은 구조화된 선택 UI 가 아니라 채팅의 번호 선택지로 옵니다. Plan 모드에서만 `request_user_input` 이
  선택 UI 를 띄웁니다.
- **스킬은 `/name` 이 아니라 `$name` 으로** 부릅니다 — 일상 작업은 `$vdev <작업 설명>`.
- **Teams 알림과 `harness-insight` 는 Claude 전용입니다.** Codex 에는 알림을 보낼 `Notification` 훅 이벤트가
  없고, `harness-insight` 가 집계할 Claude Code 트랜스크립트도 없습니다.
- **프로젝트 지침은 `AGENTS.md` 로 렌더됩니다.** Codex 는 `CLAUDE.md`·`.claude/rules/` 를 직접 읽지 않고, 세션
  디렉터리와 그 조상에서 디렉터리마다 지침 파일 하나만 읽습니다.
  - `/vdev-init`·`/doc-sync`·`/harness-init` 이 루트 `AGENTS.md` 에 관리 블록 하나를 유지합니다 — `CLAUDE.md`·
    `.claude/rules/`·모듈별 `CLAUDE.md` 에서 렌더합니다. 이전 `/vdev-init` 이 남겼을 수 있는 플러그인
    룰 `.claude/rules/vway-kit/` 는 빠집니다 — SessionStart 훅 주입이 이미 그 내용을 실어 줍니다.
  - 원본을 고치고 블록은 고치지 마세요 — 다음 렌더가 덮어씁니다.
  - 렌더된 파일 상한은 Codex 기본값 32 KiB 입니다. 넘치면 규칙 전문 대신 읽을 파일을 가리키는 색인 항목이
    들어가고, 그래도 넘치면 `/vdev-init` 이 경고합니다 — 넘친 부분은 Codex 가 말없이 잘라 냅니다.
  - `AGENTS.override.md` 가 있으면 Codex 는 `AGENTS.md` 를 읽지 않습니다 — `/vdev-init` 이 경고합니다.

## 제거

먼저 [`/vdev-uninstall`](update-and-removal.md#제거--vdev-uninstall) 을 실행하세요. Claude 쪽 정리와 같은 실행에서
`.codex/hooks.json` 의 Codex 세션 훅·게이트와 `AGENTS.md` 의 관리 블록을 지웁니다 — `harnesses` 에 `codex` 가 남아
있든 아니든. `harnesses` 에서 `codex` 만 빼면 아무것도 지워지지 않고, `/vdev-init` 이 남은 것을 보고합니다.

그다음 플러그인을 headless 로 또는 TUI 에서 지웁니다:

```
codex plugin remove vway-kit@vway
codex plugin marketplace remove vway
```

Codex 에 등록한 `recoble-*` MCP 서버는 [갱신·제거](update-and-removal.md#제거--vdev-uninstall)를 보세요.
