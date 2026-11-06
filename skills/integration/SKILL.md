---
name: integration
description: 통합 테스트 실행이나 통합 검증 결과(PASS/FAIL)가 필요할 때 사용 — 웹(Playwright)·Electron·비웹(CLI·React Native·Flutter·Go) 모두. /vdev 게이트가 아니라 사람이 부르는 수동 스킬.
---

# integration

프로젝트의 **통합 테스트를 수동 실행**하거나, 자동화가 없을 때 **사람에게 시나리오 수집**.

> **포지셔닝**: 이 스킬은 **기존 Playwright 케이스를 결정적으로 실행**. 웹인데 케이스가
> 없으면 `playwright-scaffold`로 **메인화면 smoke**("앱이 뜨는가" 결정적 검증)만 생성해 실행하고
> (임의 시나리오는 생성하지 않음), Electron이면 렌더러+주프로세스를 병행 처리하고, 그 외
> 비웹이면 human-in-the-loop 처리.
> 웹 프론트 감지는 휴리스틱이며 단정 SSOT가 아님 — 상세는
> [`references/web-playwright.md`](references/web-playwright.md) 참조.

---

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## 1. 호스트 문서 우선 소비

```bash
# harness-researcher가 생성한 통합 문서 확인 (Phase 4, 있으면 우선 소비)
ls docs/verification/integration.md 2>/dev/null && cat docs/verification/integration.md
```

- `docs/verification/integration.md` **존재 시**: 파일의 스택별 통합 전략·도구·실행 명령을 따름.
- `docs/verification/integration.md` **부재 시**: `references/web-playwright.md`·`references/electron.md`·`references/non-web.md` 로 폴백.

---

## 2. 프로젝트 유형 감지 (휴리스틱, 3분류)

> 감지 신호 전체 목록과 한계는 → [`references/web-playwright.md`](references/web-playwright.md) 참조.

`package.json`의 `dependencies`/`devDependencies`에서 웹 프레임워크 화이트리스트를 확인함:

```bash
# 웹 프레임워크 의존성 확인
grep -E '"(react|vue|next|nuxt|svelte|@angular/core|solid-js|astro)"' package.json 2>/dev/null
```

보조 신호도 함께 확인함:

```bash
# 보조 신호: vite.config, index.html, public/
ls vite.config.* index.html public/ 2>/dev/null
```

**Electron** 신호(존재하면 웹/비웹보다 우선 판정):

```bash
grep '"electron"' package.json 2>/dev/null
```

**비웹 신호** 확인(Electron·화이트리스트 둘 다 없고 아래 신호가 있으면 비웹으로 판정):

```bash
# CLI: bin 필드, RN: react-native/metro.config.js, Flutter: pubspec.yaml
grep '"bin"' package.json 2>/dev/null
grep '"react-native"' package.json 2>/dev/null
ls metro.config.js pubspec.yaml 2>/dev/null
# Go CLI/서비스: go.mod·main.go (웹 화이트리스트 미탐지 시)
ls main.go go.mod 2>/dev/null
```

| 판정 | 조건 |
|---|---|
| **Electron** | `"electron"` 의존성 — 렌더러+주프로세스 병행 처리(§4) |
| **웹** | 화이트리스트 의존성 존재 + Electron 아님 |
| **비웹** | 비웹 신호(bin/react-native/metro.config.js/pubspec.yaml/go.mod/main.go) 존재, 또는 화이트리스트 미탐지 |

---

## 3. 웹이면 — Playwright 기존 케이스 실행

> Playwright 설정·testDir/testMatch 기본값·리포터 옵션 상세는
> → [`references/web-playwright.md`](references/web-playwright.md) 참조.

### 3.1 playwright.config.* 파싱

```bash
# 설정 파일 탐지
ls playwright.config.ts playwright.config.js playwright.config.mjs playwright.config.cjs 2>/dev/null | head -1
```

설정 파일에서 `testDir`·`testMatch` 를 읽음. 기본값:
- `testDir`: `./tests`
- `testMatch`: `**/*.@(spec|test).?(c|m)[jt]s?(x)`

### 3.2 기존 케이스 발견

`TESTDIR` 는 Bash 호출 사이에 남지 않는다(호출마다 새 셸). §3.1 에서 읽은 값을 **이 커맨드의
첫 줄에 채워 넣고** 같은 호출로 실행 — 안 채우면 `tests` 로 조용히 폴백해, `e2e/` 를 쓰는
프로젝트의 실제 스위트를 "케이스 0개"로 오판하고 smoke 하나로 PASS 보고.

