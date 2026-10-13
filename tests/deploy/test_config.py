"""`vdev-config.deploy` 읽기와 타깃 검증.

모르는 타깃·예약 이름·필수 값 누락은 그 타깃만 버리고 나머지는 렌더함. PyPI 신뢰발행은
재사용 워크플로에서 안 되므로 명시됐을 때 경고하되 타깃은 남김.
"""

from pathlib import Path

import pytest
import yaml as _yaml

from scripts.vdev_init_setup import (
    DEPLOY_RESOLVE_JOB,
    DEPLOY_TEMPLATE_BY_TARGET,
    _caller_with,
    _deploy_permission_union,
    _deploy_permissions,
    _deploy_targets,
    load_deploy_config,
    render_deploy_workflows,
)
from tests.deploy._helpers import (
    PLUGIN,
    _write_deploy_config,
)


def test_load_deploy_config_absent(tmp_path: Path):
    assert load_deploy_config(tmp_path) is None


def test_load_deploy_config_unparsable(tmp_path: Path):
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-config.yaml").write_text("deploy: [oops\n", encoding="utf-8")
    assert load_deploy_config(tmp_path) is None  # FAIL-OPEN


def test_load_deploy_config_present(tmp_path: Path):
    _write_deploy_config(tmp_path, {"enable": True, "targets": []})
    assert load_deploy_config(tmp_path) == {"enable": True, "targets": []}


def test_deploy_targets_drops_unknown_target(tmp_path: Path):
    items, notes = _deploy_targets([{"name": "x", "target": "gems"}], tmp_path)
    assert items == []
    assert any("gems" in n and "[!]" in n for n in notes)


def test_deploy_targets_drops_reserved_resolve_name(tmp_path: Path):
    """`resolve` 는 오케스트레이터의 태그 해석 job 이 이미 쓰는 예약어라 드롭됨.

    공백만 다른 `"  resolve  "` 도 strip 후 비교라 드롭됨. **대소문자는 구분**
    (DEPLOY_RESOLVE_JOB 의 주석과 동일한 근거 — GitHub Actions job id 는 case-sensitive
    라 `resolve`와 `RESOLVE`는 별개의 id 다) — 그래서 `RESOLVE` 는 충돌 없이 생존해야 함.
    """
    items, notes = _deploy_targets(
        [
            {"name": "resolve", "target": "pypi"},
            {"name": "  resolve  ", "target": "npm"},
            {"name": "RESOLVE", "target": "cratesio"},
        ],
        tmp_path,
    )
    assert [i["name"] for i in items] == ["RESOLVE"]
    reserved_notes = [n for n in notes if "[!]" in n and DEPLOY_RESOLVE_JOB in n]
    assert len(reserved_notes) == 2, notes


def test_deploy_targets_normalizes_case_and_fills_name(tmp_path: Path):
    items, _ = _deploy_targets([{"target": "PyPI"}, {"target": "npm"}], tmp_path)
    assert [(i["name"], i["target"]) for i in items] == [("job-1", "pypi"), ("job-2", "npm")]


def test_deploy_targets_requires_ghcr_image(tmp_path: Path):
    items, notes = _deploy_targets([{"name": "img", "target": "ghcr"}], tmp_path)
    assert items == []
    assert any("image" in n for n in notes)


def test_deploy_targets_requires_maven_publish_and_build_tool(tmp_path: Path):
    items, notes = _deploy_targets(
        [{"name": "c", "target": "maven-central", "build_tool": "sbt"}], tmp_path
    )
    assert items == []
    assert any("publish" in n for n in notes)


def test_deploy_targets_custom_requires_existing_workflow(tmp_path: Path):
    items, notes = _deploy_targets(
        [{"name": "ecs", "target": "custom", "workflow": "./.github/workflows/deploy-ecs.yml"}],
        tmp_path,
    )
    assert items == []
    assert any("deploy-ecs.yml" in n for n in notes)

    wf = tmp_path / ".github" / "workflows" / "deploy-ecs.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: ecs\n", encoding="utf-8")
    items, _ = _deploy_targets(
        [{"name": "ecs", "target": "custom", "workflow": "./.github/workflows/deploy-ecs.yml"}],
        tmp_path,
    )
    assert [i["name"] for i in items] == ["ecs"]


def test_deploy_targets_custom_normalizes_workflow_prefix(tmp_path: Path):
    """workflow: 값에 './' 프리픽스가 없으면 보강되고, 있으면 그대로, 공백은 strip 됨."""
    wf = tmp_path / ".github" / "workflows" / "deploy-ecs.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: ecs\n", encoding="utf-8")

    items, _ = _deploy_targets(
        [{"name": "ecs", "target": "custom", "workflow": ".github/workflows/deploy-ecs.yml"}],
        tmp_path,
    )
    assert items[0]["workflow"] == "./.github/workflows/deploy-ecs.yml"

    items, _ = _deploy_targets(
        [{"name": "ecs", "target": "custom", "workflow": "./.github/workflows/deploy-ecs.yml"}],
        tmp_path,
    )
    assert items[0]["workflow"] == "./.github/workflows/deploy-ecs.yml"

    items, _ = _deploy_targets(
        [{"name": "ecs", "target": "custom", "workflow": "  .github/workflows/deploy-ecs.yml  "}],
        tmp_path,
    )
    assert items[0]["workflow"] == "./.github/workflows/deploy-ecs.yml"


