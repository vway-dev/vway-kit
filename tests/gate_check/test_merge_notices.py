"""판정 없이, 또는 경고와 함께 통과시킨 머지가 그 사실을 말하는지 — merge 검사의 통지."""

import json

import scripts.vdev_gate_check as fgc
from tests.gate_check._helpers import _run_merge_check, _write_policy


def _note(capsys) -> str:
    return json.loads(capsys.readouterr().out)["systemMessage"]


def test_a_verdict_that_raises_passes_and_says_so(monkeypatch, tmp_path, capsys):
    _write_policy(tmp_path)
    monkeypatch.setattr(fgc, "_judged", lambda command, masked: 1 / 0)
    assert _run_merge_check(monkeypatch, tmp_path, "git merge feature/x", "dev") == 0
    note = _note(capsys)
    assert "판정 실패" in note and "ZeroDivisionError" in note


def test_a_judged_merge_says_nothing(monkeypatch, tmp_path, capsys):
    _write_policy(tmp_path)
    assert _run_merge_check(monkeypatch, tmp_path, "git merge --squash feature/x", "dev") == 0
    assert capsys.readouterr().out == ""


def test_a_block_stays_a_plain_reason(monkeypatch, tmp_path, capsys):
    _write_policy(tmp_path)
    code = _run_merge_check(monkeypatch, tmp_path, "git merge feature/x", "dev")
    assert code == fgc.BLOCK_EXIT_CODE
    out = capsys.readouterr().out
    assert "--squash" in out and "systemMessage" not in out
