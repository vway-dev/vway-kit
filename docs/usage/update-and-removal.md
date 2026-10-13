# 갱신·제거

## 갱신 — `/vdev-init` 재실행

플러그인이 업데이트돼도 호스트의 스크립트 사본은 자동으로 바뀌지 않습니다. `/vdev-init` 을 다시 실행하면:

- 스크립트·정책 파일을 다시 복사하고 게이트 경로를 보정합니다. 이전 판이 남긴 룰 사본
  `.claude/rules/vway-kit/` 는 지웁니다 — 매 세션 통째로 로드되기 때문입니다
  (비대화, 항상 먼저).
- 빠진 config 슬롯이 있으면 보충을 제안하고, 그 외에는 무엇을 재설정할지 묻습니다.
- 설정값·계정·웹훅·내가 고친 양식은 보존합니다.
- Codex 호스트는 세션 훅도 여기서 다시 등록됩니다 — Codex 플러그인이 훅을 싣던 버전으로 셋업한 호스트는
  이 재실행으로 훅을 되찾습니다.
- 옛 `flow` 설치(`flow-config.yaml`·`.flow/`)는 `vdev-config.yaml`·`.vdev/` 로 무손실 이전합니다.

## 제거 — `/vdev-uninstall`

> **`/plugin uninstall` 전에 `/vdev-uninstall` 을 먼저** 실행하세요. 정리 도구가 플러그인 안에 있습니다.

`/plugin uninstall` 은 캐시만 지웁니다. `/vdev-uninstall` 은 확인 후 다음을 합니다.

- `.claude/settings.json` 의 커밋 게이트·마켓 등록 해제 — 내 설정이 하나도 남지 않으면 파일째 지웁니다.
- `.gitignore`·`CLAUDE.md` 관리 블록 제거. 단 `teamer_account.md`·`.teams-webhooks.local.json` 라인은
  남깁니다 — 어느 깊이든 매칭하므로 지운 디렉터리 밖의 비밀도 커밋에서 막고 있을 수 있습니다.
- `.claude/vway-kit/`·`.claude/rules/vway-kit/`(이전 판이 남긴 룰 사본) 삭제(호스트 자신의 룰은 남음). 그 안의
  `templates/` 도 내가 고친 내용째 사라집니다 — 남기려면 먼저 복사해 두세요. 커밋해 둔 것은 git 으로 복구되고
  정리 보고가 사라진 것의 이름을 댑니다.

`.github/workflows/` 는 지우지 않고, 남은 파일을 읽어 셋으로 나눠 이름을 댑니다.

- 지운 스크립트를 가드 없이 불러 **실패**하는 것 — `wiki-verify.yml`, 그리고 `semantic-release` 를 뺀 모든 릴리스
  도구의 `release.yml`(릴리스 브랜치 push 마다).
- 가드가 exit 0 해 아무것도 검증하지 못하는 것 — `doc-style.yml`·`srs-verify.yml`.
- 계속 도는 자기완결 렌더 — `branch-naming.yml`·`entropy-check.yml`·`unit-test.yml`·`api-contract.yml`·
  `e2e.yml`·`deploy*.yml`, `semantic-release` 의 `release.yml`.

`deploy*.yml` 을 지울 때는 `release.yml` 의 deploy 호출 job 도 함께 지웁니다 — 남기면 없는 `deploy.yml` 을 불러
릴리스가 실패합니다. 정리 전이라면 `vdev-config.deploy.enable: false` 로 `/vdev-init` 을 재실행해 그 배선을 지웁니다.

정리 보고는 바꾸거나 지운 파일·디렉터리를 모두 이름 댑니다(`.claude/vway-kit/`·`.claude/rules/vway-kit/`·
`.claude/settings.json`·`.gitignore` 등) — 커밋해야 반영됩니다.

`~/.claude.json` 의 `recoble-*` MCP 서버는 **지우지 않습니다** — 사람이 직접 추가한 서버와 구분할 근거가
없습니다. 정리 스크립트가 찍어 주는 `claude mcp remove <서버키>` 를 직접 실행하세요.

Codex 쪽([Codex](codex.md)):

