"""vdev-init 의 기계적 셋업 / --uninstall 정리 — 멱등.
(대화형 부분은 /vdev-init 커맨드의 Claude 담당)

호스트 측 vway-kit 산출물은 모두 .claude/vway-kit/ 한 곳에 모이고, 용도별로
하위 분류됨:
  - .claude/vway-kit/scripts/  복사 게이트 스크립트 (플러그인 소유·git추적)
  - .claude/vway-kit/config/   vdev-config.yaml·vdev-tiers.yaml(정책)·계정·웹훅
  - .claude/vway-kit/templates/ 호스트가 고치는 ALM·handoff 양식(호스트 소유)
  - .claude/vway-kit/.vdev/    게이트 증거 (gitignored)

setup(기본) 이 멱등하게 적용하는 것:
  - 게이트 스크립트를 .claude/vway-kit/scripts/, 정책 vdev-tiers.yaml 을 config/ 로 복사
  - 구버전(루트 분산·평면) config/증거/스크립트를 새 분류 위치로 이전 (신규 설치는 skip)
  - 구경로 templates/ 의 호스트 양식 중 이름을 댈 수 있는 것만 .claude/vway-kit/templates/
    로 이전한 **뒤**, config 가 선언한 템플릿을 그 자리에 시드(있으면 유지)
  - 커밋 게이트를 .claude/settings.json 의 hooks.PreToolUse 에 등록(경로 바뀌면 보정)
    + config `harnesses` 가 codex 를 적으면 .codex/hooks.json 에도 등록(부재 = claude 만)
  - 정적분석 훅: 없으면 .pre-commit-config.yaml 생성, 있으면 빠진 항목 보고(자동 병합 X)
  - .gitignore 에 누락 라인 추가 (중복 시 skip) + 이미 추적 중인 .vdev 증거는
    git rm --cached 로 추적 해제 (라인만으론 기존 추적분이 안 빠지는 footgun 복구)
  - 비공개 마켓 자동 갱신 인증 점검 — GITHUB_TOKEN·insteadOf 충돌 (안내만, 적용하지 않음)

uninstall(--uninstall) 은 setup 의 역연산(호스트 정리):
  - settings.json 의 커밋 게이트 / vway 마켓 등록 해제 (비워진 파일은 삭제)
  - .codex/hooks.json 의 Codex 게이트 해제 — config 와 무관, 파일이 있을 때만
  - .gitignore 의 vway-kit 라인 제거(비밀 파일 보호 라인은 유지), CLAUDE.md 의 teams 관리 블록 제거
  - .claude/vway-kit/ 디렉터리 삭제 (스크립트·config·증거·웹훅·템플릿 포함)
  - .pre-commit-config.yaml 훅·git 훅·워크플로는 파괴 위험이 커 보고만(수동 제거 안내)

경로: 호스트=CLAUDE_PROJECT_DIR(없으면 git toplevel), 플러그인=CLAUDE_PLUGIN_ROOT
(없으면 이 스크립트의 상위). 결과는 사람이 읽을 요약으로 stdout 에 출력함.

**한 단계의 실패는 실행을 끝내지 않고 판정을 바꿈.** 각 단계는 자기 문제를 `[!]` 줄로
보고하고 나머지 단계는 계속 돎 — 워크플로우도 .gitignore 도 게이트가 안 되는 호스트에서
여전히 값어치가 있음. 그것은 동시에 게이트를 끄는 그 한 줄이 마흔 줄 사이로 지나간다는
뜻이라, 마지막 줄과 **종료 코드**가 게이트 자체를 되읽어 답함(`_gate_problems` ·
uninstall 은 `_gate_hook_remains`): 완료 문구와 exit 0 은 호스트에 실제로 도는 게이트가
있을 때만, 정리 완료와 exit 0 은 훅이 실제로 사라졌을 때만 나옴. 등록 줄에 물으면
질문이 스스로 답하므로(나중 단계의 쓰기 실패도, 발화하지 않는 매처도, 통째로 꺼진 훅도 그
줄은 문제 없다고 말함) 판정은 언제나 실행이 **남긴 것**에서 만들어짐.

각 함수는 경로를 인자로 받아 결과를 반환하므로 단위 테스트가 가능함.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile  # noqa: F401 — vis.tempfile 는 tests/vdev_init 의 monkeypatch 대상(jsonfile 공유 모듈)
from collections import Counter
from collections.abc import Callable
from pathlib import Path

# 경로 세그먼트·폴백 헬퍼·인코딩 방어는 공용 SSOT(_vway_paths)에서 가져옴(중복 정의
# 금지 — rule-dry-constants). vdev_init_setup 은 플러그인 위치에서 실행되므로 형제
# import 가 기본이고, 패키지(테스트)에서는 scripts._vway_paths 로 떨어짐.
try:
    from _vway_paths import (
        CHECK_TIMINGS,
        CONFIG_DIR,
        PLUGIN_MANIFEST,
        SCRIPTS_DIR,
        TEMPLATES_DIR,
        TEMPLATES_DIRNAME,
        TIERS_FILENAME,
        VDEV_DIR,
        VWAY_DIR,
        config_path,
        force_utf8_io,
        host_root,
        is_reparse_point,
        is_safe_template_rel,
        plugin_root,
        template_rel,
        under_real_tree,
        vway_dir,
    )
except ImportError:
    from scripts._vway_paths import (
        CHECK_TIMINGS,
        CONFIG_DIR,
        PLUGIN_MANIFEST,
        SCRIPTS_DIR,
        TEMPLATES_DIR,
        TEMPLATES_DIRNAME,
        TIERS_FILENAME,
        VDEV_DIR,
        VWAY_DIR,
        config_path,
        force_utf8_io,
        host_root,
        is_reparse_point,
        is_safe_template_rel,
        plugin_root,
        template_rel,
        under_real_tree,
        vway_dir,
    )

# JSON 파일 IO(원자적 쓰기·권한 보존)는 하네스 중립 모듈로 옮김 — Claude 외 설치자도
# 같은 코드를 씀(harness/jsonfile.py 가 SSOT). 여기 이름은 기존 호출부·테스트가
# `vdev_init_setup.<이름>` 으로 계속 찾을 수 있도록 re-export.
try:
    from harness.jsonfile import ACCESS_ENTRIES as _ACCESS_ENTRIES  # noqa: F401
    from harness.jsonfile import access_entries as _access_entries  # noqa: F401
    from harness.jsonfile import confine as _confine
    from harness.jsonfile import why as _why
    from harness.jsonfile import write_json as _write_json  # noqa: F401
except ImportError:
    from scripts.harness.jsonfile import ACCESS_ENTRIES as _ACCESS_ENTRIES  # noqa: F401
    from scripts.harness.jsonfile import access_entries as _access_entries  # noqa: F401
    from scripts.harness.jsonfile import confine as _confine
    from scripts.harness.jsonfile import why as _why
    from scripts.harness.jsonfile import write_json as _write_json  # noqa: F401

WORKFLOW_TEMPLATE = "github/api-contract.workflow.example.yml"  # SOURCE(플러그인 소유)
WORKFLOW_DEST = ".github/workflows/api-contract.yml"  # 호스트(GitHub 강제 위치 — VWAY_DIR 예외)

WORKFLOW_UNIT_TEST_TEMPLATE = "github/unit-test.workflow.example.yml"  # SOURCE(플러그인 소유)
WORKFLOW_UNIT_TEST_DEST = ".github/workflows/unit-test.yml"  # 호스트(GitHub 강제 위치)

WORKFLOW_WIKI_VERIFY_TEMPLATE = "github/wiki-verify.workflow.example.yml"  # SOURCE(플러그인 소유)
WORKFLOW_WIKI_VERIFY_DEST = ".github/workflows/wiki-verify.yml"  # 호스트(GitHub 강제 위치)

WORKFLOW_SRS_VERIFY_TEMPLATE = "github/srs-verify.workflow.example.yml"  # SOURCE(플러그인 소유)
WORKFLOW_SRS_VERIFY_DEST = ".github/workflows/srs-verify.yml"  # 호스트(GitHub 강제 위치)

WORKFLOW_DOC_STYLE_TEMPLATE = "github/doc-style.workflow.example.yml"  # SOURCE(플러그인 소유)
WORKFLOW_DOC_STYLE_DEST = ".github/workflows/doc-style.yml"  # 호스트(GitHub 강제 위치)

WORKFLOW_E2E_TEMPLATE = "github/e2e.workflow.example.yml"  # SOURCE(플러그인 소유)
WORKFLOW_E2E_DEST = ".github/workflows/e2e.yml"  # 호스트(GitHub 강제 위치)
UNIT_TEST_DEFAULT_TIMEOUT = 15  # 분 — 타이트한 기본값(팀이 config 에서 올림)
UNIT_TEST_JOB_KEYS = ("name", "language", "version", "setup", "test")
# 템플릿이 if: matrix.language 로 게이팅해 공식 setup action 을 돌리는 5개 언어.
# 이 언어들은 `version` 이 필수 — action 의 `with:` 에 빈 문자열이 명시되면 GitHub
# Actions 가 action.yml 의 default 를 채우지 않고(키 부재 시에만 default 적용) 빈
# 문자열을 그대로 넘김. 그 결과 dtolnay/rust-toolchain 등은 자체 런타임 가드에서
# "required input" 에러로 죽음(예: matrix.version=''). 표에 없는 언어(빈 문자열
# 포함)는 matrix.setup 이스케이프 해치가 런타임을 전담하므로 version 없이도 안전.
UNIT_TEST_OFFICIAL_LANGUAGES = ("python", "node", "java", "go", "rust")

# ── 배포 워크플로 (deploy) ────────────────────────────────────────────────────
# 컴포넌트는 `on: workflow_call` 전용 정적 재사용 워크플로(치환 토큰 없음). 오케스트레이터
# deploy.yml 만 생성되며, 파라미터는 caller job 의 `with:` 로 전달됨.
DEPLOY_TEMPLATE_BY_TARGET = {
    "pypi": "github/deploy.pypi.workflow.example.yml",
    "npm": "github/deploy.npm.workflow.example.yml",
    "maven-central": "github/deploy.maven-central.workflow.example.yml",
    "cratesio": "github/deploy.cratesio.workflow.example.yml",
    "ghcr": "github/deploy.ghcr.workflow.example.yml",
}
WORKFLOW_DEPLOY_DEST = ".github/workflows/deploy.yml"  # 호스트(GitHub 강제 위치)
RELEASE_WORKFLOW_DEST = ".github/workflows/release.yml"

# ── Recoble MCP (local 스코프 등록 안내) ─────────────────────────────────
# vway-kit 은 저장소 `.mcp.json`(project 스코프)을 쓰지 않음 — 팀이 공유하는 파일이라
# 사람마다 다른 PAT 를 담을 수 없고, git 에 실리면 토큰이 샘. 서버는 사람이 `claude mcp add`
# (local 스코프 — `~/.claude.json` 의 프로젝트 경로 밑)로 넣고, 이 모듈은 그 상태를 읽기만 함.
RECOBLE_SERVER_PREFIX = "recoble-"
# 서버 키는 MCP 툴 이름에 그대로 들어감(mcp__recoble-labs__list_workboard_items).
# 슬러그를 벗어난 문자는 Claude Code 가 '_' 로 치환하므로, 스킬이 하드코딩한 이름과
# 어긋나 조용히 툴을 못 찾음. 그래서 렌더 단계에서 거름.
SPACE_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
# mcp_url 은 `claude mcp add …` 명령 텍스트에 그대로 실려 나가고, 그 명령은 **사람이 자기
# 터미널에 붙여넣게** 설계돼 있음(recoble-spaces.md). 그래서 셸에서 뜻을 갖는 글자
# (`"` `'` `;` `|` `&` `$` 백틱 `#` `\` 공백 개행)를 아예 배제함 — 인용으로 감싸는 대신 모양을
# 좁히는 이유: 붙여넣는 사람이 인용을 지우거나 줄을 편집해도 안전해야 함. 이 값은 팀이 공유하는
# git 추적 파일(vdev-config.yaml)에서 오므로 그 파일 쓰기 권한이 명령 실행 권한이 되면 안 됨.
# 쿼리스트링을 빼는 것은 의도 — `&` 를 들이지 않으려는 것이고, 어긋나면 [!] 로 사유를 말함.
MCP_URL_RE = re.compile(r"^https://[A-Za-z0-9._~-]+(?::[0-9]+)?(?:/[A-Za-z0-9._~%-]*)*$")
# example config 가 쓰는 자리표시자 UUID(00000000-…, 11111111-…)를 실제 스페이스로 오인하지
# 않기 위한 모양 검사. 한 자리 16진수만 반복되는 UUID 는 실서비스가 발급할 수 없는 모양이라
# 오탐이 없음 — 검사를 좁게 유지하는 이유(진짜 URL 이 걸리면 안 됨).
PLACEHOLDER_UUID_RE = re.compile(
    r"(?<![0-9a-fA-F])([0-9a-fA-F])\1{7}-\1{4}-\1{4}-\1{4}-\1{12}(?![0-9a-fA-F])"
)

# auth: oidc 일 때 caller job 에 id-token: write 가 필요한 타깃.
DEPLOY_OIDC_TARGETS = ("pypi", "npm", "cratesio")

# 타깃별 auth 기본값(명시 안 했을 때). pypi 는 재사용 워크플로에서 trusted publishing
# (OIDC)이 동작하지 않아(pypa/gh-action-pypi-publish README — 미해결, pypa/warehouse#11096)
# token 이 기본. npm·cratesio 는 최상위 호출 워크플로로 매칭되므로 재사용 워크플로에서도
# OIDC 가 동작해 oidc 가 기본(deploy.npm/deploy.cratesio 템플릿 헤더 참고). 이 표는
# _deploy_permissions(id-token: write 부여 여부)와 _caller_with(with.auth 기본값) 양쪽이
# 공유하는 단일 출처 — 둘이 어긋나면 컴포넌트가 쓰지 않는 권한을 주거나, 필요한 권한을
# 안 주는 조용한 버그가 됨.
DEPLOY_DEFAULT_AUTH = {"pypi": "token", "npm": "oidc", "cratesio": "oidc"}

# 타깃별로 caller job 의 `with:` 에 실릴 수 있는 config 키(빈 값은 실리지 않음 —
# GitHub Actions 는 `with:` 키가 부재할 때만 컴포넌트 input 의 default 를 채움).
DEPLOY_WITH_KEYS = {
    "pypi": ("version", "build", "auth"),
    "npm": ("version", "build", "auth"),
    "cratesio": ("version", "auth"),
    "maven-central": ("version", "build_tool", "build", "publish"),
}

# 타깃별 필수 config 키 — 없으면 그 job 을 drop 하고 [!] 로 보고함.
DEPLOY_REQUIRED_KEYS = {
    "ghcr": ("image",),
    "maven-central": ("build_tool", "publish"),
}

# 오케스트레이터 deploy.yml 의 태그 해석 job id(예약어). 타깃 name 이 이 값과 같으면
# jobs[name] 대입이 jobs["resolve"](steps/outputs.tag 를 가진 진짜 resolver)를 덮어써
# self-cycle(needs: [resolve] 가 이제 없는 자기 자신의 outputs 를 참조)을 만들고, GitHub
# Actions 가 워크플로 로드 자체를 거부함. _deploy_targets 가 이 이름의 타깃을 드롭하고,
# _orchestrator_doc/_deploy_needs 가 실제 resolver job 을 이 id 로 심음 — 세 곳이 같은
# 상수를 봐야 드리프트가 없음. **대소문자 구분**(casefold 안 함) — GitHub Actions job id 는
# case-sensitive 라 예: `RESOLVE` 는 이 예약어와 충돌하지 않고 그대로 생존.
DEPLOY_RESOLVE_JOB = "resolve"
DEPLOY_RESOLVE_TIMEOUT = 5  # 분 — 태그 해석 job
DEPLOY_TAG_EXPR = "${{ needs.resolve.outputs.tag }}"

# GitHub Actions permissions: 값의 랭크(좁을수록 작음). custom 타깃의 permissions 선언
# 검증(_deploy_targets)과 전 타깃 합집합 계산(_deploy_permission_union)이 공유하는 SSOT —
# 두 곳 다 "read/write/none 만 유효, write 가 가장 넓다" 는 같은 규칙을 봐야 함.
_PERM_RANK = {"none": 0, "read": 1, "write": 2}

# release.yml 에 삽입하는 deploy 호출 job 의 마커(2칸 들여쓰기 — jobs: 하위).
# CLAUDE.md 의 teams 블록과 동일한 BEGIN/END upsert 패턴.
DEPLOY_WIRE_BEGIN = "  # vway-kit:deploy BEGIN"
DEPLOY_WIRE_END = "  # vway-kit:deploy END"

EXAMPLE_CONFIG = "vdev-config.example.yaml"  # 플러그인 SOURCE(handoff 종류 SSOT)

# .claude/vway-kit/scripts/ 로 복사할 게이트 스크립트(SOURCE → HOST). _vway_paths.py 는
# 복사 스크립트들이 import 하는 공용 모듈이라 함께 따라가야 함(단일파일 복사 환경에서
# 형제 import 성립). 정책 파일 vdev-tiers.yaml 은 config/ 로 따로 복사(copy_artifacts).
# **한쪽이 다른 쪽에 묻는 곳에서는 순서가 계약.** precommit-runner.sh 는
# vdev_gate_check.py --classify 의 답으로 분기하므로 답하는 쪽을 **먼저** 복사: 동기화
# 도중의 호스트는 그러면 옛 러너 + 새 스크립트가 되고, 옛 러너의 물음은 호환 alias 가 받아
# ROOT 가 main 에 남을 뿐임. 반대 순서는 새 러너가 옛 스크립트에 묻는 상태를 만드는데,
# 옛 스크립트는 --classify 를 모르고, 판정을 못 읽은 러너는 아무것도 게이팅하지 않음.
COPY_FILES = [
    "scripts/_vway_paths.py",
    "scripts/_md_anchors.py",
    "scripts/vdev_gate_check.py",
    "scripts/precommit-runner.sh",
    "scripts/wiki_graph.py",
    "scripts/doc_style_check.py",
    "scripts/srs_check.py",
    "scripts/alm_docs.py",
    "scripts/release_version.py",
    "scripts/changelog_section.py",
    "scripts/doc_invariants.py",
    "scripts/teams_alert.py",
    "scripts/notify-push.sh",
    "scripts/check-deps.sh",
]

# 구경로에서 이 이름들 아래만 vway-kit 의 것으로 셈. 저장소 루트 `templates/` 자체는
# 남의 것일 수 있음(Django·Flask·Jekyll) — 통째로 옮기면 그 앱이 부서짐.
TEMPLATE_SUBDIRS = ("handoff", "alm")

# 이 스크립트가 넣는 것 전부 중 **게이트**가 호스트에서 실제로 필요로 하는 것: 훅이 러너를
# 부르고, 러너가 체크를 띄우고, 체크가 경로 모듈을 import 하고 — 정책을 읽음. 정책이
# 없으면 아무것도 분류되지 않아 미분류 커밋 deny 가 발화하지 않음(실측: vdev-tiers.yaml
# 이 없으면 러너가 진짜 커밋에 exit 0). 셋업 마지막에 **호스트에게** 물음 — 훅은 파일을
# 지목하는 텍스트 한 줄이고, 실패한 복사 단계는 아무것도 지목하지 않는 이름을 남김.
# 각 항목은 (내려앉는 자리, 복사해 온 원본) — 존재가 질문이 아니기 때문: 목적지를
# 만들거나 비운 뒤 실패한 복사는 이름만 남기고, 꽉 찬 볼륨은 빈 파일 넷을 깔아 둠. bash 도
# PyYAML 도 그것을 불평 없이 읽음(실측: 그 위에서 러너가 진짜 커밋에 exit 0).
GATE_FILES = (
    (f"{SCRIPTS_DIR}/precommit-runner.sh", "scripts/precommit-runner.sh"),
    (f"{SCRIPTS_DIR}/vdev_gate_check.py", "scripts/vdev_gate_check.py"),
    (f"{SCRIPTS_DIR}/_vway_paths.py", "scripts/_vway_paths.py"),
    (f"{CONFIG_DIR}/{TIERS_FILENAME}", TIERS_FILENAME),
)

# 하네스별 게이트 스크립트(COPY_FILES 와 같은 SOURCE→HOST 규약, Claude 몫은 위 집합).
# settings.json 을 거치지 않는 하네스는 자기 wrapper 로 게이트를 돌림 — Codex 훅은
# gate.sh·gate.cmd 를 직접 부르므로 GATE_FILES 가 뜻하는 그대로의 게이트 스크립트.
HARNESS_GATE_FILES: dict[str, list[str]] = {
    "codex": ["scripts/harness/codex/gate.sh", "scripts/harness/codex/gate.cmd"],
}
# 하네스가 복사하는 것 전부 — 게이트 스크립트 + 게이트가 돌리지 않는 도구(Codex 의 AGENTS.md
# 렌더러와 그것이 import 하는 모듈 — doc-sync·harness-init 이 호스트 사본을 부름). 도구 하나가
# 빠져도 정책은 그대로 내려앉음(`_gate_problems` 는 `HARNESS_GATE_FILES` 만 봄).
HARNESS_COPY_FILES: dict[str, list[str]] = {
    "codex": [
        *HARNESS_GATE_FILES["codex"],
        "scripts/harness/__init__.py",
        "scripts/harness/instructions.py",
        "scripts/harness/codex/__init__.py",
        "scripts/harness/codex/instructions.py",
        "scripts/harness/codex/hook_io.py",
    ],
}
# 하네스가 호스트 자신의 훅 파일에서 돌리는 파일 — VWAY_DIR 아래 플러그인 안의 경로 그대로
# 복사함: 각 스크립트가 룰과 헬퍼를 자기 위치 기준으로 찾으므로 사본도 플러그인 배치를 따름.
# Codex: 플러그인이 라이프사이클 훅을 싣지 않으므로(OpenAI 디렉터리가 훅 든 패키지를 거부함)
# SessionStart·PostToolUse 훅이 이 사본을 돌림.
HARNESS_ROOT_FILES: dict[str, list[str]] = {
    "codex": [
        "hooks/inject-risk-tiers.sh",
        "hooks/invalidate-gate-markers.sh",
        "hooks/codex/run-hook.cmd",
    ],
}
# 통째로 복사하는 디렉터리(그 아래 `*.md` 전부), 같은 방식.
HARNESS_ROOT_DIRS: dict[str, list[str]] = {"codex": ["rules"]}


def _dest_rel(rel: str) -> Path:
    """`scripts/` 아래 SOURCE 경로가 호스트 scripts 디렉터리 밑 어디에 앉는지.

    - 평탄 COPY_FILES 항목은 basename(`scripts/foo.py` → `foo.py`).
    - 하네스별 항목은 하위 경로 보존(`scripts/harness/codex/gate.sh` → `harness/codex/gate.sh`)
      — 두 하네스가 같은 이름의 파일을 실어도 안 겹침.
    """
    parts = Path(rel).parts
    return Path(*parts[1:]) if parts and parts[0] == "scripts" else Path(Path(rel).name)


def gate_files(harnesses) -> tuple[tuple[str, str], ...]:
    """GATE_FILES + 켜진 하네스 자신의 게이트 스크립트(그 훅이 직접 돌리는 것)."""
    extra = tuple(
        (f"{SCRIPTS_DIR}/{_dest_rel(rel).as_posix()}", rel)
        for name in harnesses
        for rel in HARNESS_GATE_FILES.get(name, [])
    )
    return GATE_FILES + extra


# .gitignore 에 추가할 라인. 자격증명·개인 웹훅은 **bare 패턴**(어느 깊이든 매칭)으로
# 둠 — 경로를 좁히면 아직 config/ 로 이전되지 않은 루트 잔여 파일이 무방비로 노출되는
# 보안 footgun 이 됨(좁히지 말고 더함). 증거 디렉터리는 위치가 고정이라 anchored.
# vdev-config.yaml 은 팀 공유 설정(브랜치·modules·teamer 번호 — 비밀 아님, 자격증명은
# keyring)이라 **추적**함(무시 목록 제외 — teams-webhooks.json·scripts/ 와 같은 결).
GITIGNORE_LINES = [
    "teamer_account.md",
    ".teams-webhooks.local.json",
    f"{VDEV_DIR}/",
    # 게이트는 PYTHONDONTWRITEBYTECODE 를 내보냄 — 이것은 사본의 그 밖의 모든 실행(scripts/harness/
    # 아래 Codex 렌더러 포함)이 남기는 바이트코드를 잡음.
    f"{SCRIPTS_DIR}/**/__pycache__/",
]

# uninstall 이 지우지 않는 라인 — 자격증명·개인 웹훅의 bare 패턴은 VWAY_DIR 밖의 비밀도 막을 수
# 있고, 호스트가 /vdev-init 전부터 가졌을 수 있음. 남긴 라인은 비용이 없고 지운 라인은 누출.
GITIGNORE_KEEP = frozenset({"teamer_account.md", ".teams-webhooks.local.json"})

# 팀 공유로 전환된 파일. 예전 설치는 vdev-config.yaml 을 무시했으므로, 같은 저장소를
# 공유하는 개발자가 모두 동일 설정을 쓰도록 setup 시 .gitignore 의 stale 라인을 능동 제거함.
GITIGNORE_UNIGNORE = ("vdev-config.yaml",)

# 구버전(루트 분산) → 신버전(분류) config/증거 이전 + flow→vdev 재명명 이전 대상.
# vdev-init 재실행 시 기존 호스트를 무손실로 업그레이드함(migrate_legacy_paths).
# 옛 경로 존재 ∧ 새 경로 부재일 때만 이동(멱등·no-clobber). flow→vdev 항목은 구
# flow-init 설치 호스트의 팀 설정·증거를 새 이름으로 옮김(클린 교체의 일회성 마이그레이션).
LEGACY_MOVES = [
    ("vdev-config.yaml", f"{CONFIG_DIR}/vdev-config.yaml"),
    # flow→vdev: config/ 의 정규 팀 설정을 **먼저** 이전함(root flat 보다 우선 —
    # first-match-wins 라 순서가 곧 우선순위. 역순이면 stale 한 루트 파일이 active config 가 됨).
    (f"{CONFIG_DIR}/flow-config.yaml", f"{CONFIG_DIR}/vdev-config.yaml"),  # flow→vdev: config/ 정규
    ("flow-config.yaml", f"{CONFIG_DIR}/vdev-config.yaml"),  # flow→vdev: 옛 루트 flat(차선)
    ("teams-webhooks.json", f"{CONFIG_DIR}/teams-webhooks.json"),
    (".teams-webhooks.local.json", f"{CONFIG_DIR}/.teams-webhooks.local.json"),
    (".claude/.vdev", VDEV_DIR),
    (".claude/.flow", VDEV_DIR),  # flow→vdev: 옛 flat 증거
    (f"{VWAY_DIR}/.flow", VDEV_DIR),  # flow→vdev: 분류 위치 증거 .flow→.vdev
]

# flow→vdev 재명명으로 옛 이름이 된 호스트 scripts/ 사본(재실행 시 잔재 제거 — 새 이름
# vdev_gate_check.py·vdev-tiers.yaml 은 copy_artifacts 가 이미 넣었으므로 옛 사본은 불용).
RENAMED_SCRIPT_ORPHANS = ("flow_gate_check.py", "flow_init_setup.py", "flow-tiers.yaml")

# flow→vdev 재명명으로 옛 tier 마커 값(fast/standard)을 신 정책 키(docs/dev)로 번역함.
# 미번역 시 unknown tier → required_gates None → FAIL-OPEN 으로 진행 중 커밋이 게이트를
# 우회할 수 있음(.flow→.vdev 이전이 마커를 그대로 옮기므로 값을 함께 고침).
TIER_RENAME = {"fast": "docs", "standard": "dev"}

# flow→vdev 재명명으로 죽은 .gitignore 라인(옛 증거 경로). setup 시 능동 제거(멱등).
STALE_GITIGNORE_LINES = (f"{VWAY_DIR}/.flow/",)

# vway-kit 가 소유한 pre-commit 훅 id(언어별 교체 대상이 아닌 고정 훅). 스크립트 위치가
# 바뀌면 기존 .pre-commit-config.yaml 의 entry 가 옛 경로를 가리키므로 drift 를 보고함.
OWNED_HOOK_ID = "teams-notify-push"

# 구버전 vway-kit 가 `- repo: local` 에 심던 레이어1 모듈 훅 id. 레이어2 vdev 게이트
# (vdev-config.modules[].checks)로 이전되며 폐기됨 — 기존 호스트 config 에 남아 있으면
# 죽은 잔재라 제거를 권장(자동 편집은 안 함: .pre-commit-config.yaml 은 외부 도구
# 소유·사용자 커스텀 훅 파일이라 round-trip 이 주석/훅을 파괴함). 화이트리스트로만
# 감지해 사용자 커스텀 훅을 폐기로 오탐하지 않음.
DEPRECATED_LOCAL_HOOK_IDS = frozenset(
    {"lint", "format-check", "security", "typecheck", "lint-imports"}
)

# 호스트 CLAUDE.md 의 Teams 관리 블록 마커(/vdev-init Step 3 이 삽입). uninstall 이
# 이 마커 사이(포함)를 제거함.
CLAUDE_MD_BEGIN = "<!-- vway-kit:teams BEGIN"
CLAUDE_MD_END = "<!-- vway-kit:teams END"

# settings.json 의 커밋 게이트·vway 마켓 등록은 Claude 하네스 설치자로 옮김
# (harness/claude/install.py 가 SSOT). 여기 이름은 기존 호출부·테스트가
# `vdev_init_setup.<이름>` 으로 계속 찾을 수 있도록 re-export — 같은 객체라 동작 동일.
try:
    from harness.claude import install as _claude
except ImportError:
    from scripts.harness.claude import install as _claude

# 게이트를 심는 하네스 레지스트리(scripts/harness/__init__.py) — Claude 밖의 이름은 전부
# `harness.installer` 로 찾음. 호출 때마다 모듈 속성으로 물으므로 `vis.harness` 를 바꾼
# monkeypatch 가 실행되는 쪽에 닿음. Claude 는 위 `_claude` 재수출을 그대로 부름 —
# `harness.*`·`scripts.harness.*` 가 두 번 로드돼도 테스트가 바꾸는 이름이 실제로 도는 이름.
try:
    import harness
except ImportError:
    from scripts import harness

GATE_MARKER = _claude.GATE_MARKER
GATE_COMMAND = _claude.GATE_COMMAND
GATE_STATUS = _claude.GATE_STATUS
GATE_ENTRY = _claude.GATE_ENTRY
MARKETPLACE_NAME = _claude.MARKETPLACE_NAME
MARKETPLACE_REPO = _claude.MARKETPLACE_REPO
MARKETPLACE_URL = _claude.MARKETPLACE_URL  # detect_autoupdate_auth 의 insteadOf 예외 안내
MARKETPLACE_ENTRY = _claude.MARKETPLACE_ENTRY
_load_settings = _claude.load_settings
_is_gate_hook = _claude.is_gate_hook
_EXACT_MATCHER_RE = _claude._EXACT_MATCHER_RE
_covers_bash = _claude.covers_bash
register_gate = _claude.register
unregister_gate = _claude.unregister
register_marketplace = _claude.register_marketplace
unregister_marketplace = _claude.unregister_marketplace
_strip_gate_hooks = _claude._strip_gate_hooks
_is_own_empty_entry = _claude._is_own_empty_entry
_gate_hook_remains = _claude.hook_remains


def _host_target(host: Path, dest: Path) -> Path:
    """`dest` 를 써도 되는 자리로 만들어 돌려줌.

    저장소는 믿을 수 없는 입력 — 이 스크립트가 쓰는 자리에 커밋된 링크는 플러그인 텍스트를
    사용자 소유의 아무 파일 위로 실어 나름. 그래서 호스트 밖으로 풀리는 디렉터리는 거절하고,
    `dest` 자신에 선 링크는 지워 쓰기가 그 자리를 교체하게 함. 플러그인 소유 쓰기에만 걸고,
    호스트 소유 파일의 제자리 편집(`.gitignore`·`settings.json`·release.yml 등)은 호스트 안의
    링크는 따라가되 밖으로 풀리면 거부(`_read_host_text`·`write_json`)."""
    _confine(host, dest.parent)
    if dest.is_symlink():
        dest.unlink()
    return dest


def _read_host_text(host: Path, path: Path) -> tuple[str, str]:
    """제자리 편집하는 호스트 파일의 LF 텍스트와 원래 줄끝(없는 파일은 "\n"). 호스트 밖으로
    풀리면 거부 — 뒤따르는 쓰기는 `path` 의 링크가 가리키는 곳으로 감."""
    _confine(host, path)
    if not path.is_file():
        return "", "\n"
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def _write_host_text(path: Path, text: str, eol: str) -> None:
    """텍스트 모드가 아니라 바이트 — 텍스트 모드는 줄끝을 플랫폼 것으로 바꿔, Linux 에서 고친
    CRLF 파일이 diff 의 모든 줄에서 LF 로 돌아옴."""
    path.write_bytes(text.replace("\n", eol).encode("utf-8"))


def _make_executable(path: Path) -> None:
    """`copyfile` 은 기본 모드로 만듦 — 훅이 이것들을 스크립트로 실행함."""
    mode = path.stat().st_mode
    os.chmod(path, mode | (mode & 0o444) >> 2)


def copy_artifacts(plugin: Path, host: Path, harnesses=("claude",)) -> list[str]:
    """배포 산출물 복사(항상 덮어씀 — SOURCE 가 SSOT). 게이트 스크립트는
    scripts/ 로(평탄 파일은 basename, 하네스별 파일은 하위 경로 — `_dest_rel`), 플러그인
    정책 vdev-tiers.yaml 은 config/ 로(vdev-config 과 한곳).

    하네스 파일은 COPY_FILES **뒤에** 붙음 — COPY_FILES 안의 순서 계약(답하는 쪽 먼저)을
    건드리지 않고, wrapper 가 부르는 러너는 wrapper 보다 먼저 새것이 됨."""
    dest_dir = host / SCRIPTS_DIR
    try:
        _confine(host, dest_dir).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # 단계들 중 첫째. 막지 않으면 뒤의 모든 단계를 함께 끌고 내려감 —
        # 워크플로우도 .gitignore 도 이것이 안 되는 호스트에서 여전히 값어치가 있음.
        return [f"  [!] {SCRIPTS_DIR} 를 만들지 못했습니다({_why(exc)}) — 수동 확인 필요"]
    report: list[str] = []
    rels = [*COPY_FILES, *(rel for name in harnesses for rel in HARNESS_COPY_FILES.get(name, []))]
    for rel in rels:
        src = plugin / rel
        dest_rel = _dest_rel(rel)
        dest_name = dest_rel.as_posix()  # 평탄 파일이면 basename
        if not src.is_file():
            report.append(f"  [!] 소스 없음, skip: {rel}")
            continue
        try:
            dest_path = _host_target(host, dest_dir / dest_rel)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest_path)
            if dest_path.suffix == ".sh":
                _make_executable(dest_path)
        except OSError as exc:
            # 호스트가 열어 두었거나 읽기 전용으로 잠근 파일 하나는 파일 하나지 실행 전체가 아님.
            report.append(f"  [!] 복사 실패({_why(exc)}): {dest_name}")
            continue
        report.append(f"  [+] 복사: {dest_name}")
    report.extend(_copy_root_files(plugin, host, harnesses))
    # 정책 파일은 config/ 로(호스트 소유 디렉터리지만 이 파일만은 플러그인 소유·SSOT).
    tiers_src = plugin / TIERS_FILENAME
    try:
        # 디렉터리는 어느 쪽이든 만듦: `/vdev-init` 이 호스트 자신의 vdev-config 을 이
        # 파일 옆에 두므로, SOURCE 가 없다는 것이 그 자리를 withhold 할 이유는 아님.
        cfg_dir = _confine(host, host / CONFIG_DIR)
        cfg_dir.mkdir(parents=True, exist_ok=True)
        if not tiers_src.is_file():
            report.append(f"  [!] 소스 없음, skip: {TIERS_FILENAME}")
            return report
        shutil.copyfile(tiers_src, _host_target(host, cfg_dir / TIERS_FILENAME))
    except OSError as exc:
        report.append(f"  [!] {TIERS_FILENAME} 복사 실패({_why(exc)}) — 수동 확인 필요")
        return report
    report.append(f"  [+] 복사: {TIERS_FILENAME} → config/")
    return report


def _copy_root_files(plugin: Path, host: Path, harnesses) -> list[str]:
    """HARNESS_ROOT_FILES·HARNESS_ROOT_DIRS 를 VWAY_DIR 아래 플러그인 안의 경로로."""
    rels = [rel for name in harnesses for rel in HARNESS_ROOT_FILES.get(name, [])]
    report = []
    for name in harnesses:
        for top in HARNESS_ROOT_DIRS.get(name, []):
            found = sorted((plugin / top).rglob("*.md")) if (plugin / top).is_dir() else []
            if not found:
                rels.append(top)
                continue
            shipped = [p.relative_to(plugin).as_posix() for p in found]
            rels.extend(shipped)
            report.extend(_drop_unshipped(host, top, set(shipped)))
    for rel in rels:
        src = plugin / rel
        if not src.is_file():
            report.append(f"  [!] 소스 없음, skip: {rel}")
            continue
        try:
            dest = _host_target(host, host / VWAY_DIR / rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            if dest.suffix == ".sh":
                _make_executable(dest)
        except OSError as exc:
            report.append(f"  [!] 복사 실패({_why(exc)}): {rel}")
            continue
        report.append(f"  [+] 복사: {rel}")
    return report


def _drop_unshipped(host: Path, top: str, shipped: set[str]) -> list[str]:
    """플러그인이 더 싣지 않는 룰을 호스트 사본에서 지움 — 세션 훅이 그 디렉터리를 링크된 룰의
    자리로 지목하므로, 남은 것은 시행 중인 룰로 읽힘."""
    base = host / VWAY_DIR
    here = base / top
    try:
        # 포함 관계가 아니라 실제 경로로 봄 — 경로 어느 단에 커밋된 링크든 이 정리를 그것이
        # 가리키는 디렉터리로 돌리고, 거기서의 삭제는 되돌릴 수 없음.
        if Path(os.path.realpath(here)) != Path(os.path.realpath(host)) / VWAY_DIR / top:
            return []
        olds = sorted(here.rglob("*.md")) if here.is_dir() else []
    except OSError:
        return []
    report = []
    for old in olds:
        rel = old.relative_to(base).as_posix()
        if rel in shipped or old.is_symlink():
            continue
        try:
            old.unlink()
        except OSError as exc:
            report.append(f"  [!] 삭제 실패({_why(exc)}): {rel}")
            continue
        report.append(f"  [-] 삭제: {rel} (플러그인에서 빠짐)")
    return report


# 이전 셋업이 출하 문체 룰을 복사해 두던 자리. Claude Code 는 .claude/rules/ 아래 파일을 매 세션
# 통째로 로드하므로, 룰은 이제 훅의 짧은 블록으로만 세션에 닿고 재동기화가 이 디렉터리(vway-kit
# 전용)를 남아 있는 곳마다 지움.
RULES_DEST = ".claude/rules/vway-kit"


def migrate_legacy_paths(host: Path) -> list[str]:
    """구버전(루트 분산·평면) 산출물을 새 분류 위치로 이전(멱등).

    1) 루트 분산 config/증거 → config/·.vdev/ 로 이동(옛 경로 존재 ∧ 새 경로 부재일
       때만 — 신규 설치이거나 이미 이전됐으면 skip).
    2) 구버전 평면 스크립트(.claude/vway-kit/ 직속) 제거 — scripts/ 로 복사되므로
       평면 사본은 잔재(copy_artifacts 가 먼저 scripts/ 에 새로 넣은 뒤 호출).
    host 소유 파일만 다루므로 이전이 실패해도 게이트엔 영향 없음(보고만).

    모든 이동의 목적지와 모든 삭제가 `VWAY_DIR` 아래라, 그것이 호스트 밖으로 풀리면 통째로
    건너뜀 — 아니면 호스트 파일이 저장소 밖으로 나가고 링크 너머의 같은 이름 파일이 지워짐.
    그 아래 `config/`·`scripts/` 같은 하위 디렉터리만 밖을 가리키면 그 자리의 이동·삭제만
    `[!]` 로 건너뜀."""
    try:
        _confine(host, host / VWAY_DIR)
    except OSError as exc:
        return [f"  [!] 구버전 경로 이전 건너뜀({_why(exc)}) — 수동 확인 필요"]
    report: list[str] = []
    for old_rel, new_rel in LEGACY_MOVES:
        old = host / old_rel
        new = host / new_rel
        # `lexists` — 끊긴 링크는 `exists()` 가 False 라, 그 자리로 옮기면 링크를 따라 씀.
        if not old.exists() or os.path.lexists(new):
            continue  # 신규 설치이거나 이미 이전됨
        try:
            _confine(host, new.parent).mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            report.append(f"  [+] 이전: {old_rel} → {new_rel}")
        except OSError as exc:
            report.append(f"  [!] 이전 실패(수동 확인): {old_rel} → {new_rel} ({exc})")

    # flow→vdev: 옛 tier 마커 값(fast/standard)을 docs/dev 로 번역함(미번역 시 unknown
    # tier → FAIL-OPEN 게이트 우회). .flow→.vdev 이전이 마커를 그대로 옮기므로 값을 고침.
    tier_file = host / VDEV_DIR / "tier"
    if tier_file.is_file():
        try:
            label, sep, rest = tier_file.read_text(encoding="utf-8").strip().partition(":")
            new_label = TIER_RENAME.get(label.strip().lower())
            if new_label:
                _confine(host, tier_file)
                tier_file.write_text(f"{new_label}:{rest}" if sep else new_label, encoding="utf-8")
                report.append(f"  [+] tier 마커 번역: {label} → {new_label}")
        except OSError as exc:
            report.append(f"  [!] tier 마커 번역 실패: {exc}")

    # 구버전 평면 스크립트 잔재 정리(scripts/ 로 옮겨졌으므로 평면 사본 제거)
    flat_dir = host / VWAY_DIR
    for rel in COPY_FILES:
        flat = flat_dir / Path(rel).name
        if flat.is_file():
            try:
                flat.unlink()
                report.append(f"  [+] 구버전 평면 스크립트 제거: {Path(rel).name}")
            except OSError as exc:
                report.append(f"  [!] 평면 스크립트 제거 실패: {Path(rel).name} ({exc})")

    # flow→vdev 재명명 잔재: scripts/ 의 옛 이름 사본 제거(새 이름은 copy_artifacts 가 이미 넣음)
    scripts_dir = host / SCRIPTS_DIR
    for name in RENAMED_SCRIPT_ORPHANS:
        orphan = scripts_dir / name
        if orphan.is_file():
            try:
                _confine(host, orphan.parent)
                orphan.unlink()
                report.append(f"  [+] 재명명 잔재 제거: {name}")
            except OSError as exc:
                report.append(f"  [!] 재명명 잔재 제거 실패: {name} ({exc})")

    # vdev-tiers.yaml 재배치(scripts/→config/): 옛 위치 사본 제거. config/ 에는
    # copy_artifacts 가 새로 넣으므로(SSOT) 옛 위치(scripts/·구버전 평면)는 잔재.
    for old_dir in (host / SCRIPTS_DIR, host / VWAY_DIR):
        orphan = old_dir / TIERS_FILENAME
        if orphan.is_file():
            try:
                _confine(host, orphan.parent)
                orphan.unlink()
                report.append(f"  [+] 재배치 잔재 제거: {old_dir.name}/{TIERS_FILENAME}")
            except OSError as exc:
                report.append(f"  [!] 재배치 잔재 제거 실패: {TIERS_FILENAME} ({exc})")

    if not report:
        report.append("  [=] 이전할 구버전 경로 없음 (skip)")
    return report


def _template_declarations(host: Path) -> list[tuple[str, str, dict]]:
    """config 의 템플릿 선언 전부 — (이름, 서브디렉터리, spec). handoff → ALM 계층 순.

    한 걸음인 이유는 이 목록을 읽는 쪽이 둘이기 때문 — 시드는 rel 을 쓰고, 보고는
    거절된 원문을 씀. 둘이 따로 걸으면 한쪽만 고친 순간 보고가 시드와 다른 집합을
    이름 댐."""
    cfg = _load_yaml_safe(config_path(host))
    found: list[tuple[str, str, dict]] = []
    handoff = cfg.get("handoff")
    if isinstance(handoff, dict):
        found += [
            (str(kind), "handoff", spec) for kind, spec in handoff.items() if isinstance(spec, dict)
        ]
    spaces = load_alm_config(host).get("recoble")
    spaces = spaces.get("spaces") if isinstance(spaces, dict) else None
    for space in spaces.values() if isinstance(spaces, dict) else []:
        layers = space.get("layers") if isinstance(space, dict) else None
        if isinstance(layers, dict):
            found += [
                (str(key), "alm", spec) for key, spec in layers.items() if isinstance(spec, dict)
            ]
    return found


def declared_template_rels(host: Path) -> list[str]:
    """vdev-config 이 선언한 템플릿 rel 전부(handoff 종류 → ALM 계층 순, 중복 제거).

    `enable` 을 보지 않음 — 선언이 곧 의도임. 켜는 날에야 템플릿이 없다는 것을 알게
    되면 그 사람은 셋업을 다시 돌려야 하고, 그 사이 요약은 조용히 일반 폴백으로 감.
    rel 규칙 자체의 SSOT 는 `_vway_paths.template_rel`(스킬이 찾는 자리와 셋업이 두는
    자리가 갈리면 시드가 아무 데도 안 닿음)."""
    rels = [template_rel(name, spec, sub) for name, sub, spec in _template_declarations(host)]
    return list(dict.fromkeys(rels))


def _unsafe_template_declarations(host: Path) -> list[str]:
    """`template:` 에 적혔지만 templates/ 를 벗어나 거절된 값을 이름으로 댐.

    거절 자체는 `template_rel` 이 기본값으로 처리하지만, 거절이 조용하면 호스트는 자기
    양식이 왜 안 쓰이는지 알 길이 없음."""
    return [
        f"  [!] template 선언이 templates/ 를 벗어나 무시됨: {name} → {spec['template']!r}"
        for name, _sub, spec in _template_declarations(host)
        if "template" in spec and not is_safe_template_rel(spec["template"])
    ]


def _legacy_template_rels(host: Path) -> list[str]:
    """구경로 `templates/` 에서 **vway-kit 이 이름을 댈 수 있는** 것만.

    그 이름은 둘뿐임: 출하 서브트리 둘(`handoff/`·`alm/`)의 `.md`, 그리고 config 가
    **선언한 rel 전부**(`template:` 을 적은 것도, 안 적어 기본값으로 떨어진 것도).
    나머지는 손대지 않음 — 저장소 루트 `templates/` 는 Django·Flask·Jekyll 프로젝트의
    것일 수 있고, 통째로 옮기면 남의 앱이 부서짐."""
    legacy = host / TEMPLATES_DIRNAME
    rels: list[str] = []
    if (host / PLUGIN_MANIFEST).is_file():
        # 플러그인을 출하하는 저장소의 루트 `templates/` 는 출하본임. 옮기면 그 플러그인이
        # 자기 SOURCE 를 잃음 — 경고를 끈 `legacy_template_path` 와 같은 답이어야 함.
        return []
    if is_reparse_point(legacy):
        return []  # 구경로 루트 자신이 남의 트리를 가리킴 — 아무것도 이름 대지 않음
    for sub in TEMPLATE_SUBDIRS:
        base = legacy / sub
        if base.is_dir() and not is_reparse_point(base):
            rels += [p.relative_to(legacy).as_posix() for p in sorted(base.rglob("*.md"))]
    return list(dict.fromkeys(rels + declared_template_rels(host)))


def _prune_emptied_dirs(candidates: set[Path], stop: Path) -> None:
    """옮긴 파일이 비웠을 **수 있는** 디렉터리만 정리(깊은 것부터).

    후보를 옮긴 파일의 조상으로 가두는 것이 요점임: 트리를 통째로 훑으면 아무것도 안
    옮긴 실행에서도 남의 빈 디렉터리가 사라짐. `stop`(구경로 루트) 자신과 그 위는 대상
    아니고, 링크·정션도 대상 아님 — Windows 에서 rmdir 은 비어 있지 않은 디렉터리
    링크도 지움. 비어 있지 않으면 rmdir 이 실패하고 남음(그것이 판정이라 따로 묻지
    않음)."""
    inside = [d for d in candidates if stop in d.parents]
    for path in sorted(inside, key=lambda p: len(p.parts), reverse=True):
        if is_reparse_point(path) or not path.is_dir():
            continue
        try:
            path.rmdir()
        except OSError:
            pass


def _has_markdown_behind(path: Path) -> bool:
    """링크 너머에 옮길 `.md` 가 실제로 있나. 읽기는 링크를 따라감(문서화된 비대칭 —
    쓰기만 막음). 없는데 알리면 고칠 편집이 없는 `[!]` 가 매 실행 남음."""
    try:
        return any(path.rglob("*.md"))
    except OSError:
        return False


def _blocked_by_link(host: Path, rel: str) -> bool:
    """이 rel 을 구경로에서 못 가져오게 하는 링크가 있고, 그 너머에 양식이 실제로 있나.

    시드가 그 자리를 채우면 never-overwrite 때문에 링크를 고치고 다시 돌려도 이전이
    영영 안 일어나고, 소비자 경고만 조용해져 원인이 사라진 것처럼 보임."""
    if (host / PLUGIN_MANIFEST).is_file():
        return False
    legacy = host / TEMPLATES_DIRNAME
    old = legacy / rel
    return old.is_file() and not under_real_tree(old, legacy)


def migrate_host_templates(host: Path) -> list[str]:
    """구경로 `templates/` 의 호스트 양식을 `.claude/vway-kit/templates/` 로 이전(멱등).

    신경로에 이미 있으면 옮기지 않음 — 호스트가 고친 쪽이 이기고, 구경로 파일은 그대로
    남아 사람이 눈으로 합칠 수 있음. host 소유 파일만 다루므로 실패해도 게이트엔 영향
    없음(보고만)."""
    legacy = host / TEMPLATES_DIRNAME
    host_templates = vway_dir(host) / TEMPLATES_DIRNAME
    report: list[str] = []
    emptied: set[Path] = set()
    # 루트 자신이 링크인 형태도 파일·목적지 링크와 같은 대칭을 가져야 함 — 조용히 빠지면
    # 소비자 경고(읽기는 링크를 따라감)가 재실행해도 안 사라지고 이유도 안 나옴.
    # 출하 저장소 예외는 그 앞 — 거기는 알릴 일이 아니라 애초에 남의 일이 아님.
    if not (host / PLUGIN_MANIFEST).is_file():
        if legacy.exists() and is_reparse_point(legacy):
            if not _has_markdown_behind(legacy):
                return []  # 옮길 것이 없는 링크 — 끊긴 링크와 같은 이유로 조용함
            return [f"  [!] 구경로 {TEMPLATES_DIRNAME}/ 가 링크 너머라 그 안의 양식을 옮기지 않음"]
        # 서브트리 링크도 같은 대칭이 필요함 — 선언이 없으면(암묵 `summary` 경로) 그 rel 이
        # 열거에 안 들어 per-rel 보고에 닿지 못하고, 소비자 경고만 영원히 남음.
        report += [
            f"  [!] 구경로 {TEMPLATES_DIRNAME}/{sub}/ 가 링크 너머라 그 안의 양식을 옮기지 않음"
            for sub in TEMPLATE_SUBDIRS
            if (legacy / sub).exists()
            and is_reparse_point(legacy / sub)
            and _has_markdown_behind(legacy / sub)
        ]
    for rel in _legacy_template_rels(host):
        old = legacy / rel
        new = host_templates / rel
        if not old.is_file():
            continue  # 선언된 rel 이 구경로에 없는 것이 정상 — 깨끗한 설치가 조용해야 함
        if not under_real_tree(old, legacy):
            # "거기 아무것도 없음" 과 다른 사실임 — 양식은 있는데 못 옮김. 조용하면
            # 소비자 경고가 재실행해도 안 사라지고 이유도 안 나옴(목적지 쪽 대칭).
            report.append(f"  [!] 구경로 양식이 링크 너머라 건너뜀: {TEMPLATES_DIRNAME}/{rel}")
            continue
        if new.exists():
            # 파일이 이미 있으면 호스트가 고친 쪽이 이김(조용히 두고 감). 파일이 **아닌**
            # 것이 앉아 있으면 다름 — 소비자 쪽 경고는 `.is_file()` 로 물어 계속 나는데
            # 여기가 말이 없으면 수렴하지 않는 루프가 됨. 막힌 자리를 이름으로 댐.
            if not new.is_file():
                report.append(f"  [!] 이전 목적지가 파일이 아니라 건너뜀: {TEMPLATES_DIR}/{rel}")
            continue
        # 이동은 쓰기이자 삭제임 — 목적지가 링크 너머면 호스트 양식이 저장소 밖으로
        # 나가고 원위치에서 사라짐. 경계가 `templates/` 가 아니라 `VWAY_DIR` 인 것은
        # 그 위 한 칸(`.claude/vway-kit` 자체가 링크)이 같은 구멍이기 때문.
        if not under_real_tree(new, vway_dir(host)):
            report.append(f"  [!] 이전 목적지가 링크 너머라 건너뜀: {TEMPLATES_DIR}/{rel}")
            continue
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            report.append(f"  [+] 이전: {TEMPLATES_DIRNAME}/{rel} → {TEMPLATES_DIR}/{rel}")
            emptied.update(old.parents)
        except OSError as exc:
            report.append(f"  [!] 이전 실패(수동 확인): {TEMPLATES_DIRNAME}/{rel} ({_why(exc)})")
    _prune_emptied_dirs(emptied, legacy)
    return report


def seed_host_templates(host: Path, plugin: Path) -> list[str]:
    """config 가 선언한 템플릿만 호스트로 복사(create-if-absent · never-overwrite).

    선언 안 된 것을 복사하지 않는 이유: 호스트 사본은 탐색에서 늘 이기고 이 단계가 절대
    덮지 않으므로, 사본이 생긴 템플릿은 **플러그인 개선이 영원히 안 닿음**. 안 쓰는
    템플릿까지 내려주면 호스트가 그 동결을 고르지도 않고 얻음.

    출하본이 없는 종류(`qa` 등)는 오류가 아니라 정상 경로 — 그런 종류는 `instruction`
    만으로 돌게 설계돼 있어 빈 스켈레톤을 깔면 그 폴백을 덮어씀."""
    report: list[str] = []
    host_templates = vway_dir(host) / TEMPLATES_DIRNAME
    for rel in declared_template_rels(host):
        dest = host_templates / rel
        # 호스트 사본 자리 안에 링크가 서면 그 너머는 저장소 밖 — 쓰기가 새 나감.
        if _blocked_by_link(host, rel):
            continue  # 이전이 이미 `[!]` 로 이름을 댐 — 그 자리를 출하본으로 덮지 않음
        if not under_real_tree(dest, vway_dir(host)):
            report.append(f"  [!] 시드 대상이 링크 너머라 건너뜀: {TEMPLATES_DIR}/{rel}")
            continue
        if dest.is_file():
            report.append(f"  [=] 이미 있음(유지): {TEMPLATES_DIR}/{rel}")
            continue
        src = plugin / TEMPLATES_DIRNAME / rel
        if not src.is_file():
            report.append(f"  [=] 출하 템플릿 없음, 건너뜀: {TEMPLATES_DIRNAME}/{rel}")
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            report.append(f"  [+] 시드: {TEMPLATES_DIR}/{rel}")
        except OSError as exc:
            report.append(f"  [!] 시드 실패({_why(exc)}): {TEMPLATES_DIRNAME}/{rel}")
    return report


def sync_host_templates(host: Path, plugin: Path) -> list[str]:
    """이전 → 시드. 순서가 계약임: 시드가 먼저면 출하본이 자리를 차지하고, 뒤이은 이전은
    '신경로에 이미 있음' 으로 호스트 양식을 구경로에 영원히 두고 감."""
    report = (
        _unsafe_template_declarations(host)
        + migrate_host_templates(host)
        + seed_host_templates(host, plugin)
    )
    if not report:
        report.append("  [=] 선언된 템플릿 없음 (skip)")
    return report


def _installed(host: Path, plugin: Path, rel: str, source: str) -> bool:
    """호스트가 이 스크립트가 넣는 파일을 바이트 단위로 그대로 갖고 있는가.

    `is_file` 로 물으면 복사가 만들고 채우지 못한 목적지가 그렇다고 답함: 빈
    `precommit-runner.sh` 는 exit 0 이고, 빈 정책은 아무것도 아닌 것으로 파싱되며,
    스스로 설치됐다고 보고한 게이트는 아무 커밋도 막지 않음. 부분 쓰기는 같은 경우가
    한 걸음 진행된 것이라, 재는 대신 비교함. 읽지 못하는 소스도 확인이 아니고, 들어갈
    수 없는 호스트 디렉터리도 아님: 거기서 `read_bytes` 는 이름이 그냥 비어 있을 때의
    False 와 달리 **raise 하고**, 답을 못 받은 채로 판정 전에 실행을 끝내 버림."""
    try:
        want = (plugin / source).read_bytes()
    except OSError:
        return False
    try:
        return (host / rel).read_bytes() == want
    except OSError:
        return False


def _ignore_rule(line: str) -> tuple[str, bool] | None:
    """.gitignore 줄이 거는 것 — (패턴, 디렉터리만). 빈 줄은 None. 다른 `/` 가 어차피 규칙을
    고정하는 곳에선 앞의 `/` 를 떼고, 맨 이름에선 규칙을 루트로 좁히므로 둠."""
    s = line.rstrip()
    if not s:
        return None
    body = s.rstrip("/")
    if "/" in body.lstrip("/"):
        body = body.lstrip("/")
    return body, s.endswith("/")


def _ignored_already(line: str, rules: set[tuple[str, bool]]) -> bool:
    """끝 `/` 없는 규칙은 있는 규칙을 덮음 — 반대는 파일을 놓침."""
    body, dir_only = _ignore_rule(line)
    return (body, False) in rules or (dir_only and (body, True) in rules)


def append_gitignore(host: Path) -> list[str]:
    """.gitignore 에 누락 라인만 추가(중복 없이). 모두 있으면 skip."""
    gi = host / ".gitignore"
    try:
        text, eol = _read_host_text(host, gi)
    except OSError as exc:
        return [f"  [!] .gitignore 수정 거부({_why(exc)}) — 수동 확인 필요"]
    rules = {r for r in map(_ignore_rule, text.splitlines()) if r is not None}
    missing = [ln for ln in GITIGNORE_LINES if not _ignored_already(ln, rules)]
    if not missing:
        return ["  [=] .gitignore 이미 최신 (skip)"]
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(ln + "\n" for ln in missing)
    _write_host_text(gi, text, eol)
    return [f"  [+] .gitignore += {ln}" for ln in missing]


def prune_stale_gitignore(host: Path) -> list[str]:
    """flow→vdev 재명명으로 죽은 .gitignore 라인(STALE_GITIGNORE_LINES)을 제거(멱등).

    옛 증거 경로 `.claude/vway-kit/.flow/` 는 증거가 `.vdev/` 에 있어 무시 대상이 아님.
    setup 시 능동 제거해 마이그레이션된 호스트에 죽은 라인이 누적되지 않게 함.
    """
    gi = host / ".gitignore"
    if not gi.is_file():
        return []
    try:
        text, eol = _read_host_text(host, gi)
    except OSError as exc:
        return [f"  [!] .gitignore 수정 거부({_why(exc)}) — 수동 확인 필요"]
    lines = text.splitlines()
    kept = [ln for ln in lines if ln.strip() not in STALE_GITIGNORE_LINES]
    if len(kept) == len(lines):
        return []
    text = "\n".join(kept)
    if text:
        text += "\n"
    _write_host_text(gi, text, eol)
    removed = sorted({ln.strip() for ln in lines} & set(STALE_GITIGNORE_LINES))
    return [f"  [-] .gitignore 죽은 라인 제거: {ln}" for ln in removed]


def load_alm_config(host: Path) -> dict:
    """vdev-config 의 alm 블록. 부재·비dict 는 {} (FAIL-OPEN).

    하위호환: alm 이 없고 최상위 teamer 만 있으면 provider=teamer 로 읽음. 이
    경로에는 recoble 스페이스가 없으므로 MCP 등록 안내는 자연히 no-op 이 됨.
    """
    cfg = _load_yaml_safe(config_path(host))
    alm = cfg.get("alm")
    if isinstance(alm, dict):
        return alm
    if isinstance(cfg.get("teamer"), dict):
        return {"provider": "teamer", "auto": False, "teamer": cfg["teamer"]}
    return {}


def recoble_servers(alm: dict) -> tuple[dict[str, dict], list[str]]:
    """alm.recoble.spaces → ({서버키: 기대하는 서버 항목}, 경고줄).

    슬러그를 벗어난 키, mcp_url 이 없는 스페이스, **example 자리표시자 UUID 를 그대로
    둔 mcp_url** 은 제외하고 경고 — 잘못된 항목 하나가 나머지 스페이스의 렌더를
    막지 않게 함(FAIL-OPEN).

    돌려주는 항목은 `claude mcp add` 가 만들 모양 그대로 — 등록 상태 판정이 이 값과
    실제 등록을 대조하므로, 기대값과 안내가 한 자리에서 나옴.

    자리표시자를 거르는 이유: 슬롯 백필이 example 의 `alm:` 블록을 verbatim 삽입하면
    호스트 config 에 `.../s/00000000-…/mcp` 가 들어옴. 그대로 안내하면 사람이 닿지
    않는 스페이스를 등록하고, ALM 은 fail-open 이라 아무도 통보받지 않음. 안내 대신
    [!] 로 사람에게 알림.
    """
    recoble = alm.get("recoble")
    spaces = recoble.get("spaces") if isinstance(recoble, dict) else None
    if not isinstance(spaces, dict):
        return {}, []
    servers: dict[str, dict] = {}
    warnings: list[str] = []
    for key, val in spaces.items():
        name = str(key)
        if not SPACE_SLUG_RE.match(name):
            warnings.append(f"  [!] 스페이스 키 '{name}' 는 [a-z0-9-] 만 허용 — 건너뜀")
            continue
        url = val.get("mcp_url") if isinstance(val, dict) else None
        if not url:
            warnings.append(f"  [!] 스페이스 '{name}' 에 mcp_url 이 없음 — 건너뜀")
            continue
        if PLACEHOLDER_UUID_RE.search(str(url)):
            warnings.append(
                f"  [!] 스페이스 '{name}' 의 mcp_url 이 example 자리표시자입니다"
                " — Recoble 웹에서 복사한 실제 URL 로 바꾼 뒤 /vdev-init 재실행 (건너뜀)"
            )
            continue
        if not MCP_URL_RE.match(str(url)):
            warnings.append(
                f"  [!] 스페이스 '{name}' 의 mcp_url 모양이 아닙니다"
                " — https 스킴에 셸 특수문자·공백·쿼리스트링 없이 적으세요 (건너뜀)"
            )
            continue
        servers[f"{RECOBLE_SERVER_PREFIX}{name}"] = {"type": "http", "url": str(url)}
    return servers, warnings


def _claude_registry_path() -> Path:
    """Claude Code 가 local 스코프 MCP 서버를 적는 파일.

    `claude mcp add`(스코프 기본값 local)는 서버를 저장소가 아니라 사용자 홈의
    `~/.claude.json` 에, 그것도 **프로젝트 경로별로** 적음. 그래서 한 사람이 저장소마다
    다른 스페이스를 쓸 수 있고, worktree 는 경로가 달라 각각 등록해야 함.
    """
    return Path.home() / ".claude.json"


def _path_key(value: object) -> str:
    """경로를 비교 가능한 한 모양으로 — 실제 파일은 Windows 경로도 슬래시로 적음."""
    return os.path.normcase(str(value).replace("\\", "/").rstrip("/"))


def _registry_servers(host: Path, registry: Path | None) -> tuple[dict, bool]:
    """(이 저장소에 등록된 MCP 서버, 판정 가능 여부) — **읽기 전용**.

    파일이 없거나 안 읽히면 (`{}`, False). 파일은 읽혔는데 이 저장소 키가 없으면
    (`{}`, True) — 등록한 적이 없는 것이고, 그것도 답. 둘을 구분하는 이유는
    판정 불가일 때만 전부 안내해야 하기 때문(FAIL-OPEN).

    **쓰지 않음.** 이 파일은 Claude Code 소유이고 사용자의 다른 프로젝트 설정이 같이
    들어 있음 — vway-kit 이 손댈 근거가 없음.
    """
    path = registry if registry is not None else _claude_registry_path()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError):
        return {}, False
    projects = doc.get("projects") if isinstance(doc, dict) else None
    if not isinstance(projects, dict):
        return {}, False
    want = _path_key(host)
    for key, val in projects.items():
        if _path_key(key) != want:
            continue
        servers = val.get("mcpServers") if isinstance(val, dict) else None
        return (servers if isinstance(servers, dict) else {}), True
    return {}, True


def _registration_problem(entry: object, expected: dict) -> str | None:
    """등록된 항목이 config 와 어긋나는 첫 사유. 정상이면 None.

    **헤더 값은 읽지 않음** — `Bearer ` 접두와 그 뒤가 비지 않았는지만 봄. 값을 읽으면
    그 순간 토큰이 이 프로세스의 출력 경로에 들어옴(Invariant 6).
    """
    if not isinstance(entry, dict):
        return "항목이 객체가 아님"
    if entry.get("type") != expected["type"]:
        return "type 불일치"
    if entry.get("url") != expected["url"]:
        return "url 불일치"
    headers = entry.get("headers")
    auth = headers.get("Authorization") if isinstance(headers, dict) else None
    if not isinstance(auth, str) or not auth.startswith("Bearer ") or not auth[7:].strip():
        return "Authorization 헤더 없음"
    return None


def recoble_mcp_instructions(host: Path, registry: Path | None = None) -> list[str]:
    """Recoble 스페이스마다 local 스코프 등록 상태를 판정해 사람이 실행할 안내를 만듦.

    vway-kit 은 저장소 `.mcp.json` 을 쓰지 않음 — 그 파일은 팀 공유(project 스코프)라
    사람마다 다른 PAT 를 담을 수 없고, git 에 실리면 토큰이 샘. 서버는 사람이 자기
    터미널에서 `claude mcp add`(local 스코프)로 넣고, 이 단계는 읽기만 해서 정상이면
    건너뛰고 어긋나면 고칠 명령을 보여줌.

    토큰은 자리표시자로만 등장 — /vdev-init 이 값을 물으면 그 순간 토큰이 모델
    컨텍스트와 트랜스크립트에 남음(Invariant 6). `claude mcp add` 는 같은 이름이 있으면
    거절하므로, 고치는 안내는 `remove` 를 먼저 세움.
    """
    servers, lines = recoble_servers(load_alm_config(host))
    if not servers:
        return lines or ["  [=] Recoble 스페이스 없음 (skip)"]

    registered, judged = _registry_servers(host, registry)
    lines.append("  [i] 아래는 사람이 자기 터미널에서 실행합니다 — 토큰을 세션에 붙여넣지 마세요.")
    if not judged:
        lines.append(
            "  [i] 등록 상태를 확인할 수 없어 전부 안내합니다 (이미 등록됐으면 거절됩니다)."
        )
    for key, expected in servers.items():
        entry = registered.get(key)
        if entry is not None:
            problem = _registration_problem(entry, expected)
            if problem is None:
                lines.append(f"  [=] {key} 정상 (skip)")
                continue
            lines.append(f"  [~] {key} {problem} — 아래로 재등록")
            lines.append(f"        claude mcp remove {key}")
        else:
            lines.append(f"  [+] {key} 미등록 — 아래로 등록")
        lines.append(f"        claude mcp add -t http {key} \\")
        lines.append(f"          {expected['url']} \\")
        lines.append('          -H "Authorization: Bearer <PAT>"')
    lines.append("  [i] local 스코프는 이 저장소 경로 전용입니다 — worktree 는 각각 등록하세요.")
    return lines


def report_recoble_mcp_servers(host: Path, registry: Path | None = None) -> list[str]:
    """uninstall 보고용 — 이 저장소에 등록된 recoble-* 를 알리고 수동 제거를 안내함.

    자동 삭제하지 않음. `~/.claude.json` 은 Claude Code 소유라 사람이 직접 넣은 서버와
    구분할 근거가 없고, 잘못 지우면 복구가 어려움(.pre-commit-config.yaml 을 보고만 하는
    것과 같은 이유).

    판정 불가를 '없음' 으로 접지 않음 — 파일이 안 읽히는 사람에게 없다고 말하면 살아 있는
    PAT 가 등록된 채로 남는 것을 아무도 통보받지 못함. 안내 경로가 같은 상황을 고지하므로
    두 입구의 답도 어긋나면 안 됨.
    """
    registered, judged = _registry_servers(host, registry)
    if not judged:
        return ["  [=] 등록 상태를 확인할 수 없음 — `claude mcp list` 로 직접 확인하세요 (skip)"]
    keys = sorted(k for k in registered if str(k).startswith(RECOBLE_SERVER_PREFIX))
    if not keys:
        return ["  [=] 등록된 recoble 서버 없음 (skip)"]
    return [
        f"  [i] 이 저장소에 recoble 서버 {len(keys)}개 등록됨"
        " — 필요 없으면 직접 제거하세요 (자동 삭제하지 않습니다).",
        *(f"        claude mcp remove {k}" for k in keys),
    ]


def report_legacy_mcp_json(host: Path) -> list[str]:
    """구버전이 저장소 `.mcp.json` 에 쓴 recoble-* 를 알림.

    vway-kit 은 이 파일을 더는 쓰지 않지만, 그 전에 설치한 저장소에는 남아 있고 git 에
    추적됨. `~/.claude.json` 만 읽는 :func:`report_recoble_mcp_servers` 는 이 파일을 못 보므로,
    그것만으로는 uninstall 이 "등록된 recoble 서버 없음" 이라는 거짓을 찍음 — 두 입구가
    같은 답을 내려면 여기를 따로 물어야 함.

    자동 삭제하지 않음 — 사람이 직접 넣은 서버와 구분할 근거가 없음. 할 말이 없으면 빈 목록.
    """
    path = host / ".mcp.json"
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        # 판정 불가를 '없음' 으로 접지 않음 — 접으면 남은 등록을 아무도 통보받지 못함.
        return ["  [=] .mcp.json 을 읽을 수 없음 — 직접 확인하세요 (skip)"]
    servers = doc.get("mcpServers") if isinstance(doc, dict) else None
    # 안쪽 값도 dict 인지 물음 — `{"mcpServers": 5}` 는 `for` 에서 TypeError 를 내고, 그 예외는
    # `_step` 의 `(OSError, UnicodeDecodeError)` 를 지나 두 입구를 통째로 죽임(uninstall 은
    # 게이트만 푼 반쪽 상태로 멈춤). 오염된 JSON 하나가 그러면 안 됨 — Invariant 1.
    if not isinstance(servers, dict):
        return []
    keys = sorted(k for k in servers if str(k).startswith(RECOBLE_SERVER_PREFIX))
    if not keys:
        return []
    return [
        f"  [i] 저장소 `.mcp.json` 에 구버전이 남긴 recoble 서버 {len(keys)}개: {', '.join(keys)}",
        "      → vway-kit 이 관리하지 않는 등록입니다. 직접 제거하세요 (자동 삭제 안 함).",
    ]


def _codex_mcp_module():
    """`scripts.harness.codex.mcp` — 임포트 실패는 여기서만 잡음(`_step` 의 `(OSError,
    UnicodeDecodeError)` 를 넓히면 claude 전용 호스트의 PyYAML 부재 동작까지 바뀜).

    `harness.installer()` 레지스트리를 쓰지 않는 이유: 그 레지스트리는 게이트 설치 모듈
    (`install.py`) 전용이고 `mcp.py` 는 판정 전용이라 다른 파일 — 같은 시도 순서(`harness.` 우선,
    `scripts.harness.` 로 폴백)만 따라 함.
    """
    try:
        from harness.codex import mcp as _mod
    except ImportError:
        from scripts.harness.codex import mcp as _mod
    return _mod


def codex_recoble_mcp_instructions(host: Path) -> list[str]:
    """setup `[Recoble MCP]` 단계의 세 번째 생산자 — codex 가 켜진 호스트에서만 추가됨.

    Claude 판정(`recoble_mcp_instructions`)과 같은 `recoble_servers(load_alm_config(host))` 를
    다시 읽음 — 두 판정이 같은 기대값(url)에서 갈리면 안 되므로 한쪽 계산을 캐시해 넘기는 대신
    각자 config 를 다시 읽음(이 파일의 다른 단계들과 같은 관례).
    """
    try:
        mod = _codex_mcp_module()
    except ImportError as exc:
        return [f"  [!] Codex MCP 판정 모듈을 불러오지 못했습니다({_why(exc)}) — 수동 확인 필요"]
    servers, _warnings = recoble_servers(load_alm_config(host))
    return mod.instructions(servers, host=host)


def codex_recoble_mcp_report(host: Path) -> list[str]:
    """uninstall `[Recoble MCP]` 단계의 세 번째 생산자.

    설정(`harnesses`)과 무관하게 호출됨(uninstall 원칙 — codex 를 목록에서 뺀 뒤에도 등록은
    남을 수 있음). 호출 여부 자체는 `_codex_present(host)` 가 가림 — 그래서 codex 를 쓴 적
    없는 claude 전용 호스트엔 "확인할 수 없음" 한 줄도 새로 생기지 않음.
    """
    try:
        mod = _codex_mcp_module()
    except ImportError as exc:
        return [f"  [!] Codex MCP 판정 모듈을 불러오지 못했습니다({_why(exc)}) — 수동 확인 필요"]
    return mod.report(host=host)


def _codex_present(host: Path) -> bool:
    """codex 실행 파일이 있거나 `.codex/` 가 있는가 — uninstall `[Recoble MCP]` 세 번째
    생산자를 켤지 가림.

    실행 파일 존재는 `mcp.py` 의 단일 seam(`_codex_path`)에 물음 — 여기서 직접
    `shutil.which("codex")` 를 부르면 seam 이 둘로 갈려, 테스트가 Codex 스폰을 막으려면
    `mcp._codex_path` 와 `shutil.which` 둘 다 patch 해야 함(후자는 bash·git 을 찾는 무관한
    테스트까지 건드림). import 실패는 있는 쪽으로 접음(FAIL-OPEN) — `codex_recoble_mcp_report`
    가 같은 실패를 다시 겪어 `[!]` 로 보고하므로, 여기서 숨기면 그 보고만 사라짐.
    """
    try:
        present = _codex_mcp_module()._codex_path() is not None
    except ImportError:
        present = True
    return present or (host / ".codex").exists()


def unignore_shared(host: Path) -> list[str]:
    """팀 공유로 전환된 파일(GITIGNORE_UNIGNORE)이 .gitignore 에 남아 있으면 제거함.

    구버전 설치의 .gitignore 에는 vdev-config.yaml 이 있음 — 같은 저장소를 공유하는
    개발자가 모두 동일 설정을 쓰려면 추적되어야 하므로, setup 시 stale ignore 라인을
    능동 제거함. 멱등(이미 없으면 빈 결과). 다른 라인은 보존함.
    """
    gi = host / ".gitignore"
    if not gi.is_file():
        return []
    try:
        text, eol = _read_host_text(host, gi)
    except OSError as exc:
        return [f"  [!] .gitignore 수정 거부({_why(exc)}) — 수동 확인 필요"]
    lines = text.splitlines()
    kept = [ln for ln in lines if ln.strip() not in GITIGNORE_UNIGNORE]
    if len(kept) == len(lines):
        return []
    text = "\n".join(kept)
    if text:
        text += "\n"
    _write_host_text(gi, text, eol)
    removed = sorted({ln.strip() for ln in lines} & set(GITIGNORE_UNIGNORE))
    return [f"  [-] .gitignore 공유 전환(추적) 제거: {ln}" for ln in removed]


def untrack_vdev_evidence(host: Path) -> list[str]:
    """이미 git 에 추적 중인 .vdev 증거를 인덱스에서 제거(작업 트리 파일은 보존).

    `.gitignore` 라인은 *아직 추적되지 않은* 파일만 무시함 — 라인 추가 전에 `git add`
    된 증거는 무시 규칙을 더해도 계속 추적됨(흔한 footgun). setup 시
    한 번 인덱스에서 빼 무시가 실제로 적용되게 함(멱등 — 추적분 없으면 빈 결과). git
    부재·비저장소·기타 내부 오류는 FAIL-OPEN(빈 결과) — 게이트 셋업을 막지 않음.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(host), "ls-files", "--", VDEV_DIR],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if tracked.returncode != 0 or not tracked.stdout.strip():
            return []
        removed = subprocess.run(
            ["git", "-C", str(host), "rm", "-r", "--cached", "--quiet", "--", VDEV_DIR],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if removed.returncode != 0:
            # rm 만 실패(권한·인덱스 잠금 등) — 추적이 안 빠졌는데 빠졌다고 거짓 보고하지
            # 않음. 게이트 셋업은 막지 않되(FAIL-OPEN) 수동 확인을 명시함.
            return [f"  [!] .vdev 추적 해제 실패 — 수동 확인 필요 (git rm --cached): {VDEV_DIR}"]
        return [f"  [-] .vdev 추적 해제 (git rm --cached): {VDEV_DIR}"]
    except Exception:
        return []


def _find_hook_entry(cfg: dict, hook_id: str) -> str | None:
    """pre-commit config dict 에서 주어진 hook id 의 `entry` 값을 찾음(없으면 None)."""
    for repo in cfg.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        for hook in repo.get("hooks") or []:
            if isinstance(hook, dict) and hook.get("id") == hook_id:
                return hook.get("entry")
    return None


def check_precommit(plugin: Path, host: Path) -> list[str]:
    """정적분석 훅 처리. 파일이 없으면 예시를 복사(생성). **이미 있으면 자동
    병합하지 않음** — PyYAML 라운드트립이 기존 주석/포맷을 정규화(파괴)하기 때문.
    대신 빠진 repo/hook 을 감지해 보고만 하고, 사용자가 직접 추가하게 함.
    """
    import yaml

    example = plugin / "pre-commit-hooks.example.yaml"
    dest = host / ".pre-commit-config.yaml"
    if not example.is_file():
        return ["  [!] pre-commit-hooks.example.yaml 없음 — skip"]
    if not dest.is_file():
        shutil.copyfile(example, _host_target(host, dest))
        return ["  [+] .pre-commit-config.yaml 생성 (예시 복사 — local 훅은 팀 언어로 교체)"]
    try:
        ex = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
        cur = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ["  [!] .pre-commit-config.yaml 파싱 실패 — 수동 확인 필요"]
    if not isinstance(ex, dict) or not isinstance(cur, dict):
        return ["  [!] .pre-commit-config.yaml 형식이 예상과 다릅니다 — 수동 확인 필요"]
    by_url = {r.get("repo"): r for r in (cur.get("repos") or []) if isinstance(r, dict)}
    missing: list[str] = []
    for exrepo in ex.get("repos", []):
        url = exrepo.get("repo")
        target = by_url.get(url)
        if target is None:
            missing.append(f"repo {url} (전체)")
            continue
        have = {h.get("id") for h in (target.get("hooks") or []) if isinstance(h, dict)}
        missing += [
            f"{url}#{h.get('id')}" for h in exrepo.get("hooks", []) if h.get("id") not in have
        ]
    # vway-kit 소유 훅의 entry 경로 drift — 스크립트 위치가 바뀌면 기존 entry 가 옛
    # 경로를 가리켜 pre-push 가 깨짐. 자동 수정하지 않고(주석/포맷 보존) 보고만 함.
    ex_entry = _find_hook_entry(ex, OWNED_HOOK_ID)
    cur_entry = _find_hook_entry(cur, OWNED_HOOK_ID)
    stale: list[str] = []
    if ex_entry and cur_entry and ex_entry != cur_entry:
        stale = [
            f"  [!] '{OWNED_HOOK_ID}' entry 가 옛 경로입니다: {cur_entry}",
            f"        → '{ex_entry}' 로 직접 수정하세요(스크립트 위치 변경).",
        ]
    # 구버전 레이어1 모듈 훅 잔재: host 의 `repo: local` 에 폐기 id 가 남아 있으면 제거
    # 권장(레이어2 게이트로 이전됨). 자동 제거하지 않고 안내만(외부 도구 소유·커스텀 훅 보존).
    dep_found = sorted(
        {
            h.get("id")
            for r in (cur.get("repos") or [])
            if isinstance(r, dict) and r.get("repo") == "local"
            for h in (r.get("hooks") or [])
            if isinstance(h, dict) and h.get("id") in DEPRECATED_LOCAL_HOOK_IDS
        }
    )
    notes = list(stale)
    if dep_found:
        notes += [
            f"  [!] 폐기된 레이어1 모듈 훅 발견(repo: local): {', '.join(dep_found)}",
            "        → 레이어2 vdev 게이트(vdev-config.modules[].checks)로 이전됨."
            " 직접 제거 권장(주석/포맷 보존).",
        ]
    if not missing:
        return ["  [=] pre-commit 훅 이미 충족 (변경 없음)", *notes]
    out = [
        "  [i] .pre-commit-config.yaml 가 이미 있어 자동 병합하지 않음(주석/포맷 보존).",
        "  [i] 아래 빠진 항목을 pre-commit-hooks.example.yaml 참고해 직접 추가하세요:",
    ]
    out += [f"        - {m}" for m in missing]
    return out + notes


def _git_config(*args: str) -> str | None:
    """`git config --global <args>` 의 stdout 반환(조회 실패 시 None)."""
    try:
        return subprocess.run(
            ["git", "config", "--global", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
    except Exception:
        return None


def detect_autoupdate_auth() -> list[str]:
    """비공개 마켓 백그라운드 자동 갱신 인증 점검(적용하지 않고 안내만).

    백그라운드 자동 갱신은 결국 git clone/fetch 로 동작하고, git 은 GITHUB_TOKEN 을
    직접 읽지 않음. 비공개 repo 가 무인 인증되려면 세 가지가 필요:
    (1) GITHUB_TOKEN env, (2) 그 토큰을 비대화형으로 넘기는 github.com 자격증명 헬퍼,
    (3) 전역 https→ssh insteadOf 가 있으면 마켓 repo 만 HTTPS 로 두는 예외(SSH 는 백그라운드
    에서 agent 가 없어 실패하므로 HTTPS 를 유지해야 헬퍼가 동작).
    """
    out: list[str] = []

    # (1) 토큰
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        out.append("  [=] GITHUB_TOKEN/GH_TOKEN 환경변수 감지됨")
    else:
        out.append(
            "  [i] 토큰 미설정 — fine-grained PAT(Contents:read)를 발급해\n"
            "      GITHUB_TOKEN 환경변수로 설정하세요(아래 자격증명 헬퍼가 이 값을 읽음)."
        )

    helper = _git_config("--get-all", "credential.https://github.com.helper")
    rules = _git_config("--get-regexp", r"^url\..*\.insteadof$")
    if helper is None or rules is None:
        out.append("  [i] git config 조회 실패 — 자격증명 헬퍼·insteadOf 확인 생략")
        return out

    # (2) github.com 비대화형 자격증명 헬퍼
    if helper.strip():
        out.append("  [=] github.com 자격증명 헬퍼 설정됨(비대화형 인증)")
    else:
        out.append(
            "  [!] github.com 자격증명 헬퍼 없음 — git 은 GITHUB_TOKEN 을 직접 안 읽어\n"
            "      비공개 마켓 백그라운드 fetch 가 막힙니다. env 토큰을 넘기는 헬퍼 설치:\n"
            '      git config --global credential.https://github.com.helper ""\n'
            "      git config --global --add credential.https://github.com.helper \\\n"
            '        \'!f() { test "$1" = get && echo username=x-access-token'
            ' && echo "password=$GITHUB_TOKEN"; }; f\''
        )

    # (3) 광범위 insteadOf 충돌
    lines = [ln.strip().lower() for ln in rules.splitlines() if ln.strip()]
    broad = any(ln.endswith(" https://github.com/") for ln in lines)  # 전역 https→ssh
    surgical = any(MARKETPLACE_URL.lower() in ln for ln in lines)  # 마켓 repo 예외
    if broad and not surgical:
        out.append(
            "  [!] 전역 https→ssh insteadOf 감지 — 토큰(HTTPS)이 SSH 로 치환돼 자동\n"
            "      갱신이 깨집니다. 마켓 repo 만 HTTPS 로 예외 처리하세요(직접 실행):\n"
            f'      git config --global url."{MARKETPLACE_URL}".insteadOf "{MARKETPLACE_URL}"'
        )
    elif broad:
        out.append("  [=] insteadOf 예외(마켓 repo HTTPS 유지) 이미 설정됨")
    else:
        out.append("  [=] 광범위 insteadOf 없음 — 토큰 HTTPS 경로에 충돌 없음")
    return out


# ── uninstall(정리) — setup 의 역연산 ──────────────────────────────────────────


def remove_gitignore_lines(host: Path) -> str:
    """.gitignore 에서 vway-kit 가 추가한 라인만 제거(다른 라인은 보존)."""
    gi = host / ".gitignore"
    if not gi.is_file():
        return "  [=] .gitignore 없음 (skip)"
    try:
        text, eol = _read_host_text(host, gi)
    except OSError as exc:
        return f"  [!] .gitignore 수정 거부({_why(exc)}) — 수동 확인 필요"
    targets = (set(GITIGNORE_LINES) | set(STALE_GITIGNORE_LINES)) - GITIGNORE_KEEP
    lines = text.splitlines()
    kept = [ln for ln in lines if ln.strip() not in targets]
    removed = len(lines) - len(kept)
    held = sorted(GITIGNORE_KEEP & {ln.strip() for ln in kept})
    note = f" — 비밀 파일 보호 라인 유지: {', '.join(held)}" if held else ""
    if removed == 0:
        return f"  [=] .gitignore 에 vway-kit 라인 없음 (skip){note}"
    text = "\n".join(kept)
    if text and not text.endswith("\n"):
        text += "\n"
    _write_host_text(gi, text, eol)
    return f"  [-] .gitignore vway-kit 라인 {removed}개 제거{note}"


def remove_claude_md_block(host: Path) -> str:
    """호스트 CLAUDE.md 의 vway-kit:teams 관리 블록(마커 포함)을 제거(없으면 skip)."""
    cm = host / "CLAUDE.md"
    if not cm.is_file():
        return "  [=] CLAUDE.md 없음 (skip)"
    try:
        text, eol = _read_host_text(host, cm)
    except OSError as exc:
        return f"  [!] CLAUDE.md 수정 거부({_why(exc)}) — 수동 확인 필요"
    lines = text.splitlines(keepends=True)
    begin = end = None
    for i, ln in enumerate(lines):
        if begin is None and CLAUDE_MD_BEGIN in ln:
            begin = i
        elif begin is not None and CLAUDE_MD_END in ln:
            end = i
            break
    if begin is None or end is None:
        return "  [=] CLAUDE.md teams 블록 없음 (skip)"
    del lines[begin : end + 1]
    _write_host_text(cm, "".join(lines), eol)
    return "  [-] CLAUDE.md teams 블록 제거"


def remove_rules(host: Path) -> str:
    """이전 셋업이 복사해 둔 룰 디렉터리 삭제 — RULES_DEST 는 vway-kit 전용이라 호스트 자신의
    룰은 남음. 그 자리의 링크·정션은 따라가지 않고 그것만 지우고, 부모가 호스트 밖으로 풀리면
    거부 — 어느 쪽을 커밋한 저장소도 밖의 것을 잃지 않음."""
    d = host / RULES_DEST
    try:
        _confine(host, d.parent)
    except OSError as exc:
        return f"  [!] {RULES_DEST} 정리 거부({_why(exc)}) — 수동 확인 필요"
    if is_reparse_point(d):
        try:
            d.unlink()
        except OSError:
            d.rmdir()  # Windows 의 디렉터리 링크·정션 — rmdir 은 링크만 지우고 너머는 안 건드림
        return f"  [-] {RULES_DEST} 링크 제거"
    if not d.is_dir():
        return f"  [=] {RULES_DEST}/ 없음 (skip)"
    shutil.rmtree(d)
    return f"  [-] {RULES_DEST}/ 삭제"


def remove_vway_dir(host: Path) -> str:
    """.claude/vway-kit/ 디렉터리를 통째 삭제(스크립트·config·증거·웹훅·템플릿 포함).

    템플릿이 있으면 사라진 것으로 **이름을 댐** — 나머지는 이 스크립트가 다시 만들 수
    있는 것이지만 템플릿은 사람이 쓴 산문임. 그래도 지우는 것은 그 자리가 gitignore 밖이라
    커밋했으면 복구가 한 줄이기 때문이고(시드 직후는 아직 untracked 라 그 조건이 문구에
    실림), 조용히 지우면 되돌릴 생각을 못 하기 때문에 이 줄이 있음."""
    d = host / VWAY_DIR
    if not d.is_dir():
        return "  [=] .claude/vway-kit/ 없음 (skip)"
    had_templates = (d / TEMPLATES_DIRNAME).is_dir()
    shutil.rmtree(d)
    kinds = "스크립트·config·증거·웹훅" + (
        "·템플릿(커밋했다면 git 에서 복구)" if had_templates else ""
    )
    return f"  [-] .claude/vway-kit/ 삭제 ({kinds} 포함)"


# /vdev-init·/wiki-init 이 .github/workflows/ 에 렌더하는 것 — 타깃별 deploy-<target>.yml 은 접두로
# 셈. 호스트 자신의 워크플로는 삭제된 스크립트를 부를 때만 보고함.
RENDERED_WORKFLOWS = frozenset(
    Path(dest).name
    for dest in (
        WORKFLOW_DEST,
        WORKFLOW_UNIT_TEST_DEST,
        WORKFLOW_WIKI_VERIFY_DEST,
        WORKFLOW_SRS_VERIFY_DEST,
        WORKFLOW_DOC_STYLE_DEST,
        WORKFLOW_E2E_DEST,
        WORKFLOW_DEPLOY_DEST,
        RELEASE_WORKFLOW_DEST,
        ".github/workflows/branch-naming.yml",
        ".github/workflows/entropy-check.yml",
    )
)
# 스크립트 존재를 먼저 확인하고 없으면 exit 0 하는 렌더(github/*.workflow.example.yml 의 가드).
GUARDED_WORKFLOWS = frozenset(
    Path(dest).name for dest in (WORKFLOW_SRS_VERIFY_DEST, WORKFLOW_DOC_STYLE_DEST)
)
# 릴리스 템플릿 공통 노트 블록의 env 줄 — 그 블록은 `[ -f "$CS" ]` 로 부재를 넘기므로 호출이 아님.
_RELEASE_NOTES_MARK = "# >>> vway-release-notes"
_RELEASE_NOTES_ENV = f"VWAY_SCRIPTS: {SCRIPTS_DIR}"


def _calls_vway_dir(text: str) -> bool:
    """워크플로 본문이 VWAY_DIR 아래를 부르는가. 노트 블록의 가드된 env 줄은 빼고 셈 —
    그것만 가진 semantic-release 렌더는 스크립트 없이도 돎."""
    if _RELEASE_NOTES_MARK in text:
        text = "\n".join(ln for ln in text.splitlines() if ln.strip() != _RELEASE_NOTES_ENV)
    return f"{VWAY_DIR}/" in text


def report_workflows(host: Path) -> list[str]:
    """삭제 뒤 남는 호스트 워크플로를 이름 댐(읽기 전용). 지우는 것은 호스트 몫이고, 어느 것이
    깨지는지는 고정 목록이 아니라 실제로 렌더된 파일이 정함."""
    wf_dir = host / ".github" / "workflows"
    try:
        files = sorted(p for p in wf_dir.iterdir() if p.suffix.lower() in (".yml", ".yaml"))
    except OSError:
        return []
    guarded, failing, running = [], [], []
    for p in files:
        try:
            calls = _calls_vway_dir(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if calls:
            (guarded if p.name in GUARDED_WORKFLOWS else failing).append(p.name)
        elif p.name in RENDERED_WORKFLOWS or p.name.startswith("deploy-"):
            running.append(p.name)
    out = []
    if failing:
        out += [
            f"  - {', '.join(failing)}: 방금 삭제된 {VWAY_DIR}/ 를 가드 없이 불러 실패합니다",
            "    (release.yml 이면 릴리스 브랜치 push 마다). 제거하거나 고치세요.",
        ]
    if guarded:
        out += [
            f"  - {', '.join(guarded)}: 스크립트가 없으면 exit 0 — 아무것도 검증하지 못한 채",
            "    push 마다 러너만 씁니다. 함께 제거하세요.",
        ]
    if running:
        out += [
            f"  - {', '.join(running)}: 삭제된 스크립트를 부르지 않아 계속 돕니다.",
            "    더 쓰지 않으면 직접 제거하세요(자동 삭제 안 함 — 팀 커스텀 보존).",
        ]
    # release.yml 의 deploy 호출 job 이 deploy.yml 을 부름 — 파일만 지우면 릴리스가 깨짐.
    # 배선을 지우는 /vdev-init 경로는 config 가 있어야 하므로 정리 전에만 쓸 수 있음.
    if any(n == "deploy.yml" or n.startswith("deploy-") for n in running):
        out += [
            "  - deploy.yml 과 deploy-*.yml 을 지우려면 release.yml 의 deploy 호출 job 도",
            "    함께 지우세요 — 남기면 없는 deploy.yml 을 불러 릴리스가 실패합니다.",
            "    정리 전이라면 vdev-config.deploy.enable 을 false 로 두고 /vdev-init 을",
            "    재실행해 배선을 지웁니다.",
        ]
    return out


def _load_yaml_safe(path: Path) -> dict:
    """YAML 파일을 dict 로 읽음. 부재·파싱 실패·비dict 는 {}(FAIL-OPEN)."""
    import yaml

    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeError):
        # UnicodeError(UnicodeDecodeError 의 부모)는 OSError 의 서브클래스가 아니라 별도로
        # 잡아야 함 — 안 잡으면 비 UTF-8 바이트 하나가 FAIL-OPEN 을 깨고 예외를 흘림.
        return {}
    return data if isinstance(data, dict) else {}


def _diff_missing(ex: dict, cur: dict, prefix: list[str]) -> list[dict]:
    """example 에 있고 host(cur)에 없는 키를 삽입 단위로 재귀 수집(example 순서).

    - cur 에 키가 없으면 그 지점을 삽입 단위로 기록(하위로 더 내려가지 않음 —
      부모 블록째 verbatim 삽입되므로).
    - 양쪽 dict 면 더 내려감. cur 쪽이 dict 가 아니면(스칼라/리스트/빈값) 멈춤.
    - example 값이 dict 인데 host 값이 dict 가 아니면(스칼라/리스트) 재귀를 멈추고
      해당 서브트리는 무보고로 남김(host 가 커스텀 타입으로 설정한 것으로 간주).
    """
    out: list[dict] = []
    for key, ex_val in ex.items():
        if key not in cur:
            path = prefix + [key]
            out.append({"path": path, "parent": list(prefix), "label": ".".join(path)})
        elif isinstance(ex_val, dict) and isinstance(cur.get(key), dict):
            out.extend(_diff_missing(ex_val, cur[key], prefix + [key]))
    return out


def missing_config_slots(host: Path, plugin: Path) -> list[dict]:
    """example 에 있고 host config 에 없는 슬롯을 삽입 단위로 반환(example 등장 순).

    각 항목 {"path", "parent", "label"}. '빠짐' 은 키 부재만(값이 비어도 키 있으면
    제외 — 의도적 빈 값 보존). host config 부재·빈 config·파싱 실패 시에는 example
    최상위 슬롯 전부를 반환함(신규 설치와 동등). 이 함수는 vdev-init 이 host config
    존재 시에만 호출함(신규 설치는 별도 전체 생성 경로). example 부재 → [].
    vdev-init 이 이 목록으로 example 블록을 verbatim 삽입함(주석 보존).
    """
    ex = _load_yaml_safe(plugin / EXAMPLE_CONFIG)
    if not ex:
        return []
    cur = _load_yaml_safe(config_path(host))
    return _diff_missing(ex, cur, [])


def report_missing_config_slots(host: Path, plugin: Path) -> list[str]:
    """run_setup 보고용: 빠진 config 슬롯을 사람이 읽을 줄로. 없으면 skip 한 줄."""
    slots = missing_config_slots(host, plugin)
    if not slots:
        return ["  [=] config 슬롯 최신 (skip)"]
    labels = ", ".join(s["label"] for s in slots)
    return [
        f"  [i] example 에 새 config 슬롯 {len(slots)}개: {labels}",
        "      → /vdev-init 으로 호스트 config 에 추가를 검토하세요.",
    ]


def report_alm_layers(host: Path, plugin: Path) -> list[str]:
    """스페이스마다 `alm.recoble.spaces[*].layers` 해석 결과를 사람이 읽을 줄로.

    미선언은 skip — 계층 추적은 옵트인이고, 안 쓰는 호스트는 task-import 경로가 정상.
    선언이 **있는데 깨진** 경우만 여기서 드러남: `alm-trace` 는 실행 시점에야 errors 를
    내고 그 전까지 호스트는 추적이 켜진 줄 알며, 링크가 안 그려진 보드는 전파가 걸을
    길이 없어 조용히 아무것도 안 함.

    모듈이 없으면 이 진단만 빠짐(FAIL-OPEN, Invariant 1). `_step` 은 OSError 계열만
    잡으므로 ImportError 를 흘리면 진단 하나가 셋업 전체를 세움 — 게이트 등록까지.
    """
    try:
        try:
            from alm_layers import resolve_layers
        except ImportError:  # 패키지(테스트)에선 scripts. 접두 — _vway_paths 와 같은 규율
            from scripts.alm_layers import resolve_layers
    except ImportError:
        return ["  [~] alm_layers 를 못 읽어 계층 점검 건너뜀"]

    cfg = config_path(host)
    alm = _load_yaml_safe(cfg).get("alm")
    recoble = alm.get("recoble") if isinstance(alm, dict) else None
    spaces = recoble.get("spaces") if isinstance(recoble, dict) else None
    if not isinstance(spaces, dict):
        return ["  [=] ALM 계층 선언 없음 (skip)"]

    out: list[str] = []
    for key in spaces:
        got = resolve_layers(cfg, str(key), plugin, host)
        if not got["configured"]:
            continue
        out.extend(f"  [!] {key}: {line}" for line in got["errors"])
        out.extend(f"  [~] {key}: {line}" for line in got["warnings"])
        if not got["errors"]:
            names = ", ".join(x["key"] for x in got["layers"])
            out.append(f"  [=] {key}: 계층 {len(got['layers'])}개 ({names})")
    return out or ["  [=] ALM 계층 선언 없음 (skip)"]


def detect_legacy_test_command(host: Path) -> dict:
    """호스트 config 의 폐기된 전역 `test.command` 상태를 진단함(module-precheck
    design G — 기계 보고). 전역 test 는 폐기됐고 테스트의 자리는 모듈별 `checks.test`
    (vdev-config.example.yaml 주석). 재실행 마이그레이션에서 이 잔재가 조용히
    남지 않도록 매 setup 이 진단을 표면화함.

    반환 dict:
      - present: bool            전역 `test.command` 가 남아 있는가
      - command: str | None      그 명령(스크립트일 수 있음 — SKILL 이 끝까지 추적)
      - module_test_covered: bool  modules[].checks.test 가 하나라도 있는가

    modules 커버리지가 있으면 안전 제거, 없으면 먼저 modules 로 이전해야 함을 뜻함.
    부재·파싱 실패는 present=False(FAIL-OPEN — 셋업/게이트를 막지 않음).
    슬롯 점검(missing_config_slots)은 example↔host 대칭 비교라 example 에서 사라진
    `test:` 를 못 잡음 — 그래서 host 쪽 잔재를 보는 이 별도 진단이 필요함.
    """
    cfg = _load_yaml_safe(config_path(host))
    block = cfg.get("test")
    command = None
    present = False
    if isinstance(block, dict) and block.get("command"):
        present = True
        command = str(block.get("command"))
    covered = False
    modules = cfg.get("modules")
    if isinstance(modules, list):
        for mod in modules:
            checks = mod.get("checks") if isinstance(mod, dict) else None
            if isinstance(checks, dict) and checks.get("test"):
                covered = True
                break
    return {"present": present, "command": command, "module_test_covered": covered}


def report_legacy_test_command(host: Path) -> list[str]:
    """run_setup 보고용: 폐기된 전역 test.command 진단을 사람이 읽을 줄로.

    - 없음 → skip 한 줄.
    - 있고 modules[].checks.test 미커버 → [!] 먼저 modules 로 이전(스크립트면 끝까지
      추적) 후 제거 안내(검증 공백 방지 — 커버 전엔 제거 금지).
    - 있고 커버됨 → [i] /vdev-init 재실행으로 이 test: 블록 제거를 확인하라 안내.
    실제 추적·이전·제거는 SKILL(Step 2.6)이 판단으로 수행함(무단 편집 안 함).
    """
    diag = detect_legacy_test_command(host)
    if not diag["present"]:
        return ["  [=] 폐기된 전역 test.command 없음 (skip)"]
    cmd = diag["command"] or ""
    if diag["module_test_covered"]:
        return [
            f"  [i] 폐기된 전역 test.command 발견: {cmd!r}",
            "      → modules[].checks.test 커버리지 있음. /vdev-init 재실행으로 이 test: 블록"
            " 제거를 확인하세요.",
        ]
    return [
        f"  [!] 폐기된 전역 test.command 발견(modules 미이전): {cmd!r}",
        "      → 이 명령(스크립트면 실제 테스트까지 끝까지 추적)을 modules[].checks.test 로"
        " **먼저** 이전한 뒤 제거하세요(검증 공백 방지).",
        "      → /vdev-init 재실행이 이전·제거를 안내합니다(무단 삭제 안 함).",
    ]


def detect_legacy_alm_config(host: Path) -> dict:
    """호스트 config 의 폐기된 **최상위 `teamer:`** 블록 상태를 진단함(ALM provider 추상화).

    Teamer 번호의 자리는 `alm.teamer`. 최상위 `teamer:` 는 `load_alm_config` 가
    `alm:` 이 **없을 때만** 하위호환으로 읽음 — `alm:` 이 생기는 순간 조용히 죽음.

    반환 dict:
      - present: bool             최상위 `teamer:` 가 남아 있는가
      - fields: dict              그 블록의 값(project_no/workitem_no/workflow_no …)
      - alm_present: bool         `alm:` 블록이 이미 있는가
      - alm_teamer_covered: bool  `alm.teamer` 가 값으로 채워져 있는가
      - alm_teamer_matches: bool  `alm.teamer` 가 구 블록의 값을 **그대로** 갖고 있는가
        (커버돼 있어도 값이 다르면 이전이 아니라 example 예시 번호가 들어온 것 —
        이 구분이 없으면 가장 해로운 상태가 [i] 로 조용히 넘어감)

    슬롯 점검(`missing_config_slots`)은 example↔host **대칭 비교**라 이 상황을 못 잡음.
    그쪽은 `alm` 을 '빠진 슬롯' 으로만 보고하고, Step 2.5 의 verbatim 삽입이 example 의
    예시 번호(996/188180/164489)와 자리표시자 mcp_url 을 그대로 들여와 **호스트의 진짜
    Teamer 연동을 무력화**함. 그래서 host 쪽 잔재를 보는 이 별도 진단이 필요함
    (`detect_legacy_test_command` 와 같은 이유·같은 모양).

    부재·파싱 실패는 present=False(FAIL-OPEN — 셋업/게이트를 막지 않음).
    """
    cfg = _load_yaml_safe(config_path(host))
    block = cfg.get("teamer")
    present = isinstance(block, dict) and bool(block)
    alm = cfg.get("alm")
    # 빈 dict `alm: {}` 도 present — load_alm_config 는 isinstance 만 보고 채택하므로
    # (빈 alm 도 legacy `teamer:` 를 죽임) 진단이 다르게 판정하면 오진이 됨.
    alm_present = isinstance(alm, dict)
    alm_teamer = alm.get("teamer") if isinstance(alm, dict) else None
    covered = isinstance(alm_teamer, dict) and bool(alm_teamer)
    fields = dict(block) if present else {}
    matches = covered and all(str(alm_teamer.get(k)) == str(v) for k, v in fields.items())
    return {
        "present": present,
        "fields": fields,
        "alm_present": alm_present,
        "alm_teamer_covered": covered,
        "alm_teamer_matches": matches,
    }


def report_legacy_alm_config(host: Path) -> list[str]:
    """run_setup 보고용: 폐기된 최상위 `teamer:` 진단을 사람이 읽을 줄로.

    - 없음 → skip 한 줄.
    - 있고 `alm:` 없음 → [!] 아직 하위호환으로 살아 있지만, `alm:` 슬롯을 넣는 순간
      죽음. 값을 `alm.teamer` 로 옮긴 뒤 최상위 블록을 제거하라 안내.
    - 있고 `alm:` 있는데 `alm.teamer` 비었음 → [!] **이미 죽은 값**(Teamer 연동이
      조용히 멈춘 상태). 같은 이전을 지시.
    - 있고 `alm.teamer` 가 **다른 값**으로 채워짐 → [!] 이전이 아니라 example 예시
      번호가 들어온 상태(가장 해로움 — 남의 프로젝트를 가리킴). 두 값을 나란히 보임.
    - 있고 `alm.teamer` 가 같은 값 → [i] 이전이 끝난 것. 최상위 블록 제거만 안내.
    실제 이전·제거는 SKILL(Step 2.5)이 판단으로 수행함(무단 편집 안 함).
    """
    diag = detect_legacy_alm_config(host)
    if not diag["present"]:
        return ["  [=] 폐기된 최상위 teamer: 없음 (skip)"]
    vals = ", ".join(f"{k}={v}" for k, v in diag["fields"].items())
    move = "      → 이 값을 alm.teamer 로 옮긴 뒤 최상위 teamer: 를 제거하세요."
    example = (
        "      → 슬롯 백필로 example 의 alm: 블록을 넣을 때 예시 번호(996/188180/"
        "164489)와 자리표시자 mcp_url 을 그대로 두지 마세요."
    )
    if not diag["alm_present"]:
        return [f"  [!] 폐기된 최상위 teamer: 발견(alm: 없음): {vals}", move, example]
    if not diag["alm_teamer_covered"]:
        return [
            f"  [!] 폐기된 최상위 teamer: 가 이미 무시되고 있습니다(alm: 존재): {vals}",
            "      → load_alm_config 는 alm 을 우선하므로 이 번호는 지금 아무 데도 쓰이지"
            " 않습니다(Teamer 연동 중단 상태).",
            move,
        ]
    if not diag["alm_teamer_matches"]:
        return [
            f"  [!] 최상위 teamer: 와 alm.teamer 의 값이 다릅니다 — 구(죽은 값): {vals}",
            "      → 지금 쓰이는 것은 alm.teamer 뿐입니다. 슬롯 백필이 넣은 example 예시"
            " 번호가 아닌지 확인하고, 구 값이 맞다면 alm.teamer 를 그 값으로 고치세요.",
            "      → 확인 후에만 최상위 teamer: 를 제거하세요.",
        ]
    return [
        f"  [i] 폐기된 최상위 teamer: 이전 완료(alm.teamer 와 값 일치): {vals}",
        "      → 최상위 teamer: 를 제거하세요(죽은 설정).",
    ]


def detect_check_timing_issues(host: Path) -> list[dict]:
    """호스트 config 의 modules[].checks 중 잘못된 when 값을 진단함(작성 시점 엄격 점검).

    확장 형식 {run, when} 에서 when 이 CHECK_TIMINGS 밖이면 오타로 봄. 런타임
    게이트는 이를 FAIL-OPEN 으로 키 기본값 라우팅하지만(vdev_gate_check._parse_check),
    여기서는 사용자가 오타를 인지하도록 표면화함. 문자열 값·when 생략은 정상(진단
    안 함). 부재·파싱 실패는 [] (FAIL-OPEN — 셋업을 막지 않음).

    타이밍 필드명은 `when`(`on` 아님) — YAML 1.1(PyYAML)이 따옴표 없는 `on:`
    키를 불리언 True 로 해석하는 함정(Norway Problem 의 키 버전)을 피하기 위함.

    반환: [{"module": name, "check": key, "when": bad_value}, ...]
    """
    cfg = _load_yaml_safe(config_path(host))
    modules = cfg.get("modules")
    issues: list[dict] = []
    if not isinstance(modules, list):
        return issues
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        name = str(mod.get("name") or mod.get("path") or "?")
        checks = mod.get("checks")
        if not isinstance(checks, dict):
            continue
        for key, val in checks.items():
            if not isinstance(val, dict) or "when" not in val:
                continue
            timing = val.get("when")
            if timing not in CHECK_TIMINGS:
                issues.append({"module": name, "check": str(key), "when": timing})
    return issues


def report_check_timing(host: Path) -> list[str]:
    """run_setup 보고용: 잘못된 when 값을 사람이 읽는 경고 줄로(없으면 skip 한 줄).

    경고만 함(거부 아님) — 런타임은 FAIL-OPEN 키 기본값으로 계속 동작하므로 커밋을
    막지 않음. 사용자가 config 를 고치도록 안내만 함.
    """
    issues = detect_check_timing_issues(host)
    if not issues:
        return ["  [=] checks.when 타이밍 값 정상 (skip)"]
    allowed = "|".join(CHECK_TIMINGS)
    lines = [f"  [!] 잘못된 checks.when 값 {len(issues)}개 (허용: {allowed}):"]
    for it in issues:
        lines.append(
            f"      → {it['module']}.{it['check']}: when={it['when']!r} — 키 기본값으로"
            " 라우팅됩니다. config 를 고치세요."
        )
    return lines


def load_contract_config(host: Path) -> dict | None:
    """vdev-config.yaml 의 contract_test dict 를 반환(없거나 파싱 실패 시 None — FAIL-OPEN)."""
    import yaml

    cfg = config_path(host)
    if not cfg.is_file():
        return None
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(data, dict):
        # 사람이 손대는 호스트 파일이라 최상위의 리스트나 스칼라는 불가능이 아니라
        # 오타 — 읽지 않으면 판정에 닿기 전에 실행을 끝내 버림.
        return None
    ct = data.get("contract_test")
    return ct if isinstance(ct, dict) else None


def render_workflow(host: Path, plugin: Path) -> list[str]:
    """contract_test 설정으로 .github/workflows/api-contract.yml 을 렌더링함.

    멱등·비파괴: enable=false/섹션부재면 미설치, 대상 파일이 이미 있으면 보고만
    (자동 병합·덮어쓰기 X — .pre-commit-config.yaml 과 동일 패턴). GitHub 이 위치를
    강제하므로 .github/workflows/ 는 VWAY_DIR 규칙의 예외.
    """
    ct = load_contract_config(host)
    if ct is None:
        return ["  [=] contract_test 미설정 — 워크플로우 skip"]
    if not ct.get("enable"):
        return ["  [=] contract_test.enable=false — 워크플로우 미설치"]
    template = plugin / WORKFLOW_TEMPLATE
    if not template.is_file():
        return ["  [!] 워크플로우 템플릿 없음 — skip"]
    dest = host / WORKFLOW_DEST
    if dest.is_file():
        return [
            "  [i] .github/workflows/api-contract.yml 이미 있어 자동 병합 안 함(주석/커스텀 보존).",
            "  [i] 갱신하려면 기존 파일을 지우고 /vdev-init 을 재실행하거나 직접 수정하세요.",
        ]
    branches = ct.get("branches") or ["dev", "stage", "main"]
    server = ct.get("server") or {}
    replacements = {
        "__VWAY_BRANCHES__": ", ".join(str(b) for b in branches),
        "__VWAY_ACTION_REF__": str(ct.get("action_ref", "schemathesis/action@v3")),
        "__VWAY_SCHEMA__": str(ct.get("schema", "")),
        "__VWAY_BASE_URL__": str(ct.get("base_url", "")),
        "__VWAY_COMPOSE_FILE__": str(server.get("compose_file", "docker-compose.yml")),
        "__VWAY_HEALTH_URL__": str(server.get("health_url", "")),
        "__VWAY_HEALTH_TIMEOUT__": str(server.get("health_timeout", 60)),
    }
    try:
        text = template.read_text(encoding="utf-8")
        for token, value in replacements.items():
            text = text.replace(token, value)
        _host_target(host, dest).parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    except OSError as exc:
        return [f"  [!] 워크플로우 렌더링 실패(수동 확인): {exc}"]
    return ["  [+] .github/workflows/api-contract.yml 생성 (contract_test 렌더링)"]


def load_versioning_config(host: Path) -> dict | None:
    """vdev-config.yaml 의 versioning dict 반환(없거나 파싱 실패 시 None — FAIL-OPEN)."""
    cfg = host / VWAY_DIR / "config" / "vdev-config.yaml"
    try:
        data = _load_yaml_safe(cfg)
    except Exception:
        return None
    v = data.get("versioning")
    return v if isinstance(v, dict) else None


def load_integration_branch(host: Path) -> str:
    """vdev-config `branches.integration` — 부재·파싱 실패는 `dev`(FAIL-OPEN)."""
    branches = _load_yaml_safe(config_path(host)).get("branches")
    value = branches.get("integration") if isinstance(branches, dict) else None
    return str(value or "dev")


_RELEASE_TEMPLATES = {
    "python-semantic-release": "github/release.python-semantic-release.workflow.example.yml",
    "semantic-release": "github/release.semantic-release.workflow.example.yml",
    "jreleaser": "github/release.jreleaser.workflow.example.yml",
    "gitversion": "github/release.gitversion.workflow.example.yml",
    "cargo-release": "github/release.cargo-release.workflow.example.yml",
    "sbt-ci-release": "github/release.sbt-ci-release.workflow.example.yml",
}


def _render_one(
    host: Path, src: Path, dest: Path, subs: dict, label: str = "versioning"
) -> list[str]:
    if not src.exists():
        return [f"  [!] 템플릿 없음: {src.name} — skip"]
    if dest.exists():
        return [f"  [i] {dest.name} 이미 있어 자동 병합 안 함(커스텀 보존)."]
    text = src.read_text(encoding="utf-8")
    for k, val in subs.items():
        text = text.replace(k, val)
    try:
        _host_target(host, dest).parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    except OSError as exc:
        return [f"  [!] {dest.name} 렌더링 실패({_why(exc)}) — 수동 확인 필요"]
    return [f"  [+] .github/workflows/{dest.name} 생성 ({label} 렌더)"]


def render_versioning_workflows(host: Path, plugin: Path) -> list[str]:
    """versioning 설정으로 release/branch-naming/entropy 워크플로우를 렌더링함.

    멱등·비파괴: enable=false/섹션부재면 미설치, 대상 파일이 이미 있으면 보고만
    (자동 병합·덮어쓰기 X). FAIL-OPEN — 예외는 통과(게이트를 막지 않음).
    release_tool 이 `_RELEASE_TEMPLATES` 에 없으면(Go/C++ 등) release.yml 은
    만들지 않고 `[?]` 보고만 남김 — vdev-init SKILL.md 가 이 신호를 받아 AI 가
    직접 작성하도록 오케스트레이션함(스크립트가 모르는 도구를 추측해 만들지 않음).
    """
    v = load_versioning_config(host)
    if not v:
        return ["  [=] versioning 미설정 — 워크플로 skip"]
    if not v.get("enable", False):
        return ["  [=] versioning.enable=false — 워크플로 미설치"]
    out: list[str] = []
    branches = v.get("branches", {}) or {}
    stable = str(branches.get("stable", "main"))
    prerelease = str(branches.get("prerelease", "") or "")
    subs = {
        "__VWAY_STABLE__": stable,
        "__VWAY_PRERELEASE__": prerelease,
        "__VWAY_INTEGRATION__": load_integration_branch(host),
    }
    wf_dir = host / ".github" / "workflows"

    # release (도구별). 템플릿이 있으면 스크립트가 결정적으로 렌더링함(python/node/
    # java/c#/rust/scala — 이 리포의 검증된 baseline). 템플릿이 없는 도구(Go/C++/기타)는 스크립트가
    # 추측해 만들지 않음 — 고정 템플릿 매핑은 언어가 늘 때마다 다시 깨지므로(하드코딩
    # whack-a-mole), 대신 AI(vdev-init 오케스트레이터)가 감지된 스택을 확인해 해당
    # 도구의 표준 CI 저작법으로 release.yml 을 직접 작성하도록 보고만 남김.
    release_dest = wf_dir / "release.yml"
    tool = str(v.get("release_tool", ""))
    tmpl = _RELEASE_TEMPLATES.get(tool)
    if tmpl:
        out += _render_one(host, plugin / tmpl, release_dest, subs)
    elif release_dest.exists():
        out.append("  [i] release.yml 이미 있어 자동 병합 안 함(커스텀 보존).")
    else:
        out.append(
            f"  [?] release_tool={tool!r} 은 준비된 템플릿이 없습니다 — AI 가 감지 스택에 "
            "맞춰 .github/workflows/release.yml 을 직접 작성해야 합니다(자동 렌더 불가)."
        )

    # branch-naming
    if (v.get("branch_naming", {}) or {}).get("enable", False):
        out += _render_one(
            host,
            plugin / "github/branch-naming.workflow.example.yml",
            wf_dir / "branch-naming.yml",
            subs,
        )

    # entropy
    ent = v.get("entropy", {}) or {}
    if ent.get("enable", False):
        esub = dict(subs)
        esub["__VWAY_ENTROPY_SCHEDULE__"] = str(ent.get("schedule", "0 0 * * 5"))
        esub["__VWAY_ENTROPY_PATHS__"] = " ".join(str(p) for p in (ent.get("paths") or ["src/"]))
        out += _render_one(
            host,
            plugin / "github/entropy-check.workflow.example.yml",
            wf_dir / "entropy-check.yml",
            esub,
        )
    return out


def load_unit_test_config(host: Path) -> dict | None:
    """vdev-config.yaml 의 unit_test dict 반환(없거나 파싱 실패 시 None — FAIL-OPEN)."""
    ut = _load_yaml_safe(config_path(host)).get("unit_test")
    return ut if isinstance(ut, dict) else None


def load_e2e_config(host: Path) -> dict | None:
    """vdev-config.yaml 의 e2e 블록. 부재·파싱 실패는 None(FAIL-OPEN)."""
    e2e = _load_yaml_safe(config_path(host)).get("e2e")
    return e2e if isinstance(e2e, dict) else None


def load_doc_style_config(host: Path) -> dict | None:
    """vdev-config.yaml 의 doc_style 블록. 부재·파싱 실패는 None(FAIL-OPEN)."""
    doc_style = _load_yaml_safe(config_path(host)).get("doc_style")
    return doc_style if isinstance(doc_style, dict) else None


def _matrix_include(jobs: list) -> tuple[str, list[str]]:
    """unit_test.jobs[] 를 strategy.matrix.include 용 flow-style 한 줄로 직렬화함.

    각 job 을 UNIT_TEST_JOB_KEYS 5개로 정규화함(누락 키는 빈 문자열 — 템플릿의
    `if: matrix.setup != ''` 가 안전하게 동작하고 matrix 엔트리가 균일해짐).
    `test` 가 없는 job 은 CI 에서 실행할 것이 없으므로 제외하고 보고함.
    `language` 는 대소문자 무관하게 매칭함(casefold) — `UNIT_TEST_OFFICIAL_LANGUAGES`
    멤버십 판정과 matrix 엔트리에 쓰는 값 모두 정규화(소문자)된 값을 씀. 정규화하지
    않으면 config 오타(예: `language: Python`)가 이스케이프 해치로 조용히 새서, 공식
    setup action 이 안 돌고 테스트 스텝이 러너의 기본 런타임으로 실행되는 조용한 오탐
    통과가 됨(템플릿의 `if: matrix.language == 'python'` 은 소문자 리터럴이므로).
    `language` 가 공식 setup action 5종(UNIT_TEST_OFFICIAL_LANGUAGES) 중 하나인데
    `version` 이 비어 있는 job 도 제외하고 보고함 — 빈 `version` 은 해당 action 에
    `with: {버전키: ''}` 로 명시 전달되어 action 자체의 default 를 무력화하고(GitHub
    Actions 는 키가 아예 없을 때만 default 를 채움) 런타임 가드에서 에러를 냄
    (예: dtolnay/rust-toolchain 의 "'toolchain' is a required input"). `language` 가
    표 밖(빈 문자열 포함)이면 matrix.setup 이스케이프 해치가 런타임을 전담하므로 그대로 둠.
    빈 `name` 은 생존(드롭되지 않은) job 중 1-based 순번으로 `job-{i}` 를 채움(Actions UI 에
    빈 라벨이 뜨는 것 방지). 생존 job 간 `name` 이 중복되면 드롭하지 않고 `[!]` 로 경고만
    함(GitHub 은 그래도 별개 job 을 만들지만 UI 라벨이 겹쳐 혼란스러움).
    flow-style 이라 템플릿 앵커의 들여쓰기와 무관함(블록 주입의 인덴트 정합 문제 회피).
    반환: (직렬화 문자열 — 유효 job 이 없으면 빈 문자열, 경고 줄 목록)
    """
    import yaml

    entries: list[dict] = []
    notes: list[str] = []
    for job in jobs:
        if not isinstance(job, dict) or not str(job.get("test") or "").strip():
            notes.append(f"  [!] unit_test.jobs 항목에 test 명령이 없어 제외: {job!r}")
            continue
        lang = str(job.get("language") or "").strip().casefold()
        ver = str(job.get("version") or "").strip()
        if lang in UNIT_TEST_OFFICIAL_LANGUAGES and not ver:
            notes.append(
                f"  [!] unit_test.jobs 항목({job.get('name')!r})의 language={lang!r} 는 "
                "공식 setup action 을 쓰므로 version 이 필요합니다(비어 있으면 해당 action "
                f"이 실패) — version 을 채우거나 제외: {job!r}"
            )
            continue
        entry = {k: str(job.get(k) or "") for k in UNIT_TEST_JOB_KEYS}
        entry["language"] = lang  # 정규화된 값을 써야 템플릿의 소문자 if: 게이트가 매치됨
        if not entry["name"].strip():
            entry["name"] = f"job-{len(entries) + 1}"  # 생존 job 중 1-based 순번
        entries.append(entry)
    if not entries:
        return "", notes
    dupes = sorted(name for name, cnt in Counter(e["name"] for e in entries).items() if cnt > 1)
    if dupes:
        notes.append(
            f"  [!] unit_test.jobs 항목 중 name 이 중복됨({', '.join(dupes)}) — 드롭하지 않지만 "
            "GitHub Actions UI 에 같은 라벨의 matrix job 이 여럿 표시됩니다."
        )
    dumped = yaml.safe_dump(entries, default_flow_style=True, width=10**6, allow_unicode=True)
    return dumped.strip(), notes


def render_wiki_verify_workflow(host: Path, plugin: Path) -> list[str]:
    """wiki-verify.yml 을 그대로 복사함 — enable 게이트도 치환 토큰도 없음.

    닿는 길은 `/wiki-init` 의 단계(`--render-wiki-verify`) 하나이고 run_setup 이 아님:
    이 워크플로가 검증하는 것은 wiki 인데 /vdev-init 시점에는 검증할 것이 없어, 그 질문을
    받은 사용자에게 답할 근거가 없음. /wiki-init 이 물을 때는 그래프가 있고 `--verify` 가
    그것을 통과한 뒤라, 여기서 설정을 읽을 것도 남지 않음 — 사용자의 "예" 가 게이트임.

    멱등·비파괴(대상이 이미 있으면 보고만) — 다른 렌더와 같음. 그래서 이미 그 파일을 가진
    호스트는 손대지 않은 채로 둠."""
    return _render_one(
        host,
        plugin / WORKFLOW_WIKI_VERIFY_TEMPLATE,
        host / WORKFLOW_WIKI_VERIFY_DEST,
        {},
        "wiki-verify",
    )


def render_srs_verify_workflow(host: Path, plugin: Path) -> list[str]:
    """srs-verify.yml 을 그대로 복사 — enable 게이트도 토큰도 없음.

    닿는 길은 `/vdev-init` 의 단계(`--render-srs-verify`) 하나이고 run_setup 이 아님:
    워크플로가 docs/srs 를 읽으므로, 그것이 없는 호스트에는 가리킬 대상이 없음. 사용자의
    yes 가 곧 게이트라 여기서 config 를 읽지 않음.

    멱등·비파괴(기존 dest 는 보고만) — 여기 모든 렌더와 같음.
    """
    return _render_one(
        host,
        plugin / WORKFLOW_SRS_VERIFY_TEMPLATE,
        host / WORKFLOW_SRS_VERIFY_DEST,
        {},
        "srs-verify",
    )


def render_doc_style_workflow(host: Path, plugin: Path) -> list[str]:
    """doc-style.yml 을 그대로 복사함 — 치환 토큰은 없고, `doc_style.enable` 이 게이팅함.

    이 플래그가 e2e 의 것과 갈리는 지점: 렌더 스위치이면서 **실행 스위치**이기도 함.
    `doc_style_check.py` 가 `enable` 이 거짓이면 자기 경로 목록을 비우므로, 켜져 있을 때
    렌더된 파일이 되돌리는 순간 조용해짐 — 멈추려고 지울 것이 없음.

    게이팅하는 이유는 이 워크플로가 산문 레이어의 **유일한 판정**이라서임 — 커밋 시점
    단계는 경고만 하고 차단하지 않음. 가정하지 않고 묻는 근거가 그것임: 여기의 침묵은
    green 으로 끝난 검사가 아니라 아무도 강제하지 않는 규칙이고, /vdev-init 이 이 플래그를
    걷을 때 그 사실을 말함.

    멱등·비파괴(대상이 이미 있으면 보고만) — 다른 렌더와 같음.
    """
    cfg = load_doc_style_config(host)
    if cfg is None:
        return ["  [=] doc_style 미설정 — 워크플로 skip"]
    if not cfg.get("enable"):
        return ["  [=] doc_style.enable=false — 워크플로 미설치"]
    return _render_one(
        host, plugin / WORKFLOW_DOC_STYLE_TEMPLATE, host / WORKFLOW_DOC_STYLE_DEST, {}, "doc-style"
    )


def render_e2e_workflow(host: Path, plugin: Path) -> list[str]:
    """e2e.yml 을 그대로 복사함 — 치환 토큰은 없고, boolean 하나가 게이팅함.

    이 boolean 은 **렌더 스위치이지 실행 스위치가 아님** — 자기 스크립트도 함께 읽는
    doc_style 의 것과 갈리는 지점이 거기임. false 로 되돌려도 이미 렌더된
    파일은 계속 돌고, 멈추는 것은 `.github/workflows/e2e.yml` 삭제임. 아래 보고가 플래그가
    아니라 스캐폴드를 지목하는 이유가 그 비대칭임.

    멱등·비파괴(대상이 이미 있으면 보고만) — 다른 렌더와 같음.
    """
    cfg = load_e2e_config(host)
    if cfg is None:
        return ["  [=] e2e 미설정 — 워크플로 skip"]
    if not cfg.get("enable"):
        return ["  [=] e2e.enable=false — 워크플로 미설치"]
    out = _render_one(host, plugin / WORKFLOW_E2E_TEMPLATE, host / WORKFLOW_E2E_DEST, {}, "e2e")
    # 전달은 사람이 당기는 방아쇠(playwright.config.* 는 /playwright-scaffold 소유)라,
    # boolean 이 못 막는 상태가 하나 남음 — "워크플로는 렌더됐고 스위트는 어디에도 없음".
    # 템플릿의 detect 스텝이 그것을 green 으로 유지하고, 이 줄이 그것을 영구가 아니게 함.
    # 루트 + 두 단계 아래까지 — 워크플로 자신의 `find -maxdepth 3`
    # (github/e2e.workflow.example.yml)과 같은 깊이. 워크플로는 찾는데 이 글로브가 못
    # 찾으면 EDIT 4 예시 경로(apps/web/playwright.config.ts)에 정확히 낡은 포인터가 뜸.
    # `node_modules` 도 워크플로의 `-not -path` 와 같이 뺌: 렌더러는 그 디렉터리가 **있는**
    # 개발자 머신에서 돌고 워크플로는 그것이 gitignore 된 **체크아웃**에서 도므로, 안 빼면
    # 의존성이 싣고 온 config 하나가 포인터를 지우고 CI 는 found=false 로 아무것도 안 함 —
    # 이 줄이 막으려던 바로 그 상태가 조용히 영구가 됨.
    config_globs = ("playwright.config.*", "*/playwright.config.*", "*/*/playwright.config.*")
    found = (
        hit
        for pattern in config_globs
        for hit in host.glob(pattern)
        if "node_modules" not in hit.parts
    )
    if next(found, None) is None:
        out.append("  [i] playwright.config.* 없음 — /playwright-scaffold 로 먼저 만드세요.")
    return out


def render_unit_test_workflow(host: Path, plugin: Path) -> list[str]:
    """unit_test 설정으로 .github/workflows/unit-test.yml 을 렌더링함(순수 치환).

    **런타임 파생 없음** — modules 나 코드베이스를 읽지 않음(스택 감지는 harness-init
    영역). jobs[] 초안 작성은 /vdev-init SKILL 이 셋업 시점에 1회 수행함.
    멱등·비파괴: enable=false/섹션부재/jobs 공백이면 미설치, 대상이 이미 있으면 보고만
    (자동 병합·덮어쓰기 X — render_workflow 와 동일 패턴). FAIL-OPEN.
    """
    ut = load_unit_test_config(host)
    if ut is None:
        return ["  [=] unit_test 미설정 — 워크플로 skip"]
    if not ut.get("enable"):
        return ["  [=] unit_test.enable=false — 워크플로 미설치"]
    template = plugin / WORKFLOW_UNIT_TEST_TEMPLATE
    if not template.is_file():
        return ["  [!] unit-test 워크플로 템플릿 없음 — skip"]
    dest = host / WORKFLOW_UNIT_TEST_DEST
    if dest.is_file():
        return [
            "  [i] .github/workflows/unit-test.yml 이미 있어 자동 병합 안 함(커스텀 보존).",
            "  [i] 갱신하려면 기존 파일을 지우고 /vdev-init 을 재실행하거나 직접 수정하세요.",
        ]
    jobs = ut.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return ["  [!] unit_test.jobs 가 비어 있어 워크플로 미설치 (jobs 를 채우고 재실행)"]
    include, notes = _matrix_include(jobs)
    if not include:
        return [*notes, "  [!] 실행 가능한 unit_test.jobs 가 없어 워크플로 미설치"]
    branches = ut.get("branches") or ["dev", "stage", "main"]
    replacements = {
        "__VWAY_BRANCHES__": ", ".join(str(b) for b in branches),
        "__VWAY_TIMEOUT__": str(ut.get("timeout_minutes", UNIT_TEST_DEFAULT_TIMEOUT)),
        "__VWAY_MATRIX_INCLUDE__": include,
    }
    try:
        text = template.read_text(encoding="utf-8")
        for token, value in replacements.items():
            text = text.replace(token, value)
        _host_target(host, dest).parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    except OSError as exc:
        return [*notes, f"  [!] unit-test 워크플로 렌더링 실패(수동 확인): {exc}"]
    return [*notes, "  [+] .github/workflows/unit-test.yml 생성 (unit_test 렌더링)"]


def load_deploy_config(host: Path) -> dict | None:
    """vdev-config.yaml 의 deploy dict 반환(없거나 파싱 실패 시 None — FAIL-OPEN)."""
    dp = _load_yaml_safe(config_path(host)).get("deploy")
    return dp if isinstance(dp, dict) else None


def _deploy_targets(targets: list, host: Path) -> tuple[list[dict], list[str]]:
    """deploy.targets[] 를 정규화함. 반환: (생존 항목, 경고 줄).

    - `target` 은 대소문자 무관(casefold). 알려진 5종 + `custom` 밖이면 drop + 보고.
    - `custom` 은 `workflow:` 경로가 **실재해야** 함(스킬이 저작한 컴포넌트).
    - 타깃별 필수 키(DEPLOY_REQUIRED_KEYS)가 비면 drop + 보고 — 특히 maven-central 의
      `publish` 는 auto-publish 함정 때문에 기본값을 주지 않음.
    - 빈 `name` 은 생존 job 중 1-based 순번으로 `job-{i}`. 중복 `name` 은 drop 하지 않고
      경고만 함(unit_test 와 동일 규칙).
    """
    items: list[dict] = []
    notes: list[str] = []
    for raw in targets:
        if not isinstance(raw, dict):
            notes.append(f"  [!] deploy.targets 항목이 dict 가 아니어서 제외: {raw!r}")
            continue
        target = str(raw.get("target") or "").strip().casefold()
        # custom 분기의 파생값(workflow 정규화)은 여기 하나에만 모음 — item 조립 직전
        # 별도 `if target == "custom":` 블록에서 다시 읽으면(비인접) 그 변수의 생존이
        # "모든 조기 종료가 continue" 라는 이 함수의 불변식에 암묵적으로 기대게 되어,
        # 나중 리팩터로 조용히 깨질 수 있음(Pyright 도 "possibly unbound" 로 지적).
        overrides: dict = {}
        if target == "custom":
            rel = str(raw.get("workflow") or "").strip()
            if not rel:
                notes.append(f"  [!] target: custom 에 workflow 경로가 없어 제외: {raw!r}")
                continue
            _rel_path = Path(rel)
            # is_absolute() 만으론 Windows 에서 드라이브 없는 루트 경로("/etc/passwd")를
            # 놓침(WindowsPath 는 이를 "절대"로 안 침 — root 는 있는데 drive 가 없어서).
            # root 유무까지 같이 봐야 host 를 discard 하는 join 을 모두 막음.
            if _rel_path.is_absolute() or _rel_path.root or ".." in _rel_path.parts:
                notes.append(
                    f"  [!] custom 워크플로 경로 {rel!r} 가 절대경로이거나 상위 디렉터리로 "
                    "이동해 제외 — 저장소 내부 상대경로만 허용됩니다."
                )
                continue
            # Path 조인은 선행 './' 를 자연히 정규화하므로 lstrip 을 쓰지 않음 — lstrip은
            # 문자 집합을 벗겨내므로 "./.github/..." 에서 ".github" 의 선행 '.' 까지 삭제해
            # "github/..." 를 만드는 버그가 있음(존재 검사가 엉뚱한 경로를 보게 됨).
            if not (host / rel).is_file():
                notes.append(
                    f"  [!] custom 워크플로 {rel} 가 없어 제외 — /harness-deployments 로 "
                    "먼저 저작하세요."
                )
                continue
            # `uses:` 에 로컬 재사용 워크플로를 쓰려면 GitHub Actions 가 './' 프리픽스를
            # 강제함 — target 처럼 정규화된 값을 item 에 저장함(raw 원문 금지).
            overrides["workflow"] = rel if rel.startswith("./") else f"./{rel}"
            # custom 의 permissions 값은 검증되지 않은 채로 오면 YAML 스칼라(불리언 등)가
            # 그대로 새어나갈 수 있음(예: `contents: yes` → 따옴표 없는 `contents: true`).
            # str()·strip()·casefold() 로 정규화 후 read/write/none 세 값만 허용하고, 벗어나면
            # 드롭 + [!] 로 키를 짚어 보고함(재파싱 게이트는 uses: 만 보므로 여기서 막아야 함).
            declared_perms = raw.get("permissions")
            if isinstance(declared_perms, dict):
                clean_perms: dict[str, str] = {}
                for perm_key, perm_val in declared_perms.items():
                    norm_val = str(perm_val).strip().casefold()
                    if norm_val in _PERM_RANK:
                        clean_perms[str(perm_key)] = norm_val
                    else:
                        notes.append(
                            f"  [!] deploy.targets 항목({raw.get('name')!r}) target=custom 의 "
                            f"permissions.{perm_key} 값 {perm_val!r} 은(는) 알 수 없어 제외"
                            "(read/write/none 만 허용)."
                        )
                overrides["permissions"] = clean_perms
        elif target not in DEPLOY_TEMPLATE_BY_TARGET:
            known = ", ".join([*DEPLOY_TEMPLATE_BY_TARGET, "custom"])
            notes.append(f"  [!] 알 수 없는 deploy target {target!r} 제외 (알려진 값: {known})")
            continue
        missing = [
            k for k in DEPLOY_REQUIRED_KEYS.get(target, ()) if not str(raw.get(k) or "").strip()
        ]
        if missing:
            notes.append(
                f"  [!] deploy.targets 항목({raw.get('name')!r}) target={target} 에 "
                f"필수 키 {', '.join(missing)} 가 없어 제외"
            )
            continue
        # pypi 는 auth 기본값이 token(DEPLOY_DEFAULT_AUTH — 재사용 워크플로에서
        # trusted publishing 미지원). 그런데도 config 가 **명시적으로** auth: oidc 를
        # 선언했다면(부재·token 은 해당 없음) 타깃을 드롭하지 않고(업스트림 수정을 앞서
        # 추적 중일 수 있으므로) [!] 로 오늘 기준 동작하지 않음을 경고함.
        if target == "pypi" and str(raw.get("auth") or "").strip().casefold() == "oidc":
            notes.append(
                f"  [!] deploy.targets 항목({raw.get('name')!r}) target=pypi 의 auth: oidc 는 "
                "재사용 워크플로에서 PyPI trusted publishing 이 동작하지 않습니다"
                "(pypa/gh-action-pypi-publish README — 미해결, pypa/warehouse#11096). "
                "auth: token 을 권장합니다."
            )
        overrides["target"] = target
        overrides["name"] = str(raw.get("name") or "").strip() or f"job-{len(items) + 1}"
        # resolve 는 오케스트레이터의 태그 해석 job 이 이미 쓰는 예약 id — 자동 채움
        # 이름(job-1, job-2…)은 이 값이 될 수 없지만, config 가 명시적으로
        # `name: resolve`(공백 포함)를 줄 수 있으므로 auto-fill **뒤에** 정규화된 값으로
        # 검사함. 대소문자 구분(DEPLOY_RESOLVE_JOB 주석 참고) — `RESOLVE` 는 충돌하지 않음.
        if overrides["name"] == DEPLOY_RESOLVE_JOB:
            notes.append(
                f"  [!] deploy.targets 항목(target={target})의 name 이 예약어"
                f" {DEPLOY_RESOLVE_JOB!r} 이어서 제외 — 오케스트레이터의 태그 해석 job 이"
                " 이미 이 id 를 씁니다. 다른 이름으로 바꾸세요."
            )
            continue
        item = dict(raw)
        item.update(overrides)
        items.append(item)
    dupes = sorted(n for n, cnt in Counter(i["name"] for i in items).items() if cnt > 1)
    if dupes:
        notes.append(
            f"  [!] deploy.targets 의 name 이 중복됨({', '.join(dupes)}) — 드롭하지 않지만 "
            "GitHub Actions UI 에 같은 라벨의 job 이 여럿 표시됩니다."
        )
    return items, notes


def _deploy_permissions(item: dict) -> dict:
    """(target, auth) → caller job 의 최소 권한. custom 은 config 가 선언함.

    체인에서 권한은 감소만 가능하므로(재사용 워크플로), 컴포넌트가 아니라 호출 job 이
    권한의 단일 출처.
    """
    target = item.get("target")
    perms = {"contents": "read"}
    if target == "custom":
        declared = item.get("permissions")
        if isinstance(declared, dict):
            perms.update({str(k): str(v) for k, v in declared.items()})
        return perms
    auth = str(item.get("auth") or "").strip().casefold()
    if not auth:
        auth = DEPLOY_DEFAULT_AUTH.get(target, "oidc")  # 타깃별 기본값(DEPLOY_DEFAULT_AUTH)
    if target in DEPLOY_OIDC_TARGETS and auth == "oidc":
        perms["id-token"] = "write"
    if target == "ghcr":
        perms["packages"] = "write"
    return perms


def _caller_with(item: dict) -> dict:
    """caller job 의 `with:` 를 만듦. **빈 값을 가진 키는 넣지 않음.**

    GitHub Actions 는 `with:` 키가 부재할 때만 컴포넌트 input 의 `default:` 를 채움.
    빈 문자열을 명시하면 default 가 억제됨. ghcr 의 context/dockerfile 은 required 라
    여기서 기본값을 계산해 채움(빈 `file:` 이 build-push-action 의 기본값을 억제하는 것 방지).

    전제조건: `_deploy_targets` 가 반환한 item 에 대해서만 호출함 — `DEPLOY_REQUIRED_KEYS`
    (예: ghcr 의 `image`)가 이미 검증돼 있다고 가정하며, 그렇지 않은 item(예: `image` 없는
    ghcr 항목)을 넘기면 `KeyError` 로 죽음(의도된 동작 — 빈 값을 조용히 허용하지 않음).
    """
    target = item["target"]
    with_: dict[str, str] = {"tag": DEPLOY_TAG_EXPR}
    if target == "custom":
        extra = item.get("with")
        if isinstance(extra, dict):
            with_.update({str(k): str(v) for k, v in extra.items()})
        return with_
    if target == "ghcr":
        ctx = str(item.get("context") or ".").strip() or "."
        dockerfile = str(item.get("dockerfile") or "").strip()
        if not dockerfile:
            dockerfile = "Dockerfile" if ctx == "." else f"{ctx.rstrip('/')}/Dockerfile"
        with_["image"] = str(item["image"]).strip()
        with_["context"] = ctx
        with_["dockerfile"] = dockerfile
        return with_
    for key in DEPLOY_WITH_KEYS[target]:
        val = str(item.get(key) or "").strip()
        if key == "auth":
            # _deploy_permissions 와 동일하게 casefold — 두 함수는 같은 파생 상태를 보는
            # 일관된 뷰여야 함("OIDC" 가 with: 에 원문 그대로 새는 것을 방지).
            val = val.casefold()
        if val:
            with_[key] = val
    if target in DEPLOY_OIDC_TARGETS:
        # 타깃별 기본값(DEPLOY_DEFAULT_AUTH) — _deploy_permissions 와 같은 SSOT 를 봐야
        # with: 의 기본 auth 와 부여된 id-token 권한이 어긋나지 않음.
        with_.setdefault("auth", DEPLOY_DEFAULT_AUTH.get(target, "oidc"))
    return with_


class _BlockStr(str):
    """literal block scalar(`|`)로 덤프되는 str — 생성된 워크플로의 `run:` 가독성."""


def _represent_block(dumper, data):  # pragma: no cover - 등록 콜백
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


# resolve job 의 태그 해석 스크립트.
#  - 체크아웃 게이트는 `github.event_name == 'workflow_dispatch'`(inputs.tag == '' 아님).
#    호출된 재사용 워크플로의 github 컨텍스트는 호출자의 것이라, release 가 push 로 돌면
#    체크아웃을 건너뜀. 호출자가 실수로 빈 tag 를 넘기면 여기서 시끄럽게 죽음
#    (inputs.tag == '' 게이트였다면 git describe 가 최신 태그를 집어 조용히 오배포함).
#  - `gh release view` 가 아니라 `git describe` 를 씀 — 전자는 최신 "정식" 릴리스를
#    돌려줘 stage 에서 rc 를 재배포하려 하면 main 의 정식 태그를 집음.
_DEPLOY_RESOLVE_RUN = (
    'TAG="$IN"\n'
    'if [ -z "$TAG" ]; then TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"; fi\n'
    'if [ -z "$TAG" ]; then\n'
    '  echo "::error::배포할 태그를 결정할 수 없습니다'
    ' (tag 입력이 비었고 도달 가능한 태그도 없습니다)"\n'
    "  exit 1\n"
    "fi\n"
    'echo "tag=$TAG" >> "$GITHUB_OUTPUT"\n'
)


def _deploy_needs(items: list[dict], order: list | None) -> dict:
    """order 를 needs 체인으로. 모든 job 은 언제나 resolve 를 needs 함.

    order 가 list 가 아니면(정수·bool·문자열 등 스칼라) 없는 것으로 취급함 — 문자열은
    글자 단위로 순회 가능해 조용히 잘못된 needs 를 만들 수 있으므로 함께 막음(FAIL-OPEN).
    중복 항목은 첫 등장만 남기고 제거해 자기참조·순환 needs(Actions 가 로드 자체를
    거부)를 방지함.
    """
    names = [i["name"] for i in items]
    chain = {n: [DEPLOY_RESOLVE_JOB] for n in names}
    if not isinstance(order, list):
        order = []
    seq: list[str] = []
    seen: set[str] = set()
    for o in order:
        s = str(o)
        if s in names and s not in seen:
            seq.append(s)
            seen.add(s)
    for prev, cur in zip(seq, seq[1:]):
        chain[cur].append(prev)
    return chain


def _orchestrator_doc(items: list[dict], order: list | None) -> dict:
    """deploy.yml 문서를 만듦(정적 템플릿 없음 — job 목록이 config 마다 다름)."""
    needs = _deploy_needs(items, order)
    jobs: dict = {
        DEPLOY_RESOLVE_JOB: {
            "runs-on": "ubuntu-latest",
            "timeout-minutes": DEPLOY_RESOLVE_TIMEOUT,
            "permissions": {"contents": "read"},
            "outputs": {"tag": "${{ steps.resolved.outputs.tag }}"},
            "steps": [
                {
                    "if": "github.event_name == 'workflow_dispatch'",
                    "uses": "actions/checkout@v7",
                    "with": {"fetch-depth": 0},
                },
                {
                    "id": "resolved",
                    "env": {"IN": "${{ inputs.tag }}"},
                    "run": _BlockStr(_DEPLOY_RESOLVE_RUN),
                },
            ],
        }
    }
    for item in items:
        name = item["name"]
        target = item["target"]
        uses = (
            str(item["workflow"])
            if target == "custom"
            else f"./.github/workflows/deploy-{target}.yml"
        )
        jobs[name] = {
            "needs": needs[name],
            "if": f"inputs.target == 'all' || inputs.target == '{name}'",
            "permissions": _deploy_permissions(item),
            "uses": uses,
            "with": _caller_with(item),
            "secrets": "inherit",
        }
    tag_desc = "배포할 git 태그(verbatim). 비우면 dispatch 시 최신 태그를 해석한다."
    target_desc = "배포할 타깃 이름, 또는 all"
    return {
        "name": "deploy",
        "on": {
            # 두 블록은 입력을 공유하지 않음. target 을 한쪽에만 선언하면 다른 경로에서
            # inputs.target 이 빈 값이 되어 모든 배포 job 이 조용히 스킵됨.
            "workflow_call": {
                "inputs": {
                    "tag": {"description": tag_desc, "required": True, "type": "string"},
                    "target": {
                        "description": target_desc,
                        "required": False,
                        "default": "all",
                        "type": "string",
                    },
                }
            },
            "workflow_dispatch": {
                "inputs": {
                    "tag": {
                        "description": tag_desc,
                        "required": False,
                        "default": "",
                        "type": "string",
                    },
                    "target": {
                        "description": target_desc,
                        "required": False,
                        "default": "all",
                        "type": "string",
                    },
                }
            },
        },
        "concurrency": {"group": "deploy-${{ inputs.tag }}", "cancel-in-progress": False},
        "jobs": jobs,
    }


# 오케스트레이터 첫 줄 — release.yml 배선이 deploy.yml 을 이 스크립트의 생성본으로 알아보는 표지.
ORCHESTRATOR_HEADER = (
    "# 배포 오케스트레이터 — /vdev-init 이 vdev-config.deploy 로 **생성**한다(직접 수정 금지;"
)


def _orchestrator_is_ours(path: Path) -> bool:
    """`path` 가 없거나 이 스크립트가 만든 deploy.yml 인가. 바이트로 비교 — UTF-8 이 아닌 파일은
    호스트의 것이고, 편집기가 붙인 BOM 은 생성본을 생성본으로 남김."""
    if not path.is_file():
        return True
    try:
        head = path.read_bytes()
    except OSError:
        return False
    return head.lstrip(b"\xef\xbb\xbf").startswith(ORCHESTRATOR_HEADER.encode("utf-8"))


def render_deploy_workflows(host: Path, plugin: Path) -> list[str]:
    """deploy 설정으로 컴포넌트를 복사하고 오케스트레이터 deploy.yml 을 생성함.

    컴포넌트는 치환 없는 **정적 복사**(파라미터는 caller job 의 with: 로 전달). 오케스트레이터
    만 생성됨(job 목록이 config 마다 다르므로 정적 템플릿이 없음).
    멱등·비파괴: 대상이 이미 있으면 보고만 함. FAIL-OPEN.
    """
    import yaml

    dp = load_deploy_config(host)
    if dp is None:
        return ["  [=] deploy 미설정 — 배포 워크플로 skip"]
    if not dp.get("enable"):
        return ["  [=] deploy.enable=false — 배포 워크플로 미설치"]
    targets = dp.get("targets")
    if not isinstance(targets, list) or not targets:
        return ["  [!] deploy.targets 가 비어 있어 배포 워크플로 미설치 (targets 를 채우고 재실행)"]

    items, out = _deploy_targets(targets, host)
    if not items:
        out.append("  [!] 실행 가능한 deploy.targets 가 없어 배포 워크플로 미설치")
        return out

    for target in sorted({i["target"] for i in items} - {"custom"}):
        src = plugin / DEPLOY_TEMPLATE_BY_TARGET[target]
        dest = host / ".github" / "workflows" / f"deploy-{target}.yml"
        # subs={} → 순수 복사. 컴포넌트에는 치환 토큰이 없음(파라미터는 caller 의 with:).
        out.extend(_render_one(host, src, dest, {}, label="deploy 컴포넌트"))

    dest = host / WORKFLOW_DEPLOY_DEST
    if dest.is_file():
        out.append("  [i] .github/workflows/deploy.yml 이미 있어 자동 병합 안 함(커스텀 보존).")
        out.append("  [i] 갱신하려면 기존 파일을 지우고 /vdev-init 을 재실행하세요.")
        return out

    order = dp.get("order")
    if order is not None and not isinstance(order, list):
        out.append(
            "  [!] deploy.order 가 리스트가 아니어서 무시합니다"
            "(순서 미적용, 모든 job 이 resolve 만 needs)"
        )

    dumper = yaml.SafeDumper
    dumper.add_representer(_BlockStr, _represent_block)
    header = (
        ORCHESTRATOR_HEADER + "\n"
        "# 수정하려면 config 를 고치고 이 파일을 지운 뒤 /vdev-init 재실행).\n"
        "# release.yml 이 workflow_call 로 호출하고, 수동 재배포는 workflow_dispatch 로 한다.\n"
        "# uses: 호출 job 에는 timeout-minutes 를 달 수 없다 — 타임아웃은 각 컴포넌트 안에 있다.\n"
    )
    try:
        body = yaml.dump(
            _orchestrator_doc(items, order),
            Dumper=dumper,
            sort_keys=False,
            allow_unicode=True,
            width=10**6,
        )
        _host_target(host, dest).parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(header + body, encoding="utf-8")
    except (OSError, yaml.YAMLError) as exc:
        out.append(f"  [!] deploy.yml 생성 실패(수동 확인): {exc}")
        return out
    out.append(f"  [+] .github/workflows/deploy.yml 생성 (deploy 렌더링, job {len(items)}개)")
    return out


def _deploy_permission_union(items: list[dict]) -> dict:
    """구성된 전 타깃 권한의 합집합. 체인에서 권한은 감소만 가능하므로 최상위가 상한을 줌.

    값은 `_PERM_RANK`(none < read < write)로 랭크해 **최댓값만** 남김 — 나중 타깃이
    이전 값(또는 `contents: read` 시드)을 낮추면 안 됨. 예: custom 타깃이
    `permissions: {contents: none}` 을 선언해도 시드 `contents: read` 가 살아 있어야
    함(spec 은 `contents: read` 가 항상 있음을 보장). write 만 dominant 로 보는 랭크는
    "later < earlier" 케이스를 놓쳐 read 시드를 none 으로 덮어씀.
    """
    union = {"contents": "read"}
    for item in items:
        for key, val in _deploy_permissions(item).items():
            if _PERM_RANK.get(val, 1) > _PERM_RANK.get(union.get(key, ""), -1):
                union[key] = val
    return union


def _deploy_wire_block(job_id: str, perms: dict) -> str:
    """release.yml 에 넣을 마커 블록(2칸 들여쓰기)."""
    lines = [
        DEPLOY_WIRE_BEGIN + " — /vdev-init 이 vdev-config.deploy 로 생성. 직접 수정 금지.",
        "  deploy:",
        f"    needs: [{job_id}]",
        f"    if: ${{{{ needs.{job_id}.outputs.tag != '' }}}}",
        "    # 전 타깃 권한의 합집합 — 재사용 워크플로 체인에서 권한은 감소만 가능하다.",
        "    permissions:",
    ]
    lines.extend(f"      {k}: {v}" for k, v in perms.items())
    lines.extend(
        [
            "    uses: ./.github/workflows/deploy.yml",
            "    with:",
            f"      tag: ${{{{ needs.{job_id}.outputs.tag }}}}",
            "    secrets: inherit",
            DEPLOY_WIRE_END,
        ]
    )
    return "\n".join(lines) + "\n"


def _strip_wire_block(text: str) -> tuple[str, bool]:
    """마커 블록을 제거한 텍스트를 반환(없으면 원본 그대로).

    반환: (제거된 텍스트, ok). `BEGIN` 은 있는데 매칭되는 `END` 가 끝까지 안 나오면
    (병합 충돌·수기 편집으로 마커가 손상된 경우) **원본을 그대로** 돌려주고 ok=False —
    EOF 까지 먹어치우는 truncation 을 막음. 손상 여부는 호출부가 ok 로 판단해 아무것도
    쓰지 않고 거부해야 함(마커 뒤에 소비자가 직접 추가한 job 이 있으면 자칫 그것까지
    조용히 삭제될 수 있음).
    """
    lines = text.splitlines(keepends=True)
    out, skipping = [], False
    for line in lines:
        if line.startswith(DEPLOY_WIRE_BEGIN):
            skipping = True
            continue
        if skipping:
            if line.rstrip("\n") == DEPLOY_WIRE_END:
                skipping = False
            continue
        out.append(line)
    if skipping:
        return text, False  # BEGIN 은 찾았지만 END 를 못 찾음 — 마커 손상, truncate 금지
    return "".join(out), True


def wire_release_deploy(host: Path) -> list[str]:
    """release.yml 에 deploy 호출 job 을 마커 블록으로 멱등 upsert 함.

    모델이 하는 YAML 수술은 blast radius 가 가장 크고(오삽입 시 릴리스 전체 정지) 유일하게
    테스트가 없는 쓰기. 그래서 스크립트가 함 — register_gate/append_gitignore 와 같은
    부류의 멱등 패치. 어느 단계에서 거부해도 원본을 건드리지 않음. FAIL-OPEN.
    """
    import yaml

    wf = host / RELEASE_WORKFLOW_DEST
    dp = load_deploy_config(host)
    items: list[dict] = []
    if dp and dp.get("enable") and isinstance(dp.get("targets"), list):
        items, _ = _deploy_targets(dp["targets"], host)

    if not wf.is_file():
        return ["  [=] release.yml 없음 — deploy 는 workflow_dispatch 수동 전용"]

    try:
        text, eol = _read_host_text(host, wf)
        doc = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError, UnicodeError) as exc:
        # UnicodeError 도 함께 잡음 — 비 UTF-8 바이트가 섞인 release.yml 하나 때문에
        # 셋업 전체가 죽으면 안 됨(OSError 만으론 UnicodeDecodeError 를 못 잡음).
        return [f"  [!] release.yml 읽기/파싱 실패(배선 skip): {exc}"]

    # 두 호출부(제거 경로·재배선 경로)가 모두 쓰는 stripped 텍스트를 여기서 한 번만
    # 계산함 — BEGIN 은 있는데 END 가 없는 손상된 마커는 ok=False 로 신호되고, 그 경우
    # 아무것도 쓰지 않고 즉시 거부함(제거 경로든 재배선 경로든 truncation 을 막아야 함).
    stripped_text, marker_ok = _strip_wire_block(text)
    if not marker_ok:
        return [
            "  [!] release.yml 의 vway-kit:deploy 마커 블록이 손상되어(BEGIN 은 있는데 END 가"
            " 없음) 배선/제거를 거부합니다 — 원본 유지.",
            "      마커 블록을 수동으로 복구하거나 통째로 제거한 뒤 /vdev-init 을 다시"
            " 실행하세요(자동 truncate 하지 않습니다).",
        ]

    if not items:
        if stripped_text == text:
            return ["  [=] deploy 미구성 — release.yml 배선 없음"]
        try:
            _write_host_text(wf, stripped_text, eol)
        except (OSError, UnicodeError) as exc:
            return [f"  [!] release.yml 배선 제거 실패: {exc}"]
        return ["  [-] release.yml 의 deploy 배선 제거 (deploy 미구성)"]

    if not _orchestrator_is_ours(host / WORKFLOW_DEPLOY_DEST):
        # 호출 job 은 재사용 워크플로에 `tag` 를 넘김 — 부르는 파일이 그 입력을 안 받으면 GitHub 이
        # release.yml 을 통째로 거부함.
        return [
            "  [!] release.yml deploy 배선 보류 — deploy.yml 이 생성본이 아님"
            " (workflow_call 의 tag 입력을 확인한 뒤 직접 배선하세요)"
        ]

    # doc 이 dict 가 아닐 수 있음(예: release.yml 이 문자열/리스트 하나뿐인 YAML) —
    # _load_yaml_safe 와 동일한 isinstance 방어(doc.get 자체가 AttributeError 로 죽지 않게).
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return ["  [!] release.yml 에 jobs 가 없어 배선 skip"]
    release_ids = [j for j in jobs if j != "deploy"]
    if len(release_ids) != 1:
        return [
            f"  [!] release.yml 의 job 이 여러 개({', '.join(sorted(release_ids))}) — "
            "어느 것이 릴리스 job 인지 추측하지 않습니다. deploy 배선을 수동으로 추가하세요."
        ]
    job_id = release_ids[0]
    job_val = jobs[job_id]
    outputs = job_val.get("outputs") if isinstance(job_val, dict) else None
    if not (isinstance(outputs, dict) and outputs.get("tag")):
        return [
            f"  [!] release.yml 의 {job_id} job 에 outputs.tag 가 없어 배선 거부(구버전 템플릿).",
            "      갱신: 커스텀이 없으면 .github/workflows/release.yml 을 지우고 /vdev-init"
            " 재실행,",
            "            커스텀이 있으면 pretag/released 두 스텝과 outputs.tag 를 수동 추가하세요.",
        ]

    if list(doc)[-1] != "jobs":
        return ["  [!] release.yml 의 jobs: 가 마지막 최상위 키가 아니어서 배선 거부(수동 추가)."]

    base = stripped_text
    if not base.endswith("\n"):
        base += "\n"
    new_text = base + _deploy_wire_block(job_id, _deploy_permission_union(items))

    try:
        check = yaml.safe_load(new_text) or {}
        check_jobs = check.get("jobs") if isinstance(check, dict) else None
        check_deploy = check_jobs.get("deploy") if isinstance(check_jobs, dict) else None
        if not isinstance(check_deploy, dict) or "uses" not in check_deploy:
            raise yaml.YAMLError("deploy job 이 만들어지지 않았습니다")
    except yaml.YAMLError as exc:
        return [
            f"  [!] 배선 결과가 유효 YAML 이 아니어서 원본 유지: {exc}",
            "      흔한 원인: release.yml 이 `jobs:` 뒤에 문서 종료 마커 `...` 로 끝나면"
            " 블록 삽입 후 두 번째 YAML 문서가 되어 파싱이 실패합니다 — 있다면 제거하세요.",
        ]

    try:
        _write_host_text(wf, new_text, eol)
    except (OSError, UnicodeError) as exc:
        return [f"  [!] release.yml 배선 쓰기 실패(원본 유지): {exc}"]
    verb = "갱신" if DEPLOY_WIRE_BEGIN in text else "추가"
    return [f"  [+] release.yml 에 deploy 호출 job 배선 {verb} (needs: {job_id})"]


# stale_publish 니들 — run/uses/env 세 축으로 나눠 파싱된 step·job·workflow 만 스캔함.
# 손으로 쓴 release 템플릿의 헤더 주석은 "발행은 deploy 로 이전됐다" 처럼 도구명을 자유롭게
# 설명할 수 있어야 하므로(rule: 주석은 금지어를 설명에 쓸 자유가 있음) raw text 검색은
# 오탐 — 파싱된 구조만 봄. 이 상수들은 **이 스크립트가 SSOT**:
# tests/test_workflow_templates.py::test_release_templates_have_no_build_or_publish 가
# 그대로 import 해서 씀(rule-dry-constants — 니들셋이 두 곳에 따로 있으면 반드시
# 드리프트함, Important finding 2). run 은 부분일치(in), uses/env 키는 접두사
# (startswith) 로 매칭함.
STALE_PUBLISH_RUN_NEEDLES = (
    "mvn",
    "gradlew",
    "dotnet",
    "sbt ci-release",
    "cargo publish",
    "CARGO_REGISTRY_TOKEN",
    "PGP_SECRET",
    "PGP_PASSPHRASE",
    "SONATYPE_",
)
STALE_PUBLISH_USES_PREFIXES = ("actions/setup-dotnet", "sbt/setup-sbt")
STALE_PUBLISH_ENV_NEEDLES = (
    "CARGO_REGISTRY_TOKEN",
    "PGP_SECRET",
    "PGP_PASSPHRASE",
    "SONATYPE_USERNAME",
    "SONATYPE_PASSWORD",
)


def _release_jobs(doc: dict) -> dict:
    """release.yml 파싱 doc 에서 `jobs:` dict 를 반환함(비정상 구조는 빈 dict).

    아래 스캔 함수들의 공통 진입점 — `jobs` 가 dict 가 아니면(오타로 정수 등이 들어간
    경우) 무엇도 순회하지 않고 조용히 빈 결과로 수렴함(Critical finding 1).
    """
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def _release_workflow_steps(doc: dict):
    """release.yml 파싱 doc 의 모든 job 의 모든 step(dict)을 훑음.

    job 이 dict 가 아니거나, `steps:` 가 list 가 아니거나(예: `steps: 5` 같은 오타), 개별
    step 이 dict 가 아니면 그 지점만 skip 함 — 한 곳의 비정상 구조가 전체 진단을
    죽이면 안 됨(FAIL-OPEN, Critical finding 1).
    """
    for job in _release_jobs(doc).values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict):
                yield step


def _env_needle_matches(env: object, needles: tuple[str, ...]) -> list[str]:
    """env: 블록의 키가 needles 중 하나로 시작하면 그 needle 들을 반환함.

    `env` 가 dict 가 아니면(예: `env: [a, b]` 같은 오타) 빈 리스트 — 스캔이 죽지 않음.
    """
    if not isinstance(env, dict):
        return []
    return [needle for needle in needles if any(str(k).startswith(needle) for k in env)]


def _stale_publish_needles(doc: dict) -> list[str]:
    """파싱된 release.yml 에서 잔존 빌드/레지스트리 발행 니들을 찾음(run/uses/env).

    env: 는 step 레벨뿐 아니라 job 레벨(`jobs.<id>.env`)·워크플로 최상위 레벨(`env:`)도
    스캔함(Important finding 3) — 손으로 만든 release.yml 이 step 이 아니라 job 이나
    워크플로 전체에 시크릿을 주입해도 잡아야 함.
    """
    found: list[str] = []

    def _add(needles: list[str]) -> None:
        for needle in needles:
            if needle not in found:
                found.append(needle)

    workflow_env = doc.get("env") if isinstance(doc, dict) else None
    _add(_env_needle_matches(workflow_env, STALE_PUBLISH_ENV_NEEDLES))
    for job in _release_jobs(doc).values():
        if isinstance(job, dict):
            _add(_env_needle_matches(job.get("env"), STALE_PUBLISH_ENV_NEEDLES))

    for step in _release_workflow_steps(doc):
        run = step.get("run")
        run = run if isinstance(run, str) else ""
        for needle in STALE_PUBLISH_RUN_NEEDLES:
            if needle not in found and needle in run:
                found.append(needle)
        uses = step.get("uses")
        uses = uses if isinstance(uses, str) else ""
        for prefix in STALE_PUBLISH_USES_PREFIXES:
            if prefix not in found and uses.startswith(prefix):
                found.append(prefix)
        _add(_env_needle_matches(step.get("env"), STALE_PUBLISH_ENV_NEEDLES))
    return found


def _release_has_tag_output(doc: dict) -> bool:
    """release.yml 의 (deploy 제외) 단일 job 이 outputs.tag 를 선언하는지 봄.

    `steps.released.outputs.tag` 문자열을 grep 하지 않음 — 사용자가 released 스텝
    이름을 바꿀 수 있음(task 요구사항). release job 후보를 **이름 기준**(deploy 제외)으로
    골라 `wire_release_deploy` 와 동일한 규칙을 씀 — 후보가 정확히 하나가 아니면(job
    없음·복수) 판단하지 않고 True(경보 없음)로 둠: 구조 자체가 모호한 경우까지 이
    진단이 알람을 울리면 오탐이 늘 뿐. 하지만 후보가 정확히 하나인데 그 값이 dict 가
    아니면(예: `release: "not-a-dict"`) `wire_release_deploy` 는 outputs 조차 읽을 수 없어
    배선을 거부함 — 이 경우에는 False 를 반환해 진단과 배선 판정을 일치시킴(Minor
    finding 5). 후보를 세는 것이 dict 검사보다 **먼저** — 순서가 뒤집히면 dict 아닌
    후보가 걸러져 후보 0 개로 오판하고 True 로 무보고함. 문서 자체가 파싱 불가능한
    경우(YAML 오류 등)는 이 함수까지 오지 않고
    `detect_legacy_release_workflow` 의 except 가 True 로 처리함(FAIL-OPEN).
    """
    jobs = _release_jobs(doc)
    release_ids = [name for name in jobs if name != "deploy"]
    if len(release_ids) != 1:
        return True
    job_val = jobs[release_ids[0]]
    if not isinstance(job_val, dict):
        return False
    outputs = job_val.get("outputs")
    return isinstance(outputs, dict) and bool(outputs.get("tag"))


def _takes_dispatch_level(doc: dict) -> bool:
    """`on.workflow_dispatch.inputs.level` 이 있는가 — YAML 1.1 이 맨몸 `on:` 을 불리언 True 로
    읽으므로 두 철자를 모두 물음."""
    on = doc.get("on", doc.get(True))
    if not isinstance(on, dict):
        return False
    dispatch = on.get("workflow_dispatch")
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    return isinstance(inputs, dict) and "level" in inputs


def detect_legacy_release_workflow(host: Path) -> dict:
    """렌더된 release 워크플로가 구 방식(GITHUB_TOKEN 기반)인지 + 배선 가능 여부를 진단함.

    릴리스 인증은 저장소 전용 PAT 시크릿 `RELEASE_TOKEN` 이고,
    stable 브랜치는 rc 를 finalize 함(강제-어긋난 rc 를 PSR 로 정식화 불가하므로).
    구 워크플로(`secrets.GITHUB_TOKEN` 사용, `RELEASE_TOKEN` 미참조)를 재실행 때마다
    표면화해 조용히 남지 않게 함(_render_one 은 기존 파일을 덮지 않으므로 필요).

    `stale_publish`/`has_tag_output` 은 `wire_release_deploy` 배선과 무관하게 release.yml
    의 상태를 사람에게 보이기 위한 것 — release 워크플로가 여전히 빌드/레지스트리
    발행을 하고 있으면(구 설계) deploy 로 이전이 안 됐다는 뜻이고, outputs.tag 가 없으면
    deploy 배선 자체가 거부됨. 둘 다 raw text 가 아니라 `yaml.safe_load` 로 파싱한 step
    구조만 봄(헤더 주석의 도구명 언급이 오탐되지 않게 — 위 니들 상수 주석 참고).

    반환 dict:
      - present     : bool        release.yml 이 존재하는가
      - legacy      : bool        GITHUB_TOKEN 을 쓰고 RELEASE_TOKEN 을 안 쓰는가(구 방식)
      - stale_publish: list[str]  아직 남아있는 빌드/레지스트리 발행 니들
      - has_tag_output: bool      outputs.tag 계약이 있는가(없으면 deploy 배선 불가)
      - stale_level_channel: bool 레벨을 `workflow_dispatch` `level` 로 받고 `Release-Level`
                                  트레일러는 안 읽는가(구 레벨 채널 — /release-commit 이 멈춤)
      - no_release_notes: bool    공통 release-notes 블록이 없는가(있으면 정식 릴리스 본문이
                                  fold 한 CHANGELOG 절로 바뀜 — 없으면 승인받은 절이 안 실림)
      - path        : str         대상 경로
    부재·읽기 실패·비 UTF-8·YAML 파싱 실패는 legacy=False·stale_publish=[]·
    has_tag_output=True·stale_level_channel=False·no_release_notes=False(FAIL-OPEN — 셋업/게이트를
    막지 않음; 판단 불가는 경보 사유가 아님).
    니들 스캔 헬퍼(`_stale_publish_needles`/`_release_has_tag_output`)는
    최대한 타입을 방어하지만, 예상 못한 조합에 대한 belt-and-braces 로 TypeError·
    AttributeError 도 같은 FAIL-OPEN 경로로 흡수함(Critical finding 1 — 헬퍼 호출을
    이 try 밖에 두면 오타 YAML 하나가 `/vdev-init` 전체를 죽임). 그 외 예외는 잡지
    않음.
    """
    import yaml

    wf = host / ".github" / "workflows" / "release.yml"
    if not wf.is_file():
        return {
            "present": False,
            "legacy": False,
            "stale_publish": [],
            "has_tag_output": True,
            "stale_level_channel": False,
            "no_release_notes": False,
            "path": str(wf),
        }
    try:
        text = wf.read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
        if not isinstance(doc, dict):
            doc = {}
        uses_ghtoken = "secrets.GITHUB_TOKEN" in text
        uses_release_token = "RELEASE_TOKEN" in text
        stale_publish = _stale_publish_needles(doc)
        has_tag_output = _release_has_tag_output(doc)
        stale_level_channel = _takes_dispatch_level(doc) and "Release-Level" not in text
        no_release_notes = "vway-release-notes" not in text
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, AttributeError):
        # UnicodeError 도 함께 잡음 — 비 UTF-8 바이트가 섞인 release.yml 이 FAIL-OPEN
        # 을 깨고 진단을 죽이지 않게(OSError 만으론 UnicodeDecodeError 를 못 잡음).
        # 파싱 실패(yaml.YAMLError)도 마찬가지 — legacy 조차 raw text 로 판단하지 않음
        # (파일이 깨져 있으면 아무것도 신뢰성 있게 알 수 없다는 뜻이므로 전부 무경보).
        # TypeError/AttributeError 는 니들 스캔 헬퍼의 방어를 뚫는 미지의 조합에 대한
        # 안전망(bare Exception 은 잡지 않음 — 진짜 버그를 숨기면 안 되므로).
        return {
            "present": True,
            "legacy": False,
            "stale_publish": [],
            "has_tag_output": True,
            "stale_level_channel": False,
            "no_release_notes": False,
            "path": str(wf),
        }

    return {
        "present": True,
        "legacy": uses_ghtoken and not uses_release_token,
        "stale_publish": stale_publish,
        "has_tag_output": has_tag_output,
        "stale_level_channel": stale_level_channel,
        "no_release_notes": no_release_notes,
        "path": str(wf),
    }


