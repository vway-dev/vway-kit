"""drift 판정 — 커밋된 `graph.yaml` 이 트리와 같은 것을 말하는가.

verify 는 절대 쓰지 않음. 손으로 고친 그래프·재포맷·BOM·깨진 YAML 각각이 drift 인지
아닌지가 다르고, 내부 예외는 FAIL-OPEN.
"""

import subprocess
from pathlib import Path

import pytest

from scripts import wiki_graph
from scripts.wiki_graph import (
    DERIVED_EDGES,
    EDGE_KEYS,
    MANUAL_EDGES,
    build_graph,
    cmd_build,
    cmd_verify,
    collect_warnings,
    graph_path,
    load_wiki_config,
)
from tests.wiki._helpers import (
    _check,
    _mk,
    _node,
    _wiki_repo,
    _write_config,
)


def test_coerced_id_is_reported_instead_of_vanishing(tmp_path: Path):
    # `wiki_id: no` → False → the node dropped out of the graph and was reported as having no
    # wiki_id, on a document whose wiki_id is right there. `wiki_id: 0123456` → 42798 silently
    # became a valid-looking id.
    problems = _check(
        tmp_path,
        [
            {
                "id": None,
                "path": "docs/a.md",
                "line_count": 3,
                "front": {"wiki_id": False, "title": "A"},
            },
            {
                "id": "42798",
                "path": "docs/c.md",
                "line_count": 3,
                "front": {"wiki_id": 42798, "title": "C"},
            },
        ],
    )
    assert any("docs/a.md" in p and "따옴표" in p for p in problems)
    assert any("docs/c.md" in p and "따옴표" in p for p in problems)


def test_coerced_edge_target_is_reported_by_type(tmp_path: Path):
    # `depends_on: no` became the string "False" and surfaced as "points at a missing id 'False'".
    problems = _check(tmp_path, [_mk("b.x", {"depends_on": False}, "docs/b.md")])
    assert any("depends_on[]" in p and "따옴표" in p for p in problems)


def test_missing_root_directory_is_announced(tmp_path: Path, capsys):
    # A typo'd root turned the whole gate off in total silence, and /wiki-init Step 8 reads
    # --build + --verify succeeding on empty output as proof the wiki is enforced.
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: doc/\n")
    (tmp_path / "docs").mkdir()
    assert load_wiki_config(tmp_path) is None
    assert "doc" in capsys.readouterr().err


def test_orphan_warnings_are_capped(tmp_path: Path):
    nodes = [_mk("index", path="docs/index.md")] + [
        _mk(f"n{i}", path=f"docs/n{i}.md") for i in range(6)
    ]
    warns = collect_warnings({"root": "docs", "index": "docs/index.md"}, nodes, build_graph(nodes))
    assert sum(1 for w in warns if w.startswith("orphan:")) == 3
    assert any("외 3건" in w for w in warns)


def test_bom_on_graph_yaml_is_not_drift(tmp_path: Path):
    # PyYAML accepts a leading BOM, so a Windows editor re-saving graph.yaml unchanged does not
    # turn it into permanent drift. Pinned because .md reads need utf-8-sig for the same reason
    # and the asymmetry looks like a bug.
    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    gp = graph_path(tmp_path, load_wiki_config(tmp_path))
    gp.write_bytes(b"\xef\xbb\xbf" + gp.read_bytes())
    assert cmd_verify(tmp_path) == 0


def test_edge_constants_cannot_desync():
    # DERIVED_EDGES / MANUAL_EDGES / EDGE_KEYS encode one fact three times, and EDGE_KEYS keeps
    # its own ORDER (it is the --neighbors budget priority), so it cannot be derived.
    # Adding an edge kind and forgetting EDGE_KEYS would silently drop it from drift detection
    # and orphan reachability with no error — this is the enforcement.

    assert set(EDGE_KEYS) == set(MANUAL_EDGES) | set(DERIVED_EDGES.values())
    assert set(DERIVED_EDGES) <= set(MANUAL_EDGES)
    assert len(EDGE_KEYS) == len(set(EDGE_KEYS))


def test_build_avoids_the_python_310_only_write_text_newline(tmp_path: Path, monkeypatch):
    # 게이트의 런타임 하한은 python 3.8 (check-deps.sh / precommit-runner.sh) 인데
    # Path.write_text(newline=…) 는 3.10 에 생김. 3.9 호스트에서는 TypeError 가 나고
    # main() 의 FAIL-OPEN 이 그것을 exit 0 으로 삼켜, --build 가 아무것도 안 쓴 채
    # 성공한 것처럼 보임 — 그 뒤 --verify 는 영원히 모든 커밋을 막음.
    _wiki_repo(tmp_path)
    real_write_text = Path.write_text

    def _as_python_39(self, *args, **kwargs):
        if "newline" in kwargs:
            raise TypeError("write_text() got an unexpected keyword argument 'newline'")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _as_python_39)
    assert cmd_build(tmp_path) == 0
    assert graph_path(tmp_path, load_wiki_config(tmp_path)).is_file()


