"""깨진 front matter — 막을 것과 경고할 것의 경계.

`wiki_id` 마커를 든 채 파싱이 깨지면 막음. 마커가 없으면 노드가 아니므로 경고에
그침 — 평범한 마크다운을 붙잡으면 아무도 문서를 안 씀.
"""

from pathlib import Path

from scripts.wiki_graph import (
    PROBLEM_CAP,
    build_graph,
    cmd_build,
    cmd_verify,
    collect_nodes,
    collect_warnings,
    load_wiki_config,
)
from tests.wiki._helpers import (
    _check,
    _mk,
    _node,
    _wiki_repo,
    _write_config,
)


def test_broken_front_matter_with_marker_blocks_and_names_the_file(tmp_path: Path):
    # 따옴표 하나 빠지면 YAML 이 죽음. 이 문서는 wiki_id 를 썼으니 노드로 의도한 것이
    # 명백함 — 조용히 사라지면 --verify 가 exit 0 을 보고하고, /wiki-init 8절의
    # "verify 통과 = wiki 강제됨" 이 거짓이 됨.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/broken.md", "wiki_id: broken\ntitle: New: Doc\n")
    nodes = collect_nodes(tmp_path, load_wiki_config(tmp_path))
    problems = _check(tmp_path, nodes)
    assert any("docs/broken.md" in p and "읽지 못했습니다" in p for p in problems)


def test_broken_front_matter_without_marker_warns_but_never_blocks(tmp_path: Path):
    # 파싱이 죽었으니 wiki_id 가 있었는지 YAML 로는 알 수 없음. 원문에 마커 줄이 없으면
    # 남의 문서일 수 있으므로 차단하지 않음 — Task 1 과 같은 원칙.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/theirs.md", "title: New: Doc\nsidebar_position: 1\n")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    assert _check(tmp_path, nodes) == []
    warns = collect_warnings(wiki, nodes, build_graph(nodes), tmp_path)
    assert any("docs/theirs.md" in w and "읽지 못해" in w for w in warns)


def test_plain_markdown_is_not_reported_as_broken(tmp_path: Path):
    # 여는 `---` 가 없거나 닫는 `---` 가 없는 파일은 front matter 가 아님. 문서 첫 줄의
    # 수평선·setext 밑줄이 흔하고, 이것까지 깨진 것으로 세면 경고가 노이즈가 됨.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    (tmp_path / "docs" / "plain.md").write_text("# 제목\n\n본문\n", encoding="utf-8")
    (tmp_path / "docs" / "rule.md").write_text("---\n\n본문만 있고 닫히지 않음\n", encoding="utf-8")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    assert nodes == []
    assert collect_warnings(wiki, nodes, build_graph(nodes), tmp_path) == []


def test_empty_front_matter_is_not_reported_as_broken(tmp_path: Path):
    # Jekyll 관례로 흔한 빈 블록. safe_load 가 None 을 돌려주지만 깨진 것이 아니라
    # 그냥 노드가 아님 — 이걸 경고하면 평범한 문서 트리 전체가 다시 노이즈가 됨.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    (tmp_path / "docs" / "empty.md").write_text("---\n---\n\n본문\n", encoding="utf-8")
    (tmp_path / "docs" / "comment.md").write_text("---\n# 주석뿐\n---\n\n본문\n", encoding="utf-8")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    assert nodes == []
    assert collect_warnings(wiki, nodes, build_graph(nodes), tmp_path) == []


def test_non_map_front_matter_is_still_reported_broken(tmp_path: Path):
    # None (empty block) is not broken, but a non-None non-map — a bare YAML list, here — still
    # is. Pins the `if front is None or isinstance(front, dict)` guard so it cannot be loosened
    # into skipping every non-dict yield, which would silently re-admit the exact "front matter
    # that parses to something other than a node" case this task exists to surface.
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/listy.md", "- a\n- b\n")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    assert _check(tmp_path, nodes) == []  # no wiki_id line in the raw text -> warn, not block
    warns = collect_warnings(wiki, nodes, build_graph(nodes), tmp_path)
    assert any("docs/listy.md" in w and "읽지 못해" in w for w in warns)


