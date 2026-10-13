"""wiki 설정 읽기 — 꺼져 있으면 아무 일도 하지 않음.

`vdev-config.wiki` 가 없거나 꺼졌거나 깨졌으면 no-op(FAIL-OPEN). 루트 경로는
정규화해 노드 경로와 대조하므로 `./docs` 같은 비정규 표기도 같은 그래프를 만듦.
"""

from pathlib import Path

from scripts.wiki_graph import (
    build_graph,
    collect_nodes,
    collect_warnings,
    load_wiki_config,
)
from tests.wiki._helpers import (
    _node,
    _write_config,
)


def test_config_absent_is_noop(tmp_path: Path):
    assert load_wiki_config(tmp_path) is None


def test_wiki_key_absent_is_noop(tmp_path: Path):
    _write_config(tmp_path, "branches:\n  integration: dev\n")
    assert load_wiki_config(tmp_path) is None


def test_wiki_disabled_is_noop(tmp_path: Path):
    _write_config(tmp_path, "wiki:\n  enable: false\n  root: docs/\n")
    assert load_wiki_config(tmp_path) is None


def test_wiki_root_missing_dir_is_noop(tmp_path: Path):
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    assert load_wiki_config(tmp_path) is None


def test_non_canonical_root_still_matches_node_paths(tmp_path: Path):
    # 노드 경로는 relative_to(root).as_posix() 로 만들어짐. root 를 날것으로 두면
    # './docs/' 는 index 경로 './docs/index.md' 를 낳고 어떤 노드 경로와도 같아질 수 없어,
    # orphan 검사가 저장소 전체에서 조용히 꺼짐.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: ./docs/\n")
    cfg = load_wiki_config(tmp_path)
    assert cfg["root"] == "docs"
    assert cfg["index"] == "docs/index.md"


def test_non_canonical_index_is_normalized(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n  index: ./docs/home.md\n")
    assert load_wiki_config(tmp_path)["index"] == "docs/home.md"


def test_orphan_check_survives_a_non_canonical_root(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: ./docs/\n")
    _node(tmp_path, "docs/index.md", "wiki_id: index\ntitle: Index\n")
    _node(tmp_path, "docs/lonely.md", "wiki_id: lonely\ntitle: Lonely\n")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    warns = collect_warnings(wiki, nodes, build_graph(nodes))
    assert any("orphan" in w and "lonely" in w for w in warns)
    assert not any("orphan 검사를 생략" in w for w in warns)


def test_wiki_enabled_fills_defaults(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    cfg = load_wiki_config(tmp_path)
    assert cfg["root"] == "docs"
    assert cfg["index"] == "docs/index.md"
    assert cfg["max_lines"] == 400
    assert cfg["context_lines"] == 2000
    assert cfg["defect_rule_threshold"] == 3


def test_broken_config_is_noop(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki: [this is: not: valid\n")
    assert load_wiki_config(tmp_path) is None


def test_top_level_list_preserves_fail_open(tmp_path: Path):
    """Non-mapping top level (e.g. bare list) must return None, never raise."""
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "- not a mapping\n")
    assert load_wiki_config(tmp_path) is None
