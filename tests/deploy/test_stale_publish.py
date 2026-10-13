"""낡은 publish 스텝 탐지 — 배포가 두 곳에서 도는 상태를 잡음.

run 스텝의 실제 publish 명령과 job·workflow 수준 `env:` 의 레지스트리 시크릿을 모두
봄. 접두 일치지 부분 문자열이 아님 — 그래야 오탐이 없음.
"""

from pathlib import Path

import pytest

from scripts.vdev_init_setup import (
    report_legacy_release_workflow,
)
from tests.deploy._helpers import (
    _MALFORMED_RELEASE_CASES,
    _RELEASE_NO_TAG_OUTPUT,
    _write_release_token_workflow,
)


def test_stale_publish_detects_real_cargo_publish_run_step(tmp_path: Path):
    """실제 step 의 run: 에 cargo publish 가 있으면(주석이 아니라) stale_publish 가
    잡고 [!] 안내가 나와야 함 — 오탐 회피가 진탐까지 죽이면 안 됨."""
    _write_release_token_workflow(
        tmp_path, extra_step="      - name: publish\n        run: cargo publish\n"
    )
    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert "cargo publish" in diag["stale_publish"]
    out = report_legacy_release_workflow(tmp_path)
    assert any("[!]" in ln and "cargo publish" in ln for ln in out)


def test_stale_publish_detects_real_registry_secret_env(tmp_path: Path):
    """step 의 env: 에 CARGO_REGISTRY_TOKEN 키가 있으면 stale_publish 가 잡아야 함."""
    _write_release_token_workflow(
        tmp_path,
        extra_step=(
            "      - name: publish\n"
            "        env:\n"
            "          CARGO_REGISTRY_TOKEN: ${{ secrets.CARGO_REGISTRY_TOKEN }}\n"
            "        run: echo noop\n"
        ),
    )
    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert "CARGO_REGISTRY_TOKEN" in diag["stale_publish"]
    out = report_legacy_release_workflow(tmp_path)
    assert any("[!]" in ln and "CARGO_REGISTRY_TOKEN" in ln for ln in out)


def test_stale_publish_guidance_orders_deploy_config_before_delete(tmp_path: Path):
    """release.yml 을 vdev-config.deploy 설정보다 먼저 지우면 발행이 조용히 멈춤 —
    안내는 (1) vdev-config.deploy 설정 → (2) release.yml 삭제/재실행 순서로 나와야 함.
    """
    _write_release_token_workflow(
        tmp_path, extra_step="      - name: publish\n        run: cargo publish\n"
    )
    out = report_legacy_release_workflow(tmp_path)
    joined = "\n".join(out)
    assert joined.index("vdev-config.deploy") < joined.index("release.yml")


