---
name: harness-init
description: 프로젝트에 맞는 AI 하네스(CLAUDE.md·룰·에이전트·기술문서)를 리서치 기반으로 생성하는 마법사
disable-model-invocation: true
---

# Harness-Init — AI 하네스 생성 마법사

대상 프로젝트에 맞는 Claude Code 하네스를 다중 에이전트로 생성. 산출물은 **.md 기본**, 실설정(보안
스캐너·CI·폴더 스캐폴딩 등)은 **질문 후 동의 시에만** 적용. **커맨드 생성 금지.**
**규율 SSOT**: [harness-rules.md](../../rules/harness-rules.md) — 읽고 따름(중복 금지).

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## 경로
```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
PLUGIN="${CLAUDE_PLUGIN_ROOT}"
HARNESS_DIR="${ROOT}/.claude/vway-kit/.harness"   # 증거(research/rationale/plan/critic/manifest), gitignored
```
각 Bash 호출은 새 셸임 — 뒤의 블록마다 이 대입을 다시 열지 않으면 거기서 이 변수들이 빔.
증거는 vway-kit 규약대로 `.claude/vway-kit/.harness/` 한 곳에 집중(루트 분산 금지):
`research/<agent>_<topic>.md` · `rationale.md` · `plan.json` · `critic-report.json` · `manifest.json`.
첫 쓰기 전 `.gitignore` 에 `.claude/vway-kit/.harness/` **멱등 추가**(이미 있으면 skip).
harness-init 은 vdev 와 독립이므로 자기 증거는 자기가 ignore(vdev-init 의존 금지).
쓰기는 `${ROOT}` 아래만 — `${PLUGIN}` 은 읽기 전용.

## Step 0 — 검증/감지 (스크립트)
```bash
python3 "${PLUGIN}/scripts/harness_scaffold.py" detect --root "${ROOT}"
python3 "${PLUGIN}/scripts/harness_scaffold.py" doctor --root "${ROOT}"
```
`detect` 결과(state/frameworks/existing)를 사용자에게 **표로** 제시. vdev 설치
(.claude/vway-kit/config/vdev-config.yaml) 여부도 보고.

`doctor` = **중단된 이전 실행의 잔해** 진단(보고 항목·판정 근거 SSOT = `harness_scaffold.py`
의 `doctor` 독스트링, 여기서 복제 금지). **`verdict: dirty` 면 진행 전에 항목별로 사용자에게
보고하고 「수습 후 재시작 / 그대로 진행」을 ask the user (structured choice) 로 확정** — 재실행이 스스로
낫지 않으므로(Step 7 의 `create` 가 반쯤 쓰인 파일을 `exists()` 로 보고 `conflicts` 에 넣고
넘어감) 사람의 판단이 필요. 수습도 사람이 함 — 증거 메타(`plan.json`·`manifest.json`)
삭제 금지, 재실행 입력.

## Step 1 — 인터뷰 (ask the user, 최소하되 범위는 명확히)
0. **개발 범위 명확화 (SRS 범위 명확화 게이트 — 추측 금지)**: SRS 산출물이 선택되면(brownfield 도 같음),
   **Step 2 리서치·Step 4 SRS 작성 전에** 받은 프롬프트를 파싱해 개발 범위 확정.
   **SRS 필수 슬롯의 공백 + 모호한 항목 전부** ask the user (structured choice) 로 질문 — **모호 = 측정 불가·복수
   해석·범위 불분명**(예: "빠르게"·"사용자 친화적"). **측정 가능하고 단일 해석이 될 때까지** 질문하되
   이미 명확한 건 되묻지 않음(과생성·심문 금지). 필수 슬롯 = 목적 · 목표/비목표(YAGNI 경계) ·
   핵심 기능 요구사항 · 대상 사용자/시나리오 · 핵심 제약(규모·성능·보안·배포 환경). 추가로 **분류 축**
   (도메인 1차·사용자권한/하위영역 2차)과 **깊이(2~3차)** 도 확정(적용 안 되는 축은 SRS 에
   "해당 없음 — 사유"로 유지). **용어**도 확정 — 프롬프트가 한 대상을 두 이름으로 부르면
   ("로그인"·"사인인") 모호하므로 정식 용어를 질문하고, 모든 도메인 용어·약어는 뜻과 함께 범위 요약에
   넣어 SRS 용어집의 입력으로 삼음. 상세 규율·구조는 harness-rules 8-1·`tech-doc-guide.md` SRS 절·
   `srs.template.md`.
   - **게이트**: 범위 공백·모호가 남은 채로 Step 2·Step 4 진행 금지. 질문 후에도 미상인 슬롯은
     SRS 에 **"확인 필요" 명시**, 지어내기 절대 금지(harness-rules 4·8-1).
   - 산출 = **범위 요약(scope summary)** → research·rationale·SRS 의 단일 입력원(downstream 단일 출처).
   - **brownfield 도 이 게이트를 통과함** — 다만 골격만 받고 미해결 슬롯은 "확인 필요"로 남음.
     코드 분석은 범위의 입력이지 요구의 출처가 아님(harness-rules 8-1) — 코드로 해소되지 않는
     의도(목표/비목표 등)만 선택적으로 질문.
