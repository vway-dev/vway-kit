"""Codex PostToolUse 페이로드가 무엇을 편집했는가 — apply_patch 헤더, 또는 셸로 돌린 패치.

- 판정 근거는 `tool_input.command` 하나 — `tool_response` 는 적용 안 한 패치도 인용할 수 있음.
- Bash 는 `*** Begin Patch` … `*** End Patch` 봉투가 있을 때만 편집. 마커를 인용만 하는
  `grep`·`echo` 는 편집 아님(아니면 읽기마다 review·doc-sync 가 서로를 지움).
- CLI 종료 코드가 "편집 아님"(0)과 "편집인데 경로를 못 댐"(3)·"판정 불가"(4)를 가름 — 훅의
  cwd 폴백이 이 구분에 기댐.
- 픽스처 셋은 상류에서 실측한 Codex 페이로드 그대로.
"""

import json
import sys
from pathlib import Path, PureWindowsPath

from scripts.harness.codex.hook_io import classify, edited_paths
from tests._proc import run_bounded

FIX = Path(__file__).parent / "fixtures"
HOOK_IO = Path(__file__).resolve().parents[3] / "scripts" / "harness" / "codex" / "hook_io.py"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _norm(paths):
    return [PureWindowsPath(p).as_posix() for p in paths]


def test_apply_patch_headers_resolve_against_cwd():
    assert _norm(edited_paths(_load("post_apply_patch.json"))) == [
        "C:/host/repo/note.txt",
        "C:/host/repo/src/a.py",
        "C:/host/repo/src/b.py",
        "C:/host/repo/old/c.py",
    ]


def test_patch_run_through_the_shell_counts():
    assert _norm(edited_paths(_load("post_bash_patch.json"))) == ["C:/host/repo/한글/파일.md"]


def test_plain_shell_command_edits_nothing():
    assert edited_paths(_load("post_bash_plain.json")) == []


def test_garbage_is_nothing():
    assert edited_paths({}) == [] and edited_paths({"tool_input": {"command": 5}}) == []


def test_bash_without_begin_patch_ignores_header_shaped_lines():
    """헤더처럼 생긴 줄을 출력만 하는 Bash(diff 출력, cat)는 패치가 아님 — 셸 안 apply_patch 와
    가르는 것은 `*** Begin Patch` 마커이고, `git add -A` 만으로는 헤더 줄이 없어 이 구분을
    못 박음."""
    payload = {
        "cwd": "C:\\host\\repo",
        "tool_name": "Bash",
        "tool_input": {"command": "cat <<'EOF'\n*** Update File: x.py\nEOF"},
    }
    assert edited_paths(payload) == []


def _bash_payload(command: str) -> dict:
    return {"cwd": "C:\\host\\repo", "tool_name": "Bash", "tool_input": {"command": command}}


def _patch(cd_prefix: str, path: str) -> str:
    body = f"*** Begin Patch\n*** Update File: {path}\n*** End Patch"
    return f"{cd_prefix} apply_patch <<'EOF'\n{body}\nEOF"


def test_cd_relative_prefix_resolves_headers_there():
    command = _patch("cd sub &&", "a.py")
    assert _norm(edited_paths(_bash_payload(command))) == ["C:/host/repo/sub/a.py"]


def test_cd_chain_of_quoted_and_bare_segments_joined_by_mixed_separators():
    command = _patch('cd "a b" ; cd c &&', "x.py")
    assert _norm(edited_paths(_bash_payload(command))) == ["C:/host/repo/a b/c/x.py"]


def test_cd_with_a_variable_falls_back_to_the_payload_cwd():
    command = _patch("cd $X &&", "a.py")
    assert _norm(edited_paths(_bash_payload(command))) == ["C:/host/repo/a.py"]


def test_cd_absolute_dir_replaces_the_cwd_entirely():
    command = _patch("cd /other/place &&", "a.py")
    assert edited_paths(_bash_payload(command)) == ["/other/place/a.py"]


