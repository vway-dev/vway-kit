"""`--harness codex` 갈래 — Codex 편집(apply_patch, 또는 셸로 돌린 패치)이 증거를 지우는가.

- Codex 는 편집을 `file_path` 가 아니라 `tool_input.command` 의 패치 헤더로 알리고, 경로는 세션
  `cwd` 기준 상대 경로. 무엇이 편집인지는 `scripts/harness/codex/hook_io.py` 가 정함.
- 평범한 Bash(`git add -A`)는 마커를 남김 — 커밋 직전 스테이징이 그 커밋이 번 증거를 지우면 안 됨.
- Codex 는 `CLAUDE_PROJECT_DIR` 를 안 줌 → 경로를 못 댄 편집·돌지 못한 hook_io 는 페이로드
  `cwd` 의 루트를 통째로 지움(안전한 방향).
- 64 KB 읽기 상한은 바이트 — 한글 페이로드에서 문자 수로 재면 잘린 것을 온전하게 읽음.
"""

import json
import os
from pathlib import Path

import pytest

from tests._hook_args import BAD_HARNESS_ARGS
from tests._proc import run_bounded
from tests.invalidate_gate_markers._helpers import (
    BASH,
    MARKERS,
    SCRIPT,
    pytestmark,  # noqa: F401 — 모듈 수준 skip 은 이 이름으로만 걸림
    repo,
    vdev,
    worktree_of,
)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    vdev(repo).mkdir(parents=True)
    for m in MARKERS:
        (vdev(repo) / m).write_text("", encoding="utf-8")
    return repo


def _env(**extra: str) -> dict[str, str]:
    """실제 환경에서 `CLAUDE_PROJECT_DIR` 만 뺌 — Codex 훅은 그것 없이 돎. 손으로 만든 env 는
    Windows 에서 bash 자신이 쓰는 것(SYSTEMROOT, TEMP)을 떨어뜨림."""
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.update(extra)
    return env


def _run_raw(raw: bytes, script: Path = SCRIPT, **env: str):
    return run_bounded(
        [BASH, script.as_posix(), "--harness", "codex"], input=raw, env=_env(**env), timeout=30
    )


def _run(repo: Path, tool: str, command: str):
    payload = {
        "cwd": str(repo),
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {"command": command},
    }
    return _run_raw(json.dumps(payload).encode())


def _voided(repo: Path) -> bool:
    return not any((vdev(repo) / m).exists() for m in MARKERS)


def _kept(repo: Path) -> bool:
    return all((vdev(repo) / m).exists() for m in MARKERS)


def _run_payload(repo: Path, payload: dict, script: Path = SCRIPT) -> None:
    body = {"cwd": str(repo), "hook_event_name": "PostToolUse", **payload}
    run = _run_raw(json.dumps(body).encode(), script)
    assert run.returncode == 0, run.stderr


def test_apply_patch_voids(tmp_path):
    repo = _repo(tmp_path)
    run = _run(repo, "apply_patch", "*** Begin Patch\n*** Update File: a.txt\n*** End Patch")
    assert run.returncode == 0, run.stderr
    assert _voided(repo)
    assert b"review" in run.stdout and b"doc-sync" in run.stdout, "무효화 알림이 없다"


def test_bash_patch_voids(tmp_path):
    repo = _repo(tmp_path)
    command = "apply_patch <<'EOF'\n*** Begin Patch\n*** Update File: a.txt\n*** End Patch\nEOF"
    _run(repo, "Bash", command)
    assert _voided(repo)


def test_plain_bash_keeps_evidence(tmp_path):
    repo = _repo(tmp_path)
    run = _run(repo, "Bash", "git add -A")
    assert run.returncode == 0, run.stderr
    assert _kept(repo), "커밋 직전 `git add` 가 그 커밋이 번 증거를 지웠다"


def test_evidence_dir_edit_is_ignored(tmp_path):
    repo = _repo(tmp_path)
    command = "*** Begin Patch\n*** Add File: .claude/vway-kit/.vdev/x\n*** End Patch"
    _run(repo, "apply_patch", command)
    assert _kept(repo)


