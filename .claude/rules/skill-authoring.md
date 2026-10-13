---
paths:
  - skills/**
---

# 스킬 작성 규율 (vway-kit 자신의 스킬)

`skills/**` 편집 시 로드. 규율 **본문은 아래 SSOT 에만** — 여기서 복제 금지.

- **작성 품질** = [skill-writing-guide.md](../../skills/harness-authoring/references/skill-writing-guide.md)
  — 특히 **§8 커맨드 블록은 한 호출에서 자족**. Bash 호출은 매번 새 셸이라 앞 호출의 `export` 가
  안 남고, 빈 변수가 흘러 들어가면 빈 결과가 "이상 없음"으로 리포트에 실림(탐지 실패 = 통과 둔갑).
  `${VAR:-기본값}` 폴백·`2>/dev/null` 이 그 단서까지 지움.
- **frontmatter 스펙** = [authoring-spec.md](../../skills/harness-authoring/references/authoring-spec.md)
  — 모델 지식 아닌 [공식문서](https://code.claude.com/docs/en/skills.md)로 확인.
  `allowed-tools` 는 **제한이 아니라 권한 사전승인**(제한은 `disallowed-tools`).
- **문체** = [doc-style.md](../../rules/doc-style.md) — 개조식·이력 금지·한 사실 한 곳.
  강제는 `tests/skill_docs/test_prose.py::test_shipped_prose_stays_terse`. 단 frontmatter `description` 은
  예외 — `evals/scores.json` 이 그 sha 로 호출률 점수를 고정하므로, 한 글자만 고쳐도
  `uv run python -m evals.run --skill <name>` 재측정(모델 호출) 없이는 게이트가 빨개짐.

두 참조 파일은 `harness-authoring` 이 *생성되는* 하네스에 적용하는 규율이지만, vway-kit 의 제품이
곧 같은 종류의 `.md` 이므로 자기 스킬에도 동일 적용.
