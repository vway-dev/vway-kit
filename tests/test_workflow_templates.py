"""워크플로 템플릿 불변식 — 모든 job 에 timeout-minutes 가 있어야 함.

소비자가 /vdev-init 으로 렌더받아 실제 CI 에서 돌리는 템플릿. timeout 이 없으면
hang 시 GitHub 기본 상한(360분)까지 CI minutes 를 태움. 새 템플릿을 추가하면
EXPECTED_TIMEOUTS 에 등록해야 통과(누락 방지 가드).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.vdev_init_setup import (
    STALE_PUBLISH_ENV_NEEDLES,
    STALE_PUBLISH_RUN_NEEDLES,
    STALE_PUBLISH_USES_PREFIXES,
)

PLUGIN = Path(__file__).resolve().parent.parent  # repo root == 플러그인 루트
TEMPLATE_DIR = PLUGIN / "github"

# 파일명 → 기대 timeout-minutes. 정적 값(int) 또는 config 구동 토큰(str).
# 6종 release 템플릿은 모두 20 — 버전 계산 + 태그 + GitHub Release 만 하기 때문.
# 빌드(mvn package)·발행(sbt ci-release, cargo publish)은 deploy 컴포넌트 몫이고
# 그 비용은 deploy.* 템플릿의 timeout 이 흡수함(maven-central 45 등).
EXPECTED_TIMEOUTS: dict[str, int | str] = {
    "api-contract.workflow.example.yml": 15,
    "branch-naming.workflow.example.yml": 5,
    "entropy-check.workflow.example.yml": 10,
    "release.cargo-release.workflow.example.yml": 20,
    "release.gitversion.workflow.example.yml": 20,
    "release.jreleaser.workflow.example.yml": 20,
    "release.python-semantic-release.workflow.example.yml": 20,
    "release.sbt-ci-release.workflow.example.yml": 20,
    "release.semantic-release.workflow.example.yml": 20,
    # unit-test 는 config(unit_test.timeout_minutes) 구동이라 토큰이 그대로 남음.
    "unit-test.workflow.example.yml": "__VWAY_TIMEOUT__",
    "wiki-verify.workflow.example.yml": 5,
    "srs-verify.workflow.example.yml": 5,
    "doc-style.workflow.example.yml": 5,
    # 브라우저 스위트는 의존성·브라우저 설치 + 스택 기동 + 실행이라 다른 검사보다 김.
    "e2e.workflow.example.yml": 45,
    "deploy.pypi.workflow.example.yml": 10,
    "deploy.npm.workflow.example.yml": 15,
    "deploy.cratesio.workflow.example.yml": 20,
    "deploy.maven-central.workflow.example.yml": 45,
    "deploy.ghcr.workflow.example.yml": 30,
}


# 파일시스템에서 파생 — 하드코딩 튜플이면 컴포넌트 추가를 깜빡했을 때
# test_deploy_components_are_workflow_call_only 등이 빈 이터러블로 공허하게 통과함.
DEPLOY_COMPONENTS = tuple(
    sorted(p.name for p in TEMPLATE_DIR.glob("deploy.*.workflow.example.yml"))
)
assert DEPLOY_COMPONENTS == (
    "deploy.cratesio.workflow.example.yml",
    "deploy.ghcr.workflow.example.yml",
    "deploy.maven-central.workflow.example.yml",
    "deploy.npm.workflow.example.yml",
    "deploy.pypi.workflow.example.yml",
), f"deploy 컴포넌트 목록이 기대와 다르다: {DEPLOY_COMPONENTS}"


def _on_block(data: dict) -> dict:
    """손으로 쓴 템플릿의 맨 `on:` 은 YAML 1.1 규칙상 bool True 키로 파싱됨."""
    on = data.get("on", data.get(True))
    assert isinstance(on, dict), f"on: 블록이 없거나 파싱되지 않았다: {on!r}"
    return on


def _templates() -> list[Path]:
    return sorted(TEMPLATE_DIR.glob("*.workflow.example.yml"))


def test_every_template_is_registered():
    """새 템플릿을 EXPECTED_TIMEOUTS 등록 없이 추가하면 실패함."""
    names = {p.name for p in _templates()}
    missing = names - set(EXPECTED_TIMEOUTS)
    orphan = set(EXPECTED_TIMEOUTS) - names
    assert not missing and not orphan, f"미등록={missing} 파일없음={orphan}"


def test_every_job_has_expected_timeout():
    """모든 템플릿의 모든 job 에 기대 timeout-minutes 가 있음."""
    for path in _templates():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "jobs" in data, f"{path.name}: jobs: 키 없음"
        jobs = data["jobs"]
        assert jobs, f"{path.name}: jobs 없음"
        assert path.name in EXPECTED_TIMEOUTS, f"{path.name}: EXPECTED_TIMEOUTS 미등록"
        for job_name, job in jobs.items():
            assert "timeout-minutes" in job, f"{path.name}:{job_name} timeout-minutes 누락"
            assert job["timeout-minutes"] == EXPECTED_TIMEOUTS[path.name], (
                f"{path.name}:{job_name} timeout={job['timeout-minutes']!r}"
            )


def test_unit_test_template_gates_official_setup_actions():
    """언어별 공식 setup action 이 if: matrix.language 로 게이팅되고,
    표에 없는 언어는 matrix.setup 셸 이스케이프 해치가 전담함."""
    path = TEMPLATE_DIR / "unit-test.workflow.example.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = data["jobs"]["unit-test"]

    # 한 모듈이 실패해도 나머지 모듈 테스트는 계속 돌아감
    assert job["strategy"]["fail-fast"] is False
    # matrix.include 는 렌더 시점에 치환됨(순수 치환 — 템플릿엔 토큰만)
    assert job["strategy"]["matrix"]["include"] == "__VWAY_MATRIX_INCLUDE__"

    gated = {s["if"]: s.get("uses") for s in job["steps"] if "if" in s}
    assert gated["matrix.language == 'python'"] == "actions/setup-python@v6"
    assert gated["matrix.language == 'node'"] == "actions/setup-node@v6"
    assert gated["matrix.language == 'java'"] == "actions/setup-java@v6"
    assert gated["matrix.language == 'go'"] == "actions/setup-go@v6"
    assert gated["matrix.language == 'rust'"] == "dtolnay/rust-toolchain@stable"
    # 이스케이프 해치 — 공식 action 5종 밖 언어(scala/c# 등)는 setup 셸이 전담
    assert "matrix.setup != ''" in gated

    # setup/test 값은 run: 에 직접 보간하지 않고 env: 로 넘김(따옴표/개행 보존 +
    # actionlint/zizmor 템플릿 인젝션 린트 회피) — eval 로 &&/파이프/리다이렉션을 보존함.
    setup_step = next(s for s in job["steps"] if s.get("if") == "matrix.setup != ''")
    assert setup_step["env"]["VWAY_SETUP"] == "${{ matrix.setup }}"
    assert setup_step["run"] == 'eval "$VWAY_SETUP"'

    # 마지막 스텝은 테스트 실행 — 동일하게 env 경유
    last = job["steps"][-1]
    assert last["env"]["VWAY_TEST"] == "${{ matrix.test }}"
    assert last["run"] == 'eval "$VWAY_TEST"'


def _release_steps(path):
    """release 템플릿의 모든 job 의 모든 step(dict)을 훑음."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job in data["jobs"].values():
        yield from job.get("steps", [])


