#!/usr/bin/env python3
"""Build throwaway projects that put a skill's judgement under test, and print the
prompt + pass criteria for each.

`tests/skill_docs/` proves a skill's *commands* work and that the judgement snippets
they carry (`test_report_parsing.py`) verdict the way they claim. It cannot prove the
agent reading the skill reaches the right conclusion — that needs a model. This script
supplies the other half: an isolated fixture whose correct answer is known in advance,
so a fresh agent's behaviour is checkable rather than merely plausible.

    python3 scripts/skill_sandbox.py --list
    python3 scripts/skill_sandbox.py custom-testdir          # build + print the prompt
    python3 scripts/skill_sandbox.py --all --out-dir /tmp/sb

Run the printed prompt in a *fresh* agent with no memory of this conversation, cwd set
to the built sandbox. Then score the transcript against `expect` / `reject`.

**Coverage is scoped to skills a fixture can decide.** A scenario is worth writing only
where a throwaway directory can create the state that fixes the skill's answer in
advance — that covers /integration, /playwright-scaffold, /performance, /doc-sync,
/wiki-init, /commit and /vdev — the last only for the state it routes on, a working tree
with pending changes. Every other skill is registered in OUT_OF_REACH below with the reason a
fixture cannot reach it, and tests/skill_docs/ fails if any skill is neither covered
nor registered.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Scenario:
    name: str
    skill: str
    why: str
    prompt: str
    expect: list[str]
    reject: list[str]
    files: dict[str, str] = field(default_factory=dict)
    dirs: list[str] = field(default_factory=list)
    # { "<픽스처 내 상대경로>": "<이 저장소 내 상대경로>" } — 인라인 문자열로 쓰는 대신
    # 그대로 복사하는 파일. 호스트가 /vdev-init 으로 받는 게이트 스크립트용. 스킬이
    # 문서화된 호스트 경로로 그것을 실행한다면 실제로 거기 있어야 하고, 900줄짜리
    # 스크립트를 문자열로 인라인하면 원본이 바뀌는 순간 낡음.
    copy_from_repo: dict[str, str] = field(default_factory=dict)
    # 픽스처를 전부 커밋된 git 저장소로 시드함. git 상태를 읽는 스킬 — wiki-init 은
    # 그래프를 인덱스에서 만듦 — 에게 맨 디렉터리는 실제 경로가 아니라 폴백 경로를
    # 측정하게 함. 기본값 off: `git init` 은 빌드마다 서브프로세스를 쓰는데, 다른
    # 시나리오는 답이 git 상태에 달려 있지 않음.
    git: bool = False
    # git 시드 커밋 **이후에** 쓰는 파일 — 워킹트리를 더럽힌 채로 남김. `git` 시드는
    # 전부 커밋하므로 그것만으로는 트리가 깨끗하고, 커밋할 것이 있어야만 답이 정해지는
    # 스킬에게 깨끗한 트리는 빈 디렉터리와 같음(발동 전에 "커밋할 게 없다" 로 끝남).
    # `git: True` 없이 쓰면 의미가 없음.
    git_dirty: dict[str, str] = field(default_factory=dict)


PLAYWRIGHT_CONFIG_E2E = """\
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://localhost:5173' },
});
"""

PLAYWRIGHT_CONFIG_DEFAULT = """\
import { defineConfig } from '@playwright/test';
export default defineConfig({
  use: { baseURL: 'http://localhost:3000' },
});
"""

SPEC = """\
import { test, expect } from '@playwright/test';
test('placeholder', async ({ page }) => { await page.goto('/'); });
"""

WEB_PACKAGE_JSON = json.dumps(
    {
        "name": "sandbox-web",
        "devDependencies": {"@playwright/test": "^1.48.0", "vite": "^5.0.0"},
        "dependencies": {"react": "^18.3.0"},
    },
    indent=2,
)

CLI_PACKAGE_JSON = json.dumps(
    {"name": "sandbox-cli", "bin": {"sbx": "./bin/sbx.js"}, "dependencies": {}}, indent=2
)

# 채점자가 split 과 stamp 를 가르는 데 쓰는 문장. `docs/backend.md` 의 두 H2 절 중 하나에만
# 들어 있어서, 이 문장이 어디에 남는지가 문서가 쪼개졌는지 front matter 만 찍혔는지를 말해
# 줌: 올바른 실행은 그 자리에 링크를 남기고 주장 자체는 인증 노드로 옮김. 절 전체가
# 아니라 한 문장인 것은 의도적 — 재포맷된 블록은 여러 줄짜리 바늘을 빠져나감.
# **expect 목록이 이 문장을 문자 그대로 인용함**: 채점이 사람 눈이라, 여기 상수로만
# 두고 판정 문구에서 지목하지 않으면 채점자는 바늘의 존재조차 모름.
WIKI_JWT_CLAIM = "액세스 토큰은 15분 뒤 만료된다."

WIKI_BACKEND_DOC = f"""\
# Backend

## JWT 인증

{WIKI_JWT_CLAIM} 리프레시 토큰은 30일을 살고 사용할 때마다 회전하므로, 탈취된 리프레시
토큰은 한 번만 쓸 수 있다.

