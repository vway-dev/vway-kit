"""이 폴더의 모든 모듈이 딛는 `project` 픽스처."""

from pathlib import Path

import pytest

from tests.invalidate_gate_markers._helpers import KEPT, repo, vdev


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = repo(tmp_path / "project")
    for name in KEPT:
        (vdev(root) / name).touch()
    return root
