"""settings.json 을 읽고 쓰는 일 자체 — 원자성 · 권한 · 인코딩.

이 파일은 호스트 소유. 쓰기가 실패해도 원본이 남아야 하고, 호스트가 준 모드·ACL·
심볼릭 링크는 살아남아야 하며, UTF-8 이 아니거나 객체가 아닌 문서는 덮어쓰지 않고
보고해야 함.
"""

import json
import os
from pathlib import Path

import pytest

from tests.vdev_init._helpers import (
    ACCESS_ENTRIES,
    _gate_commands,
    _gate_hook,
    _is_gate,
    _planted,
    _set_acl,
)


def test_a_settings_path_that_cannot_be_written_is_reported(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude" / "settings.json").mkdir(parents=True)
    assert vis.register_gate(tmp_path).startswith("  [!]")


def test_a_claude_directory_that_is_a_file_is_reported(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").write_text("not a directory", encoding="utf-8")
    assert vis.register_gate(tmp_path).startswith("  [!]")
    assert vis.unregister_gate(tmp_path).startswith("  [!]")
    assert vis.register_marketplace(tmp_path).startswith("  [!]")


def test_a_settings_file_that_cannot_be_read_is_reported(tmp_path: Path, monkeypatch):
    """파일은 있는데 읽기가 실패 — 잠금·권한·장치. 셋업의 나머지 단계는 이 뒤에도 돌아감."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    real = Path.read_text

    def refuse(self, *a, **kw):
        if self.name == "settings.json":
            raise OSError(13, "Permission denied")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", refuse)
    assert "읽지 못했습니다" in vis.register_gate(tmp_path)
    assert "읽지 못했습니다" in vis.unregister_gate(tmp_path)


def test_a_settings_file_too_deep_to_parse_is_reported(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text(
        "[" * 100000 + "]" * 100000, encoding="utf-8"
    )
    assert "파싱 실패" in vis.register_gate(tmp_path)


@pytest.mark.parametrize("document", ["false", "0", '""', "[]", "0.0"])
def test_a_falsy_document_is_data_not_an_empty_one(tmp_path: Path, document: str):
    """`json.loads(...) or {}` 가 모양 검사보다 먼저 돌면 falsy 한 값이 전부 빈 객체로
    쓰기에 닿아 깨끗한 등록 줄 아래에서 덮어써짐. `null` 만이 "아직 아무것도 설정 안 됨"
    에 대한 호스트 자신의 철자."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(document, encoding="utf-8")
    assert vis.register_gate(tmp_path).startswith("  [!]")
    assert settings.read_text(encoding="utf-8") == document


def test_a_document_that_is_not_an_object_is_left_alone(tmp_path: Path):
    """보고하되 덮어쓰지 않음. 가드는 파일이 그것을 넘기고 살아남을 때만 값어치가 있음."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text('["the host\'s own array-shaped config", {"keep": "me"}]', encoding="utf-8")
    before = settings.read_text(encoding="utf-8")
    assert vis.register_gate(tmp_path).startswith("  [!]")
    assert settings.read_text(encoding="utf-8") == before


def test_a_settings_file_holding_only_null_still_takes_the_gate(tmp_path: Path):
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text("null", encoding="utf-8")
    assert "등록" in vis.register_gate(tmp_path)
    assert any(_is_gate(c) for c in _gate_commands(settings))


def test_hooks_turned_off_wholesale_is_said_out_loud(tmp_path: Path):
    """모든 훅을 끄는 settings.json 에 등록하면서 돌 수 없는 게이트의 깨끗한 설치를
    보고함."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"disableAllHooks": True}), encoding="utf-8"
    )
    assert "disableAllHooks" in vis.register_gate(tmp_path)


def test_a_reason_survives_an_error_that_carries_no_strerror():
    import scripts.vdev_init_setup as vis

    assert vis._why(OSError()) == "OSError"
    assert vis._why(ValueError("surrogates not allowed")) == "surrogates not allowed"
    assert vis._why(OSError(2, "no such file")) == "no such file"


def test_a_write_that_fails_leaves_the_host_file_as_it_was(tmp_path: Path):
    """쓰기로 여는 것이 쓰기 전에 truncate 하므로, 중간에 실패하면 호스트 설정은 사라짐 —
    그리고 보고 줄은 그것을 "쓰지 못했습니다" 라고 부를 참."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    # 고립 서로게이트 하나는 JSON 으로 파싱되고 인코딩은 되지 않음.
    poisoned = json.dumps({"permissions": {"allow": ["Bash"]}, "n": "\ud800"})
    settings.write_text(poisoned, encoding="utf-8")
    before = settings.read_text(encoding="utf-8")
    assert vis.register_gate(tmp_path).startswith("  [!]")
    assert settings.read_text(encoding="utf-8") == before
    assert not list((tmp_path / ".claude").glob("settings.json.*")), "임시 파일이 남았다"


def test_the_temporary_file_is_made_beside_the_file_it_replaces(tmp_path: Path, monkeypatch):
    """rename 은 파일시스템을 건너지 못함. 대상 옆이 아닌 곳에 만들면, 프로젝트를 다른
    볼륨에 두는 바로 그 호스트들에서만 쓰기가 실패함."""
    import scripts.vdev_init_setup as vis

    seen = []
    real = vis.tempfile.mkstemp

    def spy(*args, **kwargs):
        seen.append(kwargs.get("dir"))
        return real(*args, **kwargs)

    monkeypatch.setattr(vis.tempfile, "mkstemp", spy)
    vis.register_gate(tmp_path)
    assert seen == [tmp_path / ".claude"], seen


def test_a_temporary_file_does_not_consume_one_the_host_already_had(tmp_path: Path):
    """settings.json 옆의 이름이 고정이면 호스트가 거기 갖고 있던 무엇이든 rename 과
    함께 사라짐."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    victim = tmp_path / ".claude" / "settings.json.vway-new"
    victim.write_text("the host wrote this", encoding="utf-8")
    vis.register_gate(tmp_path)
    assert victim.read_text(encoding="utf-8") == "the host wrote this"


@pytest.mark.parametrize(
    "failure",
    [
        PermissionError(13, "Permission denied"),
        OSError(28, "No space left on device"),
        OSError(122, "Disk quota exceeded"),
    ],
    ids=["no permission", "full disk", "over quota"],
)
def test_a_write_that_cannot_make_a_temporary_file_leaves_the_host_alone(
    tmp_path: Path, monkeypatch, failure
):
    """제자리에 쓰는 것은 임시 파일이 막으려는 그 truncate 이고, `mkstemp` 는 쓸 수 없는
    디렉터리 말고도 여러 이유로 실패함 — 꽉 찬 디스크와 고갈된 inode 가 같은 호출에
    닿는데, 그때 호스트 자신의 파일은 완벽하게 쓸 수 있음."""
    import scripts.vdev_init_setup as vis

    settings = _planted(tmp_path, [{"matcher": "Read", "hooks": []}])
    before = settings.read_bytes()

    def refuse(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(vis.tempfile, "mkstemp", refuse)
    assert vis.register_gate(tmp_path).startswith("  [!]")
    assert settings.read_bytes() == before
    assert not list((tmp_path / ".claude").glob("settings.json.*"))


def test_a_marketplace_write_that_fails_is_reported(tmp_path: Path, monkeypatch):
    """settings.json 을 쓰는 모든 단계가 그것을 말해야 함 — 셋업의 판정은 파일을 읽지만,
    어느 쓰기가 잘못됐는지를 이름 대는 것은 그 단계 자신의 줄임."""
    import scripts.vdev_init_setup as vis

    _planted(tmp_path, [{"matcher": "Bash", "hooks": [_gate_hook()]}])

    def refuse(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(vis.tempfile, "mkstemp", refuse)
    assert vis.register_marketplace(tmp_path).startswith("  [!]")


def test_an_uninstall_write_that_fails_is_reported(tmp_path: Path, monkeypatch):
    """제거 쪽도 자기 결과를 버리지 않음. 호스트 훅을 곁에 둬 파일이 비지 않게 함 — 비면 쓰기
    대신 삭제로 감."""
    import scripts.vdev_init_setup as vis

    theirs = {"type": "command", "command": "theirs.sh"}
    _planted(tmp_path, [{"matcher": "Bash", "hooks": [_gate_hook(), theirs]}])

    def refuse(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(vis.tempfile, "mkstemp", refuse)
    assert vis.unregister_gate(tmp_path).startswith("  [!]")


def test_a_settings_file_the_host_keeps_as_a_link_is_written_through(tmp_path: Path):
    """rename 은 이름을 갈아치우므로 링크가 평범한 파일이 되고, 호스트가 실제로 관리하는
    dotfiles 사본은 옛 내용을 유지함 — 다음 동기화가 게이트째 그것을 도로 깔아 놓음."""
    import scripts.vdev_init_setup as vis

    managed = tmp_path / "dotfiles-settings.json"
    managed.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}), encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    link = tmp_path / ".claude" / "settings.json"
    try:
        link.symlink_to(managed)
    except OSError as exc:  # 심링크를 만들 권한이 없는 호스트
        pytest.skip(str(exc))
    assert "등록" in vis.register_gate(tmp_path)
    assert link.is_symlink()
    assert _is_gate(_gate_commands(managed)[0])


def test_the_mode_the_host_gave_settings_json_survives_a_write(tmp_path: Path):
    """rename 은 임시 파일의 모드를 옮기고, mkstemp 는 소유자만 읽을 수 있는 것을 만듦.
    다른 uid 가 .claude/settings.json 을 읽는 빌드 머신에서 그것은 설정이 사라진 것이고,
    git 은 exec 비트 말고는 모드를 추적하지 않아 아무것도 그것을 드러내지 않음."""
    import stat as _stat

    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}), encoding="utf-8")
    settings.chmod(0o644)
    before = _stat.S_IMODE(settings.stat().st_mode)
    if before != 0o644:  # 비트를 옮기지 않는 파일시스템의 호스트
        pytest.skip(f"mode not honoured here: {before:o}")
    assert "등록" in vis.register_gate(tmp_path)
    assert _stat.S_IMODE(settings.stat().st_mode) == before


