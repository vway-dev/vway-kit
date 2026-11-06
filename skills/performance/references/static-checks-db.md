# DB 쿼리 플랜 정적 안티패턴 (언어 무관)

> SSOT: 스펙 §10.2 사전 리서치 기준 (2026-06). 출처 URL·라이선스 명시.
> 정적으로 탐지 가능한 패턴만 플래깅. 최종 판정은 EXPLAIN ANALYZE 실행으로 위임.

| 정적 패턴 | 문제 | 권고 | 검증 명령 |
|---|---|---|---|
| `SELECT *` | 불필요 컬럼 전송, 인덱스 커버리지 손실 | 필요 컬럼만 명시 | `EXPLAIN ANALYZE SELECT *` 후 플랜 확인 |
| `WHERE func(column) = ?` | 함수 래핑으로 인덱스 스캔 불가 | 함수 없는 조건 재작성 or 함수 기반 인덱스 | `EXPLAIN ANALYZE` |
| `LIKE '%keyword%'` | 선행 와일드카드로 풀 스캔 | 역방향 인덱스·FTS 고려 | `EXPLAIN ANALYZE` |
| 복잡 `OR` 체인 | 옵티마이저가 인덱스 병합 실패 가능 | `UNION ALL` 재작성 검토 | `EXPLAIN ANALYZE` |
| 서브쿼리 `IN (SELECT ...)` 남용 | 상관 서브쿼리로 N×M 스캔 가능 | `JOIN` 또는 `EXISTS` 재작성 | `EXPLAIN ANALYZE` |

## 정적 탐지 커맨드

```bash
# 프로젝트 전역에서 SELECT * 사용처
grep -rniE 'select\s+\*\s+from' --include='*.sql' --include='*.py' --include='*.rb' --include='*.java' --include='*.cs' --include='*.js' --include='*.ts' .
# 선행 와일드카드 LIKE
grep -rniE "like\s+['\"]%\S" --include='*.sql' --include='*.py' --include='*.rb' --include='*.java' --include='*.cs' --include='*.js' --include='*.ts' .
```

## EXPLAIN 공식 문서

| DB | 명령 | 출처 |
|---|---|---|
| PostgreSQL | `EXPLAIN (ANALYZE, BUFFERS)` | https://www.postgresql.org/docs/current/sql-explain.html · https://www.postgresql.org/docs/current/using-explain.html |
| MySQL 8.4 | `EXPLAIN FORMAT=JSON` | https://dev.mysql.com/doc/refman/8.4/en/explain.html · https://dev.mysql.com/doc/refman/8.4/en/explain-output.html |
| SQLite | `EXPLAIN QUERY PLAN` | https://www.sqlite.org/eqp.html |

## 보조 자료

- **Use The Index, Luke!** (쿼리 플랜 해석 가이드): https://use-the-index-luke.com/sql/explain-plan
- **PEV2** (PostgreSQL EXPLAIN 시각화, PostgreSQL License): https://github.com/dalibo/pev2
