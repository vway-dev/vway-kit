# OpenAPI 발견 + API 부하 측정 + 리포트 표준

> SSOT: 스펙 §10.5~§10.6 사전 리서치 기준 (2026-06). 출처 URL·라이선스 명시.

---

## 0. BASE_URL 확인 (playwright-scaffold Step 1과 동일 순서)

BASE_URL 하드코딩 금지. 아래 순서로 후보를 모으고 **마지막엔 반드시 사용자에게 확인**
(추측 단정 금지 — 질문은 `performance` 스킬의 Interaction 규칙을 따름).

```bash
# 1) playwright.config 의 use.baseURL
ls playwright.config.* 2>/dev/null && grep -n "baseURL" playwright.config.* 2>/dev/null
# 2) docker-compose 포트 매핑
grep -nE '^\s*-\s*"?[0-9]+:[0-9]+' docker-compose.y*ml compose.y*ml 2>/dev/null
# 3) .env 의 PORT / BASE_URL / 공개 URL
grep -nhE '^(PORT|BASE_URL|VITE_[A-Z_]*URL|NEXT_PUBLIC_[A-Z_]*URL)=' .env .env.* 2>/dev/null
# 4) 프레임워크 설정 / dev 스크립트 포트
grep -nE 'server\s*:|port\s*:' vite.config.* next.config.* 2>/dev/null
grep -nE '"dev"\s*:.*(--port|-p )\s*[0-9]+' package.json 2>/dev/null
```

수집한 후보가 여러 개면 ask the user (structured choice) 로 제시해 확정. 후보가 없으면 프레임워크 기본
포트(FastAPI=8000, Spring Boot=8080, Rails=3000, ASP.NET=5000/7000 등)를 후보로 사용자 확인.
`BASE_URL` 은 **Bash 호출 사이에 안 남음**(호출마다 새 셸). 확정한 값은 그것을 쓰는 커맨드와
**같은 호출의 첫 줄 `BASE_URL=` 에 삽입**(§1의 발견 스크립트, k6 실행의 `-e BASE_URL=`).

---

## 1. OpenAPI 스펙 자동 발견

### 1.1 후보 경로 순서

서버가 실행 중이면 아래 순서로 GET. 첫 성공 응답 사용.

| 우선순위 | 경로 | 프레임워크 | 출처 |
|---|---|---|---|
| 1 | `/openapi.json` | FastAPI | https://fastapi.tiangolo.com/tutorial/metadata/ |
| 2 | `/v3/api-docs` | springdoc-openapi | https://github.com/springdoc/springdoc-openapi |
| 3 | `/swagger/v1/swagger.json` | ASP.NET Swashbuckle (documentName 기본 `v1`) | https://learn.microsoft.com/en-us/aspnet/core/tutorials/getting-started-with-swashbuckle |
| 4 | `/swagger.json` | 일반 관례 | — |
| 5 | `/api-docs` | 일반 관례 | — |

**ASP.NET documentName 가변 처리**: `/swagger/v1/swagger.json` 실패 시 `/swagger` HTML을
가져와 `<script>` 내 `url: "..."` 패턴을 파싱해 실제 spec URL 추출.

```bash
# 자동 발견 스크립트 (bash)
BASE_URL=       # ← §0 에서 확정한 값을 채운다 (예: http://localhost:8000)
: "${BASE_URL:?§0에서 확정한 BASE_URL이 필요합니다}"
# 아래 k6-load.js 는 이 줄이 찍는 경로 밑에 Write 로 씀: Git Bash 의 /tmp 는 %TEMP% 인데
# Write 도구는 리터럴 /tmp 를 C:\tmp 로 읽어, 여기 어떤 명령도 보지 않는 곳에 씀.
cygpath -m /tmp 2>/dev/null || echo /tmp
SPEC_URL=""
for path in /openapi.json /v3/api-docs /swagger/v1/swagger.json /swagger.json /api-docs; do
  if curl -sf "${BASE_URL}${path}" -o /tmp/openapi_spec.json; then
    SPEC_URL="${BASE_URL}${path}"
    echo "spec found: ${SPEC_URL}"
    break
  fi
done
if [ -z "$SPEC_URL" ]; then
  echo "OpenAPI spec not found — check server is running and spec endpoint is enabled"
  exit 1
fi
```