def test_cli_prints_utf8_one_per_line():
    """`PYTHONUTF8=0` + 빈 PATH — 로캘 코덱(Windows cp949)으로 한글 경로를 읽고 쓰면 인코딩 오류로
    경로가 사라짐(Invariant 2). 이 머신은 사용자 env 가 `PYTHONUTF8=1` 이라 명시로 꺼야 재현됨."""
    raw = (FIX / "post_bash_patch.json").read_bytes()
    run = run_bounded(
        [sys.executable, str(HOOK_IO), "edited-paths"],
        input=raw,
        env={"PYTHONUTF8": "0", "PATH": ""},
    )
    assert run.returncode == 0, run.stderr
    assert "한글/파일.md" in PureWindowsPath(run.stdout.decode("utf-8").strip()).as_posix()


def test_only_a_patch_envelope_in_the_command_makes_a_bash_edit():
    quoted = _bash_payload('grep -n "*** Begin Patch" hook.sh')
    echoed = _bash_payload("echo '*** Begin Patch'")
    output = {**_bash_payload("git diff HEAD"), "tool_response": _patch("", "a.py")}
    assert classify(quoted) == classify(echoed) == classify(output) == (False, [])
    argument = _bash_payload("apply_patch '*** Begin Patch\n*** Update File: a.py\n*** End Patch'")
    assert classify(argument)[0] is True


def test_an_edit_with_no_placeable_path_is_still_an_edit():
    assert classify({"tool_name": "apply_patch", "tool_input": {"input": "x"}}) == (True, [])
    empty = {
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n*** End Patch"},
    }
    assert classify(empty) == (True, [])


def _cli(raw: bytes) -> int:
    return run_bounded([sys.executable, str(HOOK_IO), "edited-paths"], input=raw).returncode


def test_cli_exit_status_separates_not_an_edit_from_an_unplaced_one():
    assert _cli(json.dumps(_bash_payload("git diff HEAD")).encode()) == 0
    empty = {
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n*** End Patch"},
    }
    assert _cli(json.dumps(empty).encode()) == 3
    assert _cli(b"not json at all") == 4


def test_a_cut_payload_is_judged_by_tool_name_and_surviving_command():
    whole = json.dumps(_bash_payload(_patch("", "a.py")) | {"tool_response": "x" * 50})
    assert _cli(whole[:-20].encode()) == 3  # 명령의 봉투가 잘림에서 살아남음
    cut_bash = json.dumps(_bash_payload(_patch("", "a.py" + "x" * 500)))
    assert _cli(cut_bash[: cut_bash.index("*** End Patch")].encode()) == 0
    patch = json.dumps({"tool_name": "apply_patch", "tool_input": {"command": "*** Begin"}})
    assert _cli(patch[:-10].encode()) == 3


def test_a_tab_indented_dash_heredoc_patch_counts():
    body = "\t*** Begin Patch\n\t*** Update File: a.py\n\t*** End Patch"
    command = f"apply_patch <<-'EOF'\n{body}\n\tEOF"
    assert _norm(edited_paths(_bash_payload(command))) == ["C:/host/repo/a.py"]


def test_an_ansi_c_quoted_patch_counts():
    command = r"apply_patch $'*** Begin Patch\n*** Update File: 한글.py\n*** End Patch\n'"
    assert _norm(edited_paths(_bash_payload(command))) == ["C:/host/repo/한글.py"]


def test_an_ansi_c_quoted_mention_without_an_envelope_is_not_an_edit():
    assert classify(_bash_payload(r"echo $'*** Begin Patch\nno end'")) == (False, [])


def test_a_cut_ansi_c_patch_still_reads_as_an_edit():
    command = r"apply_patch $'*** Begin Patch\n*** Update File: a.py\n*** End Patch'"
    whole = json.dumps(_bash_payload(command) | {"tool_response": "x" * 50})
    assert _cli(whole[:-20].encode()) == 3
