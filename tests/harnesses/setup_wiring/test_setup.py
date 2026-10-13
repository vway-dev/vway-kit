"""`run_setup` 의 하네스 배선 — 켜진 하네스마다 게이트를 등록하고, 판정이 그 등록을 되읽는지 잼.

- `[커밋 게이트]` 는 `register_gates`, `[복사]` 는 `copy_artifacts(plugin, host, names)`.
- `_gate_problems(host, plugin, harnesses)` 는 `gate_files(harnesses)` 를 물음 — 빠지거나 깨진
  Codex wrapper 도 게이트가 돌지 않을 이유로 보고됨.
- codex 를 목록에서 뺀 호스트의 남은 훅은 보고만 하고 지우지 않음.
"""

import json
from pathlib import Path

import scripts.vdev_init_setup as vis
from tests.harnesses.setup_wiring._helpers import HOOKS, _cfg, _codex
from tests.vdev_init._helpers import PLUGIN

WRAPPERS = Path(".claude/vway-kit/scripts/harness/codex")


def _closed(_host):
    raise PermissionError(13, "Permission denied")


def test_claude_only_setup_writes_nothing_for_codex(tmp_path: Path):
    assert vis.run_setup(tmp_path, PLUGIN)
    assert not (tmp_path / ".codex").exists()
    assert not (tmp_path / ".claude/vway-kit/scripts/harness").exists()


