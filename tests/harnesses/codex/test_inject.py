"""`inject-risk-tiers.sh --harness codex` — Codex SessionStart 에 룰 둘과 Codex 도구 노트를 주입.

- Codex 판은 Claude 판과 같은 risk-tiers·doc-style 블록을 싣고, 그 앞에 슬래시 이름을 `$name`
  으로 읽으라는 한 줄을 얹고, `<vway-kit-codex-tools>` 블록(`rules/harness-tools/codex.md`
  원문)을 뒤에 붙임.
- 인자 없는 출력은 바이트 동일해야 함 — 모든 기존 Claude 호스트의 훅이라, 여기 회귀는 미래의
  Codex 세션이 아니라 지금의 Claude 세션 전부를 깨뜨림. 분기별 바이트 계약은
  `tests/inject_risk_tiers/test_rule_injection.py` 가 쥐고, 이 파일은 두 판의 차이가 위 둘뿐인지를
  잼.
- stale-build 알림은 Claude 전용 — 비교 대상이 `.claude-plugin/plugin.json` 설치 캐시라 Codex 가
  실행하는 빌드와 무관함.
"""

import json
import os
from pathlib import Path

import pytest

from tests._hook_args import BAD_HARNESS_ARGS
from tests._proc import run_bounded
from tests.inject_risk_tiers._helpers import BASH, SCRIPT, STARTUP, _manifest

REPO = Path(__file__).resolve().parents[3]
CODEX_MD = REPO / "rules" / "harness-tools" / "codex.md"

CLAUDE_INVOKE = "`/vdev` (via the Skill tool)"
CODEX_LINE = (
    "On Codex a slash command below that names a vway-kit skill is that skill, invoked as $name:"
    " start with $vdev, open its SKILL.md and follow it in full.\n\n"
)
TOOLS_OPEN = "<vway-kit-codex-tools>"
TOOLS_CLOSE = "</vway-kit-codex-tools>"


