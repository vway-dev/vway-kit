"""구조 검증 — 무엇이 커밋을 막고 무엇이 경고에 그치는가.

막는 것: id 형식·중복, `title` 누락, 매달린 참조, 순환, 손으로 쓴 역방향 필드,
defect 필드 오용. 경고: 고아 노드, 파일 크기, 규칙 승격 임계. 경고는 상한을 둠 —
쏟아지면 아무도 안 읽음.
"""

from pathlib import Path

from scripts.wiki_graph import (
    _safe_int,
    build_graph,
    collect_nodes,
    collect_warnings,
    load_wiki_config,
    undirected_adjacency,
    validate_defects,
)
from tests.wiki._helpers import (
    _check,
    _mk,
    _node,
    _wiki,
    _write_config,
)


def test_duplicate_id_blocks(tmp_path: Path):
    # The field an author would grep for is `wiki_id` (Task 1); the message must name that
    # field, not the internal `id` key, or the grep for the fault comes up empty.
    problems = _check(tmp_path, [_mk("a.x", path="docs/a.md"), _mk("a.x", path="docs/b.md")])
    assert any("wiki_id" in p and "중복" in p and "a.x" in p for p in problems)


def test_bad_wiki_id_format_blocks(tmp_path: Path):
    # 전용 키를 썼다는 건 노드로 의도했다는 뜻이므로 더 이상 모호하지 않음 — 차단이 옳음.
    assert any("형식" in p and "wiki_id" in p for p in _check(tmp_path, [_mk("Auth.JWT")]))


def test_foreign_id_front_matter_is_not_a_node_and_never_blocks(tmp_path: Path):
    # Docusaurus 의 `id:` 는 문서화된 1급 front matter 필드이고, wiki.root 기본값과
    # Docusaurus 기본 문서 경로는 둘 다 docs/ 임. 이것을 노드로 보면 형식 위반으로 판정되어
    # 저장소의 모든 커밋이 영구히 막힘 — wiki 게이트는 docs 티어에도 걸려 있음.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/getting-started.md", "id: Getting_Started\nsidebar_position: 1\n")
    nodes = collect_nodes(tmp_path, load_wiki_config(tmp_path))
    assert [n["id"] for n in nodes] == [None]
    assert _check(tmp_path, nodes) == []


def test_non_string_wiki_id_blocks(tmp_path: Path):
    # YAML 1.1 은 전용 키라도 묾: `wiki_id: 0123456` 은 octal 이라 정수 42798 이 되고,
    # 그 문자열화 "42798" 은 WIKI_ID_RE 를 통과해 아무도 쓰지 않은 유효해 보이는 id 가 됨.
    node = {
        "id": "42798",
        "path": "docs/a.md",
        "line_count": 3,
        "front": {"wiki_id": 42798, "title": "T"},
    }
    assert any("wiki_id" in p and "문자열" in p for p in _check(tmp_path, [node]))


def test_front_matter_without_id_warns_capped(tmp_path: Path):
    # "related" 는 WIKI_ONLY_FIELDS 라 노드로 의도했다는 신호가 있음 — 그래야 경고가 뜸.
    nodes = [
        {"id": None, "path": f"docs/f{i}.md", "line_count": 3, "front": {"related": ["x"]}}
        for i in range(5)
    ]
    warns = collect_warnings({"index": "docs/index.md"}, nodes, build_graph(nodes))
    assert sum(1 for w in warns if "wiki_id 가 없어" in w) == 3  # 3건만 나열
    assert any("외 2건" in w for w in warns)  # 나머지는 건수로


def test_missing_marker_warns_only_when_wiki_fields_are_present(tmp_path: Path):
    # 전용 키로 바꾸면 "front matter 는 있는데 노드가 아니다" 가 정상 상태. Docusaurus
    # 저장소에서 전수 경고는 매 커밋 영구 노이즈가 됨. related 를 손으로 썼다는 것만이
    # 노드로 쓰려던 의도의 증거.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/theirs.md", "id: Getting_Started\nsidebar_position: 1\ntags: [x]\n")
    _node(tmp_path, "docs/meant-it.md", "title: Auth\nrelated: [index]\n")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    warns = collect_warnings(wiki, nodes, build_graph(nodes), tmp_path)
    assert any("docs/meant-it.md" in w and "wiki_id" in w for w in warns)
    assert not any("docs/theirs.md" in w for w in warns)


