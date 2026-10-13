"""stamp 게이트 — sha 만 바꾼 커밋은 막음.

본문을 안 고치고 sha 만 갱신하는 것은 '문서를 봤다'는 거짓 증거. git 이 답을 못 하는
경우(루트 커밋·읽기 실패)는 전부 FAIL-OPEN.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import wiki_graph
from scripts.wiki_graph import (
    cmd_build,
    cmd_verify,
    collect_nodes,
    load_wiki_config,
    validate_stamps,
)
from tests.wiki._helpers import (
    _blob_of,
    _commit,
    _node,
    _nodes_for_repo,
    _sha_in,
    _stamp_repo,
)


def test_stamp_only_change_blocks(tmp_path: Path, capsys):
    root = _stamp_repo(tmp_path)
    doc = root / "docs" / "a.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0  # graph 는 일치시켜 도장 위반만 남김
    assert cmd_verify(root) == 1
    assert "본문 변경이 없습니다" in capsys.readouterr().err


def test_stamp_with_body_edit_passes(tmp_path: Path):
    root = _stamp_repo(tmp_path)
    doc = root / "docs" / "a.md"
    text = doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40)
    doc.write_text(text + "\n갱신된 설명.\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 0


def test_stamp_migration_rewrite_passes(tmp_path: Path):
    # old 가 커밋 sha, new == `git rev-parse <old>:<src>` → 의미보존 재작성 허용.
    root = _stamp_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    doc = root / "docs" / "a.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(_sha_in(doc), head), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "legacy marker"],
        cwd=root,
        check=True,
    )
    blob_at_head = subprocess.run(
        ["git", "rev-parse", f"{head}:src/a.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    doc.write_text(doc.read_text(encoding="utf-8").replace(head, blob_at_head), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 0


def test_stamp_allowed_when_head_carries_the_body_edit(tmp_path: Path):
    # 차단 메시지가 권하는 amend 경로 그 자체 — 본문 동기화를 이미 커밋했다면 HEAD 는 그
    # 본문을 들고 있으므로 남은 델타는 sha 뿐임. 이것을 막으면 권고안이 실행 불가가 되고,
    # split-commit(본문 커밋 → 도장 커밋)도 같은 모양이라 함께 열림.
    root = _stamp_repo(tmp_path)
    doc = root / "docs" / "a.md"
    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("본문", "코드에 맞춰 갱신한 본문"),
        encoding="utf-8",
    )
    _commit(root, "docs: sync the body, stamp not yet applied")
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), _blob_of(root, "src/a.py")),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 0


def test_stamp_still_blocks_when_head_body_is_unchanged(tmp_path: Path):
    # 위 허용이 검사를 통째로 열어버리지 않는지 — 직전 커밋이 그 문서의 본문을 건드리지
    # 않았다면 도장만 찍는 커밋은 여전히 차단.
    root = _stamp_repo(tmp_path)
    (root / "other.txt").write_text("무관한 변경\n", encoding="utf-8")
    _commit(root, "chore: touch an unrelated file")
    doc = root / "docs" / "a.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 1


def test_stamp_fails_open_when_git_cannot_answer(tmp_path: Path):
    # rev-parse 가 답하지 못하는 상황(타임아웃 등)은 판정이 아니라 내부 오류 — Invariant #1
    # 은 그런 커밋을 통과시키라고 요구함. "객체가 없다"는 정당한 nonzero 와 구별해야 하므로
    # git 생존 확인이 실패할 때에만 열림.
    root = _stamp_repo(tmp_path)
    doc = root / "docs" / "a.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    wiki = load_wiki_config(root)
    nodes = collect_nodes(root, wiki)
    assert validate_stamps(root, wiki, nodes)  # 평시에는 차단

    real = wiki_graph._git

    def dying_git(args, cwd):
        if args[0] in ("rev-parse", "cat-file"):
            return None  # git 이 더 이상 답하지 못함
        return real(args, cwd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", dying_git)
        assert validate_stamps(root, wiki, nodes) == []


def test_stamp_fails_open_on_a_root_commit(tmp_path: Path):
    # 부모가 없으면 "직전 커밋이 이 본문을 동기화했는가"를 물을 수 없음 — 판정 불가는 통과.
    root = _stamp_repo(tmp_path)
    subprocess.run(["git", "reset", "-q", "--soft", "HEAD~1"], cwd=root, check=True)
    doc = root / "docs" / "a.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 0


def test_nodes_for_finds_a_directory_source_from_a_file(tmp_path: Path, capsys):
    # /vdev 는 바뀐 파일 경로를 넘김 — 디렉터리를 문서화한 노드가 그 조회에서 빠지면
    # 결과가 빈 줄이고, 호출자는 그것을 "미문서화"로 읽음.
    root = _nodes_for_repo(tmp_path)
    _node(root, "docs/authdir.md", "wiki_id: auth.dir\ntitle: D\nsources:\n  src/auth: null\n")
    assert wiki_graph.cmd_nodes_for(root, ["src/auth/jwt.py"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert sorted(out) == ["src/auth/jwt.py\tauth.dir", "src/auth/jwt.py\tauth.jwt"]


def test_nodes_for_directory_source_keeps_the_segment_boundary(tmp_path: Path, capsys):
    # 대칭 매칭의 이 방향에도 세그먼트 경계가 살아 있어야 함 — `src/auth` 노드가
    # 형제 디렉터리 `src/auth-x/` 의 파일에 걸리면 조회가 남의 문서를 끌어옴.
    root = _nodes_for_repo(tmp_path)
    _node(root, "docs/authdir.md", "wiki_id: auth.dir\ntitle: D\nsources:\n  src/auth: null\n")
    assert wiki_graph.cmd_nodes_for(root, ["src/auth-x/jwt.py"]) == 0
    assert capsys.readouterr().out == ""


def test_stamp_still_blocks_a_document_introduced_by_head(tmp_path: Path):
    # HEAD~1 은 읽히는데 그 문서만 없음 = HEAD 가 문서를 신설한 경우. 신설 커밋은 자기
    # 도장을 이미 들고 있으므로 그 다음 커밋의 sha 교체는 동기화가 아님 — 차단 유지.
    root = _stamp_repo(tmp_path)
    blob = _blob_of(root, "src/a.py")
    _node(
        root,
        "docs/b.md",
        f"wiki_id: b\ntitle: B\nrelated: [index]\nsources:\n  src/a.py: '{blob}'\n",
    )
    _commit(root, "docs: add a second node")
    doc = root / "docs" / "b.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(blob, "b" * 40), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 1


def test_stamp_allows_a_rename_synced_in_head(tmp_path: Path):
    # rename+본문 동기화가 한 커밋에 있고 도장이 다음 커밋(또는 amend)이면 HEAD~1 에는
    # 새 경로가 없음 — 그것을 "신설"로 단정하면 그 동기화를 못 보고, 차단 메시지가 권하는
    # amend·rebase/fixup 까지 막음. diff -M 으로 이전 경로를 되짚어 본문 비교를 이어감.
    root = _stamp_repo(tmp_path)
    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    subprocess.run(["git", "mv", "docs/a.md", "docs/alpha.md"], cwd=root, check=True)
    doc = root / "docs" / "alpha.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("본문", "코드에 맞춰 갱신한 본문"),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    _commit(root, "docs: rename and sync the body, stamp deferred")
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), _blob_of(root, "src/a.py")),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_verify(root) == 0


def test_stamp_still_blocks_a_pure_rename_with_sha_swap(tmp_path: Path):
    # 이동만으로는 어떤 소스도 동기화되지 않음 — rename 허용이 sha 세탁 통로가 되면 안 됨.
    root = _stamp_repo(tmp_path)
    subprocess.run(["git", "mv", "docs/a.md", "docs/alpha.md"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    _commit(root, "docs: pure rename, nothing synced")
    doc = root / "docs" / "alpha.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_verify(root) == 1


def test_stamp_fails_open_when_the_parent_read_flakes(tmp_path: Path):
    # HEAD~1:<path> 본문 읽기만 실패하고(타임아웃 등) 객체 조회는 살아 있는 상황 — "부모에
    # 그 문서가 없다"는 판정이 아니므로 차단 흐름으로 이어지면 Invariant #1 위반.
    root = _stamp_repo(tmp_path)
    (root / "other.txt").write_text("무관한 변경\n", encoding="utf-8")
    _commit(root, "chore: touch an unrelated file")
    doc = root / "docs" / "a.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    wiki = load_wiki_config(root)
    nodes = collect_nodes(root, wiki)
    assert validate_stamps(root, wiki, nodes)  # 평시에는 차단

    real = wiki_graph._git
    target = "HEAD~1:docs/a.md"

    def flaky_parent_read(args, cwd):
        if args[-1] == target and args != ["rev-parse", "--verify", target]:
            return None  # 본문 읽기(show/cat-file)만 죽고 객체 조회는 답함
        return real(args, cwd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", flaky_parent_read)
        assert validate_stamps(root, wiki, nodes) == []


def test_stamp_fails_open_when_the_rename_lookup_fails(tmp_path: Path):
    # 부모에 경로가 없어 rename 을 물어야 하는데 diff 가 답하지 못하면 신설/개명을 가를 수
    # 없음 — 판정 불가는 통과 (Invariant #1).
    root = _stamp_repo(tmp_path)
    subprocess.run(["git", "mv", "docs/a.md", "docs/alpha.md"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    _commit(root, "docs: pure rename")
    doc = root / "docs" / "alpha.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(_sha_in(doc), "b" * 40), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    wiki = load_wiki_config(root)
    nodes = collect_nodes(root, wiki)

    real = wiki_graph._git

    def no_rename_answer(args, cwd):
        if args[0] == "diff" and "HEAD~1" in args:
            return None
        return real(args, cwd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", no_rename_answer)
        assert validate_stamps(root, wiki, nodes) == []


def test_stamp_fails_open_when_the_parent_path_was_a_tree(tmp_path: Path):
    # 부모 커밋에서 같은 경로가 디렉터리였다면 `git show` 는 tree 목록을 exit 0 으로 내
    # "본문이 다르다"로 오독됨. cat-file blob 은 tree 에서 실패하고, 객체 존재 확인이
    # 그 실패를 "부모에 문서가 없다"와 갈라 통과시킴 (Invariant #1).
    # 통과 여부만 보면 `show` 경로도 (다른 이유로) 통과하므로, 이 테스트가 고정하는
    # 것은 결과가 아니라 **경유한 질의** — 객체 존재 확인이 실제로 일어나야 함.
    root = _stamp_repo(tmp_path)
    d = root / "docs" / "x.md"
    d.mkdir()
    (d / "inner.txt").write_text("i\n", encoding="utf-8")
    _commit(root, "docs: x.md is a directory here")
    shutil.rmtree(d)
    blob = _blob_of(root, "src/a.py")
    _node(
        root,
        "docs/x.md",
        f"wiki_id: x\ntitle: X\nrelated: [index]\nsources:\n  src/a.py: '{blob}'\n",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    _commit(root, "docs: x.md becomes a node")
    doc = root / "docs" / "x.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(blob, "b" * 40), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    wiki = load_wiki_config(root)
    nodes = collect_nodes(root, wiki)

    real = wiki_graph._git
    seen: list[list[str]] = []

    def recording(args, cwd):
        seen.append(args)
        return real(args, cwd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", recording)
        assert validate_stamps(root, wiki, nodes) == []
    assert ["cat-file", "blob", "HEAD~1:docs/x.md"] in seen
    assert ["rev-parse", "--verify", "HEAD~1:docs/x.md"] in seen
