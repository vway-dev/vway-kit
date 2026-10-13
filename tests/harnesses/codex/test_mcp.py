"""Codex 의 Recoble MCP 등록 판정 — `codex mcp list --json` 을 읽기만 함(쓰기·토큰 읽기 없음).

argv[0] 은 `mcp._codex_path()`(내부적으로 `shutil.which("codex")`) 가 정함 — 실측(Windows, npm
전역 설치): 리터럴 `"codex"` 는 `codex.CMD` 를 PATHEXT 없이 못 찾아 `FileNotFoundError` 로 죽고,
`shutil.which` 가 돌려주는 절대경로는 됨. 이 파일의 테스트 대부분은 그 판정 로직(정상/미등록/
불일치)을 재는 것이라 `_codex_on_path` 로 경로 해석 자체를 "codex" literal 로 고정해 기존
`_runner` 의 `argv[:4]` 단언이 그대로 유효하게 함 — 경로 해석 자체는 아래 전용 테스트 둘이 잼.
"""

import json
import os
import subprocess
import time

import pytest

import scripts.vdev_init_setup as vis
from scripts.harness.codex import mcp

EXPECTED = {"recoble-dev3": {"type": "http", "url": "https://r.example/mcp/dev3"}}


@pytest.fixture(autouse=True)
def _codex_on_path(monkeypatch):
    monkeypatch.setattr(mcp, "_codex_path", lambda: "codex")


def _runner(payload=None, *, code=0, exc=None):
    def run(argv, **kw):
        assert argv[:4] == ["codex", "mcp", "list", "--json"]
        assert kw.get("encoding") == "utf-8" and kw.get("timeout")
        if exc is not None:
            raise exc
        out = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess(argv, code, out, "")

    return run


def _entry(**transport):
    base = {
        "type": "streamable_http",
        "url": "https://r.example/mcp/dev3",
        "bearer_token_env_var": "RECOBLE_DEV3_PAT",
    }
    base.update(transport)
    return [{"name": "recoble-dev3", "transport": base}]


def test_env_name_is_upper_snake():
    assert mcp.env_name("recoble-dev3") == "RECOBLE_DEV3_PAT"
    assert mcp.env_name("recoble-client.a") == "RECOBLE_CLIENT_A_PAT"


def test_healthy_registration_skips():
    lines = mcp.instructions(EXPECTED, runner=_runner(_entry()))
    assert any("[=] recoble-dev3" in ln for ln in lines)
    assert not any("codex mcp add" in ln for ln in lines)


def test_unregistered_emits_add_with_env_var():
    lines = mcp.instructions(EXPECTED, runner=_runner([]))
    text = "\n".join(lines)
    assert (
        "codex mcp add recoble-dev3 --url https://r.example/mcp/dev3"
        " --bearer-token-env-var RECOBLE_DEV3_PAT" in text
    )
    assert "codex mcp remove" not in text


def test_mismatches_emit_remove_first():
    for bad in ({"url": "https://other/mcp"}, {"bearer_token_env_var": None}, {"type": "stdio"}):
        text = "\n".join(mcp.instructions(EXPECTED, runner=_runner(_entry(**bad))))
        assert text.index("codex mcp remove recoble-dev3") < text.index(
            "codex mcp add recoble-dev3"
        )


def test_unjudgeable_lists_everything():
    for runner in (
        _runner(exc=FileNotFoundError()),
        _runner(exc=subprocess.TimeoutExpired("codex", 1)),
        _runner([], code=1),
        _runner("not json"),
        _runner({"not": "a list"}),
    ):
        text = "\n".join(mcp.instructions(EXPECTED, runner=runner))
        assert "확인할 수 없어" in text and "codex mcp add recoble-dev3" in text
        # 같은 이름 `codex mcp add` 는 덮어씀(exit 0, acceptance 실측) — 거절로 안내하면 틀림
        assert "이미 등록됐으면 덮어씁니다" in text and "거절" not in text


def test_report_lists_registered_recoble_only():
    payload = _entry() + [{"name": "other", "transport": {"type": "stdio"}}]
    text = "\n".join(mcp.report(runner=_runner(payload)))
    assert "codex mcp remove recoble-dev3" in text and "other" not in text


def test_report_does_not_fold_unjudgeable_into_none():
    text = "\n".join(mcp.report(runner=_runner(exc=FileNotFoundError())))
    assert "확인할 수 없음" in text


def test_never_prints_env_values(monkeypatch):
    monkeypatch.setenv("RECOBLE_DEV3_PAT", "secret-token-value")
    text = "\n".join(
        mcp.instructions(EXPECTED, runner=_runner([])) + mcp.report(runner=_runner(_entry()))
    )
    assert "secret-token-value" not in text


def test_recoble_prefix_matches_vdev_init_setups_constant():
    """`mcp.py` 는 순환 import 를 피하려고 접두 상수를 복사함 — 값이 갈리면 조용히 두 판정이
    다른 이름을 봄(예: Codex 는 `recoble-` 로 걸렀는데 setup 은 다른 접두를 기대)."""
    assert mcp.RECOBLE_PREFIX == vis.RECOBLE_SERVER_PREFIX


def test_argv0_is_the_which_resolved_path(monkeypatch):
    """실측(Windows): 리터럴 `"codex"` 는 npm 이 깐 `codex.CMD` 를 PATHEXT 없이 못 찾아
    `FileNotFoundError` 로 죽음 — argv[0] 은 `_codex_path()` 가 돌려주는 절대경로여야 함."""
    resolved = r"C:\Users\USER\AppData\Roaming\npm\codex.CMD"
    monkeypatch.setattr(mcp, "_codex_path", lambda: resolved)
    seen = []

    def run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    servers, judged = mcp.codex_servers(runner=run)
    assert judged is True and servers == {}
    assert seen == [[resolved, "mcp", "list", "--json"]]


