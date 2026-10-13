"""release 템플릿 회귀 커버리지 — 갓 렌더한 템플릿은 절대 stale 이 아님."""

from pathlib import Path

import pytest

from scripts.vdev_init_setup import (
    report_legacy_release_workflow,
)
from tests.deploy._helpers import (
    _RELEASE_TEMPLATE_NAMES,
    _render_release_template,
)


def test_every_release_template_is_covered_by_regression():
    """새 release 템플릿이 추가되면 아래 parametrize 목록도 같이 늘어야 한다(누락 방지)."""
    assert _RELEASE_TEMPLATE_NAMES == [
        "release.cargo-release.workflow.example.yml",
        "release.gitversion.workflow.example.yml",
        "release.jreleaser.workflow.example.yml",
        "release.python-semantic-release.workflow.example.yml",
        "release.sbt-ci-release.workflow.example.yml",
        "release.semantic-release.workflow.example.yml",
    ]


@pytest.mark.parametrize("name", _RELEASE_TEMPLATE_NAMES)
def test_freshly_rendered_release_template_is_never_stale(name: str, tmp_path: Path):
    """6종 release 템플릿을 각각 렌더해 report_legacy_release_workflow 가 OK 한 줄만
    내는지 확인. cargo-release/gitversion/sbt-ci-release 는 헤더 주석에 각각
    cargo publish·dotnet build·sbt ci-release 를 언급하므로, raw text 스캔 구현이면
    이 테스트가 RED 다(현재 구현은 파싱된 step 만 보므로 GREEN)."""
    _render_release_template(name, tmp_path)
    assert report_legacy_release_workflow(tmp_path) == [
        "  [=] release 워크플로 RELEASE_TOKEN 방식 (OK)"
    ]