## Postgres 스키마

`users` 가 신원 컬럼을 갖고, `sessions` 는 리프레시 토큰당 한 행을 들고 삭제 시 cascade 한다.
"""


# 산문 규칙이 이름 대는 실패를 한 파일에 전부: author 태그·변경 이력·수정일을 인 헤더,
# 아랫줄을 풀어 쓴 주석 둘, 어떻게를 설명하는 독스트링, 그리고 다른 파일로 건 줄 앵커.
# 여기 주석 기호와 따옴표는 픽스처의 바이트이지 이 모듈 자신의 산문이 아님 — 문자열
# 리터럴은 `python_prose` 에게 코드임.
PROSE_REVIEW_MODULE = '''"""Order pricing.

@author  j.doe
Last updated: 2026-08-14
Changelog:
  2026-08-14  split the discount table out of price()
  2026-07-02  first cut
"""

DISCOUNTS = {"gold": 0.2, "silver": 0.1}


def discount_for(tier):
    """Look the tier up in DISCOUNTS and return what is there.

    Does a dict lookup, falling back to 0.0 when the key is absent.
    """
    # read the discount out of the dict
    return DISCOUNTS.get(tier, 0.0)


def price(amount, tier):
    # multiply the amount by one minus the discount
    net = amount * (1 - discount_for(tier))
    # round to two places, the same way billing/invoice.py:118 does
    return round(net, 2)
'''


SCENARIOS: list[Scenario] = [
    Scenario(
        name="custom-testdir",
        skill="integration",
        why=(
            "스위트가 비표준 testDir 아래 있다. ./tests 를 가정하는 에이전트는 케이스 0개로 "
            "보고하고 실제 스위트 위에 스타터 smoke 를 스캐폴딩한다 — 이 픽스처가 잡으려는 "
            "바로 그 회귀다."
        ),
        prompt="이 프로젝트에 통합 검증을 실행하고 결과를 보고하라.",
        expect=[
            "playwright.config 에서 testDir 를 읽는다 (./e2e 로 해석)",
            "e2e/ 아래 기존 케이스 2개를 찾는다",
            "기존 스위트를 실행하거나 실행을 시도한다",
        ],
        reject=[
            "케이스 0개로 보고한다",
            "playwright-scaffold 를 호출하거나 main.smoke.spec 을 생성한다",
            "testDir 를 먼저 해석하지 않고 ./tests 를 뒤진다",
        ],
        files={
            "playwright.config.ts": PLAYWRIGHT_CONFIG_E2E,
            "package.json": WEB_PACKAGE_JSON,
            "e2e/checkout.spec.ts": SPEC,
            "e2e/auth.spec.ts": SPEC,
            "index.html": "<!doctype html><title>sandbox</title>\n",
        },
    ),
    Scenario(
        name="empty-web",
        skill="integration",
        why=(
            "웹 프로젝트인데 케이스가 0개다. 0개는 계속 도달 가능해야 한다 — 스캐폴딩이 "
            "정답인 유일한 상태이므로, custom-testdir 를 고친답시고 아예 스캐폴딩을 하지 "
            "않게 만든 수정은 그 테스트는 통과해도 여기서 실패한다."
        ),
        prompt="이 프로젝트에 통합 검증을 실행하고 결과를 보고하라.",
        expect=[
            "프로젝트를 웹 프론트엔드로 판별한다",
            "기존 케이스가 0개임을 확인한다",
            "playwright-scaffold 로 메인 화면 smoke 생성을 시도한다",
            "baseURL 을 임의로 가정하지 않고 사용자에게 확인을 요청한다",
        ],
        reject=[
            "메인 화면 smoke 대신 사용자 시나리오(로그인, 결제)를 지어낸다",
            "확인 없이 baseURL 을 단정한다",
        ],
        files={
            "playwright.config.ts": PLAYWRIGHT_CONFIG_DEFAULT,
            "package.json": WEB_PACKAGE_JSON,
            "index.html": "<!doctype html><title>sandbox</title>\n",
        },
        dirs=["tests"],
    ),
    Scenario(
        name="misconfigured-testdir",
        skill="integration",
        why=(
            "설정이 testDir 를 존재하지 않는 디렉터리로 가리킨다. find 의 stderr 를 "
            "숨기면 이 상태가 '디렉터리는 있고 비어 있음'과 동일하게 보이는데, 비어 "
            "있음은 스캐폴딩을 승인하는 조건이다. 올바른 답은 설정 오류를 보고하는 "
            "것이지, Playwright 가 보지도 않는 경로에 스펙을 생성하는 게 아니다."
        ),
        prompt="이 프로젝트에 통합 검증을 실행하고 결과를 보고하라.",
        expect=[
            "설정에서 testDir 를 ./e2e 로 해석한다",
            "./e2e 가 존재하지 않음을 알아챈다",
            "설정 오류로 보고한다",
        ],
        reject=[
            "'케이스 0개'로 결론짓고 스캐폴딩한다",
            "./e2e 를 조용히 생성하고 그 안에 스펙을 만든다",
            "디렉터리 누락을 언급하지 않은 채 테스트가 없다고 보고한다",
        ],
        files={
            "playwright.config.ts": PLAYWRIGHT_CONFIG_E2E,
            "package.json": WEB_PACKAGE_JSON,
            "index.html": "<!doctype html><title>sandbox</title>\n",
        },
    ),
    Scenario(
        name="frameworkless-web",
        skill="integration",
        why=(
            "순수 웹 앱: index.html 과 번들러만 있고 허용목록에 있는 프레임워크는 "
            "없다. 판정을 허용목록만으로 내리면 완벽하게 자동화 가능한 브라우저 "
            "앱을 non-web 으로 분류해 사람에게 떠넘기게 된다."
        ),
        prompt="이 프로젝트에 통합 검증을 실행하고 결과를 보고하라.",
        expect=[
            "보조 신호(index.html / vite.config)로 프로젝트를 웹으로 분류한다",
            "Playwright 경로로 진행한다",
        ],
        reject=[
            "허용목록 의존성이 일치하지 않는다는 이유로 non-web 으로 분류한다",
            "사용자에게 수동 시나리오를 요청한다",
        ],
        files={
            "package.json": json.dumps(
                {"name": "vanilla", "devDependencies": {"vite": "^5.0.0"}}, indent=2
            ),
            "vite.config.js": "export default { server: { port: 5173 } };\n",
            "index.html": "<!doctype html><title>vanilla</title>\n",
            "src/main.js": "document.body.textContent = 'hi';\n",
        },
    ),
    Scenario(
        name="non-web-cli",
        skill="integration",
        why=(
            "CLI 는 `bin` 필드가 있고 웹 프레임워크가 없다. 이 스킬은 non-web 을 "
            "사람에게 라우팅하므로, 여기서 Playwright 로 향하는 에이전트는 설명문의 "
            "'web' 이라는 단어를 본문의 판별표보다 앞세운 것이다."
        ),
        prompt="이 프로젝트에 통합 검증을 실행하고 결과를 보고하라.",
        expect=[
            "프로젝트를 non-web(CLI)으로 분류한다",
            "사용자에게 시나리오와 통과 기준을 요청한다",
        ],
        reject=[
            "Playwright 를 설치하거나 실행한다",
            "smoke 테스트를 생성한다",
        ],
        files={
            "package.json": CLI_PACKAGE_JSON,
            "bin/sbx.js": "#!/usr/bin/env node\nconsole.log('hi');\n",
        },
    ),
    Scenario(
        name="scaffold-idempotent",
        skill="playwright-scaffold",
        why=(
            "이전 실행이 이미 main.smoke.spec.ts 를 남겨두었다. 재생성하면 그 이후 "
            "가해진 수정이 모두 날아간다."
        ),
        prompt="이 프로젝트의 메인 화면 smoke 테스트를 생성하라.",
        expect=[
            "기존 main.smoke.spec.ts 를 감지한다",
            "보고하고 쓰기 없이 멈춘다",
        ],
        reject=[
            "main.smoke.spec.ts 를 덮어쓰거나 재생성한다",
        ],
        files={
            "playwright.config.ts": PLAYWRIGHT_CONFIG_E2E,
            "package.json": WEB_PACKAGE_JSON,
            "e2e/main.smoke.spec.ts": SPEC,
        },
    ),
    Scenario(
        name="scaffold-baseurl-unknown",
        skill="playwright-scaffold",
        why=(
            "설정에 baseURL 이 없고 코드베이스는 서로 충돌하는 포트 두 개를 "
            "제시한다(compose 는 8080, dev 스크립트는 5173). 이 스킬은 추측을 "
            "단정하는 것을 금지하므로 에이전트는 반드시 물어야 한다."
        ),
        prompt="이 프로젝트의 메인 화면 smoke 테스트를 생성하라.",
        expect=[
            "코드베이스에서 baseURL 후보를 수집한다(8080 및/또는 5173)",
            "어느 baseURL 이 맞는지 사용자에게 확인을 요청한다",
        ],
        reject=[
            "포트를 하나 골라 확인 없이 사실인 것처럼 단정한다",
        ],
        files={
            "package.json": json.dumps(
                {
                    "name": "sandbox-web",
                    "scripts": {"dev": "vite --port 5173"},
                    "devDependencies": {"@playwright/test": "^1.48.0", "vite": "^5.0.0"},
                    "dependencies": {"react": "^18.3.0"},
                },
                indent=2,
            ),
            "docker-compose.yml": 'services:\n  web:\n    ports:\n      - "8080:80"\n',
            "index.html": "<!doctype html><title>sandbox</title>\n",
        },
    ),
    Scenario(
        name="scaffold-ts-without-tsconfig",
        skill="playwright-scaffold",
        why=(
            "`@playwright/test` 는 자체 TypeScript 를 번들링하므로, TS Playwright "
            "프로젝트에는 tsconfig.json 도 typescript 의존성도 없는 경우가 흔하다. "
            "이 둘만으로 언어를 판단하면 .ts 스위트에 .js 스펙을 떨어뜨리게 된다. "
            "이 픽스처는 그 간극을 드러낸 실제 형태다."
        ),
        prompt="이 프로젝트의 메인 화면 smoke 테스트를 생성하라.",
        expect=[
            ".spec.ts 를 생성한다(playwright.config.ts 자체가 TypeScript 신호다)",
        ],
        reject=[
            "tsconfig.json 과 typescript 의존성이 없다는 이유로 .spec.js 를 생성한다",
        ],
        files={
            "playwright.config.ts": PLAYWRIGHT_CONFIG_E2E,
            "package.json": WEB_PACKAGE_JSON,
            "index.html": "<!doctype html><title>sandbox</title>\n",
        },
        dirs=["e2e"],
    ),
    Scenario(
        name="perf-n-plus-one",
        skill="performance",
        why=(
            "루프 안에 있는 전형적인 Django N+1 에, select_related 로 고칠 수 "
            "있는 상태까지 갖췄다. 이 스킬은 정적으로 플래그만 하고 판정은 런타임 "
            "도구에 위임한다 — grep 만으로 측정된 회귀라고 단언하는 에이전트는 "
            "과잉 주장을 한 것이다."
        ),
        prompt="이 프로젝트에 성능 점검을 실행하라.",
        expect=[
            "Python 스택을 감지한다",
            "views.py 의 N+1 을 플래그한다",
            "'검토 필요'로 표시하거나 최종 판정을 런타임 도구에 위임한다",
            "언어 무관 복잡도 점검도 함께 실행한다",
        ],
        reject=[
            "정적 분석만으로 측정된 지연이나 확정된 쿼리 수를 보고한다",
            "부하 테스트를 실행한다(OpenAPI 스펙도 실행 중인 백엔드도 없다)",
        ],
        files={
            "pyproject.toml": '[project]\nname = "sandbox"\nversion = "0.1.0"\n',
            "app/views.py": (
                "def index(request):\n"
                "    users = User.objects.all()\n"
                "    return [u.profile.name for u in users]  # N+1: profile per user\n"
            ),
            "app/models.py": (
                "class Profile(models.Model):\n"
                "    name = models.CharField(max_length=100)\n\n"
                "class User(models.Model):\n"
                "    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)\n"
            ),
        },
    ),
    Scenario(
        name="doc-sync-drift",
        skill="doc-sync",
        why=(
            "코드는 포트 9090 을 말하는데 문서 두 개가 그것과도, 서로와도 다르다. "
            "이 스킬의 일은 SSOT 를 골라 나머지를 거기에 맞추는 것이지, 다수결을 "
            "택하거나 코드를 다시 쓰는 게 아니다."
        ),
        prompt="포트가 변경됐다. 문서를 동기화하라.",
        expect=[
            ".env.example, README.md, docs/api.md 간의 포트 불일치를 찾아낸다",
            "코드/.env.example 을 진실의 원천으로 취급한다(9090)",
            "무엇을 왜 바꿨는지 보고한다",
        ],
        reject=[
            "app/server.py 를 문서에 맞춰 수정한다",
            "서로 다른 포트를 말하는 문서 두 개를 그대로 둔다",
        ],
        files={
            ".env.example": "PORT=9090\n",
            "app/server.py": "PORT = 9090\n\ndef serve():\n    return PORT\n",
            "README.md": "# Sandbox\n\nThe server listens on port 8080.\n",
            "docs/api.md": "# API\n\nBase URL: `http://localhost:3000`\n",
        },
    ),
    Scenario(
        name="prose-review-comments",
        skill="prose-review",
        why=(
            "app/pricing.py 의 주석 둘은 아랫줄을 되풀이하고, 독스트링은 어떻게를 설명하며, "
            "모듈 헤더는 author 태그·변경 이력·수정일을 인다. 솔깃한 답은 전부를 더 나은 "
            "산문으로 고쳐 쓰는 것이고, 규칙의 답은 그 대부분이 있으면 안 되며 헤더는 "
            "git 의 것이라는 쪽이다."
        ),
        prompt="app/pricing.py 의 주석과 독스트링을 프로젝트 산문 규칙에 맞춰 정리하라.",
        expect=[
            "아랫줄을 풀어 쓴 주석을 고쳐 쓰지 않고 삭제한다",
            "모듈 독스트링에서 author 태그·변경 이력·날짜를 걷어낸다",
            "billing 파일명은 남기고 거기 붙은 줄 번호를 뗀다",
            "독스트링에서 어떻게 설명을 빼고 코드가 못 말하는 것만 남긴다",
        ],
        reject=[
            "자명한 주석을 더 나은 문장으로 고쳐 쓰고 그대로 둔다",
            "읽어서 쓸모 있어 보인다며 변경 이력 헤더를 남긴다",
            "산문을 고치면서 코드 한 줄을 함께 바꾼다",
        ],
        files={
            "app/pricing.py": PROSE_REVIEW_MODULE,
            "README.md": "# Pricing\n\nTier discounts are applied before rounding.\n",
        },
    ),
    Scenario(
        name="wiki-init-migration",
        skill="wiki-init",
        why=(
            "docs/backend.md 는 두 H2 아래 두 개념을 담고 있다. 솔깃한 답은 거기에 front "
            "matter 만 찍고 넘어가는 것이다 — 구조 규칙은 전부 통과하므로 --verify 는 조용하고, "
            "그러면 --neighbors 가 두 주제를 뭉친 덩어리를 모델에 건네 wiki 가 쓸모없어진다. "
            "docs/deploy.md 는 반대 함정이다: H2 가 하나도 없으니 쪼개면 오답이다."
        ),
        # /wiki-init 은 disable-model-invocation 이라 슬래시 커맨드 자체가 프롬프트 —
        # 모델이 매칭할 description 이 없음. 두 절은 5·3단계가 사람에게 묻는 답을 대신하고,
        # 그것이 게이팅하는 판단(무엇을 쪼갤지·id 파생·어떤 관계를 쓸지)은 에이전트 몫으로 남음.
        prompt=(
            "/wiki-init — 후보 문서를 전부 이관하고, 관계는 내 확인을 기다리지 말고 "
            "네가 제안한 대로 진행해."
        ),
        # expect/reject 는 이 저장소에서 **사람이 채점함**(상류에는 기계 채점 골든이
        # 따로 있지만 vway-kit 엔 그 arm 이 없음). 그래서 픽스처가 심은 함정마다 그것을
        # 지목하는 항목이 여기 있어야 함 — 함정만 있고 판별 문구가 없으면 오답이
        # 그대로 통과. 아래 각 항목은 files 의 어떤 함정을 잡는지에 1:1로 대응함.
        expect=[
            "docs/backend.md 를 두 H2 기준으로 쪼개고 각 절 자리에 링크를 남긴다",
            f"추적 문장 `{WIKI_JWT_CLAIM}` 이 docs/backend.md 에서 사라지고 인증 노드에 있다",
            "원본도 노드로 남기고 related 로 쪼개 나간 문서들을 가리킨다",
            "docs/deploy.md 는 통째로 둔다 — H2 가 없으니 쪼갤 것이 없다",
            "각 wiki_id 를 docs/ 기준 상대경로에서 파생하고, used_by 는 절대 쓰지 않는다",
            "docs/index.md 자신도 wiki_id(관례상 index)를 가진 노드로 만든다",
            "쪼갠 노드의 sources 에 app/auth.py·app/db.py 를 sha: null 로 적는다",
            "branches 등 wiki 밖 키를 보존한 채 wiki.enable 만 true 로 바꾼다",
            "새 문서를 git add 한 뒤 --build 하고, --verify 가 통과할 때까지 반복한다",
        ],
        reject=[
            "docs/backend.md 에 쪼개지 않고 front matter 만 준다",
            "절을 옮긴 뒤 docs/backend.md 를 지운다",
            "used_by 나 defects 를 손으로 쓴다",
            "새 wiki_id 를 index 의 related 목록에서 빠뜨린다",
            "index.md 에 related 만 주고 wiki_id 를 빠뜨려 orphan 검사를 통째로 끈다",
            "vdev-config.yaml 을 wiki 블록만 남기고 다시 써 branches 를 날린다",
            "sources sha 에 빈 문자열을 쓰거나 sources 를 map 아닌 리스트로 적는다",
            "--verify 가 빨간 채로 끝내거나, 스테이징 대신 related 를 지워 통과시킨다",
        ],
        files={
            ".claude/vway-kit/config/vdev-config.yaml": (
                "branches:\n"
                "  integration: dev\n"
                "  staging: stage\n"
                "  production: main\n"
                "wiki:\n"
                "  enable: false\n"
                "  root: docs/\n"
                "  index: docs/index.md\n"
                "  max_lines: 400\n"
                "  context_lines: 2000\n"
                "  defect_rule_threshold: 3\n"
            ),
            "docs/index.md": "# Docs\n\n- [Backend](backend.md)\n- [Deploy](deploy.md)\n",
            "docs/backend.md": WIKI_BACKEND_DOC,
            "docs/deploy.md": "# Deploy\n\nmain 에 push 하면 릴리스 워크플로가 나머지를 한다.\n",
            "app/auth.py": "ACCESS_TTL_MIN = 15\nREFRESH_TTL_DAYS = 30\n",
            "app/db.py": "TABLES = ('users', 'sessions')\n",
        },
        # 8단계는 이것을 문자 그대로의 호스트 경로로 실행함. 실제 호스트에선 /vdev-init 이
        # 거기 놓아 줌. 없으면 매 실행이 그 명령에서 실패해, 점수가 에이전트의 대체 경로
        # 추측 실력을 재게 됨.
        copy_from_repo={
            ".claude/vway-kit/scripts/wiki_graph.py": "scripts/wiki_graph.py",
            ".claude/vway-kit/scripts/_vway_paths.py": "scripts/_vway_paths.py",
        },
        # 그래프는 git 인덱스에서 만들어지므로 문서가 추적되고 있어야 함.
        git=True,
    ),
    Scenario(
        name="commit-dirty-tree",
        skill="commit",
        why=(
            "빈 디렉터리에서 이 스킬은 0/25 였다(2026-08-28 vway-kit 실측). 손으로 재현한 "
            "세션에선 에이전트가 repo 가 없다는 것만 확인하고 턴을 끝냈지만, 원인은 분리되지 "
            "않았다 — 같은 날 자매 저장소는 같은 빈 디렉터리 조건에서 6/15 였고, 이쪽 최종 "
            "엔트리의 `lost_to: {vdev: 3}` 는 라우터 경쟁도 함께 걸려 있음을 가리킨다. "
            "어느 쪽이든 커밋 작업의 실제 조건은 저장소이므로 픽스처가 그것을 세운다. "
            "함정은 둘이다: `notes.txt` 는 "
            "이번 변경과 무관하므로 `git add -A` 로 쓸려 들어가면 제목이 diff 에 대해 "
            "거짓이 되고, 반올림 버그 수정이라 type 은 `feat` 이 아니라 `fix` 다."
        ),
        prompt="반올림 버그 고치고 테스트 추가했어. 커밋해줘.",
        expect=[
            "app/pricing.py 와 tests/test_pricing.py 만 경로로 지목해 스테이징한다",
            "notes.txt 는 스테이징하지 않는다 — 이번 변경과 무관하다",
            "type 이 fix 다 — 동작 변경이 아니라 잘못된 반올림의 수정이다",
            "제목이 50자 이내, 본문 각 줄이 72자 이내",
            "본문이 무엇을(int→round)·왜(절사) 를 말한다",
        ],
        reject=[
            "git add -A 또는 git add . 로 전부 스테이징한다",
            "notes.txt 가 커밋에 들어간다",
            "type 을 feat 이나 chore 로 고른다",
            "제목이 50자를 넘는데 그대로 발행한다",
            "무관한 notes.txt 까지 한 제목으로 묶는다(둘이면 커밋도 둘)",
        ],
        files={
            "app/pricing.py": (
                "def total(cents: int, rate: float) -> int:\n"
                '    """세금 포함 합계를 센트 단위로 돌려준다."""\n'
                "    return int(cents * (1 + rate))\n"
            ),
            # tests/ 는 시드에 없음 — 새 테스트 파일이 untracked 로 남아야 "새 파일도
            # 이름으로 스테이징한다" 가 판정 가능해짐.
            "notes.txt": "다음에 볼 것: 환불 흐름 정리\n",
            "README.md": "# sandbox-pricing\n\n주문 합계 계산.\n",
        },
        git=True,
        # 시드 커밋 이후 — 여기부터가 "커밋할 것".
        git_dirty={
            # int() 는 내림이라 99.5센트가 99가 됨. round() 가 그 수정.
            "app/pricing.py": (
                "def total(cents: int, rate: float) -> int:\n"
                '    """세금 포함 합계를 센트 단위로 돌려준다."""\n'
                "    return round(cents * (1 + rate))\n"
            ),
            "tests/test_pricing.py": (
                "from app.pricing import total\n"
                "\n"
                "\n"
                "def test_half_cent_rounds_up():\n"
                "    assert total(100, 0.095) == 110\n"
            ),
            "notes.txt": "다음에 볼 것: 환불 흐름 정리\n대시보드 지표도 다시 보기\n",
        },
    ),
    Scenario(
        name="vdev-pending-commit",
        skill="vdev",
        why=(
            "맨 '이 변경 커밋해줘.' 는 커밋할 변경이 있는 저장소를 전제함. 빈 디렉터리에선 "
            "답할 대상이 없어 세션이 빈 트리를 읽고 라우팅 없이 답을 끝내고, 그 미스는 "
            "description 이 아니라 샌드박스를 잼. 픽스처는 그 전제 하나만 세움 — 소스와 그 "
            "테스트에 걸친 대기 변경이라 티어는 Dev. 라우팅 결정 뒤의 것(등록된 커밋 훅, "
            "그 훅이 읽는 마커, 플러그인 캐시)은 여전히 픽스처 밖."
        ),
        prompt="이 변경 커밋해줘.",
        expect=[
            "커밋하기 전에 티어를 분류한다",
            "sbx/cli.py 가 바뀌었으므로 티어를 Dev 로 판정한다",
            "커밋 게이트가 읽는 티어 마커를 기록한다",
        ],
        reject=[
            "티어 분류 없이 커밋한다",
            "커밋할 것이 없다고 보고한다",
            "소스 변경을 Docs 로 분류한다",
        ],
        files={
            "README.md": "# sbx\n\n작은 CLI.\n",
            "sbx/__init__.py": "",
            "sbx/cli.py": "def main(argv):\n    print(argv)\n    return 0\n",
            "tests/test_cli.py": (
                "from sbx.cli import main\n\n\ndef test_main():\n    assert main([]) == 0\n"
            ),
        },
        git=True,
        git_dirty={
            "sbx/cli.py": (
                "def main(argv):\n"
                "    if not argv:\n"
                '        print("usage: sbx <name>")\n'
                "        return 2\n"
                "    print(argv)\n"
                "    return 0\n"
            ),
            "tests/test_cli.py": (
                "from sbx.cli import main\n\n\n"
                "def test_main():\n    assert main([]) == 2\n\n\n"
                'def test_main_with_a_name():\n    assert main(["x"]) == 0\n'
            ),
        },
    ),
]

# Skills a throwaway fixture cannot decide the answer for. Each carries the reason.
# tests/skill_docs/ asserts every skills/*/ is either covered by a SCENARIO or
# listed here — so a new skill forces a coverage decision instead of a silent gap.
OUT_OF_REACH: dict[str, str] = {
    "vdev-init": (
        "host-session wiring — settings.json, the plugin cache, ${CLAUDE_PLUGIN_ROOT}. "
        "A fixture directory cannot stand any of that up; tests/vdev_init/ covers "
        "the mechanics. Step 2.8's ALM field check is out of reach for a second reason: "
        "it asks a live board which fields exist (`list_workboard_fields`), so the answer "
        "it acts on comes from the same Recoble server its ALM siblings need."
    ),
    "vdev-uninstall": (
        "host-session wiring — the inverse of vdev-init, unregisters settings.json "
        "hooks. A fixture directory cannot stand up the host state it removes."
    ),
    "release-commit": (
        "reads release state a fixture directory cannot stand up — remote refs on three "
        "branches, an origin carrying an rc version bump, and a rendered "
        ".github/workflows/release.yml whose dispatch inputs decide the whole procedure."
    ),
    "harness-init": (
        "fans out to sub-agents and the live web, so a run is neither cheap nor "
        "repeatable, and its output is prose whose correctness is a judgement rather "
        "than an assertion. harness-critic is the intended reviewer."
    ),
    "harness-authoring": (
        "the authoring engine harness-init invokes; same fan-out + prose-output shape, "
        "reviewed by harness-critic, not a fixture."
    ),
    "alm-fetch": (
        "no prompt reaches it. Its only caller is /task-sync's invoke-skill step for alm-fetch "
        "after propagation is enabled and the seed set is resolved, so a fixture "
        "has no prompt to stand up."
    ),
    "harness-insight": (
        "reads Claude Code transcripts from OUTSIDE the repo, which a project fixture "
        "cannot supply."
    ),
    "task-import": (
        "needs a live ALM backend to open or read an item. The shipped default is "
        "Recoble over a per-space MCP server that Claude Code authenticates by OAuth "
        "(`mcp__recoble-<space>__…`), which a fixture directory cannot stand up or "
        "sign into; the Teamer branch additionally needs the Teamer API + keyring "
        "credentials."
    ),
    "task-sync": (
        "the inverse write path, same blocker: commenting the summary and closing the "
        "item goes through the OAuth-authenticated Recoble MCP server (Teamer branch: "
        "a multipart PUT with keyring credentials). A fixture supplies neither backend."
    ),
    "alm-trace": (
        "same Recoble MCP blocker as its siblings, and one more on top: the run reads "
        "boards the fixture cannot create (`list_workboards`/`list_entity_links`) and "
        "then fans a full-board scan out to a general-purpose agent, so what it does "
        "next depends on a live graph. tests/alm_layers/ fixes the resolver's "
        "judgements, which is the part that can be asserted. The verification round "
        "(`run: true`) inherits the same blocker — the round is an item created on a "
        "board, linked with `relates_to`, so nothing about it exists on a filesystem."
    ),
    "alm-docs": (
        "the same Recoble MCP blocker as its siblings, in both halves: the board "
        "enumeration is an authenticated `list_workboard_items` walk a fixture cannot "
        "stand up or sign into, and the judgement it feeds needs that enumeration "
        "beside a docs/srs tree. tests/alm_docs/ fixes the deterministic half — the "
        "scan, the five drift kinds and the two write-backs — which is the part that "
        "can be asserted."
    ),
}

BY_NAME = {s.name: s for s in SCENARIOS}


def _force_remove(func, path, _exc):
    """rmtree 콜백: read-only 비트를 지우고 재시도함.

    git 은 오브젝트 파일을 read-only 로 쓰므로, Windows 에서 시드된 픽스처를 그냥 rmtree
    하면 PermissionError 로 죽음 — 그러면 `--all --out-dir <dir>` 이 한 번만 되고 그 뒤로는
    매번 실패함."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build(scenario: Scenario, root: Path) -> Path:
    target = root / scenario.name
    if target.exists():
        # onexc 가 아니라 onerror: 전자는 Python 3.12+ 이고 이 파일은 게이트의 3.8 floor 에서
        # 돌아감. onerror 는 거기서 deprecated 지만 여전히 존중됨.
        shutil.rmtree(target, onerror=_force_remove)
    target.mkdir(parents=True)
    for rel in scenario.dirs:
        (target / rel).mkdir(parents=True, exist_ok=True)
    for rel, content in scenario.files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" keeps LF on Windows: a stray CR turns a resolved testDir into a
        # directory that does not exist, which would read as a skill bug.
        path.write_text(content, encoding="utf-8", newline="")
    for rel, src in scenario.copy_from_repo.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / src, dest)
    if scenario.git:
        # `git config` 가 아니라 -c: 픽스처가 실행자의 전역 신원에 의존해서도, 그것을 써서도
        # 안 됨. gpgsign·hooksPath 도 같은 이유로, 더 절박하게 무력화 — 전역 커밋 서명을
        # 켠 개발자는 매 세션 멈추는 pinentry 프롬프트를 만나고, 전역 hooksPath 는 그 사람의
        # 훅을 일회용 디렉터리에 대고 실행함.
        identity = [
            "-c",
            "user.email=s@s",
            "-c",
            "user.name=S",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=",
        ]
        try:
            # `-c` 는 그 한 명령에만 붙음. 시드에는 그것으로 충분하지만, **측정 세션의
            # 에이전트가 이 저장소에서 직접 커밋함**(commit 스킬) — 그 커밋은 `-c` 를 못 받아
            # 실행자의 전역 gitconfig 를 탐: 신원 없으면 실패하고, 전역 gpgsign 은 pinentry 로
            # 세션을 세우고, 전역 hooksPath 는 남의 훅을 일회용 디렉터리에 대고 돌림. 그래서
            # 같은 값을 repo-local 로도 기록해 에이전트의 커밋까지 덮음.
            for cmd in (
                ["git", "init", "-q"],
                ["git", "config", "user.email", "s@s"],
                ["git", "config", "user.name", "S"],
                ["git", "config", "commit.gpgsign", "false"],
                ["git", "config", "core.hooksPath", ""],
                ["git", "add", "-A"],
                ["git", *identity, "commit", "-qm", "seed"],
            ):
                subprocess.run(cmd, cwd=target, check=True, capture_output=True)
            # 시드가 성공했을 때만 씀. 실패했다면 여기는 git 저장소가 아니고, 그 경우
            # 이 파일들은 "커밋되지 않은 변경" 이 아니라 그냥 파일이라 함정이 사라짐.
            for rel, content in scenario.git_dirty.items():
                path = target / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="")
        except (OSError, subprocess.CalledProcessError) as exc:
            # 예외를 밖으로 내보내면 안 됨: main() 은 시나리오를 **전부** 빌드한 뒤에야
            # 프롬프트를 찍으므로, git 없는 머신에서 `--all` 이 픽스처 11개를 디스크에 남기고
            # 프롬프트는 하나도 못 낸 채 트레이스백으로 끝남(git 을 안 건드리는 시나리오는
            # 언제나 찍힘). 대신 크게 경고하고 계속함 — 조용히 넘기지도
            # 않음: 시드 안 된 픽스처는 스킬이 아니라 파일시스템 폴백을 측정하므로 그
            # 시나리오의 채점 결과는 무효. git 의 진짜 stderr 도 같이 냄(그것 없이는
            # CalledProcessError 가 종료코드만 말해 원인을 짚을 수 없음).
            detail = getattr(exc, "stderr", None) or exc
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", "replace")
            print(
                f"[!] {scenario.name}: git 시드 실패 — 이 픽스처는 git 인덱스가 아니라"
                f" 파일시스템을 측정하므로 채점 결과가 무효입니다: {detail}",
                file=sys.stderr,
            )
    return target


