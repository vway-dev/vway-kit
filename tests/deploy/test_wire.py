"""release.yml 에 deploy 호출 job 배선.

태그 출력이 없거나 job 이 여럿이거나 마커 블록이 손상됐으면 **거부**함 — truncate 하면
사람이 쓴 워크플로가 사라짐. 비-UTF8 바이트도 FAIL-OPEN.
"""

from pathlib import Path

import yaml as _yaml

from scripts.vdev_init_setup import (
    _load_yaml_safe,
)
from tests.deploy._helpers import (
    _RELEASE_DANGLING_BEGIN,
    _RELEASE_OK,
    PLUGIN,
    _wire,
    _write_deploy_config,
    _write_release,
)


def test_wire_inserts_deploy_job(tmp_path: Path):
    wf = _write_release(tmp_path)
    lines = _wire(
        tmp_path,
        {
            "enable": True,
            "targets": [
                {"name": "p", "target": "pypi", "auth": "oidc"},
                {"name": "img", "target": "ghcr", "image": "x"},
            ],
        },
    )
    doc = _yaml.safe_load(wf.read_text(encoding="utf-8"))
    dep = doc["jobs"]["deploy"]
    assert dep["needs"] == ["release"]
    assert dep["if"] == "${{ needs.release.outputs.tag != '' }}"
    assert dep["uses"] == "./.github/workflows/deploy.yml"
    assert dep["with"] == {"tag": "${{ needs.release.outputs.tag }}"}
    assert dep["secrets"] == "inherit"
    # 전 타깃 권한의 합집합 — 체인에서 권한은 감소만 가능. pypi 는 auth: oidc 를
    # 명시해야 id-token: write 가 합집합에 들어감(auth 기본값은 token).
    assert dep["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "packages": "write",
    }
    assert "timeout-minutes" not in dep
    assert any("배선" in line for line in lines)


def test_wire_pypi_default_auth_grants_no_id_token(tmp_path: Path):
    """pypi 를 auth 명시 없이 두면 기본값 token 이 적용돼 id-token 이 합집합에 없음."""
    wf = _write_release(tmp_path)
    _wire(
        tmp_path,
        {
            "enable": True,
            "targets": [
                {"name": "p", "target": "pypi"},
                {"name": "img", "target": "ghcr", "image": "x"},
            ],
        },
    )
    doc = _yaml.safe_load(wf.read_text(encoding="utf-8"))
    dep = doc["jobs"]["deploy"]
    assert dep["permissions"] == {"contents": "read", "packages": "write"}


def test_wire_is_idempotent(tmp_path: Path):
    wf = _write_release(tmp_path)
    cfg = {"enable": True, "targets": [{"name": "p", "target": "pypi"}]}
    _wire(tmp_path, cfg)
    first = wf.read_text(encoding="utf-8")
    _wire(tmp_path, cfg)
    assert wf.read_text(encoding="utf-8") == first
    assert first.count("# vway-kit:deploy BEGIN") == 1


def test_wire_replaces_block_when_targets_change(tmp_path: Path):
    wf = _write_release(tmp_path)
    _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    assert "packages: write" not in wf.read_text(encoding="utf-8")
    _wire(
        tmp_path,
        {"enable": True, "targets": [{"name": "i", "target": "ghcr", "image": "x"}]},
    )
    text = wf.read_text(encoding="utf-8")
    assert text.count("# vway-kit:deploy BEGIN") == 1
    assert "packages: write" in text
    assert "id-token: write" not in text


def test_wire_removes_block_when_disabled(tmp_path: Path):
    wf = _write_release(tmp_path)
    _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    _wire(tmp_path, {"enable": False, "targets": [{"name": "p", "target": "pypi"}]})
    text = wf.read_text(encoding="utf-8")
    assert "vway-kit:deploy" not in text
    assert _yaml.safe_load(text)["jobs"].keys() == {"release"}


def test_wire_refuses_when_no_tag_output(tmp_path: Path):
    """구버전 release.yml — outputs.tag 를 소급 삽입하지 않는다(의미적 배치)."""
    legacy = _RELEASE_OK.replace("    outputs:\n      tag: ${{ steps.released.outputs.tag }}\n", "")
    wf = _write_release(tmp_path, legacy)
    lines = _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    assert wf.read_text(encoding="utf-8") == legacy
    assert any("outputs.tag" in line and "[!]" in line for line in lines)


def test_wire_refuses_when_multiple_jobs(tmp_path: Path):
    two = _RELEASE_OK + "  lint:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n"
    wf = _write_release(tmp_path, two)
    lines = _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    assert wf.read_text(encoding="utf-8") == two
    assert any("job 이 여러 개" in line for line in lines)


def test_wire_uses_actual_release_job_id(tmp_path: Path):
    renamed = _RELEASE_OK.replace("  release:\n", "  publish:\n")
    wf = _write_release(tmp_path, renamed)
    _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    dep = _yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"]["deploy"]
    assert dep["needs"] == ["publish"]
    assert dep["if"] == "${{ needs.publish.outputs.tag != '' }}"