### 1.2 $ref dereference

`$ref`가 있는 spec 은 도구 처리 전 resolve 필요할 수 있음.

| 도구 | 라이선스 | 용도 | 출처 |
|---|---|---|---|
| prance | MIT | Python — $ref resolve + 유효성 검사 | https://github.com/RonnyPfannschmidt/prance |
| schemathesis | MIT | $ref resolve + contract 테스트 | https://github.com/schemathesis/schemathesis |
| json-schema-faker | MIT | example 값 생성 (JS) | https://github.com/json-schema-faker/json-schema-faker |

### 1.3 example 값 override 규칙

OpenAPI 3.1.1 스펙 기준:

- 필드 레벨 `example` (단수) → 단일 예제값.
- 필드 레벨 `examples` (복수) → 이름 키: `{ value, summary }` 맵.
- 부하 테스트 시 `examples` 중 첫 번째(또는 `default` 키)를 우선 사용.
- `$ref`로 참조된 schema의 example은 참조 해석 후 오버라이드 가능.

출처: https://spec.openapis.org/oas/v3.1.1.html · 3.0→3.1 업그레이드: https://learn.openapis.org/upgrading/v3.0-to-v3.1.html

---

## 2. 부하 도구

### 2.1 1순위: openapi-to-k6 + k6 (AGPL-3.0)

> **라이선스 주의**: openapi-to-k6 와 k6 는 모두 **AGPL-3.0**.
> - **내부 CI/개발 환경 사용**: 무해. AGPL은 내부 사용 시 소스 공개 의무 없음.
> - **회피해야 하는 경우**: 도구 자체를 재배포하거나 SaaS로 호스팅할 때.
> 일반적인 팀 내부 성능 점검 목적이면 AGPL-3.0 도구 사용 가능.

| 도구 | 버전 확인 | 출처 |
|---|---|---|
| openapi-to-k6 | `npx @grafana/openapi-to-k6 --version` | https://github.com/grafana/openapi-to-k6 |
| k6 | `k6 version` | https://grafana.com/docs/k6/latest/ |

> **실측 확인(2026-07)**: `npx openapi-to-k6`(스코프 없이)는 npm 레지스트리에 그 이름의
> 패키지가 없어 **404 실패** — 반드시 `npx @grafana/openapi-to-k6` 로 스코프를 붙여야
> 함. 사전 `npm install -g @grafana/openapi-to-k6` 를 해뒀다면 `openapi-to-k6`(스코프 없이)가
> PATH에 잡히므로 그때는 바로 실행 가능.

**설치 (없을 경우):**
```bash
# openapi-to-k6 — 전역 설치(스코프 없는 이름이 PATH에 잡힘) 또는 npx 직접(스코프 필수)
npm install -g @grafana/openapi-to-k6  # 또는 매번 npx @grafana/openapi-to-k6 (아래 예시 방식)

# k6 (OS별)
# macOS: brew install k6
# Linux: https://grafana.com/docs/k6/latest/set-up/install-k6/
# Windows: choco install k6  또는 공식 MSI/zip(https://github.com/grafana/k6/releases)
```

**실행 (각 엔드포인트 100회):**

> ⚠️ `k6 run --iterations N`은 **스크립트 전체** 실행 횟수이지 엔드포인트별 횟수가 **아님**.
> 엔드포인트가 여러 개면 단순 `--iterations 100` 은 "각 API 100회"를 **미보장**.
> **각 엔드포인트를 정확히 100회** 측정하려면 k6 **scenarios**로 엔드포인트마다 별도
> 시나리오(`iterations: 100`)를 둠. openapi-to-k6가 operation별 **메서드를 가진 클라이언트
> 클래스**를 생성하므로(단일 함수 export가 아님), 그 인스턴스 메서드를 시나리오 `exec`
> 함수 안에서 호출.

