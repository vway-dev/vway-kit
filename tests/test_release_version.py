"""`scripts/release_version.py` — 트레일러와 태그 목록에서 다음 버전.

릴리스 템플릿 다섯이 이 스크립트 하나에 버전을 물으므로, 여기 틀리면 모든 도구가 같은 틀린
rc 를 냄. 워크플로 배선(스텝이 이 답을 어느 출력에 싣는가)은 `test_release_rc_version.py`.
"""

from __future__ import annotations

import pytest

from scripts.release_version import (
    finalize_version,
    main,
    next_version,
    parse_level,
    pending_rc,
    stable_version,
    state,
)

_PENDING = ["v1.0.4", "v1.1.0-rc.1", "v1.1.0-rc.2"]


def _msg(level: str) -> str:
    return f"Merge dev: x\n\nRelease-Level: {level}\n"


@pytest.mark.parametrize(
    ("tags", "level", "expected"),
    [
        ([], "patch", "0.0.1-rc.1"),
        (["v1.0.4"], "minor", "1.1.0-rc.1"),
        (_PENDING, "continue", "1.1.0-rc.3"),
        (_PENDING, "patch", "1.1.1-rc.1"),
        (_PENDING, "minor", "1.2.0-rc.1"),
        (_PENDING, "major", "2.0.0-rc.1"),
        (["v0.1.3", "v0.2.0-rc.1"], "continue", "0.2.0-rc.2"),
        (["v1.1.0-rc.2", "v1.1.0"], "patch", "1.1.1-rc.1"),
        # 대기 rc 는 최고 base 하나 — 위로 새 시리즈를 연 뒤의 patch 는 그 새 base 에서 오름.
        (_PENDING + ["v1.1.1-rc.1"], "patch", "1.1.2-rc.1"),
        (_PENDING, "auto", "auto"),
    ],
)
def test_next_version(tags, level, expected):
    assert next_version(_msg(level), tags) == expected


@pytest.mark.parametrize(
    ("tags", "message", "expected"),
    [
        (_PENDING, "Merge dev: x\n", "1.1.0-rc.3"),
        (_PENDING, _msg("auto"), "1.1.0-rc.3"),
        (["v1.0.4"], "Merge dev: x\n", "1.0.5-rc.1"),
        # 트레일러가 있으면 그것이 이김 — 대체 레벨은 트레일러가 없을 때만.
        (_PENDING, _msg("minor"), "1.2.0-rc.1"),
    ],
)
def test_auto_level_cuts_an_rc_without_a_trailer(tags, message, expected):
    """커밋 타입으로 레벨을 못 정하는 도구 — 트레일러 없는 staging push 도 rc 를 냄."""
    assert next_version(message, tags, auto_level="patch") == expected


def test_next_refuses_a_tag_that_already_exists(monkeypatch):
    """대기 rc 정의상 닿지 않는 경우지만, 정의가 바뀌면 같은 태그를 두 번 push 하는 대신 실패함."""
    import scripts.release_version as rv

    monkeypatch.setattr(rv, "pending_rc", lambda tags, token="rc": ((1, 1, 0), 1))
    with pytest.raises(ValueError, match="이미 있음"):
        rv.next_version(_msg("continue"), ["v1.0.4", "v1.1.0-rc.1", "v1.1.0-rc.2"])


def test_no_trailer_leaves_the_rc_to_the_tool():
    assert next_version("Merge dev: x\n\nplain body\n", _PENDING) == "auto"


def test_a_shipped_rc_is_not_pending():
    """정식 태그가 난 rc 는 이어 갈 시리즈가 아님 — 도달 가능성이 아니라 태그 목록으로 봄."""
    assert pending_rc(["v1.1.0-rc.2", "v1.1.0"]) is None


def test_an_rc_below_the_last_stable_is_abandoned():
    """`1.1.0` 이 나간 뒤 남은 `1.0.5-rc.1` 은 버려진 시리즈 — continue 가 그것을 되살리면 정식보다
    낮은 rc 가 나옴."""
    assert pending_rc(["v1.0.5-rc.1", "v1.1.0"]) is None


def test_foreign_tags_are_ignored():
    assert pending_rc(["v1.0.0", "v1.0.1-rc.1-x", "v1.0.1-beta.1", "release-2"]) is None


@pytest.mark.parametrize(
    ("tags", "message"),
    [
        ([], _msg("continue")),
        (["v1.1.0-rc.2", "v1.1.0"], _msg("continue")),
        (_PENDING, _msg("pach")),
        (_PENDING, _msg("")),
        (_PENDING, "x\n\nRelease-Level: patch\nRelease-Level: minor\n"),
    ],
)
def test_unusable_level_raises(tags, message):
    with pytest.raises(ValueError):
        next_version(message, tags)