def test_deploy_targets_custom_rejects_absolute_and_traversal(tmp_path: Path):
    """절대경로/상위 디렉터리 이동 가드가 실제로 발동했음을 증명함.

    `tmp_path` 는 Windows 에서 여러 단계 깊이라 `../../etc/passwd` 가 존재하지 않는
    경로로 resolve 될 수 있어, 가드 없이도 기존 "파일 없음" 분기가 같은 부분 문자열을
    포함한 `[!]` 노트를 내놓아 테스트가 통과해버릴 수 있음(vacuous). 가드 분기의
    구분되는 문구(`절대경로이거나 상위 디렉터리로 이동해 제외`)로 특정해 가드가
    실제로 발동했는지 증명함(누락-파일 분기의 `가 없어 제외` 와 구분).
    """
    items, notes = _deploy_targets(
        [
            {"name": "abs", "target": "custom", "workflow": "/etc/passwd"},
            {"name": "trav", "target": "custom", "workflow": "../../etc/passwd"},
            {"name": "ok", "target": "pypi"},
        ],
        tmp_path,
    )
    assert [i["name"] for i in items] == ["ok"]
    guard_text = "절대경로이거나 상위 디렉터리로 이동해 제외"
    abs_notes = [n for n in notes if "/etc/passwd" in n and "../../etc/passwd" not in n]
    trav_notes = [n for n in notes if "../../etc/passwd" in n]
    assert any(guard_text in n for n in abs_notes), abs_notes
    assert any(guard_text in n for n in trav_notes), trav_notes
    assert not any("가 없어 제외" in n for n in abs_notes + trav_notes)


def test_deploy_targets_duplicate_name_warns_but_keeps(tmp_path: Path):
    items, notes = _deploy_targets(
        [{"name": "a", "target": "pypi"}, {"name": "a", "target": "npm"}], tmp_path
    )
    assert len(items) == 2
    assert any("중복" in n for n in notes)


def test_deploy_targets_warns_on_explicit_pypi_oidc_but_keeps_target(tmp_path: Path):
    """pypi + auth: oidc 는 재사용 워크플로에서 동작하지 않지만(pypa/warehouse#11096)
    드롭하지 않음 — 소비자가 업스트림 수정을 앞서 추적 중일 수 있음."""
    items, notes = _deploy_targets([{"name": "p", "target": "pypi", "auth": "oidc"}], tmp_path)
    assert [i["name"] for i in items] == ["p"]
    assert any("[!]" in n and "pypi" in n and "oidc" in n for n in notes)


def test_deploy_targets_no_warning_when_pypi_auth_absent_or_token(tmp_path: Path):
    """auth 미지정(기본 token)과 명시적 token 은 경고를 내지 않음."""
    items, notes = _deploy_targets(
        [
            {"name": "p1", "target": "pypi"},
            {"name": "p2", "target": "pypi", "auth": "token"},
            {"name": "n", "target": "npm", "auth": "oidc"},
        ],
        tmp_path,
    )
    assert [i["name"] for i in items] == ["p1", "p2", "n"]
    assert not any("[!]" in n and "oidc" in n for n in notes)


def test_deploy_targets_custom_rejects_invalid_permission_value(tmp_path: Path):
    """permissions 값이 read/write/none 밖(YAML 불리언 등)이면 드롭 + [!] 로 키를 짚음.

    `contents: yes` 를 사람이 손으로 쓰면 raw YAML 이 이를 불리언 True 로 파싱함 —
    `_deploy_targets` 가 이를 걸러내지 않으면 caller job 의 permissions: 에 따옴표 없는
    `true` 가 그대로 새어나감(재파싱 게이트는 jobs.deploy.uses 만 보므로 못 잡음).
    """
    wf = tmp_path / ".github" / "workflows" / "deploy-ecs.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: ecs\n", encoding="utf-8")
    items, notes = _deploy_targets(
        [
            {
                "name": "ecs",
                "target": "custom",
                "workflow": "./.github/workflows/deploy-ecs.yml",
                "permissions": {"contents": True, "id-token": "write"},
            }
        ],
        tmp_path,
    )
    assert items[0]["permissions"] == {"id-token": "write"}
    assert any("[!]" in n and "contents" in n for n in notes)


