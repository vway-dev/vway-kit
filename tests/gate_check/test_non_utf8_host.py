"""UTF-8 이 아닌 호스트 — 게이트가 거기서도 서는가(Invariant 2).

호스트가 `PYTHONIOENCODING` 을 세우면 게이트 스크립트가 stdin 을 로캘 코덱으로 디코딩하면서
죽고, 그 자리는 조용함(Invariant 1 이 FAIL-OPEN 이므로). 근거와 실측은
`_vway_paths.force_utf8_io` 독스트링이 SSOT — 여기서 되풀이하지 않음.

이 파일이 재는 것은 그 축뿐임. 자식 git 출력 디코딩은 호출마다 `encoding=` 으로 이미 닫혀
있고 `tests/vway_paths/test_child_output.py` 가 잼.
"""

import json
import sys
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from tests._non_utf8 import stdio_host_env
from tests._proc import run_bounded
from tests.gate_check._helpers import (
    _init_repo,
    _rg,
    _run_runner,
    requires_bash_git,
)

REPO = Path(__file__).resolve().parent.parent.parent
# 호스트가 세울 수 있는 인코딩 환경들. `PYTHONUTF8=1` 은 러너가 자식에 주는 값이라, 그것과
# 함께 선 경우가 실제로 도는 모양임.
HOSTS = [
    pytest.param({"PYTHONUTF8": "1"}, id="pythonutf8-1"),
    pytest.param({"PYTHONUTF8": "0"}, id="pythonutf8-0"),
    pytest.param({"PYTHONIOENCODING": "cp949"}, id="ioencoding-cp949"),
    pytest.param({"PYTHONUTF8": "1", "PYTHONIOENCODING": "cp949"}, id="both"),
]


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    """비UTF-8 자식 환경의 SSOT 는 `tests/_non_utf8.py` — 여기서 다시 짓지 않음."""
    return stdio_host_env(CLAUDE_PROJECT_DIR=str(REPO), **extra)


@pytest.mark.parametrize("host", HOSTS)
def test_classify_reads_a_payload_that_carries_non_ascii(host: dict[str, str]):
    """`--classify` 가 한글을 담은 훅 페이로드를 읽어야 함.

    stdin 이 로캘 코덱으로 디코딩되면 여기서 `UnicodeDecodeError` 가 나고, 그 예외는
    최상위 핸들러가 `allowing` 으로 삼켜 **출력 없이 exit 0** 함. 러너는 그 빈 판정을
    `ok=1` 부재로 알아보고 스스로 게이팅하지만, 같이 사라진 `worktree=` 줄은 못 되살림 —
    그래서 ROOT 가 프로젝트 디렉터리에 남고 그 트리가 깨끗하면 조기 종료함.
    """
    command = 'git commit -m "fix(gate): 한글 커밋 메시지"'
    hook = json.dumps({"cwd": str(REPO), "tool_input": {"command": command}}, ensure_ascii=False)
    r = run_bounded(
        [sys.executable, str(REPO / "scripts" / "vdev_gate_check.py"), "--classify"],
        input=hook.encode("utf-8"),
        env=_child_env(host),
    )
    out = r.stdout.decode("utf-8", "replace")
    assert "ok=1" in out, (host, r.returncode, out, r.stderr.decode("utf-8", "replace"))
    assert "commit=1" in out, (host, r.returncode, out)


@requires_bash_git
@pytest.mark.parametrize("host", HOSTS)
def test_runner_gates_a_korean_path_worktree_commit(tmp_path: Path, host: dict[str, str]):
    """한글 경로 worktree 의 미분류 커밋 — 러너 exit 코드로 잼.

    main 은 깨끗하고 worktree 만 더러움. 경로가 온전히 읽히면 ROOT 가 worktree 로 재지정돼
    차단됨. stdin 이 깨지면 판정이 사라져 재지정을 못 하고, ROOT 가 깨끗한 main 에 남아 러너가
    조기 종료함 — 진짜 커밋에서 게이트가 통째로 빠짐(실측: cp949 에서 exit 0).
    """
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "작업트리"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    (wt / "f.txt").write_text("x", encoding="utf-8")
    _rg(["add", "f.txt"], wt)
    r = _run_runner(main, f'git -C "{wt.as_posix()}" commit -m x', env_extra=host)
    assert r.returncode == 2, (host, r.returncode, r.stdout, r.stderr)


