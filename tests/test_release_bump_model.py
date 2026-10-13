"""릴리스 템플릿의 레벨 수신 방식 — 두 갈래 중 정확히 하나로 등재되어야 함.

`release-commit` Step 0 은 렌더된 release.yml 을 읽어 staging 에서 물을 레벨을 정함:
`# vway-release-levels:` 선언이 있으면 그 목록이 곧 선택지(`Release-Level:` 트레일러 채널),
없으면 트레일러를 읽지 않는 워크플로(커밋 타입 자동 전용). 그 판정이 안전한 것은 템플릿의 선언이
템플릿이 실제로 하는 일과 같을 동안뿐임 — `auto` 를 선언했는데 트레일러 없는 push 가 rc 를
안 내면, 스킬이 rc 가 영영 안 나는 선택지를 권함. 레벨별 실제 셸 동작은
`tests/test_release_rc_version.py` 가 잼.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent  # repo root == 플러그인 루트

_DECLARATION = re.compile(r"^# vway-release-levels:(.*)$", re.MULTILINE)


def _release_tools():
    from scripts.vdev_init_setup import _RELEASE_TEMPLATES

    return sorted(_RELEASE_TEMPLATES)


# 갈래별 등재. 탐지가 아니라 목록인 이유 — 새 템플릿의 갈래는 추측이 아니라 결정이어야 하고,
# 어느 목록에도 없거나 둘에 든 것은 아래 테스트가 잡음.
#
# 트레일러: 선언한 레벨을 `Release-Level:` 로 받음. `auto` 는 트레일러 없는 push 가 커밋 타입으로
# rc 를 내는 템플릿만 선언함.
_TRAILER_LEVELS = {
    "python-semantic-release": ["auto", "continue", "patch", "minor", "major"],
    "gitversion": ["continue", "patch", "minor", "major"],
    "cargo-release": ["continue", "patch", "minor", "major"],
    "jreleaser": ["continue", "patch", "minor", "major"],
    "sbt-ci-release": ["continue", "patch", "minor", "major"],
}
# 자동 전용: 레벨을 강제할 수단이 없음 — prerelease push 가 커밋 타입으로 rc 를 냄.
_AUTO_ONLY_TOOLS = {"semantic-release"}

# 스킬의 탐지 블록이 반드시 읽어야 하는 신호 — 선언 · 선언 없는 트레일러 · 옛 dispatch 입력.
_PROBE_SIGNAL = ("vway-release-levels", "'Release-Level'", "'level'")


def _body(tool: str) -> str:
    from scripts.vdev_init_setup import _RELEASE_TEMPLATES

    return (PLUGIN / _RELEASE_TEMPLATES[tool]).read_text(encoding="utf-8")


def _on(body: str) -> dict:
    """YAML 1.1 이 맨몸 `on:` 을 불리언 True 로 읽으므로 두 철자를 모두 물음."""
    doc = yaml.safe_load(body) or {}
    on = doc.get("on", doc.get(True)) or {}
    return on if isinstance(on, dict) else {}


@pytest.mark.parametrize("tool", _release_tools())
def test_a_release_template_is_declared_as_exactly_one_release_model(tool: str):
    declared = [tool in _TRAILER_LEVELS, tool in _AUTO_ONLY_TOOLS]
    assert sum(declared) == 1, (
        f"{tool}: 릴리스 모델 등재가 {sum(declared)}개 — 정확히 하나여야 함. _TRAILER_LEVELS · "
        f"_AUTO_ONLY_TOOLS 중 이 템플릿이 실제로 하는 일에 맞는 쪽 하나에만 넣어라."
    )


@pytest.mark.parametrize("tool", sorted(_TRAILER_LEVELS))
def test_a_trailer_template_declares_the_levels_it_reads(tool: str):
    """선언이 스킬의 선택지 SSOT — 등재와 한 글자라도 다르면 스킬이 템플릿이 안 받는 레벨을 권함."""
    body = _body(tool)
    m = _DECLARATION.search(body)
    assert m, f"{tool}: `# vway-release-levels:` 선언 없음 — Step 0 이 선택지를 못 읽음."
    assert m.group(1).split() == _TRAILER_LEVELS[tool], (
        f"{tool}: 선언 {m.group(1).split()} ≠ 등재 {_TRAILER_LEVELS[tool]}. 템플릿이 실제로 받는 "
        f"레벨에 맞춰 둘 중 하나를 고쳐라."
    )
    assert "Release-Level" in body, f"{tool}: 레벨을 선언했는데 트레일러를 읽지 않음."


@pytest.mark.parametrize("tool", sorted(_TRAILER_LEVELS))
def test_a_trailer_template_takes_no_dispatch_level(tool: str):
    """레벨 채널은 트레일러 하나 — dispatch 가 남으면 기본 브랜치(production)로 간 실행이 계획에
    없던 정식 릴리스를 내는 경로와, 트레일러와 dispatch 중 무엇이 이기나라는 물음이 되살아남."""
    assert "workflow_dispatch" not in _on(_body(tool)), (
        f"{tool}: workflow_dispatch 가 다시 생김 — 레벨은 Release-Level 트레일러로만 받음."
    )


@pytest.mark.parametrize("tool", sorted(_AUTO_ONLY_TOOLS))
def test_an_auto_only_template_reads_no_level(tool: str):
    body = _body(tool)
    assert not _DECLARATION.search(body), f"{tool}: 자동 전용인데 레벨 선언이 있음."
    assert "Release-Level" not in body, (
        f"{tool}: 자동 전용인데 Release-Level 을 언급함 — 읽는다면 _TRAILER_LEVELS 로 옮겨라."
    )


def test_the_repos_own_release_workflow_takes_the_trailer():
    """이 저장소 자신의 승격도 같은 스킬을 탐 — 선언이 없거나 dispatch 가 남으면 Step 0 이 이
    저장소를 `legacy-dispatch` 로 읽고 멈춤. 버전 계산은 소스 스크립트를 직접 부름(호스트 사본
    없음)."""
    body = (PLUGIN / ".github/workflows/release.yml").read_text(encoding="utf-8")
    m = _DECLARATION.search(body)
    assert m and m.group(1).split() == _TRAILER_LEVELS["python-semantic-release"], (
        "release.yml: 선언이 PSR 템플릿과 다름 — 같은 도구, 같은 레벨."
    )
    assert "workflow_dispatch" not in _on(body), "release.yml: workflow_dispatch 가 다시 생김."
    assert "RV=scripts/release_version.py" in body


def test_the_skill_probe_looks_for_the_marker_this_file_declares():
    """등재와 탐지는 같은 신호를 봄. 스킬의 python3 블록이 다른 것을 읽기 시작하면 트레일러 호스트가
    자동 전용으로 분류되는데, 위 등재는 템플릿만 보므로 그대로 초록임 — 두 곳이 갈라진 것을 아무도
    못 봄."""
    skill = (PLUGIN / "skills/release-commit/SKILL.md").read_text(encoding="utf-8")
    probe = re.search(r"```bash\n(python3 -c .*?)\n```", skill, re.DOTALL)
    assert probe, (
        "release-commit Step 0 의 python3 탐지 블록을 못 찾음 — 이 파일의 등재가 무엇에도 "
        "묶이지 않게 됨. 블록을 되돌리거나 여기 추출 패턴을 새 형태에 맞춰라."
    )
    missing = [name for name in _PROBE_SIGNAL if name not in probe.group(1)]
    assert not missing, (
        f"release-commit Step 0 의 탐지 블록이 {missing} 를 더는 읽지 않음 — 등재가 재는 "
        f"신호와 갈라짐. 둘 중 하나를 고쳐라."
    )