1. **주 개발 언어 확정(hard gate, harness-rules 참고)**: ask the user (structured choice) 로 주 개발 언어 반드시
   확정(감지값 무관 항상 질문). 감지 언어가 있으면 첫 옵션(권장), 멀티/미감지면 후보 나열. 감지값과
   사용자 선택이 다르면 **사용자 선택 우선**. **주 언어 ≠ 전 계층 동일 언어** — 프로젝트를 계층
   (프런트/백/기타)으로 나누고, 각 계층에서 **더 프로덕션 레디·표준에 가까운 스택을 권장 1순위**로
   제시(가능 시 research 근거), **"전 계층 동일 vs 계층별 분리"를 ask the user (structured choice) 로 확인**.
   결과 = **계층별 언어/스택 맵**(잠정 — Step 2.5 에서 리서치 발견분으로 reconcile 해 **동결**; 사용자
   사인오프는 Step 6; downstream 단일 출처). 아직 안 드러난 스택을 여기서 추측해 채우기 금지(인프라가
   특히 그러함 — 모르는 채 일찍 잠그면 누락; 리서치 후 reconcile 에서 충전, harness-rules 10-1).
2. 감지 프레임워크/버전 확인(틀리면 정정, 미감지면 입력 요청).
3. 생성 산출물 선택: CLAUDE.md / 룰(baseline 5종 + 프레임워크 컨벤션) / skills / agents /
   기술문서(SRS·SDS·스택별 code-style·research·onboarding·**성능/통합 SSOT 문서(`docs/verification/performance.md`·`docs/verification/integration.md`)**, 분류별 폴더). **커맨드 선택지 없음.**
4. **실설정 opt-in**: 보안 스캐너 설치·CI 추가·실폴더 스캐폴딩·실제 버전핀 — 각각 질문.
   보안 렌즈의 시크릿·인증/인가·입력검증 축은 directive 만으로 끝내지 말고 스캐너 opt-in 을 함께 제안(9-5).
5. 브라운필드 충돌(existing) 항목별: 스킵 / 사용자선택.

## Step 1.5 — 증분 렌즈 갭 채우기 (통합 갭 모델)
`docs/code-style/<stack>.md` 는 first-run/재실행 구분 없이 **갭 = 적용 렌즈 − present 렌즈**를 항상
충전(상세는 아래 스펙 §5):
1. **로컬 스캔(토큰 0)**:
   ```bash
   python3 "${PLUGIN}/scripts/harness_scaffold.py" scan-lenses --root "${ROOT}"
   ```
   `docs/code-style/*.md` 를 스택별 `{stack, path, state, present}` 로 보고. `state`: `lensed`(이 스택의
   렌즈 마커가 하나 이상 존재)·`flat`(베스트 프랙티스 헤딩은 있으나 마커 없음 — 마이그레이션 대상)·
   `nonstandard`(그 헤딩 자체가 없음 — **스킵+경고**, 추측 금지). 스캔 결과에 아예 없는 스택(문서 파일
   부재)은 "없음"으로 간주해 Step 4 의 기존 `create` 경로(템플릿, 렌즈 블록 포함)로 처리.
2. **적용 렌즈 판정(경량)**: 리더가 스택 성격으로 harness-rules 9-1/9-2 의 9렌즈(정확성·운영·보안·
   성능·UX·접근성·국제화·유지보수성·계층 횡단) 중 적용분을 인라인 판정(UI 스택→UX·접근성·국제화
   포함, headless 백엔드→제외 등). **web research 아님** — 비용은 4의 내용 채우기에만 사용. 갭 = 적용
   렌즈 − present.
