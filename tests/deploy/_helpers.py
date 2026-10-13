"""deploy 렌더 테스트가 공유하는 헬퍼 — config 쓰기, 렌더·배선 호출."""

from pathlib import Path

import yaml as _yaml

from scripts.vdev_init_setup import (
    render_deploy_workflows,
)

PLUGIN = Path(__file__).resolve().parent.parent.parent


def _write_deploy_config(host: Path, deploy: dict) -> None:
    """호스트 config 에 deploy 블록만 씀."""
    cfg_dir = host / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "vdev-config.yaml").write_text(
        _yaml.safe_dump({"deploy": deploy}, allow_unicode=True), encoding="utf-8"
    )


def _render(host: Path, deploy: dict) -> tuple[list[str], dict | None]:
    _write_deploy_config(host, deploy)
    lines = render_deploy_workflows(host, PLUGIN)
    dest = host / ".github" / "workflows" / "deploy.yml"
    doc = _yaml.safe_load(dest.read_text(encoding="utf-8")) if dest.is_file() else None
    return lines, doc


# ── wire_release_deploy: release.yml 에 deploy 호출 job 배선 ─────────────────────

_RELEASE_OK = """\
name: release

on:
  push:
    branches: [main]

concurrency:
  group: release-${{ github.ref }}

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    outputs:
      tag: ${{ steps.released.outputs.tag }}
    steps:
      - uses: actions/checkout@v7
      - id: released
        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"
"""


def _write_release(host: Path, text: str = _RELEASE_OK) -> Path:
    wf = host / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")
    return wf


def _wire(host: Path, deploy: dict) -> list[str]:
    from scripts.vdev_init_setup import wire_release_deploy

    _write_deploy_config(host, deploy)
    return wire_release_deploy(host)


# ── Finding 2: 손상된(END 없는) 마커 블록은 truncate 하지 않고 거부해야 함 ──────────────


_RELEASE_DANGLING_BEGIN = (
    _RELEASE_OK
    + "  # vway-kit:deploy BEGIN — /vdev-init 이 vdev-config.deploy 로 생성. 직접 수정 금지.\n"
    "  deploy:\n"
    "    needs: [release]\n"
    "    if: ${{ needs.release.outputs.tag != '' }}\n"
    "    permissions:\n"
    "      contents: read\n"
    "    uses: ./.github/workflows/deploy.yml\n"
    "    with:\n"
    "      tag: ${{ needs.release.outputs.tag }}\n"
    "    secrets: inherit\n"
    # END 마커가 없음(병합 충돌·수기 편집으로 손상됐다고 가정) — 대신 소비자가 직접
    # 추가한 job 이 바로 이어 붙음.
    "  my-own-job:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - run: true\n"
)


# ── detect_legacy_release_workflow: 헤더 주석 오탐 회귀(Task 8 결함) ─────────────────
#
# release 템플릿의 헤더 주석은 발행을 어디가 맡는지 설명하며 도구명을 자유롭게
# 언급함(예: cargo-release 템플릿은 "crates.io 발행은 이 워크플로 몫이 아님
# (--no-publish)" 처럼 "cargo publish" 를 explains-away 문맥에서 언급). raw text 검색은
# 이 주석을 잔존 발행 스텝으로 오탐함 — 파싱된 step 만 봐야 함(test_workflow_templates
# .py::test_release_templates_have_no_build_or_publish 와 동일 원칙).

RELEASE_TEMPLATE_DIR = PLUGIN / "github"
_RELEASE_TEMPLATE_NAMES = sorted(
    p.name for p in RELEASE_TEMPLATE_DIR.glob("release.*.workflow.example.yml")
)


def _render_release_template(name: str, host: Path) -> Path:
    """SOURCE release 템플릿을 __VWAY_* 토큰만 치환해 호스트에 렌더 — 6종 템플릿에
    등장하는 토큰은 __VWAY_STABLE__/__VWAY_PRERELEASE__ 뿐(render_versioning_workflows
    가 실제로 치환하는 것과 동일)."""
    text = (RELEASE_TEMPLATE_DIR / name).read_text(encoding="utf-8")
    text = text.replace("__VWAY_STABLE__", "main").replace("__VWAY_PRERELEASE__", "stage")
    wf = host / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")
    return wf


# ── true-positive: 진단이 실제 문제는 여전히 잡아야 한다(오탐 회피가 무보고로 안 새게) ──────

_RELEASE_TOKEN_BASE = """\
name: release
on:
  push:
    branches: [main]
jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    outputs:
      tag: ${{ steps.released.outputs.tag }}
    steps:
      - uses: actions/checkout@v7
        with:
          token: ${{ secrets.RELEASE_TOKEN }}
__EXTRA_STEP__
      - id: released
        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"
"""


def _write_release_token_workflow(host: Path, extra_step: str = "") -> Path:
    text = _RELEASE_TOKEN_BASE.replace("__EXTRA_STEP__", extra_step)
    wf = host / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")
    return wf


_RELEASE_NO_TAG_OUTPUT = """\
name: release
on:
  push:
    branches: [main]
jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
        with:
          token: ${{ secrets.RELEASE_TOKEN }}
      - id: released
        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"
"""


# ── Finding 1 (Critical): 파싱된 step/job 의 타입이 오타로 깨져 있어도 raise 하면 안 됨 ─────
# (예: `run: 5`, `uses: true`, `steps: 5` — 인용부호 없는 YAML 스칼라는 흔한 실수).
# 각 케이스는 crash 안전성(_release_workflow_steps/_stale_publish_needles/
# _release_has_tag_output 하드닝)을 검증. has_tag_output 기대값은 케이스마다 다름:
# jobs 자체가 무너지면(0 개 후보) FAIL-OPEN=True, release job 의 *값*이 dict 가 아니면
# (job_value_not_dict) wire_release_deploy 의 거부와 일치시켜 False 임(Minor finding 5).

_MALFORMED_RELEASE_CASES: dict[str, str] = {
    "run_not_str": ("jobs:\n  release:\n    outputs:\n      tag: v1\n    steps:\n      - run: 5\n"),
    "uses_not_str": (
        "jobs:\n  release:\n    outputs:\n      tag: v1\n    steps:\n      - uses: true\n"
    ),
    "steps_not_list": "jobs:\n  release:\n    outputs:\n      tag: v1\n    steps: 5\n",
    "jobs_not_dict": "jobs: 5\n",
    "job_value_not_dict": 'jobs:\n  release: "not-a-dict"\n',
    "env_not_dict": (
        "env: [a, b]\njobs:\n  release:\n    outputs:\n      tag: v1\n    steps: []\n"
    ),
}
