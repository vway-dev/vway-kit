"""호스트로 복사되는 스크립트가 python 3.8 에서 import 되는지 — 실행 시점에 평가되는 식만 잼.

호스트 스크립트의 하한은 3.8(`check-deps.sh`)이고 CI·개발 호스트는 3.12 라 `tuple[int, int]`
같은 내장 제네릭 첨자가 어디서도 안 깨짐. 3.8 은 그 식을 **평가하는 순간** `TypeError` 를 내고
모듈 import 가 통째로 죽음. `from __future__ import annotations` 아래의 주석은 문자열로 남아
평가되지 않으므로 대상 밖 — 모듈 수준 대입·기본값처럼 import 때 도는 식만 봄.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.vdev_init_setup import COPY_FILES

_ROOT = Path(__file__).resolve().parent.parent
_BUILTIN_GENERICS = {"tuple", "list", "dict", "set", "frozenset", "type"}


def _type_checking_nodes(tree: ast.Module) -> set[int]:
    """`if TYPE_CHECKING:` 본문의 노드 id — 런타임에 안 도는 블록(`doc_style_check.py` 의 방식)."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        test = getattr(node, "test", None)
        if isinstance(node, ast.If) and isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            for stmt in node.body:
                skip.update(id(n) for n in ast.walk(stmt))
    return skip


def _annotation_nodes(tree: ast.Module) -> set[int]:
    """평가되지 않는 주석 서브트리의 노드 id — future import 가 있을 때만 비움."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        roots = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            roots.append(node.returns)
            a = node.args
            roots += [x.annotation for x in a.posonlyargs + a.args + a.kwonlyargs]
            roots += [x.annotation for x in (a.vararg, a.kwarg) if x]
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
        for r in roots:
            if r is not None:
                skip.update(id(n) for n in ast.walk(r))
    return skip


def _runtime_generic_subscripts(src: str) -> list[int]:
    tree = ast.parse(src)
    postponed = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "__future__"
        and any(a.name == "annotations" for a in n.names)
        for n in tree.body
    )
    skip = _type_checking_nodes(tree) | (_annotation_nodes(tree) if postponed else set())
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Subscript)
        and isinstance(n.value, ast.Name)
        and n.value.id in _BUILTIN_GENERICS
        and id(n) not in skip
    ]


def test_detector_sees_a_module_level_alias_and_skips_postponed_annotations():
    src = (
        "from __future__ import annotations\n"
        "Core = tuple[int, int]\n"
        "def f(x: list[int]) -> dict[str, int]: ...\n"
    )
    assert _runtime_generic_subscripts(src) == [2]
    guarded = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    Core = tuple[int, int]\n"
    assert _runtime_generic_subscripts(guarded) == []


@pytest.mark.parametrize("rel", [r for r in COPY_FILES if r.endswith(".py")])
def test_host_script_has_no_runtime_builtin_generic(rel):
    lines = _runtime_generic_subscripts((_ROOT / rel).read_text(encoding="utf-8"))
    assert not lines, f"{rel}: 3.8 에서 import 가 죽는 내장 제네릭 첨자 — 줄 {lines}"