3. **스코핑 질문(research 전 · 토큰 게이트)**: ask the user (multi-select) 로 갭을 표로 제시해 확정.
   `flat` 은 **스택 단위**(적용 렌즈 전부, all-or-nothing — 부분 교체 시 나머지 렌즈를 다루던 옛
   프로즈가 대체 없이 사라짐), `lensed` 는 **렌즈 단위**(기본=빠진 렌즈, 기존 렌즈 refresh 도 선택
   가능)로 선택지 분리. 승인분만 다음 단계로 전달.
4. **스코프드 dispatch**: 승인된 `(stack, lens)` 만 Step 2 의 harness-researcher/harness-code-analyzer 로
   보내 렌즈 body 생성(미승인 렌즈는 research·쓰기 모두 스킵 — 토큰 절약).
5. **적용**: Step 4 plan 에 `lens_upsert` entry(`{path, action:"lens_upsert", stack, mode, lenses:[{key,
   body}]}`) 추가 — `lensed`=`additive`(빠진 렌즈 블록만 9-1 순서 자리에 insert, 기존 블록 무접촉),
   `flat`=`replace_section`(`## 베스트 프랙티스` 섹션 통째를 렌즈 블록 구조로 교체 — 옛 자유산문은 git
   히스토리에 잔존). Step 6 preview→confirm 후 Step 7 apply, 교체 검토는 커밋 시 git diff 로.


## Step 2 — 리서치 (서브에이전트 fan-out, 격리)
**표준**: Dispatch subagent `harness-researcher`(웹 컨벤션·BP·안티패턴·무료 기성솔루션) + 브라운필드면
Dispatch subagent `harness-code-analyzer`(코드베이스 실제 컨벤션·안티패턴·손수구현) 를 **병렬 서브에이전트로 디스패치**.
각 서브에이전트는 `.harness/research/<agent>_<topic>.md` 에 저장하고, 리더가 `Read` 로 팬인해 종합.
**리더는 디스패치 프롬프트에 저장 경로와 유니크 `<topic>` 명시**(재디스패치는 신규 접미사 — 동일
파일명 덮어쓰기로 결과 유실 방지; researcher 도 code-analyzer 와 대칭으로 저장 경로 보유, harness-rules 10-2).
- **범위 주입**: SRS 를 생성하면 Step 1-0 의 **범위 요약(scope summary)** 을 디스패치 입력에 포함해
  리서치를 실제 요구사항에 한정(범위를 추측으로 확장 금지 — 미상 슬롯은 "확인 필요"로 둔 채 조사).
- **관점 렌즈 주입**: 리서치 디스패치 시 harness-rules 9-1 관점 렌즈 택소노미(정확성·운영·보안·성능·
  UX·접근성·국제화·유지보수성·계층 횡단)와 **계층별 언어/스택 맵**을 `lenses` 로 전달해, 각 (계층,스택)에서 **적용 렌즈별**
  BP·축의 최신 표준·출처·대안·적용성을 조사하게 함(9-2~9-4 — 렌즈가 실재할 때만). **code-style 렌즈
  문서의 갭은 Step 1.5 에서 스코핑된 `(stack,lens)` 집합만 대상**(적용 렌즈 전량 재조사 아님 — first-run
  은 present=∅ 라 갭=전부여서 결과적으로 기존 동작과 동일).
- **버전/릴리스 도구 리서치**: 감지 스택의 표준 릴리스 도구(`release_tool`)·`version_files`·0.x 정책 조사(harness-rules 13·13-1).
- **성능·통합 차원 주입**: Step 2.5 reconcile 로 스택 확정 후, harness-researcher 재디스패치 시 확정
  `stack_map` 을 함께 전달해 절차 9(성능 SSOT·통합 검증 SSOT) 조사 지시.
  조사 결과는 `.harness/research/` 에 저장하고 Step 4 authoring 에서 소비.