def test_release_templates_have_no_build_or_publish():
    """릴리스 워크플로는 버전·태그·GitHub Release 만 함 — 빌드/레지스트리 발행 금지.

    주석은 금지 문자열을 설명에 쓸 수 있으므로 파싱된 스텝만 검사함. 니들셋은 여기서
    다시 정의하지 않음 — `scripts/vdev_init_setup.py::detect_legacy_release_workflow`
    가 SSOT(rule-dry-constants). 이 테스트와 그 진단 로직이 각자 니들을 하드코딩하면
    반드시 드리프트함(Important finding 2 — 실제로 PGP_PASSPHRASE 누락·`uses:` 매칭
    방식 불일치로 드리프트한 전례). 매칭 방식도 스크립트와 동일해야 함: run 은
    부분일치(in), uses/env 키는 접두사(startswith).
    """
    for path in sorted(TEMPLATE_DIR.glob("release.*.workflow.example.yml")):
        for step in _release_steps(path):
            run = step.get("run", "")
            for needle in STALE_PUBLISH_RUN_NEEDLES:
                assert needle not in run, f"{path.name}: run 에 '{needle}' 잔존"
            uses = step.get("uses", "")
            for prefix in STALE_PUBLISH_USES_PREFIXES:
                assert not uses.startswith(prefix), f"{path.name}: {prefix} 잔존"
            for key in step.get("env", {}):
                for needle in STALE_PUBLISH_ENV_NEEDLES:
                    assert not str(key).startswith(needle), f"{path.name}: env.{key} 잔존"

    cargo = TEMPLATE_DIR / "release.cargo-release.workflow.example.yml"
    calls = [
        s["run"] for s in _release_steps(cargo) if s.get("run", "").startswith("cargo release")
    ]
    assert calls, "cargo release 호출을 찾지 못했다"
    for call in calls:
        assert "--no-publish" in call, f"cargo release 호출에 --no-publish 누락: {call!r}"

    jre = TEMPLATE_DIR / "release.jreleaser.workflow.example.yml"
    assert not any(
        s.get("uses", "").startswith("actions/setup-java") for s in _release_steps(jre)
    ), "jreleaser/release-action 의 setup-java 입력 기본값이 true 라 스스로 Java 를 깐다"


