"""stamp 게이트의 rename 경로와 git 호출 횟수 계약.

HEAD 에서 함께 옮겨진 문서는 통과하고, 경로만 바꾸며 sha 를 갈아끼운 것은 막음.
rename 조회와 부모 커밋 탐침은 **각각 한 번** — 노드마다 부르면 큰 저장소에서
훅이 타임아웃하고, 타임아웃은 조용히 건너뛴 게이트.
"""

import subprocess
from pathlib import Path

import pytest

from scripts import wiki_graph
from scripts.wiki_graph import (
    cmd_build,
    cmd_stale,
    cmd_verify,
    collect_nodes,
    load_wiki_config,
    validate_stamps,
)
from tests.wiki._helpers import (
    _blob_of,
    _commit,
    _count_git,
    _git_repo_with_source,
    _node,
    _renamed_nodes_repo,
    _sha_in,
    _stamp_repo,
)


def test_stamp_probes_head_liveness_once(tmp_path: Path):
    # 차단 경로에서 swap 마다 같은 HEAD 생존 프로브를 재실행하면 spawn 이 소스 수에
    # 비례해 낭비됨(문서 40×소스 3이면 120회) — 호출당 1회면 충분.
    root = _stamp_repo(tmp_path)
    (root / "src" / "b.py").write_text("y = 1\n", encoding="utf-8")
    doc = root / "docs" / "a.md"
    a_blob, b_blob = _sha_in(doc), _blob_of(root, "src/b.py")
    doc.write_text(
        f"---\nwiki_id: a\ntitle: A\nsources:\n  src/a.py: '{a_blob}'\n  src/b.py: '{b_blob}'\n"
        "---\n\n본문\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    _commit(root, "docs: two sources")
    (root / "other.txt").write_text("무관한 변경\n", encoding="utf-8")
    _commit(root, "chore: unrelated")
    text = doc.read_text(encoding="utf-8")
    doc.write_text(text.replace(a_blob, "b" * 40).replace(b_blob, "c" * 40), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    wiki = load_wiki_config(root)
    nodes = collect_nodes(root, wiki)

    real = wiki_graph._git
    probes: list[list[str]] = []

    def counting(args, cwd):
        if args == ["rev-parse", "--verify", "HEAD"]:
            probes.append(args)
        return real(args, cwd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", counting)
        problems = validate_stamps(root, wiki, nodes)
    assert len(problems) == 2  # swap 마다 문제 1건 — 차단 자체는 유지
    assert len(probes) == 1


def test_stamp_looks_up_renames_once_even_when_git_cannot_answer(tmp_path: Path):
    # renames 를 None 하나로 "아직 조회 안 함"과 "조회했는데 못 답함"에 겸용하면, 실패한
    # 조회가 rename 분기에 닿는 노드마다 되풀이됨 — `diff -M` 은 이 게이트가 던지는 가장
    # 비싼 질의이고 _git 타임아웃이 5초라 최악 N×5초가 커밋 훅 안에 들어앉음.
    root = _renamed_nodes_repo(tmp_path, 5)
    wiki = load_wiki_config(root)
    nodes = collect_nodes(root, wiki)
    real = wiki_graph._git

    def dead_rename_lookup(args, cwd):
        if args[0] == "diff" and "-M" in args:
            return None
        return real(args, cwd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", dead_rename_lookup)
        count, problems = _count_git(root, wiki, nodes, lambda a: a[0] == "diff" and "-M" in a)
    assert problems == []  # 답을 못 얻었으니 판정도 없음 (Invariant #1)
    assert count == 1


def test_stamp_probes_the_parent_commit_once(tmp_path: Path):
    # `rev-parse --verify HEAD~1` 의 답은 저장소 상수 — 노드마다 되물으면 HEAD 프로브에서
    # 없앤 낭비가 그대로 남음.
    root = _renamed_nodes_repo(tmp_path, 5)
    wiki = load_wiki_config(root)
    nodes = collect_nodes(root, wiki)
    count, problems = _count_git(
        root, wiki, nodes, lambda a: a == ["rev-parse", "--verify", "HEAD~1"]
    )
    assert len(problems) == 5  # 순수 개명이므로 차단은 그대로
    assert count == 1


def test_head_renames_fails_open_on_a_truncated_record(tmp_path: Path):
    # 잘린 레코드를 건너뛰면 결과가 {} 가 되고, 그것은 "개명이 없다"는 **판정**이라
    # 정당한 개명+동기화를 차단으로 몰 수 있음. 읽을 수 없는 출력은 판정이 아님.
    # 정상 출력은 언제나 NUL 로 끝남(A/D/M/T/R 전부, 공백·한글 경로 포함) — `_git` 의
    # .strip() 은 NUL 을 안 지우므로('\0'.isspace() 가 False) 종료자가 그대로 남음.
    # 케이스 표는 순서 있는 목록이지 맵이 아님. 다만 dict 리터럴의 중복 키는 ruff F601 이
    # 공짜로 잡아주고 리스트에는 그 그물이 없으므로, 잃는 보호를 아래 단언으로 되돌림.
    cases = [
        ("R100\0docs/old.md\0docs/new.md\0", {"docs/new.md": "docs/old.md"}),
        ("M\0docs/a.md\0R100\0docs/old.md\0docs/new.md\0", {"docs/new.md": "docs/old.md"}),
        ("M\0docs/a.md\0", {}),  # 완결된 출력 — 개명이 없다는 정당한 판정
        ("", {}),  # 변경 없음
        ("R100\0docs/old.md", None),  # 레코드가 통째로 모자람
        ("M\0docs/a", None),  # 필드 중간에서 잘림 — 길이는 맞아 보임
        ("R100\0docs/old.md\0", None),  # NUL 경계에서 잘려 새 경로가 빈 문자열
        ("M\0docs/a.md\0R100\0", None),  # 앞은 온전하고 마지막 레코드만 모자람
        ("M\0", None),  # 2필드 레코드도 마찬가지 — 경로 자리가 종료자임
        ("M\0docs/a.md\0D\0", None),  # 마지막 2필드 레코드만 경로를 잃음
        # 빈 status 는 맨 끝(종료자)에서만 정상. 중간에 있으면 손상된 출력이고, 거기서
        # 멈추면 뒤따르는 개명을 조용히 버려 역시 "개명 없음" 판정이 됨.
        ("M\0docs/a.md\0\0R100\0docs/o.md\0docs/n.md\0", None),
    ]
    assert len({out for out, _ in cases}) == len(cases)  # 입력 중복은 케이스 소실임
    real = wiki_graph._git
    with pytest.MonkeyPatch.context() as mp:
        for out, expected in cases:
            mp.setattr(wiki_graph, "_git", lambda a, c, _o=out: _o)
            assert wiki_graph._head_renames(tmp_path, "docs") == expected, repr(out)
    assert wiki_graph._git is real


def test_head_renames_ignores_a_copy_record(tmp_path: Path):
    # C 는 원본을 남김 — 도장을 미룬 문서는 *이동한* 원본을 타므로 복사를 개명으로 읽으면
    # 그대로 있는 파일의 본문과 비교하게 됨. `-M` 만 넘기므로 git 이 C 를 낼 일은 없지만
    # (명시적 `-M` 은 `diff.renames=copies` 를 renames-only 로 덮으므로 — `-M` 이 없으면 그
    # 설정만으로 C 가 나올 수 있음 — `-M` 을 준 이상 복사 탐지를 켤 길은 명령줄 `-C`/
    # `--find-copies-harder` 뿐임. git 2.47.1 실측), 파서가 그 보장에 기대지는 않음.
    real = wiki_graph._git
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", lambda a, c: "C100\0docs/src.md\0docs/copy.md\0")
        assert wiki_graph._head_renames(tmp_path, "docs") == {}
        # 3필드를 소비하는 것 자체는 맞음 — 안 그러면 뒤 레코드가 어긋남.
        mp.setattr(
            wiki_graph,
            "_git",
            lambda a, c: "C100\0docs/src.md\0docs/copy.md\0R100\0docs/o.md\0docs/n.md\0",
        )
        assert wiki_graph._head_renames(tmp_path, "docs") == {"docs/n.md": "docs/o.md"}
    assert wiki_graph._git is real


def test_stamp_new_file_passes(tmp_path: Path):
    # HEAD 에 없는 새 문서의 최초 도장은 자유 (저작 자체가 동기화).
    root = _stamp_repo(tmp_path)
    _node(
        root,
        "docs/b.md",
        "wiki_id: b\ntitle: B\nrelated: [index]\nsources:\n  src/a.py: '" + "c" * 40 + "'\n",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 0


def test_stamp_check_sees_non_ascii_paths(tmp_path: Path, capsys):
    # 기본 core.quotePath 아래서 `git diff --name-only` 는 한글 경로를 C-escape 로 인용해
    # 반환함 — -z 없이는 그런 문서가 도장 검사에서 조용히 빠짐 (_candidate_files 의
    # "-z is mandatory" 와 같은 footgun).
    root = _stamp_repo(tmp_path)
    doc = root / "docs" / "한글노트.md"
    blob = _blob_of(root, "src/a.py")
    _node(
        root,
        "docs/한글노트.md",
        f"wiki_id: ko\ntitle: K\nrelated: [index]\nsources:\n  src/a.py: '{blob}'\n",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "ko node"],
        cwd=root,
        check=True,
    )
    doc.write_text(doc.read_text(encoding="utf-8").replace(blob, "b" * 40), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 1
    assert "한글노트" in capsys.readouterr().err


def test_stamp_allows_entry_add_remove_and_null_fill(tmp_path: Path):
    # missing-path 해소(항목 삭제)·새 소스 추가·null→sha 최초 등록은 본문 편집 없이도
    # 정당함 — 이 guard 가 사라지면 정당한 커밋이 오차단됨.
    root = _stamp_repo(tmp_path)
    doc = root / "docs" / "a.md"
    blob = _sha_in(doc)
    (root / "src" / "b.py").write_text("y = 1\n", encoding="utf-8")
    front = f"---\nwiki_id: a\ntitle: A\nsources:\n  src/a.py: '{blob}'\n  src/b.py: null\n"
    doc.write_text(front + "---\n\n본문\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    assert cmd_verify(root) == 0  # 항목 추가 (null 등록)
    b_blob = _blob_of(root, "src/b.py")
    doc.write_text(doc.read_text(encoding="utf-8").replace("null", f"'{b_blob}'"), encoding="utf-8")
    assert cmd_verify(root) == 0  # null→sha 최초 등록 (graph 는 키만 실으므로 재빌드 불필요)
    doc.write_text(
        f"---\nwiki_id: a\ntitle: A\nsources:\n  src/a.py: '{blob}'\n---\n\n본문\n",
        encoding="utf-8",
    )
    assert cmd_build(root) == 0  # 키 집합이 줄었으므로 graph 재빌드
    assert cmd_verify(root) == 0  # 항목 삭제


def test_stale_batches_hash_object(tmp_path: Path, monkeypatch):
    # Windows 에서 프로세스 spawn 이 제일 비쌈 — 경로가 몇 개든 hash-object 는 1회.
    _git_repo_with_source(tmp_path, "null")
    (tmp_path / "src" / "b.py").write_text("y = 1\n", encoding="utf-8")
    (tmp_path / "src" / "c.py").write_text("z = 1\n", encoding="utf-8")
    _node(
        tmp_path,
        "docs/a.md",
        "wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: null\n  src/b.py: null\n  src/c.py: null\n",
    )
    calls: list[str] = []
    real = wiki_graph._git

    def spy(args, cwd):
        calls.append(args[0])
        return real(args, cwd)

    monkeypatch.setattr(wiki_graph, "_git", spy)
    assert cmd_stale(tmp_path) == 0
    assert calls.count("hash-object") == 1
