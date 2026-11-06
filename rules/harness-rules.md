# Harness Generation Rules

> 자동 주입 안 됨(risk-tiers.md 와 다름). `/harness-init`·`harness-authoring` 스킬이 실행 시점에 defer 해 읽는 SSOT.

## 안전
1. **검증→계획→미리보기→확정→쓰기.** 미리보기·확정 전 어떤 파일도 쓰기 금지.
2. **덮어쓰기 금지.** 기존 파일은 마커블록 upsert(전용 영역)만. create 는 부재 시만.
3. **harness-init 은 커밋 안 함**(/vdev 책임).
4. **모호하면 질문**(Karpathy). 프레임워크 미감지·충돌 시 사용자에게 질문.
4-1. **편입 사본 cleanup**: apply 성공 후 docs 로 편입된 중간 사본(`.harness/research/` 등)은
   `harness_scaffold.py cleanup` 으로 제거. 감사용 증거(`plan.json`·`manifest.json`·
   `critic-report.json`·`rationale.md`)는 보존. FAIL-OPEN(정리 실패는 흐름을 안 막음).
   **링크 가드(FAIL-SAFE)**: 문서 출처 링크는 편입 위치 `docs/research/` 를 가리킴, `.harness/` 참조 금지.
   cleanup 은 제거 전 docs 의 `.harness/research` 참조를 검사 — 참조가 있으면 보류 + 경고(링크 깨짐 방지).
4-2. **편입은 plan 항목**(`docs/research/*.md` `action: create`), 파일 복사 아님 — `cp`·`mv`·`rsync` 로
   `.harness/` 를 옮기면 아래 강제 지점을 전부 우회함. 규칙마다 그것을 잡는 자리(`harness_scaffold.py`):
   - `validate_plan` — `path`(쓰기에 안전하지 않은 경로 — 목록은 `_path_problem`) ·
     `harness-ref`(본문 링크가 증거 경로), 둘 다 high. 진단이라 차단은 안 함.
   - `apply_plan` — 같은 경로를 **쓰기 직전에** 거부하고 `rejected` 로 보고. 철자(`_path_problem`)와
     실제 위치(`_escapes_root` — 심링크)를 모두 봄. 거부는 그 엔트리 하나뿐, 나머지는 계속 적용.
   - `cleanup_harness` — 링크 가드(위).
   - `doctor` — 중단된 실행의 잔해. `cleanup` 이 못 보는 사각(apply 성공 후에만 돎)을 덮음.
   `dead-link` 의 `detail` 은 **원문 링크만** 실음 — 해석된 경로를 실으면 그걸 읽은 모델이 그
   자리에 파일을 만들어 `docs/<x>/.claude/…` 유령 트리가 생김. 그래서 해소는 링크 수정이지
   그 자리에 파일 만들기가 아님.
   `dead-anchor`(warn) 는 대상 문서는 있는데 `#프래그먼트`가 그 문서의 `<a id>` 에도 헤딩
   슬러그에도 없는 것 — SDS 의 `[FR-xxx](../srs/README.md#fr-xxx)` 역추적이 조용히 끊기는
   자리. 대상이 아예 없으면 `dead-link` 하나만 나감(한 원인 이중 보고 금지). 대상 본문은
   **디스크 우선**(plan 의 `create` 는 기존 파일을 안 덮으므로) 이고 전체 쓰기 엔트리만
   대신 설 수 있음(부분 액션의 `content` 는 파일이 아님). 못 읽으면 판정 안 함(FAIL-OPEN),
   `#L42`·`#L42-L51` 은 앵커가 아니라 GitHub 줄 참조라 대상 아님.
   드라이브 루트에 걸리는 링크(`\Users\x.md`·`/x.md`)와 드라이브 접두 링크(`C:/x.md`·
   드라이브-상대 `C:../x.md`)는 정규화하면 root 밖이라 **어느 쪽으로도 판정하지 않음** —
   그 읽기가 저장소 밖 파일을 열게 되므로, dead-link 보고보다 안 여는 쪽을 택함.
   의도된 잔여: 자기 `.harness/` 를 쓰는 호스트의 정상 링크가 `harness-ref` 로 걸림 · `~` 는
   확장 안 돼 `<root>/~/` 디렉터리가 생김 · 기존 파일을 가리키는 하드링크는 판정 대상 아님 ·
   Windows 예약 디바이스명(`docs/nul.txt`)은 Windows 에서만 거부(그쪽에서만 디바이스라 OS 별로
   갈림) · `doctor` 의 `research_residue` 는 `exists()` 로 판정해 "apply 가 만든 파일"과 "원래
   있던 파일"을 구분 못 함.

