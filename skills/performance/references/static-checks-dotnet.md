# N+1 쿼리 탐지 — .NET (EF Core)

> SSOT: 스펙 §10.1 사전 리서치 기준 (2026-06).

| 탐지 패턴 | 올바른 형태 | 출처 |
|---|---|---|
| `foreach (var x in ctx.Entities) { x.Nav.Load(); }` | `.Include(e => e.Nav)` | https://learn.microsoft.com/en-us/ef/core/performance/efficient-querying (MIT) |
| 대형 결과셋에 `.Include()` 체인 남용 | Split Query(`AsSplitQuery()`) 고려 | https://learn.microsoft.com/en-us/ef/core/querying/single-split-queries |

## 정적 탐지 커맨드

```bash
SRC=            # ← SKILL.md §2.0 에서 확정한 소스 루트를 채운다 (예: src · app · apps/api · .)
[ -d "${SRC:-}" ] || { echo "SRC 미확정/경로 없음 — SKILL.md §2.0 에서 소스 루트를 먼저 확정하라"; exit 1; }
comm -12 \
  <(grep -rl "foreach\s*(" "$SRC" 2>/dev/null | sort) \
  <(grep -rlE '\.Load\(\)|\.Entry\(' "$SRC" 2>/dev/null | sort)
```

## 공유 카탈로그

- DB 쿼리 플랜: [`static-checks-db.md`](static-checks-db.md)
- 복잡도/재귀/중첩루프: [`static-checks-complexity.md`](static-checks-complexity.md)
