"""실행의 판정 — 완료 문구와 종료 코드가 무엇을 근거로 나오는가.

등록 줄에 물으면 질문이 스스로 답함(나중 단계의 쓰기 실패도, 발화하지 않는 매처도,
통째로 꺼진 훅도 그 줄은 문제 없다고 말함). 그래서 판정은 언제나 실행이 **남긴
것**에서 만들어짐 — setup 은 `_gate_problems`, uninstall 은 `_gate_hook_remains`.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from tests.vdev_init._helpers import (
    MALFORMED,
    PLUGIN,
    _gate_commands,
    _gate_hook,
    _gate_is_in,
    _is_gate,
    _planted,
)


@pytest.mark.parametrize("label,payload", MALFORMED, ids=[label for label, _ in MALFORMED])
def test_a_settings_shape_the_schema_does_not_describe_is_reported(
    tmp_path: Path, label: str, payload
):
    """읽을 수 없는 모양이면 손대지 않고, 읽을 수 있는 곳 아래의 쓰레기라면 그 둘레로
    설치하되 호스트가 쓴 엔트리는 전부 그대로 남음."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps(payload), encoding="utf-8")
    before = settings.read_bytes()
    outs = [vis.register_gate(tmp_path), vis.unregister_gate(tmp_path)]
    for out in outs:
        assert out[:5] in ("  [!]", "  [=]", "  [+]", "  [-]"), (label, out)
    if outs[0].startswith("  [!]"):
        assert settings.read_bytes() == before, label
        return
    planted = (payload.get("hooks") or {}).get("PreToolUse")
    kept = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert all(entry in kept for entry in planted), (label, kept)


@pytest.mark.parametrize("label,payload", MALFORMED, ids=[label for label, _ in MALFORMED])
def test_setup_finishes_its_other_steps_on_a_settings_shape_it_cannot_use(
    tmp_path: Path, label: str, payload, monkeypatch, capsys
):
    """`/vdev-init` 은 각 단계의 결과를 무방비로 찍으므로, raise 하나가 마켓 등록·pre-commit
    점검·.gitignore·렌더된 모든 워크플로우를 게이트와 함께 끌고 내려감.

    다만 끝내는 것이 성공은 아님: 등록되지 않은 게이트는 설치의 요점 자체가 빠진 것이고,
    그 `[!]` 한 줄은 마흔 줄 사이로 지나감. 그래서 마지막 줄과 종료 코드가 게이트와,
    어느 쪽이든, 일치해야 함."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
    monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py"])
    code = 0
    try:
        vis.main()
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr().out
    # 출력에 물으면 질문이 스스로 답함: 줄을 아예 찍지 않는 빌드는 문제가 없다는 자기
    # 말과 일치. 호스트의 파일이 앎.
    registered = _gate_is_in(tmp_path / ".claude" / "settings.json")
    assert (code == 0) is registered, (label, code, out)
    assert ("기계적 셋업 완료" in out) is registered, (label, out)
    assert (tmp_path / ".gitignore").is_file()
    assert (tmp_path / ".claude" / "vway-kit" / "scripts" / "precommit-runner.sh").is_file()


def test_hooks_turned_off_wholesale_is_not_a_finished_setup(tmp_path: Path, monkeypatch, capsys):
    """게이트가 결코 발화하지 않으리라고 대놓고 말하는 유일한 입력이고, `기계적 셋업 완료.`
    를 exit 0 으로 끝내던 바로 그 입력."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"disableAllHooks": True}), encoding="utf-8"
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
    monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py"])
    with pytest.raises(SystemExit) as raised:
        vis.main()
    assert raised.value.code == 1
    out = capsys.readouterr().out
    assert "기계적 셋업 완료" not in out
    assert "disableAllHooks" in out