```bash
TESTDIR=        # ← §3.1 의 testDir (playwright.config 에 없으면 tests) — playwright-scaffold 와 동일한 testMatch 정합 매처
[ -n "$TESTDIR" ] || { echo "testDir 미확정 — §3.1 을 먼저 수행하라"; exit 1; }
[ -d "$TESTDIR" ] || { echo "MISSING: $TESTDIR"; exit 1; }
find "$TESTDIR" ! -type d \( -name '*.spec.[jt]s' -o -name '*.spec.[jt]sx' -o -name '*.spec.[cm][jt]s' -o -name '*.spec.[cm][jt]sx' -o -name '*.test.[jt]s' -o -name '*.test.[jt]sx' -o -name '*.test.[cm][jt]s' -o -name '*.test.[cm][jt]sx' \) 2>/dev/null | wc -l
```

**케이스 0개이면** `playwright-scaffold` 스킬을 호출해 **메인화면 smoke 를 생성한 뒤 바로 실행**
(임의 시나리오가 아니라 "앱이 뜨는가" 결정적 검증):

1. `Skill` 도구로 `playwright-scaffold` 호출 → baseURL 확인(코드베이스 스캔 + 사용자 확인)
   → `<testDir>/main.smoke.spec.*` 멱등 생성. (Playwright 미설치 시 scaffold가 설치를 안내.)
2. 생성된 smoke 를 §3.3대로 `--reporter=json` 으로 실행하고 §3.4로 PASS/FAIL 보고.
3. 보고에 **"스타터 smoke이니 실제 케이스로 확장하라"**(`npx playwright codegen <baseURL>`) 명시.

> 실행 러너는 `npx playwright test`(결정적·SSOT)다. 세션의 playwright MCP는 케이스 부재·탐색
> 보조 경로로만 활용(회귀 SSOT 아님, 이 스킬이 직접 호출하는 도구도 아님). MCP 참조:
> [`references/web-playwright.md`](references/web-playwright.md) "playwright MCP" 절.

### 3.3 결정적 실행

케이스가 존재하면 `--reporter=json`(+junit)으로 결정적 실행. `--reporter=json` 은 기본적으로
**stdout**으로 내보내므로, 파일로 받으려면 `PLAYWRIGHT_JSON_OUTPUT_NAME`을 지정한다(미지정 시
§3.4의 파일 파싱이 ENOENT로 깨짐):

```bash
PLAYWRIGHT_JSON_OUTPUT_NAME=results.json \
PLAYWRIGHT_JUNIT_OUTPUT_NAME=results.xml \
  npx playwright test --reporter=json,junit
```

### 3.4 결과 파싱 및 PASS/FAIL 보고

§3.3에서 지정한 `results.json` 파싱. **비정상 종료(설정 오류·크래시로 파일 부재/형식 이상)를
방어**해 항상 명확한 판정을 냄:

```bash
node -e "
  let r;
  try {
    r = JSON.parse(require('fs').readFileSync('results.json', 'utf8'));
  } catch (e) {
    console.log('FAIL: results.json을 읽거나 파싱할 수 없음 (Playwright 비정상 종료 가능) —', e.message);
    process.exit(1);
  }
  const s = r.stats;
  if (!s || typeof s.expected !== 'number') {
    console.log('FAIL: results.json에 stats 필드가 없음 (설정 오류 가능)');
    process.exit(1);
  }
  // 실행 자체가 죽은 회차는 errors 에만 사유가 남음. 셋업이 죽으면 집계 넷이 전부 0 이라
  // 아래 0건 검사도 함께 잡지만, 티어다운이 죽으면 케이스가 다 돌아 그 검사를 통과함 —
  // 티어다운이 죽은 회차를 막는 것은 이 검사뿐이고, 없으면 승격이 그 판정을 근거로 씀.
  if ((r.errors || []).length) {
    console.log('FAIL: 실행 자체가 오류로 끝남 —', r.errors[0].message || r.errors[0]);
    process.exit(1);
  }
  if (s.expected + s.unexpected + (s.flaky || 0) === 0) {
    console.log('FAIL: 실행된 케이스가 0개 (셋업 실패·필터가 전부 걸러냄 가능)');
    process.exit(1);
  }
  // flaky 는 **통과한 실행** — 마지막 시도가 통과했고 unexpected 에도 안 실림. 통과 칸에
  // 안 세면 재시도로 통과한 회차의 증거가 'PASS: 0' 이 되어, 종료 코드는 통과인데 문구는
  // 아무것도 안 돈 것처럼 읽힘.
  console.log('PASS:', s.expected + (s.flaky || 0), '/ FAIL:', s.unexpected,
              '/ FLAKY:', s.flaky || 0, '/ SKIP:', s.skipped);
  // 건너뛴 케이스는 여기서 판정을 못 가름 — Playwright 의 stats 는 test.skip() 과 중단된
  // 실행의 잔여를 같은 칸에 담음. 얼마나 돌아야 충분한지는 케이스별 표의 NOT_RUN 줄과
  // promotion_verification.exit_criteria 가 정함(release-commit 3단계).
  // failOnFlakyTests 를 켠 호스트는 flaky 를 통과로 안 세므로 PASS 칸에서도 빼고 exit 조건에
  // || (s.flaky || 0) > 0 을 더함 — 기본값이 false 라 Playwright 자신도 flaky 를 통과로 냄.
  process.exit(s.unexpected > 0 ? 1 : 0);
"
```