> **실측 확인(2026-07, openapi-to-k6 0.4.1 + k6 2.1.0)**: 아래 커맨드·코드는 실제
> `npx @grafana/openapi-to-k6`로 클라이언트를 생성하고 실제 k6 바이너리로 실행해 확인.
> CLI 시그니처는 `openapi-to-k6 <openApiPath> <outputDir>`이며 **`-o` 플래그는 없고 두
> 번째 인자는 파일이 아니라 디렉터리**다. 생성 결과는 `<outputDir>/<ApiTitle>Api.ts`
> **한 파일**(`mode` 기본값 `single`)이며 `.js`가 아니라 **`.ts`**다 — k6는 `.ts`를
> 네이티브로 임포트해 실행하므로 별도 트랜스파일 단계 불요.

```bash
# 1) OpenAPI → k6 클라이언트 생성 (스코프 패키지명 필수 — `npx openapi-to-k6`는 404)
npx @grafana/openapi-to-k6 /tmp/openapi_spec.json /tmp/k6-client
# 생성된 파일과 export된 클라이언트 클래스명 확인 (예: FixtureApiClient)
CLIENT_FILE=$(find /tmp/k6-client -name '*.ts' | head -1)
grep -oP 'export class \K\w+' "$CLIENT_FILE"
```

```javascript
// <§1 이 찍은 /tmp 경로>/k6-load.js — 엔드포인트별 시나리오(각 100 iterations)
// import 경로·클래스명은 위 CLIENT_FILE·grep 결과를 그대로 옮긴 것 — 매 스펙마다 값이 다르다.
import { FixtureApiClient } from './k6-client/fixtureApi.ts';
// BASE_URL 은 -e 로 주입. 폴백 기본값을 두면 -e 를 빠뜨렸을 때 §0에서 확정한 대상이 아니라
// localhost 를 조용히 때리고, 그 수치가 리포트에 그대로 실림 — 없으면 큰 소리로 정지.
if (!__ENV.BASE_URL) throw new Error('BASE_URL 미지정 — k6 run -e BASE_URL=<§0에서 확정한 값>');
const client = new FixtureApiClient({ baseUrl: __ENV.BASE_URL });

export const options = {
  scenarios: {
    getUsers:    { executor: 'shared-iterations', vus: 10, iterations: 100, exec: 'getUsers' },
    createOrder: { executor: 'shared-iterations', vus: 10, iterations: 100, exec: 'createOrder' },
  },
};
export function getUsers()    { client.getUsers(); }    // openapi-to-k6가 생성한 인스턴스 메서드(operationId 기준) 호출
export function createOrder() { client.createOrder(); }
```

> `shared-iterations`는 `iterations` 총량을 `vus` 풀에 나눠 배분하므로 총 실행 횟수가 정확히
> `iterations`(=100). `per-vu-iterations` 는 VU마다 `iterations` 를 반복해 총
> `vus × iterations`(=1000)가 되므로 "엔드포인트당 정확히 100회" 약속과 모순됐다(실측으로
> 재현: 카운터 서버 기준 `shared-iterations`=100건, `per-vu-iterations`=1000건).

```bash
# 2) 실행 + JSON 결과 (엔드포인트별 100회)
BASE_URL=       # ← §0 에서 확정한 값 (호출마다 새 셸이라 여기 다시 채운다)
: "${BASE_URL:?§0에서 확정한 BASE_URL이 필요합니다}"
k6 run -e BASE_URL="$BASE_URL" --out json=/tmp/k6-result.json /tmp/k6-load.js
```

> 엔드포인트가 많으면 위 `scenarios` 를 스펙의 (method, path) 목록에서 **프로그램으로 생성**
> (§2.1.1). 단일 엔드포인트뿐이면 `k6 run --iterations 100`로 충분하다(그때만 전체=엔드포인트).

### 2.1.1 엔드포인트별 시나리오 자동 생성