def test_a_gate_hook_under_a_matcher_that_does_not_fire_is_not_a_gate(
    tmp_path: Path, monkeypatch, capsys
):
    """훅은 파일 안에 있으므로 하나 있느냐만 묻는 것은 셋업이 끝났다고 말함. 그것은
    `Read` 에 발화하고 커밋은 Bash 로 도착 — 그리고 평소라면 그것을 빼 왔을
    settings.json 을 쓸 수 없음."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "Read", "hooks": [_gate_hook()]}])
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):  # 비트가 소유자를 막지 않는 호스트
            pytest.skip("read-only is not enforced here")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
        monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py"])
        with pytest.raises(SystemExit) as raised:
            vis.main()
        assert raised.value.code == 1
        out = capsys.readouterr().out
        assert "커밋 게이트가 settings.json 에 없습니다" in out
        assert "기계적 셋업 완료" not in out
        assert any(_is_gate(c) for c in _gate_commands(settings)), "훅은 여전히 거기 있다"
    finally:
        settings.chmod(0o644)


@pytest.mark.parametrize(
    "field", [{"if": "Bash(git commit:*)"}, {"async": True}, {"type": "prompt"}]
)
def test_a_gate_hook_the_repair_could_not_reach_is_not_a_finished_setup(
    tmp_path: Path, monkeypatch, capsys, field: dict
):
    """`if` 를 도로 떼는 수리는 쓰기가 내려앉을 때만 내려앉음. 발화하는 매처 아래 게이트
    훅이 **하나라도** 있느냐로 물으면, 쓸 수 없었던 settings.json 이 아무것에도 발화하지
    않는 훅 위에서 끝난 셋업을 보고함(Invariant 4)."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "Bash", "hooks": [dict(_gate_hook(), **field)]}])
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):
            pytest.skip("read-only is not enforced here")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
        monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py"])
        with pytest.raises(SystemExit) as raised:
            vis.main()
        assert raised.value.code == 1
        assert "기계적 셋업 완료" not in capsys.readouterr().out
    finally:
        settings.chmod(0o644)


def test_a_gate_that_is_there_and_firing_is_a_finished_setup(tmp_path: Path, monkeypatch, capsys):
    """등록 줄은 무언가 잘못됐다고 말함 — 발화하지 않는 엔트리에서 옮기려던 게이트 훅과,
    그러기 위해 쓸 수 없었던 settings.json. 게이트 자체는 내내 등록돼 있고 발화했으며,
    셋업의 판정은 게이트에 대한 것."""
    import scripts.vdev_init_setup as vis

    settings = _planted(
        tmp_path,
        [
            {"matcher": "Bash", "hooks": [_gate_hook()]},
            {"matcher": "Read", "hooks": [_gate_hook()]},
        ],
    )
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):
            pytest.skip("read-only is not enforced here")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
        monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py"])
        vis.main()
        out = capsys.readouterr().out
        assert "기계적 셋업 완료" in out
        assert "커밋 게이트가 settings.json 에 없습니다" not in out
    finally:
        settings.chmod(0o644)


