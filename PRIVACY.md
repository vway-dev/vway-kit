# 개인정보 처리방침

vway-kit 은 사용자 컴퓨터에서 도는 Claude Code·Codex 플러그인입니다.

- 배포자(vway)는 이 플러그인을 위한 서버를 운영하지 않습니다.
- 플러그인은 사용 통계·텔레메트리·기기 식별자를 수집하거나 보내지 않습니다.
- 플러그인이 데이터를 보내는 곳은 사용자가 직접 설정한 아래 세 서비스뿐이고, 설정하지 않으면 아무것도
  보내지 않습니다. 보낸 뒤의 처리는 각 서비스의 방침을 따릅니다.

## 외부로 보내는 데이터

| 대상 | 켜지는 조건 | 보내는 데이터 | 자격증명 보관 위치 |
|---|---|---|---|
| Microsoft Teams(Power Automate 웹훅) | 웹훅 URL 을 등록했을 때 | 알림 제목·본문, `프로젝트 폴더 이름 @ git 브랜치` 라벨, push 알림이면 그 커밋의 제목 | 개인 채널: gitignored `.claude/vway-kit/config/.teams-webhooks.local.json`. 브랜치 채널: 같은 local 파일, `--shared` 로 등록한 URL 만 git 추적 파일 `teams-webhooks.json` |
| Teamer(`https://teamer.live`) | `vdev-config.yaml` 에 Teamer 를 설정하고 `teamer_api.py setup` 을 실행했을 때 | 로그인 id·비밀번호(인증 요청), 항목 검색어·번호, 작업 요약·상태(항목 수정) | OS keyring 서비스 `vway-kit-teamer` |
| Recoble | 사용자가 `claude mcp add` 로 Recoble MCP 서버를 등록했을 때 | 모델이 MCP 도구로 읽고 쓰는 항목 — 작업 항목 내용, 작업 요약·상태, `docs/srs` 요구사항 텍스트, 항목 간 링크 | 사용자의 `~/.claude.json`(local 스코프). vway-kit 은 서버를 등록하지 않고 PAT 값을 출력하지 않음 |

- Teams·Teamer 호출은 플러그인 스크립트(`scripts/teams_alert.py`, `scripts/teamer_api.py`)가 하고, Recoble 호출은
  세션의 모델이 사용자가 등록한 MCP 서버로 함.
- Teamer 오류 메시지는 출력 전에 id·비밀번호를 `***` 로 가림.
- Teams 알림 실패와 ALM 실패는 커밋을 막지 않음 — 해당 단계만 건너뜀.

## 모델 제공자에게 가는 데이터

세션의 모델이 읽는 것은 사용 중인 Claude Code 또는 Codex 의 모델 제공자에게 전달됩니다. 그 처리는 사용자와
그 제공자 사이의 약관을 따르고, vway-kit 은 그 경로에 다른 수신자를 더하지 않습니다. vway-kit 때문에 모델이
읽게 되는 것은 다음과 같습니다.

- 세션 시작 때 훅이 주입하는 규칙(`rules/risk-tiers.md` 전문, `rules/doc-style.md` 요약)
- 스킬 문서와 스킬이 여는 저장소 파일
- 연결된 ALM 항목의 내용
- `/harness-insight` 를 요청했을 때 현재 프로젝트 트랜스크립트에서 뽑은 프롬프트·도구 사용 집계

## 로컬에서만 읽는 데이터

- **`~/.claude.json`** — `/vdev-init` 이 Recoble MCP 등록 상태를 판정함. `Authorization` 헤더는 있는지만 보고,
  안내하는 명령에는 `<PAT>` 자리표시만 씀.
- **세션 트랜스크립트**(`~/.claude/projects/<프로젝트>/*.jsonl`, Codex 는 `~/.codex/sessions`)
  - `scripts/worklog.py` 가 AI Agent 활동 시간을 계산함. 밖으로 나가는 것은 계산된 시각·시간뿐이고,
    `/task-sync` 가 ALM 요약에 적음.
  - `scripts/harness_insight.py` 는 `/harness-insight` 요청 때만 돌고, 집계를 임시 파일로 냄 — 모델이 읽고
    보고서를 만든 뒤 지움.
- **git 상태** — 브랜치 이름·커밋 메시지·변경 파일. 커밋 게이트의 판정에만 씀.

## 로컬에 쓰는 데이터

- **`.claude/vway-kit/.vdev/`**(gitignored) — 게이트 증거 마커, ALM 링크 마커 `alm`, 권한 승인 대기 시각과
  세션 id(`waits`).
- **`.claude/vway-kit/config/`** — 저장소 설정과 Teams 웹훅 파일.
- **OS keyring `vway-kit-teamer`** — Teamer id·비밀번호. `teamer_account.md` 평문 파일이 있으면 keyring 으로
  옮긴 뒤 그 파일을 지움.

## 삭제

- **저장소의 vway-kit 파일** — `/vdev-uninstall` 이 `.claude/vway-kit/`(설정·웹훅·증거)를 지웁니다. 그 뒤
  `/plugin uninstall vway-kit` 이 플러그인 캐시를 지웁니다.
- **Teamer 자격증명** — 파일 삭제로 지워지지 않으므로 keyring 에서 지웁니다.

  ```bash
  python3 -m keyring del vway-kit-teamer id
  python3 -m keyring del vway-kit-teamer password
  ```
- **Recoble MCP 서버** — `claude mcp remove <서버 이름>` 으로 지웁니다.
- **이미 보낸 데이터** — Teams·Teamer·Recoble 에 게시된 내용은 각 서비스에서 지웁니다.

## 문의

[GitHub Issues](https://github.com/vway-dev/vway-kit/issues) 로 문의합니다.
