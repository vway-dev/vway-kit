"""플랜 검증 — 무엇이 생성되면 안 되는가.

슬래시 커맨드 생성은 막음(하네스는 스킬로만 확장). 끊어진 링크는 플랜이 채울
파일까지 계산해 판정하고, 마커 줄이 본문에 섞이면 다음 upsert 가 깨지므로 막음.
"""

import json

import scripts.harness_scaffold as hs
from tests.harness._helpers import (
    _baseline_entry,
    _conv_entry,
    _write_component,
)


def test_validate_ok_minimal(tmp_path):
    plan = {"files": [_baseline_entry()]}
    rep = hs.validate_plan(tmp_path, plan)
    assert rep["ok"] is True and rep["issues"] == []


def test_validate_missing_rule_anchor(tmp_path):
    e = _baseline_entry()
    e["content"] = e["content"].replace("<!-- rule:reuse-first -->\n", "")
    rep = hs.validate_plan(tmp_path, {"files": [e]})
    assert rep["ok"] is False
    assert any(i["kind"] == "rule-load" and "reuse-first" in i["detail"] for i in rep["issues"])


def test_validate_flags_command_generation(tmp_path):
    plan = {
        "files": [
            _baseline_entry(),
            {"path": ".claude/commands/x.md", "action": "create", "content": "y"},
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert any(i["kind"] == "command" for i in rep["issues"]) and rep["ok"] is False


def test_validate_frontmatter_missing(tmp_path):
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: \n---\nbody",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert any(i["kind"] == "frontmatter" for i in rep["issues"])


def test_validate_dedup_collision_with_existing(tmp_path):
    _write_component(tmp_path / ".claude" / "agents" / "dup.md", "dup", "Existing")
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/new.md",
                "action": "create",
                "content": "---\nname: dup\ndescription: New\n---\nbody",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert any(i["kind"] == "dedup" for i in rep["issues"])


def test_validate_dead_link(tmp_path):
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: a\ndescription: d\n---\nsee [x](./missing.md)",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert any(i["kind"] == "dead-link" for i in rep["issues"])


def test_validate_dead_link_satisfied_by_plan(tmp_path):
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: a\ndescription: d\n---\nsee [b](./b.md)",
            },
            {
                "path": ".claude/agents/b.md",
                "action": "create",
                "content": "---\nname: b\ndescription: d\n---\nx",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "dead-link" for i in rep["issues"])


def test_validate_no_baseline_marker(tmp_path):
    rep = hs.validate_plan(tmp_path, {"files": []})
    assert any(i["kind"] == "rule-load" for i in rep["issues"])


def test_main_validate_outputs_json_exit0(tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({"files": [_baseline_entry()]}), encoding="utf-8")
    rc = hs.main(["validate", "--root", str(tmp_path), "--plan", str(plan_file)])
    assert rc == 0  # FAIL-OPEN: 진단이지 게이트 아님
    out = json.loads(capsys.readouterr().out)
    assert "ok" in out and "issues" in out


def test_validate_name_non_string_no_crash(tmp_path):
    # name 이 YAML 리스트/딕트여도 add() TypeError 로 죽지 않고 frontmatter 누락 처리(FAIL-OPEN).
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: [a, b]\ndescription: d\n---\nbody",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)  # 예외 없이 반환되어야 함
    assert any(i["kind"] == "frontmatter" for i in rep["issues"])


def test_validate_nested_component_path_checked(tmp_path):
    # 하위 디렉터리 컴포넌트도 frontmatter 검증 대상이어야 함.
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/sub/a.md",
                "action": "create",
                "content": "no frontmatter here",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert any(i["kind"] == "frontmatter" for i in rep["issues"])


def test_validate_dead_link_satisfied_by_noncanonical_plan_path(tmp_path):
    # plan path 가 비정규('./')여도 정규화 후 매칭되어 dead-link 오탐이 없어야 함.
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: a\ndescription: d\n---\nsee [b](./b.md)",
            },
            {
                "path": ".claude/agents/./b.md",
                "action": "create",
                "content": "---\nname: b\ndescription: d\n---\nx",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "dead-link" for i in rep["issues"])