**케이스별 판정** — 회차를 남기는 호스트(`run: true` 계층 선언)에서는 집계만으로 부족.
스위트를 순회해 제목의 `@<케이스 key>` 태그를 뽑음. 태그가 대응의 SSOT — 보드 필드에 스펙 파일
경로를 적어 두는 반대 방향은 테스트 이름이 바뀌면 조용히 끊김.

```bash
node -e "
  let r;
  try {
    r = JSON.parse(require('fs').readFileSync('results.json', 'utf8'));
  } catch (e) {
    console.log('FAIL: results.json을 읽거나 파싱할 수 없음 —', e.message);
    process.exit(1);
  }
  const rows = [];
  (function walk(s) {
    (s.suites || []).forEach(walk);
    (s.specs || []).forEach(spec => {
      const tests = spec.tests || [];
      const tag = (spec.title.match(/@[A-Za-z]+-\d+/) || [])[0] || '';
      // project 마다 한 번씩 도므로 **전부** 봄 — 첫 것만 보면 chromium 통과·firefox 실패가
      // PASS 로 기록되고, 같은 회차의 집계와 표가 어긋남.
      const each = tests.map(t => {
        const runs = t.results || [];
        // **마지막** 시도가 그 project 의 결론 — 첫 시도를 보면 재시도로 통과한 flaky 가
        // 표에서 FAIL 이 되어 집계(unexpected 0)와 갈리고, 그 FAIL 이 latest_result 로 박힘.
        const res = runs[runs.length - 1] || {};
        // 결과가 없거나(중단) skipped 면 안 돈 것. 판정을 spec.ok() 로 접는 지름길이 여기서
        // 깨짐 — ok() 는 skipped 에도 true 라 안 돈 케이스에 PASS 가 박힘.
        if (!runs.length || t.status === 'skipped' || res.status === 'skipped') return 'NOT_RUN';
        if (res.status === 'passed' || res.status === 'expected') return 'PASS';
        // 셋업 단계에서 멈춘 것만 BLOCKED. 본문 타임아웃은 진짜 실패라 FAIL 로 둠.
        const msg = (res.error && res.error.message) || '';
        return /beforeAll|beforeEach|globalSetup|fixture/.test(msg) ? 'BLOCKED' : 'FAIL';
      });
      const rank = ['FAIL', 'BLOCKED', 'NOT_RUN', 'PASS'];
      const verdict = each.length
        ? rank.find(v => each.includes(v))          // 하나라도 나쁘면 그쪽으로 접음
        : 'NOT_RUN';
      const worst = Math.max(0, ...tests.map(t => {
        const rs = t.results || [];
        return (rs[rs.length - 1] || {}).duration || 0;
      }));
      rows.push([tag, spec.title, verdict, (worst / 1000).toFixed(1) + 's']);
    });
  })(r);
  rows.forEach(x => console.log(x.join(' | ')));
"
```

