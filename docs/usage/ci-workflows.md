# CI 워크플로 — `.github/workflows/`

커밋 게이트는 에이전트 세션(Claude Code·Codex) 커밋만 봅니다. CI 는 터미널·직접 커밋의 사각을 덮습니다.
`/vdev-init` 이 config 블록마다 워크플로를 렌더하고, 블록이 없거나 `enable: false` 면 만들지 않고,
이미 있는 파일은 덮어쓰지 않습니다. **전체 키·기본값은
[`vdev-config.example.yaml`](../../vdev-config.example.yaml) 인라인 주석이 SSOT**입니다.

| 스위치 | 렌더 결과 | 하는 일 |
|--------|-----------|---------|
| `contract_test` | `api-contract.yml` | REST API 계약 테스트(schemathesis) |
| `unit_test` | `unit-test.yml` | 모듈별 유닛 테스트 매트릭스(언어는 config 에 명시 선언) |
| `versioning` | `release.yml` (+ `branch-naming`·`entropy-check`) | **버전·태그·GitHub Release 만** — [승격과 릴리스](promotion-and-release.md) |
| `deploy` | `deploy.yml` + `deploy-<target>.yml` | 빌드·레지스트리 발행 |
| `e2e` | `e2e.yml` | Playwright E2E 안전망 — **차단 없음** |
| `doc_style.enable` | `doc-style.yml` | 산문 규율의 유일한 판정(커밋 게이트는 경고만) |
| `docs/srs/` 존재 | `srs-verify.yml` | SRS 무결성 — `/vdev-init` 이 묻고 동의하면 복사 |
| `/wiki-init` | `wiki-verify.yml` | 그래프 drift 검증 — 그래프 `--verify` 통과 뒤 `/wiki-init` 이 제안 |

`doc_style.enable` 은 렌더와 검사 스크립트가 **함께** 읽습니다 — 되돌리면 렌더된 워크플로가 삭제 없이
조용해집니다. 그래서 `enable: false` 는 가벼운 검사가 아니라 검사 없음입니다. 설정 파일이 YAML 로
안 읽힐 때의 예외는 [gate-mechanics](../../rules/gate-mechanics.md).

`branch-naming.yml` 은 브랜치 push 마다 돌고 태그 push 는 건너뜁니다(`branches: ["**"]`). 통과하는 이름은
`feature/*`·`fix/*`·`docs/*`·`hotfix/*`·`release/X.Y.Z`·`dependabot/*`·`renovate/*` 와, 설정된 세 브랜치
(`branches.integration`·`versioning.branches.stable`·`.prerelease`)입니다. 세 브랜치는 패턴이 아니라
문자열로 비교합니다.

렌더된 워크플로는 전부 최상위 `permissions:` 로 토큰 권한을 선언합니다 — 없으면 저장소 기본값을 받고,
GitHub 가 기본값을 바꾸기 전에 만든 저장소에서는 그것이 모든 범위의 읽기·쓰기입니다. 배포 쪽은 예외로,
`deploy.yml` 은 job 마다 선언하고 `deploy-<target>.yml` 은 호출 job 의 권한을 물려받습니다.

## 배포 — `deploy`

`release.yml` 이 태그를 만들면 `deploy.yml`(오케스트레이터)을 `workflow_call` 로 부르고, 오케스트레이터가
타깃별 `deploy-<target>.yml` 을 부릅니다. 릴리스하지 않은 실행은 배포도 건너뜁니다.

```yaml
deploy:
  enable: true
  order: [pypi, api-image]        # 선택 — needs 체인. 생략하면 병렬
  targets:
    - name: pypi
      target: pypi                # pypi | npm | maven-central | cratesio | ghcr | custom
      auth: token                 # oidc | token
      version: "3.12"
      build: "uv build"
    - name: api-image
      target: ghcr
      image: ghcr.io/OWNER/REPO/api
      context: services/api
```