def test_codex_not_on_path_is_unjudgeable_without_spawning(monkeypatch):
    """`_codex_path()` 가 None 이면 runner 를 아예 부르지 않음 — 실제 스폰 시도 자체가 없음."""
    monkeypatch.setattr(mcp, "_codex_path", lambda: None)

    def run(argv, **kw):
        raise AssertionError("codex 가 PATH 에 없으면 runner 를 부르면 안 됨")

    servers, judged = mcp.codex_servers(runner=run)
    assert (servers, judged) == ({}, False)


def _shadowing_host(tmp_path, monkeypatch, *, trusted=True, body=None):
    """trusted 여부를 고른 호스트 + 같은 이름을 적은 프로젝트 `.codex/config.toml`."""
    home = tmp_path / "codexhome"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    host = tmp_path / "Host"
    (host / ".codex").mkdir(parents=True)
    body = body or '[mcp_servers.recoble-dev3]\nurl = "https://other/mcp"\n'
    (host / ".codex" / "config.toml").write_text(body, encoding="utf-8")
    if trusted:
        key = str(host.resolve())
        key = key.lower() if os.name == "nt" else key
        (home / "config.toml").write_text(
            f"[projects.'{key}']\ntrust_level = \"trusted\"\n", encoding="utf-8"
        )
    return host


def test_mismatch_from_a_trusted_project_file_points_at_that_file(tmp_path, monkeypatch):
    """실측: `codex mcp remove` 는 프로젝트 항목을 못 지우고 `add` 는 global 에만 씀 — 안내대로
    해도 프로젝트 항목이 계속 가려 /vdev-init 이 같은 안내를 되풀이함."""
    host = _shadowing_host(tmp_path, monkeypatch)
    bad = _runner(_entry(url="https://other/mcp"))
    text = "\n".join(mcp.instructions(EXPECTED, runner=bad, host=host))
    assert ".codex/config.toml" in text and "[mcp_servers.recoble-dev3]" in text
    assert "codex mcp remove recoble-dev3" not in text
    assert "codex mcp add recoble-dev3" not in text


@pytest.mark.parametrize(
    "body",
    [
        '[mcp_servers]\nrecoble-dev3 = { url = "https://other/mcp" }\n',
        '[mcp_servers."recoble-dev3"]\nurl = "https://other/mcp"\n',
        'mcp_servers.recoble-dev3.url = "https://other/mcp"\n',
        '[mcp_servers] # 팀 공유\nrecoble-dev3 = { url = "https://other/mcp" }\n',
    ],
    ids=["inline-table", "quoted-header", "dotted-key", "commented-table-header"],
)
def test_project_definition_is_found_in_every_toml_spelling(tmp_path, monkeypatch, body):
    host = _shadowing_host(tmp_path, monkeypatch, body=body)
    bad = _runner(_entry(url="https://other/mcp"))
    text = "\n".join(mcp.instructions(EXPECTED, runner=bad, host=host))
    assert "codex mcp remove recoble-dev3" not in text, text


def test_blank_line_runs_stay_linear(tmp_path, monkeypatch):
    """`\\s*` 는 개행을 넘어 줄마다 뒤 빈 줄 전체를 다시 훑음 — 이 입력에 160초(실측)."""
    body = "[mcp_servers]\n" + "  \n" * 100_000 + 'recoble-dev3 = { url = "x" }\n'
    host = _shadowing_host(tmp_path, monkeypatch, body=body)
    started = time.perf_counter()
    assert mcp._project_shadows(host) == {"recoble-dev3"}
    assert time.perf_counter() - started < 2


def test_untrusted_project_file_is_ignored_by_codex_so_global_advice_stands(tmp_path, monkeypatch):
    host = _shadowing_host(tmp_path, monkeypatch, trusted=False)
    bad = _runner(_entry(url="https://other/mcp"))
    text = "\n".join(mcp.instructions(EXPECTED, runner=bad, host=host))
    assert text.index("codex mcp remove recoble-dev3") < text.index("codex mcp add recoble-dev3")


def test_a_similar_name_in_the_project_file_is_not_a_match(tmp_path, monkeypatch):
    host = _shadowing_host(tmp_path, monkeypatch, body='[mcp_servers.recoble-dev30]\nurl = "x"\n')
    bad = _runner(_entry(url="https://other/mcp"))
    text = "\n".join(mcp.instructions(EXPECTED, runner=bad, host=host))
    assert "codex mcp remove recoble-dev3" in text


def test_report_sends_trusted_project_entries_to_their_file(tmp_path, monkeypatch):
    """제거는 두 곳 다 — `remove` 는 가려진 global 항목을 지우고(없으면 exit 0 무변경, 실측)
    프로젝트 항목은 파일에서만 지워짐."""
    host = _shadowing_host(tmp_path, monkeypatch)
    lines = mcp.report(runner=_runner(_entry()), host=host)
    assert any("codex mcp remove recoble-dev3" in ln for ln in lines)
    assert any(".codex/config.toml" in ln and "[mcp_servers.recoble-dev3]" in ln for ln in lines)


def test_list_runs_in_the_host_so_codex_merges_its_project_config(tmp_path):
    """`codex mcp list` 는 cwd 의 trusted 프로젝트 설정을 합침(실측) — /vdev-init 프로세스의
    cwd 가 아니라 판정하는 호스트여야 함."""
    seen = []

    def run(argv, **kw):
        seen.append(kw.get("cwd"))
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    mcp.codex_servers(runner=run, cwd=tmp_path)
    assert seen == [tmp_path]
