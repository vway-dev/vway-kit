"""모듈별 검사 라우팅 — `checks.when` 타이밍 버킷과 변경 경로 매칭.

`precommit` 은 바뀐 모듈의 `every-commit` 검사를, `security-scan` 은 모든 모듈의
`promotion` 검사를 돌림. 어느 모듈에도 안 걸리는 경로는 보고하되 막지 않음.
"""

import json
import os
import sys
from pathlib import Path

import scripts.vdev_gate_check as fgc
from tests._proc import run_bounded
from tests.gate_check._helpers import (
    _repo_with_worktree,
    _write_modcfg,
    _write_timingcfg,
)


def test_parse_check_string_defaults_every_commit():
    assert fgc._parse_check("lint", "ruff check") == ("ruff check", "every-commit")


def test_parse_check_string_security_key_is_promotion():
    # 하위호환: 문자열 "security" 키는 promotion 으로 라우팅(매직 키 잔존).
    assert fgc._parse_check("security", "bandit -r .") == ("bandit -r .", "promotion")


def test_parse_check_dict_explicit_when():
    assert fgc._parse_check("perf", {"run": "pytest bench", "when": "promotion"}) == (
        "pytest bench",
        "promotion",
    )


def test_parse_check_dict_when_omitted_uses_key_default():
    # when 생략 → 키 기반 기본값(비-security 키 → every-commit).
    assert fgc._parse_check("typecheck", {"run": "mypy ."}) == ("mypy .", "every-commit")


def test_parse_check_dict_bad_when_failopen_to_key_default():
    # 오류값 when → FAIL-OPEN 키 기본값(security 키였다면 promotion).
    assert fgc._parse_check("audit", {"run": "pip-audit", "when": "bogus"}) == (
        "pip-audit",
        "every-commit",
    )
    assert fgc._parse_check("security", {"run": "x", "when": "bogus"}) == ("x", "promotion")


def test_parse_check_empty_cmd_returns_none():
    assert fgc._parse_check("lint", "") == (None, "every-commit")
    assert fgc._parse_check("lint", {"when": "promotion"}) == (None, "promotion")


def test_module_commands_every_commit_bucket_routes_custom(tmp_path: Path, monkeypatch):
    # precommit 버킷: every-commit 타이밍 검사만(lint + license-check + typecheck + audit),
    # promotion 타이밍(security, perf-bench)은 제외.
    _write_timingcfg(tmp_path)
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["services/api/x.py"])
    cmds, _ = fgc.module_commands(tmp_path, "dev", ["precommit", "review"])
    assert cmds == ["ruff check services/api", "reuse lint", "mypy services/api", "pip-audit"]
    assert "bandit -r services/api" not in cmds
    assert "pytest bench" not in cmds


def test_module_commands_promotion_bucket_routes_custom(tmp_path: Path, monkeypatch):
    # security-scan 버킷: promotion 타이밍 검사만(security + perf-bench), 전체 모듈 순회.
    _write_timingcfg(tmp_path)
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["services/api/x.py"])
    cmds, _ = fgc.module_commands(tmp_path, "release", ["precommit", "security-scan"])
    # every-commit(변경 모듈) + promotion(전체 모듈) 둘 다. promotion 커스텀 다개 포함.
    assert "bandit -r services/api" in cmds
    assert "pytest bench" in cmds


def test_module_commands_dev_runs_changed_non_security(tmp_path: Path, monkeypatch):
    _write_modcfg(tmp_path)
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["services/api/x.py"])
    cmds, report = fgc.module_commands(tmp_path, "dev", ["precommit", "review", "doc-sync"])
    # api 변경 → api 의 non-security(lint, test). web 미변경 → 제외. security 제외.
    assert cmds == ["ruff check services/api", "pytest services/api"]
    assert report == []


def test_module_commands_dev_gate_removed_skips_non_security(tmp_path: Path, monkeypatch):
    # precommit 이 gates 에서 빠지면 변경 모듈이 있어도 사전검사를 실행하지 않음
    # (gates 리스트가 실제 스위치 — tier 라벨만으로는 실행되지 않음).
    _write_modcfg(tmp_path)
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["services/api/x.py"])
    cmds, report = fgc.module_commands(tmp_path, "dev", ["review", "doc-sync"])
    assert cmds == []
    assert report == []


def test_module_commands_release_adds_full_security(tmp_path: Path, monkeypatch):
    _write_modcfg(tmp_path)
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["services/api/x.py"])
    cmds, _ = fgc.module_commands(
        tmp_path, "release", ["precommit", "review", "security-scan", "security"]
    )
    # 변경 모듈 non-security + 전체 모듈 security(api 만 security 있음 → bandit).
    assert cmds == ["ruff check services/api", "pytest services/api", "bandit -r services/api"]