def test_oversized_payload_still_voids_via_the_cwd_fallback(tmp_path):
    """64 KB `head -c` 상한 너머는 잘려 JSON 파싱이 실패하고 hook_io.py 는 경로를 못 냄 — 실측한
    모든 Codex 페이로드에서 `cwd` 가 `tool_input` 앞이라 잘림에서 살아남고, 그 repo 를 통째로
    지움."""
    repo = _repo(tmp_path)
    padding = "x" * 100_000
    command = f"*** Begin Patch\n*** Update File: a.txt\n+{padding}\n*** End Patch"
    run = _run(repo, "apply_patch", command)
    assert len(json.dumps({"tool_input": {"command": command}})) > 65536
    assert run.returncode == 0, run.stderr
    assert _voided(repo)


def test_spaced_json_voids_too(tmp_path):
    """`json.dumps(indent=2)` 는 콜론마다 공백을 둠 — 사전 필터가 손으로 만든 페이로드의 압축
    철자에 기대면 안 됨."""
    repo = _repo(tmp_path)
    payload = {
        "cwd": str(repo),
        "hook_event_name": "PostToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n*** Update File: a.txt\n*** End Patch"},
    }
    _run_raw(json.dumps(payload, indent=2).encode())
    assert _voided(repo)


def test_oversized_non_ascii_payload_is_measured_in_bytes(tmp_path):
    """Codex 는 날 UTF-8 을 보내고, UTF-8 로캘의 `${#var}` 는 문자를 셈 — 64 KB 바이트 상한을 한참
    넘는 한글 패치도 65536 문자 미만이라 문자 수로 재면 온전하게 읽힘. Git Bash here-string 은 이
    크기에서 멈추므로 훅이 파이프로 넘기는지도 여기서 걸림(시간 초과 = 실패)."""
    repo = _repo(tmp_path)
    command = f"*** Begin Patch\n*** Update File: a.txt\n+{'가' * 30_000}\n*** End Patch"
    payload = {
        "cwd": str(repo),
        "hook_event_name": "PostToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": command},
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert len(raw) > 65536 > len(raw.decode("utf-8"))
    # C.UTF-8 은 Git Bash 와 기본 Ubuntu 모두에 있음 — en_US.UTF-8 은 생성 안 된 곳이 있음.
    run = _run_raw(raw, LANG="C.UTF-8", LC_ALL="C.UTF-8")
    assert run.returncode == 0, run.stderr
    assert _voided(repo)


def test_a_patch_payload_without_tool_input_command_voids_via_the_cwd_fallback(tmp_path):
    """hook_io.py 는 `tool_input.command` 만 읽음 — 다른 키 밑의 패치는 경로를 못 댐."""
    repo = _repo(tmp_path)
    payload = {
        "cwd": str(repo),
        "hook_event_name": "PostToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"input": "*** Begin Patch\n*** Update File: a.txt\n*** End Patch"},
    }
    run = _run_raw(json.dumps(payload).encode())
    assert run.returncode == 0, run.stderr
    assert _voided(repo)


def test_an_undecodable_patch_payload_under_the_cap_voids_via_the_cwd_fallback(tmp_path):
    repo = _repo(tmp_path)
    raw = json.dumps({"cwd": str(repo), "tool_name": "apply_patch"}).encode()[:-1] + b", oops"
    run = _run_raw(raw)
    assert run.returncode == 0, run.stderr
    assert _voided(repo)


def test_a_placed_patch_outside_any_repo_does_not_fall_back_to_cwd(tmp_path):
    """폴백은 경로 없는 패치용 — 경로가 모든 repo 밖에 놓인 패치는 자리를 댄 것이고, cwd 의
    증거는 그것이 편집한 것이 아님."""
    repo = _repo(tmp_path)
    outside = (tmp_path / "scratch" / "a.txt").as_posix()
    _run(repo, "apply_patch", f"*** Begin Patch\n*** Update File: {outside}\n*** End Patch")
    assert _kept(repo)


ENVELOPE = "*** Begin Patch\n*** Update File: a.txt\n@@\n-a\n+b\n*** End Patch"


def test_a_bash_read_whose_output_holds_a_patch_keeps_evidence(tmp_path):
    """Codex 는 Bash 로 파일을 읽음 — 패치를 담은 파일의 `git diff` 는 편집이 아니고, 여기서
    지우면 읽기마다 review 와 doc-sync 가 서로를 지움."""
    repo = _repo(tmp_path)
    _run_payload(
        repo,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git diff HEAD"},
            "tool_response": f"+{ENVELOPE}",
        },
    )
    assert not _voided(repo)