def report_legacy_release_workflow(host: Path) -> list[str]:
    """run_setup 보고용: release 워크플로 진단(구 방식·잔존 발행 스텝·태그 계약)을 사람이 읽을 줄로.

    - 파일 없음 → skip 한 줄.
    - 아무 문제 없음 → OK 한 줄(문구는 기존 테스트가 단언하므로 그대로 유지).
    - 하나 이상 문제 있음 → 누적해서 전부 보고(조기 return 하지 않음 — 신 방식이어도
      stale_publish/has_tag_output 진단은 계속 돎).
    - 구 방식 → [!] RELEASE_TOKEN 방식 갱신 + 시크릿 생성/주입 안내(GitHub 측 작업이라
      스크립트가 자동 처리 불가). 실제 재렌더(기존 파일 삭제 후 /vdev-init 재실행)는
      SKILL 이 사용자 동의로 수행함(무단 덮어쓰기 안 함 — 커스텀 보존).
    """
    diag = detect_legacy_release_workflow(host)
    if not diag["present"]:
        return ["  [=] release 워크플로 없음 (skip)"]

    out: list[str] = []
    if diag["legacy"]:
        out.extend(
            [
                "  [!] release 워크플로가 구 방식(GITHUB_TOKEN) — RELEASE_TOKEN 방식으로 갱신"
                " 필요.",
                "      재설계: 인증=RELEASE_TOKEN · stable=rc finalize · 프리플라이트/실패 안내.",
                "      갱신: .github/workflows/release.yml 을 삭제하고 /vdev-init 재실행(새 템플릿"
                " 렌더),",
                "            커스텀이 있으면 새 템플릿을 직접 병합하세요.",
                "      RELEASE_TOKEN 시크릿 생성/주입(둘 다 GitHub 웹에서):",
                "        [1] fine-grained PAT 생성 — Settings → Developer settings → Personal"
                " access",
                "            tokens → Fine-grained tokens → 이 저장소 선택 → Contents: Read and"
                " write",
                "        [2] 저장소 → Settings → Secrets and variables → Actions → New repository",
                "            secret → Name: RELEASE_TOKEN, Secret: 위 토큰",
            ]
        )
    if diag["stale_publish"]:
        out.extend(
            [
                "  [!] release 워크플로에 빌드/레지스트리 발행 스텝이 남아 있습니다"
                f"({', '.join(diag['stale_publish'])}).",
                "      릴리스는 버전·태그·GitHub Release 만 해야 하며, 발행은"
                " vdev-config.deploy 로 이전됐습니다.",
                # 순서가 중요 — release.yml 을 먼저 지우면(재렌더된 새 템플릿은 발행을
                # 안 함) deploy 가 아직 안 구성된 상태라 발행이 조용히 멈춤. 그래서
                # (1) vdev-config.deploy 설정 → (2) release.yml 삭제/재실행 순으로 안내함.
                "      순서: (1) 이 발행 스텝을 대체할 타깃으로 vdev-config.deploy 를 먼저"
                " 설정하고,",
                "      (2) 그 다음 release.yml 을 지우고 /vdev-init 재실행(커스텀 없을 때).",
                "      deploy 설정 전에 release.yml 부터 지우면 발행이 조용히 멈춥니다.",
            ]
        )
    if not diag["has_tag_output"]:
        out.extend(
            [
                "  [!] release 워크플로에 jobs.<release>.outputs.tag 가 없어 deploy 배선이"
                " 거부됩니다.",
                "      새 템플릿은 이 계약을 이미 갖고 있습니다 — 재렌더를 검토하세요.",
            ]
        )
    if diag["stale_level_channel"]:
        out.extend(
            [
                "  [!] release 워크플로가 레벨을 workflow_dispatch 로 받고 Release-Level 트레일러를"
                " 읽지 않습니다.",
                "      /release-commit 은 트레일러 채널만 다루므로 이 호스트의 staging 승격을"
                " 멈춥니다.",
                "      갱신: .github/workflows/release.yml 을 삭제하고 /vdev-init 재실행(새 템플릿"
                " 렌더),",
                "            커스텀이 있으면 새 템플릿을 직접 병합하세요.",
            ]
        )
    if diag["no_release_notes"]:
        out.extend(
            [
                "  [!] release 워크플로에 정식 릴리스 노트 스텝(vway-release-notes)이 없습니다.",
                "      /release-commit 이 사용자 승인으로 CHANGELOG 에 접어 넣은 정식 절을 아무도"
                " 싣지 않습니다.",
                "      갱신: .github/workflows/release.yml 을 삭제하고 /vdev-init 재실행(새 템플릿"
                " 렌더),",
                "            커스텀이 있으면 새 템플릿을 직접 병합하세요.",
            ]
        )
    if out:
        return out
    return ["  [=] release 워크플로 RELEASE_TOKEN 방식 (OK)"]


