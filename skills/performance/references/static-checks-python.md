# N+1 쿼리 탐지 — Python (Django · SQLAlchemy)

> SSOT: 스펙 §10.1 사전 리서치 기준 (2026-06). 출처 URL·라이선스 명시.
> **런타임 도구는 "검증 위임" 표기** — 정적 탐지로 후보 추출, 런타임 도구로 최종 판정.

## Django

| 탐지 패턴 | 올바른 형태 | 도구 | 출처 |
|---|---|---|---|
| `for obj in qs: obj.related_set.all()` — 루프 내 역방향 릴레이션 접근 | `prefetch_related('related_set')` | nplusone (MIT) | https://github.com/jmcarp/nplusone |
| `for obj in qs: obj.fk_field.attr` — 루프 내 외래키 순방향 접근 | `select_related('fk_field')` | nplusone / django-zen-queries | https://github.com/dabapps/django-zen-queries (BSD-2) |
| 현대 fork (Django 5.x 지원) | — | nplus1 | https://github.com/huynguyengl99/nplus1 |

### 정적 탐지 커맨드

`for` 루프가 있는 파일과 ORM 접근 패턴이 있는 파일의 **교집합**을 구한다(한 파일에 두 패턴이
공존 = 검토 후보). `comm` 은 정렬된 입력을 요구하므로 각 서브셸에 반드시 `sort` 포함.

```bash
SRC=            # ← SKILL.md §2.0 에서 확정한 소스 루트를 채운다 (예: src · app · apps/api · .)
[ -d "${SRC:-}" ] || { echo "SRC 미확정/경로 없음 — SKILL.md §2.0 에서 소스 루트를 먼저 확정하라"; exit 1; }
comm -12 \
  <(grep -rl "for .*:" "$SRC" 2>/dev/null | sort) \
  <(grep -rlE '\.(objects|\w+_set)\.(get|filter|all)\(' "$SRC" 2>/dev/null | sort)
```

**검증 위임**: `nplusone.hooks.NPlusOneHook` 을 테스트에 연결하면 런타임 N+1 을 예외로 포착.

## SQLAlchemy

| 탐지 패턴 | 올바른 형태 | 출처 |
|---|---|---|
| 루프 내 lazy load (기본값 `lazy='select'`) | `joinedload()` / `selectinload()` | https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html (MIT) |
| `Session.get()` 루프 반복 | 배치 조회 or `in_()` 필터 | 위 동일 |

### 정적 탐지 커맨드

```bash
SRC=            # ← SKILL.md §2.0 에서 확정한 소스 루트를 채운다 (예: src · app · apps/api · .)
[ -d "${SRC:-}" ] || { echo "SRC 미확정/경로 없음 — SKILL.md §2.0 에서 소스 루트를 먼저 확정하라"; exit 1; }
comm -12 \
  <(grep -rl "for .*:" "$SRC" 2>/dev/null | sort) \
  <(grep -rl "session.get(\|\.query(" "$SRC" 2>/dev/null | sort)
```

## 공유 카탈로그

- DB 쿼리 플랜: [`static-checks-db.md`](static-checks-db.md)
- 복잡도/재귀/중첩루프: [`static-checks-complexity.md`](static-checks-complexity.md)
