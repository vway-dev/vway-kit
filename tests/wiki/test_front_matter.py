"""front matter 파싱과 노드 수집.

구분자가 없으면 노드가 아님. BOM·CRLF·본문의 `---` 줄처럼 파일을 깨뜨리기 쉬운
모양들이 여기서 결판남 — 잘못 읽으면 문서가 조용히 그래프에서 사라짐.
"""

from pathlib import Path

from scripts import wiki_graph
from scripts.wiki_graph import (
    build_graph,
    collect_nodes,
    collect_warnings,
    load_wiki_config,
    parse_front_matter,
)
from tests.wiki._helpers import (
    _node,
    _write_config,
)


def test_parse_front_matter_returns_none_without_delimiters():
    assert parse_front_matter("# 그냥 문서\n\n본문\n") is None


def test_parse_front_matter_reads_yaml():
    text = "---\nwiki_id: auth.jwt\ntitle: JWT\n---\n\n본문\n"
    assert parse_front_matter(text) == {"wiki_id": "auth.jwt", "title": "JWT"}


def test_parse_front_matter_broken_yaml_is_none():
    assert parse_front_matter("---\nwiki_id: [unclosed\n---\n\n본문\n") is None


def test_front_matter_ruler_first_line_is_not_a_block():
    # `----` 는 여는 구분자가 아님 — find("\n---") 시절 hr 로 시작하는 문서가
    # "깨진 front matter" 경고로 잡히던 케이스.
    assert wiki_graph._front_matter_block("----\n제목\n----\n본문\n") is None


def test_front_matter_crlf_closing_line():
    text = "---\r\nwiki_id: a\r\ntitle: T\r\n---\r\n\r\n본문\r\n"
    assert parse_front_matter(text) == {"wiki_id": "a", "title": "T"}


def test_front_matter_closing_line_tolerates_trailing_blanks():
    text = "---\nwiki_id: a\ntitle: T\n---  \n본문\n"
    assert parse_front_matter(text) == {"wiki_id": "a", "title": "T"}


def test_front_matter_body_dashes_line_does_not_close_early():
    # 블록 안 열 0 의 `--- note` 줄은 닫는 구분자가 아님. 조기 종결은 wiki_id 를
    # 조용히 블록 밖으로 밀어내 노드가 소리 없이 사라지게 함.
    text = "---\ntitle: T\n--- note\nwiki_id: a\n---\n본문\n"
    block = wiki_graph._front_matter_block(text)
    assert block is not None and "wiki_id: a" in block


def test_duplicate_wiki_id_lines_warn(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/index.md", "wiki_id: index\ntitle: Index\n")
    _node(tmp_path, "docs/a.md", "wiki_id: old\nwiki_id: a\ntitle: A\n")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    warns = collect_warnings(wiki, nodes, build_graph(nodes))
    assert any("wiki_id" in w and "여러 개" in w for w in warns)


def test_collect_nodes_skips_files_without_front_matter(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/index.md", "wiki_id: index\ntitle: Index\n")
    (tmp_path / "docs" / "README.md").write_text("# 랜딩\n", encoding="utf-8")
    nodes = collect_nodes(tmp_path, load_wiki_config(tmp_path))
    assert [n["id"] for n in nodes] == ["index"]


def test_collect_nodes_records_path_and_line_count(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/auth/jwt.md", "wiki_id: auth.jwt\ntitle: JWT\n", "가\n나\n다\n")
    (node,) = collect_nodes(tmp_path, load_wiki_config(tmp_path))
    assert node["path"] == "docs/auth/jwt.md"
    assert node["line_count"] == 8  # --- id title --- 빈줄 가 나 다
    assert node["front"]["title"] == "JWT"


def test_collect_nodes_strips_utf8_bom(tmp_path: Path):
    # Windows 에디터가 남기는 BOM(﻿)이 "---" 앞에 붙으면 plain utf-8 로는 그대로
    # 살아남아 parse_front_matter 의 startswith 검사를 조용히 깨뜨림 — 노드가 경고 없이
    # graph 에서 사라짐 (Invariant #2, Windows 에서만 재현·permissive 방향으로 틀림).
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/index.md", "wiki_id: index\ntitle: Index\n")
    bommed = tmp_path / "docs" / "auth.md"
    fm = "---\nwiki_id: auth.jwt\ntitle: JWT\n---\n\n본문\n"
    bommed.write_bytes(b"\xef\xbb\xbf" + fm.encode())
    nodes = collect_nodes(tmp_path, load_wiki_config(tmp_path))
    assert sorted(n["id"] for n in nodes) == ["auth.jwt", "index"]


def test_collect_nodes_keeps_document_missing_marker(tmp_path: Path):
    # id 누락은 여기서 거르지 않음 — 노드는 아니지만 경고로 보이게 해야 하므로 실어 보냄.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/broken.md", "title: 제목만\n")
    (node,) = collect_nodes(tmp_path, load_wiki_config(tmp_path))
    assert node["id"] is None


def test_collect_nodes_broken_document_shape(tmp_path: Path):
    # Every downstream consumer relies on `front` being a dict rather than None (a broken
    # node still flows through `node["front"].get(...)` calls), and on `broken` /
    # `marker_seen` being present at all — pin the exact shape collect_nodes produces for a
    # document whose front matter opens and closes but fails to parse as YAML.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/broken.md", "title: New: Doc\n")
    (node,) = collect_nodes(tmp_path, load_wiki_config(tmp_path))
    assert node["id"] is None
    assert node["front"] == {}
    assert isinstance(node["broken"], str) and node["broken"]
    assert isinstance(node["marker_seen"], bool)