# ── 버전 감지 + 마이그레이션 레지스트리 ──────────────────────────────────────────

# 호스트 적용 버전 마커: gitignored 경로(.vway-kit/ 직속, config/ 밖 — config/ 는 git-tracked).
# GITIGNORE_LINES 에 추가해 setup 시 자동으로 gitignore 등록함.
VERSION_MARKER_PATH = f"{VWAY_DIR}/.applied-version"

# .gitignore 에 VERSION_MARKER_PATH 추가 — GITIGNORE_LINES 를 직접 수정하는 대신
# append_gitignore 가 GITIGNORE_LINES 를 읽으므로 리스트에 포함함.
# (아래 선언 시점에 GITIGNORE_LINES 가 이미 정의돼 있으므로 append 로 추가함.)
GITIGNORE_LINES.append(VERSION_MARKER_PATH)


def _vkey(s: str) -> tuple:
    """SemVer 문자열을 비교 가능한 정수 tuple 로 파싱함(stdlib-only, packaging 불필요)."""
    return tuple(int(x) for x in re.findall(r"\d+", s)) or (0,)


# 버전 구간별 마이그레이션. key=이 버전으로 올라올 때 실행. 지금은 비어 있음(골격).
MIGRATIONS: dict = {}


def plugin_version(plugin: Path) -> str:
    """플러그인 plugin.json 의 version 값을 반환(읽기 실패 시 '0.0.0')."""
    try:
        data = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        return str(data.get("version", "")) or "0.0.0"
    except Exception:
        return "0.0.0"