`BLOCKED` 판정은 **최선 추정**이고 양쪽으로 틀림. 셋업이 죽은 경우(`ECONNREFUSED` 등)는
메시지에 앵커 낱말이 안 실려 FAIL 로 떨어지고(안전한 방향 — 사람 선별에 올라감), 반대로
`test.extend` fixture 를 쓰는 저장소에서는 진짜 단언 실패의 코드프레임에 `fixture` 가 실려
BLOCKED 로 접힘. 뒤쪽은 그 결함이 선별 목록에서 빠져 보드에 안 오르는 손실 — 승격은 집계가
막으므로 릴리스는 무사함. 그래서 **진짜 판정은 사람이** 함: 선별 화면에 BLOCKED 줄도 함께
보이고, 사람이 결함이라 하면 그것도 승격 대상.

판정 어휘는 다섯 — `PASS`·`FAIL`·`BLOCKED`·`NOT_APPLICABLE`·`NOT_RUN`. **`BLOCKED` 는 FAIL
아님**: 환경이 무너져 못 돈 것을 FAIL 로 뭉개면 결함 선별이 매 회차 쓰레기를 받음. 둘을 안
가르면 사람이 그 목록을 안 읽게 되고, 그때 결함 보드가 오염됨.

태그 없는 케이스도 회차 표에 `''` 키로 남김 — 보드에 대응이 없다는 사실 자체가 커버리지 정보.

**리포트 형식**:

```
## 통합 테스트 결과 — <날짜>

### Playwright 실행 결과
| 스위트 | 통과 | 실패 | 건너뜀 | 판정 |
|---|---|---|---|---|
| tests/auth.spec.ts | 5 | 0 | 0 | PASS |
| tests/checkout.spec.ts | 3 | 1 | 0 | FAIL |

**전체 판정**: FAIL (실패 1건)
실패 케이스: tests/checkout.spec.ts › 결제 완료 후 확인 페이지 이동
```

### 3.5 회차 기록

`run: true` 계층을 선언한 호스트에서만. 미선언이면 이 절 통째로 스킵.

- `create_workboard_item` 으로 회차 항목 하나. 본문은 `alm/run.md` 템플릿의 고정 스키마 결과표,
  거기에 `fields` 의 `scope`(이 회차가 돌기로 한 suite 집합)·`build`(커밋 sha)·`environment`·
  `result` 를 함께 실음. `scope` 가 커버리지 분모라, 비우면 무엇을 덜 돌았는지 못 답함.
  본문은 비개발자가 읽음 — 규칙은 [item-body](../task-import/references/item-body.md).
- 회차 하나 = (scope × build × environment) 하나. 환경 둘을 돌았으면 회차도 둘.
- 케이스 항목의 `latest_result`·`latest_run` 갱신(그 계층이 `fields` 로 매핑했을 때만).
  갱신 대상 보드는 회차 계층의 `runs` 가 지목한 계층 — 그 선언이 이 회차가 어느 케이스 집합을
  담는지 말함.
- **`result` 확정은 사람 승인.** 자동으로 PASS 를 쓰면 코드를 쓴 쪽이 자기 검증을 통과 판정하는
  경로에 사람이 한 번도 안 들어감.
- **FAIL 목록에서** 진짜 결함을 골라 승격(Ask the user (multi-select)). `BLOCKED` 는 기본 선별
  대상이 아니라 환경 보고 줄로 나가되 **화면에 함께 보임** — 자동으로 결함을 만들면 보드를
  아무도 안 믿고, 아예 감추면 오분류된 진짜 결함이 영영 안 오름. 고른 것은
  [`alm-trace`](../alm-trace/SKILL.md) 결함 경로로 넘김 — 깨진 케이스가 요구사항을 이미
  지목하므로 유사도 스캔은 스킵.
- 스타터 smoke 단독 실행이면 회차 없음(§3.6 의 세 조건과 같은 이유).

### 3.6 ALM 항목 완료 제안과 전파

셋이 모두 참일 때만 제안 — 전체 판정 PASS · `vdev-config.alm` 의 provider 에 `recoble` 이 있음
(`--verified` 는 Recoble 전용) · 방금 `playwright-scaffold` 가 만든 smoke 단독 실행이 아님. 스타터 smoke 하나의 PASS 는
"앱이 뜬다" 이지 E2E 검증이 아님.