def test_reformatted_graph_is_not_drift(tmp_path: Path):
    # PyYAML 은 버전마다 emitter 출력이 미묘하게 다름. 바이트로 비교하면 의미가 같은
    # graph.yaml 이 drift 로 읽혀, A 가 커밋하면 B 가 막히고 B 가 다시 빌드하면 A 가
    # 막히는 왕복이 됨. 판정 기준은 파싱 결과여야 함.
    import yaml as _yaml

    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    gp = graph_path(tmp_path, load_wiki_config(tmp_path))
    canonical = gp.read_bytes()
    same_graph = _yaml.safe_load(gp.read_text(encoding="utf-8"))
    gp.write_text(
        _yaml.safe_dump(same_graph, sort_keys=False, default_flow_style=True, width=20),
        encoding="utf-8",
    )
    assert gp.read_bytes() != canonical  # 바이트는 다름
    assert cmd_verify(tmp_path) == 0  # 의미는 같으므로 통과


def test_build_is_idempotent(tmp_path: Path):
    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    first = graph_path(tmp_path, load_wiki_config(tmp_path)).read_bytes()
    cmd_build(tmp_path)
    assert graph_path(tmp_path, load_wiki_config(tmp_path)).read_bytes() == first


def test_verify_without_graph_file_is_drift(tmp_path: Path):
    _wiki_repo(tmp_path)
    assert cmd_verify(tmp_path) == 1


def test_verify_never_writes_graph_file(tmp_path: Path):
    # --verify 는 읽기 전용 — 커밋 게이트가 부르는 쪽이 graph.yaml 을 쓰기 시작하면
    # doc-sync 만 build 를 부른다는 설계 전제가 깨짐.
    _wiki_repo(tmp_path)
    assert cmd_verify(tmp_path) == 1
    assert not graph_path(tmp_path, load_wiki_config(tmp_path)).exists()


def test_verify_does_not_modify_existing_graph_file(tmp_path: Path):
    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    gp = graph_path(tmp_path, load_wiki_config(tmp_path))
    before = gp.read_bytes()
    assert cmd_verify(tmp_path) == 0
    assert gp.read_bytes() == before


def test_hand_edited_graph_is_drift(tmp_path: Path):
    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    gp = graph_path(tmp_path, load_wiki_config(tmp_path))
    gp.write_text(gp.read_text(encoding="utf-8").replace("JWT", "JWT2"), encoding="utf-8")
    assert cmd_verify(tmp_path) == 1


def test_malformed_graph_yaml_is_drift_not_crash(tmp_path: Path):
    # 파싱은 되지만 map 이 아니거나 nodes/edges 가 map 이 아닌 형태 — _drifted_paths 가
    # AttributeError 를 내면 안 됨. 판별은 못 해도(빈 목록) drift 판정 자체는 유지됨.
    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    gp = graph_path(tmp_path, load_wiki_config(tmp_path))
    for bad in ("- a\n- b\n", "just text\n", "nodes: [a, b]\n", "edges: [x]\n"):
        gp.write_text(bad, encoding="utf-8")
        assert cmd_verify(tmp_path) == 1, f"crashed or passed on: {bad!r}"


def test_unreadable_graph_yaml_is_drift_not_crash(tmp_path: Path, capsys):
    # UnicodeDecodeError 를 내는 graph.yaml — 못 읽는 파일은 "최신"의 증거가 아니므로
    # 조용히 건너뛰지 않고 drift 로 보고해 block 해야 함.
    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    gp = graph_path(tmp_path, load_wiki_config(tmp_path))
    gp.write_bytes(b"\xff\xfe\xfd\xfc not valid utf-8")
    assert cmd_verify(tmp_path) == 1
    err = capsys.readouterr().err
    assert "graph.yaml" in err and "읽을 수 없습니다" in err


