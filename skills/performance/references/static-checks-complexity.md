# 복잡도 정적 분석 — lizard 기반 (언어 무관)

> **중요**: 순환복잡도(Cyclomatic Complexity, CC)는 분기 수이며 **Big-O 시간복잡도가 아님**.
> CC 가 높아도 O(n) 가능, CC 가 낮아도 O(n²) 가능. 두 개념 혼용 금지.
> 아래 lizard 결과는 재귀·중첩루프의 **근사 프록시**일 뿐 — CC 가 높은 함수를 우선
> 검토 대상으로 좁혀줄 뿐, "재귀"·"3중 중첩"을 직접 증명하지는 않음. 최종 판정은
> 해당 함수를 직접 읽거나 런타임 프로파일러로 확인.

## 정적 복잡도 도구 (다국어 지원, 정상 동작 확인됨)

| 도구 | 지원 언어 | 라이선스 | 출처 |
|---|---|---|---|
| lizard | Python·C/C++·Java·JS·C#·Ruby·Go 등 다중 | MIT | https://github.com/terryyin/lizard |
| radon | Python | MIT | https://radon.readthedocs.io/ |

## 사용법 — 복잡도 높은 함수 우선순위화

```bash
# 순환복잡도(CCN) 10 초과 함수만 경고 형식으로 출력 (재귀/중첩루프 후보 우선순위화)
lizard . -C 10 -w
```

설치가 없으면 안내함:

```bash
pip install lizard
```

> **실측 확인(2026-07, lizard 1.23.0)**:
> - `-w`(`--warnings_only`)는 임계값(`-C`) 초과 함수만 `파일:줄: warning: ...` 한 줄 형식으로
>   추출 — 전체 함수 목록에서 눈으로 찾을 필요 없음.
> - **경고가 하나라도 있으면 lizard 는 exit code 1 반환**(경고 0건이면 0). 이건 도구
>   실행 실패가 아니라 "임계값 초과 함수가 있다"는 정상 신호 — 이 커맨드를 스크립트에서
>   `set -e` 나 `&&` 체인에 넣으면 "경고 있음"이 "명령 실패"로 오처리되니 주의.
> - `--sort cyclomatic_complexity`로 전체 함수 목록을 정렬할 수도 있지만 **오름차순만
>   지원**(내림차순 옵션 없음) — 목록이 길면 CCN 높은 함수가 맨 아래. 우선순위화가
>   목적이면 정렬보다 위 `-w` 방식 권장.

출력 컬럼: `NLOC`(코드 라인)·`CCN`(순환복잡도)·`token`·`PARAM`·`length`·`location`.
**CCN 이 높은 함수를 사람이 직접 열어** 재귀 호출·3중 이상 중첩 루프 유무 확인 —
lizard 자체는 "재귀"·"중첩 깊이"를 별도 필드로 보고하지 않음.

## 런타임 프로파일러 (검증 위임)

| 언어 | 도구 | 라이선스 | 출처 |
|---|---|---|---|
| Python | py-spy | MIT | https://github.com/benfred/py-spy |
| Python | cProfile (내장) | PSF | https://docs.python.org/3/library/profile.html |
| Python | Scalene | Apache-2.0 | https://github.com/plasma-umass/scalene |
| Node.js | --prof (내장 V8) | MIT(Node) | https://nodejs.org/learn/getting-started/profiling |
| Node.js | 0x | MIT | https://github.com/davidmarkclements/0x |
| Node.js | Clinic.js | MIT *(유지보수 비활성 주의)* | https://github.com/clinicjs/node-clinic |
| Go | runtime/pprof (내장) | BSD-3 | https://pkg.go.dev/runtime/pprof |
| Go | net/http/pprof (내장) | BSD-3 | https://pkg.go.dev/net/http/pprof |
| Java | async-profiler | Apache-2.0 | https://github.com/async-profiler/async-profiler |
| Java | JDK Flight Recorder (JFR) | GPL+CE | https://docs.oracle.com/en/java/java-components/jdk-mission-control/9/user-guide/using-jdk-flight-recorder.html |