def test_codex_setup_registers_both(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    assert vis.run_setup(tmp_path, PLUGIN)
    hooks = json.loads((tmp_path / HOOKS).read_text(encoding="utf-8"))
    assert _codex().GATE_ENTRY in hooks["hooks"]["PreToolUse"]
    settings = json.loads((tmp_path / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["PreToolUse"]
    assert (tmp_path / WRAPPERS / "gate.sh").is_file()
    assert (tmp_path / WRAPPERS / "gate.cmd").is_file()


def test_codex_setup_relays_trust_notes(tmp_path: Path, capsys):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    assert "trusted" in out and "/hooks" in out, out


def test_register_gates_is_just_the_claude_line_for_a_claude_only_host(tmp_path: Path):
    assert vis.register_gates(tmp_path, ["claude"]) == ["  [+] 커밋 게이트 등록 (settings.json)"]


def test_gate_problems_reports_a_missing_codex_registration(tmp_path: Path):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    (tmp_path / HOOKS).unlink()
    problems = vis._gate_problems(tmp_path, PLUGIN, ["claude", "codex"])
    assert any(".codex/hooks.json" in p for p in problems), problems
    # 등록만 지웠음 — 파일 누락 갈래가 아니라 codex.problems() 갈래가 발화해야 함.
    assert not any("gate.sh" in p or "gate.cmd" in p for p in problems), problems


def test_gate_problems_reports_a_missing_or_corrupt_codex_wrapper(tmp_path: Path):
    """컨트롤러 판정 1: 고정 `GATE_FILES` 가 아니라 `gate_files(harnesses)` 를 물음."""
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    assert vis.run_setup(tmp_path, PLUGIN)
    assert vis._gate_problems(tmp_path, PLUGIN, ["claude", "codex"]) == []
    (tmp_path / WRAPPERS / "gate.cmd").unlink()
    (tmp_path / WRAPPERS / "gate.sh").write_bytes(b"")
    problems = vis._gate_problems(tmp_path, PLUGIN, ["claude", "codex"])
    assert any("gate.sh" in p and "gate.cmd" in p for p in problems), problems
    # claude 전용 질문은 Codex wrapper 를 묻지 않음.
    assert vis._gate_problems(tmp_path, PLUGIN) == []


def test_a_missing_wrapper_fails_the_setup_verdict(tmp_path: Path, monkeypatch, capsys):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    real = vis.copy_artifacts

    def without_cmd(plugin, host, harnesses=("claude",)):
        out = real(plugin, host, harnesses)
        (host / WRAPPERS / "gate.cmd").unlink()
        return out

    monkeypatch.setattr(vis, "copy_artifacts", without_cmd)
    assert vis.run_setup(tmp_path, PLUGIN) is False
    assert "gate.cmd" in capsys.readouterr().out


def test_an_unresolvable_codex_installer_is_a_problem_not_a_crash(tmp_path: Path, monkeypatch):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)

    def _raise(_name):
        raise ImportError("codex install module cannot be imported")

    monkeypatch.setattr(vis.harness, "installer", _raise)
    problems = vis._gate_problems(tmp_path, PLUGIN, ["claude", "codex"])
    assert any("cannot be imported" in p for p in problems), problems


def test_a_harnesses_read_that_raises_costs_only_its_line(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(vis, "load_harnesses", _closed)
    assert vis.run_setup(tmp_path, PLUGIN) is True
    out = capsys.readouterr().out
    assert "[!] harnesses 를 읽지 못했습니다(Permission denied)" in out, out
    assert "기계적 셋업 완료" in out, out
    assert not (tmp_path / ".codex").exists()


def test_dropping_codex_reports_what_it_left_and_removes_nothing(tmp_path: Path, capsys):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    hooks = (tmp_path / HOOKS).read_bytes()
    _cfg(tmp_path, "harnesses: [claude]\n")
    capsys.readouterr()
    vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    notes = [line for line in out.splitlines() if "harnesses 에 codex 가 없지만" in line]
    assert len(notes) == 1, out
    assert ".codex/hooks.json" in notes[0] and "/vdev-uninstall" in notes[0], notes
    assert (tmp_path / HOOKS).read_bytes() == hooks


def test_a_claude_only_host_gets_no_leftover_note(tmp_path: Path, capsys):
    (tmp_path / ".codex").mkdir()
    (tmp_path / HOOKS).write_text("{ their own, broken", encoding="utf-8")
    vis.run_setup(tmp_path, PLUGIN)
    assert "harnesses 에 codex 가 없지만" not in capsys.readouterr().out


def test_leftover_note_is_suppressed_when_harnesses_read_raises(
    tmp_path: Path, monkeypatch, capsys
):
    """읽기 실패의 `["claude"]` 는 진짜 config 를 읽은 답이 아님 — 여전히 codex 가 있을 수 있음."""
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    hooks = (tmp_path / HOOKS).read_bytes()
    capsys.readouterr()
    monkeypatch.setattr(vis, "load_harnesses", _closed)
    assert vis.run_setup(tmp_path, PLUGIN) is True
    out = capsys.readouterr().out
    assert "harnesses 를 읽지 못했습니다" in out, out
    assert "harnesses 에 codex 가 없지만" not in out, out
    assert (tmp_path / HOOKS).read_bytes() == hooks


def test_leftover_note_is_suppressed_for_a_malformed_harnesses_value(tmp_path: Path, capsys):
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    _cfg(tmp_path, "harnesses: codex\n")
    capsys.readouterr()
    vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    assert "목록이어야 합니다" in out, out
    assert "harnesses 에 codex 가 없지만" not in out, out


def test_leftover_note_still_shows_beside_an_unrelated_unknown_name(tmp_path: Path, capsys):
    """목록 속 모르는 이름 하나의 `[!]` 는 목록을 못 믿을 이유가 아님."""
    _cfg(tmp_path, "harnesses: [claude, codex]\n")
    vis.run_setup(tmp_path, PLUGIN)
    _cfg(tmp_path, "harnesses: [claude, some-typo]\n")
    capsys.readouterr()
    vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    assert "알 수 없는 이름 'some-typo'" in out, out
    assert "harnesses 에 codex 가 없지만" in out, out


def test_an_unresolvable_codex_installer_costs_only_its_registration_line(
    tmp_path: Path, monkeypatch
):
    def _raise(_name):
        raise ImportError("codex install module cannot be imported")

    monkeypatch.setattr(vis.harness, "installer", _raise)
    out = vis.register_gates(tmp_path, ["claude", "codex"])
    assert out[0] == "  [+] 커밋 게이트 등록 (settings.json)"
    assert out[1].startswith("  [!] codex 게이트 설치 모듈을 불러오지 못했습니다"), out


def test_a_codex_leftovers_raise_keeps_the_lines_before_it(tmp_path: Path, monkeypatch, capsys):
    """`[커밋 게이트]` 는 생산자 셋(config 줄·등록·남은 Codex 훅) — 셋째가 raise 해도 앞 둘이
    이미 만든 줄(사용자가 고칠 `[!]`·게이트 등록 사실)은 찍혀 있어야 함."""
    _cfg(tmp_path, "harnesses: [claude, some-typo]\n")

    def _raise(_host, _names):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(vis, "codex_leftovers", _raise)
    vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    step = out.split("[커밋 게이트]\n", 1)[1].split("\n[", 1)[0]
    assert "알 수 없는 이름 'some-typo'" in step, step
    assert "  [+] 커밋 게이트 등록 (settings.json)" in step, step
    assert "[!] 이 단계를 끝내지 못했습니다(Permission denied)" in step, step
