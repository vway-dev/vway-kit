"""sds 문서가 자기 코드를 가리키는가 — `--verify` 경고와 `--unmapped` 목록.

`sources` 값이 없는 sds 노드는 `--stale` 에도 `--nodes-for` 에도 안 잡혀 아무 데서도
보고되지 않음. 경고는 키가 없거나 값이 비었을 때만 울고, 그린필드가 적는 `sources: {}`
에는 침묵함 — 그 빈 맵을 세는 유일한 자리가 `--unmapped`.
"""

import json
from pathlib import Path

from scripts import wiki_graph
from scripts.wiki_graph import build_graph, collect_warnings
from tests.wiki._helpers import _mk, _node, _wiki, _write_config


def _sources_warns(nodes):
    """이 경고만 골라냄. 'sds' 로만 매칭하면 같은 경로를 대는 orphan 줄까지 걸려,
    아래 침묵 단언들이 전부 엉뚱한 경고 위에서 통과함."""
    warns = collect_warnings(_wiki(), nodes, build_graph(nodes))
    return [w for w in warns if "sds 문서인데 sources 값이" in w]


def test_sds_node_without_sources_warns():
    nodes = [
        _mk("index", path="docs/index.md"),
        _mk("sds.readme", {"tags": ["sds"]}, "docs/sds/README.md"),
    ]
    assert any("docs/sds/README.md" in w for w in _sources_warns(nodes))


def test_sds_node_with_empty_sources_is_quiet():
    # `sources: {}` 는 "아직 매핑할 코드가 없음" 이라는 저자의 진술 — 그린필드 SDS 가 달고
    # 나오는 모양임. 여기서 울면 생성된 설계 문서마다 영원히 울고, 유일한 해소책이 doc-sync
    # 단계가 명시적으로 금지한 것(경로 지어내기)임.
    node = _mk("sds.readme", {"tags": ["sds"], "sources": {}}, "docs/sds/README.md")
    assert _sources_warns([node]) == []


def test_sds_node_with_null_sources_warns():
    # `sources:` 뒤가 빈 것은 YAML null — 빈 맵 진술이 아니라 중간에 멈춘 편집임.
    # `validate_structure` 도 None 을 통과시키므로, 이것을 "선언됨" 으로 읽으면 노드가
    # 아무 데서도 안 보이는 채로 남음.
    node = _mk("sds.readme", {"tags": ["sds"], "sources": None}, "docs/sds/README.md")
    assert any("docs/sds/README.md" in w for w in _sources_warns([node]))


def test_sds_node_with_list_sources_is_quiet():
    # 리스트는 틀린 모양이지만 `validate_structure` 가 자기 메시지로 이미 막고,
    # `--nodes-for` 는 리스트를 읽음 — 이 경고 문구가 거짓이 되고 한 실수가 두 번 보고됨.
    node = _mk("sds.readme", {"tags": ["sds"], "sources": ["src/a.py"]}, "docs/sds/README.md")
    assert _sources_warns([node]) == []


def test_sds_tag_is_read_from_a_bare_string():
    # `tags: sds`(리스트 아닌 스칼라)는 사람이 쓰는 유효한 YAML. `_as_list` 없이는 멤버십
    # 검사가 문자열에 걸려 "sds" in "sds" 가 우연히 참 — 그러면 `tags: sdsx` 도 걸림.
    node = _mk("sds.readme", {"tags": "sds"}, "docs/sds/README.md")
    assert any("docs/sds/README.md" in w for w in _sources_warns([node]))


def test_a_substring_tag_does_not_count_as_sds():
    # 일부러 스칼라: `_as_list("sdsx")` 는 `["sdsx"]` 라 "sds" 를 포함하지 않음. 원값을
    # 그대로 읽으면 멤버십이 부분문자열 검사가 되어 세 글자 든 태그가 전부 울림.
    node = _mk("x.readme", {"tags": "sdsx"}, "docs/x/README.md")
    assert _sources_warns([node]) == []


def test_a_non_node_is_never_warned_about():
    # wiki_id 가 없으면 wiki 노드가 아님. 그 front matter 는 저자의 wiki 선언이 아니므로,
    # 보고하면 다른 곳의 마커 억제가 피하려는 바로 그 소음이 됨.
    node = {"id": "", "path": "docs/sds/README.md", "line_count": 3, "front": {"tags": ["sds"]}}
    assert _sources_warns([node]) == []


def test_sds_node_with_sources_is_quiet():
    node = _mk("sds.readme", {"tags": ["sds"], "sources": {"src/a.py": None}}, "docs/sds/README.md")
    assert _sources_warns([node]) == []


def test_non_sds_node_without_sources_is_quiet():
    # 태그로 좁히는 이유 자체 — 요구사항·온보딩 문서는 코드 경로에 안 걸리는 게 정상이고,
    # 거기까지 울면 블록 전체가 안 읽히는 상시 소음이 됨.
    node = _mk("srs.readme", {"tags": ["srs"]}, "docs/srs/README.md")
    assert _sources_warns([node]) == []


# ---------------------------------------------------------------- --unmapped


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    return tmp_path


def _unmapped(root: Path, capsys) -> list[dict]:
    assert wiki_graph.cmd_unmapped(root) == 0
    return json.loads(capsys.readouterr().out)


