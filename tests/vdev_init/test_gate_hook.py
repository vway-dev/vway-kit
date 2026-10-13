"""커밋 게이트 훅의 호스트 등록/해제 — settings.json 의 PreToolUse 엔트리.

재는 것 하나: **셋업이 끝났다고 말할 때 호스트에 실제로 도는 게이트가 있는가.**
매처가 Bash 에 발화하는지의 판정(`_is_gate`·두 방언 대조), 옛 경로·꺼진 훅의 보정,
그리고 해제가 호스트 자신의 엔트리를 남기는지가 여기 모임.
"""

import json
from pathlib import Path

import pytest

from scripts.vdev_init_setup import (
    GATE_COMMAND,
    _is_gate_hook,
    register_gate,
    unregister_gate,
)
from tests.vdev_init._helpers import (
    CANNOT_DECIDE,
    COVERS_BASH,
    COVERS_NOTHING,
    _firing,
    _gate_commands,
    _gate_hook,
    _is_gate,
    _planted,
    _pre,
)


def test_register_gate_creates(tmp_path: Path):
    msg = register_gate(tmp_path)
    assert "등록" in msg
    cmds = _gate_commands(tmp_path / ".claude" / "settings.json")
    assert any(_is_gate(c) for c in cmds)


def test_register_gate_idempotent(tmp_path: Path):
    register_gate(tmp_path)
    msg = register_gate(tmp_path)
    assert "이미" in msg
    # 중복 등록되지 않음
    cmds = _gate_commands(tmp_path / ".claude" / "settings.json")
    assert sum(_is_gate(c) for c in cmds) == 1


def test_register_gate_preserves_existing(tmp_path: Path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo other"}]}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [other]}}), encoding="utf-8")
    register_gate(tmp_path)
    cmds = _gate_commands(settings)
    assert "echo other" in cmds
    assert any(_is_gate(c) for c in cmds)


@pytest.mark.parametrize("matcher", COVERS_BASH, ids=[repr(m) for m in COVERS_BASH])
def test_a_matcher_that_names_bash_is_read_as_firing(matcher):
    from scripts.vdev_init_setup import _covers_bash

    assert _covers_bash(matcher) is True


@pytest.mark.parametrize("matcher", COVERS_NOTHING, ids=[repr(m) for m in COVERS_NOTHING])
def test_a_matcher_naming_no_tool_the_gate_uses_is_read_as_not_firing(matcher):
    from scripts.vdev_init_setup import _covers_bash

    assert _covers_bash(matcher) is False


@pytest.mark.parametrize("matcher", CANNOT_DECIDE, ids=[repr(m) for m in CANNOT_DECIDE])
def test_a_matcher_the_two_dialects_disagree_on_is_undecided(matcher):
    """ "발화 안 함"으로 다루면 호스트가 일부러 앵커한 `^Bash$` 가 자기 훅을 잃고, 보고는
    그 엔트리가 발화한 적 없다고 말함. 둘 다 거짓."""
    from scripts.vdev_init_setup import _covers_bash

    assert _covers_bash(matcher) is None


@pytest.mark.parametrize(
    "payload",
    # 빈 배열·`null` 은 `_load_settings` 가 `{}` 로 읽음(내용이 없으므로 새로 써도 무해).
    # 여기서 재는 것은 **내용이 든** 모양.
    ['{"hooks": []}', '{"hooks": "x"}', '[{"hooks": {}}]', '"x"'],
    ids=["hooks-list", "hooks-string", "top-array", "top-string"],
)
def test_register_gate_reports_a_settings_shape_it_cannot_edit(tmp_path: Path, payload: str):
    """모양이 예상 밖이면 트레이스백이 아니라 한 줄로 알림 — `/vdev-init` 은 계속 돎."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(payload, encoding="utf-8")
    msg = register_gate(tmp_path)
    assert "[!]" in msg, msg
    assert settings.read_text(encoding="utf-8") == payload  # 손대지 않음


def test_register_gate_leaves_the_hook_where_it_already_fires(tmp_path: Path):
    """이미 Bash 에 발화하는 호스트 엔트리 안이면 옮기지 않음 — 옮기면 중복이 됨."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    entry = {
        "matcher": "Bash|Write",
        "hooks": [_gate_hook(), {"type": "command", "command": "echo host-hook"}],
    }
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [entry]}}), encoding="utf-8")
    assert "skip" in register_gate(tmp_path)
    assert len(_pre(settings)) == 1


