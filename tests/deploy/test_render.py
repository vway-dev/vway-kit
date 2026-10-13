"""deploy 워크플로 렌더 — 오케스트레이터와 needs 사슬.

`order` 가 needs 사슬이 됨. 스칼라·맨 문자열·중복은 순환을 만들지 않고 무시되거나
합쳐짐. 렌더는 멱등이고 기존 파일을 파괴하지 않음.
"""

from pathlib import Path

from scripts.vdev_init_setup import (
    DEPLOY_RESOLVE_JOB,
    render_deploy_workflows,
)
from tests.deploy._helpers import (
    PLUGIN,
    _render,
)


def test_render_skips_when_absent(tmp_path: Path):
    lines = render_deploy_workflows(tmp_path, PLUGIN)
    assert lines == ["  [=] deploy 미설정 — 배포 워크플로 skip"]
    assert not (tmp_path / ".github" / "workflows" / "deploy.yml").exists()


def test_render_skips_when_disabled(tmp_path: Path):
    lines, doc = _render(tmp_path, {"enable": False, "targets": [{"target": "pypi"}]})
    assert doc is None
    assert any("enable=false" in line for line in lines)


def test_render_skips_when_no_target_survives(tmp_path: Path):
    """빈 jobs: 는 GitHub Actions 에러라 파일을 쓰지 않음."""
    lines, doc = _render(tmp_path, {"enable": True, "targets": [{"target": "gems"}]})
    assert doc is None
    assert any("실행 가능한 deploy.targets" in line for line in lines)


def test_render_skips_when_only_target_is_reserved_resolve(tmp_path: Path):
    """타깃이 전부 `resolve` 예약어면(_deploy_targets 가 모두 드롭) 생존 job 이 0개라
    빈 jobs: 를 피하려고 deploy.yml 을 쓰지 않는다(GitHub Actions 에러 방지)."""
    lines, doc = _render(
        tmp_path, {"enable": True, "targets": [{"name": "resolve", "target": "pypi"}]}
    )
    assert doc is None
    assert any("실행 가능한 deploy.targets" in line for line in lines)
    assert any("예약어" in line and DEPLOY_RESOLVE_JOB in line for line in lines)


def test_render_drops_reserved_resolve_but_keeps_valid_target(tmp_path: Path):
    """`resolve` 예약어 타깃은 드롭되고 나머지 유효 타깃만으로 deploy.yml 이 생성됨.

    jobs.resolve 는 여전히 진짜 resolver(steps/outputs.tag 를 가진, uses: 없는 job)여야
    함 — caller job 으로 덮이면 self-cycle(needs: [resolve] 가 사라진 자기 outputs 를
    참조)이 생겨 GitHub Actions 가 워크플로 로드를 거부함.
    """
    lines, doc = _render(
        tmp_path,
        {
            "enable": True,
            "targets": [
                {"name": "resolve", "target": "pypi"},
                {"name": "p", "target": "pypi"},
            ],
        },
    )
    assert doc is not None
    assert set(doc["jobs"]) == {"resolve", "p"}
    resolver = doc["jobs"]["resolve"]
    assert "steps" in resolver
    assert resolver.get("outputs", {}).get("tag") == "${{ steps.resolved.outputs.tag }}"
    assert "uses" not in resolver
    assert any("예약어" in line and DEPLOY_RESOLVE_JOB in line for line in lines)