def test_the_runner_pins_utf8_for_its_children_but_cannot_rely_on_it():
    """러너가 자식에 `PYTHONUTF8=1` 을 주는 것은 사실이나 **충분하지 않음** — 호스트의
    `PYTHONIOENCODING` 이 그것을 이김(실측). 그래서 방어는 러너의 env 가 아니라
    `force_utf8_io` 에 있어야 하고, 이 단언이 그 근거를 파일로 못 박음."""
    runner = (REPO / "scripts" / "precommit-runner.sh").read_text(encoding="utf-8")
    assert "PYTHONUTF8=1" in runner, "러너가 자식 UTF-8 핀을 잃었다"
    probe = "import sys; print(sys.stdin.encoding)"
    r = run_bounded(
        [sys.executable, "-c", probe],
        input=b"",
        env=_child_env({"PYTHONUTF8": "1", "PYTHONIOENCODING": "cp949"}),
    )
    assert r.stdout.decode().strip().lower().replace("-", "") == "cp949", (
        "PYTHONIOENCODING 이 더는 PYTHONUTF8 을 이기지 않는다면 이 파일의 전제가 바뀐 것"
    )


@pytest.mark.parametrize("host", HOSTS)
def test_the_notifier_prints_its_own_help_on_a_non_utf8_host(host: dict[str, str], tmp_path: Path):
    """`teams_alert.py` 의 사용법·오류 문구가 한글임 — 로캘 코덱으로는 인코딩이 안 됨.

    argparse 는 `parse_args()` 안에서 사용법을 출력하므로, 방어가 그보다 **앞**에 서야 함.
    알림은 호출측 훅을 실패시키지 않는 것이 규율인데(모듈 독스트링), `--help` 가
    `UnicodeEncodeError` 로 죽으면 그 규율이 시작도 못 함(실측: cp949·cp1252 에서 rc 1).
    """
    r = run_bounded(
        [sys.executable, str(REPO / "scripts" / "teams_alert.py"), "--help"],
        input=b"",
        env=_child_env(host),
        cwd=str(tmp_path),
    )
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    assert r.returncode == 0, (host, r.returncode, out[-300:])
    assert "채널" in out, (host, out[:300])


def test_stdin_survives_bytes_that_are_not_utf8_at_all():
    """`errors="surrogateescape"` 가 막는 것 — 훅 페이로드가 **UTF-8 이 아닌** 바이트를 실어
    오는 경우.

    UTF-8 모드가 stdin 에 주는 것과 같은 값이라 러너 아래에서는 아무것도 안 바뀜. 다른 값일
    때가 문제임. **종료 코드로는 못 가림** — 어느 쪽이든 최상위 핸들러가 삼켜 rc 0 이고,
    가르는 것은 stdout 이 비었는지임(실측). `strict` 면 그런 바이트 하나가
    `UnicodeDecodeError` 를 내 판정이 통째로 사라짐. 읽어 낸 텍스트가 그 자리에서 깨져 있는
    것은 감수함 — 판정이 **있는** 것이 없는 것보다 나은 방향이고, 커밋·머지 낱말은 ASCII 라
    그대로 살아남음.
    """
    payload = (
        b'{"cwd": ".", "tool_input": {"command": "git commit -m \\"'
        + "한글".encode("cp949")  # UTF-8 로는 디코딩 불가
        + b'\\""}}'
    )
    r = run_bounded(
        [sys.executable, str(REPO / "scripts" / "vdev_gate_check.py"), "--classify"],
        input=payload,
        env=_child_env({"PYTHONIOENCODING": "cp949"}),
    )
    out = r.stdout.decode("utf-8", "replace")
    assert "ok=1" in out, (r.returncode, out, r.stderr.decode("utf-8", "replace")[-300:])
    assert "commit=1" in out, (r.returncode, out)


