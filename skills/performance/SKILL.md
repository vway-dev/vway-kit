---
name: performance
description: 성능 점검이 필요할 때 사용 — 성능 안티패턴(N+1·쿼리플랜·재귀/복잡도·프론트 리렌더) 정적 플래깅, 또는 API 부하 측정(p50/p95/p99·throughput·에러율 대 SLO). /vdev 게이트가 아니라 사람이 부르는 수동 스킬.
---

# performance

코드베이스의 **성능 안티패턴 정적 플래깅** + 백엔드가 있으면 **API 부하 측정** 수행.

> **포지셔닝**: 이 스킬은 정적 코드 분석으로 **의심 패턴을 플래깅**하는 것이지, 확정 탐지가
> 아님. 런타임에만 알 수 있는 결과(실측 지연·N+1 횟수·메모리 사용)는 본질적으로 **런타임
> 도구로 검증** 필수. false positive 는 "검토 요망"으로 표기하고 해당 런타임 도구로
> 최종 판정 위임.

> **디스패처 원칙**: 이 파일은 실행 가능한 커맨드 사본 미보유. 모든 grep/curl/node
> 커맨드는 아래 표가 가리키는 `references/*.md` 파일에 정확히 한 곳에만 존재 — SKILL.md 와
> reference 가 서로 다른 사본을 갖다가 드리프트되는 것을 원천 차단하기 위함.

---

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## 1. 스택 감지

호스트 문서 우선 소비, 없으면 내장 카탈로그로 폴백.

```bash
# 호스트 harness-researcher가 생성한 문서 확인 (Phase 4, 있으면 우선 소비)
ls docs/verification/performance.md 2>/dev/null && cat docs/verification/performance.md
```

- `docs/verification/performance.md` **존재 시**: 파일에서 스택 목록·SSOT·도구를 읽어 해당 스택 섹션만 실행. **호스트 문서가 감지된 스택 중 일부만 다루면, 문서에 없는 스택은 아래 §2 폴백 카탈로그로 보완** — host 문서 존재 여부는 "전체 대체"가 아니라 "우선 소비" 의미.
- `docs/verification/performance.md` **부재 시**, 또는 일부 스택만 커버 시: 미커버 스택은 아래 §2의 해당 파일로 폴백.

### 스택 자동 감지

| 신호 파일/패턴 | 판정 스택 | 참고 reference |
|---|---|---|
| `pyproject.toml` / `setup.py` / `*.py` | Python | [`static-checks-python.md`](references/static-checks-python.md) |
| `package.json` (`react`/`next`) | React | [`static-checks-react.md`](references/static-checks-react.md) |
| `pom.xml` / `*.java` / `build.gradle` | Java/Hibernate | [`static-checks-java.md`](references/static-checks-java.md) |
| `Gemfile` / `*.rb` | Ruby | [`static-checks-ruby.md`](references/static-checks-ruby.md) |
| `*.csproj` / `*.cs` | .NET | [`static-checks-dotnet.md`](references/static-checks-dotnet.md) |
| `package.json` (ORM/express 의존성, React 미탐지) | Node.js | [`static-checks-node.md`](references/static-checks-node.md) |
| `go.mod` / `*.go` | Go | (전용 static-checks 없음 — §2 DB·복잡도만 적용) |
| `*.sql` / DB 관련 마이그레이션 | DB | [`static-checks-db.md`](references/static-checks-db.md) |

복수 스택이 감지되면 **해당 스택 모두** 아래 §2에서 실행한다(스택 간 독립 — 순서 무관, 병렬 실행 가능).

---

## 2. 언어별 정적 안티패턴 플래깅

### 2.0 소스 루트 확정 (먼저, 필수)

reference 커맨드는 전부 `$SRC` 를 훑음. **이 값이 실제 소스 경로가 아니면 grep 이 빈 결과를
내고, 그것이 "안티패턴 없음"으로 보고됨** — 탐지 실패가 통과로 둔갑. 스택마다 실제 소스
디렉터리를 확정하고(예: `src` · `app` · `apps/api` · 패키지 루트 · `.`), 확정되지 않으면
Ask the user (structured choice) 로 묻는다(추측 금지).