## 산출물
5. **.md 기본**, 실설정(bandit·CI·pre-commit·실폴더·실제 ==핀)은 항목별 opt-in.
5-1. **스킬 보조폴더**: 역할상 참조/사례가 있으면 `references/`·`examples/` 동반(YAGNI — 단순 스킬엔 미강제).
5-2. **산출물이 스스로 말하지 못하는 것만 씀** — 생성하는 모든 주석·독스트링·`.md`·룰 파일에 적용.
   문체·금지·배치 규정의 SSOT 는 [doc-style.md](doc-style.md), 여기서 복제 금지. 하네스 고유분만:
   - **주석·독스트링**: 목적과 코드에 안 드러나는 계약. 시그니처를 되풀이하는 파라미터 나열 제외.
   - 이 파일이 강제하는 스키마(SRS §번호, code-style 렌즈 블록)는 장식이 아니라 내용 — doc-style 7 의 예외.
   - **룰 파일**(`CLAUDE.md`·`.claude/rules/**`)은 지금 유효한 룰만 — 대체된 룰 금지.
   - 컴포넌트 문서의 형식 규율은
     [authoring-spec 공통 규율](../skills/harness-authoring/references/authoring-spec.md).
6. **필수 룰 5종 항상 주입**: Karpathy 4원칙 + DRY/상수 + ==버전핀 + 보안 + **reuse-first**
   ([rule-reuse-first.md](../skills/harness-authoring/references/rule-reuse-first.md)).
   **로드경로 보장** — CLAUDE.md 본문/명시 import(`.claude/rules/` 단독 금지). 앵커 `<!-- rule:<key> -->`
   (key: `karpathy`·`dry-constants`·`version-pinning`·`security`·`reuse-first`)는 **claude-md 템플릿 소유** →
   baseline 마커블록에서 각 룰 슬롯 앞에 배치. 룰 reference 본문 파일엔 앵커 금지(중복).
7. **중복 생성 금지**: name+description 으로 기능 중복 확인.
7-1. **SSOT 축은 따로 지목** — 요구·설계 **텍스트**는 저장소 문서(`docs/srs/`·`docs/sds/`)에,
   **상태·승인·담당자**는 외부 트래커에 위치. 축마다 정본은 하나만 지목. 양방향 자동 머지는 금지.
8. **기술문서(분류별 폴더)**: `docs/README.md`(전체 인덱스·마지막) · `docs/srs/`(`README.md` = 공통
   절 + 비기능 요구사항 + 영역 인덱스, `<area>.md` = 기능 요구사항·가장 먼저) · `docs/sds/`(구조 + **Mermaid 필수**; 컴포넌트가
   경계(프로세스/오리진/호스트/인증)를 넘어 통신하면 **통합 지점 계약** 절 포함) ·
   `docs/code-style/`(스택별 `<stack>.md`, 코드 스니펫 제외, 툴체인 설정 한 세트) ·
   `docs/research/`(편입, 출처 링크) · `docs/onboarding/`(실행/디버그 + 주요 문서 링크·마지막) ·
   `docs/verification/performance.md`(스택별 성능 SSOT — N+1·프로파일러·쿼리플랜·API 부하, 확정 스택만·빈 절 금지) ·
   `docs/verification/integration.md`(스택별 통합 검증 SSOT — 웹=Playwright·비웹=human-in-the-loop, 확정 스택만·빈 절 금지).
   진입 문서는 `README.md`. 구조적 컨벤션은 룰, 행위적 스타일은 문서 — **한 사실 한 곳**.
   **모든 문서는 참조 출처를 링크로**.