def test_has_tag_output_false_when_release_job_missing_outputs(tmp_path: Path):
    """release job 에 outputs.tag 가 없으면 has_tag_output=False 이고 [!] 안내가 나옴."""
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(_RELEASE_NO_TAG_OUTPUT, encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert diag["has_tag_output"] is False
    out = report_legacy_release_workflow(tmp_path)
    assert any("[!]" in ln and "outputs.tag" in ln for ln in out)


def test_unparsable_release_yml_reports_nothing_alarming(tmp_path: Path):
    """FAIL-OPEN: YAML 파싱이 실패하면 legacy/stale_publish/has_tag_output/stale_level_channel/
    no_release_notes 전부 무경보이고 raise 하지 않는다(jobs: [oops 처럼 대괄호가 안 닫히면
    yaml.YAMLError)."""
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text("jobs: [oops\n", encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert diag == {
        "present": True,
        "legacy": False,
        "stale_publish": [],
        "has_tag_output": True,
        "stale_level_channel": False,
        "no_release_notes": False,
        "path": str(wf),
    }
    out = report_legacy_release_workflow(tmp_path)
    assert out == ["  [=] release 워크플로 RELEASE_TOKEN 방식 (OK)"]


@pytest.mark.parametrize("case", sorted(_MALFORMED_RELEASE_CASES))
def test_detect_legacy_release_workflow_never_raises_on_malformed_yaml(case: str, tmp_path: Path):
    """오타로 흔한 비정상 YAML(정수/불리언이 run:/uses:/steps:/jobs:/env: 에 들어간 경우)이
    스캔을 죽이면 안 된다(FAIL-OPEN, Critical finding 1)."""
    from scripts.vdev_init_setup import detect_legacy_release_workflow

    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(_MALFORMED_RELEASE_CASES[case], encoding="utf-8")

    diag = detect_legacy_release_workflow(tmp_path)  # raise 하면 이 테스트 자체가 실패
    assert diag["stale_publish"] == []
    if case == "job_value_not_dict":
        assert diag["has_tag_output"] is False
    else:
        assert diag["has_tag_output"] is True


def test_detect_legacy_release_workflow_never_raises_on_non_utf8_bytes(tmp_path: Path):
    """release.yml 전체가 비 UTF-8 바이트여도 raise 하지 않는다(기존 except 경로 회귀 방지)."""
    from scripts.vdev_init_setup import detect_legacy_release_workflow

    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_bytes(b"\xff")

    diag = detect_legacy_release_workflow(tmp_path)  # raise 하면 이 테스트 자체가 실패
    assert diag["stale_publish"] == []
    assert diag["has_tag_output"] is True


# 스크립트의 STALE_PUBLISH_* 상수가 tests/test_workflow_templates.py 의 니들셋과 실제로
# 달랐던 세 지점을 각각 회귀 테스트함(스크립트가 SSOT 가 된 뒤에도 값이 다시 갈라지면
# 여기서 잡힘).


def test_stale_publish_run_needle_catches_sonatype_credential_leak(tmp_path: Path):
    """run: 텍스트에 SONATYPE_ 로 시작하는 시크릿 참조가 있으면 잡아야 함 — env: 키로만
    검사하면 run: 안의 `$SONATYPE_USERNAME` 같은 사용이 무경보로 빠짐."""
    text = (
        "name: release\n"
        "jobs:\n"
        "  release:\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 20\n"
        "    outputs:\n"
        "      tag: ${{ steps.released.outputs.tag }}\n"
        "    steps:\n"
        "      - name: leak\n"
        '        run: curl -u "$SONATYPE_USERNAME" https://example.invalid\n'
        "      - id: released\n"
        '        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"\n'
    )
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert "SONATYPE_" in diag["stale_publish"]


def test_stale_publish_env_needle_catches_pgp_passphrase(tmp_path: Path):
    """step env: 의 PGP_PASSPHRASE 키를 잡아야 함 — PGP_SECRET 접두사만 보면
    PGP_PASSPHRASE 는 그 접두사로 시작하지 않아 무경보로 빠짐."""
    text = (
        "name: release\n"
        "jobs:\n"
        "  release:\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 20\n"
        "    outputs:\n"
        "      tag: ${{ steps.released.outputs.tag }}\n"
        "    steps:\n"
        "      - name: sign\n"
        "        env:\n"
        "          PGP_PASSPHRASE: ${{ secrets.PGP_PASSPHRASE }}\n"
        "        run: echo noop\n"
        "      - id: released\n"
        '        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"\n'
    )
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert "PGP_PASSPHRASE" in diag["stale_publish"]


def test_stale_publish_uses_matches_prefix_not_substring(tmp_path: Path):
    """`uses:` 는 접두사(startswith) 로만 매칭 — 우연히 부분 문자열을 포함할 뿐인
    무관한 액션(`myorg/composite-actions/setup-dotnet-wrapper@v1`)까지 잡는 `in` 매칭이면
    오탐이 늘어 가드가 신뢰를 잃음."""
    text = (
        "name: release\n"
        "jobs:\n"
        "  release:\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 20\n"
        "    outputs:\n"
        "      tag: ${{ steps.released.outputs.tag }}\n"
        "    steps:\n"
        "      - uses: myorg/composite-actions/setup-dotnet-wrapper@v1\n"
        "      - id: released\n"
        '        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"\n'
    )
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert "actions/setup-dotnet" not in diag["stale_publish"]


# step 의 env: 만 보면, 손으로 만든 release.yml 이 job 이나 워크플로 최상위에
# 시크릿을 주입할 때 조용히 통과함.


def test_stale_publish_detects_job_level_env_secret(tmp_path: Path):
    """jobs.<id>.env 에 시크릿이 있으면(스텝이 아니라 job 레벨) stale_publish 가 잡아야 함."""
    text = (
        "name: release\n"
        "jobs:\n"
        "  release:\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 20\n"
        "    outputs:\n"
        "      tag: ${{ steps.released.outputs.tag }}\n"
        "    env:\n"
        "      CARGO_REGISTRY_TOKEN: ${{ secrets.CARGO_REGISTRY_TOKEN }}\n"
        "    steps:\n"
        "      - id: released\n"
        '        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"\n'
    )
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert "CARGO_REGISTRY_TOKEN" in diag["stale_publish"]
    out = report_legacy_release_workflow(tmp_path)
    assert any("[!]" in ln and "CARGO_REGISTRY_TOKEN" in ln for ln in out)


def test_stale_publish_detects_workflow_level_env_secret(tmp_path: Path):
    """최상위 env: 에 시크릿이 있으면(job/step 이 아니라 워크플로 전체) stale_publish 가
    잡아야 함."""
    text = (
        "name: release\n"
        "env:\n"
        "  PGP_SECRET: ${{ secrets.PGP_SECRET }}\n"
        "jobs:\n"
        "  release:\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 20\n"
        "    outputs:\n"
        "      tag: ${{ steps.released.outputs.tag }}\n"
        "    steps:\n"
        "      - id: released\n"
        '        run: echo "tag=v1.0.0" >> "$GITHUB_OUTPUT"\n'
    )
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text, encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert "PGP_SECRET" in diag["stale_publish"]
    out = report_legacy_release_workflow(tmp_path)
    assert any("[!]" in ln and "PGP_SECRET" in ln for ln in out)


def test_has_tag_output_false_when_release_job_value_not_dict(tmp_path: Path):
    """release job 의 값이 dict 가 아니면(예: `release: "not-a-dict"`) wire_release_deploy
    는 배선을 거부. has_tag_output 도 False 를 반환해야 진단과 배선 판정이 일치 —
    후보 0 개로 판단해 True(OK)를 말하면 어긋남."""
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text('jobs:\n  release: "not-a-dict"\n', encoding="utf-8")

    from scripts.vdev_init_setup import detect_legacy_release_workflow

    diag = detect_legacy_release_workflow(tmp_path)
    assert diag["has_tag_output"] is False
    out = report_legacy_release_workflow(tmp_path)
    assert any("[!]" in ln and "outputs.tag" in ln for ln in out)