def test_unregister_gate_takes_the_hook_and_not_the_host_entry(tmp_path: Path):
    """게이트를 담은 엔트리가 호스트의 훅을 함께 담을 수 있음 — 엔트리째 가져가면 그것들도
    함께 사라짐."""
    from scripts.vdev_init_setup import GATE_STATUS

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    entry = {
        "matcher": "Bash",
        "hooks": [
            {"type": "command", "command": GATE_COMMAND, "statusMessage": GATE_STATUS},
            {"type": "command", "command": "echo host-hook"},
        ],
    }
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [entry]}}), encoding="utf-8")
    assert "해제" in unregister_gate(tmp_path)
    pre = _pre(settings)
    assert len(pre) == 1
    assert [h["command"] for h in pre[0]["hooks"]] == ["echo host-hook"]
    assert "skip" in unregister_gate(tmp_path)


def test_unregister_gate_drops_only_the_entry_this_plugin_wrote(tmp_path: Path):
    from scripts.vdev_init_setup import GATE_STATUS

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"Stop": []}}), encoding="utf-8")
    register_gate(tmp_path)
    assert "해제" in unregister_gate(tmp_path)
    assert json.loads(settings.read_text(encoding="utf-8")) == {"hooks": {"Stop": []}}
    # 호스트가 자기 엔트리에 게이트 훅만 넣어 뒀다면, 비워진 뒤에도 그 엔트리는 호스트의
    # 것 — 매처가 그 증거. "비었으니 지운다"로 읽으면 이 플러그인이 쓰지 않은 설정을
    # 가져감.
    host = {
        "matcher": "Bash|Write",
        "hooks": [{"type": "command", "command": GATE_COMMAND, "statusMessage": GATE_STATUS}],
    }
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [host]}}), encoding="utf-8")
    assert "해제" in unregister_gate(tmp_path)
    assert _pre(settings) == [{"matcher": "Bash|Write", "hooks": []}]


def test_settings_written_with_a_bom_still_parse(tmp_path: Path):
    """Windows 편집기가 붙인 BOM 하나면 게이트가 "파싱 실패" 로 미등록됨."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b"\xef\xbb\xbf" + json.dumps({"hooks": {"PreToolUse": []}}).encode())
    assert "등록" in register_gate(tmp_path)
    assert any(_is_gate_hook(h) for e in _pre(settings) for h in e["hooks"])


def test_a_matcher_naming_no_tool_the_gate_uses_gives_the_hook_up(tmp_path: Path):
    """발화하지 않는 엔트리에서는 게이트 훅만 빼 오고, 엔트리의 나머지는 전부 그대로 둠."""
    import scripts.vdev_init_setup as vis

    settings = _planted(
        tmp_path, [{"matcher": "Read", "team_note": "ours", "hooks": [_gate_hook()]}]
    )
    vis.register_gate(tmp_path)
    pre = _pre(settings)
    assert [e.get("matcher") for e in _firing(pre)] == ["Bash"], pre
    assert pre[0] == {"matcher": "Read", "team_note": "ours", "hooks": []}, pre


@pytest.mark.parametrize("matcher", CANNOT_DECIDE, ids=[repr(m) for m in CANNOT_DECIDE])
def test_a_matcher_this_script_cannot_decide_is_left_as_written(tmp_path: Path, matcher):
    """'발화 안 함'으로 다루면 호스트가 일부러 앵커한 `^Bash$` 가 담고 있던 훅을 잃고, 보고는
    그 엔트리가 발화한 적 없다고 말함. 둘 다 거짓이고, 그 엔트리는 호스트의 것이므로 이
    스크립트가 할 수 있는 일은 자기 것을 하나 더하는 것뿐임."""
    import scripts.vdev_init_setup as vis

    planted = {"matcher": matcher, "team_note": "ours", "hooks": [_gate_hook()]}
    settings = _planted(tmp_path, [dict(planted)])
    vis.register_gate(tmp_path)
    pre = _pre(settings)
    assert pre[0] == planted, pre
    assert "Bash" in [e.get("matcher") for e in _firing(pre)], pre


def test_registering_twice_over_a_matcher_that_cannot_be_decided_settles(tmp_path: Path):
    """더해진 엔트리는 다음 실행에서 게이트로 알아봐져야 함 — 아니면 `/vdev-init` 마다
    손대지 않을 훅 옆에 또 하나가 붙음."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "^Bash$", "hooks": [_gate_hook()]}])
    vis.register_gate(tmp_path)
    first = settings.read_text(encoding="utf-8")
    assert "skip" in vis.register_gate(tmp_path)
    assert settings.read_text(encoding="utf-8") == first