대상 항목은 사람이 고름 — 이 스킬은 언제든 도는 수동 스킬이라 어느 작업 문서인지 자동 추론 금지.
받아야 하는 것은 **ALM 항목 id**(제목이 아님 — task-sync 가 그 id 로 조회함).
승인하면 `/task-sync <항목 id…> --verified` 로 [`task-sync`](../task-sync/SKILL.md) 호출 —
릴리스가 여러 항목을 닫으면 id 를 나열해 **한 번에** 넘김(항목마다 부르면 승인이 그만큼 늘고,
그 비용이 이 단계를 통째로 건너뛰게 만듦).
FAIL 이면 제안 자체가 없음.

**결과를 적은 회차는 판정과 무관하게 끝에 전파 한 번.** §3.5 가 케이스 `latest_result` 를 하나라도 적었고
provider 에 `recoble` 이 있으면 `/task-sync <적은 케이스 id…> --propagate` 로
[`task-sync`](../task-sync/SKILL.md) 호출 — id 는 한 번에 나열. 그 id 는
§3.5 가 `latest_result` 를 쓴 케이스 항목(§3.4 태그로 찾은 것). 위 `--verified` 제안이 있으면 그
**뒤**, FAIL·BLOCKED 처럼 제안이 없으면 바로. 승인 없음: 그 모드는 상위의 `progress`·
`coverage_status` 만 쓰고 상태를 옮기지 않음. `--verified` 가 승인됐어도 건너뛰지 않음 — 그 인자는
사람이 고른 닫을 항목이라 이 케이스들이 그 시드에 없을 수 있음. 순서가 뒤인 이유: 두 전파가 같은 상위에
닿으면 나중 것이 `--verified` 가 옮긴 상태까지 읽고 판정함. 실패해도 한 줄 보고하고 끝 — ALM 실패는
게이트 아님.

---

## 4. Electron이면 — 렌더러 자동화 + 주프로세스 human-in-the-loop

> 전체 절차는 [`references/electron.md`](references/electron.md)가 유일 SSOT다 — 렌더러는
> Playwright chromium 채널로 §3과 동일하게 자동 실행하고, 주프로세스(IPC·파일시스템·네이티브 API)는
> §5의 human-in-the-loop 절차를 `<타입>` = `"Electron(주 프로세스)"`로 채워 사용.

---

## 5. 그 외 비웹이면 — human-in-the-loop

> 비웹 타입별 신호·참고 OSS 상세는 → [`references/non-web.md`](references/non-web.md) 참조.

`run: true` 계층을 선언한 호스트면 여기서도 회차를 남김 — 시나리오별 사람 판정을 §3.5 의 결과표
칸(케이스·제목·판정·소요)에 그대로 채우고, `scope` 는 확인한 시나리오 집합으로 적음. 도구가
없다고 근거가 없어도 되는 것은 아님.

자동 통합 테스트 강제 금지. §2에서 감지한 **실제 서브타입**을 프롬프트에 채워
Ask the user (structured choice) 로 시나리오와 통과 기준 수집(범용 문구 하드코딩 금지):

```
이 프로젝트는 비웹(<§2에서 감지된 타입 — 예: "CLI 도구", "React Native", "Flutter", "Go 서비스">)으로 감지되었습니다.
통합 테스트 자동화 도구를 강제하지 않습니다.

아래 항목을 알려주세요:
1. 검증할 핵심 시나리오 (예: "사용자 로그인 후 데이터 조회")
2. 각 시나리오의 통과 기준 (예: "응답 코드 200, 데이터 포함")
3. 현재 사용 중인 테스트 도구가 있으면 알려주세요.
4. 자동화 우선순위 (예: "API 엔드포인트 계약 테스트 먼저", "수동 체크리스트로 충분")
```

수집한 시나리오를 기반으로 수동 검증 체크리스트를 작성하고, 적용 가능한 OSS 안내
(Newman/Maestro/Appium — 모두 Apache-2.0, 자동 강제 없음). 상세는
[`references/non-web.md`](references/non-web.md) 참조.

---

## 참조

- [`references/web-playwright.md`](references/web-playwright.md) — 웹 감지 신호·testDir/testMatch·리포터·best-practices·SSOT URL
- [`references/electron.md`](references/electron.md) — Electron 렌더러+주프로세스 통합 절차 (유일 SSOT)
- [`references/non-web.md`](references/non-web.md) — 비웹 타입 신호·human-in-the-loop 절차·참고 OSS
- [`playwright-scaffold`](../playwright-scaffold/SKILL.md) — 웹+케이스 0개일 때 메인화면 smoke 생성기(이 스킬이 호출)
