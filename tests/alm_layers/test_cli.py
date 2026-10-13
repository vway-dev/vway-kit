"""CLI 표면 — 스킬이 부르는 명령의 출력 형상과 출하 example 의 성립."""

import json
import os
from pathlib import Path

import pytest

from scripts.alm_layers import resolve_layers
from tests._non_utf8 import non_utf8_env
from tests.alm_layers._helpers import write_config

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "alm_layers.py"


def _example_layers_yaml() -> str:
    """example.yaml 의 주석 처리된 layers 블록을 되살림.

    그 주석이 layers 선언의 SSOT 라, 해석기가 못 읽는 것을 출하하고 있지 않은지 여기서 잼."""
    example = Path(__file__).resolve().parents[2] / "vdev-config.example.yaml"
    lines = example.read_text(encoding="utf-8").splitlines()
    marks = [i for i, x in enumerate(lines) if x.strip() == "# layers:"]
    if not marks:
        pytest.fail("example.yaml 에 '# layers:' 앵커가 없음 — 주석 블록이 옮겨졌는지 확인")
    start = marks[0]
    block = []
    for line in lines[start:]:
        if not line.strip() or not line.lstrip().startswith("#"):
            break
        indent = " " * (len(line) - len(line.lstrip()))
        block.append(indent + line.lstrip()[1:].removeprefix(" "))
    return "\n".join(block)


def test_cli_emits_json(tmp_path: Path):
    import subprocess
    import sys

    body = (
        "alm:\n  recoble:\n    default: dev3\n    spaces:\n      dev3:\n"
        "        workboard: board\n        layers:\n"
        "          requirement:\n            workboard: 요구사항\n            marker: true\n"
    )
    cfg = write_config(tmp_path, body)
    out = subprocess.run(
        [sys.executable, "scripts/alm_layers.py", str(cfg), "--space", "dev3"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    got = json.loads(out.stdout)
    assert got["space"] == "dev3"
    assert got["configured"] is True
    assert got["layers"][0]["marker"] is True


def test_example_layers_block_resolves_clean(tmp_path: Path):
    body = (
        "alm:\n  recoble:\n    default: labs\n    spaces:\n      labs:\n"
        "        workboard: board\n" + _example_layers_yaml() + "\n"
    )
    got = resolve_layers(write_config(tmp_path, body), None, tmp_path, tmp_path)
    assert got["errors"] == [], got["errors"]
    assert [w for w in got["warnings"] if "모르는 선언" in w or "모르는 역할" in w] == []
    keys = {x["key"] for x in got["layers"]}
    assert keys >= {"requirement", "design", "task", "verification", "defect", "run"}, keys
    design = next(x for x in got["layers"] if x["key"] == "design")
    assert set(design["fields"]) == {"module", "feature"}
    assert design["feature_design"] is True
    task = next(x for x in got["layers"] if x["marker"])
    assert task["direct_from"] == "requirement"
    run = next(x for x in got["layers"] if x["run"])
    assert run["runs"] == "verification"


@pytest.mark.skipif(os.name != "nt", reason="POSIX 대역은 fs 인코딩까지 ASCII — tests/_non_utf8.py")
def test_a_korean_path_host_keeps_its_own_template_without_utf8_mode(tmp_path: Path):
    """스킬의 Bash 호출엔 `CLAUDE_PROJECT_DIR` 이 없어 호스트 루트는 git 이 답함. 로캘이 UTF-8 이
    아닌 호스트에서 한글 경로가 깨지면 호스트 양식을 못 찾고 본문이 출하본으로 나감 — 경고 없음."""
    import subprocess
    import sys

    from scripts._vway_paths import vway_dir

    host = tmp_path / "한글호스트"
    forms = vway_dir(host) / "templates" / "alm"
    forms.mkdir(parents=True)
    (forms / "requirement.md").write_text("host", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=host, check=True)
    body = (
        "alm:\n  recoble:\n    default: dev3\n    spaces:\n      dev3:\n"
        "        workboard: board\n        layers:\n"
        "          requirement:\n            workboard: 요구사항\n"
    )
    env = non_utf8_env()
    env.pop("CLAUDE_PROJECT_DIR", None)
    out = subprocess.run(
        [sys.executable, str(_SCRIPT), str(write_config(tmp_path, body)), "--space", "dev3"],
        # 하위 디렉터리에서 — git 이 답하지 못할 때의 폴백(cwd)이 호스트 루트와 겹치지 않게.
        cwd=forms,
        env=env,
        capture_output=True,
        check=True,
    )
    template = json.loads(out.stdout.decode("utf-8"))["layers"][0]["template"]
    assert os.path.samefile(template, forms / "requirement.md"), template
