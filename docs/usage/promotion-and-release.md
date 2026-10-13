# 승격과 릴리스

## `/release-commit`

integration→staging(Staging), staging→production(Release) 승격의 절차는
[`release-commit` 스킬](../../skills/release-commit/SKILL.md)이 가집니다. 요지:

1. **릴리스 모델부터 읽음** — 렌더된 `release.yml` 의 `# vway-release-levels:` 선언이 staging 에서
   고를 수 있는 레벨입니다. 레벨은 staging 머지 커밋 본문 끝의 `Release-Level: <level>` 트레일러로
   CI 에 전달되고, push 한 번이 rc 를 냅니다. 레벨을 `workflow_dispatch` 로 받는 옛 `release.yml` 은
   `/vdev-init` 재실행이 재렌더를 안내하고, 그 전까지 `/release-commit` 은 멈춥니다.
2. **게이트 마커** — Staging 은 `review`·`bump`, Release 는 `security` 를 남겨야 커밋이 통과합니다.
   `bump` 은 사람이 고르는 레벨이고, 고르기 전까지 staging 커밋이 막힙니다.
3. **재승격** — rc 가 대기 중이면 staging 을 integration 으로 먼저 백머지하고 레벨을 다시 고릅니다.
   `v1.1.0-rc.2` 에서 `continue` → `v1.1.0-rc.3`, `patch` → `v1.1.1-rc.1`, `minor` → `v1.2.0-rc.1`.
4. **머지 먼저, 커밋 나중** — 릴리스 CI 는 push 의 맨 위 커밋만 읽으므로 트레일러는 그 머지 커밋에
   실려야 합니다.
5. **hotfix** — `hotfix/*` → production 은 도달 가능한 rc 가 없으므로 트레일러 레벨로, 없으면 patch
   (커밋 타입 파생 도구는 auto)로 정식이 바로 나갑니다(`/release-commit hotfix`). hotfix 가 대기 rc 의
   버전을 먼저 냈거나 넘어섰으면 그 rc 는 자기 버전으로 못 나갑니다(도구에 따라 릴리스 런이 실패하거나
   마지막 정식 + patch 가 나감 — 룰 [`promotion`](../../rules/promotion.md)). 다음 staging 승격은
   patch 이상을 고릅니다.
6. **정식 릴리스 노트** — Release 에서 이번 릴리스가 접어 넣는 rc 들을 한 절로 요약해 사용자 승인 뒤
   `CHANGELOG.md` 에 `## vX.Y.Z` 로 쓰고 승격 머지에 실습니다. 릴리스 워크플로가 그 절을 GitHub
   Release 본문으로 올립니다(절이 없으면 도구가 만든 본문 유지).
7. **백머지로 닫음** — Release·hotfix 뒤 production→integration→staging 순서(staging 쪽은 fast-forward
   전용).

승격 규율의 SSOT 는 룰 [`promotion`](../../rules/promotion.md), 머지 형태는
[`merge-strategy`](../../rules/merge-strategy.md).

## 릴리스 CI 토큰 (RELEASE_TOKEN)

`vdev-config.versioning` 으로 렌더한 `release.yml` 은 커밋·태그 push 와 릴리스 생성에 저장소
**쓰기 권한**이 필요합니다. 자동 렌더 지원 도구: `python-semantic-release`·`semantic-release`(Node)·
`jreleaser`(Java)·`gitversion`(C#)·`cargo-release`(Rust)·`sbt-ci-release`(Scala). 그 외 스택은 AI 가
감지해 직접 작성합니다. 릴리스는 **버전·태그·GitHub Release 만** 만들고, 발행은
[배포](ci-workflows.md#배포--deploy)가 맡습니다.

저장소마다 **[A] 또는 [B] 하나**를 관리자가 한 번 설정합니다. [자동 업데이트 토큰](getting-started.md#4-자동-업데이트-설정-비공개-저장소)
(Contents: Read-only)과는 **별개**입니다.

**[A] 저장소 전용 PAT 시크릿 `RELEASE_TOKEN`** (권장 — 세분화된 권한)

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token.
   Resource owner = 저장소 소유자, Repository access = *Only select repositories* → 이 저장소,
   Repository permissions → **Contents: Read and write**.
2. 저장소 → Settings → Secrets and variables → Actions → New repository secret →
   Name `RELEASE_TOKEN`, Secret = 토큰 값.

**[B] 내장 `GITHUB_TOKEN` 에 쓰기 허용** (간편 — 시크릿 불필요)

`RELEASE_TOKEN` 이 없으면 워크플로가 내장 `GITHUB_TOKEN` 으로 폴백합니다. 저장소 → Settings →
Actions → General → Workflow permissions 에서 **Read and write permissions** 를 켭니다. 권한이
저장소 전역이라 세분화 통제가 필요하면 [A] 를 쓰세요.

워크플로는 시작 시 쓰기 권한을 프리플라이트로 검증하고, 없거나 커밋·push 가 실패하면 로그 끝에
`릴리스 CI 쓰기 권한 안내` 를 출력합니다.

워크플로가 직접 하는 릴리스 push 는 일시적 실패에 최대 3회 재시도하고 rebase 는 하지 않습니다.
릴리스 커밋을 올리는 곳에서는 커밋과 태그가 한 번의 atomic push 로 올라가, 실패한 릴리스는 둘 다
원격에 남기지 않습니다.

### 옛 릴리스 템플릿에서 옮길 때

옛 템플릿은 발행까지 했지만(`cargo-release` → crates.io, `sbt-ci-release` → Maven Central) 새 템플릿은
하지 않습니다. `deploy` 없이 `release.yml` 을 재렌더하면 워크플로는 초록인데 **발행이 조용히 멈춥니다.**

1. `vdev-config.yaml` 의 `deploy` 블록에 발행 타깃을 채웁니다.
2. `.github/workflows/release.yml` 을 지우고 `/vdev-init` 재실행(커스텀이 있으면 직접 병합).

`/vdev-init` 이 `[릴리스 워크플로 마이그레이션]` 으로 갱신 필요를 알립니다.
