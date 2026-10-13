# 설정 — `vdev-config.yaml`

`/vdev-init` 이 만든 `.claude/vway-kit/config/vdev-config.yaml` 을 팀 환경에 맞게 채웁니다.
git 추적 파일이라 저장소를 공유하는 모든 개발자가 같은 설정을 씁니다(자격증명은 여기 없음).
**전체 키·기본값의 SSOT 는 [`vdev-config.example.yaml`](../../vdev-config.example.yaml) 의 인라인 주석**이고,
아래는 자주 고치는 블록만 보입니다.

`vdev-tiers.yaml`(등급 → 게이트, 머지 전략)은 플러그인 소유라 편집하지 않습니다 — 호스트 사본을
고쳐도 다음 `/vdev-init` 이 덮어씁니다.

## 예시

```yaml
branches:
  integration: dev          # feature 가 머지되는 통합 브랜치
  staging: stage            # QA/RC 승격 브랜치
  production: main          # 프로덕션 릴리스 브랜치

modules:                    # 모듈별 사전검사 — 모듈마다 언어·도구가 달라도 됨
  - name: api
    path: services/api/
    checks:                 # lint/static/import_lint/test → every-commit(변경 모듈)
      lint: "ruff check services/api"
      test: "uv run pytest services/api"
      security: "uv run bandit -r services/api"   # security → promotion(전체 모듈)
      # 커스텀 키는 {run, when: every-commit|promotion} 으로 버킷 지정

review_checklist:           # Dev 리뷰가 변경 파일마다 대조하는 항목
  - "regression / 회귀 테스트 통과"
  - "cross-service contract / 서비스 간 계약 유효성"

commit_guide: docs/operations/commit-versioning-guide.md   # 있으면 commit 스킬이 우선 적용

gate_evidence:
  invalidate_on_edit: true  # false = 통과 뒤 편집이 리뷰 없이 커밋됨

doc_sync:                   # doc-sync 대상
  index: CLAUDE.md
  dirs: ["docs/", ".claude/rules/"]
  service_docs: "services/*/CLAUDE.md"

doc_style:                  # 산문 문체 검사 — 블록이 없거나 enable: false 면 검사 없음
  enable: false
  paths:                    # 기본값. 문서만 보려면 "**/*.md" 한 줄
    - "**/*.md"
    - "**/*.py"
    - "**/*.sh"
    - "**/*.bash"
  exclude:                  # 기본값. 편집으로 고칠 수 없는 것
    - "**/CHANGELOG.md"
    - "docs/superpowers/**"
    - ".superpowers/**"
```

## 블록별 안내

| 블록 | 어디서 읽나 |
|------|-------------|
| `branches` · `modules` · `review_checklist` · `gate_evidence` | [등급과 게이트](tiers-and-gates.md) |
| `commit_guide` · `doc_sync` · `doc_style` | [일상 작업](daily-work.md) |
| `alm` · `handoff` · `issue_tracker_guide` | [ALM 연동](alm.md) |
| `contract_test` · `unit_test` · `versioning` · `e2e` · `deploy` | [CI 워크플로](ci-workflows.md) |
| `wiki` | [프로젝트 하네스](project-harness.md#wiki-init) |
| `harnesses` | [Codex](codex.md) |
