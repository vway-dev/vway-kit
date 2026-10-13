"""E2E 워크플로 렌더 — 켜지는 조건과, 켜졌는데 스위트가 없는 상태.

다른 렌더와 갈리는 지점 둘을 잼. ① no-op 이 **템플릿 안 스텝**이라, 브라우저 프런트가 없는
소비자도 승격 브랜치 push 마다 그 판정에 러너를 씀 — 자기 스크립트가 무출력 exit 0 을 내주는
doc-style·wiki-verify 와 갈리는 곳. ② `e2e.enable` 은 doc_style 의 것과 달리 **렌더 스위치일
뿐**이라(그 스크립트가 같은 플래그를 읽지 않음), 켜 두고 스위트를 한 번도 안 쓴 상태가
성립함. 템플릿의 detect 스텝이 그것을 green 으로 유지하고, 셋업 보고의 스캐폴드 포인터가
그것이 영구가 되지 않게 함.
"""

from pathlib import Path

import yaml as _yaml

from scripts.vdev_init_setup import (
    load_e2e_config,
    missing_config_slots,
    render_e2e_workflow,
)
from tests.vdev_init._helpers import PLUGIN

TEMPLATE = PLUGIN / "github" / "e2e.workflow.example.yml"


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _on(data: dict) -> dict:
    # PyYAML 은 따옴표 없는 `on:` 키를 boolean True 로 읽음.
    on = data.get(True) or data.get("on")
    assert isinstance(on, dict), "템플릿의 `on:` 블록을 못 읽음"
    return on


def test_e2e_template_carries_no_render_tokens():
    # 전달 경로가 토큰 없는 복사라, 토큰이 하나라도 남으면 소비자 워크플로에 그대로
    # 실려 나가고 아무도 치환하지 않음.
    assert "__VWAY_" not in _template_text()


def test_e2e_template_has_no_pull_request_trigger():
    # fork PR 은 시크릿을 못 받음 — 자격증명이 필요한 스위트는 외부 기여마다 빨간불이 됨.
    # 필수 검사 승격은 소비자가 체크리스트를 읽고 옵트인할 결정.
    on = _on(_yaml.safe_load(_template_text()))
    assert "pull_request" not in on
    assert "push" in on and "workflow_dispatch" in on


def test_e2e_template_guards_on_a_playwright_config():
    # 실행 명령이 Playwright 리터럴이라야 템플릿이 config 파일 이름 규약을 알고,
    # 그래서 스위트가 없는 저장소에서 스스로 no-op green 이 될 수 있음.
    text = _template_text()
    assert "playwright.config." in text
    assert "steps.detect.outputs.found" in text


def test_e2e_template_guards_every_step_after_detect():
    # "켰는데 스위트가 없으면 green" 이라는 약속은 스텝마다의 `if:` 에 살아 있음.
    # 파일 어딘가에 그 문자열이 있는지만 보는 검사는 가드를 하나 지워도 통과함
    # (detect 자신의 echo 나 Teardown 의 가드가 낱말을 대신 살려 줌).
    steps = _yaml.safe_load(_template_text())["jobs"]["e2e"]["steps"]
    detect_index = next(i for i, step in enumerate(steps) if step.get("id") == "detect")
    for step in steps[detect_index + 1 :]:
        assert "steps.detect.outputs.found" in step.get("if", ""), (
            f"{step.get('name')!r} 스텝이 detect 뒤인데 그 출력에 걸려 있지 않음"
        )


def test_e2e_template_job_carries_a_timeout():
    assert _yaml.safe_load(_template_text())["jobs"]["e2e"]["timeout-minutes"] > 0


def _write_config(host: Path, e2e: dict | None) -> None:
    cfg_dir = host / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    body = {} if e2e is None else {"e2e": e2e}
    (cfg_dir / "vdev-config.yaml").write_text(
        _yaml.safe_dump(body, allow_unicode=True), encoding="utf-8"
    )


def test_render_e2e_creates_when_enabled(tmp_path: Path):
    _write_config(tmp_path, {"enable": True})
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert any("생성" in line for line in out)
    dest = tmp_path / ".github" / "workflows" / "e2e.yml"
    assert dest.read_text(encoding="utf-8") == _template_text()  # 렌더가 아니라 복사


