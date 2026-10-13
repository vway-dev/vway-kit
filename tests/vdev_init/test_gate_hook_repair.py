"""옛 게이트 엔트리의 보정 — 경로가 어긋났거나 발화하지 않는 훅을 앞으로 가져오기.

등록 자체(`test_gate_hook.py`)와 나누는 이유: 여기서 재는 것은 **이미 있는 것을 고치는
일**이고, 그 판정은 '몇 개를 옮겼는가'라는 개수 계약까지 짐 — 엔트리가 아니라 훅을
셈. 판정 못 하는 매처는 옮기되 `maybe` 로 보고.
"""

import json
from pathlib import Path

from scripts.vdev_init_setup import (
    GATE_COMMAND,
    _is_gate_hook,
    check_precommit,
    register_gate,
)
from tests.vdev_init._helpers import (
    PLUGIN,
    STALE_COMMAND,
    _gate_commands,
    _gate_hook,
    _host_with,
    _is_gate,
    _planted,
    _pre,
)


def test_register_gate_recovers_a_gate_hook_from_an_entry_that_never_fires(tmp_path: Path):
    """매처가 Bash 를 놓치면 그 훅은 커밋에 발화하지 않음 — 게이트가 아닌데 게이트로
    세면 호스트가 갖고 있지도 않은 게이트를 등록됐다고 읽음."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    host_entry = {
        "matcher": "Write|Edit",
        "hooks": [_gate_hook(), {"type": "command", "command": "echo host-hook"}],
    }
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [host_entry]}}), encoding="utf-8")
    msg = register_gate(tmp_path)
    assert "이동" in msg, msg
    pre = _pre(settings)
    # 호스트 엔트리는 매처도 자기 훅도 그대로. 매처를 고쳐 쓰면 호스트가 그 엔트리에 넣어
    # 둔 다른 훅 전부가 다른 도구를 겨냥하게 됨.
    assert pre[0]["matcher"] == "Write|Edit"
    assert [h["command"] for h in pre[0]["hooks"]] == ["echo host-hook"]
    # 게이트는 자기 엔트리를 얻고, 그 엔트리는 Bash 에 발화함.
    assert pre[-1]["matcher"] == "Bash"
    assert _is_gate(pre[-1]["hooks"][0]["command"])
    # 두 번째 실행은 그것을 자기로 알아봄.
    assert "skip" in register_gate(tmp_path)


def test_register_gate_removes_a_copy_that_never_fires(tmp_path: Path):
    """발화하는 사본이 이미 있어도, 발화하지 않는 사본은 회수해서 지움.

    "이미 등록됨"으로 넘기면 그 중복이 디스크에 남고, 다음 사람이 그것을 게이트로 읽음.
    """

    gate_hook = _gate_hook()
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Write|Edit", "hooks": [dict(gate_hook)]},
                        {"matcher": "Bash", "hooks": [dict(gate_hook)]},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    msg = register_gate(tmp_path)
    assert "skip" not in msg, msg
    remaining = [e for e in _pre(settings) if any(_is_gate_hook(h) for h in e["hooks"])]
    assert [e["matcher"] for e in remaining] == ["Bash"], _pre(settings)


def test_register_gate_repairs_all_stale_entries(tmp_path: Path):
    # 중복으로 등록된 구버전(평면 경로) 게이트 엔트리를 모두 최신 경로로 보정
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    old = 'bash ".../.claude/vway-kit/precommit-runner.sh"'  # 구버전 평면 경로
    dup = [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": old}]},
        {"matcher": "Bash", "hooks": [{"type": "command", "command": old}]},
    ]
    settings.write_text(json.dumps({"hooks": {"PreToolUse": dup}}), encoding="utf-8")
    msg = register_gate(tmp_path)
    assert "보정" in msg
    cmds = _gate_commands(settings)
    assert cmds == [GATE_COMMAND, GATE_COMMAND]  # 둘 다 보정(첫 것만 X)


def test_check_precommit_reports_stale_owned_entry(tmp_path: Path):
    # vway-kit 소유 훅(teams-notify-push)의 entry 가 옛 경로면 drift 보고
    dest = tmp_path / ".pre-commit-config.yaml"
    dest.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: teams-notify-push\n"
        "        name: x\n"
        "        entry: scripts/notify-push.sh\n"  # 옛 경로(이동 전)
        "        language: script\n",
        encoding="utf-8",
    )
    report = check_precommit(PLUGIN, tmp_path)
    assert any("entry 가 옛 경로" in line for line in report)


def test_moving_a_hook_is_written_even_when_the_gate_is_already_there(tmp_path: Path):
    """할 일이 이동뿐이어도 파일은 바뀜 — skip 으로 보고하면 발화하지 않는 매처 아래의
    게이트 훅과 그것에 대한 기록이 함께 호스트에 남음."""
    import scripts.vdev_init_setup as vis

    settings = _planted(
        tmp_path,
        [
            {"matcher": "Bash", "hooks": [_gate_hook()]},
            {"matcher": "Read", "hooks": [_gate_hook()]},
        ],
    )
    out = vis.register_gate(tmp_path)
    pre = _pre(settings)
    assert "skip" not in out and "1건" in out, out
    assert pre[1]["hooks"] == [], pre


def test_the_repair_count_covers_the_hooks_it_moved(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    stale = dict(_gate_hook(), command=STALE_COMMAND)
    _planted(
        tmp_path,
        [
            {"matcher": "Bash", "hooks": [stale]},
            {"matcher": "Read", "hooks": [_gate_hook()]},
        ],
    )
    assert "2건" in vis.register_gate(tmp_path)


def test_the_move_count_is_hooks_not_entries(tmp_path: Path):
    """엔트리 하나가 게이트 훅 여럿을 담을 수 있고, 호스트가 읽는 수는 옮겨진 수여야 함."""
    import scripts.vdev_init_setup as vis

    _planted(tmp_path, [{"matcher": "Read", "hooks": [_gate_hook(), _gate_hook(), _gate_hook()]}])
    assert "3건" in vis.register_gate(tmp_path)


def test_a_stale_hook_under_an_undecidable_matcher_is_still_brought_forward(tmp_path: Path):
    """엔트리는 호스트가 쓴 그대로 남지만 그 안의 게이트 자신의 훅은 아님 — 이 플러그인이
    설치하지 않는 경로는 아무것도 돌리지 않는 훅임."""
    import scripts.vdev_init_setup as vis

    settings = _planted(
        tmp_path, [{"matcher": "^Bash$", "hooks": [dict(_gate_hook(), command=STALE_COMMAND)]}]
    )
    vis.register_gate(tmp_path)
    pre = _pre(settings)
    assert pre[0]["matcher"] == "^Bash$", pre
    assert pre[0]["hooks"][0]["command"] == vis.GATE_COMMAND, pre


def test_a_hook_under_an_undecidable_matcher_is_reported_as_a_maybe(tmp_path: Path):
    """발화할 수도 아닐 수도 있음 — 발화한다고 말하는 것은 매처를 잘못 읽는 것과 같은
    거짓 진술."""
    import scripts.vdev_init_setup as vis

    out = vis.register_gate(
        _host_with(tmp_path, [{"matcher": "^Notebook", "hooks": [_gate_hook()]}])
    )
    assert "판정할 수 없는" in out and "1개" in out, out
    assert "발화하는 게이트 훅" not in out, out


def test_the_undecided_note_counts_hooks_not_entries(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    _planted(tmp_path, [{"matcher": "^Bash$", "hooks": [_gate_hook(), _gate_hook()]}])
    out = vis.register_gate(tmp_path)
    assert "판정할 수 없는" in out and "2개" in out, out


def test_the_undecided_note_counts_only_the_gates_own_hooks(tmp_path: Path):
    """판정할 수 없는 매처 아래의 호스트 훅은 호스트의 것이고, 그것을 게이트 실행으로 세면
    커밋이 하지 않는 일을 한다고 알리는 셈."""
    import scripts.vdev_init_setup as vis

    _planted(
        tmp_path,
        [{"matcher": "^Bash$", "hooks": [{"command": "my-audit.sh"}, {"command": "lint.sh"}]}],
    )
    assert "게이트 훅" not in vis.register_gate(tmp_path)


def test_one_gate_hook_is_not_reported_as_several(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    assert "게이트 훅" not in vis.register_gate(tmp_path)
    assert "게이트 훅" not in vis.register_gate(tmp_path)


def test_register_gate_repairs_legacy_command(tmp_path: Path):
    # 구버전 평면 경로로 등록된 게이트 command 를 최신 scripts/ 경로로 보정
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    old_cmd = 'bash ".../.claude/vway-kit/precommit-runner.sh"'  # 구버전 평면 경로
    legacy = {"matcher": "Bash", "hooks": [{"type": "command", "command": old_cmd}]}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [legacy]}}), encoding="utf-8")
    msg = register_gate(tmp_path)
    assert "보정" in msg
    cmds = _gate_commands(settings)
    assert cmds == [GATE_COMMAND]  # 단일 엔트리가 최신 경로로 보정됨(중복 추가 X)


def test_register_gate_refreshes_stale_status_message(tmp_path: Path):
    # #5: command 는 최신인데 옛 statusMessage('flow 게이트')가 남아 있으면 보정한다(skip 아님)
    from scripts.vdev_init_setup import GATE_STATUS

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    old = {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": GATE_COMMAND,
                "statusMessage": "vway-kit: flow 게이트 검사 중…",
            }
        ],
    }
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [old]}}), encoding="utf-8")
    msg = register_gate(tmp_path)
    assert "보정" in msg
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["statusMessage"] == GATE_STATUS
