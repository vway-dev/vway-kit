# 기술문서 작성 가이드

`harness-authoring` 이 호스트 프로젝트용 기술문서를 생성할 때 따르는 규율.

## 폴더 구조 (분류별)

문서는 분류별 폴더, 진입 문서는 `README.md`(GitHub 폴더 렌더링 친화적).

```text
docs/
  README.md                  전체 인덱스 · 가장 마지막 작성(다른 문서를 링크)
  srs/README.md              공통 절(용어집·개요·목표·사용자·고객요구·비기능 요구사항·제약) + 영역 인덱스 · 가장 먼저
  srs/<area>.md              §5 기능 요구사항, 요구사항 영역마다 한 파일
  sds/README.md     구조 + Mermaid 구조도(필수)
  code-style/
    README.md                스택 인덱스 + 공통 원칙
    <stack>.md               스택별 컨벤션(스니펫 제외)
  research/
    README.md                리서치 요약 인덱스
    <topic>.md               .harness/research/ 에서 편입(출처 링크)
  verification/
    README.md                검증 문서 인덱스(performance·integration 링크)
    performance.md           스택별 성능 SSOT · 확정 스택만(부재 시 /performance 내장 폴백)
    integration.md           스택별 통합 검증 SSOT · 확정 스택만(부재 시 /integration 내장 폴백)
  operations/
    commit-versioning-guide.md  Conventional Commits·SemVer·릴리스 도구 설정 · vdev 감지 무관 항상
  onboarding/README.md       실행/디버그 + 주요 문서 링크 · 가장 마지막 작성
```

**작성 순서**: `SRS → research편입 → SDS → code-style → onboarding → docs/README`.
research 는 SDS·code-style 의 **입력(근거)이므로 먼저 편입** — 그래야 두 문서가 이미 편입된
`docs/research/` 를 출처로 링크 가능.
**기존 `docs/` 관례 존중**: 이미 다른 구조(`documentation/` 등)면 그쪽 우선 + 누락 분류만 추가.
**brownfield SRS 와 역산 금지** — [harness-rules 8-1](../../../rules/harness-rules.md).
**출처 링크 의무** — 모든 문서는 참조한 research 문서/외부 URL 을 마크다운 링크로. 근거 없으면 "출처 미확인".

## SSOT 분리 (중복 금지)

- **구조적 컨벤션**(폴더/스키마 위치) → `.claude/rules/<framework>-conventions.md`(룰).
- **행위적 가이드**(네이밍·포맷·BP·안티패턴·툴체인 설정) → `docs/code-style/<stack>.md`(문서).
- 룰이 문서를 가리키되 내용 복제 금지.

## SRS — srs/README.md

`srs.template.md` 를 채움. **범위 요약(harness-init Step 1-0 의 scope summary)을 SSOT 로** 채우고
research 로 보강. 미상 슬롯은 추측 말고 "확인 필요"(harness-rules 8-1 — 공백뿐 아니라 모호 항목도
작성 전 질문으로 해소). **두 레벨로 분리**: 고객 요구(§4)는 측정가능하진 않아도 무엇을
원하는지 명확하게("편했으면" ✗ → "카드·간편결제 지원" ✓), 기능 요구사항(§5, FR)은 측정 가능·단일 해석.

**SRS 는 코드를 쓰지 않는 사람도 읽음** — 기획자·고객·QA. 셋 모두 읽을 수 있게 하는 규칙 셋:

- **비즈니스 언어** — 요구는 사용자나 비즈니스가 관찰하는 것을 말하고, 그것을 만드는 구현은
  말하지 않음("DB 인덱스로 쿼리 최적화" ✗ → "검색 버튼을 누르면 2초 안에 결과가 보임" ✓).
  구현은 SDS 몫. 기술 척도(p95·rps·RTO)는 관찰 가능한 기준의 측정 조건으로만 붙음.
