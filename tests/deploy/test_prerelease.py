"""prerelease 태그가 안정 채널에 닿지 않는가 — 레지스트리의 기본 해석 대상을 안 옮김.

rc 태그(`vX.Y.Z-rc.N`)를 레지스트리 기본 이름으로 내면 버전을 고정하지 않은 설치가 전부 그
rc 를 받음. npm 은 `--tag` 없는 발행이 `latest` 를 옮기므로 발행 스텝을 실제 bash 로 돌려 인자를
잼. GHCR 은 `type=raw` 태그 하나만 받고 `latest` 를 달지 않는지 텍스트로 봄.
"""

from __future__ import annotations

import os

import pytest
import yaml

from tests._bash import BASH
from tests._proc import run_bounded
from tests.deploy._helpers import PLUGIN


def _steps(name: str) -> list[dict]:
    doc = yaml.safe_load((PLUGIN / "github" / name).read_text(encoding="utf-8"))
    return [s for job in doc["jobs"].values() for s in job["steps"]]


@pytest.mark.skipif(not BASH, reason="bash 필요")
@pytest.mark.parametrize("auth", ["oidc", "token"])
@pytest.mark.parametrize(("tag", "dist_tag"), [("v1.2.0-rc.1", ["--tag", "next"]), ("v1.2.0", [])])
def test_npm_publishes_a_prerelease_under_next(auth, tag, dist_tag):
    """`--tag` 없이 낸 prerelease 는 `latest` 가 되고, 맨 `npm install` 이 그것을 받음."""
    step = next(s for s in _steps("deploy.npm.workflow.example.yml") if auth in str(s.get("if")))
    # PATH 스텁 대신 함수 — Git Bash 가 /usr/bin 을 PATH 앞에 다시 얹어 스텁을 가림.
    script = 'npm() { echo "ARGS $*"; }\n' + step["run"]
    r = run_bounded(
        [BASH, "-e", "-c", script], env={**os.environ, "TAG": tag}, text=True, timeout=30
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["ARGS", "publish", *dist_tag]


def test_ghcr_never_tags_latest():
    """metadata-action 의 `type=raw` 는 `flavor: latest=auto` 에서도 `latest` 를 안 더함."""
    meta = next(s for s in _steps("deploy.ghcr.workflow.example.yml") if s.get("id") == "meta")
    tags = str(meta["with"]["tags"])
    assert tags.strip() == "type=raw,value=${{ inputs.tag }}"
    assert "latest" not in str(meta["with"].get("flavor", ""))
