"""scripts/harness/jsonfile.py 단위 테스트 — 원자적 쓰기 · 권한 · 인코딩.

여러 설치자(Claude·Codex 등)가 공유할 하네스 중립 함수만 모은 모듈이라, 여기 테스트는
`vdev_init_setup` 을 거치지 않고 `jsonfile` 의 함수를 직접 호출해 잼. `tests/vdev_init/
test_settings_io.py` 의 `register_gate` 경유 테스트와 커버리지가 겹치는 것은 의도임 —
그 파일의 collected node id 는 이동 전후로 동일함.
"""

import json
import os
import stat as _stat
from pathlib import Path

import pytest

import scripts.harness.jsonfile as jf
from tests.vdev_init._helpers import ACCESS_ENTRIES, _set_acl


def test_a_reason_survives_an_error_that_carries_no_strerror():
    assert jf.why(OSError()) == "OSError"
    assert jf.why(ValueError("surrogates not allowed")) == "surrogates not allowed"
    assert jf.why(OSError(2, "no such file")) == "no such file"


def test_the_access_entries_constant_matches_the_kernel_attribute_name():
    assert jf.ACCESS_ENTRIES == ACCESS_ENTRIES


def test_the_access_entries_are_read_from_the_file_itself(tmp_path: Path):
    """carry-over 테스트가 이 함수를 교체하므로 아무것도 이것을 돌리지 않음 — 잘못 철자한
    xattr 이름도, 언제나 None 을 답하는 리더도 스위트를 초록으로 둠."""
    plain = tmp_path / "plain.json"
    plain.write_text("{}", encoding="utf-8")
    assert jf.access_entries(plain) is None  # 걸린 것도 없고 raise 도 없음
    acl = _set_acl(plain)
    assert jf.access_entries(plain) == acl


def test_write_json_creates_a_pretty_printed_utf8_file(tmp_path: Path):
    target = tmp_path / "out.json"
    data = {"b": 1, "a": "한글"}
    assert jf.write_json(target, data, tmp_path) is None
    want = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    assert target.read_text(encoding="utf-8") == want


def test_a_lone_surrogate_is_reported_without_touching_the_target(tmp_path: Path):
    """`ensure_ascii=False` 는 고립 서로게이트를 그대로 문자열에 남기고, UTF-8 로 쓰는 순간
    그것이 ValueError 로 터짐 — 그 길도 `(OSError, ValueError)` 가 잡음."""
    target = tmp_path / "out.json"
    poisoned = json.dumps({"n": "\ud800"})
    target.write_text(poisoned, encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    assert jf.write_json(target, {"n": "\ud800"}, tmp_path).startswith("  [!]")
    assert target.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("out.json.*")), "임시 파일이 남았다"


def test_write_json_uses_a_temporary_file_beside_the_target(tmp_path: Path, monkeypatch):
    """rename 은 파일시스템을 건너지 못함 — 대상 옆이 아닌 곳에 만들면 프로젝트를 다른
    볼륨에 두는 호스트에서만 쓰기가 실패함."""
    target = tmp_path / "out.json"
    seen = []
    real = jf.tempfile.mkstemp

    def spy(*args, **kwargs):
        seen.append(kwargs.get("dir"))
        return real(*args, **kwargs)

    monkeypatch.setattr(jf.tempfile, "mkstemp", spy)
    jf.write_json(target, {}, tmp_path)
    assert seen == [tmp_path], seen