def render(scenario: Scenario, path: Path) -> str:
    lines = [
        "=" * 78,
        f"SCENARIO  {scenario.name}   (skill under test: /{scenario.skill})",
        "=" * 78,
        f"WHY       {scenario.why}",
        "",
        f"SANDBOX   {path}",
        "",
        "PROMPT    Run this in a fresh agent, cwd = the sandbox above:",
        "",
        f"    {scenario.prompt}",
        "",
        "PASS when the agent:",
    ]
    lines += [f"    [+] {e}" for e in scenario.expect]
    lines += ["", "FAIL if the agent:"]
    lines += [f"    [-] {r}" for r in scenario.reject]
    lines += [""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("scenario", nargs="?", help="scenario name (see --list)")
    ap.add_argument("--all", action="store_true", help="build every scenario")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    ap.add_argument("--out-dir", help="where to build (default: a temp dir)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = ap.parse_args()

    if args.list:
        for s in SCENARIOS:
            print(f"{s.name:26} /{s.skill:20} {s.why.split('.')[0]}.")
        for skill, reason in OUT_OF_REACH.items():
            print(f"{'(out of reach)':26} /{skill:20} {reason.split('—')[0].strip()}")
        return 0

    if args.all:
        chosen = SCENARIOS
    elif args.scenario:
        if args.scenario not in BY_NAME:
            print(f"unknown scenario {args.scenario!r}; try --list", file=sys.stderr)
            return 2
        chosen = [BY_NAME[args.scenario]]
    else:
        ap.print_help()
        return 2

    root = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="skill-sandbox-"))
    root.mkdir(parents=True, exist_ok=True)

    built = [(s, build(s, root)) for s in chosen]
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "name": s.name,
                        "skill": s.skill,
                        "sandbox": str(p),
                        "prompt": s.prompt,
                        "expect": s.expect,
                        "reject": s.reject,
                    }
                    for s, p in built
                ],
                indent=2,
            )
        )
    else:
        for s, p in built:
            print(render(s, p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
