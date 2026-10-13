"""플랜의 `wiki_id` 는 경로에서 도출한 값과 같아야 함.

손으로 적은 id 는 경로와 어긋나는 순간 그래프가 두 개의 진실을 가짐. defect id 만
예외 — 그쪽은 경로가 아니라 결함을 가리킴.
"""

import scripts.harness_scaffold as hs
from tests.harness._helpers import (
    _wiki_plan,
    _write_wiki_config,
)


def test_validate_plan_flags_hand_derived_wiki_id(tmp_path):
    # 손 파생이 기계 파생과 어긋나면 나중에 duplicate/format 으로 --verify 가 모든 커밋을
    # 막음 — plan 시점에 잡는 유일한 강제점.
    content = "---\nwiki_id: code-style-python\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/code-style/python.md", content))
    hits = [i for i in res["issues"] if i["kind"] == "wiki-id"]
    assert hits and "code-style.python" in hits[0]["detail"]


def test_validate_plan_accepts_the_derived_wiki_id(tmp_path):
    content = "---\nwiki_id: code-style.python\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/code-style/python.md", content))
    assert not any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_exempts_defect_ids_from_path_parity(tmp_path):
    # defect 문서의 wiki_id 는 defect-template 의 `defect.<slug>` 관례를 따름(wiki-init §5
    # 명시) — 경로 파생이 아니므로 패리티 검사가 high 로 오탐하면 안 됨.
    content = "---\nwiki_id: defect.login-timeout\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/defects/login-timeout.md", content))
    assert not any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_flags_unfilled_id_placeholder(tmp_path):
    # {{ID}} 를 안 채운 템플릿 복제도 같은 검사에 걸림.
    content = "---\nwiki_id: '{{ID}}'\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/sds/README.md", content))
    assert any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_ignores_md_outside_wiki_root(tmp_path):
    content = "---\nwiki_id: totally-wrong\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan(".claude/rules/x-conventions.md", content))
    assert not any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_ignores_docs_without_wiki_id(tmp_path):
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/guide.md", "본문만\n"))
    assert not any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_flags_boolean_wiki_id(tmp_path):
    # YAML 1.1: an unquoted `no` resolves to the bool False, not the string "no". Left
    # unflagged this reads as "no wiki_id" and the parity check silently never runs.
    content = "---\nwiki_id: no\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/guide.md", content))
    hits = [i for i in res["issues"] if i["kind"] == "wiki-id"]
    assert hits and "bool" in hits[0]["detail"]


def test_validate_plan_flags_numeric_wiki_id(tmp_path):
    # YAML 1.1: an unquoted leading-zero scalar resolves to an (octal) int, not a string.
    content = "---\nwiki_id: 0123456\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/guide.md", content))
    hits = [i for i in res["issues"] if i["kind"] == "wiki-id"]
    assert hits and "int" in hits[0]["detail"]


def test_validate_plan_skips_front_matter_not_at_byte_zero(tmp_path):
    # 선행 HTML 주석 = "위키 밖" 마커 (wiki_graph 와 같은 의미론) — 노드가 아니므로 스킵.
    content = "<!-- note -->\n---\nwiki_id: wrong\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/guide.md", content))
    assert not any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_flags_underivable_path(tmp_path):
    content = "---\nwiki_id: onboarding\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs/온보딩.md", content))
    assert any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_treats_docs_old_as_outside_the_docs_root(tmp_path):
    # `rel.startswith(f"{wiki_root}/")` requires the separator — weakening it to
    # `rel.startswith(wiki_root)` (no "/") would false-match "docs-old/a.md" against root
    # "docs" (the same path-prefix footgun Invariant #7 guards against for worktree
    # identity), running the parity check on a file that was never under the wiki root.
    content = "---\nwiki_id: totally-wrong\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("docs-old/a.md", content))
    assert not any(i["kind"] == "wiki-id" for i in res["issues"])


def test_validate_plan_treats_dot_wiki_root_as_every_md(tmp_path):
    # A host may configure the repo root itself as the wiki root. _wiki_root_hint then
    # returns "." (not ""), and `rel.startswith(f"{wiki_root}/")` would never match since
    # rel is normalized and never carries a leading "./" — silently skipping every file.
    # A root of "." must instead mean every .md in the plan is under the wiki root.
    _write_wiki_config(tmp_path, "wiki:\n  root: .\n")
    content = "---\nwiki_id: totally-wrong\ntitle: t\n---\n본문\n"
    res = hs.validate_plan(tmp_path, _wiki_plan("guide.md", content))
    hits = [i for i in res["issues"] if i["kind"] == "wiki-id"]
    assert hits and "guide" in hits[0]["detail"]