def test_verify_no_longer_passes_silently_on_a_broken_node(tmp_path: Path):
    # 재현된 시나리오: --build 가 깨진 문서를 뺀 그래프를 먼저 쓰면 drift 탐지도 무력화되어
    # --verify 가 exit 0 을 냄. 그 무음을 없앤 것이 이 테스트의 대상.
    _wiki_repo(tmp_path)
    _node(tmp_path, "docs/broken.md", "wiki_id: broken\ntitle: New: Doc\n")
    assert cmd_build(tmp_path) == 0
    assert cmd_verify(tmp_path) == 1


def test_structural_problem_output_is_capped(tmp_path: Path, capsys):
    # 이 출력이 그대로 precommit deny 사유가 됨 (vdev_gate_check.wiki_check_output).
    # 캡이 없으면 문서 300 개가 위반일 때 deny 사유가 300 줄.
    _wiki_repo(tmp_path)
    for i in range(12):
        _node(tmp_path, f"docs/bad{i}.md", f"wiki_id: Bad_{i}\ntitle: T\n")
    assert cmd_build(tmp_path) == 0
    assert cmd_verify(tmp_path) == 1
    err = capsys.readouterr().err
    assert err.count("형식 위반") == 10
    assert "... 외 2건 (구조 위반)" in err


def test_validate_structure_itself_stays_uncapped(tmp_path: Path):
    # 캡은 출력 단계의 것. 순수 함수는 전수를 돌려줘야 테스트가 전수를 확인할 수 있음.
    nodes = [_mk(f"Bad_{i}", path=f"docs/bad{i}.md") for i in range(12)]
    assert len([p for p in _check(tmp_path, nodes) if "형식 위반" in p]) == 12


def test_drift_reason_survives_a_full_structural_cap(tmp_path: Path, capsys):
    # 합쳐진 리스트에 캡을 걸면 구조 위반 10 건이 drift 사유를 밀어내고, 저자는 두 해소
    # 경로(front matter 수정 / --build) 중 하나를 보지 못함.
    _wiki_repo(tmp_path)
    assert cmd_build(tmp_path) == 0
    for i in range(12):
        _node(tmp_path, f"docs/bad{i}.md", f"wiki_id: Bad_{i}\ntitle: T\n")
    assert cmd_verify(tmp_path) == 1
    err = capsys.readouterr().err
    assert "graph.yaml 이 front matter 와 어긋납니다" in err


def test_structural_problem_cap_boundary(tmp_path: Path, capsys):
    # count 만 보면 `if structural > PROBLEM_CAP`이 `>=` 로 뒤집혀도 안 걸림 — 그 회귀는
    # 카운터 문구만 어긋나게 만듦. 그래서 여기서는 두 경계를 각각 고정: 정확히
    # PROBLEM_CAP 건에서는 카운터 줄 자체가 없어야 하고, 그보다 하나 많을 때만 정확히
    # 1건을 보고해야 함.
    _wiki_repo(tmp_path)
    for i in range(PROBLEM_CAP):
        _node(tmp_path, f"docs/bad{i}.md", f"wiki_id: Bad_{i}\ntitle: T\n")
    assert cmd_build(tmp_path) == 0
    assert cmd_verify(tmp_path) == 1
    err = capsys.readouterr().err
    assert err.count("형식 위반") == PROBLEM_CAP
    # "해소(구조 위반): ..." 안내문에도 "구조 위반"이 들어 있으므로, 카운터 줄에만 있는
    # "건 (구조 위반)" 접미사로 좁혀서 카운터 줄의 부재를 확인함.
    assert "건 (구조 위반)" not in err

    _node(tmp_path, f"docs/bad{PROBLEM_CAP}.md", f"wiki_id: Bad_{PROBLEM_CAP}\ntitle: T\n")
    assert cmd_build(tmp_path) == 0
    assert cmd_verify(tmp_path) == 1
    err = capsys.readouterr().err
    assert err.count("형식 위반") == PROBLEM_CAP
    assert "... 외 1건 (구조 위반)" in err