def test_wire_refuses_when_jobs_not_last(tmp_path: Path):
    moved = _RELEASE_OK + "\nenv:\n  FOO: bar\n"
    wf = _write_release(tmp_path, moved)
    lines = _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    assert wf.read_text(encoding="utf-8") == moved
    assert any("마지막 최상위 키" in line for line in lines)


def test_wire_skips_when_release_absent(tmp_path: Path):
    lines = _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    assert any("release.yml 없음" in line for line in lines)
    assert not (tmp_path / ".github" / "workflows" / "release.yml").exists()


def test_load_yaml_safe_handles_non_utf8_bytes(tmp_path: Path):
    """비 UTF-8 바이트(0xff)가 섞인 YAML 파일은 raise 하지 않고 {} 를 돌려줌."""
    p = tmp_path / "bad.yaml"
    p.write_bytes(b"deploy:\n  enable: \xff true\n")
    assert _load_yaml_safe(p) == {}


def test_wire_release_deploy_handles_non_utf8_release_yml(tmp_path: Path):
    """release.yml 에 비 UTF-8 바이트가 있으면 raise 하지 않고 [!] 로 보고함.

    UnicodeDecodeError 는 ValueError 의 서브클래스이지 OSError 의 서브클래스가 아님 —
    `except (OSError, yaml.YAMLError)` 만으론 못 잡고 예외가 그대로 새어나가 setup 전체를
    죽임(FAIL-OPEN 위반).
    """
    from scripts.vdev_init_setup import wire_release_deploy

    raw = b"name: release\njobs:\n  release:\n    runs-on: ubuntu-latest\n    # \xff\n"
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_bytes(raw)
    _write_deploy_config(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    lines = wire_release_deploy(tmp_path)  # raise 하면 이 테스트 자체가 실패
    assert any("[!]" in line for line in lines)
    assert wf.read_bytes() == raw


def test_wire_refuses_dangling_begin_without_end(tmp_path: Path):
    """BEGIN 은 있는데 END 가 없으면(소비자 job 이 뒤에 붙어 있어도) 거부하고 원본을
    바이트 단위로 보존 — BEGIN 부터 EOF 까지 통째로 지우면 소비자의 my-own-job 까지
    조용히 삭제됨."""
    wf = _write_release(tmp_path, _RELEASE_DANGLING_BEGIN)
    lines = _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    assert wf.read_text(encoding="utf-8") == _RELEASE_DANGLING_BEGIN
    assert any("[!]" in line and "손상" in line for line in lines)


def test_wire_refuses_dangling_begin_even_on_removal_path(tmp_path: Path):
    """deploy.enable: false(제거 경로)여도 손상된 마커는 truncate 하지 않고 거부함."""
    wf = _write_release(tmp_path, _RELEASE_DANGLING_BEGIN)
    lines = _wire(tmp_path, {"enable": False, "targets": [{"name": "p", "target": "pypi"}]})
    assert wf.read_text(encoding="utf-8") == _RELEASE_DANGLING_BEGIN
    assert any("[!]" in line and "손상" in line for line in lines)


def test_wire_refuses_when_trailing_document_end_marker(tmp_path: Path):
    """release.yml 이 `...` 문서 종료 마커로 끝나면, 블록을 이어 붙인 결과가 두 번째 YAML
    문서가 되어 `yaml.safe_load` 가 ComposerError(YAMLError 의 서브클래스)를 냄 — 조건
    ⑤("삽입 후 재파싱 실패")의 구체적 재현. 원본은 바이트 단위로 보존돼야 하고, 원인 힌트가
    노트에 있어야 함."""
    text = _RELEASE_OK + "...\n"
    wf = _write_release(tmp_path, text)
    lines = _wire(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    assert wf.read_text(encoding="utf-8") == text
    assert any("유효 YAML 이 아니어서 원본 유지" in line for line in lines)
    assert any("문서 종료 마커" in line for line in lines)


def test_run_setup_renders_and_wires(tmp_path: Path, capsys):
    """기존 test_run_setup_renders_workflow 와 같은 방식 — monkeypatch 불필요
    (detect_autoupdate_auth 는 git config 실패를 FAIL-OPEN 으로 흡수)."""
    from scripts.vdev_init_setup import run_setup

    _write_release(tmp_path)
    _write_deploy_config(
        tmp_path,
        {"enable": True, "targets": [{"name": "p", "target": "pypi", "build": "uv build"}]},
    )
    run_setup(tmp_path, PLUGIN)
    printed = capsys.readouterr().out
    assert "[배포 워크플로우]" in printed
    assert "[배포 배선]" in printed

    wf = tmp_path / ".github" / "workflows"
    assert (wf / "deploy-pypi.yml").is_file()
    orch = _yaml.safe_load((wf / "deploy.yml").read_text(encoding="utf-8"))
    assert set(orch["jobs"]) == {"resolve", "p"}
    rel = _yaml.safe_load((wf / "release.yml").read_text(encoding="utf-8"))
    assert rel["jobs"]["deploy"]["uses"] == "./.github/workflows/deploy.yml"