OpenAPI spec 의 (method, path, operationId) 목록으로부터 `scenarios` 객체 자동 생성
(엔드포인트가 많을 때 수동 나열 회피). **반드시 `shared-iterations` 사용** —
`per-vu-iterations`로 바꾸면 위에서 고친 10배 부하 버그가 재발한다(실측 확인 완료, 위 참조).

> **사전 단계**: 클라이언트 생성(`npx @grafana/openapi-to-k6 ...`)은 셸에서 먼저 실행해 둘 것.
> 생성기 스크립트 안에서 `child_process` 로 `npx` 재호출 금지 — Windows 에서
> `npx`는 `.cmd` 셸 래퍼라 `execFile`류(인자 배열 방식, 셸 인젝션 방지)로는 `ENOENT`가 나고,
> `exec`류(셸 문자열 방식)로 우회하면 커맨드 인젝션 위험. 두 단계로 나누면 이 문제
> 자체가 없다(실측 확인: 아래처럼 나누니 정상 동작, 합쳤을 때 Windows에서 ENOENT 재현).

```bash
# 1) 클라이언트 생성 (셸에서 직접 — 스코프 패키지명 필수)
npx @grafana/openapi-to-k6 /tmp/openapi_spec.json /tmp/k6-client
```

```javascript
// generate-k6-scenarios.js — 생성된 클라이언트 + OpenAPI spec → k6 scenarios 자동 생성
const fs = require('fs');
const path = require('path');

// /tmp 는 인자로 받음 — node 는 네이티브 프로세스라 Windows 에서 리터럴 '/tmp' 를 C:\tmp 로 읽음.
const TMP = process.argv[2] || '/tmp';
const SPEC_PATH = path.join(TMP, 'openapi_spec.json');
const CLIENT_DIR = path.join(TMP, 'k6-client');
const ITERATIONS = 100;
const VUS = 10;

// 클라이언트 파일·export 클래스명은 title→클래스명 변환을 직접 재구현하지 않고
// 실제 생성물에서 읽는다(변환 규칙이 버전마다 바뀔 수 있어 재구현은 깨지기 쉽다).
const clientFile = fs.readdirSync(CLIENT_DIR).find((f) => f.endsWith('.ts'));
const clientPath = path.join(CLIENT_DIR, clientFile);
const clientSrc = fs.readFileSync(clientPath, 'utf8');
const className = clientSrc.match(/export class (\w+)/)[1];

const spec = JSON.parse(fs.readFileSync(SPEC_PATH, 'utf8'));
const scenarios = {};
const execFns = [];

for (const [p, methods] of Object.entries(spec.paths || {})) {
  for (const [method, op] of Object.entries(methods)) {
    if (!['get', 'post', 'put', 'delete', 'patch'].includes(method)) continue;
    const opId = op.operationId || `${method}_${p.replace(/[^a-zA-Z0-9]/g, '_')}`;
    scenarios[opId] = {
      executor: 'shared-iterations', // 정확히 ITERATIONS회 실행 보장 (vus×iterations 아님)
      vus: VUS,
      iterations: ITERATIONS,
      exec: opId,
    };
    execFns.push(`export function ${opId}() { client.${opId}(); }`); // openapi-to-k6가 생성한 인스턴스 메서드 호출
  }
}

const out = `import { ${className} } from './k6-client/${clientFile}';
if (!__ENV.BASE_URL) throw new Error('BASE_URL 미지정 — k6 run -e BASE_URL=<§0에서 확정한 값>');
const client = new ${className}({ baseUrl: __ENV.BASE_URL });
export const options = { scenarios: ${JSON.stringify(scenarios, null, 2)} };
${execFns.join('\n')}
`;
fs.writeFileSync(path.join(TMP, 'k6-load.generated.js'), out);
console.log(`생성 완료: ${Object.keys(scenarios).length}개 엔드포인트, 각 ${ITERATIONS}회(shared-iterations), 클라이언트 클래스: ${className}`);
```

```bash
# 2) 시나리오 파일 생성 + 실행
BASE_URL=       # ← §0 에서 확정한 값 (호출마다 새 셸이라 여기 다시 채운다)
: "${BASE_URL:?§0에서 확정한 BASE_URL이 필요합니다}"
node generate-k6-scenarios.js "$(cygpath -m /tmp 2>/dev/null || echo /tmp)"
k6 run -e BASE_URL="$BASE_URL" --out json=/tmp/k6-result.json /tmp/k6-load.generated.js
```