8-1. **SRS 범위 명확화 게이트(추측 금지)**: SRS 산출물 선택 시 리서치·SRS 작성
   **전에** 프롬프트를 파싱해 개발 범위 확정. SRS 필수 슬롯(목적·목표/비목표·핵심 기능 요구사항·
   대상 사용자/시나리오·핵심 제약)에서 **공백 + 모호한 항목 전부** ask the user (structured choice) 로 질문 —
   **모호 = 측정 불가·복수 해석 가능·범위 불분명**(예: "빠르게"·"사용자 친화적"). **측정 가능하고
   단일 해석이 될 때까지** 질문하되 이미 명확한 건 되묻지 않음(모호함 = 요구 분석 미완 신호 —
   SRS 단계에서 해소). 추가로 **분류 축**(도메인 등 1차, 사용자권한/하위영역 등 2차)과 **깊이(2~3차)**
   확정 — 적용 축을 질문하고, 미적용 축은 SRS 에서 삭제 말고 "해당 없음 — 사유"로 유지(누락과 구분 —
   9-2 와 동형). 질문 후에도 미상이면 SRS 에 "확인 필요" 명시(지어내기 금지·rule 4). 산출 **범위
   요약(scope summary)** 이 research·rationale·SRS 의 단일 입력원.
   **SRS 의 독자는 코드를 쓰지 않는 사람이기도 함** → 이 게이트가 용어도 확정: 프롬프트가 한 대상을
   두 이름으로 부르면("로그인"·"사인인") 복수 해석이므로 어느 쪽이 정식 용어인지 질문, 모든 도메인
   용어·약어는 뜻과 함께 범위 요약에 넣어 SRS 용어집의 입력으로 삼음. 요구는 사용자나 비즈니스가
   관찰하는 것을 말하고 구현은 말하지 않음(구현은 SDS 몫). 작성 절반 — 용어집 절·한 대상 한 용어 —
   은 `tech-doc-guide.md` 의 SRS 절. **brownfield 도 이 게이트를
   통과함** — 다만 골격만 받고 미해결 슬롯은 "확인 필요"로 남음, 코드 분석은 범위의 입력이지 요구의
   출처가 아님. **FR 을 기존 코드에서 역산 금지**: 코드는 무엇을 하는가지 누가 무엇을 원했는가가
   아니므로, 동작에서 추론한 FR 은 요구의 옷을 입은 현재 동작 — 룰 4 를 지킨 것이 아니라 어긴 것.
   요구는 사람이 말할 때 증분으로 유입.
8-2. **기술문서는 wiki 노드**: 생성하는 모든 기술문서(rule 8 의 `docs/` 분류 — wiki 루트 밖이라 노드가
   될 수 없는 `.claude/rules/<framework>-conventions.md` 는 제외)는 필수 YAML front matter
   (`wiki_id`·`title`)로 시작(id 파생 규칙 SSOT = [wiki-init](../skills/wiki-init/SKILL.md), 여기서
   복제 금지). 한 파일 한 개념: ~400줄 초과 또는 두 주제면 분할 + `related` 로 연결. rule 7(SSOT)의
   문서판 — 한 사실은 한 노드, 나머지는 링크. **프로젝트에 wiki 설치 여부와 무관하게** front matter
   작성: 없으면 비활성 메타데이터일 뿐이고, `/harness-init`↔`/wiki-init` 순서 의존이 사라짐.
   `used_by`·`defects` 는 절대 금지 — `depends_on`·`affects` 에서 생성되는 필드라, 담은 템플릿은
   소비자의 첫 커밋을 깨뜨림.
9. **커맨드 미생성**: 어떤 산출물도 `.claude/commands/` 에 생성 금지(revfactory 정렬).

## 관점별 컨벤션·베스트 프랙티스 (perspective lenses)

