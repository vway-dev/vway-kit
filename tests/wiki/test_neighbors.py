"""`--neighbors` — 예산 안에서 무엇을 먼저 보여주는가.

시작 노드가 예산을 넘겨도 먼저 나옴. 같은 홉이면 `depends_on` 이 `related` 를
이기고, 순환은 끝남.
"""

from pathlib import Path

from scripts.wiki_graph import (
    build_graph,
    cmd_build,
    cmd_neighbors,
    graph_path,
    load_wiki_config,
    neighbors,
)
from tests.wiki._helpers import (
    _sized,
    _wiki_repo,
)


def test_start_node_comes_first():
    nodes = [_sized("a.x", {"related": ["b.x"]}), _sized("b.x")]
    paths, _total, _cut = neighbors(build_graph(nodes), nodes, "a.x", 1000)
    assert paths[0] == "docs/a.x.md"


def test_budget_stops_expansion():
    nodes = [
        _sized("a.x", {"related": ["b.x", "c.x"]}, lines=10),
        _sized("b.x", lines=10),
        _sized("c.x", lines=10),
    ]
    paths, total, cut = neighbors(build_graph(nodes), nodes, "a.x", 25)
    assert len(paths) == 2 and total == 20 and cut == 1


def test_start_node_included_even_when_over_budget():
    nodes = [_sized("a.x", lines=9999)]
    paths, total, _cut = neighbors(build_graph(nodes), nodes, "a.x", 10)
    assert paths == ["docs/a.x.md"] and total == 9999


def test_depends_on_wins_over_related_at_the_same_hop():
    nodes = [
        _sized("a.x", {"depends_on": ["dep.x"], "related": ["rel.x"]}, lines=10),
        _sized("dep.x", lines=10),
        _sized("rel.x", lines=10),
    ]
    paths, _total, _cut = neighbors(build_graph(nodes), nodes, "a.x", 25)
    assert paths == ["docs/a.x.md", "docs/dep.x.md"]


def test_cycle_terminates():
    nodes = [_sized("a.x", {"related": ["b.x"]}), _sized("b.x", {"related": ["a.x"]})]
    paths, _total, _cut = neighbors(build_graph(nodes), nodes, "a.x", 1000)
    assert sorted(paths) == ["docs/a.x.md", "docs/b.x.md"]


def test_unknown_id_exits_nonzero(tmp_path: Path, capsys):
    # 0 + 빈 stdout 이면 "이웃 없음"과 구별되지 않아, 호출자가 조회 실패를
    # '조화시킬 문서가 없음'으로 읽고 그냥 넘어감. 게이트는 --neighbors 를 부르지 않으므로
    # 여기서 1 을 내도 커밋을 막지 않음.

    _wiki_repo(tmp_path)
    assert cmd_neighbors(tmp_path, "nope.x", None) == 1
    out = capsys.readouterr()
    assert out.out == "" and "nope.x" in out.err


def test_cli_uses_context_lines_when_budget_omitted(tmp_path: Path, capsys):
    _wiki_repo(tmp_path)
    assert cmd_neighbors(tmp_path, "index", None) == 0
    assert "docs/index.md" in capsys.readouterr().out


def test_dangling_reference_does_not_crash():
    # Edge to non-existent id should not crash; walk continues and entry point returns.
    nodes = [_sized("a.x", {"related": ["ghost.id"]})]
    paths, total, cut = neighbors(build_graph(nodes), nodes, "a.x", 1000)
    assert paths == ["docs/a.x.md"] and total == 10


def test_budget_stops_before_dangling_neighbor():
    # After budget exhaustion, walk reaches dangling node but correctly skips it.
    nodes = [
        _sized("a.x", {"related": ["b.x", "ghost.id"]}, lines=10),
        _sized("b.x", lines=10),
    ]
    paths, total, cut = neighbors(build_graph(nodes), nodes, "a.x", 15)
    # a.x (10) + b.x (10) = 20 > 15, so b.x skipped; ghost.id never checked.
    assert len(paths) == 1 and paths[0] == "docs/a.x.md" and total == 10 and cut == 1


def test_bom_on_index_does_not_shrink_the_graph(tmp_path: Path):
    # 재현된 구체 시나리오: index.md 가 BOM 을 달고 있으면 index 자신이 노드에서 빠져
    # _index_id 가 None 을 반환하고, orphan 검사가 저장소 전체에서 조용히 꺼짐.
    _wiki_repo(tmp_path)
    idx = tmp_path / "docs" / "index.md"
    idx.write_bytes(b"\xef\xbb\xbf" + idx.read_bytes())
    assert cmd_build(tmp_path) == 0
    gp = graph_path(tmp_path, load_wiki_config(tmp_path))
    import yaml as _yaml

    graph = _yaml.safe_load(gp.read_text(encoding="utf-8"))
    assert len(graph["nodes"]) == 2  # BOM 이전과 동일 — index 노드가 사라지지 않음
