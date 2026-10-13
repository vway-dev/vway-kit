# 모듈 사전검사 초안 절차

`/vdev-init` Step 2.6 이 `vdev-config.modules[]`(모노레포 모듈 단위 사전검사 설정) 초안을
작성할 때 따르는 절차. SKILL.md 본문이 이 파일을 가리킴.

## 1. harness 설치 시 모듈 초안 작성

harness 가 설치돼 있으면(Step 2.6 의 harness 감지 기준 참고) SSOT 를 읽어 modules 초안을
작성함:

1. `docs/code-style/<stack>.md` 의 "툴체인·설정"·베스트 프랙티스의 "보안" 렌즈 섹션과
   `services/*/CLAUDE.md`(모듈별 SSOT)를 읽어 모듈별 언어·도구 파악.
2. 모듈마다 `path` 와 `checks`(lint/static/import_lint/test/security 중 해당
   언어에 있는 것만) 충전. 스캐폴드 하위 폴더(`tests/` 등)로 test 경로 추정.
   - lint/static/import_lint/test → 모든 커밋(레이어2 vdev 게이트, 변경 모듈) 시점 적용
   - security → staging·release 승격 시점 적용
   - `checks` 는 관습 키 외에 임의 이름의 커스텀 검사도 수용. 값은 문자열(기본
     every-commit) 또는 확장 형식 `{ run: <명령>, when: <every-commit|promotion> }`.
     잘못된 `when` 값은 `report_check_timing` 이 셋업 보고(`[checks 타이밍 점검]`)에
     경고로 표면화하므로, 경고가 뜨면 config 의 `when` 값을 고치도록 안내.
3. **SSOT 에서 도구를 못 찾거나 모호하면 ask the user (structured choice) 로 확인**(추측 금지).
4. 작성한 초안은 `vdev-config.yaml` 의 `modules:` 섹션에 삽입한다(Edit — PyYAML
   round-trip 금지, 포맷/주석 보존). 리서치 결과는 기본값이며 사람이 config 에서
   수정; config 가 최종 권한.

## 2. 구버전 `test.command` 처리

첫 실행·재실행 모두 적용(Step 2 의 `[폐기 필드 점검]` 보고가 전역 `test.command` 를
표시하면 재실행에서도 **반드시** 수행 — 마이그레이션은 정의상 재실행이므로 이 단계를
첫 실행에만 묶으면 잔재가 영영 안 지워짐). `vdev-config.yaml` 에 전역 `test.command`
필드가 남아 있으면 아래 순서로 처리함:

1. **명령을 끝까지 추적.** `test.command` 값이 스크립트/간접 호출을 가리키면
   (예: `bash scripts/test.sh`, `make test`, `npm test`, `just test` 등) 그 대상을
   Read 로 열어 **실제로 실행되는 테스트 명령** 확인. 그 스크립트가 다시 다른
   스크립트·Makefile 타깃·`package.json` scripts·`justfile` 레시피를 부르면 **연쇄를
   끝까지 따라갈 것**. 목표는 "이 명령이 실제로 어느 경로의 어떤 테스트 러너를 돌리는가"를
   확정하는 것 — 이래야 modules 매핑이 정확함.
2. **modules 커버리지 확인.** 추적 결과가 기존 `modules[].checks.test` 중 하나로 이미
   커버되는지 확인(같은 모듈 경로 + 같은 테스트 러너면 커버로 봄). 커버되면 4로.
3. **미커버면 modules 로 먼저 이전.** 커버되지 않으면 추적한 명령을 근거로
   `modules[].checks.test` 초안을 만들고(경로는 그 명령이 대상하는 폴더로 추정), 스택이
   모호하면 ask the user (structured choice) 로 확인 후 `modules:` 에 Edit 로 삽입.
   **커버리지 확보 전 전역 `test:` 제거 금지**(검증 공백 방지).
   modules 섹션이 없으면(harness 부재 등) 먼저 `modules:` 섹션 생성.
4. **폐기된 전역 `test:` 블록 제거.** modules 커버리지가 확보된 상태에서
   Ask the user (structured choice) 로 "폐기된 전역 `test:` 블록을 제거할지"(기본 예) 확인받아 **동의 시
   Edit 로 그 `test:` 블록만 제거**한다(`command`·`coverage_threshold`·해당 주석 포함).
   사용자가 거부하면 남겨 두고 폐기 예정임만 안내한다(무단 삭제 금지 — config 는
   호스트/팀 소유).