def test_size_warning_skips_files_that_are_not_nodes(tmp_path: Path):
    nodes = [{"id": None, "path": "docs/big.md", "line_count": 999, "front": {"slug": "/x"}}]
    warns = collect_warnings({"index": "docs/index.md", "max_lines": 10}, nodes, build_graph(nodes))
    assert not any("max_lines" in w for w in warns)


def test_missing_title_blocks(tmp_path: Path):
    node = {"id": "a.x", "path": "docs/a.md", "line_count": 3, "front": {"wiki_id": "a.x"}}
    assert any("title" in p for p in _check(tmp_path, [node]))


def test_dangling_reference_blocks(tmp_path: Path):
    problems = _check(tmp_path, [_mk("a.x", {"depends_on": ["nope.x"]})])
    assert any("nope.x" in p for p in problems)


def test_depends_on_cycle_blocks(tmp_path: Path):
    nodes = [
        _mk("a.x", {"depends_on": ["b.x"]}, "docs/a.md"),
        _mk("b.x", {"depends_on": ["c.x"]}, "docs/b.md"),
        _mk("c.x", {"depends_on": ["a.x"]}, "docs/c.md"),
    ]
    assert any("순환" in p for p in _check(tmp_path, nodes))


def test_related_cycle_is_fine(tmp_path: Path):
    # related 는 양방향 수동이므로 서로 가리키는 것이 정상. 순환 검사 대상이 아님.
    nodes = [
        _mk("a.x", {"related": ["b.x"]}, "docs/a.md"),
        _mk("b.x", {"related": ["a.x"]}, "docs/b.md"),
    ]
    assert _check(tmp_path, nodes) == []


def test_manual_used_by_blocks(tmp_path: Path):
    assert any("used_by" in p for p in _check(tmp_path, [_mk("a.x", {"used_by": ["b.x"]})]))


def test_manual_defects_blocks(tmp_path: Path):
    assert any("defects" in p for p in _check(tmp_path, [_mk("a.x", {"defects": ["d.x"]})]))


def test_missing_source_path_warns_but_does_not_block(tmp_path: Path):
    # A doc legitimately documents a generated or gitignored file (a built API client), or one
    # that exists only on another branch. Blocking froze every commit — including code-only
    # ones — with nothing --build could do about it. --stale carries the same fact to doc-sync.

    (tmp_path / "docs").mkdir()
    nodes = [_mk("a.x", {"sources": {"src/gone.py": "abc1234"}})]
    assert _check(tmp_path, nodes) == []
    warns = collect_warnings(
        {"root": "docs", "index": "docs/index.md"}, nodes, build_graph(nodes), tmp_path
    )
    assert any("src/gone.py" in w for w in warns)