- **용어집이 먼저** — `## 용어집` 절이 `srs/README.md` 를 §1 보다 앞에서 엶. SRS 가 쓰는 모든
  도메인 용어·비즈니스 용어·약어가 거기 한 항목씩, 비개발자가 이해하는 말로 정의되고,
  `--next-id --kind TERM` 이 발급한 `<a id="term-xxx">` 앵커를 가짐. "해당 없음"은 없음: 정의할
  용어가 하나도 없는 문서는 아직 도메인에 이름을 붙이지 않은 것.
- **한 용어 한 뜻** — 모든 SRS 파일에서 각 대상을 용어집의 용어로 부르고 다른 말로는 부르지 않음
  (한 기능에 "로그인"·"사인인"·"사용자 인증" ✗). 독자가 들고 올 법한 동의어는 그 항목 안에서 한 번만
  언급하고 다른 곳에서는 안 씀. 용어 이름을 바꾸면 같은 편집에서 모든 파일의 이름을 바꿈.

**계층 분류(고정 스키마)**:
- **고객 요구(§4)** — 고객/이해관계자가 원하는 것을 `C-x` 로. 각 C 에 `<a id="c-xxx">` 앵커. §5 FR 이
  `(← [C-x])` 로 역참조해 고객요구→FR 추적 원천이 됨. **외부 고객/이해관계자가 없으면(개인·내부 도구)
  "해당 없음 — 단일 이해관계자"로 두고 생략(빈 의례 금지)**.
- **기능 요구사항(§5)** — 요구사항 영역마다 `docs/srs/<area>.md` 한 파일(`srs-area.template.md`
  복제). 파일 안은 `도메인(1차) > 사용자권한/하위영역(2차) > 개별 FR(3차)`. 각 FR 은
  `ID · 설명 · 우선순위(P0/P1/P2) · 수용 기준(측정 가능)`이며, **각 FR 에 `<a id="fr-<area>-xxx">`
  앵커를 달아 SDS 모듈 개요가 링크로 역추적하게 함**. 출처 고객 요구가 있으면
  `(← [C-x](README.md#c-xxx))` 로 역참조(README 로 넘는 백링크). 번호는
  `srs_check.py --next-id <파일> --kind FR` 가 발급. 적용 안 되는 축은 삭제하지 말고 "해당 없음 — 사유".
- **비기능 요구사항(§6)** — ISO/IEC 25010 정렬 고정 하위축: 성능·보안·가용성·확장성·접근성·
  유지보수성·호환성. 각 축은 **우선순위 [P0/P1/P2]** + 정량 기준(또는 "해당 없음 — 사유", 빈칸
  금지) + `<a id="nfr-xxx">` 앵커를 가져 SDS 의 `NFR 실현` 절이 역추적하게 함. **검증 절차는
  `docs/verification/*` 가 SSOT** — 링크하고 여기 옮겨 적지 않음. 섹션 앵커는 **축**, 개별
  추적 요구는 그 아래 항목 앵커 `<a id="nfr-<stem>-NNN">` — 축 키는 섹션 앵커의 stem.
- **사용자/시나리오(§3)** — 사용자 권한(role)별로 분류해 기능의 권한 축과 연결.

