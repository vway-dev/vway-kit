# vway-kit

작업의 **위험도에 따라 AI 프로세스 강도를 조절**하는 Claude Code 플러그인입니다. 문서 한 줄
수정은 가볍게, 핵심 비즈니스 로직은 무겁게 — 등급에 맞는 게이트를 **커밋 시점에 강제**합니다.
**ALM 연동**(Recoble 워크보드 기본, Teamer 선택)과 **Teams 알림**이 함께 들어 있습니다.

브랜치명·테스트 명령·ALM 번호 같은 저장소별 값은 모두 설정 파일에 있어, 새 저장소에는
`/vdev-init` 한 번으로 옮겨집니다.

> 설치 상세·설정·주제별 사용법·문제 해결은 **[USAGE.md](USAGE.md)** 에 있습니다.

## 무엇을 해 주나

- **`/vdev`** — 작업을 Docs/Dev 로 분류하고 그 등급의 절차·게이트만 실행합니다. 분류를
  거치지 않은 커밋은 막힙니다. Dev 리뷰는 변경 파일 목록을 **`git`에서 직접** 받아 전부 보고,
  **변경된 public 심볼의 호출자**까지 확인합니다.
- **`/harness-init`** — 프레임워크를 감지해 `CLAUDE.md`·규칙·기술 문서를 생성합니다.
- **`/wiki-init`** — 문서를 front matter 기반 지식 그래프로 이관하고, 이후 커밋마다 그래프가
  문서와 어긋나지 않았는지 검증합니다.
- **ALM 연동** — `/vdev` 가 작업을 Recoble(또는 Teamer) 항목과 잇고, 끝나면 결과·상태를 올립니다.
- **Teams 알림** — 입력을 기다릴 때 또는 원하는 시점에 Teams 채널로 알립니다.
- **측정되는 스킬** — 모델이 찾지 않는 스킬은 실행되지 않는 절차입니다. 그래서 모델이
  스스로 부르는 스킬은 실제 headless Claude Code 세션으로, 가야 할 프롬프트는 닿고 가지
  말아야 할 프롬프트는 닿지 않는지 잽니다. description 이 재측정 없이 바뀌면 CI 가
  실패하고(주입 룰이 가리키는 스킬은 그 룰과 주입 훅까지), 통계적으로 유의한 호출률
  하락은 사유를 남겨 수용하지 않는 한 새 점수로 기록되지 않습니다.

## 요구사항

프로젝트 언어와 무관합니다. 대부분 `/vdev-init` 이 점검하고 동의를 받아 설치합니다.

| 항목 | 수준 | 없으면 |
|------|------|--------|
| `bash` + coreutils(`timeout`·`cat`·`grep`·`sed`·`awk`·`head`) | 필수 | 게이트가 조용히 무력화됨(Windows 는 Git Bash) |
| `python3` ≥ 3.8 + `PyYAML` | 필수 | 커밋이 **차단**됨 — `python3 -m pip install pyyaml`. Windows 는 `python3` 를 만드는 Python install manager(`winget install 9NQ7512CXL7T` 후 `py install 3.12`) |
| `pre-commit` | 권장 | lint·포맷·커밋 메시지 검사만 빠짐 |
| `keyring` | Teamer 를 쓸 때만 | Teamer 자격증명을 못 읽음 |
| `superpowers` 플러그인 | Dev 작업에 필수 | Dev 에서 `/vdev` 가 중단하고 설치를 안내 |

점검만: `bash .claude/vway-kit/scripts/check-deps.sh`(`/vdev-init` 이후, 설치는 안 함).

## 빠른 시작

```
/plugin marketplace add git@github.com:vway-dev/vway-kit.git
/plugin install vway-kit@vway
/harness-init      # 선택 — CLAUDE.md 가 없는 새 프로젝트면 먼저
/vdev-init         # 게이트·ALM·Teams 배선 (재실행 안전)
/vdev <작업 설명>
```

