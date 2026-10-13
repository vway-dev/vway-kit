# N+1 쿼리 탐지 — Node.js (Prisma · TypeORM)

> SSOT: 스펙 §10.1 사전 리서치 기준 (2026-06).

## Prisma

| 탐지 패턴 | 올바른 형태 | 출처 |
|---|---|---|
| `for (const u of users) { await prisma.post.findMany({ where: { userId: u.id } }) }` | `include: { posts: true }` or `prisma.$transaction` 배치 | https://www.prisma.io/docs/orm/prisma-client/queries/query-optimization-performance (Apache-2.0) |

### 정적 탐지 커맨드

```bash
SRC=            # ← SKILL.md §2.0 에서 확정한 소스 루트를 채운다 (예: src · app · apps/api · .)
[ -d "${SRC:-}" ] || { echo "SRC 미확정/경로 없음 — SKILL.md §2.0 에서 소스 루트를 먼저 확정하라"; exit 1; }
comm -12 \
  <(grep -rl "for\s*(.*of" "$SRC" 2>/dev/null | sort) \
  <(grep -rlE '\.findMany\(|\.findUnique\(' "$SRC" 2>/dev/null | sort)
```

## TypeORM

| 탐지 패턴 | 올바른 형태 | 출처 |
|---|---|---|
| `@ManyToOne` 기본 lazy + 루프 접근 | `eager: true` or `QueryBuilder.leftJoinAndSelect()` | https://typeorm.io/docs/relations/eager-and-lazy-relations/ (MIT) |

### 정적 탐지 커맨드

```bash
SRC=            # ← SKILL.md §2.0 에서 확정한 소스 루트를 채운다 (예: src · app · apps/api · .)
[ -d "${SRC:-}" ] || { echo "SRC 미확정/경로 없음 — SKILL.md §2.0 에서 소스 루트를 먼저 확정하라"; exit 1; }
comm -12 \
  <(grep -rl "for\s*(.*of" "$SRC" 2>/dev/null | sort) \
  <(grep -rlE '\.findOne\(|\.find\(' "$SRC" 2>/dev/null | sort)
```

## 공유 카탈로그

- DB 쿼리 플랜: [`static-checks-db.md`](static-checks-db.md)
- 복잡도/재귀/중첩루프: [`static-checks-complexity.md`](static-checks-complexity.md)