def applied_version(host: Path) -> str | None:
    """호스트에 기록된 적용 vway-kit 버전을 반환(마커 없으면 None)."""
    f = host / VERSION_MARKER_PATH
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def apply_migrations(host: Path, plugin: Path, registry: dict | None = None) -> list[str]:
    """호스트 적용 버전 → 현재 plugin 버전 사이의 마이그레이션을 순서대로 실행하고
    버전 마커를 갱신함. FAIL-OPEN(마이그레이션 예외는 경고만, 흐름 유지)."""
    reg = MIGRATIONS if registry is None else registry
    cur = plugin_version(plugin)
    prev = applied_version(host)
    out: list[str] = []
    if prev == cur:
        return [f"  [=] vway-kit {cur} 이미 적용됨 — 마이그레이션 없음"]
    # prev(제외) < v <= cur 구간의 등록 마이그레이션을 버전 오름차순 실행
    todo = sorted(
        (v for v in reg if (prev is None or _vkey(prev) < _vkey(v)) and _vkey(v) <= _vkey(cur)),
        key=_vkey,
    )
    for v in todo:
        try:
            reg[v](host, plugin)
            out.append(f"  [+] 마이그레이션 적용: {v}")
        except Exception as e:  # noqa: BLE001 — FAIL-OPEN
            out.append(f"  [!] 마이그레이션 {v} 실패(무시): {e}")
    marker = _host_target(host, host / VERSION_MARKER_PATH)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(cur + "\n", encoding="utf-8")
    out.append(f"  [i] 적용 버전 기록: {prev or '(없음)'} → {cur}")
    return out


