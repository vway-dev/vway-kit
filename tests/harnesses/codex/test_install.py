"""Codex 설치자 — 호스트 `.codex/hooks.json` 에 커밋 게이트를 등록·해제·검증하고, 사용자
`config.toml` 의 프로젝트 trust 를 읽기만 하는지 잼.

- 명령 문자열은 리터럴로 고정 — 바뀌면 모든 소비자가 Codex `/hooks` 에서 다시 승인해야 함.
- Codex 는 `description`·`hooks` 밖 최상위 키가 있으면 파일 전체를 안 읽음 — 그런 파일은
  손대지 않고 `[!]` 로 보고하는지, 기존 사용자 훅의 위치가 그대로인지도 잼.
"""

import json
import os
import re
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.harness.codex import install

HOOKS = Path(".codex/hooks.json")

PINNED_COMMAND = (
    'bash "$(git rev-parse --show-toplevel)/.claude/vway-kit/scripts/harness/codex/gate.sh"'  # noqa: E501
)
PINNED_WINDOWS = (
    '& "$(git rev-parse --show-toplevel)/.claude/vway-kit/scripts/harness/codex/gate.cmd"'  # noqa: E501
)


def _stored_key(host: Path) -> str:
    """The project key as Codex writes it: lowercased on Windows only, where paths ignore case."""
    key = str(host.resolve())
    return key.lower() if os.name == "nt" else key


def _read(host: Path) -> dict:
    return json.loads((host / HOOKS).read_text(encoding="utf-8"))


def test_command_strings_are_pinned():
    # Changing these makes every consumer re-approve the hook in /hooks.
    assert install.GATE_HOOK == {
        "type": "command",
        "command": PINNED_COMMAND,
        "commandWindows": PINNED_WINDOWS,
        "timeout": 600,
        "statusMessage": "vway-kit: vdev 게이트 + 테스트 검사 중…",
    }
    assert install.GATE_ENTRY == {"matcher": "Bash", "hooks": [install.GATE_HOOK]}


def test_register_creates_and_is_idempotent(tmp_path):
    assert "등록" in install.register(tmp_path)
    assert "이미" in install.register(tmp_path)
    data = _read(tmp_path)
    assert data == {"hooks": {"PreToolUse": [install.GATE_ENTRY]}}


def test_register_keeps_user_hooks_and_their_positions(tmp_path):
    (tmp_path / ".codex").mkdir()
    user = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    (tmp_path / HOOKS).write_text(
        json.dumps({"description": "d", "hooks": {"PreToolUse": [user]}}), encoding="utf-8"
    )
    install.register(tmp_path)
    data = _read(tmp_path)
    assert data["description"] == "d"
    assert data["hooks"]["PreToolUse"][0] == user
    assert data["hooks"]["PreToolUse"][1] == install.GATE_ENTRY


def test_register_keeps_other_events_untouched(tmp_path):
    (tmp_path / ".codex").mkdir()
    start_hook = {"type": "command", "command": "echo hi"}
    other = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [start_hook]}]}}
    (tmp_path / HOOKS).write_text(json.dumps(other), encoding="utf-8")
    install.register(tmp_path)
    data = _read(tmp_path)
    assert data["hooks"]["SessionStart"] == other["hooks"]["SessionStart"]
    assert data["hooks"]["PreToolUse"] == [install.GATE_ENTRY]


def test_register_repairs_a_stale_gate_hook_in_place(tmp_path):
    (tmp_path / ".codex").mkdir()
    stale_command = 'bash "old/vway-kit/scripts/harness/codex/gate.sh"'
    stale = {"matcher": "Bash", "hooks": [{"type": "command", "command": stale_command}]}
    (tmp_path / HOOKS).write_text(json.dumps({"hooks": {"PreToolUse": [stale]}}), encoding="utf-8")
    assert "보정" in install.register(tmp_path)
    assert _read(tmp_path)["hooks"]["PreToolUse"] == [install.GATE_ENTRY]


@pytest.mark.parametrize("bad", ['{"hooks": {}, "extra": 1}', "[]", "{not json"])
def test_register_refuses_files_codex_would_not_load(tmp_path, bad):
    (tmp_path / ".codex").mkdir()
    (tmp_path / HOOKS).write_text(bad, encoding="utf-8")
    assert "[!]" in install.register(tmp_path)
    assert (tmp_path / HOOKS).read_text(encoding="utf-8") == bad


