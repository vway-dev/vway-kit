"""measure — config 스위치, 착수 시각, 출처 탐색, CLI 의 UTF-8 출력."""

import json
import re
import sys
from pathlib import Path

from scripts.worklog import measure, parse_created
from tests._non_utf8 import non_utf8_env
from tests._proc import run_bounded
from tests.worklog._helpers import m, prompt, said, tool_result, tool_use, write_jsonl

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "worklog.py"


def setup(tmp_path: Path, enabled: bool = True):
    """루트 이름은 한글 — slug 에서 비ASCII 가 `-` 로 접히고 cwd 비교는 원문으로 하는지 함께 잼.
    루트는 git 저장소가 아님 — reflog 가 없으면 전환이 없는 것으로 보고 측정을 계속함."""
    root = tmp_path / "작업"
    root.mkdir()
    cfg = tmp_path / "vdev-config.yaml"
    cfg.write_text(f"alm:\n  worklog: {'true' if enabled else 'false'}\n", encoding="utf-8")
    doc = tmp_path / "task.md"
    doc.write_text(
        f"# Task\n\n## Overview\n**Created:** {m(0).astimezone():%Y-%m-%d %H:%M}\n",
        encoding="utf-8",
    )
    claude = tmp_path / "claude"
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(root))
    write_jsonl(claude / "projects" / slug / "s1.jsonl", [prompt(0, cwd=str(root)), said(30)])
    return root, cfg, doc, claude, tmp_path / "codex"


def run(root, cfg, doc, claude, codex, now=None):
    return measure(cfg, doc, root, "feature/x", now or m(60), claude, codex)


def test_disabled_reports_only_the_start(tmp_path):
    out = run(*setup(tmp_path, enabled=False))
    assert out["enabled"] is False
    assert out["started"] == m(0).astimezone().strftime("%Y-%m-%d %H:%M")
    assert "active" not in out and "completed" not in out


def test_absent_key_is_disabled(tmp_path):
    root, cfg, doc, claude, codex = setup(tmp_path)
    cfg.write_text("alm:\n  provider: recoble\n", encoding="utf-8")
    assert run(root, cfg, doc, claude, codex)["enabled"] is False


def test_enabled_measures_this_worktree(tmp_path):
    out = run(*setup(tmp_path))
    assert out["active"] == "00:30"
    assert out["sessions"] == {"claude": 1, "codex": 0}
    assert out["completed"] == m(60).astimezone().strftime("%Y-%m-%d %H:%M")
    # 루트가 git 저장소가 아니라 worktree 목록을 못 읽음 — 거르기를 건너뛴 것이 경고로 드러남.
    assert any("worktree 목록" in w for w in out["warnings"])


def test_created_in_another_format_warns(tmp_path):
    root, cfg, doc, claude, codex = setup(tmp_path)
    doc.write_text("**Created:** [timestamp]\n", encoding="utf-8")
    out = run(root, cfg, doc, claude, codex)
    assert "started" not in out and "active" not in out
    assert any("Created" in w for w in out["warnings"])


def test_parse_created_reads_local_minutes(tmp_path):
    doc = tmp_path / "t.md"
    doc.write_bytes(b"**Created:** 2026-10-07 14:05\r\n")
    t = parse_created(doc)
    assert t is not None and t.tzinfo is not None
    assert t.astimezone().strftime("%Y-%m-%d %H:%M") == "2026-10-07 14:05"


def test_sessions_outside_the_window_do_not_count(tmp_path):
    out = run(*setup(tmp_path), now=m(10))
    assert out["active"] == "00:10"


def test_cli_prints_utf8_json_on_a_non_utf8_host(tmp_path):
    root, cfg, doc, claude, codex = setup(tmp_path)
    proc = run_bounded(
        [
            sys.executable,
            str(SCRIPT),
            "measure",
            "--config",
            str(cfg),
            "--task-doc",
            str(doc),
            "--root",
            str(root),
            "--branch",
            "feature/x",
            "--now",
            m(60).isoformat(),
            "--claude-home",
            str(claude),
            "--codex-home",
            str(codex),
        ],
        env=non_utf8_env(),
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert json.loads(proc.stdout.decode("utf-8"))["active"] == "00:30"


def test_cli_never_fails_on_missing_inputs(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("alm:\n  worklog: true\n", encoding="utf-8")
    proc = run_bounded(
        [
            sys.executable,
            str(SCRIPT),
            "measure",
            "--task-doc",
            str(tmp_path / "없음.md"),
            "--config",
            str(cfg),
            "--root",
            str(tmp_path),
        ],
        env=non_utf8_env(),
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout.decode("utf-8"))
    assert out["enabled"] is True and "active" not in out and out["warnings"]


def test_disabled_does_not_warn_about_an_old_created_line(tmp_path):
    root, cfg, doc, claude, codex = setup(tmp_path, enabled=False)
    doc.write_text("**Created:** 2026-01-07T05:00:00\n", encoding="utf-8")
    out = run(root, cfg, doc, claude, codex)
    assert out["warnings"] == [] and "started" not in out


def test_waits_and_tier_from_the_main_worktree_reach_a_linked_worktree(tmp_path):
    """record-wait 는 프로젝트(메인 worktree)의 .vdev 에 씀 — measure 의 루트는 작업 worktree."""
    main = tmp_path / "repo"
    main.mkdir()
    for args in (
        ["init", "-q", "-b", "dev"],
        ["commit", "-q", "--allow-empty", "-m", "a"],
        ["worktree", "add", "-q", "-b", "feature/x", str(main / "wt")],
    ):
        run_bounded(
            ["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True
        )
    work = main / "wt"
    vdev = main / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:feature/x\n", encoding="utf-8")
    (vdev / "waits").write_text(f"{m(2).isoformat()} s1\n", encoding="utf-8")
    cfg = tmp_path / "c.yaml"
    cfg.write_text("alm:\n  worklog: true\n", encoding="utf-8")
    doc = tmp_path / "t.md"
    doc.write_text(f"**Created:** {m(0).astimezone():%Y-%m-%d %H:%M}\n", encoding="utf-8")
    claude = tmp_path / "claude"
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(work))
    records = [prompt(0), tool_use(1, "b"), tool_result(61, "b"), said(62)]
    for rec in records:
        rec["cwd"] = str(work)
    write_jsonl(claude / "projects" / slug / "s1.jsonl", records)
    # 권한 대기 2→61 은 15분으로 잘림: 2 + 15 + 1
    out = measure(cfg, doc, work, None, m(70), claude, tmp_path / "codex")
    assert out["active"] == "00:18", out
