# 시작하기

## 1. 저장소 접근 준비 (SSH)

vway-kit 은 비공개 조직 저장소입니다. 먼저 조직 관리자에게 **멤버 초대 + 저장소 Read 권한**을
요청하세요(권한이 없으면 키를 등록해도 거부됩니다). 새 PC 라면:

1. SSH 키 생성(없을 때) — `ssh-keygen -t ed25519 -C "you@example.com"`
2. 공개키(`~/.ssh/id_ed25519.pub`)를 GitHub → Settings → SSH and GPG keys 에 등록
3. 터미널에서 `ssh -T git@github.com` → fingerprint
   (`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`) 확인 후 `yes`.
   `Hi <아이디>! You've successfully authenticated` 가 나오면 정상입니다.

Claude Code 의 `marketplace add` 는 비대화형이라 호스트 키 프롬프트를 띄우지 못합니다 — 3번을
**미리** 해야 합니다. 실패 증상별 해결은 [문제 해결](troubleshooting.md#새-pc에서-marketplace-add-가-실패해요).

## 2. 설치 순서

1. **플러그인 추가**
   ```
   /plugin marketplace add git@github.com:vway-dev/vway-kit.git
   /plugin install vway-kit@vway
   ```
2. **`/harness-init`** — `CLAUDE.md`·규칙·기술 문서 생성([프로젝트 하네스](project-harness.md)).
   아무것도 없는 새 프로젝트는 여기서 시작합니다. `CLAUDE.md` 가 갖춰진 저장소는 건너뜁니다.
3. **준비물(쓸 때만)**
   - Teamer — 터미널에서 `python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" setup` 1회
     ([ALM 연동](alm.md#teamer))
   - Teams — 채널별 웹훅 URL([Teams 알림](teams.md)). 이 시점엔 `config/` 가 없으므로 프로젝트
     루트에 두면 다음 단계가 옮깁니다.
   - Recoble — 준비물 없음. workboard 만 Recoble 웹에서 **미리 만들어 두세요**.
4. **`/vdev-init`** — 대화형 마법사. 여러 번 실행해도 안전합니다.
   - 루트 준비물을 `.claude/vway-kit/config/` 로 이전
   - `vdev-config.yaml` 생성, Recoble 스페이스 수집 + MCP 등록 명령 출력([ALM 연동](alm.md#recoble))
   - 커밋 게이트 등록, pre-commit 훅 점검·생성
   - 자동 업데이트 등록, Teams·ALM 배선
5. **마무리**
   - `uv run pre-commit install --hook-type commit-msg --hook-type pre-push`
   - `pre-commit-hooks.example.yaml` 의 언어별 검사 도구(ruff/bandit 등)를 팀 스택에 맞게 교체

이후 `/vdev <작업 설명>` 으로 시작합니다([일상 작업](daily-work.md)).

## 3. 호스트에 생기는 것

대부분 **`.claude/vway-kit/`** 한곳에 모입니다.

| 경로 | 내용 | 소유 |
|------|------|------|
| `config/` | `vdev-config.yaml`·웹훅 설정 · `vdev-tiers.yaml` | 호스트 · 플러그인(`vdev-tiers.yaml` 만) |
| `scripts/` | 게이트·도구 스크립트 사본 | 플러그인 — 재실행 때마다 덮어씀 |
| `templates/` | 내가 고치는 ALM·handoff 양식 | 호스트 |
| `.vdev/` | 게이트 진행 증거(gitignored) | 작업마다 생성·삭제 |

`scripts/` 는 커밋해 두세요. 체크아웃에 스크립트가 없으면 `doc-style.yml`·`srs-verify.yml` 은 건너뛰어
아무것도 검증하지 않고, `wiki-verify.yml` 과 `semantic-release` 를 뺀 모든 릴리스 도구의 `release.yml` 은
가드 없이 불러 실패합니다.

예외는 위치가 정해진 외부 도구 파일뿐입니다 — `.gitignore`·`.pre-commit-config.yaml`·
`.claude/settings.json`·`.github/workflows/`, Codex 를 켰다면 `.codex/hooks.json`·루트 `AGENTS.md`
([Codex](codex.md)).

`/vdev-init` 은 저장소 밖을 가리키는 심볼릭 링크를 통해 쓰지 않습니다. dotfiles 디렉터리로
연결된 `.claude/settings.json` 은 거부되어 게이트가 등록되지 않습니다 — 일반 파일로 두거나 저장소
안의 파일로 연결하세요. 편집하는 `.gitignore`·`CLAUDE.md`·`release.yml` 은 원래 줄끝(CRLF·LF)을
지킵니다.

git 최상위 아래 하위 디렉터리에서 연 세션으로 `/vdev-init` 을 돌리면 `.github/workflows/`·
`.pre-commit-config.yaml` 이 그 하위 디렉터리에 생깁니다 — GitHub·pre-commit 은 최상위에서만 찾으므로 둘 다
돌지 않습니다. 셋업이 최상위 경로를 적은 경고를 찍으니, 최상위에서 세션을 열고 `/vdev-init` 을 다시
실행하세요.

## 4. 자동 업데이트 설정 (비공개 저장소)

설정하지 않으면 새 버전이 나와도 자동 갱신이 **에러 없이 건너뛰어집니다**. SSH 와는 별개입니다.

1. **토큰(PAT) 발급** — GitHub → Settings → Developer settings → **Fine-grained tokens** →
   Generate new token. **Repository access** = *Only select repositories* → 이 저장소,
   **Permissions** = **Contents: Read-only** 만. 조직이 "Require administrator approval" 을 켰다면
   관리자가 조직 → Settings → Personal access tokens → Pending requests 에서 승인해야 동작합니다.
2. **환경변수 등록** — 셸 프로필 등 영구 위치에:
   ```bash
   export GITHUB_TOKEN=github_pat_xxxxxxxx
   ```
3. **git 자격증명 헬퍼 등록** — git 은 `GITHUB_TOKEN` 을 직접 읽지 않습니다:
   ```bash
   git config --global credential.https://github.com.helper ""
   git config --global --add credential.https://github.com.helper \
     '!f() { test "$1" = get && echo username=x-access-token && echo "password=$GITHUB_TOKEN"; }; f'
   ```
4. **SSH 치환 예외(해당될 때만)** — 전역 `insteadOf` 로 github.com 을 SSH 로 받고 있다면 이
   저장소만 HTTPS 로 되돌립니다:
   ```bash
   git config --global url."https://github.com/vway-dev/vway-kit".insteadOf "https://github.com/vway-dev/vway-kit"
   ```
5. **호스트 완전 재시작** — 토큰은 프로그램이 켜질 때 읽힙니다. VS Code 는 모든 창을 닫고 다시 여세요.

확인 — 아래가 `exit 0` 이면 동작합니다:

```bash
GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND=false git ls-remote https://github.com/vway-dev/vway-kit.git HEAD
```

실패는 거의 항상 3번 헬퍼 누락 또는 4번 치환 충돌입니다. 수동 갱신(`/plugin marketplace update vway`)은
대화형이라 이 둘을 우회하므로 "수동은 되는데 자동은 안 되는" 증상도 같은 원인입니다. 원리·정밀
진단은 [marketplace-auto-update.md](https://github.com/vway-dev/vway-kit/blob/main/docs/plugins/marketplace-auto-update.md).