@requires_bash_git
@pytest.mark.parametrize("host", HOSTS)
def test_runner_blocks_a_forbidden_merge_on_a_non_utf8_host(host: dict[str, str], tmp_path: Path):
    """`--merge-check` 도 훅 JSON 을 stdin 으로 받음 — 그리고 merge 전략은 Invariant 1 이
    fail-open 을 금지한 셋 중 하나임(근거가 명령어 문자열뿐이라 내부 오류 여지가 없다는 것).

    stdin 이 깨지면 그 판정마저 조용히 사라져, 필수 플래그를 빠뜨린 머지가 그냥 나감. 메시지가
    한글인 승격 머지는 이 저장소의 평범한 모양임. 머지는 정의상 깨끗한 트리에서 돌므로
    config 는 커밋해 둠 — 안 그러면 무관한 게이트가 먼저 막아 이 판정이 가려짐.
    """
    main = tmp_path / "main"
    _init_repo(main)  # 브랜치 main = production
    cfg = main / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "branches:\n  staging: stage\n  production: main\n", encoding="utf-8"
    )
    _rg(["add", "-A"], main)
    _rg(["commit", "-m", "cfg"], main)
    r = _run_runner(main, 'git merge origin/stage -m "기능 추가"', env_extra=host)
    assert r.returncode == fgc.BLOCK_EXIT_CODE, (host, r.returncode, r.stdout, r.stderr)
    # 종료 코드만 보면 **다른** 게이트가 막아도 초록임 — 막은 것이 merge 전략인지까지 봄.
    assert "--no-ff" in (r.stdout + r.stderr), (host, r.stdout, r.stderr)


def test_a_lossy_error_handler_would_forge_an_invocation():
    r"""`ignore` 를 고르면 안 되는 이유 — 바이트를 **지우면** 양옆 토큰이 붙음.

    `git <쓰레기> commit -m x` 는 커밋이 아님(가운데 낱말이 서브커맨드 자리를 차지함).
    쓰레기가 사라지면 `git` 과 `commit` 이 이웃이 되어 없던 호출이 생김. 게이트가 틀려도 되는
    방향이긴 하나 틀린 이유가 **입력을 지운 것**이라 다음 사람이 못 찾고, `-C` 값이나 머지
    소스가 같은 식으로 이어 붙으면 방향이 뒤집힘. `surrogateescape` 는 바이트를 되돌릴 수
    있게 보존하므로 그 일이 안 생김.

    출하된 값을 **종단에서** 잼 — 디코더 성질만 재면 `_vway_paths` 가 `ignore` 로 바뀌어도
    초록임(실측: 그 변이가 살아남았음).
    """
    junk = bytes((0xFF, 0xFE))  # UTF-8 에 없는 선두 바이트 둘
    assert junk.decode("utf-8", "ignore") == "", "이 단언의 전제(ignore 가 지움)가 깨졌다"
    payload = b'{"cwd": ".", "tool_input": {"command": "git ' + junk + b' commit -m x"}}'
    r = run_bounded(
        [sys.executable, str(REPO / "scripts" / "vdev_gate_check.py"), "--classify"],
        input=payload,
        env=_child_env({"PYTHONIOENCODING": "cp949"}),
    )
    out = r.stdout.decode("utf-8", "replace")
    assert "ok=1" in out, (r.returncode, out, r.stderr.decode("utf-8", "replace")[-300:])
    assert "commit=1" not in out, f"지워진 바이트가 없던 호출을 만들었다: {out!r}"


def test_importing_the_notifier_leaves_the_importer_alone():
    """`force_utf8_io` 는 `os.environ` 과 이 프로세스의 스트림을 바꿈 — import 만으로 그것이
    돌면 `from teams_alert import send` 한 쪽의 스트림과 그 쪽이 나중에 띄우는 자식의 환경까지
    바뀜(이 저장소의 pytest 세션이 실제로 그렇게 오염됐음).

    주석으로만 막혀 있었고, 그 배치를 import 로 되돌려도 다른 19개 테스트는 전부 초록이었음
    (실측). 재는 것은 디코더 성질이 아니라 **행동 불변식** — "이 모듈을 import 하는 것이
    import 한 쪽의 환경·스트림을 바꾸지 않음".
    """
    probe = (
        "import os, sys;"
        " before = (os.environ.get('PYTHONUTF8'), sys.stdout.errors);"
        " import scripts.teams_alert;"
        " print(before == (os.environ.get('PYTHONUTF8'), sys.stdout.errors))"
    )
    r = run_bounded([sys.executable, "-c", probe], cwd=str(REPO), env=stdio_host_env())
    assert r.stdout.decode("utf-8", "replace").strip() == "True", (
        r.stdout.decode("utf-8", "replace"),
        r.stderr.decode("utf-8", "replace")[-300:],
    )