def test_a_matcher_this_cannot_decide_is_not_a_missing_gate(tmp_path: Path, monkeypatch, capsys):
    """`^Bash$` 는 발화함. 발화하지 않는 매처로 읽으면 그것을 일부러 앵커한 호스트가
    게이트가 없다는 말을 듣고 고장나지 않은 것을 고치러 감."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "^Bash$", "hooks": [_gate_hook()]}])
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):
            pytest.skip("read-only is not enforced here")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
        monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py"])
        vis.main()
        assert "기계적 셋업 완료" in capsys.readouterr().out
    finally:
        settings.chmod(0o644)


def test_the_gate_command_resolves_against_the_host():
    """훅은 Claude Code 의 셸이 어디에 있든 거기서 돌므로 경로는 호스트 자신의 것이어야
    함 — 상대 경로로 철자하면 세션이 앉아 있던 아무 디렉터리나 이름 대는 셈."""
    import scripts.vdev_init_setup as vis

    assert "${CLAUDE_PROJECT_DIR:-.}/" in vis.GATE_COMMAND, vis.GATE_COMMAND
    assert vis.GATE_ENTRY["hooks"][0]["command"] == vis.GATE_COMMAND


def test_the_files_the_gate_needs_are_named_exactly():
    """상수에서 읽어 오지 않고 직접 철자함 — 목록을 순회하는 테스트는 항목이 목록을
    **떠나는** 것을 알아채지 못함. 그리고 각각을 호스트에서 지웠을 때 러너가 진짜 커밋에
    exit 0 하는 것이 실측됨."""
    import scripts.vdev_init_setup as vis

    assert {Path(rel).name for rel, _source in vis.GATE_FILES} == {
        "precommit-runner.sh",
        "vdev_gate_check.py",
        "_vway_paths.py",
        "vdev-tiers.yaml",
    }


def test_every_file_the_gate_needs_is_one_a_finished_setup_leaves(tmp_path: Path, capsys):
    """판정이 호스트에게 이것들을 이름으로 물음 — 한쪽만 재명명되면 방금 설치에 실패한
    게이트를 보고하는 셋업이거나, 멀쩡한 게이트에 늑대야 외치는 셋업."""
    import scripts.vdev_init_setup as vis

    assert vis.run_setup(tmp_path, PLUGIN) is True
    assert "기계적 셋업 완료." in capsys.readouterr().out
    for rel, source in vis.GATE_FILES:
        assert (tmp_path / rel).read_bytes() == (PLUGIN / source).read_bytes(), rel


@pytest.mark.parametrize(
    "rel",
    [
        ".claude/vway-kit/scripts/precommit-runner.sh",
        ".claude/vway-kit/scripts/vdev_gate_check.py",
        ".claude/vway-kit/scripts/_vway_paths.py",
        ".claude/vway-kit/config/vdev-tiers.yaml",
    ],
)
def test_a_gate_file_that_landed_corrupt_is_not_a_finished_setup(tmp_path: Path, rel: str):
    """목적지를 만들거나 비운 뒤 실패한 복사는 이름을 남기므로, 파일이 **거기 있느냐**는
    물음이 빈 파일 위에서 그렇다고 답함 — `bash` 는 그것에 exit 0 하고 PyYAML 은 아무것도
    아닌 것으로 읽으며, 스스로 설치됐다고 부른 게이트는 아무 커밋도 막지 않음. 부분 쓰기는
    같은 경우라, 호스트 사본을 비교함."""
    import scripts.vdev_init_setup as vis

    assert vis.run_setup(tmp_path, PLUGIN) is True
    assert vis._gate_problems(tmp_path, PLUGIN) == []
    (tmp_path / rel).write_bytes(b"")
    problems = vis._gate_problems(tmp_path, PLUGIN)
    assert problems and Path(rel).name in problems[0], (rel, problems)


def test_a_gate_whose_scripts_did_not_land_is_not_a_finished_setup(
    tmp_path: Path, monkeypatch, capsys
):
    """훅은 파일을 지목하는 텍스트 한 줄. 복사 단계가 쓰지 못한 호스트에 그것을 등록하면
    `bash` 가 모든 명령에 127 로 답하고 — 커밋을 막는 exit 2 는 결코 아니고 — 실행은 그
    위에서 `기계적 셋업 완료.` 라고 말함. 호스트는 모든 커밋이 게이팅된다고 믿지만 하나도
    게이팅되지 않음."""
    import scripts.vdev_init_setup as vis

    real = vis.shutil.copyfile

    def refuse(src, dst, *args, **kwargs):
        if Path(dst).name == "precommit-runner.sh":
            raise PermissionError(13, "Permission denied")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(vis.shutil, "copyfile", refuse)
    assert vis.run_setup(tmp_path, PLUGIN) is False
    out = capsys.readouterr().out
    assert "복사 실패" in out, out
    assert "커밋 게이트가 쓰는 파일이 호스트에 없거나 손상됐습니다" in out, out
    assert "precommit-runner.sh" in out, out
    assert "기계적 셋업 완료." not in out, out
    # …그리고 복사하지 못한 그 파일 하나만이 이것이 포기한 유일한 파일임.
    assert (tmp_path / ".claude/vway-kit/scripts/vdev_gate_check.py").is_file()


def test_a_policy_that_did_not_land_is_not_a_finished_setup(tmp_path: Path, monkeypatch, capsys):
    """`vdev-tiers.yaml` 이 없으면 아무것도 파싱되지 않아 커밋의 tier 를 읽을 수 없고,
    미분류 커밋 deny — 이 게이트가 결코 fail-open 하면 안 되는 셋 중 하나 — 가 발화하지
    않음. 러너로 직접 실측: 정책 없이 `git commit -m x` 에 exit 0, 되돌리면 exit 2."""
    import scripts.vdev_init_setup as vis

    real = vis.shutil.copyfile

    def refuse(src, dst, *args, **kwargs):
        if Path(dst).name == vis.TIERS_FILENAME:
            raise PermissionError(13, "Permission denied")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(vis.shutil, "copyfile", refuse)
    assert vis.run_setup(tmp_path, PLUGIN) is False
    out = capsys.readouterr().out
    assert "복사 실패" in out, out
    assert "커밋 게이트가 쓰는 파일이 호스트에 없거나 손상됐습니다" in out, out
    assert vis.TIERS_FILENAME in out, out
    assert "기계적 셋업 완료" not in out, out


def test_the_config_directory_is_made_with_no_policy_source(tmp_path: Path):
    """`/vdev-init` 이 호스트 자신의 vdev-config 을 정책 옆에 두므로 그 디렉터리는 정책이
    withhold 할 것이 아님 — 복사를 가드하면 소스의 부재가 무조건 돌던 `mkdir` 을
    건너뛰게 만듦."""
    import scripts.vdev_init_setup as vis

    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    host = tmp_path / "host"
    host.mkdir()
    vis.copy_artifacts(plugin, host)
    assert (host / vis.CONFIG_DIR).is_dir()


def test_a_step_that_cannot_finish_still_reaches_the_verdict(tmp_path: Path, monkeypatch, capsys):
    """단계는 자기가 찾아간 문제를 보고하고 나머지에서는 raise 함. 판정은 호출자가 보러 온
    줄이므로 어떤 단계도 그 전에 실행을 끝낼 수 없음."""
    import scripts.vdev_init_setup as vis

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(vis, "render_workflow", refuse)
    assert vis.run_setup(tmp_path, PLUGIN) is True
    out = capsys.readouterr().out
    assert "이 단계를 끝내지 못했습니다" in out, out
    assert "끝내지 못한 단계가 있습니다" in out, out
    assert "기계적 셋업 완료." not in out, out


def test_a_closed_claude_directory_does_not_end_the_run(tmp_path: Path, capsys):
    """가드된 `mkdir` 은 그 디렉터리 아래 여러 프로브 중 하나이고 다음 무방비 프로브가
    raise 함 — `load_contract_config` 가 그 안 경로에 `is_file()` 을 물음. 실행은
    게이트가 켜졌는지 말하는 판정 전에 거기서 끝남."""
    import scripts.vdev_init_setup as vis

    closed = tmp_path / ".claude"
    closed.mkdir()
    closed.chmod(0o000)
    try:
        if os.access(closed, os.R_OK):  # 비트가 소유자를 막지 않는 호스트
            pytest.skip("a closed directory is not enforced here")
        assert vis.run_setup(tmp_path, PLUGIN) is False
    finally:
        closed.chmod(0o755)
    out = capsys.readouterr().out
    assert "이 단계를 끝내지 못했습니다" in out, out
    assert "커밋 게이트가 쓰는 파일이 호스트에 없거나 손상됐습니다" in out, out


def test_a_claude_directory_that_cannot_be_entered_is_reported(tmp_path: Path):
    """`Path.is_file()` 은 권한 오류를 삼키지 않으므로, 가드가 막 더해진 그 자리 다음 줄이
    스크립트를 끌어내림 — 그리고 먼저 도는 복사가 같은 일을 해서 워크플로우와
    .gitignore 를 함께 데려감."""
    import scripts.vdev_init_setup as vis

    closed = tmp_path / ".claude"
    closed.mkdir()
    closed.chmod(0o000)
    try:
        if os.access(closed, os.R_OK):
            pytest.skip("a closed directory is not enforced here")
        assert vis.register_gate(tmp_path).startswith("  [!]")
        assert vis.copy_artifacts(PLUGIN, tmp_path)[0].startswith("  [!]")
    finally:
        closed.chmod(0o755)


def test_a_host_config_whose_shape_is_wrong_does_not_end_the_run(tmp_path: Path, capsys):
    """`vdev-config.yaml` 은 사람이 손대는 파일이라 최상위의 리스트나 스칼라는 불가능이
    아니라 오타 — 매핑으로 읽으면 단계 래퍼를 지나쳐 raise 하고, 판정 여섯 단계 앞에서
    트레이스백으로 끝남."""
    import scripts.vdev_init_setup as vis

    cfg = vis.config_path(tmp_path)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("- a" + chr(10) + "- b" + chr(10), encoding="utf-8")
    assert vis.run_setup(tmp_path, PLUGIN) is True
    assert "기계적 셋업 완료" in capsys.readouterr().out


def test_a_pre_commit_config_whose_shape_is_wrong_is_reported(tmp_path: Path):
    """같은 손편집을, 위생 레이어가 소유한 파일에서: 매핑으로 읽어 줄을 보고하는 대신
    실행을 끌어내림."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".pre-commit-config.yaml").write_text("- a" + chr(10), encoding="utf-8")
    lines = vis.check_precommit(PLUGIN, tmp_path)
    assert lines and lines[0].startswith("  [!]"), lines


