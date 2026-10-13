"""claude 전용 호스트의 산출물이 하네스 배선 이전과 byte-identical 인지 잼(컨트롤러 판정 5).

- 아래 두 기대 출력은 하네스 배선 직전 판의 `run_setup`·`run_uninstall` 을 빈 호스트에서
  돌려 캡처한 것 — 호스트 경로는 `<HOST>`, 플러그인 버전은 `<VERSION>` 으로 접음.
- 머신에 따라 갈리는 두 입력은 고정함: `[자동 업데이트 인증]`(사용자 git config)은 빈 목록,
  `[Recoble MCP]` 의 레지스트리(`~/.claude.json`)는 없는 경로.
- 이 기대값이 깨지면 claude 전용 호스트의 출력이 바뀐 것 — 의도한 변경일 때만 갱신.
"""

import sys
from pathlib import Path

import pytest

import scripts.vdev_init_setup as vis
from tests.harnesses.setup_wiring._helpers import _cfg
from tests.vdev_init._helpers import PLUGIN

# 슬롯 목록 한 줄은 줄 길이 한도를 넘어 따로 이어 붙임.
SLOTS = (
    "branches, modules, review_checklist, commit_guide, issue_tracker_guide, alm, handoff,"
    " gate_evidence, doc_sync, wiki, doc_style, contract_test, versioning, unit_test, e2e, deploy"
)

# uninstall 이 남기는 비밀 보호 라인 — 같은 이유로 따로 이어 붙임.
KEPT = ".teams-webhooks.local.json, teamer_account.md"
CHANGED = ".claude/settings.json, .gitignore, .claude/vway-kit/"

SETUP_STDOUT = """\
vdev-init 기계적 셋업 — host=<HOST>
[복사]
  [+] 복사: _vway_paths.py
  [+] 복사: _md_anchors.py
  [+] 복사: vdev_gate_check.py
  [+] 복사: precommit-runner.sh
  [+] 복사: wiki_graph.py
  [+] 복사: doc_style_check.py
  [+] 복사: srs_check.py
  [+] 복사: alm_docs.py
  [+] 복사: release_version.py
  [+] 복사: changelog_section.py
  [+] 복사: doc_invariants.py
  [+] 복사: teams_alert.py
  [+] 복사: notify-push.sh
  [+] 복사: check-deps.sh
  [+] 복사: vdev-tiers.yaml → config/
[커밋 게이트]
  [+] 커밋 게이트 등록 (settings.json)
[룰 정리]
  [=] .claude/rules/vway-kit/ 없음 (skip)
[마켓 자동 업데이트]
  [+] vway 마켓 등록 + autoUpdate=true
[구버전 경로 이전]
  [=] 이전할 구버전 경로 없음 (skip)
[템플릿]
  [=] 선언된 템플릿 없음 (skip)
[pre-commit 점검]
  [+] .pre-commit-config.yaml 생성 (예시 복사 — local 훅은 팀 언어로 교체)
[gitignore]
  [+] .gitignore += teamer_account.md
  [+] .gitignore += .teams-webhooks.local.json
  [+] .gitignore += .claude/vway-kit/.vdev/
  [+] .gitignore += .claude/vway-kit/scripts/**/__pycache__/
  [+] .gitignore += .claude/vway-kit/.applied-version
[계약 테스트 워크플로우]
  [=] contract_test 미설정 — 워크플로우 skip
[버저닝 워크플로우]
  [=] versioning 미설정 — 워크플로 skip
[유닛 테스트 워크플로우]
  [=] unit_test 미설정 — 워크플로 skip
[문체 검사 워크플로우]
  [=] doc_style 미설정 — 워크플로 skip
[E2E 워크플로우]
  [=] e2e 미설정 — 워크플로 skip
[배포 워크플로우]
  [=] deploy 미설정 — 배포 워크플로 skip
[Recoble MCP]
  [=] Recoble 스페이스 없음 (skip)
[배포 배선]
  [=] release.yml 없음 — deploy 는 workflow_dispatch 수동 전용
[릴리스 워크플로 마이그레이션]
  [=] release 워크플로 없음 (skip)
[config 슬롯 점검]
  [i] example 에 새 config 슬롯 16개: <SLOTS>
      → /vdev-init 으로 호스트 config 에 추가를 검토하세요.
[ALM 계층 점검]
  [=] ALM 계층 선언 없음 (skip)
[폐기 필드 점검]
  [=] 폐기된 전역 test.command 없음 (skip)
  [=] 폐기된 최상위 teamer: 없음 (skip)
[checks 타이밍 점검]
  [=] checks.when 타이밍 값 정상 (skip)
[자동 업데이트 인증]
[마이그레이션]
  [i] 적용 버전 기록: (없음) → <VERSION>
기계적 셋업 완료.
""".replace("<SLOTS>", SLOTS)

