"""모든 템플릿과 이 저장소 자신의 CI 에 걸친 워크플로 단위 성질.

최상위 `permissions:` 가 없으면 토큰이 저장소 기본값을 받음 — GitHub 가 기본값을 바꾸기 전에 만든
저장소에서는 모든 범위의 읽기·쓰기. 배포 컴포넌트(`deploy.*`)는 권한을 호출 job 에서 물려받는
설계라 대상이 아님(`tests/test_workflow_templates.py` 가 그쪽을 고정). setup-java 는 고정한
메이저의 입력 이름을 써야 하고, entropy 의 파일 크기 감사는 이름에 공백이 든 파일도 세야 함.
"""

import os
from pathlib import Path

import pytest
import yaml

from tests._bash import BASH
from tests._proc import run_bounded
from tests.vdev_init._helpers import PLUGIN

WORKFLOWS = sorted(
    [
        *(p for p in (PLUGIN / "github").glob("*.yml") if not p.name.startswith("deploy.")),
        *(PLUGIN / ".github" / "workflows").glob("*.yml"),
    ]
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").replace("__VWAY_", "VWAY_"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_workflow_declares_its_token_permissions(path):
    assert isinstance(_load(path).get("permissions"), dict), path.name


def test_the_contract_test_may_comment_on_its_pull_request():
    """schemathesis/action 은 커버리지 요약을 PR 코멘트로 남김."""
    doc = _load(PLUGIN / "github" / "api-contract.workflow.example.yml")
    assert doc["permissions"] == {"contents": "read", "pull-requests": "write"}


@pytest.mark.parametrize("path", sorted((PLUGIN / "github").glob("*.yml")), ids=lambda p: p.name)
def test_setup_java_takes_the_input_names_of_its_pinned_major(path):
    """v6 가 입력을 `*-env-var` 로 바꿈 — 옛 이름은 폐기 예정 별칭으로만 남음."""
    text = path.read_text(encoding="utf-8")
    assert "actions/setup-java@v5" not in text
    for old in ("server-username:", "server-password:", "gpg-passphrase:"):
        assert old not in text, old


@pytest.mark.skipif(not BASH, reason="bash 필요")
def test_entropy_counts_a_file_whose_name_holds_a_space(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "big file.py").write_text("x\n" * 600, encoding="utf-8")
    (src / "small.py").write_text("x\n", encoding="utf-8")
    steps = _load(PLUGIN / "github" / "entropy-check.workflow.example.yml")["jobs"]["entropy"][
        "steps"
    ]
    run = next(s for s in steps if s.get("name", "").startswith("File size audit"))["run"]
    r = run_bounded(
        [BASH, "-e", "-o", "pipefail", "-c", run.replace("VWAY_ENTROPY_PATHS__", "src/")],
        cwd=str(tmp_path),
        env=dict(os.environ),
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "600 src/big file.py" in r.stdout
    assert "small.py" not in r.stdout