def test_validate_flags_command_with_dot_prefix(tmp_path):
    # './' 접두가 붙은 커맨드 경로도 정규화 후 가드에 걸려야 함.
    plan = {
        "files": [
            _baseline_entry(),
            {"path": "./.claude/commands/x.md", "action": "create", "content": "y"},
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert any(i["kind"] == "command" for i in rep["issues"]) and rep["ok"] is False


def test_validate_flags_marker_lines_in_content(tmp_path):
    # 템플릿 BEGIN/END 를 통째로 복사한 content 는 apply 재래핑으로 중첩되므로 high.
    e = _baseline_entry()
    begin, end = hs._marker_begin("harness:baseline"), hs._marker_end("harness:baseline")
    e["content"] = begin + "\n" + e["content"] + "\n" + end
    rep = hs.validate_plan(tmp_path, {"files": [e]})
    assert any(i["kind"] == "marker" and "body" in i["detail"] for i in rep["issues"])
    assert rep["ok"] is False


def test_validate_dedup_allows_same_path_update(tmp_path):
    # 기존 컴포넌트를 같은 경로로 재emit(갱신)하는 것은 충돌이 아님.
    _write_component(tmp_path / ".claude" / "agents" / "reviewer.md", "reviewer", "Old")
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/reviewer.md",
                "action": "create",
                "content": "---\nname: reviewer\ndescription: New\n---\nbody",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "dedup" for i in rep["issues"])


def test_validate_anchor_whitespace_tolerant(tmp_path):
    # HTML 주석 공백 변형(<!--rule:x-->)도 앵커로 인정해야 함.
    e = _baseline_entry()
    e["content"] = e["content"].replace("<!-- rule:karpathy -->", "<!--rule:karpathy-->")
    rep = hs.validate_plan(tmp_path, {"files": [e]})
    assert not any(i["kind"] == "rule-load" for i in rep["issues"])


def test_validate_ops_line_limit_ok(tmp_path):
    body = (
        "<!-- ops-conventions -->\n"
        "- 에러: RFC-9457 → docs/code-style/x.md#err\n"
        "- 로깅: 레벨 → docs/code-style/x.md#log\n"
    )
    rep = hs.validate_plan(tmp_path, {"files": [_baseline_entry(), _conv_entry(body)]})
    assert not [i for i in rep["issues"] if i["kind"] == "ops-line-limit"]


def test_validate_ops_line_limit_violation(tmp_path):
    body = "<!-- ops-conventions -->\n- 에러: 1\n  2\n  3\n  4\n"
    rep = hs.validate_plan(tmp_path, {"files": [_baseline_entry(), _conv_entry(body)]})
    hits = [i for i in rep["issues"] if i["kind"] == "ops-line-limit"]
    assert len(hits) == 1 and hits[0]["severity"] == "high"
    assert not rep["ok"]


def test_ops_blocks_none_without_anchor():
    assert hs._ops_directive_blocks("- a\n- b\n") == []


def test_ops_blocks_splits_top_level_items():
    body = "<!-- ops-conventions -->\n- 에러: RFC-9457 → docs#err\n- 로깅: 레벨 규칙 → docs#log\n"
    blocks = hs._ops_directive_blocks(body)
    assert len(blocks) == 2
    assert blocks[0][0].startswith("- 에러")


def test_ops_blocks_collects_wrapped_continuation():
    body = "<!-- ops-conventions -->\n- 에러: 1\n  cont2\n  cont3\n  cont4\n\n- 로깅: ok\n"
    blocks = hs._ops_directive_blocks(body)
    assert len(blocks[0]) == 4  # `- 에러` + 3 continuation
    assert len(blocks[1]) == 1


def test_validate_dead_link_ignores_image(tmp_path):
    # 이미지 임베드 ![..](..) 는 dead-link 검사 대상이 아님.
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: a\ndescription: d\n---\n![diagram](./pic.md)",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "dead-link" for i in rep["issues"])


def test_validate_dead_link_ignores_frontmatter(tmp_path):
    # frontmatter(description) 안의 링크는 본문 스캔 대상이 아님.
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: a\ndescription: see [x](./missing.md)\n---\nbody",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "dead-link" for i in rep["issues"])


def test_validate_corrupt_marker_detected_despite_bad_encoding(tmp_path):
    # cp949 호스트의 기존 파일이 utf-8 디코드 불가여도 마커(ASCII) corrupt 는 검출해야 함.
    cm = tmp_path / "CLAUDE.md"
    begin = hs._marker_begin("harness:baseline").encode("utf-8")
    bad = "필수 룰\n".encode("cp949")  # utf-8 로는 디코드 불가한 바이트
    cm.write_bytes(begin + b"\n" + bad)  # BEGIN 만 있고 END 없음 → corrupt
    rep = hs.validate_plan(tmp_path, {"files": [_baseline_entry()]})
    assert any(i["kind"] == "marker" and "corrupt" in i["detail"] for i in rep["issues"])


def test_validate_dead_link_ignores_inline_code(tmp_path):
    # 인라인 코드 안의 링크 예시는 dead-link 가 아님.
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: a\ndescription: d\n---\n쓰지 말 것: `[x](./gone.md)`",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "dead-link" for i in rep["issues"])


def test_validate_dead_link_ignores_code_fence(tmp_path):
    # 코드 펜스 블록 안의 링크는 dead-link 가 아님.
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": ".claude/agents/a.md",
                "action": "create",
                "content": "---\nname: a\ndescription: d\n---\n```\n[x](./gone.md)\n```",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "dead-link" for i in rep["issues"])