def test_an_uninstall_that_leaves_the_hook_behind_says_so(tmp_path: Path, monkeypatch, capsys):
    """훅이 지목하는 스크립트를 같은 실행이 지우므로, 쓰지 못한 settings.json 은 그 호스트의
    모든 Bash 명령이 없는 파일을 돌게 만듦."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "Bash", "hooks": [_gate_hook()]}])
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):
            pytest.skip("read-only is not enforced here")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
        monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py", "--uninstall"])
        with pytest.raises(SystemExit) as raised:
            vis.main()
        assert raised.value.code == 1
        out = capsys.readouterr().out
        assert "정리 완료" not in out
        assert "남았습니다" in out
        assert any(_is_gate(c) for c in _gate_commands(settings))
    finally:
        settings.chmod(0o644)


@pytest.mark.parametrize(
    "raw",
    ['{"a": 1,,}', "settings".encode("cp949").decode("latin-1"), '["a host array"]'],
    ids=["unparseable", "not utf-8", "not an object"],
)
def test_an_uninstall_that_cannot_read_settings_says_the_hook_may_remain(
    tmp_path: Path, monkeypatch, capsys, raw: str
):
    """읽지 못하는 파일은 지우지도 못한 파일이고, 같은 실행이 그 훅이 지목하는 스크립트를
    이미 지움. 그 위의 `정리 완료.` 가 이 판정이 막으려는 거짓말이고, cp949 철자는 이
    게이트가 쓰이는 그 호스트(Invariant 2)."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text(raw, encoding="latin-1")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
    monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py", "--uninstall"])
    with pytest.raises(SystemExit) as raised:
        vis.main()
    assert raised.value.code == 1
    out = capsys.readouterr().out
    assert "남았습니다" in out
    assert "정리 완료" not in out