9-1. **관점(렌즈)별 관심사 체크리스트(누락 금지·열린 목록)**: 감지 스택에 대해 researcher/
   code-analyzer 는 아래 *관점 렌즈*를 렌즈별 *축*으로 **전수 검토**해 베스트 프랙티스·안티패턴 산출
   (언어/프레임워크 무관). 렌즈·축은 닫힌 floor 가 아니라 **흔한 출발점** — researcher 가 스택 특성상
   추가. **렌즈 자체도 스택에 실재할 때만 적용**(9-2 확장 — UI 없는 헤드리스 백엔드에 UX/접근성/국제화
   렌즈 강제 금지, 단일 정적 페이지에 계층 횡단 렌즈 강제 금지).
   - **정확성(correctness)** — 타입 안전 · 널/옵셔널 처리 · 경계·예외 케이스 · 불변식 강제 ·
     언어별 footgun 회피(부동소수·`==`/`===`·타임존 등).
   - **운영(operational)** — 에러/예외 처리 · 로깅(디버깅 지향: 레벨 규칙·디버깅 컨텍스트·구조적/
     검색가능·시크릿/PII 금지) · 설정·env(비시크릿) · 관측성(메트릭/트레이싱) · 헬스체크/레디니스 ·
     그레이스풀 셧다운 · 재시도/타임아웃·서킷브레이커 · 데이터 마이그레이션/스키마 진화 · rate limiting.
   - **보안(security)** — 인증 · 인가 · 시크릿 관리(코드/로그/트랜스크립트 노출 금지) · 입력 검증·
     새니타이징(서버측 강제) · 의존성 취약점 · 전송/저장 암호화 · 웹 취약점 방어(XSS·CSRF·injection) ·
     최소권한. 보편 원칙은 baseline `security-rule` 로 defer — 여기선 **스택별 구체 축**만.
   - **성능(코딩 패턴)** — N+1 회피(eager/batch) · 캐싱 전략 · 페이지네이션 · 인덱싱 · 번들 분할/코드
     스플리팅/지연 로딩(FE) · 메모이제이션 · 커넥션 풀. **"짜는 법"만** — 성능 *검증 도구*는
     `docs/verification/performance.md`(성능 SSOT)로 defer(중복 금지).
   - **UX/상호작용(UI 스택만)** — 중복 제출·재클릭 방지 · 로딩/비활성/스켈레톤 상태 · 낙관적 업데이트 ·
     에러/빈/로딩 상태 처리 · 폼 검증 **피드백**(사용자에게 보이는 방식) · 반응형.
   - **접근성(a11y, UI 스택만)** — 시맨틱 마크업 · 키보드 내비게이션·포커스 관리 · ARIA · 색 대비 ·
     스크린리더(WCAG 정렬).
   - **국제화(i18n, 사용자 대면 스택)** — 문자열 외부화 · 로캘/포맷(날짜·숫자·통화) · 복수형 ·
     RTL · 타임존. (기존 UX 렌즈의 i18n 축을 독립 렌즈로 승격.)
   - **유지보수성(maintainability)** — 모듈화·경계 · 테스트 용이성 · DRY · 명명 일관 · 문서화 ·
     복잡도 관리.
   - **계층 횡단(coherence, 다계층 스택만)** — 같은 관심사를 여러 계층에서 **일관 처리**: 멱등성(UI
     방지 + 서버 dedup) · 검증(클라 UX + 서버 강제) · 인증(클라 토큰 취급 + 서버 검증) · 에러 계약
     (서버 shape → 클라 처리) · 데이터 일관성/트랜잭션 경계. **일관성 규율만** — 구체 통신 계약은
     `docs/sds` 통합 지점으로 defer(중복 금지).
   **축의 다면성(중복 아님)**: 한 관심사가 여러 렌즈에 나타나되 **다른 면**을 봄 — 예: *검증* =
   UX(피드백 방식)·보안(서버 강제/새니타이즈)·계층 횡단(클라↔서버 일관성); *인증* = 보안(메커니즘)·
   계층 횡단(클라 취급↔서버 검증 배치). 같은 사실 복제가 아니라 면 분리 → 각 렌즈에 해당 면만 기재.
   **정확성·유지보수성은 축 중복이 아니라 전 렌즈 공통 기반**(여러 관점에 걸치는 관심사가 아니라,
   스택 전반의 코드 품질을 다루는 별도 렌즈).