def test_render_copies_only_used_components(tmp_path: Path):
    _render(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    wf = tmp_path / ".github" / "workflows"
    assert (wf / "deploy-pypi.yml").is_file()
    assert not (wf / "deploy-ghcr.yml").exists()
    # 정적 복사 — 치환 토큰이 남아 있지 않음(애초에 없음)
    assert "__VWAY_" not in (wf / "deploy-pypi.yml").read_text(encoding="utf-8")


def test_orchestrator_shape(tmp_path: Path):
    _, doc = _render(
        tmp_path,
        {
            "enable": True,
            "targets": [
                {"name": "p", "target": "pypi", "build": "uv build"},
                {
                    "name": "img",
                    "target": "ghcr",
                    "image": "ghcr.io/o/r/api",
                    "context": "services/api",
                },
            ],
        },
    )
    # safe_dump 는 문자열 "on" 을 따옴표 처리하므로 되읽으면 문자열 키
    on = doc["on"]
    assert on["workflow_call"]["inputs"]["tag"]["required"] is True
    assert on["workflow_call"]["inputs"]["target"]["default"] == "all"
    assert on["workflow_dispatch"]["inputs"]["target"]["default"] == "all"
    assert on["workflow_dispatch"]["inputs"]["tag"]["required"] is False

    resolve = doc["jobs"]["resolve"]
    assert resolve["timeout-minutes"] == 5
    assert resolve["steps"][0]["if"] == "github.event_name == 'workflow_dispatch'"
    assert "exit 1" in resolve["steps"][1]["run"]

    p = doc["jobs"]["p"]
    assert "timeout-minutes" not in p, "uses: 호출 job 에는 timeout-minutes 를 달 수 없다"
    assert p["uses"] == "./.github/workflows/deploy-pypi.yml"
    assert p["secrets"] == "inherit"
    assert p["needs"] == ["resolve"]
    assert p["if"] == "inputs.target == 'all' || inputs.target == 'p'"
    # pypi 는 auth 를 명시하지 않았으므로 기본값 token 이 적용된다(재사용 워크플로에서
    # PyPI trusted publishing 미지원 — pypa/warehouse#11096) → id-token 미부여.
    assert p["permissions"] == {"contents": "read"}
    assert p["with"]["tag"] == "${{ needs.resolve.outputs.tag }}"
    assert p["with"]["auth"] == "token"

    img = doc["jobs"]["img"]
    assert img["permissions"] == {"contents": "read", "packages": "write"}
    assert img["with"]["dockerfile"] == "services/api/Dockerfile"


def test_orchestrator_target_declared_in_both_on_blocks(tmp_path: Path):
    """한쪽에만 선언하면 릴리스 경로에서 inputs.target 이 비어 모든 job 이 조용히 스킵됨."""
    _, doc = _render(tmp_path, {"enable": True, "targets": [{"name": "p", "target": "pypi"}]})
    for trigger in ("workflow_call", "workflow_dispatch"):
        assert doc["on"][trigger]["inputs"]["target"]["default"] == "all"


def test_order_becomes_needs_chain(tmp_path: Path):
    _, doc = _render(
        tmp_path,
        {
            "enable": True,
            "order": ["p", "img"],
            "targets": [
                {"name": "p", "target": "pypi"},
                {"name": "img", "target": "ghcr", "image": "x"},
            ],
        },
    )
    assert doc["jobs"]["p"]["needs"] == ["resolve"]
    assert doc["jobs"]["img"]["needs"] == ["resolve", "p"]


def test_order_non_list_scalar_is_ignored_not_raised(tmp_path: Path):
    """deploy.order: 5 처럼 스칼라를 쓰면 TypeError 로 죽지 않고(FAIL-OPEN),
    순서 없이(모두 resolve 만 needs) deploy.yml 이 정상 생성되며 [!] 노트가 남음."""
    lines, doc = _render(
        tmp_path,
        {
            "enable": True,
            "order": 5,
            "targets": [
                {"name": "p", "target": "pypi"},
                {"name": "img", "target": "ghcr", "image": "x"},
            ],
        },
    )
    assert doc is not None
    assert doc["jobs"]["p"]["needs"] == ["resolve"]
    assert doc["jobs"]["img"]["needs"] == ["resolve"]
    assert any("[!]" in line and "order" in line for line in lines)


def test_order_bare_string_is_ignored_not_iterated_as_chars(tmp_path: Path):
    """문자열은 순회 가능하지만(글자 단위) order 로는 무효 — 글자 단위로 몰래
    이름과 매치되어 잘못된 needs 가 생기면 안 됨."""
    lines, doc = _render(
        tmp_path,
        {
            "enable": True,
            "order": "p",
            "targets": [
                {"name": "p", "target": "pypi"},
                {"name": "img", "target": "ghcr", "image": "x"},
            ],
        },
    )
    assert doc is not None
    assert doc["jobs"]["p"]["needs"] == ["resolve"]
    assert doc["jobs"]["img"]["needs"] == ["resolve"]
    assert any("[!]" in line and "order" in line for line in lines)


def test_order_duplicate_entries_are_deduplicated(tmp_path: Path):
    """order 에 중복 항목이 있으면 자기참조(needs 자기 자신)가 생기면 안 됨."""
    _, doc = _render(
        tmp_path,
        {
            "enable": True,
            "order": ["p", "p", "img"],
            "targets": [
                {"name": "p", "target": "pypi"},
                {"name": "img", "target": "ghcr", "image": "x"},
            ],
        },
    )
    assert doc["jobs"]["p"]["needs"] == ["resolve"]
    assert doc["jobs"]["img"]["needs"] == ["resolve", "p"]


def test_order_duplicate_entries_do_not_create_cycle(tmp_path: Path):
    """order 에 중복 항목이 있으면 순환 needs(p<->img)가 생기면 안 됨."""
    _, doc = _render(
        tmp_path,
        {
            "enable": True,
            "order": ["p", "img", "p"],
            "targets": [
                {"name": "p", "target": "pypi"},
                {"name": "img", "target": "ghcr", "image": "x"},
            ],
        },
    )
    assert doc["jobs"]["p"]["needs"] == ["resolve"]
    assert doc["jobs"]["img"]["needs"] == ["resolve", "p"]


def test_same_target_twice_shares_one_component_file(tmp_path: Path):
    _, doc = _render(
        tmp_path,
        {
            "enable": True,
            "targets": [
                {
                    "name": "api",
                    "target": "ghcr",
                    "image": "ghcr.io/o/r/api",
                    "context": "services/api",
                },
                {
                    "name": "web",
                    "target": "ghcr",
                    "image": "ghcr.io/o/r/web",
                    "context": "services/web",
                },
            ],
        },
    )
    assert set(doc["jobs"]) == {"resolve", "api", "web"}
    assert doc["jobs"]["api"]["uses"] == doc["jobs"]["web"]["uses"]
    assert (tmp_path / ".github" / "workflows" / "deploy-ghcr.yml").is_file()


def test_render_is_idempotent_and_non_destructive(tmp_path: Path):
    cfg = {"enable": True, "targets": [{"name": "p", "target": "pypi"}]}
    _render(tmp_path, cfg)
    dest = tmp_path / ".github" / "workflows" / "deploy.yml"
    dest.write_text("# 사람이 고친 파일\n", encoding="utf-8")
    lines, _ = _render(tmp_path, cfg)
    assert dest.read_text(encoding="utf-8") == "# 사람이 고친 파일\n"
    assert any("이미 있어" in line for line in lines)
