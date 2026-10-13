"""wiki 그래프 테스트가 공유하는 헬퍼 — 저장소·문서 세우기, 검증 호출.

노드 집합의 권위가 git 인덱스라서 헬퍼 대부분이 진짜 git 저장소를 세움.
"""

import re
import subprocess
from pathlib import Path

import pytest

from scripts import wiki_graph
from scripts.wiki_graph import (
    build_graph,
    cmd_build,
    validate_stamps,
    validate_structure,
)


def _write_config(root: Path, body: str) -> None:
    cfg = root / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "vdev-config.yaml").write_text(body, encoding="utf-8")


def _node(root: Path, rel: str, front: str, body: str = "본문\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{front}---\n\n{body}", encoding="utf-8")
    return p


def _mk(nid, front=None, path="docs/a.md"):
    front = {"wiki_id": nid, "title": "T", **(front or {})}
    return {"id": nid, "path": path, "line_count": 3, "front": front}


def _check(tmp_path: Path, nodes):
    wiki = {
        "root": "docs/",
        "index": "docs/index.md",
        "max_lines": 400,
        "context_lines": 2000,
        "defect_rule_threshold": 3,
    }
    return validate_structure(tmp_path, wiki, nodes, build_graph(nodes))


def _wiki(**over):
    base = {
        "root": "docs/",
        "index": "docs/index.md",
        "max_lines": 400,
        "context_lines": 2000,
        "defect_rule_threshold": 3,
    }
    base.update(over)
    return base


def _wiki_repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/index.md", "wiki_id: index\ntitle: Index\nrelated: [auth.jwt]\n")
    _node(tmp_path, "docs/auth/jwt.md", "wiki_id: auth.jwt\ntitle: JWT\nrelated: [index]\n")
    return tmp_path


def _sized(nid, front=None, path=None, lines=10):
    node = _mk(nid, front, path or f"docs/{nid}.md")
    node["line_count"] = lines
    return node


