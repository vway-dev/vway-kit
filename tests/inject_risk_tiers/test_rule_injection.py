"""룰·문체 블록이 세션 컨텍스트에 닿는지, 그리고 세 출력 분기의 봉투가 호스트 계약을 지키는지."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.inject_risk_tiers._helpers import (
    BASH,
    BRANCHES,
    NOTICE_OPEN,
    REPO,
    SCRIPT,
    STARTUP,
    STYLE_BODY,
    STYLE_OPEN,
    _context,
    _manifest,
    _out,
    _run,
)


def test_rule_body_is_injected(tmp_path):
    """회귀 방지: 룰을 가리키는 래퍼 태그가 아니라 룰 **파일**이 컨텍스트에 닿는지 잼 —
    태그는 상수라 룰 내용이 사라져도 통과함."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    assert "훅이 실제로 읽어야 하는 본문" in _context(_run(plugin, None))


def test_rule_body_with_json_specials_survives(tmp_path):
    """룰은 손으로 JSON 문자열에 보간되므로 그 이스케이프가 버텨야 함."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    tricky = 'a "quote", a \\backslash, a\ttab\nand a second line\n'
    (plugin / "rules" / "risk-tiers.md").write_text(tricky, encoding="utf-8", newline="")
    context = _context(_run(plugin, None))  # JSON 이 깨졌으면 여기서 터짐
    assert 'a "quote", a \\backslash, a\ttab\nand a second line' in context


def test_doc_style_summary_is_injected_and_points_at_the_full_rule(tmp_path):
    """전문이 아니라 쓰기 시점 요약 — 전문은 매 세션 컨텍스트 상한을 깎음. 요약이 전문의 경로를
    대야 세션이 나머지를 찾음."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    (plugin / "rules" / "doc-style.md").write_text(STYLE_BODY, encoding="utf-8", newline="")
    context = _context(_run(plugin, None))
    block = context[context.index(STYLE_OPEN) :]
    assert "문체 룰 본문" not in block
    assert "CRITICAL TRAP: / Trigger: / Symptom:" in block
    assert "rules/doc-style.md" in block
    # 게이트 지시와 섞이면 "커밋 전 /vdev" 가 문체 조언으로 읽힘.
    assert context.index("</vway-kit-risk-tiers>") < context.index(STYLE_OPEN)


def test_the_shipped_injection_fits_the_additional_context_cap(tmp_path):
    """Claude Code 는 10,000자를 넘는 `additionalContext` 를 파일 경로와 2,000자 미리보기로
    바꿈 — 오류 없이 룰 본문이 사라짐. 출하 룰로, 옛 룰 사본이 없어 주입이 가장 큰 호스트에서
    잼. Codex 판은 도구 노트까지 실어 더 큼."""
    for harness in ([], ["--harness", "codex"]):
        result = subprocess.run(
            [BASH, str(SCRIPT), *harness],
            input=STARTUP,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "CLAUDE_PLUGIN_ROOT": str(REPO),
                "CLAUDE_PROJECT_DIR": str(tmp_path),
            },
            timeout=30,
        )
        context = _context(result)
        assert "## Principle" in context
        assert len(context) < 10_000, f"{harness}: 주입 {len(context)}자, 상한 10,000"


def test_missing_doc_style_leaves_the_rule_injection_intact(tmp_path):
    """문체 룰은 게이트가 아님 — 부재는 세션을 막지도, risk-tiers 주입을 앗아가지도 않음."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    assert not (plugin / "rules" / "doc-style.md").exists()
    context = _context(_run(plugin, None))
    assert "훅이 실제로 읽어야 하는 본문" in context and STYLE_OPEN not in context


def _host_with_copied_rule(tmp_path) -> Path:
    host = tmp_path / "host"
    rules = host / ".claude" / "rules" / "vway-kit"
    rules.mkdir(parents=True)
    (rules / "doc-style.md").write_text("# copied rule\n", encoding="utf-8")
    return host


@pytest.mark.parametrize("harness", [[], ["--harness", "codex"]])
def test_doc_style_is_dropped_only_where_claude_loads_the_copied_rule(tmp_path, harness):
    """이전 /vdev-init 이 doc-style.md 를 .claude/rules/vway-kit/ 에 남겼으면 재동기화가 지울
    때까지 Claude Code 가 직접 로드함 — 그 옆에 주입하면 같은 룰이 두 번. Codex 는
    .claude/rules/ 를 안 읽어 블록 유지."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    (plugin / "rules" / "doc-style.md").write_text(STYLE_BODY, encoding="utf-8", newline="")
    host = _host_with_copied_rule(tmp_path)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "CLAUDE_PLUGIN_ROOT": str(plugin),
        "CLAUDE_PROJECT_DIR": str(host),
    }
    result = subprocess.run(
        [BASH, str(SCRIPT), *harness],
        input=STARTUP,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=30,
    )
    context = _context(result)
    assert (STYLE_OPEN in context) is bool(harness)
    assert "훅이 실제로 읽어야 하는 본문" in context