def test_parse_frontmatter_block_scalar_fallback(monkeypatch):
    # yaml 부재 폴백에서도 블록 스칼라(>) 멀티라인 description 을 보존함.
    monkeypatch.setattr(hs, "yaml", None)
    text = "---\nname: a\ndescription: >\n  line one\n  line two\n---\nbody"
    fm = hs._parse_frontmatter(text)
    assert fm["name"] == "a"
    assert fm["description"] == "line one line two"


# ------------------------------------------------- 경로 모양·하네스 참조(apply 전 진단)


def _entry(path, content="x"):
    return {"path": path, "action": "create", "content": content}


def test_validate_flags_absolute_path(tmp_path):
    rep = hs.validate_plan(tmp_path, {"files": [_baseline_entry(), _entry("C:/evil.md")]})
    assert rep["ok"] is False
    assert any(i["kind"] == "path" for i in rep["issues"])


def test_validate_flags_parent_traversal(tmp_path):
    rep = hs.validate_plan(tmp_path, {"files": [_baseline_entry(), _entry("../evil.md")]})
    assert any(i["kind"] == "path" and i["severity"] == "high" for i in rep["issues"])


def test_validate_flags_output_into_harness_evidence_dir(tmp_path):
    rel = ".claude/vway-kit/.harness/research/leaked.md"
    rep = hs.validate_plan(tmp_path, {"files": [_baseline_entry(), _entry(rel)]})
    assert any(i["kind"] == "path" and rel in i["path"] for i in rep["issues"])


def test_validate_flags_nested_harness_tree_under_docs(tmp_path):
    rel = "docs/requirements/.claude/vway-kit/.harness/research/x.md"
    rep = hs.validate_plan(tmp_path, {"files": [_baseline_entry(), _entry(rel)]})
    assert any(i["kind"] == "path" for i in rep["issues"])


def test_validate_accepts_normal_doc_paths(tmp_path):
    plan = {"files": [_baseline_entry(), _entry("docs/research/README.md", "본문")]}
    rep = hs.validate_plan(tmp_path, plan)
    assert not any(i["kind"] == "path" for i in rep["issues"])


def test_validate_flags_link_into_harness(tmp_path):
    # harness-rules 4-1: 산출물은 편입 위치 docs/research/ 를 가리킴. .harness/ 참조 금지.
    body = "출처: [조사](../../.claude/vway-kit/.harness/research/researcher_x.md)"
    rep = hs.validate_plan(
        tmp_path, {"files": [_baseline_entry(), _entry("docs/sds/README.md", body)]}
    )
    assert rep["ok"] is False
    assert any(i["kind"] == "harness-ref" for i in rep["issues"])


def test_harness_ref_not_double_reported_as_dead_link(tmp_path):
    body = "출처: [조사](.claude/vway-kit/.harness/research/researcher_x.md)"
    rep = hs.validate_plan(
        tmp_path, {"files": [_baseline_entry(), _entry("docs/sds/README.md", body)]}
    )
    kinds = [i["kind"] for i in rep["issues"]]
    assert "harness-ref" in kinds and "dead-link" not in kinds


def test_dead_link_detail_never_leaks_resolved_path(tmp_path):
    # 리포트가 유령 경로를 보여주면 모델이 그 자리에 파일을 만듦 — raw 링크만 실음.
    plan = {"files": [_baseline_entry(), _entry("docs/requirements/x.md", "[q](./missing.md)")]}
    rep = hs.validate_plan(tmp_path, plan)
    dead = [i for i in rep["issues"] if i["kind"] == "dead-link"]
    assert dead and all("docs/requirements/missing.md" not in i["detail"] for i in dead)
    assert all("./missing.md" in i["detail"] for i in dead)