비공개 저장소라 **SSH 준비**가 먼저이고, 자동 업데이트에는 **토큰 설정**이 따로 필요합니다 —
[시작하기](docs/usage/getting-started.md).

**Codex CLI** 에도 같은 플러그인이 자기 마켓 명령(`codex plugin marketplace add`)으로 설치됩니다. 프로젝트
신뢰·훅 승인 단계가 따로 있고 몇 가지 동작이 다릅니다 — [Codex](docs/usage/codex.md).

## 제공물

| 종류 | 항목 | 역할 |
|------|------|------|
| 커맨드 | `/vdev` | 위험도 분류 → 등급별 워크플로 → 게이트 증거 기록 |
| 커맨드 | `/vdev-init` | 설치·갱신 마법사 — 최초 설정, 재실행 시 재동기화·슬롯 보충·재설정(설정값 보존) |
| 커맨드 | `/vdev-uninstall` | 호스트에 설치된 배선 제거 |
| 커맨드 | `/harness-init` | 프레임워크 감지 + 리서치·검증으로 하네스 생성(`.md` 기본, 덮어쓰기 없음) |
| 커맨드 | `/wiki-init` | 문서를 지식 그래프로 — 임베딩 없이 front matter 기반 |
| 커맨드 | `/alm-docs` | `docs/srs` ↔ requirement 계층 대조, 한 방향(`--pull`·`--push`)만 옮김. 게이트 아님 |
| 스킬 | `task-import` · `task-sync` | `/vdev` 의 ALM 단계 — 항목 가져오기·생성 / 결과·상태 동기화 |
| 스킬 | `alm-trace` · `alm-fetch` | `layers` 선언 시 계층 추적 그래프 생성 / 상태 전파 순회(Recoble 전용) |
| 스킬 | `commit` | 커밋 작성·발행 — type 선택·50/72·스테이징 |
| 스킬 | `release-commit` | 승격 하나를 끝까지 — 게이트·범프 레벨·머지 형태·백머지 |
| 스킬 | `doc-sync` · `prose-review` | 코드 ↔ 문서 동기화 / 산문 규칙 대조 |
| 스킬 | `harness-authoring` | `/harness-init` 의 생성 엔진(직접 호출 안 함) |
| 스킬 | `harness-insight` | 기간별 활동 인사이트 + 메모리 정리 |
| 스킬 | `playwright-scaffold` · `integration` · `performance` | E2E 스캐폴드 / 통합·성능 검증(비강제 수동) |
| 에이전트 | `harness-researcher` · `harness-code-analyzer` · `harness-critic` | 하네스 생성용 리서치 / 코드 분석 / 생성물 검증 |
| 룰 | `risk-tiers` · `doc-style` | 위험도·티어 워크플로 / 문체 기준 — 매 세션 주입(`doc-style` 은 쓰기 시점 요약만) |
| 룰 | `commit-discipline` | 커밋 메시지 형식·type → 버전 표 — `/commit` 이 읽음 |
| 룰 | `promotion` · `merge-strategy` · `gate-mechanics` · `harness-rules` | 승격 절차 / 머지 전략표 / 게이트 동작 / 하네스 생성 규율 — 필요할 때 읽음 |
| 플러그인 훅 | SessionStart · PostToolUse · Notification | 룰 주입 · 편집 시 review/doc-sync 증거 무효화 · Teams 알림 · 권한 승인 대기 시각 기록(Worklog) |
| 호스트 훅 | PreToolUse(Bash) | 커밋·머지 게이트 — `/vdev-init` 이 호스트 `settings.json` 에 등록 |
| CI | GitHub Actions | `/vdev-init` 이 config 로 렌더 — [CI 워크플로](docs/usage/ci-workflows.md) |

## 라이선스

[Apache License 2.0](LICENSE). 원본 [harness-tier](https://github.com/foryouself83/harness-tier)
(Apache-2.0) 의 고지는 [NOTICE](NOTICE), 서드파티 라이선스는
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