- **`custom`** — 정적 5종 밖은 직접 저작한 재사용 워크플로 경로를 `workflow:` 로 지정합니다.
- **`auth`** — `oidc`(시크릿 불필요) 또는 `token`. PyPI 는 재사용 워크플로에서 신뢰발행이 안 돼 기본이
  `token` 입니다(npm·crates.io 는 `oidc` 가능). OIDC 신뢰발행은 최상위 `release.yml`(수동 배포 시
  `deploy.yml` 도)에 등록합니다.
- **`build`·`publish`** — 명령을 config 가 선언합니다. `maven-central` 의 `publish` 는 **필수이고 기본값이
  없습니다** — Sonatype Central 기본이 "업로드만, 미발행"이라 태스크를 의식적으로 고르게 합니다.
- **시크릿** — PyPI `PYPI_API_TOKEN`, npm `NPM_TOKEN`, crates.io `CARGO_REGISTRY_TOKEN`, GHCR 내장
  `GITHUB_TOKEN`, Maven Central Portal user token + GPG. 각 컴포넌트 헤더 주석에도 적혀 있습니다.
- **prerelease 태그** — rc 태그(`vX.Y.Z-rc.N`)는 기본 채널을 옮기지 않습니다. npm 은 `next` dist-tag 로
  발행해 `latest` 를 그대로 두고, GHCR 은 받은 태그 하나만 붙이며 `latest` 를 달지 않습니다.
- **수동 재배포** — `deploy.yml` 의 `workflow_dispatch` 에 `tag`·`target`(또는 `all`).
- **배선** — `/vdev-init` 이 `release.yml` 에 deploy 호출 job 을 마커 블록으로 넣고 권한을 타깃에서
  파생합니다. `enable: false` 로 재실행하면 그 블록을 제거합니다. `deploy.yml` 이 생성 헤더로 시작하지
  않으면(호스트가 직접 쓴 파일) 배선을 보류합니다 — 호출 job 이 넘기는 `tag` 입력을 그 파일이 받지
  않으면 GitHub 이 `release.yml` 전체를 거부하기 때문입니다.

## E2E 안전망 — `e2e`

승격 브랜치 push 마다 Playwright 스위트를 돌려 터미널·직접 커밋으로 들어온 통합 회귀를 **보이게**
만듭니다. 아무것도 차단하지 않습니다. `/integration` 의 CI 짝입니다.

- `e2e.enable: true` 로 켜고 `/vdev-init` 을 돌리면 그대로 복사됩니다. `playwright.config.*` 가 없으면
  `/vdev-init` 이 `/playwright-scaffold` 를 안내하고, 워크플로는 config 가 생길 때까지 스텝을 건너뛰어 green 입니다.
- 범위는 Linux 러너 위 Playwright 입니다. Windows 데스크톱 UI 는 범위 밖이고, 웹이 아닌 저장소는
  `unit-test.yml`·`api-contract.yml` 이 대신합니다.
- 채울 `EDIT` 표시 넷: ① 트리거 브랜치(기본 `[stage, main]`) ② 런타임 setup action ③ 스택 기동·대기·
  teardown(Playwright `webServer` 를 쓰면 셋을 함께 삭제) ④ `working-directory` 두 곳(서로 같게).

**필수 상태 검사로 올리려면** 템플릿 꼬리의 전제 넷을 전부 갖추거나 아예 하지 않습니다:
`pull_request:` 트리거 추가 · `workflow_dispatch:` 유지 · 룰셋 bypass actor 또는 복구 담당 합의 ·
fork PR 은 시크릿을 못 받는다는 점 수용. 플러그인은 이 배선을 하지 않습니다.

**승격을 실제로 막고 싶다면** `modules[].checks` 에 `when: promotion` 검사를 더합니다 — `security-scan`
버킷으로 가서 Staging·Release 커밋을 막습니다. 대가: 커밋이 스위트가 끝날 때까지 멈추고, 도는 동안
출력이 안 보이고, 승격마다 전체가 돌고, 모듈 검사에는 **타임아웃이 없어** 멈춘 스위트가 멈춘 커밋이 됩니다.