def test_release_templates_expose_tag_output():
    """6종 릴리스 템플릿이 jobs.release.outputs.tag 를 선언함(스킵이면 빈 문자열)."""
    for path in sorted(TEMPLATE_DIR.glob("release.*.workflow.example.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        job = data["jobs"]["release"]
        assert job.get("outputs", {}).get("tag") == "${{ steps.released.outputs.tag }}", (
            f"{path.name}: jobs.release.outputs.tag 누락"
        )
        step_ids = [s.get("id") for s in job["steps"]]
        assert "pretag" in step_ids, f"{path.name}: pretag 스텝 없음"
        assert "released" in step_ids, f"{path.name}: released 스텝 없음"
        assert step_ids.index("pretag") < step_ids.index("released")

        released = next(s for s in job["steps"] if s.get("id") == "released")
        assert "git fetch --tags --force" in released["run"], (
            f"{path.name}: fetch 없이 git describe 하면 jreleaser 처럼 원격에서 태그를 "
            "만드는 도구에서 직전 태그를 집는다"
        )


def test_no_template_declares_a_caller_job():
    """어떤 템플릿도 job-level `uses:`(재사용 워크플로 호출)를 갖지 않음.

    갖는 순간 test_every_job_has_expected_timeout 이 스키마와 충돌 —
    호출 job 에는 timeout-minutes 를 달 수 없기 때문(reusableWorkflowCallJob).
    """
    for path in _templates():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in data["jobs"].items():
            assert "uses" not in job, f"{path.name}:{job_name} 이 caller job"


def test_deploy_components_are_workflow_call_only():
    for name in DEPLOY_COMPONENTS:
        path = TEMPLATE_DIR / name
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        on = _on_block(data)
        assert set(on) == {"workflow_call"}, f"{name}: on 블록은 workflow_call 전용"
        assert on["workflow_call"]["inputs"]["tag"]["required"] is True, f"{name}: tag required"

        job = next(iter(data["jobs"].values()))
        first = job["steps"][0]
        assert first["uses"] == "actions/checkout@v7", f"{name}: 첫 스텝이 checkout 이어야"
        assert first["with"]["ref"] == "${{ inputs.tag }}", (
            f"{name}: 호출된 워크플로의 github.sha 는 호출자의 것이라 ref 를 명시해야 한다"
        )


def test_deploy_components_declare_no_job_permissions():
    """권한의 단일 출처는 오케스트레이터의 caller job — 양쪽에 적으면 조용히 깎임."""
    for name in DEPLOY_COMPONENTS:
        data = yaml.safe_load((TEMPLATE_DIR / name).read_text(encoding="utf-8"))
        for job_name, job in data["jobs"].items():
            assert "permissions" not in job, f"{name}:{job_name} 이 permissions 를 선언"


def test_pypi_component_splits_oidc_and_token_steps():
    data = yaml.safe_load(
        (TEMPLATE_DIR / "deploy.pypi.workflow.example.yml").read_text(encoding="utf-8")
    )
    steps = data["jobs"]["pypi"]["steps"]
    pub = [s for s in steps if s.get("uses", "").startswith("pypa/gh-action-pypi-publish")]
    assert len(pub) == 2, "OIDC/token 경로를 별도 스텝으로 분리해야 한다"
    oidc = next(s for s in pub if s["if"] == "inputs.auth == 'oidc'")
    token = next(s for s in pub if s["if"] == "inputs.auth == 'token'")
    assert "with" not in oidc, (
        "빈 password 를 넘기면 '제공됨'으로 취급되어 trusted publishing 자동감지가 억제된다"
    )
    assert token["with"]["password"] == "${{ secrets.PYPI_API_TOKEN }}"


def test_pypi_component_auth_default_is_token():
    """재사용 워크플로에서는 PyPI trusted publishing 이 동작하지 않음(pypa/warehouse#11096)
    — auth 기본값은 oidc 가 아니라 token 이어야 소비자가 기본값을 그대로 받아도 첫 릴리스가
    invalid-publisher 로 실패하지 않음. OIDC/token 스텝은 그대로 남아 있어야 함(위 테스트)."""
    data = yaml.safe_load(
        (TEMPLATE_DIR / "deploy.pypi.workflow.example.yml").read_text(encoding="utf-8")
    )
    auth_input = _on_block(data)["workflow_call"]["inputs"]["auth"]
    assert auth_input["default"] == "token"


def test_maven_central_gates_three_build_tools():
    path = TEMPLATE_DIR / "deploy.maven-central.workflow.example.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    inputs = _on_block(data)["workflow_call"]["inputs"]
    assert inputs["build_tool"]["required"] is True
    assert inputs["publish"]["required"] is True
    assert "default" not in inputs["publish"], (
        "publish 에 기본값을 주면 auto-publish 함정(업로드만 하고 미발행)을 사용자가 "
        "의식하지 못한 채 지나간다"
    )
    gates = {s.get("if") for s in data["jobs"]["maven-central"]["steps"]}
    for tool in ("maven", "sbt", "gradle"):
        assert f"inputs.build_tool == '{tool}'" in gates, f"{tool} 다리 게이팅 없음"


def test_maven_central_sbt_leg_skips_gpg_import():
    """sbt-pgp 는 PGP_SECRET(base64)을 프로세스 내부에서 읽음 — 키체인 임포트가 아님."""
    data = yaml.safe_load(
        (TEMPLATE_DIR / "deploy.maven-central.workflow.example.yml").read_text(encoding="utf-8")
    )
    steps = data["jobs"]["maven-central"]["steps"]
    sbt_java = next(
        s
        for s in steps
        if s.get("if") == "inputs.build_tool == 'sbt'"
        and s.get("uses", "").startswith("actions/setup-java")
    )
    assert "gpg-private-key" not in sbt_java["with"]
    assert any(s.get("uses") == "sbt/setup-sbt@v1" for s in steps)

    maven_java = next(
        s
        for s in steps
        if s.get("if") == "inputs.build_tool == 'maven'"
        and s.get("uses", "").startswith("actions/setup-java")
    )
    assert maven_java["with"]["gpg-private-key"] == "${{ secrets.MAVEN_GPG_PRIVATE_KEY }}"


def test_ghcr_component_requires_context_and_dockerfile():
    """빈 file 을 with 로 넘기면 build-push-action 의 {context}/Dockerfile 기본값이 억제됨."""
    data = yaml.safe_load(
        (TEMPLATE_DIR / "deploy.ghcr.workflow.example.yml").read_text(encoding="utf-8")
    )
    inputs = _on_block(data)["workflow_call"]["inputs"]
    for key in ("image", "context", "dockerfile"):
        assert inputs[key]["required"] is True, f"{key} 는 required"
        assert "default" not in inputs[key], f"{key} 의 기본값은 렌더러가 계산한다"

    steps = data["jobs"]["ghcr"]["steps"]
    meta = next(s for s in steps if s.get("uses", "").startswith("docker/metadata-action"))
    assert meta["with"]["tags"] == "type=raw,value=${{ inputs.tag }}", (
        "type=semver 는 github.ref 가 태그일 때만 해석되는데, 호출된 워크플로의 "
        "github.ref 는 호출자의 브랜치다"
    )


# 부동 버전 지정의 형태들. `pip install pkg` 처럼 **제약이 아예 없는** 경우까지 잡아야 해서
# 연산자만 찾는 정규식으로는 부족함 — 그래서 아래 검사는 설치 인자를 하나씩 뜯어 `==` 가
# 붙어 있는지를 봄.
_INSTALL = re.compile(
    r"""(?:^|\s|&&|\|\|)                     # 명령 시작 위치
        (?:python3?\s+-m\s+pip|pip3?|npx\s+--yes|npx\s+-y)\s+   # 설치 명령
        (?P<args>[^\n;&|]+)""",
    re.X,
)
# 설치 명령의 인자 중 패키지가 아닌 것(플래그·pip 서브커맨드).
_NOT_A_PACKAGE = re.compile(r"^-|^(install|--?\w)")


def _floating_installs(text: str) -> list[str]:
    """`==` 로 고정되지 않은 패키지 설치 인자."""
    floating = []
    for m in _INSTALL.finditer(text):
        # 줄 끝 주석은 인자가 아님 — 안 자르면 주석 단어가 전부 "부동 패키지" 로 잡힘.
        args = m.group("args").split(" #")[0]
        for raw in args.split():
            arg = raw.strip("\"'")
            if not arg or _NOT_A_PACKAGE.match(arg):
                continue
            # npx 는 `pkg@version`, pip 는 `pkg==version`.
            if "==" in arg or ("@" in arg and not arg.startswith("@")):
                continue
            floating.append(arg)
    return floating


def test_templates_pin_every_package_they_install():
    """`rule-version-pinning` 은 이 제품이 소비자 CLAUDE.md 에 **주입하는** 룰:
    범위·부동 지정 금지, `==`(또는 락파일·다이제스트)로 고정. 그런데 그 룰을 주입하는
    제품이 렌더하는 워크플로가 부동 설치를 해 2026-08-28 에 실제로 물림 —
    gitpython 3.1.60 이 `Actor.name_email_regex` 를 지우자 코드가 한 줄도 안 바뀐
    저장소의 릴리스가 실패함. 상한을 얹는 것으로는 부족함(그건 여전히 범위이고,
    업스트림이 고쳐도 조용한 영구 천장이 됨).

    `uses:` 는 대상이 아님 — 그쪽은 이미 `@vN` 으로 고정돼 있고 별도 단언이 있음.
    """
    offenders = {}
    for path in _templates():
        found = _floating_installs(path.read_text(encoding="utf-8"))
        if found:
            offenders[path.name] = found
    assert not offenders, (
        f"부동 버전으로 설치하는 템플릿: {offenders} — `==`(npx 는 `@version`)로 고정한다. "
        f"부동 설치는 소비자 저장소의 CI 를 아무 변경 없이 어느 날 빨갛게 만든다"
    )


def test_the_repos_own_release_workflow_pins_too():
    """`_templates()` 는 `github/` 만 훑어 이 저장소 자기 워크플로가 사각지대임.
    실제로 물린 것은 **이쪽** — 소비자 템플릿이 아니라 vway-kit 자신의 릴리스가
    멈춤. 릴리스 워크플로는 태그를 push 한 *뒤에* 도는 스텝도 있어서, 거기서 깨지면
    반쯤 릴리스된 상태로 실패함."""
    own = PLUGIN / ".github/workflows/release.yml"
    found = _floating_installs(own.read_text(encoding="utf-8"))
    assert not found, f"{own.name}: 부동 설치 {found} — `==` 로 고정한다"


def test_every_python_semantic_release_install_constrains_gitpython():
    """PSR 은 config 로드 때 `Actor.name_email_regex` 를 읽는데 GitPython 3.1.60 이
    그것만 빼고 나옴. PSR 자신의 `gitpython~=3.0` 은 그 버전을 배제하지 못하므로,
    제약 없는 재해석은 버전을 계산하기도 전에 죽음 — 2026-08-28 에 실제로 물림.

    설치 지점이 셋이고 **전부** 제약을 들어야 함: 이 저장소 CI, `/vdev-init` 이
    소비자에게 렌더하는 템플릿, 그리고 dev 그룹. 워크플로 둘은 `==` 로 고정하니
    자동으로 만족하지만, dev 그룹은 `uv lock --upgrade` 한 번이면 깨진 릴리스로
    걸어 들어감. 하나만 제약하면 실패는 재해석 한 번 거리에 그대로 남음.

    양쪽 다 파싱함 — 줄 스캔이 아님. `run:` 블록은 `\\` 로 줄바꿈되고 의존성
    리스트는 길어지면 줄바꿈되는데, 줄 스캔은 보지 못한 것을 깨끗하다고 읽음.
    """
    import tomllib

    offenders = []
    for path in _release_workflows():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (data.get("jobs") or {}).values():
            for step in (job or {}).get("steps") or []:
                run = str((step or {}).get("run", ""))
                if "pip install" not in run or "python-semantic-release" not in run:
                    continue
                if "gitpython" not in run.lower():
                    offenders.append(f"{path.name}: {(step.get('name') or run).strip()!r}")
    pyproject = tomllib.loads((PLUGIN / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project") or {}
    groups: list[tuple[str, list]] = [("project.dependencies", project.get("dependencies") or [])]
    groups += [
        (f"dependency-groups.{k}", v) for k, v in (pyproject.get("dependency-groups") or {}).items()
    ]
    groups += [
        (f"project.optional-dependencies.{k}", v)
        for k, v in (project.get("optional-dependencies") or {}).items()
    ]
    # 맨몸 언급은 제약이 아님 — `"GitPython"` 만 적으면 재해석이 3.1.60 을 그대로
    # 집음. 워크플로 쪽은 자매 테스트가 `==` 를 강제해 덮이지만 pyproject 는 여기뿐임.
    constrained = re.compile(r"gitpython\s*(==|!=|<|>|~=|===)", re.I)
    for name, specs in groups:
        text = [str(s) for s in specs]
        if any("python-semantic-release" in s for s in text) and not any(
            constrained.search(s) for s in text
        ):
            offenders.append(f"pyproject.toml [{name}]: {text}")
    assert not offenders, (
        "python-semantic-release 를 GitPython 제약 없이 설치한다:\n  " + "\n  ".join(offenders)
    )


def _release_workflows() -> list[Path]:
    """푸시로 도는 릴리스 워크플로 — 소비자 템플릿 6종 + 이 저장소 자신의 것."""
    return sorted(TEMPLATE_DIR.glob("release.*.workflow.example.yml")) + [
        PLUGIN / ".github/workflows/release.yml"
    ]


def _checkout_refs(path: Path) -> tuple[int, list[str]]:
    """(actions/checkout 스텝 수, 그중 `ref:` 를 지정한 값들).

    개수를 함께 돌려주는 것은 아래 단언이 "핀이 없다"와 "checkout 을 못 찾았다"를 구분
    하기 위해서임. 빈 문자열은 미지정으로 셈 — checkout 은 `core.getInput('ref')` 가
    비면 `github.ref` 로 폴백하므로 `ref: ""` 는 핀이 아님."""
    steps = [
        s for s in _release_steps(path) if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    return len(steps), [
        str(ref)
        for step in steps
        for ref in [(step.get("with") or {}).get("ref")]
        if ref not in (None, "")
    ]


def test_release_workflows_do_not_pin_the_checkout_ref():
    """릴리스는 브랜치 push(+workflow_dispatch)로 돌고, actions/checkout 은 그때 이미 HEAD 를
    트리거 브랜치에 붙임(`git checkout --force -B <branch> refs/remotes/origin/<branch>`,
    원격 ref 는 이벤트의 sha 로 fetch 된 상태). 어느 방향으로 핀을 박아도 그게 깨짐:
    브랜치명을 주면 브랜치 **끝**이 재해석돼 트리거 이후 커밋이 검사 없이 릴리스되고,
    sha 나 태그를 주면 detached HEAD 가 돼 python-semantic-release 의 active_branch 와
    cargo-release 의 `allow-branch` 기본값(`!HEAD`)이 거부함.

    그래서 `on:` 도 같이 잼 — 태그·release 이벤트로 도는 워크플로라면 핀이 오히려 필요
    해지고, 이 불변식은 성립하지 않는 이유로 사람을 막게 됨.

    deploy 컴포넌트는 대상이 아님: workflow_call 은 태그를 명시해야 하고 태그는 그
    아래에서 움직이지 않음(test_deploy_components_are_workflow_call_only 가 반대편을
    고정함)."""
    targets = _release_workflows()
    assert len(targets) == 7, f"릴리스 워크플로 집합이 바뀌었다: {[p.name for p in targets]}"
    offenders, blind = {}, []
    for path in targets:
        found, pinned = _checkout_refs(path)
        if not found:
            blind.append(path.name)
        if pinned:
            offenders[path.name] = pinned
        triggers = set(_on_block(yaml.safe_load(path.read_text(encoding="utf-8"))))
        assert triggers <= {"push", "workflow_dispatch"}, (
            f"{path.name}: {sorted(triggers)} 로도 돈다 — 태그·release 이벤트에서는 기본 "
            f"checkout 이 detached HEAD 를 만들어 이 불변식이 뒤집힌다"
        )
    assert not blind, (
        f"actions/checkout 스텝을 못 찾았다: {blind} — 로컬 컴포짓이나 포크로 바뀌었다면 "
        f"이 가드는 아무것도 재지 않으면서 계속 초록이다"
    )
    assert not offenders, (
        f"릴리스 체크아웃이 ref 를 고정한다: {offenders} — push 트리거는 이미 브랜치에 "
        f"붙어 있다. 브랜치명을 주면 트리거된 커밋이 아닌 끝이 릴리스되고, sha·태그를 "
        f"주면 detached HEAD 가 돼 릴리스 도구가 거부한다"
    )