def test_a_gate_that_runs_more_than_once_says_so(tmp_path: Path):
    """호스트가 닿을 수 있는 게이트 훅 둘은 커밋마다 게이트 두 번임. 하나를 지우는 것은 이
    플러그인이 쓰지 않았을 수 있는 훅을 가져가는 일이고, 말하지 않는 것은 호스트가 갖고 있지
    않은 게이트 상태를 보고하는 일임."""
    import scripts.vdev_init_setup as vis

    _planted(tmp_path, [{"matcher": "Bash", "hooks": [_gate_hook(), _gate_hook()]}])
    assert "2개" in vis.register_gate(tmp_path)


@pytest.mark.parametrize("field", [{"if": "Bash(rm *)"}, {"async": True}, {"type": "prompt"}])
def test_a_gate_hook_the_host_switched_off_is_not_the_gate(tmp_path: Path, field: dict):
    """셋 다 훅을 등록된 채로 두면서 아무것에도 발화하지 않게 만듦: `if` 는 빌드별로
    막고(Invariant 4), `async` 는 deny 할 수 없는 자리로 옮기며, 다른 `type` 은 다른 것을
    돌림. 이미 등록됐다고 보고되면 커밋 게이트는 조용히 꺼진 것."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "Bash", "hooks": [dict(_gate_hook(), **field)]}])
    assert "보정" in vis.register_gate(tmp_path)
    assert _pre(settings)[0]["hooks"][0] == vis.GATE_ENTRY["hooks"][0]


def test_a_hook_of_the_hosts_that_merely_shares_the_script_name_is_left_alone(tmp_path: Path):
    """`precommit-runner.sh` 는 호스트가 자기 것으로 쓰는 이름임. 게이트의 것으로 우기면
    그들의 훅이 발화하는 매처 아래에서는 이 경로로 고쳐 쓰이고, 발화하지 않는 매처 아래에서는
    지워짐."""
    import scripts.vdev_init_setup as vis

    theirs = {"type": "command", "command": "bash ./tools/precommit-runner.sh --their-flags"}
    for matcher in ("Bash", "Edit"):
        host = tmp_path / matcher
        settings = _planted(host, [{"matcher": matcher, "hooks": [dict(theirs)]}])
        vis.register_gate(host)
        cmds = _gate_commands(settings)
        assert theirs["command"] in cmds, (matcher, cmds)
        assert any(_is_gate(c) for c in cmds), (matcher, cmds)


def test_uninstall_leaves_a_hook_of_the_hosts_that_shares_the_script_name(tmp_path: Path):
    """설치 쪽은 그 이름을 우기지 않음. 제거 쪽은 같은 술어로 훅을 가져가고, uninstall 이 지운
    호스트 훅은 영영 사라짐."""
    import scripts.vdev_init_setup as vis

    theirs = {"type": "command", "command": "bash ./tools/precommit-runner.sh --their-flags"}
    settings = _planted(tmp_path, [{"matcher": "Bash", "hooks": [dict(theirs), _gate_hook()]}])
    assert "해제" in vis.unregister_gate(tmp_path)
    assert _gate_commands(settings) == [theirs["command"]]


def test_uninstall_keeps_the_keys_the_host_put_beside_the_gate(tmp_path: Path):
    """엔트리가 게이트 자신의 매처를 달고 있으므로, 호스트가 그 안에 무언가 썼는지는 키
    집합만이 말해 줌."""
    import scripts.vdev_init_setup as vis

    settings = _planted(
        tmp_path, [{"matcher": "Bash", "team_note": "ours", "hooks": [_gate_hook()]}]
    )
    vis.unregister_gate(tmp_path)
    assert _pre(settings) == [{"matcher": "Bash", "team_note": "ours", "hooks": []}]


def test_uninstall_keeps_a_host_entry_that_only_looks_like_the_gates(tmp_path: Path):
    """키도 같고 비어 있는 것도 같음 — 누구의 엔트리인지 말하는 것은 매처뿐이고, 여기서
    그것을 버리면 호스트가 쓴 엔트리를 가져가는 것임."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "Read", "hooks": [_gate_hook()]}])
    vis.register_gate(tmp_path)
    vis.unregister_gate(tmp_path)
    assert _pre(settings) == [{"matcher": "Read", "hooks": []}]


def test_uninstall_with_no_gate_present_writes_nothing(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "Bash", "hooks": [{"command": "theirs.sh"}]}])
    before = settings.read_text(encoding="utf-8")
    assert "skip" in vis.unregister_gate(tmp_path)
    assert settings.read_text(encoding="utf-8") == before


# -------------------------------------------------- settings.json 을 읽고 쓰는 일 자체
