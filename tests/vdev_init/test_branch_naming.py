"""렌더된 branch-naming 워크플로를 호스트가 실제로 push 하는 브랜치 이름에 돌림.

통합 브랜치는 vdev-config `branches.integration` 에서 오고, `hotfix/<이름>` 은 hotfix 절차가
만드는 모양 그대로, 봇 브랜치(`dependabot/`·`renovate/`)도 통과해야 함. 하나라도 빠지면 그
브랜치의 모든 push 가 붉어짐. 검사 스텝은 실제 bash 로 돌려 잼.
"""

import os
from pathlib import Path

import pytest
import yaml

from scripts import vdev_init_setup as m
from tests._bash import BASH
from tests._proc import run_bounded
from tests.vdev_init._helpers import PLUGIN

_CONFIG = (
    "branches: {integration: develop, staging: qa, production: trunk}\n"
    "versioning:\n  enable: true\n  release_tool: python-semantic-release\n"
    "  branches: {stable: trunk, prerelease: qa}\n"
    "  branch_naming: {enable: true}\n"
)


def _render(tmp_path: Path, config: str) -> dict:
    host = tmp_path / "host"
    cfg = host / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(config, encoding="utf-8")
    m.render_versioning_workflows(host, PLUGIN)
    text = (host / ".github" / "workflows" / "branch-naming.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    return yaml.safe_load(text)


def test_a_tag_push_never_runs_the_check(tmp_path):
    doc = _render(tmp_path, _CONFIG)
    push = doc[True]["push"]  # PyYAML 은 맨 키 `on` 을 True 로 읽음
    assert push == {"branches": ["**"]}


@pytest.mark.skipif(not BASH, reason="bash 필요")
@pytest.mark.parametrize(
    ("branch", "ok"),
    [
        ("develop", True),
        ("qa", True),
        ("trunk", True),
        ("dev", False),
        ("hotfix/login-crash", True),
        ("hotfix/1.2.3", True),
        ("dependabot/npm_and_yarn/lodash-4.17.21", True),
        ("renovate/pin-deps", True),
        ("feature/x", True),
        ("hotfix/", False),
        ("wip", False),
    ],
)
def test_the_configured_branches_and_tool_branches_pass(tmp_path, branch, ok):
    doc = _render(tmp_path, _CONFIG)
    run = doc["jobs"]["validate"]["steps"][0]["run"]
    r = run_bounded([BASH, "-e", "-c", run], env={**os.environ, "BRANCH": branch}, timeout=30)
    assert (r.returncode == 0) is ok, r.stdout


def test_integration_defaults_to_dev(tmp_path):
    assert m.load_integration_branch(tmp_path) == "dev"