def load_harnesses(host: Path) -> tuple[list[str], list[str], bool]:
    """이 호스트가 게이트를 심는 하네스 목록, 보고 줄, 그리고 그 목록을 믿어도 되는지.

    - Claude 는 언제나 첫째 — 이 플러그인은 먼저 Claude Code 플러그인이고, 키 부재는 Codex
      이전에 설치된 모든 호스트, 즉 바뀌지 않은 그 호스트.
    - 셋째 값 `reliable` 은 `harnesses:` 값 자체를 목록으로 못 읽었을 때만 False — 그때
      `names` 는 호스트의 진짜 설정이 아니라 짐작. 모르는·미지원 이름 하나는 건드리지 않음:
      나머지 목록은 여전히 진짜이고, 그 한 줄은 그 이름에 대한 사실일 뿐. 호출부가 `[!]` 를
      세어 되짚게 하면 무관한 `[!]` 가 "목록 자체를 모름" 으로 읽힘.
    """
    cfg = _load_yaml_safe(config_path(host))
    raw = cfg.get("harnesses")
    names = ["claude"]
    lines: list[str] = []
    reliable = True
    if raw is None:
        entries: list = []
    elif isinstance(raw, list):
        entries = raw
    else:
        # 모양이 틀린 값(맨 문자열·매핑)은 오타이지 키 부재가 아님 — 조용히 "하네스 없음" 으로
        # 읽으면 `harnesses: codex` 라고 쓴 호스트에게 claude 전용이 그가 고른 것처럼 말함.
        lines.append(
            "  [!] harnesses: 목록이어야 합니다(예: [claude, codex])"
            " — 무시하고 claude 만 사용합니다"
        )
        entries = []
        reliable = False
    for name in entries:
        if name == "claude" or name in names:
            continue
        if name in harness.SUPPORTED:
            names.append(name)
        elif name in harness.KNOWN:
            lines.append(f"  [=] harnesses: {name} 는 아직 지원하지 않습니다 (skip)")
        else:
            lines.append(f"  [!] harnesses: 알 수 없는 이름 '{name}' (skip)")
    return names, lines, reliable