- `.codex/hooks.json` 의 Codex 세션 훅·게이트와 루트 `AGENTS.md` 의 관리 블록을 같은 실행에서 지웁니다 —
  `harnesses` 에 `codex` 가 남아 있든 아니든. 다른 훅과 블록 밖 내용은 남깁니다.
- Codex 에 등록된 `recoble-*` 서버도 지우지 않고 `codex mcp remove <서버키>` 를 찍어 줍니다. global 스코프라
  다른 저장소도 쓰는 서버입니다. 신뢰한 프로젝트의 `.codex/config.toml` 에도 있는 서버는 그 파일에서 직접
  지우라고 함께 알립니다.
- 그 보고는 `codex` 가 PATH 에 있거나 호스트에 `.codex/` 가 있을 때만 나옵니다 — 같은 호스트라도 실행하는
  머신의 PATH 에 따라 출력이 다릅니다. `codex` 를 못 찾거나 목록을 못 읽으면 "없음" 이 아니라 확인 불가로
  보고하니 `codex mcp list` 로 직접 확인하세요.

끝 줄이 게이트 훅이 남았다고 하면 그 훅은 방금 지운 스크립트를 가리킵니다 — 아래
[수동 정리](#수동-정리-플러그인을-먼저-지웠을-때)대로 직접 지우세요.

- `커밋 게이트 훅이 settings.json 에 남았습니다` — Claude 쪽.
- `Codex 커밋 게이트 훅이 .codex/hooks.json 에 남았습니다` — Codex 쪽.
- `.codex/hooks.json 을 해석하지 못해 Codex 커밋 게이트 훅이 지워졌는지 확인하지 못했습니다` — 파싱되지
  않거나 `hooks.PreToolUse` 가 목록이 아닌데 게이트 표식(`vway-kit` 과 `harness/codex/gate`)이 있는
  파일입니다. 수동 정리대로 직접 확인하세요.
- 표식이 없는 그런 파일은 내 파일로 보고 건드리지 않습니다 —
  `[i] .codex/hooks.json 을 해석하지 못했지만 vway-kit 게이트 표식이 없어 건드리지 않았습니다.` 뒤에
  `정리 완료.` 로 끝납니다.

## 수동 정리 (플러그인을 먼저 지웠을 때)

- `rm -rf .claude/vway-kit/ .claude/rules/vway-kit/` — 남긴 룰 사본은 매 세션 로드되고, 방금 지운 검사기를 가리킵니다.
- 등록 4곳 제거: `settings.json` 게이트 훅·마켓 등록, `.gitignore` 블록, `CLAUDE.md` 블록. `.gitignore` 의
  `teamer_account.md`·`.teams-webhooks.local.json` 은 그런 파일이 저장소에 남아 있는 동안 둡니다.
- Codex 를 켰다면 `.codex/hooks.json` 에서 다음 훅**만** 제거합니다: `command` 에 `vway-kit` 과
  `harness/codex/gate` 가 함께 든 `PreToolUse` 훅, `vway-kit/hooks/inject-risk-tiers.sh` 가 든 `SessionStart` 훅,
  `vway-kit/hooks/invalidate-gate-markers.sh` 가 든 `PostToolUse` 훅. 항목의 `hooks` 목록이 비었고 항목에
  `matcher`·`hooks` 뿐이면 항목도 지웁니다. 그 뒤 `hooks` 가 비고 다른 최상위 키가 없을 때만 파일을 지웁니다.
- 루트 `AGENTS.md` 의 `<!-- vway-kit:codex-instructions BEGIN` ~ `END -->` 블록 제거
- `.github/workflows/wiki-verify.yml` 삭제 — 지운 스크립트를 실행하므로 남기면 push 마다 CI 가 실패합니다.
- `release.yml` 은 `semantic-release` 렌더가 아니면 지운 `release_version.py` 를 불러 릴리스 브랜치 push 마다
  실패합니다 — 지우거나 고치세요.
- `srs-verify.yml`·`doc-style.yml` 삭제 — 초록으로 끝나지만 더는 아무것도 검증하지 않고 러너만 씁니다.
- `e2e.yml` 등 자기완결 렌더는 하네스 스크립트를 부르지 않아 계속 돕니다 — 더 쓰지 않으면 지우세요.