def test_verify_blocks_on_structure_violation(tmp_path: Path, capsys):
    # bad.md 를 build 뒤에 추가하기만 하면 drift 만으로 이미 exit 1 이 강제되어, 이 테스트는
    # validate_structure 호출을 지워도 통과해 버림 — bad.md 를 넣은 채로 rebuild 해서
    # drift 를 없앤 뒤에야 '구조 위반 때문에' 막혔다고 주장할 수 있음.
    _wiki_repo(tmp_path)
    _node(tmp_path, "docs/bad.md", "wiki_id: BAD\ntitle: Bad\n")
    _node(tmp_path, "docs/defects/skew.md", "wiki_id: defect.skew\ntitle: Skew\n")
    cmd_build(tmp_path)
    assert cmd_verify(tmp_path) == 1
    err = capsys.readouterr().err
    assert "BAD" in err and "형식" in err
    # validate_structure 는 validate_defects 를 이미 내부에서 구성함 — cmd_verify 가 둘
    # 다 부르면 defect 위반이 두 번 보고됨.
    affects_lines = [ln for ln in err.splitlines() if "defect 노드에는 affects" in ln]
    assert len(affects_lines) == 1


def test_warnings_alone_do_not_block(tmp_path: Path, capsys):
    _wiki_repo(tmp_path)
    _node(tmp_path, "docs/lonely.md", "wiki_id: lonely.x\ntitle: Lonely\n")
    cmd_build(tmp_path)
    assert cmd_verify(tmp_path) == 0
    assert "orphan" in capsys.readouterr().err


def test_noop_when_wiki_absent(tmp_path: Path, capsys):
    assert cmd_verify(tmp_path) == 0
    assert cmd_build(tmp_path) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_drift_message_names_the_drifted_node_only(tmp_path: Path, capsys):
    # '어긋났다'가 아니라 '어느 문서가 어긋났다'를 말해야 함. 아무 노드나 집으면
    # 무관한 파일을 지목해 오히려 오해를 키움.
    _wiki_repo(tmp_path)
    cmd_build(tmp_path)
    _node(tmp_path, "docs/auth/jwt.md", "wiki_id: auth.jwt\ntitle: JWT2\nrelated: [index]\n")
    assert cmd_verify(tmp_path) == 1
    err = capsys.readouterr().err
    assert "docs/auth/jwt.md" in err
    assert "docs/index.md" not in err


def test_drift_message_names_the_last_commit(tmp_path: Path, capsys):
    _wiki_repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seed"],
        cwd=tmp_path,
        check=True,
    )
    cmd_build(tmp_path)
    _node(tmp_path, "docs/auth/jwt.md", "wiki_id: auth.jwt\ntitle: JWT2\nrelated: [index]\n")
    assert cmd_verify(tmp_path) == 1
    assert "seed" in capsys.readouterr().err


def test_main_fails_open_on_internal_exception(tmp_path: Path, monkeypatch, capsys):
    # main() 의 exit code 가 곧 게이트의 판정 — 이 모듈 어디서든 나는 예외가 저장소를
    # 통째로 막으면 안 됨 (Invariant #1: wiki 는 missing-dependency·unclassified-commit·
    # merge-strategy 세 예외에 속하지 않음).

    monkeypatch.setattr(wiki_graph, "host_root", lambda: tmp_path)

    def _boom(root):
        raise RuntimeError("boom")

    monkeypatch.setattr(wiki_graph, "load_wiki_config", _boom)
    assert wiki_graph.main(["--verify"]) == 0
    assert "boom" in capsys.readouterr().err


def test_main_routes_an_empty_neighbors_id_to_the_lookup(tmp_path: Path, monkeypatch, capsys):
    # 진위값으로 갈랐더니 `--neighbors ""` 가 조용히 cmd_verify 로 떨어짐: 호출자는
    # 조회 결과가 비었다고 읽는 동안 실제로는 그래프 검증이 돌고 있었고, drift 면 1 을
    # 돌려줘 조회 실패로 보임. 종료 코드는 양쪽 다 1 이라 stderr 로만 구별됨.

    _wiki_repo(tmp_path)  # graph.yaml 을 만들지 않았으므로 verify 로 새면 drift 로 실패함
    monkeypatch.setattr(wiki_graph, "host_root", lambda: tmp_path)
    assert wiki_graph.main(["--neighbors", ""]) == 1
    err = capsys.readouterr().err
    assert "알 수 없는 id" in err
    assert "검증 실패" not in err


def test_main_argparse_error_still_exits_nonzero():
    # argparse 사용법 오류는 SystemExit 이라 finding 5 의 `except Exception` 가드를 그대로
    # 통과해야 함 — 게이트가 이 커맨드를 직접 구성하므로 실무에서는 발생하지 않지만,
    # 가드가 SystemExit 까지 삼켜버리는 회귀를 잡아 둠.

    with pytest.raises(SystemExit) as exc:
        wiki_graph.main([])
    assert exc.value.code == 2