9-2. **emit 은 증거 기반**: 커버리지는 필수이되, 각 렌즈·축은 그 스택에 **관심사가 실재할 때만 emit**
   (정적 사이트에 헬스체크/셧다운 강제 금지, 헤드리스 백엔드에 UX/접근성/국제화 렌즈 강제 금지 —
   사용자 대면 없는 스택엔 i18n 미적용).
   적용성 **불확실** 시 지어내지 말고 Step 6 미리보기에서 질문(과생성 방지 — FAIL-OPEN 은 "스킵+질문"
   방향). emit 기준은 "모든 렌즈 존재"가 아니라 "**적용 렌즈가 covered 이거나 스킵 사유가 있음**".
9-3. **directive 는 룰, 살은 문서**: 관점별 directive(1~3줄 지시)는 `.claude/rules/
   <framework>-conventions.md` 의 `<!-- ops-conventions -->` 앵커 절(렌즈 무관 공용 앵커 — 이름은
   하위호환 유지)에, 표준 상세·매핑·안티패턴·예제·**출처 URL(SSOT)**·대안은 `docs/code-style/<stack>.md`
   "관점 관심사" 섹션(렌즈별 소섹션)에. 룰은 문서를 링크하고 같은 사실 복제 금지(한 사실 한 곳).
9-4. **표준 선택(단정 회피)**: brownfield 는 code-analyzer 가 코드에서 쓰는 표준을 감지해 명시.
   greenfield/미확정은 researcher 가 **현재 권장 최신 표준을 자동 채택(묻지 않음)** 하되, 구체
   표준명은 **문서에** "권장(변경 가능)+출처+대안"으로만, 룰엔 카테고리 directive 만.
9-5. **보안 렌즈 승격 경로**: 보안 렌즈의 강제력이 필요한 축(시크릿·인증/인가·입력 검증)은 directive
   한 줄로 끝내지 말고, harness-init Step 1 의 **실설정 opt-in**(secret scanner·linter) 제안(동의 시만).
   "정책" 강제 착시 금지 — 진짜 강제는 탐지 도구로.
9-6. **모든 확정 스택이 컨벤션 대상(reuse 아티팩트 ≠ 스택)**: reconcile(10-1)로 확정된 *모든* 스택이
   컨벤션 대상(구조/상세 SSOT 분리는 9-3 따름 — 여기서 복제 금지). 특히 인프라(DB·캐시·큐·컨테이너/
   이미지·CI/CD·IaC·클라우드)는 reuse 아티팩트로만 끝내기 쉬우니, 컨벤션(BP·안티패턴·관점 축)이
   **실재하면** 스택으로 승격(없으면 reuse 후보로만 — 9-2 증거 기반).