> **실측 검증(2026-07)**: 위 2단계 그대로(fixture spec 1개 엔드포인트, openapi-to-k6 0.4.1,
> k6 2.1.0) 실행해 로컬 카운터 서버에 정확히 100건이 도달함을 확인.

### 2.2 MIT 폴백 (AGPL 회피 시)

| 도구 | 라이선스 | 특징 | 출처 |
|---|---|---|---|
| oha | MIT | Rust 구현, JSON 출력 지원 (`-j`), schema 유사 지표 | https://github.com/hatoo/oha |
| autocannon | MIT | Node.js, JSON 출력, p99 지원 | https://github.com/mcollina/autocannon |
| vegeta | MIT | targets 파일로 다중 엔드포인트, JSON 리포트 | https://github.com/tsenart/vegeta |

**oha 예 (엔드포인트 직접 순회):**
```bash
# 각 엔드포인트 100회
oha -n 100 -c 10 -j http://localhost:8000/users > /tmp/oha-users.json
oha -n 100 -c 10 -j http://localhost:8000/orders > /tmp/oha-orders.json
```

**vegeta 예 (targets 파일):**
```bash
# targets.txt
echo "GET http://localhost:8000/users" >> targets.txt
echo "GET http://localhost:8000/orders" >> targets.txt

vegeta attack -targets=targets.txt -rate=10 -duration=10s \
  | vegeta encode --to=json \
  | vegeta report --type=json > /tmp/vegeta-result.json
```

### 2.3 참고: 단순 단일 URL 도구 (p99 미지원 등 — 권장 안 함)

| 도구 | 라이선스 | 한계 | 출처 |
|---|---|---|---|
| hey | Apache-2.0 | CSV 출력만, p99 미지원 | https://github.com/rakyll/hey |
| wrk | Apache-2.0 | p95 미제공, Lua 스크립트 필요 | https://github.com/wg/wrk |
| ab (Apache Bench) | Apache-2.0 | 단일 URL, 통계 제한 | https://httpd.apache.org/docs/2.4/programs/ab.html |

---

## 3. 리포트 표준

### 3.1 필수 지표 (평균 단독 금지)

> **원칙**: 평균(mean/avg)은 롱테일을 숨김. 반드시 백분위 분포를 함께 보고.
> 백분위는 평균 내지 않는다(비가산성) — 집계 레벨에 따라 백분위가 달라지므로
> 개별 요청 레벨에서만 계산.
>
> 출처: https://orangematter.solarwinds.com/2016/11/18/why-percentiles-dont-work-the-way-you-think/

| 지표 | 설명 | 필수 |
|---|---|---|
| p50 (중앙값) | 절반의 요청이 이 이하 | ✓ |
| p95 | 95%의 요청이 이 이하 | ✓ |
| p99 | 99%의 요청이 이 이하 | ✓ |
| p99.9 | 99.9%의 요청이 이 이하 (롱테일 포착) | 권장 |
| throughput (RPS) | 초당 처리 요청 수 | ✓ |
| VU (동시성) | 동시 가상 사용자 수 | ✓ |
| 에러율 | 5xx·연결 실패 비율 (%) | ✓ |
| **SLO 대비 PASS/FAIL** | 사전 정의 SLO와 비교한 판정 | ✓ |

SLO 참고: https://sre.google/sre-book/service-level-objectives/

### 3.2 Four Golden Signals 골격

출처: https://sre.google/sre-book/monitoring-distributed-systems/

```
### Golden Signals 요약
- **Latency (지연)**: p50 / p95 / p99 / p99.9 — SLO 기준 PASS/FAIL
- **Traffic (트래픽)**: RPS·VU·부하 모델(constant/ramp-up/spike)
- **Errors (에러율)**: 에러율 % · 에러 종류(5xx/4xx/timeout)
- **Saturation (포화도)**: CPU·메모리 측정 가능 시 기록 (선택)
```

