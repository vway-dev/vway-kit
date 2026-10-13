---
name: playwright-scaffold
description: 웹 프로젝트에 첫 Playwright 케이스(메인화면 smoke)가 필요할 때 사용 — 케이스가 없는/새 웹 프로젝트의 통합 검증 출발점. integration 스킬이 웹 + 케이스 0개를 감지하면 호출한다.
---

# playwright-scaffold

웹 프로젝트에 **결정적 메인화면 smoke** Playwright 케이스 하나 생성. "앱이 뜨는가"라는
보편·결정적 검증만 생성, **임의 사용자 시나리오 생성 금지**(사람·codegen 몫).

> **언제**: 새/빈 웹 프로젝트에 최초 통합 케이스가 필요할 때. integration 스킬이 웹 + 케이스 0개를
> 감지하면 이 스킬을 호출해 메인화면 smoke 생성 후 바로 실행.

---

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Step 1 — baseURL 감지 (순서대로, 마지막엔 사용자 확인)

1. **playwright.config**의 `use.baseURL`:
   ```bash
   ls playwright.config.* 2>/dev/null && grep -n "baseURL" playwright.config.* 2>/dev/null
   ```
2. 없으면 **코드베이스 스캔**(단정하지 말고 후보를 모음):
   ```bash
   # docker-compose 포트 매핑(웹 서비스 host 포트)
   grep -nE '^\s*-\s*"?[0-9]+:[0-9]+' docker-compose.y*ml compose.y*ml 2>/dev/null
   # .env 의 PORT / BASE_URL / 공개 URL
   grep -nhE '^(PORT|BASE_URL|VITE_[A-Z_]*URL|NEXT_PUBLIC_[A-Z_]*URL)=' .env .env.* 2>/dev/null
   # 프레임워크 설정 / dev 스크립트 포트
   grep -nE 'server\s*:|port\s*:' vite.config.* next.config.* 2>/dev/null
   grep -nE '"dev"\s*:.*(--port|-p )\s*[0-9]+' package.json 2>/dev/null
   # Dockerfile EXPOSE
   grep -niE '^EXPOSE\s+[0-9]+' Dockerfile* 2>/dev/null
   ```
   - 스캔이 비면 프레임워크 기본 포트를 후보로: Vite=5173, Next/CRA/Nuxt=3000, Angular=4200.
3. **사용자 확인(필수)**: 수집한 후보를 ask the user (structured choice) 로 제시해 baseURL 확정
   (후보 여러 개면 선택지로, 못 찾았으면 직접 입력 요청). 추측 단정 금지.

---

## Step 2 — testDir·언어 감지

```bash
# testDir: playwright.config 의 testDir, 없으면 ./tests
grep -n "testDir" playwright.config.* 2>/dev/null
# 언어: TS 프로젝트면 .spec.ts, 아니면 .spec.js
ls tsconfig.json 2>/dev/null; grep -E '"(typescript|@playwright/test)"' package.json 2>/dev/null
```
- `testDir` 미설정 → `tests/`. TS(tsconfig.json 또는 typescript 의존성) → `.spec.ts`, 아니면 `.spec.js`.

---

## Step 3 — 멱등 생성 (이미 있으면 skip)

`TESTDIR` 는 Bash 호출 사이에 남지 않는다(호출마다 새 셸) — Step 2 에서 확정한 값을 **이 커맨드의
첫 줄에 채워 넣고** 같은 호출로 실행.

```bash
# 기존 케이스가 하나라도 있으면 생성하지 않는다(스타터는 빈 프로젝트 전용)
TESTDIR=        # ← Step 2 에서 확정한 testDir (playwright.config 에 없으면 tests)
[ -n "$TESTDIR" ] || { echo "testDir 미확정 — Step 2 를 먼저 수행하라"; exit 1; }
[ -d "$TESTDIR" ] || { echo "MISSING: $TESTDIR"; exit 1; }
find "$TESTDIR" ! -type d \( -name '*.spec.[jt]s' -o -name '*.spec.[jt]sx' -o -name '*.spec.[cm][jt]s' -o -name '*.spec.[cm][jt]sx' -o -name '*.test.[jt]s' -o -name '*.test.[jt]sx' -o -name '*.test.[cm][jt]s' -o -name '*.test.[cm][jt]sx' \) 2>/dev/null | head -1
```
- 케이스가 이미 있거나 `main.smoke.spec.*`가 존재하면 **생성하지 않고 보고만** 한다(덮어쓰기 금지).
- 없을 때만 [`examples/main.smoke.spec.ts`](examples/main.smoke.spec.ts)를 기반으로
  `<testDir>/main.smoke.spec.<ts|js>`를 씀. baseURL은 spec에 박지 않고
  **playwright.config의 `use.baseURL`**로 주입한다(spec은 `'/'` 상대경로만 사용). config에
  baseURL 이 없으면 Step 4에서 config 에 추가.

---

## Step 4 — Playwright 미설치/config 부재 (opt-in)

- `@playwright/test` 미설치 또는 `playwright.config.*` 부재 시, 최소 config를 스캐폴드하고 설치를
  **안내**한다(자동 설치 강제 금지 — 동의 시에만):
  ```bash
  npm install -D @playwright/test && npx playwright install chromium
  ```
  ```javascript
  // playwright.config.ts (최소 — BASE_URL 이 Step 1에서 확정한 값을 덮는다)
  import { defineConfig } from '@playwright/test';
  export default defineConfig({
    testDir: './tests',
    use: {
      baseURL: process.env.BASE_URL ?? 'http://localhost:3000', // ← Step 1에서 확정한 값
      trace: 'retain-on-failure',  // 트레이스는 요청·응답 본문과 세션 토큰을 실어 나른다.
      video: 'off',                // CI 리포트 업로드가 안전한지는 이 두 값이 정한다 —
    },                             // 함부로 넓히지 말 것.
    // 모노레포는 앱마다 항목 하나. 병렬로 돌고, 실패가 전부 수집되며, 리포트 하나가
    // 전부를 덮는다:
    //   projects: [
    //     { name: 'web',   use: { baseURL: process.env.WEB_URL   ?? 'http://localhost:3000' } },
    //     { name: 'admin', use: { baseURL: process.env.ADMIN_URL ?? 'http://localhost:3001' } },
    //   ],
  });
  ```

---

## Step 5 — 보고 + 확장 안내

- 생성한 파일 경로와 주입한 baseURL 보고.
- **config 가 이미 있으면 다시 쓰지 않음** — 대신 보고: 모노레포가 필요로 하는 `projects[]` 모양
  (앱마다 항목 하나, 각자의 `baseURL`), `trace`·`video` 짝, 그리고
  `.github/workflows/e2e.yml` 이 `working-directory` **하나**에서 `npx playwright test` 를
  돌린다는 것 — 그래서 모든 앱이 그 config 하나에서 닿아야 함.
- **스타터 smoke 임을 명시**: "이건 '앱이 뜨는가' 검증일 뿐. 실제 시나리오(로그인·결제 등)는
  직접 추가하거나 `npx playwright codegen <baseURL>`로 녹화해 `tests/`에 저장하라."

---

## 참조
- Playwright — Apache-2.0(무료 OSS만 씀). 작성법 https://playwright.dev/docs/writing-tests ·
  설정 https://playwright.dev/docs/test-configuration