@pytest.mark.parametrize(
    "failure",
    [PermissionError(13, "Permission denied"), OSError(28, "No space left on device")],
    ids=["no permission", "full disk"],
)
def test_a_write_that_cannot_make_a_temporary_file_leaves_the_target_alone(
    tmp_path: Path, monkeypatch, failure
):
    target = tmp_path / "out.json"
    target.write_text('{"kept": true}', encoding="utf-8")
    before = target.read_bytes()

    def refuse(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(jf.tempfile, "mkstemp", refuse)
    assert jf.write_json(target, {"kept": False}, tmp_path).startswith("  [!]")
    assert target.read_bytes() == before
    assert not list(tmp_path.glob("out.json.*"))


def test_a_readonly_target_is_refused(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o444)
    try:
        if os.access(target, os.W_OK):  # 비트가 소유자를 막지 않는 호스트
            pytest.skip("read-only is not enforced here")
        assert jf.write_json(target, {"x": 1}, tmp_path).startswith("  [!]")
        assert target.read_text(encoding="utf-8") == "{}"
    finally:
        target.chmod(0o644)


def test_a_symlinked_target_is_written_through_the_link(tmp_path: Path):
    """rename 은 **이름**을 갈아치우므로, 심링크는 그것이 가리키는 쪽에 내려앉아야 함."""
    managed = tmp_path / "real.json"
    managed.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(managed)
    except OSError as exc:  # 심링크를 만들 권한이 없는 호스트
        pytest.skip(str(exc))
    assert jf.write_json(link, {"a": 1}, tmp_path) is None
    assert link.is_symlink()
    assert json.loads(managed.read_text(encoding="utf-8")) == {"a": 1}


def test_the_mode_the_target_had_survives_a_write(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o644)
    before = _stat.S_IMODE(target.stat().st_mode)
    if before != 0o644:  # 비트를 옮기지 않는 파일시스템의 호스트
        pytest.skip(f"mode not honoured here: {before:o}")
    assert jf.write_json(target, {"a": 1}, tmp_path) is None
    assert _stat.S_IMODE(target.stat().st_mode) == before


def test_a_created_file_is_as_open_as_the_umask_allows(tmp_path: Path):
    target = tmp_path / "out.json"
    assert jf.write_json(target, {}, tmp_path) is None
    mode = _stat.S_IMODE(target.stat().st_mode)
    mask = os.umask(0)
    os.umask(mask)
    if 0o666 & ~mask == 0o666:  # 비트를 옮기지 않는 파일시스템의 호스트
        pytest.skip(f"mode not honoured here: {mode:o}")
    assert mode == 0o666 & ~mask, oct(mode)


def test_the_access_entries_and_owner_are_carried_over(tmp_path: Path, monkeypatch):
    target = tmp_path / "out.json"
    target.write_text("{}", encoding="utf-8")
    entries = b"entries the host set"
    chowned, xattred = [], []
    monkeypatch.setattr(jf, "access_entries", lambda _p: entries)
    monkeypatch.setattr(
        jf.os, "setxattr", lambda p, name, value: xattred.append((name, value)), raising=False
    )
    monkeypatch.setattr(jf.os, "getuid", lambda: 4242, raising=False)
    monkeypatch.setattr(jf.os, "getgid", lambda: 4242, raising=False)
    monkeypatch.setattr(
        jf.os, "chown", lambda p, uid, gid: chowned.append((uid, gid)), raising=False
    )
    before = target.stat()
    assert jf.write_json(target, {"a": 1}, tmp_path) is None
    assert xattred == [(jf.ACCESS_ENTRIES, entries)], xattred
    assert chowned == [(before.st_uid, before.st_gid)], chowned


def test_a_named_user_entry_survives_the_write(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text("{}", encoding="utf-8")
    acl = _set_acl(target)
    assert jf.write_json(target, {"a": 1}, tmp_path) is None
    assert os.getxattr(target, ACCESS_ENTRIES) == acl


def test_load_json_object_reads_absent_as_empty_and_null_as_empty(tmp_path: Path):
    assert jf.load_json_object(tmp_path / "none.json", "x.json") == ({}, None)
    f = tmp_path / "null.json"
    f.write_text("null", encoding="utf-8")
    assert jf.load_json_object(f, "x.json") == ({}, None)


def test_load_json_object_strips_a_bom(tmp_path: Path):
    f = tmp_path / "bom.json"
    f.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode("utf-8"))
    assert jf.load_json_object(f, "x.json") == ({"a": 1}, None)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"{not json", "파싱 실패"),
        (b"[]", "객체가 아닙니다"),
        (b"0", "객체가 아닙니다"),
        (b'{"a": "\xff"}', "UTF-8 이 아닙니다"),
    ],
    ids=["garbage", "list", "zero", "not-utf8"],
)
def test_load_json_object_names_the_label_in_every_refusal(tmp_path: Path, raw, reason):
    """`0`·`[]` 는 데이터라 빈 객체로 읽지 않음 — 그렇게 읽으면 호스트 파일을 덮어씀."""
    f = tmp_path / "bad.json"
    f.write_bytes(raw)
    data, err = jf.load_json_object(f, "x.json")
    assert data is None
    assert err is not None and "x.json" in err and reason in err