**데이터·외부 인터페이스 요구는 별도 절이 아님** — 데이터 보존·규정 요구는 측정 가능하므로
FR 로 씀("계정을 삭제하면 90일 뒤 개인정보가 지워짐. 수용 기준: 삭제한 계정의 개인정보가 90일
뒤에 남아 있지 않음"). 밖에서 부과된
인터페이스 의무는 §7 제약에 옴 — 시스템이 수행하는 것이 아니라 외부가 지운 것. 소유
데이터와 통합 지점 계약 자체는 원래부터 SDS 의 것(아래 데이터 설계·통합 지점 참조).

## SDS — sds/README.md

**`sources` front matter**: brownfield 는 모듈 개요가 대는 실제 코드 경로로 채움 — 그
모듈들을 만들어 낸 분석이 이미 그것을 찾았고, 맵을 비워 두면 `doc-sync` 가 `--unmapped`
로 집어 올릴 때까지 문서가 `--stale`·`--nodes-for` 밖에 있음. greenfield 는 빈 채로
(`sources: {}`) 출하 — 코드가 아직 없고, 지어낸 경로가 이것이 피하는 실패임. 빈 맵은
누락이 아니라 진술 — `--verify` 는 키가 없거나 뒤에 아무것도 없을 때만 경고.

스택/버전 + 폴더 구조 + **Mermaid 구조도(필수, 최소 1개)** + 모듈 개요.
확인된 사실만 노드화(추측 노드 금지). 가능하면 데이터 흐름 다이어그램 추가.
**모듈 개요**: 구조도의 각 노드를 구현 단위로 한 단계 내려 `구현 요구사항·책임(단일)·제공 인터페이스·
사용 인터페이스·소유 데이터`를 기재(아키텍처=노드, SDS=노드의 계약). **구현 요구사항은 이 모듈이
충족하는 SRS FR 을 마크다운 링크로 역추적** — 영역 파일의 FR 앵커로
`[FR-<AREA>-xxx](../srs/<area>.md#fr-<area>-xxx)`
(SRS 의 `<a id="fr-<area>-xxx">` 앵커와 쌍으로 유지, 표준 Requirements Matrix 역할). **인프라/횡단
모듈(로깅·설정·DB어댑터)은 "FR 매핑 없음"으로 유지**(억지 매핑·죽은 링크 금지).
제공/사용 인터페이스는 UML provided/required 분리 — 제공=외부에 노출하는 계약, 사용=동작에 필요한 외부
계약(내부 다른 모듈 + 외부 시스템, = 의존의 구체화). **분해 축**: 절차적·데이터 파이프라인·함수형 프로젝트는
모듈 대신 처리 단계·데이터 흐름을 1차 단위로 사용. 클래스/타입 상세는 인터페이스에 흡수. 단일 모듈이면 1개만(YAGNI).
**NFR 실현(요구→설계→검증 다리)**: FR 은 모듈별 "구현 요구사항"으로 추적하고, NFR 은 전용
`## NFR 실현` 절에서 추적 — 측정 가능한 SRS §6 NFR(`#nfr-xxx`)마다 그것을 충족하는 모듈/설계
결정과 검증 SSOT(`docs/verification/*`) 링크를 맵핑. 횡단 NFR 은 한 모듈에 매이지 않아도
됨. 측정 가능한 NFR 이 없으면 생략(YAGNI).
**요구사항 커버리지(양방향 검사)**: 모듈→FR 단방향 링크를 `## 요구사항 커버리지` 절로 닫음 —
모든 SRS FR 이 최소 한 모듈에 구현되고 측정 가능한 NFR 이 전부 실현되었음을 확인하고, 매핑 없는
FR/NFR 은 갭으로 명시(조용한 누락 금지).
**데이터 설계(DB 있을 때만)**: 모듈↔데이터 연계·트랜잭션 경계만. 스키마 상세는 코드/마이그레이션이
SSOT — 복제 금지. DB 없으면 절 생략(YAGNI). **UI 흐름(UI 있을 때만)**: 화면 전이·상태·주요 액션
(스크린샷 제외, 흐름만). UI 없으면 생략. **예외 처리·에러 핸들링은 SDS 에 두지 않음** —
`docs/code-style/<stack>.md` 의 error-handling 소섹션이 SSOT(9-1), 중복 금지.
**통합 지점(다중 컴포넌트)**: 컴포넌트가 경계(프로세스/오리진/호스트/인증)를 넘어 통신하면 `## 통합 지점`
절에 통신 쌍별 계약 명시 — 도달성(호스트/라우트 해석)·identity/오리진 일치(issuer·CORS)·정책
연속성(보안 헤더/CSP 가 흐름을 막지 않고 전 응답 경로 유지)·자격증명 프로비저닝·전역 설정 blast radius.
research 가 제공한 통합 요구를 반영하고 출처 표기. **단일 프로세스면 생략**(YAGNI — 없는 경계를 지어내지 않음).
**스택 reconcile 결정 절**(harness-rules 10-1): 리서치에서 승격/기각된 (인프라 포함) 스택과 사유를 한
줄씩 기재 — 버전관리되는 결정 출구(gitignored 인 `.harness/rationale.md` 의 중복이 아니라, 그 핵심
결정만 doc 으로). 승격/기각이 없으면 절 생략.
**모듈 분할(조건부)**: 기본은 `sds/README.md` 단일 파일. 모듈이 다수로 확정된 큰 프로젝트만 `sds/<module>.md`
로 분할하되, 공통 `README.md` 는 인덱스 + 전체 구조도 + 통합/reconcile 만 두고 모듈 개요 본문은 모듈 파일이
SSOT(양쪽 중복 금지). greenfield 초기 모듈 미확정이면 미분할(조기 고착 금지 — 구현하며 확정 후 분할).

## code-style — code-style/README.md + <stack>.md

- 스택별로 파일 분리. 파일명 = `<language>` 또는 `<language>-<framework>`(또는 플랫폼).
  예: `typescript-react.md`·`python-fastapi.md`·`go.md`. **같은 언어여도 프레임워크/플랫폼이
  다르면 분리**(강조점이 달라 한 파일로 묶으면 둘 다 얕아짐). **인프라도 컨벤션이 실재하면 스택으로
  파일 분리**(예: `docker.md`·`postgresql.md`·`github-actions.md`) — Step 2.5 reconcile 로 승격된
  스택 포함(harness-rules 9-6). 대상은 초기 stack_map 이 아니라 **reconcile 확정 집합 전체**.
- 각 `<stack>.md` 는 네이밍·포맷·임포트 / 베스트 프랙티스(**관점 렌즈별** — 아래 "관점 관심사 섹션") /
  안티패턴(바퀴 재발명 포함) / 툴체인 설정 / reuse 후보를 **산문으로 상세히** 기재. **코드 스니펫 금지**.
- **툴체인 설정은 한 세트로** — 빌드러너·컴파일러·번들러·타입체커·린터·테스트러너의 상호
  정합성(예: `tsc -b`(references) ↔ 번들러 include scope)을 함께 기술. 감지된 버전의
  공식 작성법을 출처와 함께.
- **사전검사 도구 목록 명시(필수)** — `/vdev-init` 이 `vdev-config.modules[].checks` 초안을 작성할 때
  이 SSOT 를 참조. 툴체인 설정 섹션 안에 다음 축을 **언어/스택별로** 명시:
  - **lint**: 코드 품질 린터 (예: ruff, eslint, golangci-lint)
  - **format**: 포맷터 (예: ruff format, prettier, gofmt)
  - **typecheck**: 타입 검사 도구 (예: mypy, tsc --noEmit, go build)
  - **import_lint**: 임포트 질서 도구 (예: isort, import-sort, goimports) — 없으면 "해당 없음"
  - **security**: 정적 보안 스캐너 (예: bandit, semgrep, govulncheck) — 없으면 "해당 없음"
  - **test runner**: 테스트 실행 명령 (예: pytest, vitest, go test)

  각 도구는 **현재 권장 버전(research 확인)·실행 명령·설정 파일 위치**를 함께 기재. 이 목록이 없으면
  `/vdev-init` 이 초안 checks 를 추론에 의존하므로 반드시 명시.
- **폴더 구조(tests/ 위치 명시)** — 테스트 폴더 위치·규약(예: `tests/unit/`·`tests/integration/` 분리 여부,
  파일명 패턴 `test_*.py`·`*.test.ts`)을 툴체인 설정 섹션에 함께 기술. 모듈이 여러 개면 각 모듈의
  tests/ 위치를 명시(예: `packages/<module>/tests/`). `/vdev-init` 이 모듈 경계와 test 경로를
  매칭할 때 이 정보를 사용.
  단, **이 항목은 가이드(SSOT 기록)이지 게이트 강제 아님** — 강제는 vdev(harness-rules 14-1) 몫.
- **현재 권장 도구 기준** — 패키지 매니저·빌드 등 도구는 학습된 과거 표준이 아니라 research 가
  확인한 **지금 권장되는 것**을 기재(생태계 표준은 이동함 — 관성적 기본값 회귀 금지).
- `code-style/README.md` 는 스택 목록 링크 + 공통 원칙(출처 표기 등)만.
- **관점 관심사 섹션**(9-1~9-4): 각 `<stack>.md` 의 "## 베스트 프랙티스"는 **자유 산문 소섹션이 아니라
  렌즈별 관리 마커 블록**(`<!-- code-style:lens:<stack>:<lens-key> BEGIN -->` ~ `END`)으로 배치 — 마커여야
  `/harness-init` 재실행이 렌즈 단위로 갭만 찾아 채울 수 있음(자유 산문은 재실행 시 갱신 대상 특정
  불가). **형식·순서의 SSOT는 [`code-style.template.md`](../templates/code-style.template.md)** — 여기선
  규율만 서술하고 마커 문구·예시 복제 금지.
  9렌즈 정본 순서(9-1, `LENS_KEYS`)로 블록을 두며 헤딩: 정확성(correctness)·운영
  (operational)·보안(security)·성능(performance)·UX/상호작용(ux)·접근성(a11y)·국제화(i18n)·
  유지보수성(maintainability)·계층 횡단(cross-cutting). 각 블록 안엔 필요시 축별 소섹션
  (`#### error-handling`·`#### duplicate-submit` 등)을 두고, 축 소섹션엔 **채택 표준(권장 기본/감지됨)·
  매핑·안티패턴·예제·대안**과 **출처 URL(SSOT)** 기재. greenfield 미확정 표준은 "권장(변경 가능)"으로
  표기. 구조적 지시(룰)는 여기 복제 금지, 룰이 축 앵커(`#error-handling`)로 링크(GitHub 앵커는
  제목 텍스트 기반이라 렌즈 블록 아래 중첩돼도 `#<axis>` 링크가 유효). **적용 렌즈·축만 emit**(9-2 — UI
  없는 스택엔 UX/접근성 렌즈, 사용자 대면 없는 스택엔 국제화 렌즈, 단일 계층엔 계층 횡단 렌즈 생략 —
  스킵된 렌즈는 블록 자체를 두지 않음). **경계(중복 금지)**: 성능 렌즈는 *코딩 패턴*만 두고 검증 도구·
  부하 절차는 `docs/verification/performance.md` 로 링크; 계층 횡단 렌즈는 *계층 일관 규율*만 두고
  구체 통신 계약은 `docs/sds` 통합 지점으로 링크.

## research — research/README.md + <topic>.md

`.harness/research/*.md` 를 사람이 읽을 수 있게 정제(출처 링크 추가)해 `docs/research/` 로 편입.
정제한 본문은 **plan 항목**(`action: create`)으로 실음 — 셸 복사 아님(규율·강제 지점 SSOT 는
harness-rules 4-2).
`research/README.md` 는 조사 항목 요약 인덱스. **다른 문서가 research 를 출처로 링크할 때는 편입
위치 `docs/research/` 를 가리킴 — gitignored 증거인 `.harness/` 경로를 산출물에 절대 금지**
(편입 후 `.harness/research/` 사본은 init 의 cleanup 이 정리하므로 `.harness/` 링크는 깨짐).

## onboarding — onboarding/README.md (가장 마지막)

실행/디버그 + **"처음 온 사람을 위한 주요 문서 링크"** 절(SRS·SDS·code-style·research 로의 링크).
vdev 감지 시 커밋 규율은 commit-discipline.md, PR 규율은 risk-tiers 로 defer(여기 중복 금지). 다른 문서가 다 작성된 뒤 마지막에 작성.

## verification — docs/verification/ (performance·integration 묶음)

`/performance`·`/integration` 이 소비하는 두 SSOT 문서는 **`docs/verification/` 한 폴더**에 배치
(루트 평면 금지 — 분류별 폴더 규약). 진입 문서 `verification/README.md` 는 두 문서로의 링크 인덱스만
배치(내용 복제 금지). **확정 스택이 하나도 없어 두 문서를 모두 생략하면 `verification/` 폴더 자체를
생성 금지**(빈 폴더·빈 인덱스 금지).

## performance — docs/verification/performance.md

harness-researcher 의 `### 성능 SSOT (스택별)` 절을 소비해 생성.

- **목적**: `/performance` 스킬이 우선 소비하는 스택별 성능 SSOT. 부재 시 스킬 내장 references 폴백.
- **구조**:
  - 스택별 절(`## <스택>`) — N+1 탐지 도구·프로파일러·정적 복잡도·쿼리플랜 절차·출처 링크.
    확정 스택만 작성; 빈 절 금지.
  - 공통 API 부하 절(`## API 부하 공통`) — openapi-to-k6+k6(AGPL-3.0) 1순위 /
    MIT 폴백(oha/autocannon/vegeta) / 리포트 표준(p50/p95/p99·SLO PASS/FAIL·Four Golden Signals).
  - 출처는 `docs/research/` 로 링크. 직접 `.harness/` 경로 참조 금지.

## integration — docs/verification/integration.md

harness-researcher 의 `### 통합 검증 SSOT` 절을 소비해 생성.

- **목적**: `/integration` 스킬이 우선 소비하는 통합 검증 SSOT. 부재 시 스킬 내장 references 폴백.
- **구조**:
  - 스택별 절(`## <스택>`) — 웹이면 Playwright 설정(testDir/testMatch·`--reporter=json`),
    비웹이면 human-in-the-loop + 참고 OSS(Newman/Maestro/Appium). 확정 스택만; 빈 절 금지.
  - 공통 E2E 절(`## E2E 공통`) — 케이스 0개 시 임의 생성 금지·사람 보고, playwright MCP 보조 경로.
  - 출처는 `docs/research/` 로 링크.

## operations — docs/operations/commit-versioning-guide.md

**vdev 감지 여부와 무관하게 항상 생성** — 코드스타일+컨벤션 문서 범위라 harness-rules
rule 14 defer 대상 아님. 규율 SSOT 는
[harness-rules.md](../../../rules/harness-rules.md) §버전/릴리스 컨벤션 리서치(13·13-1·13-2).
출처는 `docs/research/` 로 링크(`.harness/` 경로 참조 금지 — cleanup 후 깨짐).
`vdev-config.commit_guide` 가 이 경로를 가리키고, `commit` 스킬이 그 값으로 이 문서를 읽어
스택 고유 사실을 자기 일반론보다 우선.

### 섹션 순서

1. **Conventional Commits 요약** — `<type>[optional scope]: <description>` 형식, 주요 type
   (`feat` MINOR · `fix` PATCH · `BREAKING CHANGE` MAJOR · `chore`/`docs`/`ci` 비영향),
   공식 링크 <https://www.conventionalcommits.org>(필수). 메시지 본문은
   [commit-discipline.md](../../../rules/commit-discipline.md) 가 소유한 `Body`·
   `No history narration` 불릿을 그대로 출력(재서술 금지 — [doc-style.md](../../../rules/doc-style.md)). 본문 *형식*이라
   vdev 없는 호스트도 받고, vdev 가 감지되면 6 과 함께 defer 되어 이 문서는 아무것도 안 냄.
2. **SemVer 정책** — `MAJOR.MINOR.PATCH` 의미(<https://semver.org>) + 0.x 프로젝트 권장:
   `major_on_zero=false`(`BREAKING CHANGE` 커밋에도 0.x 유지 — 1.0.0 우발 승격 방지),
   annotated 태그(`git tag -a v0.x.y -m "release v0.x.y"` — lightweight 보다 changelog 도구
   친화적), 1.0.0 승격은 명시적 수동 결정으로만.
3. **릴리스 도구 설정 (스택별)** — 스택이 확정된 경우만 기술하고, 미확정이면 "확인 필요"로
   두고 지어내기 금지(harness-rules 4). 아래는 후보이며 research·code-analyzer 근거 없이
   특정 도구 확정 금지.

   | 스택 | 권장 도구 | 버전 파일 |
   |------|-----------|-----------|
   | Python | `python-semantic-release` | `pyproject.toml` 의 `[tool.poetry] version` 또는 `__version__` |
   | Node/TypeScript | `semantic-release` | `package.json` 의 `"version"` |
   | Rust | `cargo-release` | `Cargo.toml` 의 `[package] version` |
   | Go | `goreleaser` | `go.mod` 태그 기반(파일 버전 없음 — git 태그가 SSOT) |
   | Java | `jreleaser` | 버전 외부주입(`JRELEASER_PROJECT_VERSION` env) — 파일 SSOT 없음 |
   | C# | `gitversion` | 파일 없음 — git 태그·브랜치 기록 기반 계산(`GitVersion.yml`) |
   | Scala | `sbt-ci-release` | 파일 없음 — git 태그 기반(`sbt-dynver`), `build.sbt` 에 버전 정의 금지 |
   | 기타 | researcher 가 생태계 표준 조사 후 근거와 함께 제안 | — |

   도구별로 research 결과로 채울 설정 항목:
   - changelog 생성 여부·파일 위치.
   - **CHANGELOG 정리 + 릴리스 본문(그룹핑)** — `python-semantic-release` 는
     `[tool.semantic_release.changelog]` 의 `exclude_commit_patterns`(PSR 공식 권장 세트:
     chore/ci/refactor/style/test/build-비deps)로 소비자에 무의미한 커밋을 CHANGELOG 에서
     제외(release 배관 `chore(release): … [skip ci]` 포함). 릴리스 본문은 이 CHANGELOG 의
     `vX.Y.Z`(+그 `-rc.*`) 섹션을 **버전매칭**으로 집계(Features/Bug Fixes/Performance)해 채우고,
     매칭이 비면 GitHub 자동 노트로 폴백 — finalize 가 내용을 rc 태그에 귀속시켜 정식 섹션이
     비므로 정식과 그 rc.* 를 함께 매칭. `semantic-release`(Node)는 release-notes-generator 가
     네이티브로 그룹핑하므로 별도 배선 불요.
   - pre/post-release CI 훅.
   - `vdev-config.versioning.release_tool`·`version_files` 슬롯 제안값.
   - **수동 bump 선택 (스테이징 강제 · 프로덕션 finalize)** — 렌더된 release 워크플로는 staging
     머지 커밋 본문의 `Release-Level: <level>` 트레일러로 **프리릴리스(스테이징)** rc 레벨을 받음.
     받는 레벨은 워크플로의 `# vway-release-levels:` 선언이 SSOT(`continue` = 대기 rc 의 rc.N+1,
     `auto` 는 커밋 타입 파생 도구만). **프로덕션(스테이블)** 브랜치는 재계산/재강제 없이 도달
     가능한 rc 를 **finalize**(`-rc.N` 제거)하고, rc 가 없으면(hotfix) 트레일러 레벨·없으면 patch 로
     정식 릴리스. `semantic-release`(Node)는 강제 미지원(커밋 타입만) → rc→정식은 네이티브.
     승격 시 선택 절차는 [promotion.md](../../../rules/promotion.md) Version bump selection,
     그 밖의 프로세스 규율은 risk-tiers 로 defer(중복 emit 금지).
   - **커밋 타입에서 bump 를 파생하는 도구와 아닌 도구를 명시.** `python-semantic-release`·
     `semantic-release` 는 Conventional Commits 를 스스로 읽지만 `jreleaser`·`gitversion`·
     `cargo-release` 는 안 읽음(각 도구 공식 docs 로 확인한 사실 — 새 스택에 같은 검증 없이
     가정 금지). 렌더된 워크플로는 후자에 대해 "최신 정식 태그 + `Release-Level:` 트레일러"
     모델 사용. 커밋을 쓰는 사람에게 걸리는 사실이라 반드시 출력 — 파생 안 하는 도구에서는
     `feat`/`fix` 선택이 버전을 전혀 안 움직이고 레벨이 트레일러로만 정해짐.
     `commit` 스킬이 이 문서에서 가져가는 세 사실(스코프 어휘·0.x 정책·이 파생 여부) 중 하나.
4. **릴리스 CI 쓰기 권한** — release 워크플로가 커밋/태그 push·릴리스 생성을 하려면 저장소
   쓰기 권한이 필요하고, **[A] 또는 [B]** 중 하나로 충족(둘 다 관리자 1회): **[A]** 저장소
   전용 fine-grained PAT 시크릿 **`RELEASE_TOKEN`**(Contents = Read and write, 세분화·권장),
   **[B]** 미등록 시 폴백하는 내장 `GITHUB_TOKEN`(`secrets.RELEASE_TOKEN || github.token`)에
   Settings → Actions → Workflow permissions = Read and write 토글(시크릿 불필요). 생성 문서에
   **[A] PAT 생성/시크릿 주입법**과 **[B] 토글법**을 적고, 워크플로가 시작 시 이를
   **프리플라이트로 1회 검증**(비파괴 write-프로브 — `.permissions.push` 는 role 반영이라
   신뢰 불가)하고 부재/권한 부족·이후 커밋/push 실패 시 [A]/[B] 안내를 출력함을 기술.
   가드 메시지가 여기를 링크하므로 **유일 정본 위치** — 항상 출력.
5. **버전 확인 명령** — 모든 스택 공통 `git describe --tags --abbrev=0` + 확정 도구의 dry-run:
   `semantic-release version --dry-run`(Python) · `semantic-release --dry-run`(Node) ·
   `cargo release --dry-run`(Rust) · `goreleaser release --skip-publish --snapshot`(Go) ·
   `jreleaser full-release --dry-run`(Java) · `dotnet-gitversion`(C# — 버전 계산만, 별도 릴리스
   커맨드 없음) · `sbt ci-release`(Scala — dry-run 옵션 없음, 태그 push 여부로 제어).
6. **vdev 감지 시 안내** — **감지** 시 티어는 [risk-tiers.md](../../../rules/risk-tiers.md),
   커밋 규율(1 의 메시지 본문 목록 포함)은
   [commit-discipline.md](../../../rules/commit-discipline.md) 로 defer 하고, 이 문서는 *버전·릴리스 메커니즘*만
   기술하며 프로세스 규율(승인·머지·PR) 중복 금지. **미감지** 시 릴리스 도구 실설정
   (CI 워크플로·훅)을 opt-in 으로 제안(사용자 동의 시만 생성).

### 작성 규칙

- **출처 URL 필수** — Conventional Commits·SemVer 공식 링크 + 릴리스 도구 공식 docs 링크.
- **0.x 정책 명시** — 프로젝트가 0.x 면 `major_on_zero=false` + annotated 태그를 권장 절에 기재.
- **티어·커밋 규율 emit 금지** — 승인 흐름·브랜치 전략·PR 규율은 risk-tiers defer 문구만,
  메시지 형식은 commit-discipline defer 문구만.
- **vdev 중복 생성 금지** — vdev 감지 시 `/vdev-init` 이 렌더하는 CI 워크플로·릴리스 훅
  실파일은 이 문서에서 생성 금지.
- **미확정 스택 — "확인 필요"** — 릴리스 도구·버전 파일이 불확실하면 지어내기 금지(harness-rules 4).
- **간결** — 항목당 1~3줄. 장황한 설명보다 구체적 명령/설정값.

## 공통 규율

- **출처 표기** — 리서치/스캔 근거 표기. 없으면 "출처 미확인".
- **간결** — 항목당 1-2줄. 장황한 설명보다 구체.
- **문체** — [doc-style.md](../../../rules/doc-style.md): 개조식, 다음 줄 되풀이·변경 이력 서술·장식 구조 금지.
- 문서는 사람과 에이전트 양쪽이 읽음 — 명확하고 스캔 가능하게.