def test_unregister_removes_only_the_gate_and_empty_file(tmp_path):
    install.register(tmp_path)
    assert "해제" in install.unregister(tmp_path)
    assert not (tmp_path / HOOKS).exists()
    assert "없음" in install.unregister(tmp_path)


def test_unregister_keeps_a_file_with_user_hooks(tmp_path):
    (tmp_path / ".codex").mkdir()
    user = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    (tmp_path / HOOKS).write_text(json.dumps({"hooks": {"PreToolUse": [user]}}), encoding="utf-8")
    install.register(tmp_path)
    install.unregister(tmp_path)
    assert _read(tmp_path) == {"hooks": {"PreToolUse": [user]}}


def test_problems_names_a_missing_registration(tmp_path):
    assert any(".codex/hooks.json" in p for p in install.problems(tmp_path))
    install.register(tmp_path)
    assert not [p for p in install.problems(tmp_path) if "커밋 게이트" in p]


def test_problems_treats_a_non_firing_matcher_as_not_registered(tmp_path):
    (tmp_path / ".codex").mkdir()
    entry = {"matcher": "Read", "hooks": [install.GATE_HOOK]}
    (tmp_path / HOOKS).write_text(json.dumps({"hooks": {"PreToolUse": [entry]}}), encoding="utf-8")
    assert any(".codex/hooks.json" in p for p in install.problems(tmp_path))


def test_problems_treats_an_exact_name_list_naming_bash_as_registered(tmp_path):
    (tmp_path / ".codex").mkdir()
    entry = {"matcher": "Read|Bash", "hooks": [install.GATE_HOOK]}
    (tmp_path / HOOKS).write_text(json.dumps({"hooks": {"PreToolUse": [entry]}}), encoding="utf-8")
    assert not [p for p in install.problems(tmp_path) if "커밋 게이트" in p]


@pytest.mark.parametrize(
    "matcher,want",
    [
        ("Bash,Read", None),  # comma is outside Codex's exact-list alphabet -> a regex, undecided
        ("Bash|Read", True),  # `|` is Codex's own list separator -> exact match
        ("^Bash$", None),  # outside the alphabet -> a regex this does not evaluate
    ],
)
def test_fires_on_bash_uses_codexs_own_exact_list_alphabet(matcher, want):
    assert install._fires_on_bash(matcher) is want


def test_register_moves_a_gate_hook_out_of_a_non_firing_matcher(tmp_path):
    (tmp_path / ".codex").mkdir()
    entry = {"matcher": "Read", "hooks": [install.GATE_HOOK]}
    (tmp_path / HOOKS).write_text(json.dumps({"hooks": {"PreToolUse": [entry]}}), encoding="utf-8")
    report = install.register(tmp_path)
    assert "이동" in report
    data = _read(tmp_path)
    entries = data["hooks"]["PreToolUse"]
    assert {"matcher": "Read", "hooks": []} in entries
    assert install.GATE_ENTRY in entries
    assert not [p for p in install.problems(tmp_path) if "커밋 게이트" in p]


def test_register_leaves_an_undecided_matcher_alone_and_appends_its_own(tmp_path):
    (tmp_path / ".codex").mkdir()
    undecided = {"matcher": "^Bash$", "hooks": [install.GATE_HOOK]}
    payload = json.dumps({"hooks": {"PreToolUse": [undecided]}})
    (tmp_path / HOOKS).write_text(payload, encoding="utf-8")
    install.register(tmp_path)
    data = _read(tmp_path)
    entries = data["hooks"]["PreToolUse"]
    assert undecided in entries  # the user's entry, byte-for-byte, still there
    assert install.GATE_ENTRY in entries
    assert len(entries) == 2


def test_hook_remains_true_after_register_false_after_unregister(tmp_path):
    assert install.hook_remains(tmp_path) is False
    install.register(tmp_path)
    assert install.hook_remains(tmp_path) is True
    install.unregister(tmp_path)
    assert install.hook_remains(tmp_path) is False