- **교차대화(옵션)**: Claude Code 에서 agent teams(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`)가 켜졌으면
  팀이 대신 돌며 교차대화 가능(code-analyzer "손수구현 X 발견" → researcher "무료 대체 조사"). 없으면
  교차대화 없이 병렬 디스패치 → 팬인으로 동작(빌드가 제공하지 않는 도구로 팀을 흉내 내기 금지).
- **FAIL-OPEN(전체 실패)**: 네트워크/디스패치 실패 시 지어내지 말고 경고 + 「최소 일반구조로 진행 / 중단」 선택.
- **부분 실패 감지**: 디스패치한 각 (agent,topic)의 반환·저장 파일 점검 — `null`·빈 파일·"표본 부족" 은
  **결측으로 기록**하고 해당 (계층,스택)·산출물을 Step 6 미리보기에 **"needs confirmation"** 으로 노출
  (성공분만 조용히 진행 금지 — critic 은 산출물만 보므로 못 잡음, harness-rules 10-2).

## Step 2.5 — 스택 인벤토리 reconcile (동결 전 수렴, harness-rules 10-1)
리서치가 드러낸 스택(researcher 자율확장·기성솔루션 후보·스택 호환성 매트릭스 — **인프라 포함**)을
Step 1 의 *잠정* stack_map 에 병합. 컨벤션(BP·안티패턴·관점 축)이 실재하는 스택은 컨벤션 대상으로
**승격**(reuse 아티팩트로만 끝내지 않음 — 9-6). **새로 승격된 스택은 1차 fan-out 에서 (계층,스택)으로
디스패치되지 않았으므로**, 그 스택만 골라 **타깃 후속 리서치**(researcher 재디스패치, 해당 스택 관점 렌즈
전수 + **1차 호환성 매트릭스(앵커·천장 제약) 주입** — 조각 researcher 가 전역 뷰 없이 독립 최신을 골라
앵커 위반을 재도입하지 않게, 12-2) 실행해 컨벤션 충전. 스택 집합이 **안정될 때까지 반복**(새 승격이
없으면 종료 — 보통 1회). **수렴 후 승격 스택 포함 전역 호환성 매트릭스 재통합**, 런타임 조합 호환
재검증은 critic version-compat(B, Step 5)로 defer(2.5 는 스택 병합·승격만 — 재검증 barrier 겸직 금지,
harness-rules 10-1).
추측으로 스택 확장 금지(발견 근거만, FAIL-OPEN 은 "스킵+질문"). 승격/기각 결정·사유는
**authoring(Step 4)이** `docs/sds/README.md` 에 한 줄씩 draft 하고, 다른 산출물과 함께
Step 6 미리보기에서 사용자 확정(draft@4 → confirm@6 → write@7; rationale 중복 아님).

## Step 3 — 사유 작성 (rationale)
detect + research + **범위 요약(Step 1-0)** 을 종합해 `${HARNESS_DIR}/rationale.md` 작성: 도메인 분석, **산출물별 생성 사유**,
채택 패턴, BP/안티패턴 요약, **적용 렌즈별 채택 표준+출처+적용성(emit/스킵 사유 포함)**,
**reuse-before-build 권고**(무료·상용가능, 유료 제외), 출처.
**상충 조정(교차대화 off 기본)**: researcher "X 권장" ↔ code-analyzer "코드는 anti-X" 처럼 근거가 양쪽에
있는 상충은 rationale 에 **명시 기록**하고, brownfield 우선순위(안티패턴이면 개선 권장, 아니면 코드 현실
존중)로 잠정 판정 후 Step 6 에서 사용자 확정(조용히 한쪽 흡수 금지, harness-rules 10-2).

## Step 4 — 생성 (authoring 스킬 + scaffold)
컨벤션 대상은 **Step 2.5 reconcile 로 확정된 스택 집합 전체**(승격 인프라 포함) — 초기 stack_map 아님.
각 스택의 구조/상세 컨벤션은 9-3 분리대로 룰·`docs/code-style/<stack>.md` 양쪽에 충전.
1. Invoke skill `harness-authoring` — templates/ 를 research+rationale+references 로 충전.
   - 필수 룰 5블록(`../harness-authoring/references/karpathy-principles.md`·
     `rule-dry-constants.md`·`rule-version-pinning.md`·`security-rule.md`·`rule-reuse-first.md`,
     모두 그 폴더)을 CLAUDE.md `harness:baseline` 블록에 주입(각 룰 앵커 `<!-- rule:<key> -->` 보존).
   - 기술문서를 분류별 폴더로 충전. **SRS 는 범위 요약(Step 1-0)을 SSOT 로** 채우고 미상 슬롯은
     "확인 필요"로 유지(research 로 메우되 추측 금지). (SRS→research 편입→SDS(Mermaid)→스택별
     code-style→onboarding→docs/README 순, 출처 링크). research 는 `.harness/research/` 를 정제해
     `docs/research/` 로 먼저 편입(SDS·code-style 의 근거), 이후 문서는 출처를
     `docs/research/` 로 링크(`.harness/` 참조 금지). 스킬 생성 시 references/examples 보조폴더 동반.
     - **편입은 plan 항목이지 파일 복사가 아님**(규율·강제 지점 SSOT = harness-rules 4-2) —
       정제한 본문을 `docs/research/<주제>.md` `action: create` 엔트리로 plan 에 실음.
   - vdev 감지 시 프로세스 규율은 risk-tiers defer 노트만, 자체 프로세스 룰 emit 금지.
   - **성능/통합 SSOT 문서**: 확정 스택이 있는 경우에만 `docs/verification/performance.md`·`docs/verification/integration.md`를
     authoring 으로 생성. 빈 스택 절 생성 금지. 출처는 `docs/research/` 로 링크.
     (`/performance`·`/integration` 스킬이 이 문서를 우선 소비, 부재 시 스킬 내장 references 로 폴백.)
   - **commit-versioning-guide**: `docs/operations/commit-versioning-guide.md` 생성(Conventional Commits + SemVer + 감지 스택 릴리스 도구 설정; vdev 감지 여부 무관 — harness-rules 13-1·13-2). vdev 감지 시 릴리스 도구 실설정(CI 워크플로 등) 중복 생성 금지.
2. `plan`(files[]) 을 만들어 `${HARNESS_DIR}/plan.json` 에 저장.

## Step 5 — 비판/검증 (경량, FAIL-OPEN)
1. **결정적 구조검사**:
   ```bash
   python3 "${PLUGIN}/scripts/harness_scaffold.py" validate --root "${ROOT}" --plan "${HARNESS_DIR}/plan.json"
   ```
   (게이트 아님 — high 이슈에도 exit 0. 리포트를 리더가 읽음.)
   경로 계열 high 두 종(`path`·`harness-ref`)과 `dead-link`·`dead-anchor` 는 **반드시 plan 을 고쳐서**
   해소 — 각 이슈의 뜻과 근거는 harness-rules 4-2.
2. **품질·정합성 비판**: `harness-critic` 디스패치 → `${HARNESS_DIR}/critic-report.json`.
   `verdict: revise` 면 authoring 으로 돌아가 수정 **최대 2회**. 잔여 이슈는 "미해결" 명시.

## Step 6 — 미리보기·확정
`plan`(생성/스킵/충돌) + `rationale` + `critic-report` 를 사용자에게 제시하고 확정(확정 전 쓰기 금지).
적용성이 **불확실한 렌즈·축**은 여기서 ask the user (structured choice) 로 "포함할지" 확인(9-2), greenfield
자동채택 표준은 "권장 기본(변경 가능)"으로 노출해 확정.

## Step 6.5 — migrate (구버전 경로 재배치, 확정 후·apply 전)
플러그인 갱신으로 산출물 경로가 바뀐 경우, 호스트의 **옛 위치 문서를 새 위치로 이동**(고아 사본·중복
SSOT 방지). **확정(Step 6) 이후·apply(Step 7) 전에만** 실행 — 확정 전 쓰기 금지(호스트 쓰기), 그리고
apply 전에 이동해야 apply 의 create 가 이동된(사용자 편집) 파일을 "존재"로 보고 덮어쓰지 않음.
```bash
python3 "${PLUGIN}/scripts/harness_scaffold.py" migrate --root "${ROOT}"
```
멱등·FAIL-OPEN·덮어쓰기 금지 — 옛 파일 없으면 no-op, 새 위치에 이미 있으면 clobber 없이 `conflicts`
로 보고(사람이 조정). 현재 이전 대상: `docs/{performance,integration}.md` → `docs/verification/`.
`moved`/`conflicts` 를 Step 8 보고에 노출.

## Step 7 — apply (scaffold)
```bash
python3 "${PLUGIN}/scripts/harness_scaffold.py" apply --root "${ROOT}" --plan "${HARNESS_DIR}/plan.json"
```
마커 upsert/부재시 create 만. opt-in 실설정은 기존 파일 자동병합 금지 — 누락분만 안내(.pre-commit-config.yaml 등).
`rejected`(경로가 root 밖·증거 자리로 나가거나 `path` 키가 비어 apply 가 거부한 엔트리)가
비어 있지 않으면 그 산출물은 **미기록** — 사유대로 plan 을 고쳐 다시 apply 하고 결과를 Step 8
보고에 노출. 셸로 대신 쓰기 금지(그게 이 검사를 우회하는 경로).

## Step 7.5 — cleanup (편입 사본 정리)
apply 성공 후, docs 로 편입된 중간 사본 정리(재실행/업데이트 시 혼란 방지).
```bash
python3 "${PLUGIN}/scripts/harness_scaffold.py" cleanup --root "${ROOT}"
```
`.harness/research/` 등 편입 사본만 제거하고 증거 메타(`plan.json`·`manifest.json`·
`critic-report.json`·`rationale.md`)는 보존(감사/재실행용). **링크 가드**: docs 가
`.harness/research` 를 참조하면 제거 보류 + `link_warnings` 보고(링크 깨짐 방지).
FAIL-OPEN — 정리 실패는 흐름을 안 막음. `link_warnings` 가 있으면 보고에 노출.
정리 후 `doctor --root "${ROOT}"` 를 한 번 더 돌려 `verdict` 확인. `dirty` 면 Step 8 보고에
항목별로 노출 — 커밋 전에 사람이 판단할 자리.

## Step 7.6 — 기존 문서 손실 대조 (apply 가 기존 파일을 고쳤을 때만)
`lens_upsert` 의 `replace_section` 은 `## 베스트 프랙티스` 절을 **통째로 교체**하고, 마커 upsert 는
기존 파일 안을 고침 — 그 편집이 원문의 링크·헤딩·펜스·front matter 를 함께 들어낼 수 있음.
```bash
python3 "${PLUGIN}/scripts/doc_invariants.py" --changed
```
HEAD blob ↔ 워킹트리 대조(플러그인 사본을 직접 실행 — 호스트 사본은 vdev 설치 때만 생김).
`[!]` 는 손실, `[~]` 는 참고, 새 파일(`[+]`)은 비교 대상 아님. **게이트 아님** — `flat` 교체는
설계상 옛 자유산문을 지우므로 반드시 걸림. 각 `[!]` 이 의도한 교체인지 확인, 아니면 되살린 뒤
Step 8 보고에 결과 기재. 저장소가 아니거나 HEAD 가 없으면 대조 없이 진행.

## Step 7.7 — Codex 지침
`.claude/vway-kit/config/vdev-config.yaml` 의 `harnesses` 에 `codex` 가 있을 때만.
Codex 는 `CLAUDE.md` 도 `.claude/rules/` 도 읽지 않고, 그 둘로 만든 루트 `AGENTS.md` 의 블록만
읽음 — apply 뒤 블록을 다시 만듦:
```bash
python3 "${ROOT}/.claude/vway-kit/scripts/harness/codex/instructions.py" render --host "${ROOT}"
```
출력 줄을 Step 8 보고에 옮김. 스크립트가 없으면 `codex` 를 적은 뒤 `/vdev-init` 이 돌지 않은 것 —
재실행을 안내. 블록은 손으로 고치지 말 것.

## Step 8 — 보고
생성/스킵/사용자보류 + 출처 URL + critic 결과(`version-compat` 포함) + migrate 결과(이동/충돌) +
cleanup 결과(제거/보존) + **문서 손실 대조 결과(Step 7.6 `[!]` 판정)** + **apply `rejected` ·
최종 `doctor` verdict** + 후속(스캐너 설치 명령 등)을 **표로** 요약.
`${HARNESS_DIR}/manifest.json` 에 생성내역·프레임워크·출처·critic 결과 기록(감사/재실행용).
**커밋 금지** — 사용자에게 `/vdev` 로 커밋하라 안내.
이번 실행이 `docs/srs/` 를 만들었으면 `/vdev-init` 재실행도 함께 안내 — 그때 `srs-verify`
워크플로를 제안.
