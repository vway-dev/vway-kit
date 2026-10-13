"""`derive_wiki_id` 와 `--derive-id` CLI.

경로에서 id 를 만드는 규칙 하나가 스킬과 스크립트 양쪽의 SSOT. 루트 접두는
선택이고 세그먼트 경계로 맞춤.
"""

from pathlib import Path

import pytest

from scripts import wiki_graph
from tests.wiki._helpers import (
    _EXAMPLES,
    _write_config,
)


def test_derive_wiki_id_examples():
    for path, expected in _EXAMPLES.items():
        assert wiki_graph.derive_wiki_id(path) == expected, path


def test_derive_wiki_id_root_prefix_is_optional():
    # `--derive-id docs/a.md` 와 `--derive-id a.md --root docs/` 는 같은 호출.
    assert wiki_graph.derive_wiki_id("a.b.md", "docs") == "a-b"
    assert wiki_graph.derive_wiki_id("docs/a.b.md", "docs/") == "a-b"


def test_derive_wiki_id_root_prefix_matches_segment_boundary():
    # docs-old/ 는 root docs 의 접두가 아님 (불변식 7 의 path-prefix footgun 과 동형).
    assert wiki_graph.derive_wiki_id("docs-old/a.md", "docs") == "docs-old.a"


def test_derive_wiki_id_windows_separators():
    assert wiki_graph.derive_wiki_id("docs\\sds\\README.md", "docs") == "sds.readme"


def test_derive_wiki_id_rejects_degenerate_segment():
    # 한글만인 이름은 정규화 후 남는 글자가 없음 — 방출하면 한글 문서 둘부터
    # duplicate-id 로 커밋이 막히므로 (이 기능이 없애려는 증상) 원천 거부.
    with pytest.raises(ValueError, match="영문"):
        wiki_graph.derive_wiki_id("docs/온보딩.md", "docs")


def test_derive_wiki_id_rejects_root_itself_and_empty():
    with pytest.raises(ValueError):
        wiki_graph.derive_wiki_id("docs", "docs")
    with pytest.raises(ValueError):
        wiki_graph.derive_wiki_id("", "docs")


def test_wiki_root_hint_ignores_the_enable_gate(tmp_path: Path):
    # enable: false 여도 root 는 존중 — /harness-init 은 /wiki-init 전에 돌 수 있음
    # (harness-rules 8-2). load_wiki_config 를 거치면 None 이라 조용히 docs 로 파생함.
    _write_config(tmp_path, "wiki:\n  enable: false\n  root: documentation/\n")
    assert wiki_graph._wiki_root_hint(tmp_path) == "documentation"


def test_wiki_root_hint_fails_soft_to_docs(tmp_path: Path):
    assert wiki_graph._wiki_root_hint(tmp_path) == "docs"  # config 없음
    _write_config(tmp_path, "wiki: [broken\n")
    assert wiki_graph._wiki_root_hint(tmp_path) == "docs"  # 파싱 불가


def test_derive_id_cli_prints_tab_pairs(capsys):
    # 위치 zip 이 아니라 경로<TAB>id 쌍 — 부분 실패 시 줄 밀림으로 조용히 어긋나지 않게.
    rc = wiki_graph.main(["--derive-id", "docs/a/b.md", "docs/a.b.md", "--root", "docs"])
    assert rc == 0
    assert capsys.readouterr().out.splitlines() == ["docs/a/b.md\ta.b", "docs/a.b.md\ta-b"]


def test_derive_id_cli_partial_failure_names_the_path(capsys):
    rc = wiki_graph.main(["--derive-id", "docs/ok.md", "docs/온보딩.md", "--root", "docs"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "docs/ok.md\tok" in captured.out  # 성공분은 그대로 나감
    assert "온보딩" in captured.err  # 실패분은 경로를 지목함


def test_derive_id_cli_reads_config_root(tmp_path: Path, monkeypatch, capsys):
    _write_config(tmp_path, "wiki:\n  enable: false\n  root: documentation/\n")
    monkeypatch.setattr(wiki_graph, "host_root", lambda: tmp_path)
    rc = wiki_graph.main(["--derive-id", "documentation/api_spec.md"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "documentation/api_spec.md\tapi-spec"


def test_derive_id_cli_respects_an_explicit_empty_root(tmp_path: Path, monkeypatch, capsys):
    # `--root ""` is an explicit choice the caller typed, not "no --root given". Branching
    # on truthiness would silently fall back to the config/default root instead — the same
    # footgun `main()` already guards against for `--neighbors ""` (`is not None` there too).
    # With no root to strip, "docs/a.md" derives as "docs.a", not the "a" a default root
    # of "docs" would produce — that difference is what proves the empty root was honored.
    monkeypatch.setattr(wiki_graph, "host_root", lambda: tmp_path)
    rc = wiki_graph.main(["--derive-id", "docs/a.md", "--root", ""])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "docs/a.md\tdocs.a"


def test_derive_id_is_not_swallowed_by_fail_open(monkeypatch):
    # --derive-id 는 게이트 명령이 아님 — 내부 예외가 fail-open 으로 exit 0 이 되면
    # "출력 없는 성공"이고, 호출자는 손 파생으로 회귀 (이 명령이 없애려는 실패 모드).
    def _boom(paths, root_arg):
        raise RuntimeError("boom")

    monkeypatch.setattr(wiki_graph, "cmd_derive_id", _boom)
    with pytest.raises(RuntimeError):
        wiki_graph.main(["--derive-id", "docs/a.md"])