@pytest.mark.parametrize("key", ["release-level", "RELEASE-LEVEL"])
def test_a_trailer_key_reads_in_any_case(key):
    """git 처럼 키를 대소문자 구분 없이 읽음 — 소문자 키를 놓치면 강제 레벨이 auto 로 떨어짐."""
    assert parse_level(f"chore: promote\n\n{key}: minor\n") == "minor"


def test_the_same_level_twice_is_one_level():
    assert parse_level("x\n\nRelease-Level: minor\nRelease-Level:  minor \n") == "minor"


@pytest.mark.parametrize(
    ("message", "default", "expected"),
    [
        ("fix: hotfix\n", "patch", "1.0.5"),
        ("fix: hotfix\n", None, "auto"),
        ("fix: hotfix\n\nRelease-Level: minor\n", "patch", "1.1.0"),
        ("fix: hotfix\n\nRelease-Level: major\n", None, "2.0.0"),
    ],
)
def test_stable_version(message, default, expected):
    assert stable_version(message, ["v1.0.4", "v1.1.0-rc.1"], default) == expected


def test_stable_rejects_continue():
    with pytest.raises(ValueError):
        stable_version(_msg("continue"), ["v1.0.4"], "patch")


def test_cli_exit_codes(capsys):
    tags = "\n".join(_PENDING)
    assert main(["next", "--message", _msg("continue"), "--tags", tags]) == 0
    assert capsys.readouterr().out.strip() == "1.1.0-rc.3"
    assert main(["next", "--message", _msg("pach"), "--tags", tags]) == 2
    assert "release_version:" in capsys.readouterr().err
    assert main(["next", "--message", "x\n", "--tags", tags, "--auto-level", "patch"]) == 0
    assert capsys.readouterr().out.strip() == "1.1.0-rc.3"
    assert main(["stable", "--message", "fix: x\n", "--tags", tags, "--default", "patch"]) == 0
    assert capsys.readouterr().out.strip() == "1.0.5"
    assert main(["finalize", "--rc", "v1.1.0-rc.2", "--tags", tags]) == 0
    assert capsys.readouterr().out.strip() == "1.1.0"
    assert main(["finalize", "--rc", "v1.1.0-rc.2", "--tags", tags + "\nv1.1.0"]) == 2
    assert "release_version:" in capsys.readouterr().err
    assert main(["state", "--tags", tags]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "pending: v1.1.0-rc.2"


@pytest.mark.parametrize(
    ("tags", "reason"),
    [
        # 대기 rc 1.0.5-rc.1 이 있는데 hotfix 가 1.0.4 → 1.0.5 를 먼저 냄.
        (["v1.0.4", "v1.0.5-rc.1", "v1.0.5"], "이미 있음"),
        # hotfix 가 minor 로 1.1.0 을 냄 — 1.0.5 로 정식화하면 하향.
        (["v1.0.4", "v1.0.5-rc.1", "v1.1.0"], "보다 낮음"),
    ],
)
def test_finalize_refuses_what_a_hotfix_already_shipped(tags, reason):
    """hotfix 는 staging 을 거치지 않으므로 그사이 staging 의 rc 가 이미 난 버전이나 그 아래가 될 수
    있음 — 그대로 정식화하면 중복 태그나 하향 릴리스."""
    with pytest.raises(ValueError, match=reason):
        finalize_version("v1.0.5-rc.1", tags)


def test_finalize_takes_only_an_rc_tag():
    with pytest.raises(ValueError):
        finalize_version("v1.0.5", ["v1.0.4"])


def test_state_labels_every_level():
    assert state(_PENDING) == [
        "pending: v1.1.0-rc.2",
        "continue: v1.1.0-rc.3",
        "patch: v1.1.1-rc.1",
        "minor: v1.2.0-rc.1",
        "major: v2.0.0-rc.1",
    ]
    lines = state(["v1.0.4"])
    assert lines[0] == "pending: none"
    assert lines[1].startswith("continue: 불가")
    assert lines[2] == "patch: v1.0.5-rc.1"


def test_state_reads_git_itself(tmp_path, monkeypatch, capsys):
    """인자 없는 형태 — `allowed-tools` 가 사전승인하는 것은 이것뿐."""
    from tests._proc import run_bounded

    run_bounded(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    run_bounded(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty"]
        + ["-m", "x"],
        cwd=str(tmp_path),
        check=True,
    )
    for tag in _PENDING:
        run_bounded(["git", "tag", tag], cwd=str(tmp_path), check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["state"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "pending: v1.1.0-rc.2"


def test_the_script_is_copied_to_the_host():
    """렌더된 release.yml 이 호스트 사본을 부름 — 복사 목록에서 빠지면 모든 릴리스가 `::error::`
    로 멈춤."""
    from scripts.vdev_init_setup import COPY_FILES

    assert "scripts/release_version.py" in COPY_FILES