def test_render_e2e_skips_when_disabled(tmp_path: Path):
    _write_config(tmp_path, {"enable": False})
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert any("enable=false" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "e2e.yml").exists()


def test_render_e2e_skips_when_section_absent(tmp_path: Path):
    _write_config(tmp_path, None)
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert any("미설정" in line for line in out)
    assert not (tmp_path / ".github" / "workflows" / "e2e.yml").exists()


def test_render_e2e_is_non_destructive(tmp_path: Path):
    _write_config(tmp_path, {"enable": True})
    dest = tmp_path / ".github" / "workflows" / "e2e.yml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("# 소비자가 고친 것\n", encoding="utf-8")
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert dest.read_text(encoding="utf-8") == "# 소비자가 고친 것\n"
    assert any("이미 있어" in line for line in out)


def test_render_e2e_points_at_the_scaffold_when_no_config_exists(tmp_path: Path):
    # 전달은 사람이 당기는 방아쇠라(스캐폴드가 playwright.config.* 를 소유), boolean 이
    # 막을 수 없는 상태 하나가 남음 — "워크플로는 렌더됐고 스위트는 어디에도 없음".
    _write_config(tmp_path, {"enable": True})
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert any("playwright-scaffold" in line for line in out)


def test_render_e2e_stays_quiet_when_a_config_exists(tmp_path: Path):
    _write_config(tmp_path, {"enable": True})
    (tmp_path / "playwright.config.ts").write_text("export default {};\n", encoding="utf-8")
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert not any("playwright-scaffold" in line for line in out)


def test_render_e2e_stays_quiet_when_a_nested_config_exists(tmp_path: Path):
    # 루트 + 두 단계 아래 — 템플릿 자신의 `find -maxdepth 3` 과 EDIT 4 예시 경로에 맞춤.
    # 워크플로는 찾는데 이 글로브는 못 찾으면, 스캐폴드 포인터가 이미 있는 config 를 두고
    # 계속 뜸.
    _write_config(tmp_path, {"enable": True})
    nested = tmp_path / "apps" / "web"
    nested.mkdir(parents=True)
    (nested / "playwright.config.ts").write_text("export default {};\n", encoding="utf-8")
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert not any("playwright-scaffold" in line for line in out)


def test_render_e2e_ignores_a_config_inside_node_modules(tmp_path: Path):
    # 워크플로의 find 는 `-not -path '*/node_modules/*'` 로 뺌. 렌더러가 안 빼면 비대칭이
    # 잘못된 방향으로 남음 — 렌더러는 node_modules 가 **있는** 개발자 머신에서 돌고,
    # 워크플로는 그것이 gitignore 된 체크아웃에서 돎. 의존성이 싣고 온 config 하나가
    # 포인터를 지우고 CI 는 found=false 로 아무것도 안 하는 상태가 조용히 영구가 됨.
    _write_config(tmp_path, {"enable": True})
    pkg = tmp_path / "node_modules" / "some-pkg"
    pkg.mkdir(parents=True)
    (pkg / "playwright.config.js").write_text("module.exports = {};\n", encoding="utf-8")
    out = render_e2e_workflow(tmp_path, PLUGIN)
    assert any("playwright-scaffold" in line for line in out)


def test_the_template_excludes_node_modules_too():
    # 위 배제의 짝. 한쪽만 고치면 둘이 다시 갈라짐.
    assert "node_modules" in _template_text()


def test_load_e2e_config_fails_open_on_a_broken_file(tmp_path: Path):
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "vdev-config.yaml").write_text("e2e: [broken\n", encoding="utf-8")
    assert load_e2e_config(tmp_path) is None


def test_e2e_slot_ships_disabled_in_the_example():
    # 예시의 슬롯이 **이미 설치한** 호스트에 기능 도착을 알리는 유일한 채널이고,
    # wiki·doc_style·deploy 와 같이 꺼진 채로 출하돼야 함.
    example = _yaml.safe_load((PLUGIN / "vdev-config.example.yaml").read_text(encoding="utf-8"))
    assert example["e2e"]["enable"] is False


def test_e2e_slot_is_reported_as_missing(tmp_path: Path):
    _write_config(tmp_path, None)
    assert "e2e" in [s["label"] for s in missing_config_slots(tmp_path, PLUGIN)]
