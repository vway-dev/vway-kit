"""단위 테스트 워크플로 렌더 — 언어·버전 매트릭스.

언어는 추측하지 않음. `unit_test.jobs[].language` 가 명시 선언이고, 공식 언어인데
`version` 이 비면 그 job 을 **버림** — 추측한 버전으로 도는 CI 는 녹색이어도 거짓.
빈 `language` 는 사람이 직접 setup 을 쓰겠다는 이스케이프 해치라 그대로 둠.
"""

from pathlib import Path

import yaml as _yaml

from scripts.vdev_init_setup import (
    run_setup,
)
from tests.vdev_init._helpers import (
    _UT_JOBS,
    PLUGIN,
    _write_unit_test_config,
)


def test_render_unit_test_absent_section(tmp_path: Path):
    from scripts.vdev_init_setup import load_unit_test_config, render_unit_test_workflow

    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("미설정" in line for line in out)
    assert load_unit_test_config(tmp_path) is None
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_disabled(tmp_path: Path):
    from scripts.vdev_init_setup import render_unit_test_workflow

    _write_unit_test_config(tmp_path, {"enable": False, "jobs": _UT_JOBS})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("enable=false" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_creates_and_substitutes(tmp_path: Path):
    from scripts.vdev_init_setup import render_unit_test_workflow

    _write_unit_test_config(
        tmp_path,
        {
            "enable": True,
            "branches": ["dev", "stage", "main"],
            "timeout_minutes": 25,
            "jobs": _UT_JOBS,
        },
    )
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text  # 토큰 전부 치환
    assert "branches: [dev, stage, main]" in text

    data = _yaml.safe_load(text)  # 유효 YAML
    job = data["jobs"]["unit-test"]
    assert job["timeout-minutes"] == 25
    include = job["strategy"]["matrix"]["include"]
    assert len(include) == 2
    assert include[0]["name"] == "api"
    assert include[0]["language"] == "python"
    assert include[0]["setup"] == "pip install uv && uv sync"
    assert include[0]["test"] == "uv run pytest"
    assert include[1]["test"] == "npm test"


def test_render_unit_test_defaults(tmp_path: Path):
    """branches / timeout_minutes 생략 시 기본값으로 폴백함."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    _write_unit_test_config(tmp_path, {"enable": True, "jobs": _UT_JOBS})
    render_unit_test_workflow(tmp_path, PLUGIN)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    assert "branches: [dev, stage, main]" in text
    assert _yaml.safe_load(text)["jobs"]["unit-test"]["timeout-minutes"] == 15


def test_render_unit_test_empty_jobs_skips(tmp_path: Path):
    """jobs 가 비면 워크플로를 만들지 않음(빈 matrix 는 GHA 에서 에러)."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    _write_unit_test_config(tmp_path, {"enable": True, "jobs": []})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("비어 있어" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_drops_job_without_test(tmp_path: Path):
    """test 명령이 없는 job 은 제외하고 보고하되, 나머지는 정상 렌더함."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [{"name": "docs", "language": "", "version": "", "setup": "", "test": ""}, _UT_JOBS[0]]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("test 명령이 없어 제외" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    include = _yaml.safe_load(text)["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert len(include) == 1 and include[0]["name"] == "api"


def test_render_unit_test_all_jobs_dropped_skips(tmp_path: Path):
    from scripts.vdev_init_setup import render_unit_test_workflow

    _write_unit_test_config(tmp_path, {"enable": True, "jobs": [{"name": "docs", "test": ""}]})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("실행 가능한" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_idempotent_reports_only(tmp_path: Path):
    """이미 있으면 덮어쓰지 않고 보고만 함(커스텀 보존)."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    _write_unit_test_config(tmp_path, {"enable": True, "jobs": _UT_JOBS})
    render_unit_test_workflow(tmp_path, PLUGIN)  # 1차 생성
    dest = tmp_path / ".github" / "workflows" / "unit-test.yml"
    sentinel = dest.read_text(encoding="utf-8") + "\n# user edit\n"
    dest.write_text(sentinel, encoding="utf-8")  # 사용자 수정 흉내
    out = render_unit_test_workflow(tmp_path, PLUGIN)  # 2차 — 보고만
    assert any("이미 있어" in line for line in out)
    assert dest.read_text(encoding="utf-8") == sentinel  # 덮어쓰지 않음


def test_render_unit_test_missing_keys_normalize(tmp_path: Path):
    """누락된 키(setup, language, version)가 빈 문자열로 정규화되는지 검증."""
    from scripts.vdev_init_setup import (
        UNIT_TEST_JOB_KEYS,
        render_unit_test_workflow,
    )

    jobs = [
        {
            "name": "minimal",
            "test": "pytest",
            # setup, language, version 생략 — 정규화 테스트
        }
    ]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    data = _yaml.safe_load(text)
    include = data["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert len(include) == 1
    entry = include[0]
    # 5개 키 모두 존재
    for key in UNIT_TEST_JOB_KEYS:
        assert key in entry, f"key {key} missing from normalized entry"
    # 누락된 키는 빈 문자열로 정규화
    assert entry["setup"] == ""
    assert entry["language"] == ""
    assert entry["version"] == ""
    # 제공된 키는 정상값
    assert entry["name"] == "minimal"
    assert entry["test"] == "pytest"


def test_render_unit_test_nonstring_version_coerced_int(tmp_path: Path):
    """정수 version(파싱된 20)이 문자열 '20'으로 강제됨."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    # 정수 버전(YAML 파싱 후 int)
    jobs = [
        {
            "name": "int-ver",
            "language": "python",
            "version": 20,  # int, not str
            "setup": "pip install",
            "test": "pytest",
        }
    ]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    render_unit_test_workflow(tmp_path, PLUGIN)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    data = _yaml.safe_load(text)
    include = data["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert len(include) == 1
    assert include[0]["version"] == "20"


def test_render_unit_test_nonstring_version_coerced_float(tmp_path: Path):
    """실수 version(파싱된 3.12)이 문자열 '3.12'로 강제됨."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    # 실수 버전(YAML 파싱 후 float)
    jobs = [
        {
            "name": "float-ver",
            "language": "python",
            "version": 3.12,  # float, not str
            "setup": "pip install",
            "test": "pytest",
        }
    ]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    render_unit_test_workflow(tmp_path, PLUGIN)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    assert "__VWAY_" not in text
    data = _yaml.safe_load(text)
    include = data["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert len(include) == 1
    assert include[0]["version"] == "3.12"


def test_render_unit_test_jobs_key_absent(tmp_path: Path):
    """jobs 키가 전혀 없으면(enable=true이지만) 워크플로를 만들지 않음."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    # jobs 키 없음 — enable은 true
    _write_unit_test_config(tmp_path, {"enable": True})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("비어 있어" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_run_setup_renders_unit_test(tmp_path: Path, capsys):

    _write_unit_test_config(
        tmp_path, {"enable": True, "branches": ["dev"], "timeout_minutes": 15, "jobs": _UT_JOBS}
    )
    run_setup(tmp_path, PLUGIN)
    captured = capsys.readouterr().out
    assert "유닛 테스트 워크플로우" in captured
    assert (tmp_path / ".github" / "workflows" / "unit-test.yml").is_file()


def test_render_unit_test_drops_rust_job_without_version(tmp_path: Path):
    """language=rust 인데 version 이 없으면 제외·보고하고, 나머지 job 은 정상 렌더함."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [{"name": "core", "language": "rust", "test": "cargo test"}, _UT_JOBS[0]]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("[!]" in line and "core" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    include = _yaml.safe_load(text)["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert include == [
        {
            "name": "api",
            "language": "python",
            "version": "3.12",
            "setup": "pip install uv && uv sync",
            "test": "uv run pytest",
        }
    ]


def test_render_unit_test_drops_each_official_language_without_version(tmp_path: Path):
    """공식 setup action 5종 전부, version 이 비면 제외·보고됨."""
    from scripts.vdev_init_setup import UNIT_TEST_OFFICIAL_LANGUAGES, render_unit_test_workflow

    for lang in UNIT_TEST_OFFICIAL_LANGUAGES:
        jobs = [{"name": f"job-{lang}", "language": lang, "test": "run"}]
        _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
        out = render_unit_test_workflow(tmp_path, PLUGIN)
        assert any("[!]" in line and f"job-{lang}" in line for line in out), (lang, out)
        assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_escape_hatch_blank_language_kept(tmp_path: Path):
    """language='' 이고 version 도 비었으면(이스케이프 해치) 제외되지 않고 렌더됨."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [
        {
            "name": "scala",
            "language": "",
            "version": "",
            "setup": "coursier setup",
            "test": "sbt test",
        }
    ]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    include = _yaml.safe_load(text)["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert include == [
        {
            "name": "scala",
            "language": "",
            "version": "",
            "setup": "coursier setup",
            "test": "sbt test",
        }
    ]


def test_render_unit_test_all_dropped_for_blank_version_skips(tmp_path: Path):
    """전체 job 이 version 누락으로 제외되면 워크플로를 만들지 않고 실행 가능 job
    없음을 보고함."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [{"name": "core", "language": "rust", "test": "cargo test"}]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("실행 가능한" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_whitespace_only_version_treated_as_blank(tmp_path: Path):
    """공백만 있는 version 은 빈 값으로 취급되어 제외됨."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [{"name": "core", "language": "rust", "version": "   ", "test": "cargo test"}]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("[!]" in line and "core" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_language_case_insensitive_normalized(tmp_path: Path):
    """language: 'Python'(대문자 섞임)도 매칭되고, 렌더된 matrix 엔트리는 소문자로
    정규화됨 — 그래야 템플릿의 소문자 `if: matrix.language == 'python'` 게이트가 매치함."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [{"name": "api", "language": "Python", "version": "3.12", "test": "pytest"}]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    include = _yaml.safe_load(text)["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert include[0]["language"] == "python"


def test_render_unit_test_language_case_insensitive_version_required(tmp_path: Path):
    """language: 'RUST'(대문자)도 공식 언어 판정에 포함되어 version 필수 규칙이 적용됨
    (case-insensitive 멤버십 판정이 version-required 규칙에 반영됨)."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [{"name": "core", "language": "RUST", "version": "", "test": "cargo test"}]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("[!]" in line and "core" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "unit-test.yml").exists()


def test_render_unit_test_blank_name_defaults_indexed(tmp_path: Path):
    """name 이 비어 있는 생존 job 은 순번대로 job-1, job-2 가 채워짐(1-based, 드롭된
    항목은 순번에서 제외)."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [
        {"name": "", "language": "", "setup": "", "test": "pytest"},
        {"language": "", "setup": "", "test": "npm test"},
    ]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    include = _yaml.safe_load(text)["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert include[0]["name"] == "job-1"
    assert include[1]["name"] == "job-2"


def test_render_unit_test_duplicate_name_warns_but_keeps_both(tmp_path: Path):
    """같은 name 을 가진 두 생존 job 은 드롭되지 않고 둘 다 렌더되지만, 중복을 알리는
    [!] 줄이 보고에 나옴(GitHub 은 그래도 별개 job 을 만들지만 UI 라벨이 겹침)."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [
        {"name": "dup", "language": "", "setup": "", "test": "pytest"},
        {"name": "dup", "language": "", "setup": "", "test": "npm test"},
    ]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("[!]" in line and "dup" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    include = _yaml.safe_load(text)["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert len(include) == 2
    assert include[0]["name"] == "dup"
    assert include[1]["name"] == "dup"


def test_render_unit_test_escape_hatch_still_works(tmp_path: Path):
    """language: ''·version 공백·setup/test 비공백인 이스케이프 해치 job 은 여전히
    렌더되고, 빈 version 은 `version: ''` 로 남음(공식 action 이 아니므로 안전)."""
    from scripts.vdev_init_setup import render_unit_test_workflow

    jobs = [
        {
            "name": "scala",
            "language": "",
            "version": "",
            "setup": "coursier setup",
            "test": "sbt test",
        }
    ]
    _write_unit_test_config(tmp_path, {"enable": True, "jobs": jobs})
    out = render_unit_test_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    text = (tmp_path / ".github" / "workflows" / "unit-test.yml").read_text(encoding="utf-8")
    assert "version: ''" in text
    include = _yaml.safe_load(text)["jobs"]["unit-test"]["strategy"]["matrix"]["include"]
    assert include[0]["name"] == "scala"
    assert include[0]["version"] == ""


def test_example_config_has_unit_test_block():
    """example config 의 unit_test 스키마가 렌더러 계약과 일치함."""
    text = (PLUGIN / "vdev-config.example.yaml").read_text(encoding="utf-8")
    ut = _yaml.safe_load(text)["unit_test"]
    assert ut["enable"] is True
    assert ut["branches"], "트리거 브랜치가 비어 있음"
    assert isinstance(ut["timeout_minutes"], int)
    job = ut["jobs"][0]
    assert set(job) == {"name", "language", "version", "setup", "test"}
