# Electron 통합 테스트 — 렌더러 자동화 + 메인프로세스 human-in-the-loop

> Electron은 Chromium 렌더러 위에서 동작하므로 **렌더러 프로세스는 Playwright로 부분 자동화**
> 가능하지만, **주 프로세스(Node.js IPC·파일시스템·네이티브 API)는 Playwright로 제어 불가**.
> 이 문서가 Electron 처리 방식의 유일한 SSOT — 다른 파일은 여기로 링크만.

## 1. 렌더러 프로세스 — Playwright chromium 채널로 자동화

```bash
# electron 의존성 확인 (integration/SKILL.md §2에서 이미 감지된 상태로 진입)
grep '"electron"' package.json 2>/dev/null
```

기존 웹 케이스 발견·실행 절차([`web-playwright.md`](web-playwright.md) §2-3)를 그대로 적용하되,
`playwright.config`의 `use.channel`을 `chromium`으로 지정해 Electron의 내장 Chromium을 사용함:

```javascript
// playwright.config.ts — Electron 렌더러 대상
export default defineConfig({
  use: { channel: 'chromium' },
});
```

케이스 탐색·`--reporter=json` 실행은 [`web-playwright.md`](web-playwright.md) §2-3과 동일,
결과 파싱은 [`SKILL.md`](../SKILL.md) §3.4.

## 2. 주 프로세스 — human-in-the-loop

IPC·파일시스템·네이티브 API 관련 시나리오는 자동화 금지. [`non-web.md`](non-web.md) §2의
질문 절차(ask the user (structured choice))를 그대로 사용하되, 프롬프트의 `<타입>`에 `"Electron(주 프로세스)"`를 채움.

## 3. 참고 자료

- Playwright Electron 지원: https://playwright.dev/docs/api/class-electron (Apache-2.0)