def test_a_bash_command_quoting_the_marker_keeps_evidence(tmp_path):
    repo = _repo(tmp_path)
    command = 'grep -n "*** Begin Patch" hooks/invalidate-gate-markers.sh'
    _run_payload(repo, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert not _voided(repo)


def test_a_bash_patch_envelope_without_a_parsable_header_voids(tmp_path):
    repo = _repo(tmp_path)
    command = "apply_patch <<'EOF'\n*** Begin Patch\n*** Frobnicate: a.txt\n*** End Patch\nEOF"
    _run_payload(repo, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert _voided(repo)


def test_a_shell_patch_in_ansi_c_quotes_voids(tmp_path):
    repo = _repo(tmp_path)
    command = r"apply_patch $'*** Begin Patch\n*** Update File: a.txt\n*** End Patch\n'"
    _run_payload(repo, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert _voided(repo)


def test_a_shell_patch_in_a_tab_stripping_heredoc_voids(tmp_path):
    repo = _repo(tmp_path)
    body = "\t*** Begin Patch\n\t*** Update File: a.txt\n\t*** End Patch"
    command = f"apply_patch <<-'EOF'\n{body}\n\tEOF"
    _run_payload(repo, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert _voided(repo)


def test_an_apply_patch_with_no_headers_voids(tmp_path):
    repo = _repo(tmp_path)
    command = "*** Begin Patch\n*** End Patch"
    _run_payload(repo, {"tool_name": "apply_patch", "tool_input": {"command": command}})
    assert _voided(repo)


def _hook_without_hook_io(tmp_path: Path) -> Path:
    """hook_io.py 가 없는 트리에 훅만 둠 — python3 는 돌지만 파일을 못 엶."""
    hooks = tmp_path / "bare" / "hooks"
    hooks.mkdir(parents=True)
    copy = hooks / SCRIPT.name
    copy.write_bytes(SCRIPT.read_bytes())
    return copy


def test_an_unavailable_hook_io_voids_a_prefiltered_payload(tmp_path):
    repo = _repo(tmp_path)
    command = "*** Begin Patch\n*** Update File: a.txt\n*** End Patch"
    payload = {"tool_name": "apply_patch", "tool_input": {"command": command}}
    _run_payload(repo, payload, _hook_without_hook_io(tmp_path))
    assert _voided(repo)


def test_an_unavailable_hook_io_leaves_a_payload_the_prefilter_rejects(tmp_path):
    repo = _repo(tmp_path)
    payload = {"tool_name": "Bash", "tool_input": {"command": "git add -A"}}
    _run_payload(repo, payload, _hook_without_hook_io(tmp_path))
    assert not _voided(repo)


def test_an_oversized_bash_patch_cut_before_its_end_keeps_evidence(tmp_path):
    """상한에서 잘린 Bash 명령의 남은 텍스트에는 온전한 봉투가 없고, 그것은 마커를 인용한 명령과
    가를 수 없음 — 그래서 Bash 는 남기고 apply_patch 는 지움."""
    repo = _repo(tmp_path)
    command = "apply_patch <<'EOF'\n*** Begin Patch\n*** Update File: a.txt\n+" + "x" * 100_000
    command += "\n*** End Patch\nEOF"
    _run_payload(repo, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert not _voided(repo)


def test_the_opt_out_switch_holds_for_codex_edits_too(tmp_path):
    """`gate_evidence.invalidate_on_edit: false` 는 하네스를 가리지 않음 — 스위치는 트리마다 묻는
    공용 루프에 있고, Codex 갈래는 대상만 정함."""
    repo = _repo(tmp_path)
    config = repo / ".claude" / "vway-kit" / "config" / "vdev-config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("gate_evidence:\n  invalidate_on_edit: false\n", encoding="utf-8")
    _run(repo, "apply_patch", "*** Begin Patch\n*** Update File: a.txt\n*** End Patch")
    assert _kept(repo)


def test_claude_payload_under_codex_flag_is_not_read_as_a_claude_edit(tmp_path):
    """`--harness codex` 는 Claude 의 `file_path` 모양을 읽지 않음 — 하네스는 훅 엔트리가
    이름 대고 환경에서 추측하지 않음. Codex 에는 `CLAUDE_PROJECT_DIR` 도 없음."""
    repo = _repo(tmp_path)
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "a.py")}}
    _run_payload(repo, payload)
    assert _kept(repo)


def test_a_worktree_edit_also_voids_the_session_cwd_view_of_the_same_repo(tmp_path):
    """게이트는 커밋의 worktree 를 이름 대지 못하면 세션 트리로 물러섬 — 그래서 링크된
    worktree 의 편집은 Claude 경로처럼 cwd 루트의 증거도 지움."""
    main = repo(tmp_path / "main")
    wt = worktree_of(main, tmp_path / "wt")
    edited = (wt / "a.txt").as_posix()
    command = f"*** Begin Patch\n*** Update File: {edited}\n*** End Patch"
    _run_payload(main, {"tool_name": "apply_patch", "tool_input": {"command": command}})
    assert _voided(wt) and _voided(main)


def test_a_worktree_edit_voids_the_repo_of_a_subdirectory_cwd(tmp_path):
    main = repo(tmp_path / "main")
    sub = main / "sub" / "deep"
    sub.mkdir(parents=True)
    wt = worktree_of(main, tmp_path / "wt")
    edited = (wt / "a.txt").as_posix()
    command = f"*** Begin Patch\n*** Update File: {edited}\n*** End Patch"
    _run_payload(sub, {"tool_name": "apply_patch", "tool_input": {"command": command}})
    assert _voided(wt) and _voided(main)


def test_an_edit_in_another_repo_keeps_the_session_cwd_evidence(tmp_path):
    main = repo(tmp_path / "main")
    other = repo(tmp_path / "other")
    edited = (other / "a.txt").as_posix()
    command = f"*** Begin Patch\n*** Update File: {edited}\n*** End Patch"
    _run_payload(main, {"tool_name": "apply_patch", "tool_input": {"command": command}})
    assert _voided(other) and not _voided(main)


def _run_bad(args: tuple[str, ...], payload: dict, **env: str):
    return run_bounded(
        [BASH, SCRIPT.as_posix(), *args],
        input=json.dumps(payload).encode(),
        env=_env(**env),
        timeout=30,
    )


@pytest.mark.parametrize("args", BAD_HARNESS_ARGS)
def test_an_unknown_harness_voids_the_cwd_tree_and_fails_loudly(tmp_path, args):
    """Claude 로 읽으면 Codex 페이로드엔 file_path 가 없어 모든 편집이 증거를 조용히 남김. 오타 난
    엔트리는 편집 자리를 못 대므로 세션 트리의 증거를 지우고, exit 2 가 잘못된 값을 에이전트
    앞에 내놓음."""
    repo = _repo(tmp_path)
    command = "*** Begin Patch\n*** Update File: a.txt\n*** End Patch"
    run = _run_bad(
        args, {"cwd": str(repo), "tool_name": "apply_patch", "tool_input": {"command": command}}
    )
    assert run.returncode == 2, run.stderr
    assert b"--harness" in run.stderr
    assert "무효화: review, doc-sync".encode() in run.stderr
    assert _voided(repo)


def test_an_unknown_harness_voids_the_project_dir_without_a_cwd(tmp_path):
    repo = _repo(tmp_path)
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/nowhere/a.txt"}}
    run = _run_bad(("--harness", "cdx"), payload, CLAUDE_PROJECT_DIR=repo.as_posix())
    assert run.returncode == 2, run.stderr
    assert _voided(repo)


def test_an_unknown_harness_with_no_tree_to_void_still_fails_loudly(tmp_path):
    run = _run_bad(("--harness", "cdx"), {"cwd": str(tmp_path), "tool_name": "Bash"})
    assert run.returncode == 2, run.stderr
    assert b"--harness" in run.stderr
    assert "무효화: 없음".encode() in run.stderr


def test_an_exported_voided_does_not_leak_into_the_bad_args_report(tmp_path):
    run = _run_bad(("--harness", "cdx"), {"cwd": str(tmp_path)}, voided="review")
    assert run.returncode == 2, run.stderr
    assert "무효화: 없음".encode() in run.stderr


def test_the_bad_args_report_reaches_the_agent_as_printable_ascii(tmp_path):
    """exit 2 는 stderr 를 에이전트에 넘김 — 훅 엔트리의 제어 바이트가 거기 닿으면 안 됨."""
    command = """exec bash "$0" --harness "$(printf 'a\\033b')" """
    run = run_bounded(
        [BASH, "-c", command, SCRIPT.as_posix()],
        input=json.dumps({"cwd": str(tmp_path)}).encode(),
        env=_env(),
        timeout=30,
    )
    assert run.returncode == 2, run.stderr
    assert b"--harness a?b" in run.stderr and b"\x1b" not in run.stderr
