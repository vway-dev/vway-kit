"""source sha 신선도 — 문서가 가리키는 코드가 그 뒤로 움직였는가.

빈 sha·YAML 이 숫자로 강제한 sha·사라진 커밋 각각이 다른 답을 낳음. 조용히
비교되면 낡은 문서가 신선하다고 보고됨.
"""

import json
import subprocess
from pathlib import Path

from scripts.wiki_graph import (
    build_graph,
    cmd_stale,
    collect_nodes,
    load_wiki_config,
    validate_structure,
)
from tests.wiki._helpers import (
    _blob_of,
    _check,
    _git_repo_with_source,
    _node,
    _write_config,
)


def test_empty_recorded_sha_is_still_reported_stale(tmp_path: Path, capsys):
    # `src/a.py: ""` — what a hand-edit (or an LLM meaning "unknown") produces instead of null.
    # `current.startswith("")` is unconditionally true, so the node reported fresh forever and
    # doc-sync Mode W, which runs entirely off --stale, never revisited it again.
    _git_repo_with_source(tmp_path, "")
    assert cmd_stale(tmp_path) == 0
    rep = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in rep] == ["a.x"]
    assert rep[0]["recorded"] is None


def test_yaml_coerced_sha_is_reported_not_silently_compared(tmp_path: Path):
    # `commit: 0123456` is YAML 1.1 octal → int 42798. Left uncaught, the message names a number
    # the author never typed ("commit '42798' 은 hex 7~40자가 아닙니다") and the fix is
    # undiscoverable; as a sources value it makes the node stale forever.
    import yaml as _yaml

    assert _yaml.safe_load("commit: 0123456") == {"commit": 42798}  # the coercion is real
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/a.md", "wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: 0123456\n")
    wiki = load_wiki_config(tmp_path)
    nodes = collect_nodes(tmp_path, wiki)
    problems = validate_structure(tmp_path, wiki, nodes, build_graph(nodes))
    assert any("따옴표" in p and "int" in p for p in problems)


def test_yaml_coerced_title_is_not_reported_as_missing(tmp_path: Path):
    # `title: no` parses to False. Truthiness read that as absent and blocked with
    # "필수 필드 title 이 없습니다" on a document whose title is right there.
    node = {"id": "a.x", "path": "docs/a.md", "front": {"wiki_id": "a.x", "title": False}}
    node["line_count"] = 3
    problems = _check(tmp_path, [node])
    assert not any("title 이 없습니다" in p for p in problems)
    assert any("따옴표" in p and "bool" in p for p in problems)


def test_missing_source_path_is_flagged_in_stale(tmp_path: Path, capsys):
    # git log answers for a deleted path, so a moved file reads as an ordinary sha drift
    # unless stale flags it: doc-sync stamps the new sha and --verify's
    # "sources 경로 … 가 없습니다" block stays.
    _git_repo_with_source(tmp_path, "null")
    subprocess.run(["git", "mv", "src/a.py", "src/b.py"], cwd=tmp_path, check=True)
    assert cmd_stale(tmp_path) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["missing"] is True and entry["current"] is None


def test_matching_sha_is_not_stale(tmp_path: Path, capsys):
    sha = _git_repo_with_source(tmp_path, "PLACEHOLDER")
    _node(tmp_path, "docs/a.md", f'wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: "{sha}"\n')
    assert cmd_stale(tmp_path) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_short_sha_prefix_matches(tmp_path: Path, capsys):
    sha = _git_repo_with_source(tmp_path, "PLACEHOLDER")
    _node(tmp_path, "docs/a.md", f'wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: "{sha[:7]}"\n')
    assert cmd_stale(tmp_path) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_outdated_sha_is_stale(tmp_path: Path, capsys):
    _git_repo_with_source(tmp_path, "0000000")
    assert cmd_stale(tmp_path) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["id"] == "a.x" and entry["source"] == "src/a.py"
    assert entry["recorded"] == "0000000"


def test_null_sha_is_stale_as_a_new_source(tmp_path: Path, capsys):
    _git_repo_with_source(tmp_path, "null")
    assert cmd_stale(tmp_path) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["recorded"] is None


def test_stale_blob_recorded_fresh_and_stale(tmp_path: Path, capsys):
    # 기록 값 = working tree blob → fresh. 파일 내용이 바뀌면(커밋 불필요) stale — 판정이
    # 커밋 이력이 아니라 내용에 붙음 (squash/rebase 승격이 가짜 stale 을 못 만듦).
    _git_repo_with_source(tmp_path, "PLACEHOLDER")
    blob = _blob_of(tmp_path, "src/a.py")
    _node(tmp_path, "docs/a.md", f'wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: "{blob}"\n')
    assert cmd_stale(tmp_path) == 0
    assert json.loads(capsys.readouterr().out) == []
    (tmp_path / "src" / "a.py").write_text("changed = True\n", encoding="utf-8")
    assert cmd_stale(tmp_path) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["recorded"] == blob and entry["current"] != blob
    assert "migrated" not in entry


def test_stale_commit_recorded_offers_migration(tmp_path: Path, capsys):
    # 구형 기록(커밋 sha) → migrated == `git rev-parse <커밋>:<경로>` (그 시점 blob).
    # 내용 무변경이어도 항목이 나옴 — doc-sync 가 마커만 재작성해 저장소가 수렴하도록.
    _git_repo_with_source(tmp_path, "PLACEHOLDER")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    want = subprocess.run(
        ["git", "rev-parse", f"{head}:src/a.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    _node(tmp_path, "docs/a.md", f'wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: "{head}"\n')
    assert cmd_stale(tmp_path) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["migrated"] == want


def test_stale_vanished_commit_migrates_to_null(tmp_path: Path, capsys):
    # GC 로 사라진 커밋(타입 조회 불가) → migrated: null — 일반 stale 로 본문 동기화 대상.
    _git_repo_with_source(tmp_path, "f" * 40)
    assert cmd_stale(tmp_path) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["migrated"] is None