`SRC` 는 **Bash 호출 사이에 안 남음** — 호출마다 새 셸이라 `export` 로 미리 심는 방식은
무효. 확정한 값은 reference 커맨드를 실행하는 **같은 호출의 첫 줄 `SRC=` 에 삽입**
(각 블록이 그 자리를 비워 둔 채 가드와 함께 옴). 스택이 여럿이면 스택마다 다시 채움
(모노레포는 스택별 경로가 다름). 리포트의 **측정 메타에 사용한 `SRC` 명시**
(빈 결과가 "없음"인지 "안 봤음"인지 구분).

### 2.1 실행

감지된 각 스택에 대해, §1 표가 가리키는 reference 파일을 **그대로 열어 그 안의 커맨드를 실행**.

모든 스택 공통으로 다음 두 파일도 함께 확인함:

- [`static-checks-db.md`](references/static-checks-db.md) — DB 쿼리 플랜 안티패턴(언어 무관)
- [`static-checks-complexity.md`](references/static-checks-complexity.md) — lizard 기반 복잡도/재귀/중첩루프 근사 탐지(언어 무관)

---

## 3. 백엔드 존재 시 API 부하분석

> BASE_URL 확인(사용자 확인 포함)·OpenAPI 발견·도구·부하 스크립트 생성·리포트 템플릿까지 전
> 과정은 → [`references/api-load.md`](references/api-load.md) 참조.

반복 횟수(기본 100)·SLO 임계는 스킬 기본값. 팀 부하 프로파일이 필요하면 스킬을 fork 하지
말고 호스트 `docs/verification/performance.md`(harness 생성)에 두어 그 값을 우선한다(config-주도 원칙).

---

## 4. 리포트 형식 (Four Golden Signals 골격)

```
## 성능 점검 결과 — <날짜>

### 정적 플래깅 결과
| 스택 | 패턴 | 위치 | 판정 | 권고 |
|---|---|---|---|---|
| Python/Django | N+1 의심 | users/views.py:42 | 검토 요망 | select_related('profile') 사용 |
| React | 인라인 객체 prop | components/List.tsx:17 | 검토 요망 | useMemo로 메모화 |

> 위 항목은 정적 탐지 후보 — 런타임 도구로 최종 판정 위임.

### API 부하 결과 (있는 경우)
| 엔드포인트 | p50 | p95 | p99 | RPS | VU | 에러율 | SLO | 판정 |
|---|---|---|---|---|---|---|---|---|
| GET /users | 12ms | 45ms | 120ms | 850 | 10 | 0.0% | p99≤200ms | PASS |
| POST /orders | 80ms | 350ms | 890ms | 210 | 10 | 1.2% | p99≤500ms | FAIL |

**측정 메타**: openapi-to-k6 0.3.x + k6 0.52.x / iterations=100 per endpoint(shared-iterations) / VU=10 /
warm-up 제외(첫 10회) / CO 보정 없음 / 로컬 실행(네트워크 오버헤드 없음)

### Golden Signals 요약
- **지연(Latency)**: …
- **트래픽(Traffic)**: …
- **에러율(Errors)**: …
- **포화도(Saturation)**: …
```

---

## 참조

- [`references/static-checks-python.md`](references/static-checks-python.md) · [`references/static-checks-java.md`](references/static-checks-java.md) · [`references/static-checks-ruby.md`](references/static-checks-ruby.md) · [`references/static-checks-dotnet.md`](references/static-checks-dotnet.md) · [`references/static-checks-node.md`](references/static-checks-node.md) · [`references/static-checks-react.md`](references/static-checks-react.md) — 언어별 N+1·리렌더 SSOT
- [`references/static-checks-db.md`](references/static-checks-db.md) — DB 쿼리플랜 SSOT (언어 무관)
- [`references/static-checks-complexity.md`](references/static-checks-complexity.md) — lizard 기반 복잡도 SSOT (언어 무관)
- [`references/api-load.md`](references/api-load.md) — BASE_URL 확인 + OpenAPI 발견 + openapi-to-k6/k6 + 리포트 표준