def _tracked_repo(tmp_path: Path, docs: dict[str, str], ignore: str = "") -> Path:
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    (tmp_path / "docs").mkdir(exist_ok=True)
    for rel, front in docs.items():
        _node(tmp_path, rel, front)
    if ignore:
        (tmp_path / ".gitignore").write_text(ignore, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seed"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _git_repo_with_source(tmp_path: Path, sha_slot: str) -> str:
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    # Special case: "null" should remain unquoted so YAML parses it as Python None
    if sha_slot == "null":
        front = f"wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: {sha_slot}\n"
    else:
        front = f'wiki_id: a.x\ntitle: A\nsources:\n  src/a.py: "{sha_slot}"\n'
    _node(tmp_path, "docs/a.md", front)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seed"],
        cwd=tmp_path,
        check=True,
    )
    # Returns the working-tree BLOB hash — the fresh value under cmd_stale's blob semantics.
    return subprocess.run(
        ["git", "hash-object", "--", "src/a.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _blob_of(root: Path, rel: str) -> str:
    return subprocess.run(
        ["git", "hash-object", "--", rel], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _stamp_repo(tmp_path: Path) -> Path:
    """repo + 커밋된 노드 1개(sources 에 working-tree blob 기록) + 매칭 graph.yaml."""
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    _write_config(root, "wiki:\n  enable: true\n  root: docs/\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    blob = _blob_of(root, "src/a.py")
    _node(root, "docs/index.md", "wiki_id: index\ntitle: Index\nrelated: [a]\n")
    _node(root, "docs/a.md", f"wiki_id: a\ntitle: A\nsources:\n  src/a.py: '{blob}'\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seed"],
        cwd=root,
        check=True,
    )
    # HEAD~1 이 존재하고 문서를 이미 들고 있게 커밋을 하나 더 둠 — 저장소의 평시 상태.
    # 루트 커밋에서는 도장 검사가 비교할 부모가 없어 fail-open 하므로, 아래 픽스처들이
    # 조용히 검증되지 않은 채로 통과해 버림.
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seed readme"],
        cwd=root,
        check=True,
    )
    return root


def _sha_in(doc: Path) -> str:
    m = re.search(r"'([0-9a-f]{7,40})'", doc.read_text(encoding="utf-8"))
    assert m is not None
    return m.group(1)


def _commit(root: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", message],
        cwd=root,
        check=True,
    )


def _renamed_nodes_repo(tmp_path: Path, count: int) -> Path:
    """노드 count 개를 전부 개명한 커밋 + 그 다음 sha 만 교체한 작업 트리."""
    root = _stamp_repo(tmp_path)
    blob = _blob_of(root, "src/a.py")
    ids = [f"n{i}" for i in range(count)]
    related = ", ".join(ids)
    _node(root, "docs/index.md", f"wiki_id: index\ntitle: Index\nrelated: [a, {related}]\n")
    for i in ids:
        _node(root, f"docs/{i}.md", f"wiki_id: {i}\ntitle: {i}\nsources:\n  src/a.py: '{blob}'\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    _commit(root, "docs: add nodes")
    for i in ids:
        subprocess.run(["git", "mv", f"docs/{i}.md", f"docs/r{i}.md"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert cmd_build(root) == 0
    _commit(root, "docs: rename them all")
    for i in ids:
        doc = root / "docs" / f"r{i}.md"
        doc.write_text(doc.read_text(encoding="utf-8").replace(blob, "b" * 40), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _count_git(root: Path, wiki, nodes, match) -> tuple[int, list[str]]:
    real = wiki_graph._git
    hits = {"n": 0}

    def counting(args, cwd):
        if match(args):
            hits["n"] += 1
        return real(args, cwd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiki_graph, "_git", counting)
        problems = validate_stamps(root, wiki, nodes)
    return hits["n"], problems


def _nodes_for_repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    _write_config(tmp_path, "wiki:\n  enable: true\n  root: docs/\n")
    _node(tmp_path, "docs/index.md", "wiki_id: index\ntitle: I\nrelated: [auth.jwt]\n")
    _node(
        tmp_path,
        "docs/jwt.md",
        "wiki_id: auth.jwt\ntitle: JWT\nsources:\n  src/auth/jwt.py: null\n",
    )
    return tmp_path


# ---------------------------------------------------------------- derive_wiki_id

# The canonical example set. `test_wiki_init_step5_table_is_parity_tested` asserts
# wiki-init §5's table EQUAL to it — one source, so the table cannot silently shrink.
_EXAMPLES = {
    "docs/code-style/python.md": "code-style.python",
    "docs/a.b.md": "a-b",
    "docs/a/b.md": "a.b",
    "docs/api_spec.md": "api-spec",
    "docs/sds/README.md": "sds.readme",
    "docs/onboarding/README.md": "onboarding.readme",
}


# ---------------------------------------------------------------- prose ↔ code parity

_REPO = Path(__file__).resolve().parents[2]
_TABLE_ROW_RE = re.compile(r"^\s*\|\s*`([^`]+\.md)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)
_ARROW_EXAMPLE_RE = re.compile(r"\b(docs/[^\s`]+?\.md)\s*(?:->|→)\s*([a-z0-9.-]+)")


# 읽는 파일은 wiki-init 의 SKILL.md 하나지만, 다른 skills/ 산문의 관례(들여쓴 펜스,
# 3-백틱을 감싸는 4-백틱 — skills/vdev·vdev-init)와 CommonMark 가 허용하는 `~~~` 까지
# 미리 덮음. 여는 울타리를 백레퍼런스로 되받으므로 안쪽 3-백틱은 4-백틱 블록을 닫지
# 못함. 닫는 들여쓰기는 절대 0–3 칸 또는 여는 쪽 +0–3 칸만 받음 — 리스트 안 펜스는
# 들여쓰기를 컨테이너 기준으로 재므로 절대 갈래만으로는 자기 짝을 못 닫고, 무제한이면 블록
# 안의 더 깊은 구분자 줄에서 조기 종료. 받는 닫기가 없으면 `\Z` 로 파일 끝까지 삼킴 —
# 덜 걷어내면 표 행이 새고, 과하게 걷어내면 표가 사라져 아래 assert 가 크게 터짐. 위 절들의
# 행동과 남은 CommonMark 괴리는 `_FENCE_CASES` 가 값으로 고정.
_FENCE_RE = re.compile(
    r"^([ \t]*)(`{3,}|~{3,}).*?(?:^(?:[ ]{0,3}|\1[ ]{0,3})\2|\Z)", re.MULTILINE | re.DOTALL
)


def _step5_section(text: str) -> str:
    """wiki-init SKILL.md 의 §5 본문, 펜스 코드블록을 걷어낸 것.

    표 정규식을 파일 전체에 풀어놓으면 다른 절의 같은 모양까지 끌어와 아래 중복 단언이
    오탐으로 터지고, 메시지는 원인을 오도함(그 경로는 §5 표에 중복으로 있지 않음).
    절로 좁히는 것만으로는 부족 — 펜스는 산문이 아니라 예시이므로, §5 안의 펜스가 표
    행 모양을 인용하면 같은 오탐이 되고, 컬럼 0 에서 `## 5.` 로 시작하는 펜스 줄은 헤딩
    분할까지 어긋냄.

    걷어내는 쪽의 비용 하나 — 표 *아래*에서 짝 없는 펜스 뒤에 붙은 행은 통째로 걷혀 케이스가
    되지 않음. wiki-init SKILL.md §5 의 "행을 더하면 케이스가 는다"가 성립하지 않는 유일한
    자리."""
    blocks = [
        b
        for b in re.split(r"^## ", _FENCE_RE.sub("", text), flags=re.MULTILINE)
        if b.startswith("5.")
    ]
    assert len(blocks) == 1, f"wiki-init SKILL.md 의 §5 블록이 {len(blocks)} 개다 (1 이어야)"
    return blocks[0]


# 위 테스트는 `_FENCE_RE` 를 태우지 않음 — 입력이 wiki-init 의 SKILL.md 하나뿐인데 그
# 파일의 펜스는 §5 바깥의 컬럼 0 3-백틱 쌍이라, 스트립을 통째로 걷어내도 rows=6 으로
# 통과. 정규식이 막는다고 선언한 형태는 여기서만 태워지므로, 새 형태를 막을 땐 케이스를 같이
# 늘려야 함. 각 케이스는 정규식의 한 절을 떨어뜨리면 깨짐. 라벨의 though 절은 그 읽기가
# CommonMark 와 갈린다는 표시 — 값을 고정해 둬야 바뀔 때 눈에 띄고, 그런 케이스도 절을
# 태움(어떤 절의 유일한 가드인 것도 있음).
_FENCE_IN = "| `docs/in.md` | `in` |"
_FENCE_KEEP = "| `docs/keep.md` | `keep` |"
_FENCE_CASES = [
    (f"   ```md\n   {_FENCE_IN}\n   ```\n\n{_FENCE_KEEP}\n", ["docs/keep.md"], "indented fence"),
    (f"~~~md\n{_FENCE_IN}\n~~~\n\n{_FENCE_KEEP}\n", ["docs/keep.md"], "tilde fence"),
    (
        f"````md\n```\n{_FENCE_IN}\n```\n````\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "four-backtick wrapper",
    ),
    (
        f"```text\n    ```\n{_FENCE_IN}\n```\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a delimiter indented 4 inside a fence does not close it",
    ),
    # 리스트로 감싸야 라벨이 기계장치대로임 — 최상위의 4칸 이상 여는 줄을 CommonMark 는
    # 펜스로 읽지 않아(빈 줄 뒤면 들여쓴 코드블록, 문단 뒤면 문단 연속) "닫는" 일 자체가 없음.
    (
        f"- item\n\n     ```bash\n     {_FENCE_IN}\n     ```\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a list-nested block indented past 3 closes itself",
    ),
    (
        f"  ```bash\n  {_FENCE_IN}\n```\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "an indented block closes at column 0",
    ),
    # 닫기가 절대 3칸 — 상대 갈래(5칸 요구)가 못 받아 절대 창의 상한을 태움. 하한은 위
    # 컬럼 0 케이스가 잡음.
    (
        f"- item\n\n     ```bash\n     {_FENCE_IN}\n   ```\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a list-nested block closes at a shallower absolute indent",
    ),
    # 행 단위 답은 우연히 일치 — 그 블록이 들여쓴 코드가 되어 행이 산문 밖인 것이지,
    # 펜스로 닫혀서가 아님. 닫기만 컬럼 0 으로 바꾸면 두 해석의 결과가 서로소.
    (
        f"\t```md\n\t{_FENCE_IN}\n\t```\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a tab-indented fence opens, though CommonMark reads it as an indented code block",
    ),
    (
        f"```md\n{_FENCE_IN}\n\t```\n\n{_FENCE_KEEP}\n",
        [],
        "a tab-indented delimiter does not close a space-opened fence",
    ),
    (
        f"prose ``` prose\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a backtick run away from line start opens nothing",
    ),
    (
        f"``a`` inline\n\n{_FENCE_KEEP}\n\n``b`` inline\n",
        ["docs/keep.md"],
        "an inline double-backtick run opens nothing",
    ),
    (
        f"~~struck~~ text\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a strikethrough run opens nothing",
    ),
    (
        f"````md\n```\n{_FENCE_IN}\n```\n\n{_FENCE_KEEP}\n",
        [],
        "an unclosed fence swallows to end of input, following rows included",
    ),
    (
        f"1. item\n\n   ```text\n   {_FENCE_IN}\n      ```\n\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a list-nested fence closes within 3 past its opening indent",
    ),
    # 바로 위와 같은 절대 좌표가 최상위에 오면 CommonMark 와 갈림 — 정규식은 컨테이너를
    # 모르므로 둘 다 닫음.
    (
        f"{_FENCE_KEEP}\n\n   ```text\n   | `docs/body.md` | `body` |\n      ```\n{_FENCE_IN}\n",
        ["docs/keep.md", "docs/in.md"],
        "a closer within 3 of the opening indent closes, though CommonMark reads it as content",
    ),
    (
        f"```md\n{_FENCE_IN}\n``` xyz\n{_FENCE_KEEP}\n",
        ["docs/keep.md"],
        "a closer with trailing text closes, though CommonMark reads on",
    ),
]
# 같은 입력이 다시 들어오면 라벨이 달라도 한쪽 커버리지는 허상 — 위에 한 줄 차이 쌍이
# 실제로 있음(4-백틱 래퍼 vs 그 미닫힘 변형).
assert len({doc for doc, _, _ in _FENCE_CASES}) == len(_FENCE_CASES)


# {{ID}} 를 안 쓰는 템플릿은 wiki_id 가 리터럴로 실려 있음 — 파생 규칙이 바뀌면 무음으로
# 표류하므로, 각 템플릿의 정본 출력 경로(주석·harness-authoring 규약)의 파생값과 대조.
_LITERAL_ID_TEMPLATES = {
    "docs-readme.template.md": "docs/README.md",
    "onboarding.template.md": "docs/onboarding/README.md",
}
