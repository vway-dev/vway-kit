# N+1 쿼리 탐지 — Java (Hibernate)

> SSOT: 스펙 §10.1 사전 리서치 기준 (2026-06).

| 탐지 패턴 | 올바른 형태 | 도구 | 출처 |
|---|---|---|---|
| `@OneToMany` 기본 `FetchType.LAZY` + 루프 접근 | `FetchType.EAGER` or `JOIN FETCH` JPQL | Hibernate Statistics (런타임 검증 위임) | https://docs.jboss.org/hibernate/orm/5.4/javadocs/org/hibernate/stat/Statistics.html |
| 루프 내 `entityManager.find()` | `entityManager.createQuery("...JOIN FETCH...")` | — | 위 동일 |

## 정적 탐지 커맨드

```bash
SRC=            # ← SKILL.md §2.0 에서 확정한 소스 루트를 채운다 (예: src · app · apps/api · .)
[ -d "${SRC:-}" ] || { echo "SRC 미확정/경로 없음 — SKILL.md §2.0 에서 소스 루트를 먼저 확정하라"; exit 1; }
comm -12 \
  <(grep -rl "for\s*(.*:" "$SRC" 2>/dev/null | sort) \
  <(grep -rlE '\.find\(|\.getReference\(' "$SRC" 2>/dev/null | sort)
```

**검증 위임**: `hibernate.generate_statistics=true` 후 `StatisticsImpl.getQueryExecutionCount()`로
루프당 쿼리 수 실측.

## 공유 카탈로그

- DB 쿼리 플랜: [`static-checks-db.md`](static-checks-db.md)
- 복잡도/재귀/중첩루프: [`static-checks-complexity.md`](static-checks-complexity.md)
