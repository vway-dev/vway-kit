# N+1 쿼리 탐지 — Ruby (Rails)

> SSOT: 스펙 §10.1 사전 리서치 기준 (2026-06).

| 탐지 패턴 | 올바른 형태 | 도구 | 출처 |
|---|---|---|---|
| 루프 내 `belongs_to` / `has_many` 접근 (lazy) | `includes(:assoc)` / `eager_load(:assoc)` | bullet (MIT) | https://github.com/flyerhzm/bullet (MIT) |
| `where` 후 루프 내 연관 접근 | `preload` 사용 | prosopite (Apache-2.0) | https://github.com/charkost/prosopite |

## 정적 탐지 커맨드

```bash
SRC=            # ← SKILL.md §2.0 에서 확정한 소스 루트를 채운다 (예: src · app · apps/api · .)
[ -d "${SRC:-}" ] || { echo "SRC 미확정/경로 없음 — SKILL.md §2.0 에서 소스 루트를 먼저 확정하라"; exit 1; }
comm -12 \
  <(grep -rl "\.each\s*do" "$SRC" 2>/dev/null | sort) \
  <(grep -rlE '\.\w+\.(each|map|to_a)' "$SRC" 2>/dev/null | sort)
```

**검증 위임**: `bullet` gem을 test 환경에서 활성화하면 N+1·unused eager loading을 로그에 기록.

## 공유 카탈로그

- DB 쿼리 플랜: [`static-checks-db.md`](static-checks-db.md)
- 복잡도/재귀/중첩루프: [`static-checks-complexity.md`](static-checks-complexity.md)