def test_module_commands_release_gate_removed_skips_security(tmp_path: Path, monkeypatch):
    # security-scan 이 gates 에서 빠지면 release 여도 전체 모듈 security 는 실행하지 않음.
    _write_modcfg(tmp_path)
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["services/api/x.py"])
    cmds, _ = fgc.module_commands(tmp_path, "release", ["precommit", "review", "security"])
    assert cmds == ["ruff check services/api", "pytest services/api"]
    assert "bandit -r services/api" not in cmds


def test_module_commands_docs_empty(tmp_path: Path):
    assert fgc.module_commands(tmp_path, "docs", ["doc-sync"]) == ([], [])
    assert fgc.module_commands(tmp_path, None, None) == ([], [])


def test_module_commands_uncovered_reported_not_blocked(tmp_path: Path, monkeypatch):
    _write_modcfg(tmp_path)
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["scripts/build.py", "services/api/y.py"])
    cmds, report = fgc.module_commands(tmp_path, "dev", ["precommit", "review", "doc-sync"])
    assert "ruff check services/api" in cmds  # 커버된 모듈은 실행
    assert any("scripts/build.py" in line for line in report)  # 미커버는 리포트로만


def test_module_commands_failopen_no_config(tmp_path: Path):
    assert fgc.module_commands(tmp_path, "dev", ["precommit"]) == ([], [])


def test_match_modules_prefix_and_empty_path():
    mods = [{"name": "api", "path": "services/api/"}, {"name": "app", "path": ""}]
    # 빈 path 는 전체 매칭(단일스택 단일모듈). 명시 path 가 먼저 매칭되면 그쪽.
    matched, uncovered = fgc._match_modules(["services/api/a.py", "README.md"], mods)
    assert {m["name"] for m in matched} == {"api", "app"}
    assert uncovered == []


def test_module_commands_output_splits_streams(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    _write_modcfg(tmp_path)
    (tmp_path / "vdev-tiers.yaml").write_text(
        "tiers:\n  dev:\n    gates: [precommit, review]\n", encoding="utf-8"
    )
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:feature/x", encoding="utf-8")
    monkeypatch.setattr(fgc, "_current_branch", lambda _r: "feature/x")
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["scripts/x.py", "services/api/y.py"])
    fgc.module_commands_output()
    out = capsys.readouterr()
    assert "ruff check services/api" in out.out  # 명령 → stdout
    assert "scripts/x.py" in out.err  # 미커버 → stderr


def test_module_commands_output_empty_when_precommit_gate_removed(
    tmp_path: Path, monkeypatch, capsys
):
    # tiers.yaml dev gates 에 precommit 이 없으면 변경 모듈이 있어도 명령이 나오지 않음.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    _write_modcfg(tmp_path)
    (tmp_path / "vdev-tiers.yaml").write_text(
        "tiers:\n  dev:\n    gates: [review]\n", encoding="utf-8"
    )
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:feature/x", encoding="utf-8")
    monkeypatch.setattr(fgc, "_current_branch", lambda _r: "feature/x")
    monkeypatch.setattr(fgc, "_changed_files", lambda _r: ["services/api/y.py"])
    fgc.module_commands_output()
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""


def test_resolve_worktree_prints_committing_worktree(tmp_path: Path):
    main, wt = _repo_with_worktree(tmp_path)
    hook_json = json.dumps(
        {"cwd": str(main), "tool_input": {"command": f'git -C "{wt}" commit -m x'}}
    )
    proc = run_bounded(
        [sys.executable, str(Path(fgc.__file__)), "--resolve-worktree"],
        text=True,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(main),
            "VWAY_HOOK_JSON": hook_json,
            "PYTHONUTF8": "1",
        },
    )
    printed = proc.stdout.strip()
    assert printed and os.path.samefile(printed, wt)


def test_resolve_worktree_says_nothing_when_there_is_no_worktree(tmp_path: Path):
    # 호환 alias 는 main 과 **다른** 트리만 냄. 빈 출력은 러너의 `[ -n "$_wt" ]` 가 ROOT 를
    # 그대로 두게 하는, 재지정 없음의 표현(FAIL-OPEN). 구버전 러너도 같은 검사를 함.
    main, _wt = _repo_with_worktree(tmp_path)
    hook_json = json.dumps({"cwd": str(main), "tool_input": {"command": "git commit -m x"}})
    proc = run_bounded(
        [sys.executable, str(Path(fgc.__file__)), "--resolve-worktree"],
        text=True,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(main),
            "VWAY_HOOK_JSON": hook_json,
            "PYTHONUTF8": "1",
        },
    )
    assert proc.stdout.strip() == ""