def test_deploy_targets_custom_invalid_permission_still_emits_parsable_block(tmp_path: Path):
    """드롭 후에도 나머지 permissions 로 렌더된 deploy.yml 이 여전히 유효 YAML 임."""
    wf = tmp_path / ".github" / "workflows" / "deploy-ecs.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: ecs\n", encoding="utf-8")
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-config.yaml").write_text(
        "deploy:\n"
        "  enable: true\n"
        "  targets:\n"
        "    - name: ecs\n"
        "      target: custom\n"
        "      workflow: ./.github/workflows/deploy-ecs.yml\n"
        "      permissions:\n"
        "        contents: yes\n"
        "        id-token: write\n",
        encoding="utf-8",
    )
    render_deploy_workflows(tmp_path, PLUGIN)
    dest = tmp_path / ".github" / "workflows" / "deploy.yml"
    doc = _yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert doc["jobs"]["ecs"]["permissions"] == {"contents": "read", "id-token": "write"}


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"target": "pypi", "auth": "oidc"}, {"contents": "read", "id-token": "write"}),
        ({"target": "pypi", "auth": "token"}, {"contents": "read"}),
        # auth 기본값은 타깃별(DEPLOY_DEFAULT_AUTH) — pypi 는 재사용 워크플로에서 trusted
        # publishing 이 동작하지 않아(pypa/warehouse#11096) token 이 기본임.
        ({"target": "pypi"}, {"contents": "read"}),  # auth 기본 token
        ({"target": "npm"}, {"contents": "read", "id-token": "write"}),  # auth 기본 oidc
        ({"target": "cratesio"}, {"contents": "read", "id-token": "write"}),  # auth 기본 oidc
        ({"target": "maven-central"}, {"contents": "read"}),
        ({"target": "ghcr"}, {"contents": "read", "packages": "write"}),
        (
            {"target": "custom", "permissions": {"id-token": "write"}},
            {"contents": "read", "id-token": "write"},
        ),
    ],
)
def test_deploy_permissions(item, expected):
    assert _deploy_permissions(item) == expected


def test_deploy_permission_union_never_downgrades_contents_seed():
    """custom 타깃이 contents: none 을 선언해도 시드 contents: read 밑으로 못 내려감.

    write 만 dominant 로 취급하면 union.get(key)=="read" 인데 새 값이 "none"
    이면 그냥 덮어씀 — spec 은 contents: read 가 항상 있어야 한다고 명시함. custom 을
    **뒤에** 둠 — 앞에 두면 이어지는 pypi 항목의 contents: read 가 우연히 다시 덮어써
    버그가 가려짐(order-dependent vacuous pass 방지).
    """
    items = [
        {"target": "pypi", "auth": "token"},
        {"target": "custom", "permissions": {"contents": "none"}},
    ]
    assert _deploy_permission_union(items)["contents"] == "read"


def test_deploy_permission_union_keeps_custom_write_upgrade():
    """custom 이 contents: write 를 선언하면(더 넓음) 그대로 유지된다(다운그레이드 방지와 대칭)."""
    items = [{"target": "custom", "permissions": {"contents": "write"}}]
    assert _deploy_permission_union(items)["contents"] == "write"


def test_caller_with_drops_empty_values():
    """빈 값을 with 로 넘기면 컴포넌트 input 의 default 가 억제됨."""
    got = _caller_with({"name": "p", "target": "pypi", "version": "", "build": "uv build"})
    # pypi 의 auth 기본값은 token(DEPLOY_DEFAULT_AUTH — 재사용 워크플로 OIDC 미지원).
    assert got == {"tag": "${{ needs.resolve.outputs.tag }}", "build": "uv build", "auth": "token"}


def test_caller_with_default_auth_is_per_target():
    """auth 기본값은 타깃별로 다름 — pypi 는 token, npm/cratesio 는 oidc."""
    assert _caller_with({"name": "p", "target": "pypi"})["auth"] == "token"
    assert _caller_with({"name": "n", "target": "npm"})["auth"] == "oidc"
    assert _caller_with({"name": "c", "target": "cratesio"})["auth"] == "oidc"


def test_caller_with_normalizes_auth_case():
    """_deploy_permissions 와 동일한 파생 상태를 보여야 함 — with: 에 원문 케이스가 새면 안 됨."""
    got = _caller_with({"name": "p", "target": "pypi", "auth": "OIDC"})
    assert got["auth"] == "oidc"


def test_caller_with_ghcr_fills_defaults():
    got = _caller_with({"name": "i", "target": "ghcr", "image": "ghcr.io/o/r/api"})
    assert got["context"] == "."
    assert got["dockerfile"] == "Dockerfile"

    got = _caller_with({"name": "i", "target": "ghcr", "image": "x", "context": "services/api"})
    assert got["dockerfile"] == "services/api/Dockerfile"


def test_deploy_template_by_target_files_exist():
    for target, rel in DEPLOY_TEMPLATE_BY_TARGET.items():
        assert (PLUGIN / rel).is_file(), f"{target}: {rel} 없음"