def test_empty_map_is_listed(tmp_path: Path, capsys):
    # `--verify` 가 일부러 침묵하는 경우. 이것을 세는 자리가 달리 없어서, 그린필드 설계의
    # `sources: {}` 가 코드가 붙은 뒤에도 실경로가 되지 못하고 남았음.
    root = _repo(tmp_path)
    _node(root, "docs/sds/README.md", "wiki_id: sds.readme\ntitle: S\ntags: [sds]\nsources: {}\n")
    assert _unmapped(root, capsys) == [{"id": "sds.readme", "path": "docs/sds/README.md"}]


def test_absent_key_is_listed(tmp_path: Path, capsys):
    root = _repo(tmp_path)
    _node(root, "docs/sds/README.md", "wiki_id: sds.readme\ntitle: S\ntags: [sds]\n")
    assert [n["id"] for n in _unmapped(root, capsys)] == ["sds.readme"]


def test_valueless_key_is_listed(tmp_path: Path, capsys):
    root = _repo(tmp_path)
    _node(root, "docs/sds/README.md", "wiki_id: sds.readme\ntitle: S\ntags: [sds]\nsources:\n")
    assert [n["id"] for n in _unmapped(root, capsys)] == ["sds.readme"]


def test_a_mapped_node_is_not_listed(tmp_path: Path, capsys):
    root = _repo(tmp_path)
    _node(
        root,
        "docs/sds/README.md",
        "wiki_id: sds.readme\ntitle: S\ntags: [sds]\nsources:\n  src/a.py: null\n",
    )
    assert _unmapped(root, capsys) == []


def test_a_list_valued_sources_is_not_listed(tmp_path: Path, capsys):
    # `--nodes-for` 가 리스트를 읽으므로 노드는 닿을 수 있고 빠진 것이 없음. 모양 위반은
    # 구조 검증이 따로 막음 — 여기 실으면 엉뚱한 해소책을 지시하게 됨.
    root = _repo(tmp_path)
    _node(
        root,
        "docs/sds/README.md",
        "wiki_id: sds.readme\ntitle: S\ntags: [sds]\nsources: [src/a.py]\n",
    )
    assert _unmapped(root, capsys) == []


def test_a_non_sds_node_is_not_listed(tmp_path: Path, capsys):
    # SRS 나 온보딩 문서는 코드 경로에 안 걸리는 게 정상.
    root = _repo(tmp_path)
    _node(root, "docs/srs/README.md", "wiki_id: srs.readme\ntitle: R\ntags: [srs]\n")
    assert _unmapped(root, capsys) == []


def test_a_substring_tag_is_not_sds_in_the_listing(tmp_path: Path, capsys):
    # 일부러 스칼라: `_as_list("sdsx")` 는 `["sdsx"]` 라 "sds" 를 안 담음. 원값을 읽으면
    # 멤버십이 부분문자열 검사가 되어 "sdsx" 가 걸림.
    root = _repo(tmp_path)
    _node(root, "docs/x/README.md", "wiki_id: x.readme\ntitle: X\ntags: sdsx\n")
    assert _unmapped(root, capsys) == []


def test_a_scalar_tag_still_counts(tmp_path: Path, capsys):
    root = _repo(tmp_path)
    _node(root, "docs/sds/README.md", "wiki_id: sds.readme\ntitle: S\ntags: sds\n")
    assert [n["id"] for n in _unmapped(root, capsys)] == ["sds.readme"]


def test_a_document_without_a_wiki_id_is_not_a_node(tmp_path: Path, capsys):
    root = _repo(tmp_path)
    _node(root, "docs/sds/README.md", "title: S\ntags: [sds]\n")
    assert _unmapped(root, capsys) == []


def test_no_wiki_prints_an_empty_list(tmp_path: Path, capsys):
    # doc-sync 는 이 명령을 무조건 돌림 — wiki 가 없어도 실패가 아니라 답을 내야 함.
    # 노드가 있어야 판별력이 생김: 빈 `docs/` 는 no-wiki 갈래를 읽든 config 를 무시하고
    # `docs/` 를 훑든 똑같이 `[]`.
    (tmp_path / "docs").mkdir()
    _node(tmp_path, "docs/sds/README.md", "wiki_id: sds.readme\ntitle: S\ntags: [sds]\n")
    assert _unmapped(tmp_path, capsys) == []


def test_output_is_path_sorted(tmp_path: Path, capsys):
    root = _repo(tmp_path)
    _node(root, "docs/sds/b.md", "wiki_id: sds.b\ntitle: B\ntags: [sds]\n")
    _node(root, "docs/sds/a.md", "wiki_id: sds.a\ntitle: A\ntags: [sds]\n")
    assert [n["path"] for n in _unmapped(root, capsys)] == ["docs/sds/a.md", "docs/sds/b.md"]


def test_cli_dispatches_unmapped(tmp_path: Path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _node(root, "docs/sds/README.md", "wiki_id: sds.readme\ntitle: S\ntags: [sds]\n")
    monkeypatch.setattr(wiki_graph, "host_root", lambda: root)
    assert wiki_graph.main(["--unmapped"]) == 0
    assert [n["id"] for n in json.loads(capsys.readouterr().out)] == ["sds.readme"]