def register_gates(host: Path, harnesses: list[str]) -> list[str]:
    """켜진 모든 하네스에 커밋 게이트를 등록.

    - Claude 는 settings.json 의 `register_gate` — claude 전용 호스트는 그 한 줄 그대로.
    - 나머지는 레지스트리(`harness.installer`)의 자기 훅 파일 등록 + 전할 읽기 전용 경고
      (Codex: 프로젝트가 trusted 인지, `/hooks` 승인이 아직 필요한지).
    """
    out = [register_gate(host)]
    for name in harnesses:
        if name == "claude":
            continue
        try:
            mod = harness.installer(name)
        except ImportError as exc:
            # 설치 모듈의 패키징 실패는 그 하네스 한 줄만 잃음 — Claude 등록 줄과 나머지 단계는
            # 그대로. 판정(`_gate_problems`)이 같은 해석을 다시 해 실패로 답함.
            out.append(
                f"  [!] {name} 게이트 설치 모듈을 불러오지 못했습니다({_why(exc)}) — 수동 확인 필요"
            )
            continue
        out.append(mod.register(host))
        if name == "codex":
            out.append(mod.register_session(host))
            out.extend(mod.trust_notes(host))
    return out


def codex_leftovers(host: Path, harnesses: list[str]) -> list[str]:
    """codex 를 `harnesses` 에서 뺀 호스트에 남은 Codex 게이트 — 보고만, 지우지 않음.

    목록만으로는 사용자가 Codex 게이트를 없애길 원하는지 알 수 없음 — 지우는 것은 uninstall.
    """
    if "codex" in harnesses:
        return []
    left = []
    try:
        # `hook_remains` 가 아니라 표식 낱말로 봄 — 그것은 못 읽는 파일에 "남았을 수 있음" 으로
        # 답하는데, claude 전용 호스트 자신의 깨진 hooks.json 은 여기서 보고할 것이 아님.
        hooks = (host / ".codex" / "hooks.json").read_text(encoding="utf-8")
        if all(word in hooks for word in harness.installer("codex").MARKER):
            left.append(".codex/hooks.json 게이트 훅")
        if harness.installer("codex").session_hooks_remain(host):
            left.append(".codex/hooks.json 세션 훅")
    except Exception:  # noqa: BLE001 — 안내 한 줄이지 단계를 잃을 이유가 아님
        pass
    if _codex_instructions_block(host) is True:
        left.append("AGENTS.md 지침 블록")
    if not left:
        return []
    # 훅 하나만 남은 경우의 문구는 지침 블록 배선 전과 같음.
    subject = "이" if left == [".codex/hooks.json 게이트 훅"] else " 이(가)"
    return [
        f"  [i] harnesses 에 codex 가 없지만 {' · '.join(left)}{subject} 남아 있습니다 — 지우려면"
        " /vdev-uninstall, 계속 쓰려면 harnesses 에 codex 를 다시 추가하세요"
    ]