def test_trust_notes_read_the_user_config_without_writing(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "Host"
    host.mkdir()
    notes = install.trust_notes(host, home)
    assert any("trusted" in n for n in notes)  # not trusted yet -> says how
    key = _stored_key(host)
    config = home / "config.toml"
    config.write_text(f"[projects.'{key}']\ntrust_level = \"trusted\"\n", encoding="utf-8")
    before = config.read_bytes()
    notes = install.trust_notes(host, home)
    assert not any("trust_level" in n for n in notes)
    assert any("/hooks" in n for n in notes)  # hook approval is always a reminder
    assert (home / "config.toml").read_bytes() == before


def test_trust_notes_accepts_double_quoted_keys(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "Host2"
    host.mkdir()
    key = _stored_key(host)
    config = f'[projects."{key}"]\ntrust_level = "trusted"\n'
    # 이스케이프 없는 Windows 경로의 "\U…" 는 잘못된 이스케이프 — TOML(그래서 Codex)이 파일을
    # 거부함. 판정은 파서를 따름.
    try:
        expect_trusted = key in tomllib.loads(config)["projects"]
    except tomllib.TOMLDecodeError:
        expect_trusted = False
    (home / "config.toml").write_text(config, encoding="utf-8")
    notes = install.trust_notes(host, home)
    assert (not any("[!]" in n for n in notes)) is expect_trusted


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive path matching is nt-only")
def test_trust_notes_matches_windows_path_case_insensitively(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "MixedCaseHost"
    host.mkdir()
    key = str(host.resolve()).upper()
    (home / "config.toml").write_text(
        f"[projects.'{key}']\ntrust_level = \"trusted\"\n", encoding="utf-8"
    )
    notes = install.trust_notes(host, home)
    assert not any("trusted" in n and "[!]" in n for n in notes)


def test_trust_notes_unescapes_basic_string_keys(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "Host4"
    host.mkdir()
    escaped = _stored_key(host).replace("\\", "\\\\")
    (home / "config.toml").write_text(
        f'[projects."{escaped}"]\ntrust_level = "trusted"\n', encoding="utf-8"
    )
    notes = install.trust_notes(host, home)
    assert not any("trusted" in n and "[!]" in n for n in notes), notes


def _unicode_spelled(key: str, wide: bool) -> str:
    return "".join(f"\\U{ord(c):08X}" if wide else f"\\u{ord(c):04x}" for c in key)


@pytest.mark.parametrize("wide", [False, True])
def test_trust_notes_decodes_unicode_escaped_keys_as_toml_does(tmp_path, wide):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "Host6"
    host.mkdir()
    config = f'[projects."{_unicode_spelled(_stored_key(host), wide)}"]\ntrust_level = "trusted"\n'
    assert _stored_key(host) in tomllib.loads(config)["projects"]
    (home / "config.toml").write_text(config, encoding="utf-8")
    assert not any("[!]" in n for n in install.trust_notes(host, home))


@pytest.mark.parametrize(
    "spelled",
    [
        r"C:\\Work",
        r"a\"b",
        r"\b\t\n\f\r",
        r"\u0041\U0001F600",
        r"\u00e9\u00E9",
        r"C:\Work",
        r"\x41",
        r"\u004",
        r"\uD800",
        r"\U00110000",
        "trailing\\",
        "raw\ttab",
        "raw\x01ctl",
        "raw\x7fdel",
        "raw\x1fus",
    ],
)
def test_basic_unescape_agrees_with_tomllib(spelled):
    try:
        want = tomllib.loads(f'k = "{spelled}"')["k"]
    except tomllib.TOMLDecodeError:
        want = None
    assert install._basic_unescape(spelled) == want


def test_trust_notes_reads_an_invalid_escape_as_untrusted(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "Host7"
    host.mkdir()
    escaped = _stored_key(host).replace("\\", "\\\\")
    spelled = escaped[:-1] + "\\" + escaped[-1]  # "\7": TOML 은 거부, 느슨한 판독기는 "\" 를 버림
    (home / "config.toml").write_text(
        f'[projects."{spelled}"]\ntrust_level = "trusted"\n', encoding="utf-8"
    )
    assert any("[!]" in n for n in install.trust_notes(host, home))


def test_hook_remains_ignores_an_extra_top_level_key_without_a_gate(tmp_path):
    (tmp_path / ".codex").mkdir()
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
    payload = {"hooks": {"PreToolUse": [other]}, "x-team": 1}
    (tmp_path / HOOKS).write_text(json.dumps(payload), encoding="utf-8")
    assert install.hook_remains(tmp_path) is False
    payload["hooks"]["PreToolUse"].append(install.GATE_ENTRY)
    (tmp_path / HOOKS).write_text(json.dumps(payload), encoding="utf-8")
    assert install.hook_remains(tmp_path) is True


def test_trust_notes_never_raises_on_odd_config(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "Host3"
    host.mkdir()
    (home / "config.toml").write_bytes(b"\xff\xfe not valid utf-8 at all [[[")
    notes = install.trust_notes(host, home)
    assert any("trusted" in n for n in notes)


def _snippet_from(notes: list[str]) -> str:
    """`trust_notes` 경고문 속 `[projects.<key>]` 부분만 — 뒤따르는 ` trust_level` 앞에서 자름."""
    note = next(n for n in notes if "config.toml" in n)
    m = re.search(r"\[projects\..*?\](?= trust_level)", note)
    assert m, note
    return m.group(0)


def test_toml_project_key_round_trips_a_windows_path_with_backslashes():
    # `\U`(`...\Users\...`) 는 basic string 에서 무효 이스케이프 -> literal string 이어야 함.
    key = r"C:\Users\vway\host"
    snippet = install._toml_project_key(key)
    assert snippet == f"[projects.'{key}']"
    doc = tomllib.loads(f'{snippet}\ntrust_level = "trusted"\n')
    assert doc == {"projects": {key: {"trust_level": "trusted"}}}


def test_toml_project_key_round_trips_a_path_containing_a_single_quote():
    # 작은따옴표가 든 키는 literal string 을 못 열므로 basic string(큰따옴표) + 이스케이프.
    key = r"C:\Users\o'brien\host"
    snippet = install._toml_project_key(key)
    doc = tomllib.loads(f'{snippet}\ntrust_level = "trusted"\n')
    assert doc == {"projects": {key: {"trust_level": "trusted"}}}


def test_trust_notes_printed_snippet_is_valid_toml_for_a_windows_style_path(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "Users" / "vway" / "host"
    host.mkdir(parents=True)
    notes = install.trust_notes(host, home)
    snippet = _snippet_from(notes)
    # 메시지 속 키는 `host.resolve()` 원문(대소문자 그대로) — 매칭만 nt 에서 대소문자 무시.
    key = str(host.resolve())
    doc = tomllib.loads(f'{snippet}\ntrust_level = "trusted"\n')
    assert doc == {"projects": {key: {"trust_level": "trusted"}}}


def test_trust_notes_printed_snippet_is_valid_toml_for_a_path_with_a_quote(tmp_path):
    home = tmp_path / "codexhome"
    home.mkdir()
    host = tmp_path / "O'Brien"
    host.mkdir()
    notes = install.trust_notes(host, home)
    snippet = _snippet_from(notes)
    key = str(host.resolve())
    doc = tomllib.loads(f'{snippet}\ntrust_level = "trusted"\n')
    assert doc == {"projects": {key: {"trust_level": "trusted"}}}


def test_register_and_unregister_leave_a_file_with_an_unknown_top_level_key_untouched(tmp_path):
    (tmp_path / ".codex").mkdir()
    user = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    payload = json.dumps({"hooks": {"PreToolUse": [user, install.GATE_ENTRY]}, "x-team": 1})
    (tmp_path / HOOKS).write_text(payload, encoding="utf-8")
    assert "[!]" in install.register(tmp_path)
    assert "[!]" in install.unregister(tmp_path)
    assert (tmp_path / HOOKS).read_text(encoding="utf-8") == payload
    assert install.problems(tmp_path)  # Codex 가 안 읽는 파일의 게이트는 게이트가 아님


def test_unregister_keeps_user_hooks_beside_the_gate_in_place(tmp_path):
    (tmp_path / ".codex").mkdir()
    first = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo first"}]}
    shared = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    shared["hooks"].append(dict(install.GATE_HOOK))
    last = {"matcher": "Read", "hooks": [{"type": "command", "command": "echo last"}]}
    payload = {"description": "d", "hooks": {"PreToolUse": [first, shared, last]}}
    (tmp_path / HOOKS).write_text(json.dumps(payload), encoding="utf-8")
    assert "이미" in install.register(tmp_path)
    assert "해제" in install.unregister(tmp_path)
    entries = _read(tmp_path)["hooks"]["PreToolUse"]
    assert entries == [first, {"matcher": "Bash", "hooks": [shared["hooks"][0]]}, last]


def test_hook_remains_on_an_unreadable_file_answers_without_probing_again(tmp_path, monkeypatch):
    """못 읽은 파일은 남은 것으로 셈 — 다시 `.exists()` 로 묻지 않음. 그 물음이 PermissionError
    를 내면 `_step` 밖에서 도는 uninstall 판정까지 새어 나감(Claude 설치자와 같은 모양)."""

    class _Closed:
        def exists(self):
            raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(install, "_path", lambda _host: _Closed())
    monkeypatch.setattr(install, "load_json_object", lambda _p, _l: (None, "  [!] closed"))
    assert install.hook_remains(tmp_path) is True
