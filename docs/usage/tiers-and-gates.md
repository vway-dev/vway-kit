# 등급과 게이트

작업 등급이 **어떤 검증을 통과해야 커밋되는지**를 정합니다. 분류 기준의 SSOT 는 매 세션 주입되는
룰 [`risk-tiers`](../../rules/risk-tiers.md),
등급 → 게이트 목록은 [`vdev-tiers.yaml`](../../vdev-tiers.yaml).

| 등급 | 언제 | 필수 게이트 |
|------|------|------------|
| `docs` | 코드 없는 변경(문서·주석·설정값) | doc-sync · wiki · doc-style |
| `dev` | 코드 포함 변경(feature/fix) | 정적 분석 · 도메인 리뷰 · doc-sync · wiki · doc-style |
| `staging` | QA/RC 승격(integration→staging) | 정적 분석 · 도메인 리뷰 · 버전 레벨(bump) · 전체 모듈 보안 스캔 · wiki · doc-style |
| `release` | 프로덕션 배포(staging→production) | 정적 분석 · 전체 모듈 보안 스캔 · 보안 리뷰 · wiki · doc-style |

Release 에 도메인 리뷰가 없는 것은 그 diff 가 Dev·Staging 에서 이미 읽혔기 때문입니다.
Docs·Dev 는 `/vdev` 가 분류하고, 승격은 **타깃 브랜치**가 등급을 정합니다.

## 게이트별 동작

- **정적 분석·전체 모듈 보안 스캔** — 각각 `precommit`·`security-scan` 타이밍 버킷입니다. 커밋 훅이
  [`modules[].checks`](configuration.md#예시) 중 타이밍이 맞는 것을 직접 실행합니다
  (`every-commit` = 변경 모듈, `promotion` = 전체 모듈). 커스텀 검사는 `when:` 으로 버킷을 고릅니다.
- **wiki** — `wiki` 설정이 켜졌을 때만, 게이트 프로세스 안에서 읽기 전용으로 돕니다.
  `docs/graph/graph.yaml` 을 문서 front matter 와 대조하고, 본문 편집 없이 `sources` sha 만 바꾼
  커밋도 막습니다. 훅은 스테이징 **전에** 워킹트리를 읽으므로 `graph.yaml` 은 그것을 만든 문서와
  **함께** 스테이징하세요. 그래프 품질 경고는 커밋이 통과해도 `systemMessage` 로 옵니다.
- **doc-style** — `doc_style` 설정이 켜졌을 때만 돕니다. 이 커밋이 바꾸는 파일의 산문을
  [문체 규율](daily-work.md#문체-규율)에 대고 **경고만** 합니다. 판정은 트리 전체를 보는
  `doc-style.yml` CI 가 합니다.
- **review·doc-sync** — `/vdev` 가 통과시킨 뒤 증거 마커를 남기고, 커밋 훅은 마커가 있어야
  통과시킵니다. 승격의 `review`·`bump`·`security` 는 `/release-commit` 이 남깁니다.

세부 동작(fail-open 조건, 경고 종류)의 SSOT 는 룰 [`gate-mechanics`](../../rules/gate-mechanics.md).

## 증거 마커 무효화

`review`·`doc-sync` 는 워킹트리를 판정하므로, 편집이 일어나면 PostToolUse 훅이 **두 마커를 모두**
지웁니다 — 리뷰가 요구한 수정도 포함입니다. 그래서 수정이 생기면 doc-sync → 도메인 리뷰를 다시
밟습니다. 훅이 못 보는 편집(터미널 명령, 다른 도구)은 손으로 지웁니다:

```bash
rm -f .claude/vway-kit/.vdev/review.done .claude/vway-kit/.vdev/doc-sync.done
```

`gate_evidence.invalidate_on_edit: false` 로 끌 수 있으나, 대가는 통과 뒤의 수정이 리뷰 없이
커밋되는 것입니다([gate-mechanics](../../rules/gate-mechanics.md#증거-무효화-스위치)).
`bump`·`security` 는 깨끗한 트리에서 내리는 승격 결정이라 대상이 아닙니다.

## 머지 전략

`git merge` 와, 브랜치를 대는 `git pull` 도 게이트가 검사합니다 — 브랜치 flow 별 필수·금지
플래그(`--squash`·`--no-ff` 등)를 어기면 차단됩니다.
플래그는 `git merge`·`git pull` 줄에 리터럴로 적습니다 — 게이트가 git 이 읽는 그대로 읽습니다.
rebase 하는 pull 도 그 브랜치를 들이므로 판정하고, 머지 커밋이 없으니 머지 플래그가 없는 것으로
읽습니다. 판정을 마치지 못했거나 rebase 선행이 안 보이는 통과는 알림으로 보입니다.
전략표와 자동 검사 행, 머지가 떨어지는 트리는 룰 [`merge-strategy`](../../rules/merge-strategy.md),
판정에서 빠지는 경우는 [gate-mechanics](../../rules/gate-mechanics.md#merge-전략-판정의-fail-open).
전략은 `vdev-tiers.yaml` 소속이라 호스트에서 조정하지 않습니다.

## 강제 범위

게이트는 **에이전트 세션(Claude Code·Codex)의 `git commit`·`git merge`**(브랜치를 대는 `git pull` 포함)
**에만** 걸립니다(PreToolUse). 터미널에서 직접 한 커밋은 [CI 워크플로](ci-workflows.md)가 덮습니다.
명령은 적힌 그대로 읽습니다 — git 별칭(`git ci`, `git -c alias.ci=commit ci`)이나 확장으로 만든
서브커맨드(`git $(echo commit)`, `$g commit`)는 커밋으로 읽지 않고, 커밋을 만드는 다른 명령
(`cherry-pick`·`revert`·`am`·`rebase`·`commit-tree`)도 게이트에 걸리지 않습니다. worktree 의
커밋은 그 worktree 자신의 `.claude/vway-kit/` 로 판정하므로, `/vdev-init` 셋업 커밋 전에 딴
worktree 는 정책이 없어 그 커밋을 받기(머지·rebase) 전까지 게이트 없이 통과합니다. 다른 저장소를
대놓고 지목하는 명령 하나 — `git -C <dir> commit` 또는 `cd <dir> && git commit`, 그 디렉터리의
`--git-common-dir` 가 이 저장소와 다름으로 증명됨 — 는 이 저장소의 커밋으로 읽지 않습니다. 다음
경우는 증명이 안 되어 게이팅됩니다.

- 두 번째 명령(개행으로 이어진 것 포함)
- 확장으로 닿는 디렉터리(`$VAR`·`~`·glob·brace)나 `-` 로 시작하는 디렉터리
- 겹친 `-C`, 커밋을 이리 되돌릴 수 있는 `--git-dir`·`GIT_DIR`
- `..` 구간을 가진 `cd` 디렉터리 — bash 는 논리적으로, 판정은 물리적으로 경로를 풂
- Windows 에서 `cd` 형태 전부와, `C:/…` 나 평범한 상대 경로가 아닌 `-C` 디렉터리 — Git Bash 는
  경로를 판정이 읽지 않는 MSYS 마운트 표로 옮김

강제가 필요 없는 저장소는 `/vdev-uninstall` 로 게이트를 뗍니다.

성능·통합 검증은 게이트가 아니라 **수동 스킬** `/performance`·`/integration` 입니다(승격 전 권장).