# `harness/codex/instructions.py` 의 `_BEGIN_PREFIX` 를 다시 적음(둘은 테스트가 고정) — 블록이
# 있는지는 렌더러 모듈을 import 하지 않고 답해야 함: 그 import 가 실패하는 호스트에서도 제거
# 단계는 떠서 자기 `[!]` 를 찍어야 하므로.
CODEX_INSTRUCTIONS_BEGIN = "<!-- vway-kit:codex-instructions BEGIN"


def _codex_instructions_block(host: Path) -> bool | None:
    """루트 AGENTS.md 에 Codex 지침 블록의 BEGIN 줄이 있는가 — 물음 자체가 막히면 None.

    - 줄 머리의 접두로만 봄(렌더러 `_spans` 와 같은 기준) — 문장 속 인용은 블록이 아님.
    - claude 전용 호스트의 자기 AGENTS.md(블록 없음)는 False — 출력이 배선 전과 같음.
    """
    path = host / "AGENTS.md"
    try:
        if not path.is_file():
            return False
        text = path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None
    return any(line.startswith(CODEX_INSTRUCTIONS_BEGIN) for line in text.split("\n"))


def _codex_instructions():
    """Codex AGENTS.md 렌더러 — 단계가 돌 때 찾아 패키징 실패가 그 단계만 잃게 함."""
    try:
        from harness.codex import instructions as _mod
    except ImportError:
        from scripts.harness.codex import instructions as _mod
    return _mod