def test_a_settings_file_this_creates_is_as_open_as_the_umask_allows(tmp_path: Path):
    """`mkstemp` 는 소유자만 읽는 파일을 만들고 rename 이 그것을 옮기므로, 가장 흔한 경로 —
    첫 설치 — 가 세션 자신의 uid 가 읽지 못할 수도 있는 settings.json 을 남김."""
    import stat as _stat

    import scripts.vdev_init_setup as vis

    assert "등록" in vis.register_gate(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    mode = _stat.S_IMODE(settings.stat().st_mode)
    mask = os.umask(0)
    os.umask(mask)
    if 0o666 & ~mask == 0o666:  # 비트를 옮기지 않는 파일시스템의 호스트
        pytest.skip(f"mode not honoured here: {mode:o}")
    assert mode == 0o666 & ~mask, oct(mode)


def test_a_settings_file_the_host_locked_is_not_replaced(tmp_path: Path):
    """rename 은 파일이 아니라 **디렉터리**에 허가를 물음 — 쓰기가 임시 파일을 거치는
    순간 읽기 전용은 아무 뜻도 없어짐."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}), encoding="utf-8")
    before = settings.read_text(encoding="utf-8")
    settings.chmod(0o444)
    try:
        if os.access(settings, os.W_OK):  # 비트가 소유자를 막지 않는 호스트
            pytest.skip("read-only is not enforced here")
        assert vis.register_gate(tmp_path).startswith("  [!]")
        assert settings.read_text(encoding="utf-8") == before
    finally:
        settings.chmod(0o644)


def test_the_access_entries_are_read_from_the_file_itself(tmp_path: Path):
    """carry-over 테스트가 이 함수를 교체하므로 아무것도 이것을 돌리지 않음 — 잘못 철자한
    xattr 이름도, 언제나 None 을 답하는 리더도 스위트를 초록으로 둠."""
    import scripts.vdev_init_setup as vis

    assert vis._ACCESS_ENTRIES == ACCESS_ENTRIES
    plain = tmp_path / "plain.json"
    plain.write_text("{}", encoding="utf-8")
    assert vis._access_entries(plain) is None  # 걸린 것도 없고 raise 도 없음
    acl = _set_acl(plain)
    assert vis._access_entries(plain) == acl


def test_a_named_user_entry_survives_the_write(tmp_path: Path):
    """carry-over 가 무엇을 위한 것인지를 호출이 아니라 파일에 물음: rename 은 새 inode 를
    내려놓고, 이름 붙은 사용자 하나에게 준 항목은 어떤 모드도 되돌리지 못하는 부분임.
    Windows 호스트는 이것을 skip 하고 Linux CI 는 하지 않음."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    acl = _set_acl(settings)
    assert "등록" in vis.register_gate(tmp_path)
    assert os.getxattr(settings, ACCESS_ENTRIES) == acl


def test_the_access_entries_and_owner_are_carried_over(tmp_path: Path, monkeypatch):
    """둘 다 rename 을 넘지 못하고 둘 다 diff 에 나타나지 않음 — `st_mode` 는 group
    비트에 ACL 마스크를 보고하므로 그것을 평범한 모드로 되돌리는 것이 이름 붙은 사용자
    하나에게 권한을 준 파일에 group 쓰기를 준 그 일이고, 새 inode 는 쓴 쪽의 것임.
    Windows 호스트는 둘 중 어느 것도 관측할 방법이 없어, 여기서 지키는 것은 **읽은 값으로
    호출이 이뤄졌다는 사실** 하나임."""
    import scripts.harness.jsonfile as jf
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}), encoding="utf-8")
    entries = b"entries the host set"
    chowned, xattred = [], []
    # `_access_entries` 는 vdev_init_setup 으로 온 re-export 일 뿐 — `write_json` 자신은
    # jsonfile 모듈 안에서 `access_entries` 를 부르므로, 그 호출을 바꾸려면 원본을 patch.
    monkeypatch.setattr(jf, "access_entries", lambda _p: entries)
    monkeypatch.setattr(
        vis.os, "setxattr", lambda p, name, value: xattred.append((name, value)), raising=False
    )
    monkeypatch.setattr(vis.os, "getuid", lambda: 4242, raising=False)
    monkeypatch.setattr(vis.os, "getgid", lambda: 4242, raising=False)
    monkeypatch.setattr(
        vis.os, "chown", lambda p, uid, gid: chowned.append((uid, gid)), raising=False
    )
    before = settings.stat()
    assert "등록" in vis.register_gate(tmp_path)
    assert xattred == [(vis._ACCESS_ENTRIES, entries)], xattred
    assert chowned == [(before.st_uid, before.st_gid)], chowned


def test_a_settings_file_that_is_not_utf8_is_reported(tmp_path: Path):
    """이 게이트가 쓰이는 호스트는 cp949 콘솔을 돌림 — 로컬 코드 페이지로 한글 주석이 든
    settings.json 은 거기서 깨진 파일이 아니라 평범한 파일임(Invariant 2)."""
    import scripts.vdev_init_setup as vis

    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_bytes('{"note": "한글"}'.encode("cp949"))
    assert "UTF-8" in vis.register_gate(tmp_path)
    assert "UTF-8" in vis.unregister_gate(tmp_path)