def test_an_uninstall_step_that_cannot_finish_still_reaches_the_verdict(
    tmp_path: Path, monkeypatch, capsys
):
    """셋업 쪽은 래퍼를 받았고 이쪽은 못 받아서, 호스트가 닫아 둔 `.claude` 가 훅이 남았다는
    줄 전에 실행을 끝냄 — 같은 실행이 이미 지운 스크립트를 가리키는 훅."""
    import scripts.vdev_init_setup as vis

    _planted(tmp_path, [{"matcher": "Bash", "hooks": [_gate_hook()]}])

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(vis, "remove_vway_dir", refuse)
    assert vis.run_uninstall(tmp_path) is True
    out = capsys.readouterr().out
    assert "이 단계를 끝내지 못했습니다" in out, out
    assert "끝내지 못한 단계가 있습니다" in out, out
    assert "정리 완료." not in out, out


def test_an_uninstall_prints_the_follow_ups_it_is_quoted_for(tmp_path: Path, capsys):
    """`/vdev-uninstall` 은 사용자를 "스크립트가 찍는 수동 후속 조치" 로 보내고, 이제
    삭제된 스크립트를 이름 대는 git 훅을 끄는 유일한 안내가 그 안에 있음."""
    import scripts.vdev_init_setup as vis

    _planted(tmp_path, [{"matcher": "Bash", "hooks": [_gate_hook()]}])
    assert vis.run_uninstall(tmp_path) is True
    out = capsys.readouterr().out
    assert "pre-commit uninstall" in out
    assert "정리 완료." in out


def test_a_step_prints_what_its_earlier_producers_made(tmp_path: Path, monkeypatch, capsys):
    """한 제목 아래 생산자가 여럿인 단계가 있음(`[gitignore]`·`[폐기 필드 점검]`). 결과를
    이어 붙여 한 번에 찍으면 뒤에서 난 raise 가 앞 생산자의 `[!]` 줄까지 삼키는데, 그 줄들이
    곧 사용자가 고쳐야 할 목록 — 판정만 남고 조치가 사라짐."""
    import scripts.vdev_init_setup as vis

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(vis, "prune_stale_gitignore", refuse)
    vis.run_setup(tmp_path, PLUGIN)
    out = capsys.readouterr().out
    # 같은 단계의 앞 생산자가 만든 줄이 살아 있음.
    assert ".gitignore" in out, out
    assert "이 단계를 끝내지 못했습니다" in out, out