UNINSTALL_STDOUT = """\
vway-kit 정리(uninstall) — host=<HOST>
[커밋 게이트 해제]
  [-] 커밋 게이트 해제 (settings.json)
[Recoble MCP]
  [=] 등록 상태를 확인할 수 없음 — `claude mcp list` 로 직접 확인하세요 (skip)
[마켓 등록 해제]
  [-] vway 마켓 등록 해제 (settings.json) — 남은 설정이 없어 settings.json 삭제
[gitignore 정리]
  [-] .gitignore vway-kit 라인 3개 제거 — 비밀 파일 보호 라인 유지: <KEPT>
[CLAUDE.md teams 블록 제거]
  [=] CLAUDE.md 없음 (skip)
[vway-kit 디렉터리 삭제]
  [-] .claude/vway-kit/ 삭제 (스크립트·config·증거·웹훅 포함)
[룰 삭제]
  [=] .claude/rules/vway-kit/ 없음 (skip)
[남는 항목 — 수동 처리 안내]
  - .pre-commit-config.yaml 의 teams-notify-push 훅/정적분석 훅은 자동 제거하지
    않습니다(주석·팀 커스텀 보존). 필요 시 직접 제거하세요.
  - 설치했던 git 훅 비활성화:
      pre-commit uninstall --hook-type pre-commit --hook-type commit-msg \\
        --hook-type pre-push
  - 이 정리가 바꾼 것은 커밋해야 반영됩니다: <CHANGED>
정리 완료.
""".replace("<KEPT>", KEPT).replace("<CHANGED>", CHANGED)

SETUP_FILES = {
    ".claude/settings.json",
    ".claude/vway-kit/.applied-version",
    ".claude/vway-kit/config/vdev-tiers.yaml",
    ".claude/vway-kit/scripts/_md_anchors.py",
    ".claude/vway-kit/scripts/_vway_paths.py",
    ".claude/vway-kit/scripts/alm_docs.py",
    ".claude/vway-kit/scripts/changelog_section.py",
    ".claude/vway-kit/scripts/check-deps.sh",
    ".claude/vway-kit/scripts/doc_invariants.py",
    ".claude/vway-kit/scripts/doc_style_check.py",
    ".claude/vway-kit/scripts/notify-push.sh",
    ".claude/vway-kit/scripts/precommit-runner.sh",
    ".claude/vway-kit/scripts/release_version.py",
    ".claude/vway-kit/scripts/srs_check.py",
    ".claude/vway-kit/scripts/teams_alert.py",
    ".claude/vway-kit/scripts/vdev_gate_check.py",
    ".claude/vway-kit/scripts/wiki_graph.py",
    ".gitignore",
    ".pre-commit-config.yaml",
}

UNINSTALL_FILES = {".gitignore", ".pre-commit-config.yaml"}


@pytest.fixture
def host(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(vis, "detect_autoupdate_auth", lambda: [])
    monkeypatch.setattr(vis, "_claude_registry_path", lambda: tmp_path / "no-such-claude.json")
    root = tmp_path / "host"
    root.mkdir()
    return root


def _files(host: Path) -> set[str]:
    return {p.relative_to(host).as_posix() for p in host.rglob("*") if p.is_file()}


def _run(fn, host: Path, capsys) -> str:
    capsys.readouterr()
    assert fn() is True
    out = capsys.readouterr().out.replace(str(host), "<HOST>")
    return out.replace(vis.plugin_version(PLUGIN), "<VERSION>")


def test_claude_only_setup_and_uninstall_match_the_pre_harness_capture(host: Path, capsys):
    """`harnesses` 키 없는 호스트 — 셋업·정리의 stdout 과 남는 파일 집합이 배선 전 캡처와 같음."""
    assert _run(lambda: vis.run_setup(host, PLUGIN), host, capsys) == SETUP_STDOUT
    assert _files(host) == SETUP_FILES
    assert _run(lambda: vis.run_uninstall(host), host, capsys) == UNINSTALL_STDOUT
    assert _files(host) == UNINSTALL_FILES


def test_an_explicit_claude_list_changes_nothing_but_the_config_file(host: Path, capsys):
    """`[claude]` 는 부재와 같은 호스트 — 슬롯 점검 줄 말고는 같은 출력, config 한 파일만 더함."""
    _cfg(host, "harnesses: [claude]\n")
    out = _run(lambda: vis.run_setup(host, PLUGIN), host, capsys).splitlines()
    want = SETUP_STDOUT.splitlines()
    slot = want.index("[config 슬롯 점검]")
    assert out[: slot + 1] == want[: slot + 1]
    assert out[slot + 3 :] == want[slot + 3 :]
    assert _files(host) == SETUP_FILES | {".claude/vway-kit/config/vdev-config.yaml"}


def test_a_host_without_pyyaml_fails_exactly_as_before(host: Path, monkeypatch, capsys):
    """PyYAML 부재 — 배선 전과 같이 YAML 을 읽는 첫 단계(`[템플릿]`)에서 예외가 새어 셋업이
    비0 으로 끝남. 하네스 배선이 그 예외를 삼켜 완료로 바꾸거나 `harnesses` 줄을 더하면 안 됨."""
    monkeypatch.setitem(sys.modules, "yaml", None)
    with pytest.raises(ImportError):
        vis.run_setup(host, PLUGIN)
    out = capsys.readouterr().out.replace(str(host), "<HOST>").splitlines()
    want = SETUP_STDOUT.splitlines()
    assert out == want[: want.index("[템플릿]") + 1]
