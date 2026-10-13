"""Codex 게이트 wrapper 만 — 가짜 러너를 뒤에 두고 종료 코드 변환·문구 재작성·Git Bash 탐지를 잼.

- Codex 는 exit 2 가 아니라 deny JSON 을 읽음(Windows pwsh 가 2 를 1 로 바꿈) → wrapper 가
  러너의 2 만 0 으로 바꾸고 나머지는 그대로 전달해야 함.
- 문구 재작성이 실패해도 러너의 원문이 나가야 함 — JSON 이 곧 차단이라 사라지면 게이트가 없음.
- 셸 구동은 `run_bounded`, bash 는 `tests/_bash.py` 가 고른 절대 경로(이름 `bash` 는 WSL 스텁).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._bash import BASH
from tests._proc import run_bounded

REPO = Path(__file__).resolve().parents[3]
WRAP_SH = REPO / "scripts" / "harness" / "codex" / "gate.sh"
WRAP_CMD = REPO / "scripts" / "harness" / "codex" / "gate.cmd"
DENY = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "fake",
    }
}

needs_bash = pytest.mark.skipif(BASH is None, reason="repo 를 볼 수 있는 bash 가 필요함")
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="cmd wrapper 는 Windows 전용")


def _host(tmp_path: Path, runner_exit: int) -> Path:
    """호스트 배치(`scripts/harness/codex/` 와 그 두 단계 위의 러너)를 가짜 러너로 재현."""
    scripts = tmp_path / "scripts"
    (scripts / "harness" / "codex").mkdir(parents=True)
    shutil.copyfile(WRAP_SH, scripts / "harness" / "codex" / "gate.sh")
    shutil.copyfile(WRAP_CMD, scripts / "harness" / "codex" / "gate.cmd")
    body = f"cat > /dev/null\nprintf '%s\\n' '{json.dumps(DENY)}'\nexit {runner_exit}\n"
    (scripts / "precommit-runner.sh").write_text(body, encoding="utf-8", newline="\n")
    return scripts / "harness" / "codex"


@needs_bash
@pytest.mark.parametrize("runner_exit,want", [(2, 0), (0, 0), (1, 1)])
def test_sh_maps_only_exit_2(tmp_path, runner_exit, want):
    where = _host(tmp_path, runner_exit)
    run = run_bounded([BASH, (where / "gate.sh").as_posix()], input=b"{}")
    assert run.returncode == want
    assert json.loads(run.stdout.decode("utf-8").strip()) == DENY


@windows_only
@pytest.mark.parametrize("runner_exit,want", [(2, 0), (0, 0), (1, 1)])
def test_cmd_blocks_through_git_bash(tmp_path, runner_exit, want):
    # (1, 1) 이 잡는 결함: 한 줄의 `& exit /b %errorlevel%` 는 줄 파싱 때 확장돼 gate.sh 의
    # 결과가 아니라 탐지 단계의 잔여값(0)을 냄. (2, 0) 만으로는 잔여값과 정답이 우연히 같음.
    where = _host(tmp_path, runner_exit)
    run = run_bounded(
        ["cmd", "/d", "/c", str(where / "gate.cmd")],
        input=b'{"tool_input":{"command":"git commit"}}',
    )
    assert run.returncode == want
    assert json.loads(run.stdout.decode("utf-8").strip()) == DENY


SYSWOW64_CMD = Path(r"C:\Windows\SysWOW64\cmd.exe")
X86_GIT_BASH = Path(r"C:\Program Files (x86)\Git\bin\bash.exe")


@windows_only
@pytest.mark.skipif(not SYSWOW64_CMD.exists(), reason="SysWOW64 의 32-bit cmd.exe 가 필요함")
@pytest.mark.skipif(
    X86_GIT_BASH.exists(),
    reason="Program Files (x86) 에도 Git Bash 가 있어 32-bit 재지정으로도 탐지가 빗나가지 않음",
)
def test_cmd_without_git_bash_denies_commit_words_only(tmp_path):
    # - 64-bit cmd 자식의 ProgramFiles 는 env= 로 못 속임 — Windows 가 레지스트리에서
    #   다시 계산(실측)
    # - 32-bit cmd(SysWOW64)는 진짜로 "Program Files (x86)" 을 보고, Git 64-bit 기본 설치는
    #   거기 없음 → PATH 에서 Git 을 빼면 두 탐지 경로가 실제 설치를 건드리지 않고 함께 빗나감
    where = _host(tmp_path, 0)
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = r"C:\Windows\System32;C:\Windows\SysWOW64"
    commit = run_bounded(
        [str(SYSWOW64_CMD), "/d", "/c", str(where / "gate.cmd")],
        env=env,
        input=b'{"tool_input":{"command":"git commit -m x"}}',
    )
    other = run_bounded(
        [str(SYSWOW64_CMD), "/d", "/c", str(where / "gate.cmd")],
        env=env,
        input=b'{"tool_input":{"command":"ls"}}',
    )
    assert commit.returncode == 0
    reason = json.loads(commit.stdout.decode("utf-8").strip())["hookSpecificOutput"]
    assert reason["permissionDecision"] == "deny"
    assert reason["permissionDecisionReason"].startswith("vway-kit: ")
    assert other.returncode == 0 and other.stdout.strip() == b""


# 러너가 실제로 내는 두 문구의 모양 — 스킬 호출(`/vdev…`)과 게이트 훅 위치(settings.json).
# 증거 경로의 `/.vdev` 는 스킬이 아니므로 그대로 남아야 함.
CLAUDE_WORDED = (
    "vdev 미진입: /vdev 로 분류한 뒤 커밋하세요(강제가 불필요하면 /vdev-uninstall). "
    "불가하면 settings.json 의 게이트 훅을 제거. 증거: .claude/vway-kit/.vdev/tier"
)
CODEX_WORDED = (
    "vdev 미진입: $vdev 로 분류한 뒤 커밋하세요(강제가 불필요하면 $vdev-uninstall). "
    "불가하면 .codex/hooks.json 의 게이트 훅을 제거. 증거: .claude/vway-kit/.vdev/tier"
)


@needs_bash
def test_sh_rewords_the_reason_for_codex(tmp_path):
    where = _host(tmp_path, 2)
    deny = {
        "hookSpecificOutput": {
            **DENY["hookSpecificOutput"],
            "permissionDecisionReason": CLAUDE_WORDED,
        }
    }
    runner = tmp_path / "scripts" / "precommit-runner.sh"
    body = f"cat > /dev/null\nprintf '%s\\n' '{json.dumps(deny, ensure_ascii=False)}'\nexit 2\n"
    runner.write_text(body, encoding="utf-8", newline="\n")
    run = run_bounded([BASH, (where / "gate.sh").as_posix()], input=b"{}")
    assert run.returncode == 0
    output = json.loads(run.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert output["permissionDecisionReason"] == CODEX_WORDED


@needs_bash
def test_sh_prints_nothing_when_the_runner_allows(tmp_path):
    where = _host(tmp_path, 0)
    (tmp_path / "scripts" / "precommit-runner.sh").write_text(
        "cat > /dev/null\nexit 0\n", encoding="utf-8", newline="\n"
    )
    run = run_bounded([BASH, (where / "gate.sh").as_posix()], input=b"{}")
    assert run.returncode == 0 and run.stdout == b""


@needs_bash
@pytest.mark.parametrize("fake_sed", ["exit 1", "cat > /dev/null; exit 0"], ids=["fails", "empty"])
def test_sh_keeps_the_deny_when_rewording_fails(tmp_path, fake_sed):
    where = _host(tmp_path, 2)
    broken = tmp_path / "broken-bin"
    broken.mkdir()
    (broken / "sed").write_text(
        f"#!/usr/bin/env bash\n{fake_sed}\n", encoding="utf-8", newline="\n"
    )
    (broken / "sed").chmod(0o755)
    posix = broken.as_posix()
    bin_dir = f'$(cygpath -u "{posix}" 2>/dev/null || echo "{posix}")'
    gate = (where / "gate.sh").as_posix()
    # Git Bash 는 PATH 앞에 /usr/bin 을 다시 얹을 수 있음 — 가짜 sed 가 실제로 잡히는지
    # 가드로 확인하지 않으면 테스트가 헛통과함
    guard = f'[ "$(command -v sed)" = "{bin_dir}/sed" ] || exit 9'
    script = f'PATH="{bin_dir}:$PATH"; {guard}; bash "{gate}"'
    run = run_bounded([BASH, "-c", script], input=b"{}")
    assert run.returncode == 0
    assert json.loads(run.stdout.decode("utf-8").strip()) == DENY


@windows_only
@pytest.mark.parametrize("wrapper", ["gate.cmd", "run-hook.cmd"])
def test_cmd_finds_git_bash_from_a_mingw64_git(tmp_path, wrapper):
    r"""Git for Windows 는 git.exe 를 `cmd\` 와 `mingw64\bin\` 에 둠 — 뒤의 것은 설치 루트 두 단계
    아래라 `..\bin\bash.exe` 가 없는 파일을 가리킴. 가짜 bash 는 이름만 바꾼 cmd.exe 라 stdin 의
    `exit 7` 을 돌림: 7 은 ProgramFiles 의 진짜 설치가 아니라 이 git 옆의 bash 를 골랐다는 증거."""
    install = tmp_path / "Git"
    (install / "mingw64" / "bin").mkdir(parents=True)
    (install / "mingw64" / "bin" / "git.exe").write_bytes(b"")
    (install / "cmd").mkdir()
    (install / "cmd" / "git.exe").write_bytes(b"")
    (install / "bin").mkdir()
    cmd_exe = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    shutil.copyfile(cmd_exe, install / "bin" / "bash.exe")
    source = WRAP_CMD if wrapper == "gate.cmd" else REPO / "hooks" / "codex" / "run-hook.cmd"
    host = tmp_path / "host"
    host.mkdir()
    shutil.copyfile(source, host / wrapper)
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = f"{install / 'mingw64' / 'bin'};{Path(os.environ['SystemRoot']) / 'System32'}"
    # 파이프 입력: `run_bounded` 의 파일 stdin 은 가짜 bash 에 빈 입력으로 닿음(실측, 배너만 찍고
    # exit 0). 손자 없는 호출이라 파이프 timeout 이 들음.
    run = subprocess.run(
        ["cmd", "/d", "/c", str(host / wrapper), "x.sh"],
        env=env,
        input=b"exit 7\r\n",
        capture_output=True,
        timeout=60,
    )
    assert run.returncode == 7, run.stdout


def _run_shim_wrapper(tmp_path: Path, wrapper: str, program_files: Path) -> int:
    r"""PATH 에 scoop shim(`scoop\shims\git.exe`) 하나만 두고 wrapper 를 돌림 — `%ProgramFiles%`
    는 `program_files` 로 바꿔 이 머신의 진짜 설치를 가림. 종료 코드 7 = 가짜 bash 를 고름."""
    shims = tmp_path / "scoop" / "shims"
    shims.mkdir(parents=True, exist_ok=True)
    (shims / "git.exe").write_bytes(b"")
    source = WRAP_CMD if wrapper == "gate.cmd" else REPO / "hooks" / "codex" / "run-hook.cmd"
    host = tmp_path / "host"
    host.mkdir()
    text = source.read_text(encoding="utf-8")
    (host / wrapper).write_text(
        text.replace("%ProgramFiles%", str(program_files)), encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = f"{shims};{Path(os.environ['SystemRoot']) / 'System32'}"
    run = subprocess.run(
        ["cmd", "/d", "/c", str(host / wrapper), "x.sh"],
        env=env,
        input=b"exit 7\r\n",
        capture_output=True,
        timeout=60,
    )
    return run.returncode


def _fake_bash(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", path)


@windows_only
@pytest.mark.parametrize("wrapper", ["gate.cmd", "run-hook.cmd"])
def test_cmd_skips_a_bash_two_levels_above_a_git_shim(tmp_path, wrapper):
    # shim 디렉터리는 Git 설치가 아니므로 두 단계 위의 `bin\bash.exe` 는 남의 것. `cmd\git.exe`
    # 를 쥔 루트만 Git for Windows.
    _fake_bash(tmp_path / "bin" / "bash.exe")
    assert _run_shim_wrapper(tmp_path, wrapper, tmp_path / "none") != 7


@windows_only
@pytest.mark.parametrize("wrapper", ["gate.cmd", "run-hook.cmd"])
def test_cmd_finds_scoops_git_bash_through_its_shim(tmp_path, wrapper):
    # scoop 은 git.exe 를 `shims\git.exe` 로 PATH 에 두고 Git 자체는 `apps\git\current\` 에 설치함.
    _fake_bash(tmp_path / "scoop" / "apps" / "git" / "current" / "bin" / "bash.exe")
    assert _run_shim_wrapper(tmp_path, wrapper, tmp_path / "none") == 7


@windows_only
@pytest.mark.parametrize("wrapper", ["gate.cmd", "run-hook.cmd"])
def test_cmd_falls_back_to_program_files_past_a_shim_without_git(tmp_path, wrapper):
    # 이웃에 Git 이 없는 shim 이 ProgramFiles 설치의 자리를 차지하면 안 됨.
    _fake_bash(tmp_path / "pf" / "Git" / "bin" / "bash.exe")
    assert _run_shim_wrapper(tmp_path, wrapper, tmp_path / "pf") == 7


@pytest.mark.skipif(sys.platform != "win32", reason="cmd wrapper 는 Windows 전용")
@pytest.mark.parametrize("script, says", [("inject-risk-tiers.sh", True), ("x.sh", False)])
def test_run_hook_without_git_bash_tells_the_session(tmp_path, script, says):
    """SessionStart 의 평문 stdout 은 세션 컨텍스트로 닿음 — 다른 훅은 조용히 있음."""
    # cmd.exe 는 환경과 무관하게 %ProgramFiles% 를 스스로 세우므로 사본에서 빈 디렉터리로
    # 바꿈. PATH 에는 git 이 없음.
    text = (REPO / "hooks" / "codex" / "run-hook.cmd").read_text(encoding="utf-8")
    assert text.count("%ProgramFiles%") == 2
    wrapper = tmp_path / "run-hook.cmd"
    wrapper.write_text(text.replace("%ProgramFiles%", str(tmp_path / "none")), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    run = subprocess.run(
        ["cmd", "/d", "/c", str(wrapper), script],
        env=env,
        capture_output=True,
        timeout=60,
    )
    assert run.returncode == 0
    assert (b"Git Bash was not found" in run.stdout) is says, run.stdout
