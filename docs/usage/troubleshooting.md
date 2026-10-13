# 문제 해결

## 커밋이 막혀요 — "python3 / PyYAML 필요"

게이트는 `python3`(3.8+)와 `PyYAML` 이 없으면 **일부러** 막습니다(검사가 조용히 빠지는 것 방지).

`python3 가 Microsoft Store 별칭이라 python 이 실행되지 않습니다` 는 Windows 전용입니다 — Store 의 앱 실행
별칭은 `command -v python3` 에 답하지만 인터프리터를 돌리지 않습니다. python.org 나
`Python.Python.3.x` 설치는 `python` 만 만들고 `python3` 를 그 별칭에 남깁니다. Python install manager
(`winget install 9NQ7512CXL7T` 후 `py install 3.12`)를 설치하거나, Windows 설정의 '앱 실행 별칭 관리'에서
별칭을 끄고 진짜 `python3` 를 `PATH` 에 두세요.

```bash
python3 -m pip install pyyaml                 # 훅이 부르는 python3 에 설치(uv add 는 가상환경에만 들어감)
bash .claude/vway-kit/scripts/check-deps.sh   # 무엇이 빠졌는지 점검
```

## 커밋이 막혀요 — 미분류

`/vdev` 를 거치지 않아 등급 마커가 없습니다. `/vdev` 로 분류하면 풀립니다. `/commit` 단독 호출도 분류는
하지 않습니다.

## Dev 작업인데 절차가 안 돌아요

`superpowers@claude-plugins-official` 플러그인이 필요합니다. 수동 구현으로 건너뛰지 마세요.

## `git commit` 을 언급만 했는데 차단돼요

게이트는 셸이 읽는 대로 읽고 **진짜 `git … commit` 호출이 있는가**만 묻습니다. 따옴표 안·주석·heredoc
본문의 언급과 `git commit-graph`·`git merge-base` 같은 비슷한 이름은 걸리지 않습니다.

**일부러** 걸리는 형태는 하나입니다 — 커밋처럼 생긴 텍스트를 그것을 **실행할 수 있는** 프로그램에 건네는
경우(`bash -c …`·`xargs …`·`ssh …`·`gh pr create --body …`). 면제 기준은 그 프로그램이 자기 인자에 적힌
명령도, 자기 환경이 지목하는 명령도 돌릴 방법이 없는가입니다.

- 면제: `grep`·`rg`·`cat`·`head`·`tail`·`wc`·`sort`·`printf`·`echo` 등
- 비면제: `awk`(`system`)·`sed`(GNU `e`)·`find`(`-exec`)·`xargs`·`ssh`,
  그리고 `LESSOPEN` 을 따르는 `less`·`more`
- 같은 명령 안의 `$( … )`·백틱, 읽기 전용 명령 **앞의** 대입(`LC_ALL=C grep …`)·리다이렉션(`2>/dev/null grep …`)은
  면제를 취소합니다. 명령 **뒤** 리다이렉션은 괜찮습니다.
- `git grep "git commit"` 은 돌지만, 같은 파이프라인 단계에
  `-c`·`--exec`·`submodule foreach`·`bisect run` 류가 서면 취소됩니다.

푸는 법:

- **부분을 나누세요** — `;`·`&&`·`||`·개행으로 나뉜 부분은 따로 읽힙니다. 파이프와 `$( … )` 안의 구분자는
  나누지 않습니다.
- **본문을 heredoc 으로** 넘기세요:
  ```bash
  gh pr create --body-file - <<'EOF'
  git commit 을 설명하는 본문
  EOF
  ```

그 밖에 막히면 호스트 게이트 사본이 옛 버전입니다 — `/vdev-init` 재실행.

## `git merge` 가 차단돼요

flow 별 머지 전략(rebase / squash / `--no-ff`)을 어겼습니다. 브랜치를 대는 `git pull` 도 같은
판정을 받습니다 — rebase 하면 머지 커밋이 없으므로 플래그 없음으로 읽습니다. 차단 메시지가 필요한
플래그를 알려 주고, 표는 [`merge-strategy`](../../rules/merge-strategy.md) 입니다. 차단은 플래그 형태에만
걸리고 rebase 선행 여부는 경고입니다(`[경고] 머지 전략: … rebase 선행이 요구됩니다` — feature 브랜치를
먼저 rebase 하거나, `origin` 참조가 낡았다면 무시). 내부 오류로 판정을 마치지 못한 머지도 같은 방식으로
알립니다(`merge 전략 판정 실패 — 판정 없이 통과`). `git -C <wt> merge …`·선행 `cd <wt> && …` 처럼 **다른** 저장소를
지정한 머지는 검사하지 않습니다(fail-open) — 강제받으려면 그 worktree 안에서 세션을 여세요. 같은
저장소의 하위 디렉터리(`cd sub && …`·`git -C sub …`)는 사이에 다른 `.git`(중첩 저장소·worktree)이
없으면 검사를 비켜 가지 못합니다(같은 명령이 새로 만든 디렉터리는 예외).