### 3.3 측정 메타 (필수 기록)

```
측정 메타:
- 도구·버전: openapi-to-k6 x.y.z + k6 0.52.x
- 부하 모델: constant / ramp-up / spike
- 지속시간: Xs (또는 iterations=100 per endpoint)
- VU (동시성): N
- warm-up 제외: 첫 M회 제외 여부 명시
- CO(Coordinated Omission) 보정: 적용/미적용 명시
- 실행 환경: 로컬 / CI / 네트워크 오버헤드 유무
```

### 3.4 통계 관례

#### warm-up 제외

JVM·JIT·커넥션풀 초기화로 첫 요청이 느림. warm-up 구간은 결과에서 제거.
출처: https://www.azul.com/blog/ramps-in-performance-tests-best-practices/

#### Coordinated Omission (CO) 보정

클라이언트가 응답 대기 중 다음 요청을 보내지 않으면, 느린 응답이 숨겨짐.
HdrHistogram 기반 CO 보정이 가능한 도구(k6의 일부 설정, vegeta)를 사용하면 실제 지연 분포를
더 정확히 측정. 보정 여부는 반드시 메타에 명시.
출처: https://github.com/HdrHistogram/HdrHistogram

The Tail at Scale 참고(고백분위 중요성): https://cacm.acm.org/research/the-tail-at-scale/

#### 백분위 비가산성

서비스 A의 p99 + 서비스 B의 p99 ≠ 전체 p99. 요청 레벨 데이터에서 직접 집계 필수.
출처: https://orangematter.solarwinds.com/2016/11/18/why-percentiles-dont-work-the-way-you-think/

### 3.5 리포트 템플릿

```markdown
## API 부하 측정 결과 — <날짜>

**측정 메타**
- 도구: openapi-to-k6 <버전> + k6 <버전>
- 부하 모델: constant / iterations=100 per endpoint (executor: shared-iterations — vus 풀에 총량 배분, per-vu-iterations 아님)
- VU: 10 / warm-up: 첫 10회 제외 / CO 보정: 미적용
- 환경: 로컬 (서버: localhost:8000)

**SLO 기준**
| 엔드포인트 | p99 SLO | 에러율 SLO |
|---|---|---|
| 전체 | ≤ 500ms | ≤ 1% |

**결과**
| 엔드포인트 | p50 | p95 | p99 | p99.9 | RPS | VU | 에러율 | SLO 판정 |
|---|---|---|---|---|---|---|---|---|
| GET /users | 12ms | 45ms | 120ms | 350ms | 850 | 10 | 0.0% | PASS |
| POST /orders | 80ms | 350ms | 890ms | 2100ms | 210 | 10 | 1.2% | FAIL |

**Golden Signals**
- Latency: POST /orders p99 890ms > SLO 500ms ← **주목**
- Traffic: RPS 850 (GET) / 210 (POST)
- Errors: POST /orders 1.2% 에러율 > SLO 1%
- Saturation: 측정 안 함

**권고**
- POST /orders: p99 초과 — 쿼리 플랜 확인 및 DB 인덱스 추가 검토
- POST /orders: 에러율 초과 — 5xx 로그 확인
```

---

## 4. 라이선스 요약

| 도구 | 라이선스 | 내부 CI 사용 | 재배포/SaaS |
|---|---|---|---|
| openapi-to-k6 | AGPL-3.0 | 무해 | 회피 필요 |
| k6 | AGPL-3.0 | 무해 | 회피 필요 |
| oha | MIT | 무해 | 무해 |
| autocannon | MIT | 무해 | 무해 |
| vegeta | MIT | 무해 | 무해 |
| prance | MIT | 무해 | 무해 |
| schemathesis | MIT | 무해 | 무해 |
| json-schema-faker | MIT | 무해 | 무해 |
| hey | Apache-2.0 | 무해 | 무해 |
| wrk | Apache-2.0 | 무해 | 무해 |
| ab | Apache-2.0 | 무해 | 무해 |
