# Teams 알림

입력을 기다릴 때 또는 원하는 시점에 Teams 채널로 알립니다. 알림 실패는 작업을 막지 않습니다.

## 웹훅 등록

채널마다 Teams **incoming webhook URL**(Power Automate workflow 로 만든 URL — `sig=` 포함)을 발급합니다.
URL 이 빈 채널은 **조용히 건너뛰므로** 개인 채널만 먼저 켜도 됩니다.

개인 채널 URL 은 플러그인 옵션 `teams_webhook_personal` 에 넣는 것을 권합니다. Claude Code 가 플러그인
활성화 때 묻고 OS 보안 저장소에 둡니다. 이 값이 있으면 아래 파일의 `personal` 보다 우선합니다.

| 파일 | 추적 | 채널 |
|------|------|------|
| `.claude/vway-kit/config/.teams-webhooks.local.json` | gitignored | 개인(`personal`), 그리고 기본으로 브랜치 채널의 URL |
| `.claude/vway-kit/config/teams-webhooks.json` | git 추적 | 감시할 브랜치 이름(dev/stage/main 등) — URL 은 `--shared` 로 등록했을 때만 |

```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
# 개인·브랜치 URL 은 기본으로 local 파일에 등록 — 브랜치는 이름만(URL 없이) 추적 파일에도 들어가
# 모든 클론이 그 브랜치를 감시
python3 "${ROOT}/.claude/vway-kit/scripts/teams_alert.py" --set personal https://...
python3 "${ROOT}/.claude/vway-kit/scripts/teams_alert.py" --set dev https://...
# 브랜치 URL 자체를 팀 전체용으로 추적 파일에 커밋
python3 "${ROOT}/.claude/vway-kit/scripts/teams_alert.py" --set dev https://... --shared
# 수동 알림
python3 "${ROOT}/.claude/vway-kit/scripts/teams_alert.py" --channel personal --title "..." --text "..."
```

## 발화 시점

- **자동** — 권한·idle·입력 요청 대기 시 `personal` 채널(Notification 훅). Codex 에는 Notification 훅
  이벤트가 없어 자동 알림이 없습니다([Codex](codex.md#claude-code-와-다른-점)).
- **수동** — `AskUserQuestion` 은 자동 알림을 띄우지 않으므로, 입력을 기다리기 직전 위 명령으로 알립니다.
  Teams 채널을 설정하면 `/vdev-init` 이 호스트 `CLAUDE.md` 에 이 안내 블록을 넣습니다.
- **브랜치 push** — pre-push 훅 `teams-notify-push` 가 push 한 브랜치 이름이 두 파일 중 어느 쪽의 키와
  같으면 그 커밋 제목을 알립니다. `pre-commit install --hook-type pre-push` 가 필요합니다. 알림은 그 브랜치의
  URL 을 쥔 클론에서만 나갑니다.

## 보안

Power Automate URL 의 `sig=` 토큰이 그 채널에 글을 올리는 자격증명입니다. 기본으로 gitignored local 파일에
남으므로 공개되는 것은 브랜치 이름뿐입니다. 팀 전체가 그 채널로 알리기를 원할 때만 `--shared` 로 등록하세요 —
그러면 저장소를 읽는 누구나 그 채널에 글을 올릴 수 있습니다(메시지 주입뿐, 데이터 유출·권한 상승은 없음).
그렇게 했다면 시크릿 스캐너 예외로 표시하세요.