## Codex 에서

위 메시지는 공용입니다 — Codex wrapper 가 같은 스크립트를 돌리고, 이름만 Codex 식으로 바꿔(`/vdev…` →
`$vdev…`, `settings.json 의 게이트 훅` → `.codex/hooks.json 의 게이트 훅`) 종료 코드 대신 deny JSON 으로
냅니다. 다른 점 셋:

- **승인 안 된 훅은 발화하지 않습니다.** 규칙 주입·마커 무효화·커밋 게이트가 `/hooks` 에서 승인하기 전까지
  조용히 빠집니다([훅 승인](codex.md#훅-승인)).
- **신뢰하지 않은 프로젝트는 모든 훅을 조용히 잃습니다.** `.codex/hooks.json` 이 통째로 무시되어 세션 시작 규칙
  주입·마커 무효화·커밋 게이트가 모두 없습니다([프로젝트 신뢰](codex.md#프로젝트-신뢰)). 신뢰한 프로젝트인데 세션에
  규칙이 없으면, Codex 플러그인이 훅을 싣지 않게 된 뒤로 `$vdev-init` 을 다시 돌리지 않은 것입니다
  ([`/vdev-init`](codex.md#vdev-init-으로-훅과-커밋-게이트-켜기)).
- **Git Bash 없는 Windows 는 건너뛰지 않고 막힙니다.** 게이트의 Windows wrapper 가 Git 동봉 `bash.exe` 를 못
  찾으면 모든 커밋·머지를 거부합니다 — Git for Windows 를 설치하세요.

## 새 PC에서 `marketplace add` 가 실패해요

[시작하기 1단계](getting-started.md#1-저장소-접근-준비-ssh) 누락입니다.

- **`Host key verification failed` / `No ED25519 host key is known`** —
  터미널에서 `ssh -T git@github.com` 으로 fingerprint 확인 후 `yes`.
- **`Permission denied (publickey)`** — 이 PC 의 SSH 키가 GitHub 계정에 없거나, 계정에 저장소 권한이 없습니다.
- **HTTPS 로 새는 경우** — 전역 `insteadOf` 가 github.com 을 HTTPS 로 치환하고 있습니다. 치환을 풀거나 토큰 경로를 쓰세요.

`git config user.name` 은 SSH 접근과 무관합니다 — SSH 는 그 PC 의 `known_hosts` + 키 쌍을 봅니다.

## 자동 업데이트가 안 돼요

[자동 업데이트 설정](getting-started.md#4-자동-업데이트-설정-비공개-저장소)의 확인 명령으로 점검하세요.
급하면 `/plugin marketplace update vway`.

## 릴리스 CI 가 실패해요 — 쓰기 권한

프리플라이트나 커밋·태그 push 단계에서 멈추면 토큰에 쓰기 권한이 없습니다. 로그 끝
`릴리스 CI 쓰기 권한 안내` 대로
[RELEASE_TOKEN](promotion-and-release.md#릴리스-ci-토큰-release_token)의 [A] 또는 [B] 를 설정하세요.

## 플러그인 저장소가 옮겨졌어요 (기존 설치자)

설치 시점의 마켓 source 는 자동으로 안 바뀌고 `/vdev-init` 도 보존하므로, 자동 업데이트가 옛 경로를 향해
조용히 건너뜁니다. 둘 중 하나:

1. `extraKnownMarketplaces` 가 있는 `settings.json`(프로젝트 `.claude/settings.json` 먼저, 없으면
   `~/.claude/settings.json`)에서 `vway.source.repo` 를 새 경로로:
   ```json
   "vway": { "source": { "source": "github", "repo": "vway-dev/vway-kit" }, "autoUpdate": true }
   ```
2. `/plugin marketplace remove vway` → `/plugin marketplace add <새 경로>`

이후 토큰 권한·`insteadOf` 예외도 새 경로로 맞추고 호스트를 완전히 재시작하세요.

## 인수인계 요약이 3섹션 구조를 잃었어요

`handoff.*.template` 에 없는 파일(예: `handoff/summary.html`)을 명시하면 오류 없이 일반 요약으로 내려갑니다.
그 줄을 지우거나 `handoff/summary.md` 로 고치세요. 저장소 루트 `templates/` 에 둔 양식은 `/vdev-init` 을 다시
돌려 `.claude/vway-kit/templates/` 로 옮겨야 쓰입니다.
