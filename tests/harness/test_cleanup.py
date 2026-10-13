"""리서치 사본 정리와 구 문서 이전.

증거는 보존하고 사본만 지움. 문서가 하네스로 링크를 걸고 있으면 정리를 **미룸** —
지우면 그 링크가 끊어짐.
"""

import json

import scripts.harness_scaffold as hs


def test_cleanup_removes_research_copies_but_preserves_evidence(tmp_path):
    harness = tmp_path / ".claude" / "vway-kit" / ".harness"
    research = harness / "research"
    research.mkdir(parents=True)
    (research / "researcher_nextjs.md").write_text("조사 내용", encoding="utf-8")
    (research / "code-analyzer.md").write_text("스캔 내용", encoding="utf-8")
    # 보존돼야 하는 감사용 증거
    for name in ("plan.json", "manifest.json", "critic-report.json", "rationale.md"):
        (harness / name).write_text("{}", encoding="utf-8")

    report = hs.cleanup_harness(harness, tmp_path)

    # research 사본은 제거(docs가 .harness를 참조하지 않으므로)
    assert not research.exists() or not any(research.iterdir())
    assert any("researcher_nextjs.md" in r for r in report["removed"])
    assert report["link_warnings"] == []
    # 증거 메타는 보존
    for name in ("plan.json", "manifest.json", "critic-report.json", "rationale.md"):
        assert (harness / name).exists()
    assert sorted(report["preserved"]) == sorted(
        ["critic-report.json", "manifest.json", "plan.json", "rationale.md"]
    )


def test_cleanup_is_safe_when_no_research_dir(tmp_path):
    harness = tmp_path / ".claude" / "vway-kit" / ".harness"
    harness.mkdir(parents=True)
    (harness / "plan.json").write_text("{}", encoding="utf-8")
    report = hs.cleanup_harness(harness, tmp_path)
    assert report["removed"] == []
    assert report["preserved"] == ["plan.json"]


def test_cleanup_does_not_touch_non_research_non_preserve(tmp_path):
    # 보존 화이트리스트도 아니고 research/ 도 아닌 파일은 건드리지 않는다(보수적).
    harness = tmp_path / ".claude" / "vway-kit" / ".harness"
    harness.mkdir(parents=True)
    (harness / "stray.txt").write_text("x", encoding="utf-8")
    hs.cleanup_harness(harness, tmp_path)
    assert (harness / "stray.txt").exists()


def test_migrate_relocates_old_flat_doc(tmp_path):
    # 옛 flat 경로의 문서를 새 verification/ 위치로 이동하고 내용을 보존함.
    old = tmp_path / "docs" / "performance.md"
    old.parent.mkdir(parents=True)
    old.write_text("사용자 편집 성능 문서", encoding="utf-8")
    report = hs.migrate_docs(tmp_path)
    new = tmp_path / "docs" / "verification" / "performance.md"
    assert not old.exists()  # 이동(복사 아님)
    assert new.read_text(encoding="utf-8") == "사용자 편집 성능 문서"
    assert {"from": "docs/performance.md", "to": "docs/verification/performance.md"} in report[
        "moved"
    ]
    assert report["conflicts"] == [] and report["errors"] == []


def test_migrate_noop_when_old_absent(tmp_path):
    # 옛 파일이 없으면 이동할 게 없음 → 멱등 no-op(재실행 안전).
    report = hs.migrate_docs(tmp_path)
    assert report["moved"] == [] and report["conflicts"] == [] and report["errors"] == []
    assert not (tmp_path / "docs" / "verification").exists()  # 빈 폴더 만들지 않음


def test_migrate_conflict_preserves_both_when_new_exists(tmp_path):
    # 새 위치에 이미 파일이 있으면 clobber 하지 않고 conflict 로 보고(양쪽 보존).
    old = tmp_path / "docs" / "integration.md"
    old.parent.mkdir(parents=True)
    old.write_text("OLD", encoding="utf-8")
    new = tmp_path / "docs" / "verification" / "integration.md"
    new.parent.mkdir(parents=True)
    new.write_text("NEW", encoding="utf-8")
    report = hs.migrate_docs(tmp_path)
    assert old.read_text(encoding="utf-8") == "OLD"  # 보존
    assert new.read_text(encoding="utf-8") == "NEW"  # 덮어쓰지 않음
    assert report["moved"] == []
    assert {"from": "docs/integration.md", "to": "docs/verification/integration.md"} in report[
        "conflicts"
    ]


def test_migrate_handles_both_docs(tmp_path):
    for name in ("performance.md", "integration.md"):
        p = tmp_path / "docs" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(name, encoding="utf-8")
    report = hs.migrate_docs(tmp_path)
    assert len(report["moved"]) == 2
    assert (tmp_path / "docs" / "verification" / "performance.md").exists()
    assert (tmp_path / "docs" / "verification" / "integration.md").exists()


def test_main_migrate_outputs_json(tmp_path, capsys):
    old = tmp_path / "docs" / "performance.md"
    old.parent.mkdir(parents=True)
    old.write_text("x", encoding="utf-8")
    rc = hs.main(["migrate", "--root", str(tmp_path)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["moved"] and "conflicts" in report


def test_cleanup_holds_when_docs_link_into_harness(tmp_path):
    # 링크 가드(FAIL-SAFE): docs가 .harness/research 를 참조하면 제거를 보류함.
    harness = tmp_path / ".claude" / "vway-kit" / ".harness"
    research = harness / "research"
    research.mkdir(parents=True)
    (research / "researcher_nextjs.md").write_text("조사", encoding="utf-8")
    arch = tmp_path / "docs" / "sds"
    arch.mkdir(parents=True)
    (arch / "README.md").write_text(
        "출처: [조사](../../.claude/vway-kit/.harness/research/researcher_nextjs.md)",
        encoding="utf-8",
    )
    report = hs.cleanup_harness(harness, tmp_path)
    assert (research / "researcher_nextjs.md").exists()  # 보류로 보존
    assert report["removed"] == []
    assert any("sds/README.md" in w for w in report["link_warnings"])
