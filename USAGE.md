# vway-kit 사용 설명서

[README](README.md)가 "무엇을 해 주나 + 빠른 시작"이라면, 이 문서는 주제별 상세로 가는 목차입니다.
각 주제는 [`docs/usage/`](docs/usage/) 아래 한 파일입니다. 플러그인 내부 원리는 개발자용
[.claude/CLAUDE.md](https://github.com/vway-dev/vway-kit/blob/main/.claude/CLAUDE.md)에 있습니다.

| 주제 | 다루는 것 |
|------|-----------|
| [시작하기](docs/usage/getting-started.md) | SSH 준비, 설치 순서, 자동 업데이트 토큰, 호스트에 생기는 것 |
| [설정](docs/usage/configuration.md) | `vdev-config.yaml` 의 블록별 역할, 편집하지 않는 `vdev-tiers.yaml` |
| [등급과 게이트](docs/usage/tiers-and-gates.md) | 네 등급, 게이트별 검사, 증거 마커, 머지 전략 |
| [일상 작업](docs/usage/daily-work.md) | `/vdev` · `commit` · `doc-sync` · 문체 규율 |
| [승격과 릴리스](docs/usage/promotion-and-release.md) | `/release-commit`, 릴리스 CI 토큰(`RELEASE_TOKEN`) |
| [CI 워크플로](docs/usage/ci-workflows.md) | `/vdev-init` 이 렌더하는 워크플로, 배포, E2E 안전망 |
| [프로젝트 하네스](docs/usage/project-harness.md) | `/harness-init` · `/wiki-init` · `harness-insight` |
| [ALM 연동](docs/usage/alm.md) | Recoble·Teamer 등록, 항목 상태, 계층 추적, `/alm-docs`, 인수인계 |
| [Codex](docs/usage/codex.md) | Codex CLI 설치·프로젝트 신뢰·훅 승인, Recoble MCP 등록, Claude Code 와 다른 점 |
| [Teams 알림](docs/usage/teams.md) | 웹훅 등록, 채널별 발화 시점 |
| [문제 해결](docs/usage/troubleshooting.md) | 차단 메시지별 원인, 설치·갱신 실패 |
| [갱신·제거](docs/usage/update-and-removal.md) | `/vdev-init` 재실행, `/vdev-uninstall`, 수동 정리 |

라이선스는 [README](README.md#라이선스).