def test_missing_source_path_warning_is_capped(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    nodes = [_mk("a.x", {"sources": {f"src/gone{i}.py": None for i in range(6)}})]
    warns = collect_warnings(
        {"root": "docs", "index": "docs/index.md"}, nodes, build_graph(nodes), tmp_path
    )
    assert sum(1 for w in warns if "가 없습니다" in w and "src/gone" in w) == 3
    assert any("외 3건" in w for w in warns)


def test_existing_source_path_passes(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "here.py").write_text("x = 1\n", encoding="utf-8")
    assert _check(tmp_path, [_mk("a.x", {"sources": {"src/here.py": "abc1234"}})]) == []


def test_source_list_form_blocks(tmp_path: Path):
    # 설계가 명시적으로 거부한 모양 — sources 는 map 이어야 함. 리스트로 손으로 쓰는
    # 것이 가장 그럴듯한 실수이므로, 없는 경로 검사와 별개로 형태 자체를 block 해야 함.
    problems = _check(tmp_path, [_mk("a.x", {"sources": ["src/nope.py"]})])
    assert any("map" in p for p in problems)


def test_source_scalar_form_blocks(tmp_path: Path):
    problems = _check(tmp_path, [_mk("a.x", {"sources": "src/nope.py"})])
    assert any("map" in p for p in problems)


def test_non_string_source_key_does_not_raise(tmp_path: Path):
    # YAML with a numeric key like `sources: { 42: abc1234 }` parses to `{42: 'abc1234'}`.
    # Must not raise TypeError anywhere it is consumed.

    (tmp_path / "docs").mkdir()
    node = {
        "id": "a.x",
        "path": "docs/a.md",
        "line_count": 3,
        "front": {"wiki_id": "a.x", "title": "T", "sources": {42: "abc1234"}},
    }
    assert _check(tmp_path, [node]) == []
    warns = collect_warnings(
        {"root": "docs", "index": "docs/index.md"}, [node], build_graph([node]), tmp_path
    )
    assert any("docs/a.md" in w and "42" in w for w in warns)


def test_dangling_reference_includes_source_file(tmp_path: Path):
    problems = _check(
        tmp_path,
        [_mk("a.x", {"depends_on": ["nope.x"]}, "docs/a.md")],
    )
    assert any("docs/a.md" in p and "nope.x" in p for p in problems)


def test_dangling_edge_names_both_sides(tmp_path: Path):
    # 참조자만 지목하면 저자가 멀쩡한 index.md 를 들여다보게 됨.
    problems = _check(tmp_path, [_mk("index", {"related": ["ghost"]}, path="docs/index.md")])
    (msg,) = [p for p in problems if "ghost" in p]
    assert "docs/index.md" in msg
    assert "wiki_id" in msg


def test_cycle_includes_all_file_paths(tmp_path: Path):
    nodes = [
        _mk("a.x", {"depends_on": ["b.x"]}, "docs/a.md"),
        _mk("b.x", {"depends_on": ["c.x"]}, "docs/b.md"),
        _mk("c.x", {"depends_on": ["a.x"]}, "docs/c.md"),
    ]
    problems = _check(tmp_path, nodes)
    cycle_msg = [p for p in problems if "순환" in p][0]
    assert "docs/a.md" in cycle_msg
    assert "docs/b.md" in cycle_msg
    assert "docs/c.md" in cycle_msg


def test_defect_without_affects_blocks(tmp_path: Path):
    node = _mk("defect.skew", {}, "docs/defects/skew.md")
    assert any("affects" in p for p in validate_defects(tmp_path, [node]))


def test_defect_with_affects_passes(tmp_path: Path):
    node = _mk("defect.skew", {"affects": ["auth.jwt"]}, "docs/defects/skew.md")
    assert validate_defects(tmp_path, [node]) == []


def test_bad_commit_sha_blocks(tmp_path: Path):
    node = _mk(
        "defect.skew", {"affects": ["auth.jwt"], "commit": "not-a-sha"}, "docs/defects/skew.md"
    )
    assert any("commit" in p for p in validate_defects(tmp_path, [node]))


def test_good_commit_sha_passes(tmp_path: Path):
    node = _mk(
        "defect.skew", {"affects": ["auth.jwt"], "commit": "66b7463"}, "docs/defects/skew.md"
    )
    assert validate_defects(tmp_path, [node]) == []


def test_missing_regression_test_file_blocks(tmp_path: Path):
    node = _mk(
        "defect.skew",
        {"affects": ["auth.jwt"], "regression_test": "tests/test_jwt.py::test_skew"},
        "docs/defects/skew.md",
    )
    assert any("tests/test_jwt.py" in p for p in validate_defects(tmp_path, [node]))


def test_regression_test_checks_only_the_path_before_the_node_id(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_jwt.py").write_text("", encoding="utf-8")
    node = _mk(
        "defect.skew",
        {"affects": ["auth.jwt"], "regression_test": "tests/test_jwt.py::test_skew"},
        "docs/defects/skew.md",
    )
    assert validate_defects(tmp_path, [node]) == []


def test_missing_promoted_rule_file_blocks(tmp_path: Path):
    node = _mk(
        "defect.skew",
        {"affects": ["auth.jwt"], "promoted_to_rule": "rules/gone.md"},
        "docs/defects/skew.md",
    )
    assert any("rules/gone.md" in p for p in validate_defects(tmp_path, [node]))


def test_non_defect_node_using_defect_fields_blocks(tmp_path: Path):
    node = _mk("auth.jwt", {"affects": ["auth.user"]}, "docs/a.md")
    assert any("defect" in p for p in validate_defects(tmp_path, [node]))


def test_adjacency_ignores_direction():
    nodes = [_mk("b.x", {"related": ["a.x"]}, "docs/b.md"), _mk("a.x", path="docs/a.md")]
    adj = undirected_adjacency(build_graph(nodes))
    assert "b.x" in adj["a.x"] and "a.x" in adj["b.x"]


def test_adjacency_drops_dangling_targets():
    # 실존하지 않는 id 를 인접에 실으면, 같은 오타를 가리키는 두 노드가 orphan 판정에서
    # 서로 연결된 것으로 세어짐 — index 에서 도달 불가인 노드가 도달 가능으로 보임.
    nodes = [
        _mk("a.x", {"related": ["ghost.id"]}, "docs/a.md"),
        _mk("b.x", {"related": ["ghost.id"]}, "docs/b.md"),
    ]
    adj = undirected_adjacency(build_graph(nodes))
    assert "ghost.id" not in adj
    assert adj["a.x"] == [] and adj["b.x"] == []


def test_orphan_warns():
    nodes = [
        _mk("index", path="docs/index.md"),
        _mk("lonely.x", path="docs/lonely.md"),
    ]
    warns = collect_warnings(_wiki(), nodes, build_graph(nodes))
    assert any("lonely.x" in w and "orphan" in w for w in warns)


def test_node_reachable_from_index_is_not_orphan():
    nodes = [
        _mk("index", {"related": ["a.x"]}, "docs/index.md"),
        _mk("a.x", {"related": ["index"]}, "docs/a.md"),
    ]
    assert collect_warnings(_wiki(), nodes, build_graph(nodes)) == []


def test_max_lines_warns():
    node = _mk("a.x", path="docs/a.md")
    node["line_count"] = 500
    nodes = [_mk("index", {"related": ["a.x"]}, "docs/index.md"), node]
    node["front"]["related"] = ["index"]
    warns = collect_warnings(_wiki(max_lines=400), nodes, build_graph(nodes))
    assert any("500" in w and "docs/a.md" in w for w in warns)


def test_max_lines_zero_disables_the_check():
    node = _mk("index", path="docs/index.md")
    node["line_count"] = 9999
    assert collect_warnings(_wiki(max_lines=0), [node], build_graph([node])) == []


def test_rule_promotion_threshold_warns():
    nodes = [_mk("index", path="docs/index.md")]
    for i in range(3):
        nodes.append(
            _mk(f"defect.d{i}", {"affects": ["index"], "tags": ["auth"]}, f"docs/defects/d{i}.md")
        )
    warns = collect_warnings(_wiki(), nodes, build_graph(nodes))
    assert any("auth" in w and "Rule" in w for w in warns)


def test_rule_promotion_silent_when_already_promoted():
    nodes = [_mk("index", path="docs/index.md")]
    for i in range(3):
        nodes.append(
            _mk(
                f"defect.d{i}",
                {
                    "affects": ["index"],
                    "tags": ["auth"],
                    "promoted_to_rule": "rules/x.md" if i == 0 else None,
                },
                f"docs/defects/d{i}.md",
            )
        )
    assert not any("Rule" in w for w in collect_warnings(_wiki(), nodes, build_graph(nodes)))


def test_safe_int_handles_non_numeral_strings():
    assert _safe_int("abc") == 0
    assert _safe_int("many") == 0
    assert _safe_int("42") == 42
    assert _safe_int(42) == 42
    assert _safe_int(0.0) == 0
    assert _safe_int("0") == 0
    assert _safe_int(None) == 0
    assert _safe_int("xyz", default=100) == 100


def test_index_not_a_node_skips_per_node_orphan_check():
    # index 가 노드로 해석되지 않으면 개별 노드를 orphan 이라고 오판해서는 안 됨 —
    # 도달 가능성 자체를 계산할 기준점이 없기 때문.
    nodes = [
        _mk("a.x", path="docs/a.md"),
        _mk("b.x", path="docs/b.md"),
    ]
    warns = collect_warnings(_wiki(index="docs/missing.md"), nodes, build_graph(nodes))
    assert not any("'a.x'" in w or "'b.x'" in w for w in warns)


def test_index_not_a_node_warns_the_check_is_off():
    # wiki 가 켜진 상태에서 index 가 노드로 해석되지 않으면, orphan 검사 자체가 조용히
    # 꺼져 있다는 것을 운영자에게 알려야 함 (block 이 아니라 warn).
    nodes = [_mk("a.x", path="docs/a.md")]
    warns = collect_warnings(_wiki(index="docs/missing.md"), nodes, build_graph(nodes))
    assert any("docs/missing.md" in w for w in warns)


def test_index_not_a_node_is_silent_when_there_are_no_nodes():
    # 노드가 아예 없으면 검사할 것도 없음 — 빈 wiki 에 노이즈를 내지 않음.
    warns = collect_warnings(_wiki(index="docs/missing.md"), [], build_graph([]))
    assert warns == []


def test_node_linked_to_but_not_from_is_not_orphan():
    nodes = [
        _mk("index", path="docs/index.md"),
        _mk("a.x", {"related": ["index"]}, "docs/a.md"),
    ]
    warns = collect_warnings(_wiki(), nodes, build_graph(nodes))
    assert not any("orphan" in w for w in warns)
