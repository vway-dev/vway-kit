# 프론트엔드 리렌더 정적 안티패턴 — React

> SSOT: 스펙 §10.4 사전 리서치 기준 (2026-06).

## React Compiler 활성 감지 (버그 수정: Vite camelCase 옵션 포함)

```bash
grep -rE "react-compiler|babel-plugin-react-compiler|reactCompiler" package.json babel.config.* vite.config.* 2>/dev/null
```

## React Compiler v1.0 활성 시 (2025-10 GA 기준)

Compiler가 활성화되면 **자동 메모화**가 적용되므로 수동 `memo`/`useMemo`/`useCallback` 룰을
완화. 대신 **Rules of React 위반** 중심으로 점검:

- `eslint-plugin-react-hooks`의 `rules-of-hooks` + `exhaustive-deps` 규칙 (Compiler와 통합)
- 컴포넌트 외부에서 훅 호출 / 조건부 훅 호출 등 Rules of React 위반

| 항목 | 출처 |
|---|---|
| eslint-plugin-react-hooks (MIT) | https://react.dev/reference/eslint-plugin-react-hooks |
| React Compiler v1.0 블로그 | https://react.dev/blog/2025/10/07/react-compiler-1 |
| React Compiler 소개 | https://react.dev/learn/react-compiler/introduction |

## React Compiler 미활성 시

| 정적 탐지 패턴 | 문제 | 권고 | 출처 |
|---|---|---|---|
| JSX prop에 인라인 객체 `<Comp style={{ color: 'red' }}>` | 매 렌더마다 새 객체 참조 → 자식 리렌더 | `useMemo`로 메모화 또는 모듈 상수로 추출 | https://react.dev/reference/react/useMemo |
| JSX prop에 인라인 함수 `<Comp onClick={() => handler(id)}>` | 매 렌더마다 새 함수 참조 | `useCallback(…, [id])` | https://react.dev/reference/react/useCallback |
| `React.memo` 감싼 컴포넌트에 인라인 prop | memo가 무효화됨 | prop을 안정 참조로 | https://react.dev/reference/react/memo |
| `useEffect` deps 배열 누락 또는 과다 | stale closure / 무한 루프 | `exhaustive-deps` lint 룰 적용 | https://react.dev/reference/eslint-plugin-react-hooks |

## 런타임 리렌더 도구 (검증 위임)

| 도구 | 라이선스 | 출처 |
|---|---|---|
| React DevTools Profiler | MIT | https://react.dev/reference/react/Profiler |
| why-did-you-render | MIT | https://github.com/welldone-software/why-did-you-render |
| react-scan | MIT | https://github.com/aidenybai/react-scan |