def render_codex_instructions(host: Path) -> list[str]:
    """setup `[Codex 지침 렌더]` 단계 — 렌더러 임포트 실패는 여기서만 잡음(`_step` 이 잡는 예외를
    넓히면 claude 전용 호스트의 PyYAML 부재 동작까지 바뀜)."""
    try:
        mod = _codex_instructions()
    except ImportError as exc:
        return [f"  [!] Codex 지침 렌더러를 불러오지 못했습니다({_why(exc)}) — 수동 확인 필요"]
    return mod.render(host)


def remove_codex_instructions(host: Path) -> list[str]:
    """uninstall `[Codex 지침 블록 제거]` 단계.

    - 임포트 실패 처리는 `render_codex_instructions` 와 같음.
    - 제거는 PyYAML 없이도 돎(원본을 파싱하지 않음).
    """
    try:
        mod = _codex_instructions()
    except ImportError as exc:
        return [f"  [!] Codex 지침 렌더러를 불러오지 못했습니다({_why(exc)}) — 수동 확인 필요"]
    return [mod.remove(host)]


def _gate_problems(host: Path, plugin: Path, harnesses=("claude",)) -> list[str]:
    """이 호스트에서 커밋 게이트가 돌지 않을 이유를, 실행이 남긴 것에서 되읽음.

    `register_gate` 가 찍은 줄에 물으면 질문이 스스로 답함: **나중** 단계에서 실패한
    쓰기도, 발화하지 않는 매처도, 통째로 꺼진 훅도 전부 그 줄은 아무 문제 없다고 말하고 —
    게이트가 이미 있고 발화하는데 등록이 거절된 경우는 문제가 있다고 말함.

    게이트가 돌리는 파일은 파일시스템에 묻되, 이름이 차 있는지가 아니라 이 스크립트가
    넣는 그것인지를 물음. 훅은 파일 하나를 지목하는 텍스트 한 줄이라, `[!]` 를 찍고
    지나간 복사 단계는 그러지 않으면 끝났다고 불릴 등록을 남김: `bash` 는 없는
    스크립트에 127 로 답하고, 정책의 부재는 모든 분류를 게이트가 fail-open 하는 내부
    오류로 바꾸며, 어느 쪽도 커밋을 막는 exit 2 가 아님.

    파일 집합은 `gate_files(harnesses)` — 켜진 하네스의 wrapper(Codex 의 gate.sh·gate.cmd)도
    그 훅이 직접 돌리는 게이트 스크립트라, 빠지거나 깨지면 같은 이유로 게이트가 없음.
    """
    problems = []
    missing = [
        Path(rel).name
        for rel, source in gate_files(harnesses)
        if not _installed(host, plugin, rel, source)
    ]
    if missing:
        problems.append(
            "커밋 게이트가 쓰는 파일이 호스트에 없거나 손상됐습니다("
            + ", ".join(missing)
            + ") — 훅이 등록되어 있어도 아무 커밋도 막지 못합니다."
            " 위 [!] 를 해결한 뒤 /vdev-init 를 다시 실행하세요."
        )
    problems.extend(_claude.problems(host))
    if "codex" in harnesses:
        hooks_missing = [
            Path(rel).name
            for rel in HARNESS_ROOT_FILES["codex"]
            if not _installed(host, plugin, f"{VWAY_DIR}/{rel}", rel)
        ]
        if hooks_missing:
            problems.append(
                "Codex 세션 훅이 실행하는 파일이 호스트에 없거나 손상됐습니다("
                + ", ".join(hooks_missing)
                + ") — 편집 후에도 게이트 증거가 무효화되지 않습니다."
                " 위 [!] 를 해결한 뒤 /vdev-init 를 다시 실행하세요."
            )
    if "codex" in harnesses:
        try:
            problems.extend(harness.installer("codex").problems(host))
        except Exception as exc:  # noqa: BLE001 — 판정은 반드시 닿아야 함, 확인 못 함은 문제
            problems.append(
                f"Codex 커밋 게이트를 확인하지 못했습니다({_why(exc)}) — /vdev-init 를 다시"
                " 실행하세요."
            )
    return problems


def _step(title: str, *produce: Callable[[], list[str]]) -> bool:
    """셋업의 한 단계를 찍고, 그것을 끝내지 못하게 하는 호스트에서도 살아남음.

    각 단계는 자기 문제를 `[!]` 줄로 보고하지만, 그것이 찾아간 문제만 그러함: 호스트가
    닫아 둔 `.claude` 는 보고가 쓰이기 전에 프로브에서 raise 하고, 끝의 판정 — 게이트가
    켜졌는지를 말하는 그 한 줄 — 에는 아예 닿지 못함. 끝냈는지는 호출부가 보고할 몫:
    끝내지 못한 단계 위에서 완료라는 낱말로 끝나는 실행은 같은 거짓말의 작은 판.

    한 제목 아래 생산자가 여럿인 단계가 있어서(`[gitignore]`·`[폐기 필드 점검]`) 생산자
    **하나씩** 돌리고 찍음. 결과를 이어 붙여 한 번에 찍으면 뒤에서 난 raise 가 앞 생산자가
    이미 만들어 둔 `[!]` 줄까지 함께 삼키는데, 그 줄들이 곧 사용자가 고쳐야 할 목록.
    """
    print(title)
    for one in produce:
        try:
            for line in one():
                print(line)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"  [!] 이 단계를 끝내지 못했습니다({_why(exc)}) — 수동 확인 필요")
            return False
    return True


def subdir_warning(host: Path) -> list[str]:
    """세션이 git 최상위 아래에서 시작됐으면 한 줄, 아니면 빈 목록.

    GitHub 은 워크플로를, pre-commit 은 자기 config 를 저장소 최상위에서만 읽음 — `host` 아래에
    쓴 사본은 어디서도 안 돎. 사본은 옮기지 않음: 렌더된 워크플로가 부르는
    `.claude/vway-kit/scripts` 는 최상위 기준 경로라 하위 디렉터리 호스트엔 거기에도 없음.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(host),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        top = Path(out.stdout.strip()).resolve() if out.returncode == 0 else None
        if top is None or top == Path(host).resolve():
            return []
    except Exception:  # noqa: BLE001 — 경고가 셋업을 멈추지 않음
        return []
    return [
        f"  [!] 세션이 git 최상위({top})가 아닌 하위 디렉터리에서 시작됨 — .github/workflows/ 와"
        " .pre-commit-config.yaml 은 GitHub·pre-commit 이 읽지 않는 위치에 생김. 저장소 최상위에서"
        " 세션을 열고 /vdev-init 을 다시 실행할 것"
    ]


def run_setup(host: Path, plugin: Path) -> bool:
    """모든 단계를 돌리고, 커밋 게이트가 등록됐는지를 답함.

    읽거나 쓰지 못한 settings.json 은 저마다 줄을 찍고 나머지 셋업을 계속 돌게 함 —
    옳음, 워크플로우도 .gitignore 도 어느 쪽이든 값어치가 있음. 그것은 동시에 게이트를
    끄는 그 한 단계가 마흔 줄 사이로 스크롤되어 지나간다는 뜻이라, 끝에서 다시 말하고
    종료 코드에도 실음.

    아예 끝내지 못한 단계도 같은 경우지 더 나쁜 경우가 아님: 줄을 찍고 실행은 계속됨,
    판정이야말로 호출자가 보러 온 것이므로.
    """
    try:
        names, cfg_lines, harnesses_readable = load_harnesses(host)
    except ImportError:
        # PyYAML 부재 — 이 줄에서 보고하지 않음: 배선 전과 같이 YAML 을 읽는 첫 단계가
        # 그 부재를 그대로 드러냄(claude 전용 호스트의 출력·종료 코드 보존).
        names, cfg_lines, harnesses_readable = ["claude"], [], False
    except Exception as exc:  # noqa: BLE001 — 닫힌 `.claude/` 도 판정까지는 닿아야 함
        names = ["claude"]
        cfg_lines = [f"  [!] harnesses 를 읽지 못했습니다({_why(exc)}) — claude 만 사용합니다"]
        harnesses_readable = False
    # `codex_leftovers` 는 "harnesses 에 codex 가 없음" 을 아는 사실처럼 보고함 — 목록을 못
    # 읽었으면(위 except·목록 아닌 값) `names == ["claude"]` 는 짐작이고 진짜 config 는 여전히
    # codex 를 적었을 수 있음. 그 호스트에 자기 게이트를 지우라고 하면 방향이 거꾸로.
    # claude 전용 호스트는 `cfg_lines` 가 비고 `register_gates` 가 한 줄이라 출력이 그대로.
    print(f"vdev-init 기계적 셋업 — host={host}")
    for line in subdir_warning(host):
        print(line)
    # 등록(게이트 command 보정)을 flat 스크립트 삭제(migrate)보다 먼저 함 — copy 가
    # 새 scripts/ 사본을 이미 만들었으므로, command 를 새 경로로 보정한 뒤 옛 flat 을
    # 지워야 중단되더라도 게이트가 삭제된 경로를 가리키는 창이 생기지 않음.
    # deploy.yml 을 먼저 만들어야 wire_release_deploy 의 uses: 가 실재하는 파일을 가리킴.
    finished = [
        _step("[복사]", lambda: copy_artifacts(plugin, host, names)),
        # 생산자 셋으로 나눔 — 이어 붙이면 뒤의 raise 가 앞이 만든 `[!]`·등록 줄까지 삼킴(`_step`).
        _step(
            "[커밋 게이트]",
            lambda: cfg_lines,
            lambda: register_gates(host, names),
            lambda: codex_leftovers(host, names) if harnesses_readable else [],
        ),
        _step("[룰 정리]", lambda: [remove_rules(host)]),
        _step("[마켓 자동 업데이트]", lambda: [register_marketplace(host)]),
        _step("[구버전 경로 이전]", lambda: migrate_legacy_paths(host)),
        _step("[템플릿]", lambda: sync_host_templates(host, plugin)),
        _step("[pre-commit 점검]", lambda: check_precommit(plugin, host)),
        _step(
            "[gitignore]",
            lambda: append_gitignore(host),
            lambda: untrack_vdev_evidence(host),
            lambda: unignore_shared(host),
            lambda: prune_stale_gitignore(host),
        ),
        _step("[계약 테스트 워크플로우]", lambda: render_workflow(host, plugin)),
        _step("[버저닝 워크플로우]", lambda: render_versioning_workflows(host, plugin)),
        _step("[유닛 테스트 워크플로우]", lambda: render_unit_test_workflow(host, plugin)),
        _step("[문체 검사 워크플로우]", lambda: render_doc_style_workflow(host, plugin)),
        _step("[E2E 워크플로우]", lambda: render_e2e_workflow(host, plugin)),
        _step("[배포 워크플로우]", lambda: render_deploy_workflows(host, plugin)),
        _step(
            "[Recoble MCP]",
            lambda: recoble_mcp_instructions(host),
            lambda: report_legacy_mcp_json(host),
            *(
                [lambda: codex_recoble_mcp_instructions(host)]
                if "codex" in names and recoble_servers(load_alm_config(host))[0]
                else []
            ),
        ),
        _step("[배포 배선]", lambda: wire_release_deploy(host)),
        _step("[릴리스 워크플로 마이그레이션]", lambda: report_legacy_release_workflow(host)),
        _step("[config 슬롯 점검]", lambda: report_missing_config_slots(host, plugin)),
        _step("[ALM 계층 점검]", lambda: report_alm_layers(host, plugin)),
        _step(
            "[폐기 필드 점검]",
            lambda: report_legacy_test_command(host),
            lambda: report_legacy_alm_config(host),
        ),
        _step("[checks 타이밍 점검]", lambda: report_check_timing(host)),
        _step("[자동 업데이트 인증]", lambda: detect_autoupdate_auth()),
        _step("[마이그레이션]", lambda: apply_migrations(host, plugin)),
    ]
    if "codex" in names:
        finished.append(_step("[Codex 지침 렌더]", lambda: render_codex_instructions(host)))
    problems = _gate_problems(host, plugin, names)
    if problems:
        for line in problems:
            print(line)
        return False
    if not all(finished):
        # 게이트는 켜졌고 그것이 이 답이 말하는 것 — 다만 끝내지 못한 단계가 다른
        # 무언가를 못 한 채로 남겼고, 완료라는 낱말만으로는 그것이 가려짐.
        print("기계적 셋업 완료 — 다만 끝내지 못한 단계가 있습니다(위 [!] 확인).")
        return True
    print("기계적 셋업 완료.")
    return True


def _unregister_codex_session(host: Path) -> str:
    """Codex 세션 훅 해제 한 줄 — 모듈 해석 실패의 처리는 `_unregister_codex` 와 같음."""
    try:
        mod = harness.installer("codex")
    except ImportError as exc:
        return f"  [!] Codex 게이트 설치 모듈을 불러오지 못했습니다({_why(exc)}) — 수동 확인 필요"
    return mod.unregister_session(host)


def _unregister_codex(host: Path) -> str:
    """Codex 게이트 해제 한 줄. 설치 모듈 해석 실패(ImportError)는 이 줄의 `[!]` 로만 — `_step`
    이 잡는 예외를 넓히면 claude 전용 호스트의 PyYAML 부재 동작까지 바뀜. 남았는지는 판정의
    `_codex_hook_status` 가 "unconfirmed" 로 답함."""
    try:
        mod = harness.installer("codex")
    except ImportError as exc:
        return f"  [!] Codex 게이트 설치 모듈을 불러오지 못했습니다({_why(exc)}) — 수동 확인 필요"
    return mod.unregister(host)


def _codex_hooks_present(host: Path) -> bool:
    """`.codex/hooks.json` 이 있거나, 있는지 알 수 없는가(물음 자체가 막히면 있는 쪽으로)."""
    try:
        return (host / ".codex" / "hooks.json").exists()
    except OSError:
        return True


def _codex_hook_status(host: Path) -> str:
    """`.codex/hooks.json` 의 Codex 게이트 훅이 어디 있는지.

    - "gone": 파일 없음, 또는 읽혔고 게이트 훅 없음.
    - "left": 읽혔고 게이트 훅이 남음.
    - "unconfirmed": 훅을 담았을 수 있는 파일에서 확인이 돌지 못함(설치 모듈 해석 실패 포함 —
      "확인 못 함" 은 "사라짐" 이 아님).
    - "foreign": 파싱되지 않거나 `PreToolUse` 목록이 아닌 모양인데 게이트 표식도 없음 — 호스트
      자신의 파일이고 vway-kit 이 쓴 적 없음.

    판정 시점에 설치 모듈을 찾음 — 임포트 시점이면 Codex 패키징 실패가 "훅 없음" 의 증거로
    읽힘. 다만 파일이 아예 없는 호스트는 등록한 적도 없으므로 "gone".
    """
    path = host / ".codex" / "hooks.json"
    try:
        if not path.exists():
            return "gone"
        mod = harness.installer("codex")
        data, _err = mod.load_json_object(path, ".codex/hooks.json")
        if data is not None:
            if not mod.hook_remains(host):
                return "gone"
            hooks = data.get("hooks", {})
            if isinstance(hooks, dict) and isinstance(hooks.get("PreToolUse", []), list):
                return "left"
        raw = path.read_bytes().decode("utf-8", "replace")
        return "unconfirmed" if all(word in raw for word in mod.MARKER) else "foreign"
    except Exception:  # noqa: BLE001 — 돌지 못한 확인은 "아니오" 가 아님(위)
        return "unconfirmed"


# uninstall 단계가 호스트에서 바꿀 수 있는 것 — 커밋 안내용. 파일은 내용, 디렉터리는 존재로 비교.
UNINSTALL_FILES = (
    ".claude/settings.json",
    ".codex/hooks.json",
    ".gitignore",
    "CLAUDE.md",
    "AGENTS.md",
)
UNINSTALL_DIRS = (VWAY_DIR, RULES_DEST)


def _bytes_or_none(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _uninstall_state(host: Path) -> dict[str, object]:
    state: dict[str, object] = {rel: _bytes_or_none(host / rel) for rel in UNINSTALL_FILES}
    state.update({f"{rel}/": (host / rel).is_dir() for rel in UNINSTALL_DIRS})
    return state


def run_uninstall(host: Path) -> bool:
    """모든 단계를 돌리고, 게이트 훅이 사라졌는지를 답함.

    쓰지 못한 settings.json 은 훅을 남기는데 같은 실행이 그 훅이 지목하는 스크립트를
    지움 — 그 호스트의 모든 Bash 명령이 그때부터 없는 파일을 돎. 그 위에
    `정리 완료.` 를 찍는 것은 셋업 쪽이 등록한 적 없는 게이트에 대해 했던 것과 같은
    거짓말. 끝내지 못한 단계도 다시 같은 경우: 줄을 찍고 실행은 계속됨,
    판정이야말로 호출자가 보러 온 것이므로."""
    print(f"vway-kit 정리(uninstall) — host={host}")
    before = _uninstall_state(host)
    finished = [
        _step("[커밋 게이트 해제]", lambda: [unregister_gate(host)]),
    ]
    # config 의 `harnesses` 와 무관 — 설치 뒤 codex 를 목록에서 뺀 호스트에도 훅 파일은 남고,
    # uninstall 은 "config 가 말하지 않으면 남김" 이 아니라 사라짐. 다만 `.codex/hooks.json` 이
    # 없으면 뗄 것도 없어 단계째 건너뜀 — claude 전용 호스트의 출력은 배선 전과 같음.
    # 설치 모듈은 단계 **안에서** 찾음 — Codex 패키징 실패가 그 한 단계만 잃게.
    if _codex_hooks_present(host):
        # 게이트보다 먼저 — 게이트 해제가 다른 훅이 없는 파일을 지우므로.
        finished.append(_step("[Codex 세션 훅 해제]", lambda: [_unregister_codex_session(host)]))
        finished.append(_step("[Codex 게이트 해제]", lambda: [_unregister_codex(host)]))
    finished += [
        _step(
            "[Recoble MCP]",
            lambda: report_recoble_mcp_servers(host),
            lambda: report_legacy_mcp_json(host),
            *([lambda: codex_recoble_mcp_report(host)] if _codex_present(host) else []),
        ),
        _step("[마켓 등록 해제]", lambda: [unregister_marketplace(host)]),
        _step("[gitignore 정리]", lambda: [remove_gitignore_lines(host)]),
        _step("[CLAUDE.md teams 블록 제거]", lambda: [remove_claude_md_block(host)]),
    ]
    # 게이트 단계와 같이 `harnesses` 와 무관 — 다만 우리 BEGIN 줄이 없는 AGENTS.md(또는 파일
    # 없음)면 뗄 것이 없어 단계째 건너뜀(claude 전용 호스트의 출력은 배선 전과 같음). 물음이
    # 막히면(None) 단계를 띄워 렌더러가 스스로 보고하게 함.
    if _codex_instructions_block(host) is not False:
        finished.append(_step("[Codex 지침 블록 제거]", lambda: remove_codex_instructions(host)))
    finished.append(_step("[vway-kit 디렉터리 삭제]", lambda: [remove_vway_dir(host)]))
    finished.append(_step("[룰 삭제]", lambda: [remove_rules(host)]))
    print("[남는 항목 — 수동 처리 안내]")
    print("  - .pre-commit-config.yaml 의 teams-notify-push 훅/정적분석 훅은 자동 제거하지")
    print("    않습니다(주석·팀 커스텀 보존). 필요 시 직접 제거하세요.")
    try:
        workflows = report_workflows(host)
    except Exception:  # noqa: BLE001 — 목록을 못 만들어도 판정은 잃지 않음
        workflows = ["  - .github/workflows/ 를 읽지 못했습니다 — 남은 워크플로를 직접 확인하세요."]
    for line in workflows:
        print(line)
    print("  - 설치했던 git 훅 비활성화:")
    print("      pre-commit uninstall --hook-type pre-commit --hook-type commit-msg \\")
    print("        --hook-type pre-push")
    after = _uninstall_state(host)
    changed = [rel for rel in before if before[rel] != after[rel]]
    if changed:
        print(f"  - 이 정리가 바꾼 것은 커밋해야 반영됩니다: {', '.join(changed)}")
    # 한 줄로 합치지 않고 따로 이름을 댐: settings.json 과 .codex/hooks.json 은 서로 다른 단계가
    # 못 지운 서로 다른 파일이고, Codex 훅만 남은 호스트를 이미 빈 settings.json 으로 보내면 안 됨.
    claude_left = _gate_hook_remains(host)
    codex_state = _codex_hook_status(host)
    if codex_state == "foreign":
        print(
            "  [i] .codex/hooks.json 을 해석하지 못했지만 vway-kit 게이트 표식이 없어"
            " 건드리지 않았습니다."
        )
    if claude_left or codex_state in ("left", "unconfirmed"):
        if claude_left:
            print(
                "커밋 게이트 훅이 settings.json 에 남았습니다 — 방금 삭제된 스크립트를"
                " 가리키므로 직접 지우세요."
            )
        if codex_state == "left":
            print(
                "Codex 커밋 게이트 훅이 .codex/hooks.json 에 남았습니다 — 방금 삭제된"
                " 스크립트를 가리키므로 직접 지우세요."
            )
        if codex_state == "unconfirmed":
            print(
                ".codex/hooks.json 을 해석하지 못해 Codex 커밋 게이트 훅이 지워졌는지 확인하지"
                " 못했습니다 — 남았다면 방금 삭제된 스크립트를 가리키므로 직접 확인하세요."
            )
        return False
    if not all(finished):
        # 훅은 사라졌고 그것이 이 답이 말하는 것 — 다만 끝내지 못한 단계가 무언가를
        # 남겼고, 완료라는 낱말만으로는 그것이 가려짐.
        print("정리 완료 — 다만 끝내지 못한 단계가 있습니다(위 [!] 확인).")
        return True
    print("정리 완료.")
    return True


def main() -> None:
    force_utf8_io()
    parser = argparse.ArgumentParser(description="vdev-init 기계적 셋업 / --uninstall 정리")
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="호스트에서 vway-kit 배선을 제거(setup 의 역연산)",
    )
    parser.add_argument(
        "--render-wiki-verify",
        action="store_true",
        help="wiki 검증 워크플로우만 렌더(/wiki-init 이 사용자 동의를 받은 뒤 호출).",
    )
    parser.add_argument(
        "--render-srs-verify",
        action="store_true",
        help="SRS 검증 워크플로우만 렌더(/vdev-init 이 사용자 동의를 받은 뒤 호출).",
    )
    args = parser.parse_args()
    host = host_root()
    if args.render_wiki_verify:
        for line in render_wiki_verify_workflow(host, plugin_root()):
            print(line)
        return
    if args.render_srs_verify:
        for line in render_srs_verify_workflow(host, plugin_root()):
            print(line)
        return
    if args.uninstall:
        if not run_uninstall(host):
            raise SystemExit(1)
    elif not run_setup(host, plugin_root()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