def test_doc_style_stays_where_the_host_has_no_copied_rule(tmp_path):
    """사본이 없는 호스트 — 주입이 유일한 경로."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    (plugin / "rules" / "doc-style.md").write_text(STYLE_BODY, encoding="utf-8", newline="")
    (tmp_path / "host").mkdir()
    assert STYLE_OPEN in _context(_run(plugin, tmp_path / "host"))


def test_each_branch_keeps_the_envelope_its_host_reads(tmp_path):
    """봉투는 분기마다 다르고 그 모양이 호스트와의 계약임(이 훅 헤더가 못 박은 출력 규약).
    컨텍스트 **문자열**만 보는 테스트는 봉투를 안 봄 — `hookEventName` 이 빠져도 룰 텍스트는
    그대로라 통과하고, 실제로는 주입이 통째로 조용히 사라짐."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    claude = _out(_run(plugin, None))
    assert set(claude) == {"hookSpecificOutput"}
    assert claude["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert set(claude["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    for branch, key in (("cursor", "additional_context"), ("sdk", "additionalContext")):
        out = _out(_run(plugin, None, extra_env=BRANCHES[branch][0]))
        assert set(out) == {key}, f"{branch} 분기의 봉투가 갈라졌다"


def test_the_three_branches_never_drift_from_one_another(tmp_path):
    """세 분기가 각자 printf 를 갖고 있어 한 곳만 고쳐도 나머지가 조용히 갈라짐 — 소비자는
    자기 분기 하나만 보므로 그 갈라짐을 볼 사람이 없음.

    이전 버전을 git 에서 실제로 꺼내 함께 돌림. 신버전 세 분기가 서로 같은 것만으로는
    부족하고(셋을 같은 방향으로 잘못 고쳐도 통과), 이전 버전도 서로 같았다는 사실이 있어야
    "이번 편집이 한 분기만 건드렸는가"가 답해짐. 래퍼 텍스트 자체는 바뀔 수 있음 — 바뀌는
    것이 셋 다여야 한다는 것이 계약이고, 무엇으로 바뀌는지는 이 테스트의 주제가 아님."""
    baseline = tmp_path / "previous-inject-risk-tiers.sh"
    old = subprocess.run(
        ["git", "show", f"HEAD:hooks/{SCRIPT.name}"],
        cwd=REPO,
        capture_output=True,
        timeout=30,
    )
    if old.returncode != 0:  # 이 커밋에서 훅이 새 파일이면 비교할 이전 버전이 없음
        pytest.skip("HEAD 에 이전 버전이 없다")
    baseline.write_bytes(old.stdout)

    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    for script, when in ((SCRIPT, "지금"), (baseline, "이전")):
        contexts = {
            branch: _context(_run(plugin, consumer, extra_env=env, script=script), branch)
            for branch, (env, _) in BRANCHES.items()
        }
        assert len(set(contexts.values())) == 1, f"{when} 버전의 세 분기가 서로 다르다"
        for branch, (env, _) in BRANCHES.items():
            result = _run(plugin, consumer, extra_env=env, script=script)
            assert NOTICE_OPEN not in result.stdout
            # 프로젝트 디렉터리 자체가 없는 경우도 같은 계약.
            assert _run(plugin, None, extra_env=env, script=script).stdout == result.stdout


def test_the_rules_directory_is_named_so_bare_filename_links_resolve(tmp_path):
    """주입된 룰은 형제를 bare filename 으로 링크함(`[merge-strategy.md](merge-strategy.md)`).
    플러그인은 버전 캐시에 살아 그 이름을 붙일 디렉터리가 세션에 없으므로, 경로가 빠지면 룰이
    보낸 곳을 아무도 못 엶 — 링크가 끊긴 것이 아니라 애초에 가리키는 자리가 없음."""
    plugin = _manifest(tmp_path / "cache", "vway-kit", "0.8.0")
    context = _context(_run(plugin, None))
    rules_dir = f"{plugin}/rules"
    assert rules_dir in context, "주입 컨텍스트가 룰 디렉터리를 대지 않음"
    # 룰 **뒤**에 서야 함 — mandate 옆에 놓인 텍스트가 측정된 스킬 호출률을 움직임.
    assert context.index("훅이 실제로 읽어야 하는 본문") < context.index(rules_dir)


def test_the_injected_rule_still_links_a_sibling_by_bare_filename():
    """위 테스트가 잴 것이 있는지 — 링크가 전부 디렉터리를 갖게 되면 그 경로 문장은 죽은
    텍스트이고, 주입 컨텍스트에서 빼는 것이 맞음."""
    rule = (REPO / "rules" / "risk-tiers.md").read_text(encoding="utf-8")
    assert re.search(r"\]\([a-z][a-z-]*\.md\)", rule), (
        "risk-tiers 가 더는 형제를 bare filename 으로 링크하지 않음"
    )