## 다중 에이전트 / 비판
10. **리서치는 서브에이전트 fan-out** — Dispatch subagent `harness-researcher`
    (+ 브라운필드 시 `harness-code-analyzer`) 병렬 디스패치·팬인.
    Claude Code 에서 agent teams(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`)가 켜졌으면 팀이 대신 돌며 교차대화 가능(옵션).
    빌드가 제공하지 않는 도구로 팀을 흉내 내기 금지. 네트워크/디스패치 실패는 FAIL-OPEN(경고 + 선택), 지어내기 금지.
10-1. **스택 인벤토리 reconcile(동결 전 수렴 — 누락 방지)**: `stack_map` 은 인터뷰에서 *잠정* 확정,
    리서치(researcher 자율확장·기성솔루션·스택 호환성 매트릭스)가 드러낸 (인프라 포함) 스택을
    authoring **전에** `stack_map` 에 병합. 컨벤션이 실재하는 스택(인프라가 특히 누락되기 쉬움)은
    컨벤션 대상으로 승격(9-6), 새로 승격된 스택은 1차 fan-out 에서 (계층,스택)으로 디스패치되지
    않았으므로 **타깃 후속 리서치**(해당 스택 관점 렌즈 전수 + **1차 호환성 매트릭스(천장 제약) 주입** —
    조각이 전역 뷰 없이 독립 최신을 골라 앵커 위반을 재도입하지 않게, 12-2) 실행해 컨벤션을 채움.
    스택 집합이 **안정될 때까지 반복**(보통 1회). 수렴 후 **승격 스택 포함 전역 호환성 매트릭스 재통합**,
    런타임 조합 호환 **재검증은 critic version-compat(B)** 로 defer(reconcile 은 병합·승격만 — 재검증
    barrier 겸직 금지). **추측으로 스택 확장 금지** — 발견 근거가 있는 것만. 승격/기각 결정·사유는
    authoring 이 `docs/sds/README.md` 에 한 줄씩 기록(미리보기에서 다른 산출물과 함께 사용자 확정) —
    버전관리되는 결정 출구(rationale 중복 아님).
10-2. **fan-in 계약·부분 실패·상충(교차대화 off 기본 모드)**:
    - **fan-in 은 파일 채널**: 각 서브에이전트는 `.harness/research/<agent>_<topic>.md` 에 저장하고
      (researcher 도 code-analyzer 와 대칭으로 저장 경로를 자기 정의에 보유), 리더 `Read` 팬인 +
      authoring 소비가 이 파일을 읽음. 리더는 디스패치 프롬프트에 저장 경로와 **유니크 `<topic>`** 명시
      (재디스패치는 신규 접미사 — 동일 파일명 덮어쓰기로 결과 유실 금지).
    - **부분 실패 = 결측(FAIL-OPEN 확장)**: rule 10 의 FAIL-OPEN 은 *전체* 실패만의 것이 아님. 일부
      agent 만 성공/사망(`null`·빈 파일·"표본 부족")한 부분 상태는 **결측으로 기록**해 Step 6 미리보기에
      "needs confirmation" 으로 노출(성공분만 조용히 진행 금지). critic 은 산출물만 보므로 보고 자체가
      실패한 결측은 못 잡음 — 방어는 디스패치 시점에만 가능.
    - **상충 조정**: researcher 권장 ↔ code-analyzer 코드 현실이 **양쪽 근거로** 충돌하면 rationale 에
      명시 기록 + brownfield 우선순위(안티패턴이면 개선, 아니면 코드 존중)로 잠정 판정, Step 6 사용자
      확정. authoring 의 "라이브러리 단정 금지"는 *근거 없음* 만 흡수하지 이 상충을 대신 해결하지 않음.
11. **사유 작성**: research 종합 후 `.harness/rationale.md`(산출물별 생성 근거·채택 패턴·reuse 권고·출처).
12. **경량 비판**: `validate`(결정적 구조) → `harness-critic`(품질·정합성·reuse 위반·커맨드 미생성).
    재작성 최대 2회, 잔여는 "미해결"로 미리보기/보고에 명시(차단 금지).
12-1. **버전 호환성(`version-compat`) — 두 축**: (a) **설정 작성 정합** — 툴체인을 한 세트로 보고
    감지된 실제 버전의 공식 작성법과 산출물 정합성 검증(빌드↔설정, 예: `tsc -b`↔references).
    (b) **런타임 조합 호환** — 한 런타임에 함께 올라가는 구성요소(앱 프레임워크 ↔ 플러그인/스타터/
    엔진/이미지)가 **함께 GA-호환되는 최신 집합**인지, 추천한 기성 아티팩트가 가정한 기능을
    **실제로 제공**하는지. **만들 때**는 설정을 추론하지 말고 감지된 프레임워크의 **공식 스캐폴더
    출력을 복제**해 baseline 으로 삼음(reuse-first 의 설정판). researcher 는 설정 방법을 버전별로
    수집하고 프레임워크 특성상 필요한 항목을 자율 확장.
12-2. **최신 ≠ 독립 최신(천장 우선)**: **버전을 선택할 때**(greenfield·미확정·의도적 업그레이드)
    researcher 는 각 구성요소의 독립 최신을 따로 고르지 않음. 플랫폼 major 를 가두는 **앵커(천장)
    의존성**을 식별하고 그 앵커가 **GA 로 지원하는** 최신 버전 집합으로 선택(함께 GA-호환 안 되면 가장
    늦게 따라온 것에 맞춰 내림; 프리릴리스·미배포 의존에 본체를 맞추지 않음). 산출에 **스택 호환성
    매트릭스**(구성요소→버전→천장 제약→출처) 기록. 9-4 의 "최신 표준 자동 채택"은 이 천장 제약 안에서만
    적용. (brownfield 의 *검출된* 버전 조합이 GA-호환되는지의 점검은 선택이 아니라 검출이므로 12-1(b)
    담당 — `harness-researcher` 절차 7-1·critique-guide(B)는 이 selection 부분을 인용.)

## 버전/릴리스 컨벤션 리서치

13. **릴리스 도구 리서치(감지 스택별)**: Step 2 리서치 시 감지 스택의 표준 릴리스 도구를 조사해
    `vdev-config.versioning.release_tool`·`version_files` 후보 제안.
    스택별 기본 후보:
    - Python → `python-semantic-release`
    - Node/TypeScript → `semantic-release`
    - Java → `jreleaser`
    - C# → `gitversion`
    - Rust → `cargo-release`
    - Scala → `sbt-ci-release`
    - Go → `goreleaser`
    - 기타 → researcher 가 생태계 표준 조사 후 근거와 함께 제안
    (스택 부재·불확실 시 지어내지 말고 "확인 필요" — rule 4.)
13-1. **`commit-versioning-guide` 생성(기술문서)**: Step 4 authoring 에서
    `docs/operations/commit-versioning-guide.md` 생성. 내용:
    - Conventional Commits + SemVer 기본 설명(출처 URL 필수)
    - 감지 스택의 릴리스 도구 설정(버전 파일·changelog·CI 훅 — 스택 미확정이면 "확인 필요")
    - **0.x 프로젝트** 권장: `major_on_zero=false` + annotated 태그(우발적 1.0.0 승격 방지)
    - 버전 확인 명령(예: `git describe --tags`, 도구별 dry-run 명령)
    - **티어는 [risk-tiers.md](risk-tiers.md), 메시지 형식은 [commit-discipline.md](commit-discipline.md)
      로 defer** — 여기서 어느 쪽도 직접 emit 금지.
    문서 출처는 `docs/research/` 로 링크(`.harness/` 경로 참조 금지, harness-rules 4-1·8).
13-2. **opt-in 분기(vdev 감지 여부)**:
    - **vdev 미감지** — 릴리스 도구 설정(CI 워크플로·훅 등)을 opt-in 제안(동의 시에만 실설정 파일
      생성 — rule 5 실설정 opt-in 동일).
    - **vdev 감지** — `/vdev-init` 이 `vdev-config.contract_test` 등 워크플로를 렌더하므로 릴리스 도구
      실설정 중복 생성 금지. `commit-versioning-guide` 문서 생성은 vdev 감지 여부 무관하게 항상 진행
      (코드스타일+컨벤션 문서 범위 — rule 14 의 defer 대상 아님).

## vdev 공존
14. **vdev 감지(.claude/vway-kit/config/vdev-config.yaml)** 시 프로세스·머지·PR 규율은
    [risk-tiers.md](risk-tiers.md), 커밋 메시지 규율은 [commit-discipline.md](commit-discipline.md)
    로 defer. 하네스는 코드스타일+프레임워크 컨벤션만 emit.
14-1. **사전검사 도구·폴더구조는 SSOT 가이드(강제는 vdev 몫)**: 하네스는 `docs/code-style/<stack>.md`
    툴체인 설정 섹션에 언어/스택별 사전검사 도구 목록(lint/format/typecheck/import_lint/security/test runner)과
    tests/ 폴더 구조를 SSOT 로 기록 — `/vdev-init` 이 `vdev-config.modules[].checks` 초안 작성 시 참조.
    단 하네스는 *가이드(기술 스택 정보)* 만, 실제 게이트 강제(checks 실행·차단)는 vdev 몫(rule 14 defer
    연장). `harness_scaffold.py` 의 stack_map/스캐폴드 로직은 여기서 변경 금지.
15. **settings.json 훅 미변경**(게이트 아님). 보안은 워크플로/pre-commit 파일로만.