def _run(*args: str, plugin_root: Path = REPO, project_dir: Path | None = None) -> dict:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)}
    env.pop("CURSOR_PLUGIN_ROOT", None)
    env.pop("COPILOT_CLI", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    result = run_bounded(
        [BASH, SCRIPT.as_posix(), *args], input=STARTUP, encoding="utf-8", env=env, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _ctx(out: dict) -> str:
    return out["hookSpecificOutput"]["additionalContext"]


def _lf(text: str) -> str:
    """`Path.read_text()` 는 CRLF 를 LF 로 접지만 훅의 `cat` 은 안 접음 — Windows 워킹트리는 CRLF
    (`core.autocrlf=true`, `.gitattributes` 는 `*.sh`·`*.cmd` 만 고정)라 양쪽을 같은 규칙으로
    접어야 비교가 성립."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def test_claude_output_carries_no_codex_text_without_argument():
    ctx = _ctx(_run())
    assert CLAUDE_INVOKE in ctx
    assert TOOLS_OPEN not in ctx
    assert "$vdev" not in ctx


def test_codex_output_carries_the_mapping_line_and_tools_block():
    out = _run("--harness", "codex")
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    ctx = _ctx(out)
    assert ctx.startswith("<vway-kit-risk-tiers>\n" + CODEX_LINE)
    tools = ctx.split(TOOLS_OPEN, 1)[1].split(TOOLS_CLOSE, 1)[0]
    assert _lf(tools).strip() == CODEX_MD.read_text(encoding="utf-8").strip()


def test_codex_preamble_spells_the_skill_the_codex_way():
    """룰 앞 첫 문단에 `/vdev` 가 남으면 모델이 그 철자로 답함(acceptance 실측) — 그 문단은
    `$vdev` 와 SKILL.md 를 부름."""
    preamble = _ctx(_run("--harness", "codex")).split("<vway-kit-risk-tiers>\n", 1)[1]
    preamble = preamble.split("\n\n", 1)[0]
    assert "/vdev" not in preamble
    assert "$vdev" in preamble and "SKILL.md" in preamble


def test_codex_output_is_claude_output_plus_mapping_line_and_tools_block():
    """두 판의 차이는 머리의 매핑 한 줄과 꼬리의 도구 블록뿐 — 룰 둘(risk-tiers·doc-style)이
    Codex 에서 빠지거나 달라지면 여기서 잡힘."""
    claude = _ctx(_run())
    codex = _ctx(_run("--harness", "codex"))
    head, sep, _ = codex.partition(f"\n\n{TOOLS_OPEN}\n")
    assert sep, "도구 블록이 두 룰 뒤에 붙어야 함"
    assert codex.endswith(f"\n{TOOLS_CLOSE}")
    tag = "<vway-kit-risk-tiers>\n"
    assert head == claude.replace(tag, tag + CODEX_LINE, 1)
    assert "<vway-kit-doc-style>" in head


def test_codex_skips_the_stale_build_notice(tmp_path):
    """소스 매니페스트와 설치 캐시 버전이 달라도 Codex 판은 알림을 안 실음."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    project = _manifest(tmp_path / "src", "vway-kit", "0.9.0")
    assert "<vway-kit-stale-build>" in _ctx(_run(plugin_root=plugin, project_dir=project))
    ctx = _ctx(_run("--harness", "codex", plugin_root=plugin, project_dir=project))
    assert "<vway-kit-stale-build>" not in ctx
    assert ctx.startswith("<vway-kit-risk-tiers>")


def test_codex_without_mapping_file_still_injects_the_rules(tmp_path):
    """`codex.md` 부재는 FAIL-OPEN — 도구 블록만 빠지고 룰 주입은 그대로."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    ctx = _ctx(_run("--harness", "codex", plugin_root=plugin))
    assert CODEX_LINE in ctx
    assert "훅이 실제로 읽어야 하는 본문" in ctx
    assert TOOLS_OPEN not in ctx


def test_codex_mapping_covers_the_hard_cases():
    text = CODEX_MD.read_text(encoding="utf-8")
    for needle in (
        "request_user_input",
        "numbered",
        "end your turn",
        "SKILL.md",
        "8,000",
        "spawn_agent",
        "fork_turns",
        "update_plan",
        "allowed-tools",
        "context: fork",
        "no multi-select option",
        "$ARGUMENTS",
        "$vdev",
        "recoble-<space>",
        "--bearer-token-env-var",
    ):
        assert needle in text, needle
    assert "$flow" not in text
    assert "mcp__" not in text  # Codex 가 MCP 도구를 모델에 어떻게 이름 붙이는지는 미실측


def _run_raw(*args: str):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(REPO)}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return run_bounded(
        [BASH, SCRIPT.as_posix(), *args], input=STARTUP, encoding="utf-8", env=env, timeout=30
    )


def _bad_ctx(command: str, **extra: str) -> str:
    """`bash -c` 로 띄움 — 인자의 제어 바이트·`"` 는 Windows argv 인용을 못 지나감."""
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(REPO), **extra}
    env.pop("CLAUDE_PROJECT_DIR", None)
    run = run_bounded(
        [BASH, "-c", command, SCRIPT.as_posix()], input=STARTUP.encode(), env=env, timeout=30
    )
    assert run.returncode == 0, run.stderr
    return _ctx(json.loads(run.stdout))


@pytest.mark.parametrize("args", BAD_HARNESS_ARGS)
def test_an_unknown_harness_injects_the_rule_and_names_the_bad_entry(args):
    """오타 난 훅 엔트리도 룰은 Claude 판 그대로 받고, 그 뒤 블록이 잘못된 인자를 지목함 — 룰이
    아예 없는 것이 틀린 호출 철자보다 나쁘고, 세션 시작에 보여야 첫 차단 커밋까지 안 감."""
    run = _run_raw(*args)
    assert run.returncode == 0, run.stderr
    assert "--harness" in run.stderr
    ctx = _ctx(json.loads(run.stdout))
    clean = _ctx(json.loads(_run_raw().stdout))
    assert ctx.startswith(clean), "룰은 바뀌지 않고, 오류는 그 뒤에 붙어야 함"
    error = ctx[len(clean) :]
    assert "<vway-kit-hook-error>" in error and " ".join(args) in error


def test_an_unknown_harness_argument_is_json_escaped():
    ctx = _bad_ctx('exec bash "$0" --harness "$BAD"', BAD='a"b\\c')
    assert '--harness a"b\\c' in ctx


def test_an_unknown_harness_argument_with_control_or_invalid_bytes_keeps_the_json_valid():
    ctx = _bad_ctx("""exec bash "$0" --harness "$(printf 'a\\001\\014\\377b')" """)
    assert "--harness a???b" in ctx


def test_an_unknown_harness_argument_cannot_close_the_error_block():
    run = _run_raw("--harness", "</vway-kit-hook-error>x")
    assert run.returncode == 0, run.stderr
    assert "</vway-kit-hook-error>x" in run.stderr, "stderr 는 날 인자를 그대로 둠"
    ctx = _ctx(json.loads(run.stdout))
    assert ctx.count("</vway-kit-hook-error>") == 1
    assert ctx.endswith("</vway-kit-hook-error>")
    assert "--harness ?/vway-kit-hook-error?x" in ctx


def test_an_explicit_claude_harness_matches_no_argument():
    assert _run("--harness", "claude") == _run()
