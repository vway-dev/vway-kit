"""배포·wiki 검증·SRS 검증·문체 검사 워크플로 렌더 — 무엇이 렌더를 켜는가.

넷이 서로 다른 스위치에 달림. `deploy` 는 `deploy` 섹션, `doc-style` 은
`doc_style.enable`(그 스크립트가 읽는 것과 **같은** 플래그라 되돌리면 렌더된 파일이
조용해짐), `wiki-verify` 와 `srs-verify` 는 플래그가 아니라 각각 `/wiki-init`·
`/vdev-init` 이 받아 오는 사람의 동의 — `/vdev-init` Step 2 시점에는 wiki 그래프가 없어
`wiki-verify` 를 물을 수 없지만, `srs-verify` 는 그 같은 시점(Step 2.9)에 직접 물음. 넷
다 이미 있는 파일은 덮지 않고 보고만 함.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml as _yaml

from scripts.vdev_init_setup import (
    load_contract_config,
    render_doc_style_workflow,
    render_srs_verify_workflow,
    render_wiki_verify_workflow,
    render_workflow,
    run_setup,
)
from tests.vdev_init._helpers import (
    PLUGIN,
    _mk_host_config,
    _write_vdev_config,
)


def _write_doc_style(host: Path, doc_style) -> None:
    """호스트 config 에 `doc_style` 블록만 씀 — 이 파일의 판정이 그 한 키에 걸림."""
    _mk_host_config(host, _yaml.safe_dump({"doc_style": doc_style}, allow_unicode=True))


def test_render_workflow_creates_and_substitutes(tmp_path: Path):
    _write_vdev_config(
        tmp_path,
        {
            "enable": True,
            "branches": ["dev", "stage", "main"],
            "action_ref": "schemathesis/action@v3",
            "schema": "http://localhost:8000/openapi.json",
            "base_url": "http://localhost:8000",
            "server": {
                "compose_file": "docker-compose.yml",
                "health_url": "http://localhost:8000/health",
                "health_timeout": 60,
            },
        },
    )
    out = render_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    dest = tmp_path / ".github" / "workflows" / "api-contract.yml"
    text = dest.read_text(encoding="utf-8")
    # 토큰이 모두 치환됨
    assert "__VWAY_" not in text
    # 렌더 결과가 유효 YAML(예외 없이 파싱). 주의: GitHub Actions 의 'on:' 키는
    # PyYAML 이 boolean True 키로 파싱하므로(YAML 1.1 함정) data["on"] 접근은 KeyError.
    # 의도(브랜치/액션/스키마 치환)는 텍스트로 직접 검증함.
    _yaml.safe_load(text)
    assert "branches: [dev, stage, main]" in text
    assert "schemathesis/action@v3" in text
    assert "http://localhost:8000/openapi.json" in text


def test_render_workflow_disabled(tmp_path: Path):
    _write_vdev_config(tmp_path, {"enable": False, "branches": ["dev"]})
    out = render_workflow(tmp_path, PLUGIN)
    assert any("enable=false" in line for line in out)
    assert load_contract_config(tmp_path) == {"enable": False, "branches": ["dev"]}
    assert not (tmp_path / ".github" / "workflows" / "api-contract.yml").exists()


def test_render_workflow_absent_section(tmp_path: Path):
    # vdev-config 자체가 없으면 미설정 — skip
    out = render_workflow(tmp_path, PLUGIN)
    assert any("미설정" in line for line in out)
    assert load_contract_config(tmp_path) is None
    assert not (tmp_path / ".github" / "workflows" / "api-contract.yml").exists()


def test_run_setup_renders_workflow(tmp_path: Path, capsys):
    from scripts.vdev_init_setup import run_setup

    _write_vdev_config(
        tmp_path,
        {
            "enable": True,
            "branches": ["dev", "stage", "main"],
            "action_ref": "schemathesis/action@v3",
            "schema": "http://localhost:8000/openapi.json",
            "base_url": "http://localhost:8000",
            "server": {
                "compose_file": "docker-compose.yml",
                "health_url": "http://localhost:8000/health",
                "health_timeout": 60,
            },
        },
    )
    run_setup(tmp_path, PLUGIN)
    captured = capsys.readouterr().out
    assert "계약 테스트" in captured
    assert (tmp_path / ".github" / "workflows" / "api-contract.yml").is_file()


def test_render_wiki_verify_workflow_reads_no_config(tmp_path: Path):
    # 함수 자체는 무조건 — 판정하는 것은 `/wiki-init` 이고, 그것이 키를 읽는 대신 사람에게
    # 물음. 거기 닿았다는 것이 곧 wiki 가 있고 그 그래프가 `--verify` 를 통과했다는 뜻이라,
    # 여기 남겨 둘 게이트가 없음.
    out = render_wiki_verify_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    dest = tmp_path / ".github" / "workflows" / "wiki-verify.yml"
    text = dest.read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    data = _yaml.safe_load(text)
    assert data["jobs"]["wiki-verify"]["timeout-minutes"] == 5


def test_render_wiki_verify_workflow_preserves_existing(tmp_path: Path):
    dest = tmp_path / ".github" / "workflows" / "wiki-verify.yml"
    dest.parent.mkdir(parents=True)
    dest.write_text("# custom\n", encoding="utf-8")
    out = render_wiki_verify_workflow(tmp_path, PLUGIN)
    assert any("이미" in line for line in out)
    assert dest.read_text(encoding="utf-8") == "# custom\n"


def test_run_setup_does_not_render_wiki_verify(tmp_path: Path, capsys):
    # /vdev-init 은 wiki 가 있기 전에 돎 — 그 그래프를 검증하는 워크플로는 사용자에게 물을
    # 수 없는 질문이라, 렌더도 위험 고지도 /wiki-init 이 가져감.
    run_setup(tmp_path, PLUGIN)
    assert not (tmp_path / ".github" / "workflows" / "wiki-verify.yml").exists()
    assert "wiki 검증" not in capsys.readouterr().out


def test_run_setup_does_not_render_srs_verify(tmp_path: Path, capsys):
    # 셋업은 docs/srs 를 보지 않음 — 가리킬 SRS 가 있는지는 /vdev-init 의 단계가 묻고,
    # 사용자의 yes 가 곧 게이트라 run_setup 이 대신 렌더하면 그 질문이 통째로 사라짐.
    run_setup(tmp_path, PLUGIN)
    assert not (tmp_path / ".github" / "workflows" / "srs-verify.yml").exists()
    assert "srs-verify" not in capsys.readouterr().out


def test_render_wiki_verify_cli_flag_writes_the_workflow(tmp_path: Path):
    # /wiki-init 이 이 플래그로만 렌더에 닿음 — 이름이 바뀌면 사용자가 "예" 라고 답한 바로
    # 그 순간에 스킬의 단계가 실패함.
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
    env["PYTHONPATH"] = str(PLUGIN)
    proc = subprocess.run(
        [sys.executable, str(PLUGIN / "scripts" / "vdev_init_setup.py"), "--render-wiki-verify"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / ".github" / "workflows" / "wiki-verify.yml").is_file()


def test_render_srs_verify_workflow_reads_no_config(tmp_path: Path):
    # wiki-verify 와 같은 이유로 무조건 — 판정하는 것은 사람의 "예" 이고, 여기 닿는
    # 유일한 길(--render-srs-verify)이 그 답을 이미 받은 뒤라 남겨 둘 게이트가 없음.
    out = render_srs_verify_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    dest = tmp_path / ".github" / "workflows" / "srs-verify.yml"
    text = dest.read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    data = _yaml.safe_load(text)
    assert data["jobs"]["srs-verify"]["timeout-minutes"] == 5


def test_render_srs_verify_workflow_preserves_existing(tmp_path: Path):
    dest = tmp_path / ".github" / "workflows" / "srs-verify.yml"
    dest.parent.mkdir(parents=True)
    dest.write_text("# custom\n", encoding="utf-8")
    out = render_srs_verify_workflow(tmp_path, PLUGIN)
    assert any("이미" in line for line in out)
    assert dest.read_text(encoding="utf-8") == "# custom\n"


def test_render_srs_verify_cli_flag_writes_the_workflow(tmp_path: Path):
    # /vdev-init 의 Step 2.9 가 이 플래그로만 렌더에 닿음 — 이름이 바뀌면 사용자가 "예"
    # 라고 답한 바로 그 순간에 스킬의 단계가 실패함.
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
    env["PYTHONPATH"] = str(PLUGIN)
    proc = subprocess.run(
        [sys.executable, str(PLUGIN / "scripts" / "vdev_init_setup.py"), "--render-srs-verify"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / ".github" / "workflows" / "srs-verify.yml").is_file()


def test_render_workflow_idempotent_reports_only(tmp_path: Path):
    contract = {
        "enable": True,
        "branches": ["dev", "stage", "main"],
        "action_ref": "schemathesis/action@v3",
        "schema": "http://localhost:8000/openapi.json",
        "base_url": "http://localhost:8000",
        "server": {
            "compose_file": "docker-compose.yml",
            "health_url": "http://localhost:8000/health",
            "health_timeout": 60,
        },
    }
    _write_vdev_config(tmp_path, contract)
    render_workflow(tmp_path, PLUGIN)  # 1차 생성
    dest = tmp_path / ".github" / "workflows" / "api-contract.yml"
    sentinel = dest.read_text(encoding="utf-8") + "\n# user edit\n"
    dest.write_text(sentinel, encoding="utf-8")  # 사용자 수정 흉내
    out = render_workflow(tmp_path, PLUGIN)  # 2차 — 보고만
    assert any("이미 있어" in line for line in out)
    assert dest.read_text(encoding="utf-8") == sentinel  # 덮어쓰지 않음


# ── Task 4: 마이그레이션 골격 ───────────────────────────────────────────────────


# ── load_alm_config — 최상위 teamer 하위호환(레거시 경로가 I3 의 근거) ─────────────


def test_render_doc_style_workflow_when_enabled(tmp_path: Path):
    _write_doc_style(tmp_path, {"enable": True, "paths": ["**/*.md"]})
    out = render_doc_style_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    dest = tmp_path / ".github" / "workflows" / "doc-style.yml"
    text = dest.read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    data = _yaml.safe_load(text)
    assert data["jobs"]["doc-style"]["timeout-minutes"] == 5


@pytest.mark.parametrize(
    "doc_style",
    [None, {"enable": False, "paths": ["**/*.md"]}],
    ids=["section-absent", "enable-false"],
)
def test_render_doc_style_workflow_skips_unless_opted_in(tmp_path: Path, doc_style):
    # 산문 레이어가 내는 판정이 이 워크플로 하나뿐이라 가정하지 않고 물음 — 답한 적 없는
    # 호스트는 파일을 못 받음.
    if doc_style is not None:
        _write_doc_style(tmp_path, doc_style)
    out = render_doc_style_workflow(tmp_path, PLUGIN)
    assert not (tmp_path / ".github" / "workflows" / "doc-style.yml").exists()
    assert any("[=]" in line for line in out)


def test_render_doc_style_workflow_preserves_existing(tmp_path: Path):
    _write_doc_style(tmp_path, {"enable": True, "paths": ["**/*.md"]})
    dest = tmp_path / ".github" / "workflows" / "doc-style.yml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("# custom\n", encoding="utf-8")
    out = render_doc_style_workflow(tmp_path, PLUGIN)
    assert any("이미" in line for line in out)
    assert dest.read_text(encoding="utf-8") == "# custom\n"


def test_run_setup_renders_doc_style_when_enabled(tmp_path: Path, capsys):
    _write_doc_style(tmp_path, {"enable": True, "paths": ["**/*.md"]})
    run_setup(tmp_path, PLUGIN)
    dest = tmp_path / ".github" / "workflows" / "doc-style.yml"
    assert dest.is_file()
    assert "문체 검사" in capsys.readouterr().out
    assert "doc_style_check.py" in dest.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "doc_style",
    [None, {"enable": False}],
    ids=["section-absent", "enable-false"],
)
def test_run_setup_skips_doc_style_unless_opted_in(tmp_path: Path, doc_style):
    if doc_style is not None:
        _write_doc_style(tmp_path, doc_style)
    run_setup(tmp_path, PLUGIN)
    assert not (tmp_path / ".github" / "workflows" / "doc-style.yml").exists()
