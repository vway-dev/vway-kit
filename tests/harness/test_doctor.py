"""중단된 실행의 잔해 진단 — 재실행 전에 무엇이 어긋났는지 이름을 댐.

cleanup 은 apply 성공 후에만 돌아 중단 사고를 못 봄. doctor 는 그 사각을 덮는
읽기 전용 진단 — 아무것도 고치지 않고, 게이트도 아님(exit 0 고정).
"""

import json

import pytest

import scripts.harness_scaffold as hs


def _harness(root):
    h = root / ".claude" / "vway-kit" / ".harness"
    h.mkdir(parents=True, exist_ok=True)
    return h


def test_doctor_clean_on_untouched_project(tmp_path):
    rep = hs.doctor(tmp_path)
    assert rep["verdict"] == "clean"
    assert rep["stray_trees"] == [] and rep["research_residue"] == []
    assert rep["plan_unapplied"] == [] and rep["plan_bad_paths"] == []


def test_doctor_detects_stray_tree_regardless_of_case(tmp_path):
    stray = tmp_path / "docs" / "sds" / ".CLAUDE"
    stray.mkdir(parents=True)
    (stray / "a.md").write_text("a", encoding="utf-8")
    assert hs.doctor(tmp_path)["stray_trees"] == ["docs/sds/.CLAUDE"]


def test_doctor_detects_stray_harness_tree_under_docs(tmp_path):
    stray = tmp_path / "docs" / "requirements" / ".claude" / "vway-kit" / ".harness" / "research"
    stray.mkdir(parents=True)
    (stray / "researcher_x.md").write_text("조사", encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["verdict"] == "dirty"
    assert any("docs/requirements/.claude" in s for s in rep["stray_trees"])


def test_doctor_reports_stray_tree_once_not_per_file(tmp_path):
    stray = tmp_path / "docs" / "sds" / ".claude" / "vway-kit" / ".harness"
    stray.mkdir(parents=True)
    (stray / "a.md").write_text("a", encoding="utf-8")
    (stray / "b.md").write_text("b", encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["stray_trees"] == ["docs/sds/.claude"]


def test_doctor_detects_research_residue_after_apply(tmp_path):
    h = _harness(tmp_path)
    (h / "manifest.json").write_text("{}", encoding="utf-8")  # apply 가 끝났다는 표식
    (h / "research").mkdir()
    (h / "research" / "researcher_x.md").write_text("조사", encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["verdict"] == "dirty"
    assert any("researcher_x.md" in r for r in rep["research_residue"])


def test_doctor_ignores_research_before_apply(tmp_path):
    # manifest 가 없으면 아직 진행 중 — research 는 잔해가 아니라 입력임.
    h = _harness(tmp_path)
    (h / "research").mkdir()
    (h / "research" / "researcher_x.md").write_text("조사", encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["research_residue"] == []


def test_doctor_lists_plan_entries_never_applied(tmp_path):
    h = _harness(tmp_path)
    plan = {"files": [{"path": "docs/sds/README.md", "action": "create", "content": "x"}]}
    (h / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["plan_unapplied"] == ["docs/sds/README.md"]
    assert rep["verdict"] == "dirty"


def test_doctor_plan_applied_is_clean(tmp_path):
    h = _harness(tmp_path)
    plan = {"files": [{"path": "docs/sds/README.md", "action": "create", "content": "x"}]}
    (h / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (tmp_path / "docs" / "sds").mkdir(parents=True)
    (tmp_path / "docs" / "sds" / "README.md").write_text("x", encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["plan_unapplied"] == [] and rep["verdict"] == "clean"


@pytest.mark.parametrize(
    "body",
    [
        "{ not json",  # 파싱 실패
        '{"files": "not a list"}',  # 모양 실패 — 파싱은 되지만 files 가 리스트가 아님
        '{"files": null}',
        '{"files": [null]}',  # 원소가 dict 가 아님 — 그 엔트리를 판정할 수 없음
        "[]",  # 최상위가 dict 가 아님
    ],
)
def test_doctor_survives_malformed_plan(tmp_path, body):
    # doctor 가 존재하는 이유가 중단된 실행이 남긴 반쯤 쓰인 plan.json 임 — 그 입력에
    # 죽으면 Step 0 첫 줄에서 /harness-init 전체가 시작도 못 함. 그렇다고 조용히 삼켜
    # clean 을 보고하면 크래시보다 나쁨 — 못 읽었다는 사실이 리포트에 남아야 함.
    h = _harness(tmp_path)
    (h / "plan.json").write_text(body, encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["plan_unapplied"] == [] and rep["plan_bad_paths"] == []
    assert rep["plan_unreadable"] is True and rep["verdict"] == "dirty"


def test_doctor_entry_without_path_is_readable_but_bad(tmp_path):
    # 모양은 멀쩡하고 경로만 빈 엔트리 — plan 이 깨진 건 아니지만 apply 는 이걸 거부함.
    # 버리고 넘어가면 전부 null-path 인 plan 이 clean 으로 읽힘.
    h = _harness(tmp_path)
    (h / "plan.json").write_text('{"files": [{"nope": 1}, {"path": null}]}', encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["plan_unreadable"] is False
    assert rep["plan_bad_paths"] == ["<빈 경로>", "<빈 경로>"] and rep["verdict"] == "dirty"


def test_doctor_plan_without_files_key_matches_apply(tmp_path):
    # apply·validate 는 `plan.get("files", [])` 로 빈 계획으로 읽음 — doctor 만 "깨짐"이라
    # 하면 같은 입력에 세 함수가 다른 답을 냄.
    h = _harness(tmp_path)
    (h / "plan.json").write_text("{}", encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["plan_unreadable"] is False and rep["verdict"] == "clean"


def test_doctor_bad_paths_match_apply_rejections(tmp_path):
    # 두 리포트를 표에서 대조하려면 같은 문자열이어야 함 — 빈 경로 자리표도 포함.
    h = _harness(tmp_path)
    plan = {
        "files": [
            {"path": ".claude/vway-kit/.harness/r/x.md", "action": "create", "content": "x"},
            {"path": "docs\\x\\.harness\\y.md", "action": "create", "content": "x"},
            {"path": None, "action": "create", "content": "x"},
        ]
    }
    (h / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    rejected = {r["path"] for r in hs.apply_plan(tmp_path, plan)["rejected"]}
    assert rejected == set(hs.doctor(tmp_path)["plan_bad_paths"])


def test_doctor_no_plan_file_is_not_unreadable(tmp_path):
    # 계획이 아직 없는 정상 상태를 "깨짐"으로 오인하면 안 됨.
    _harness(tmp_path)
    rep = hs.doctor(tmp_path)
    assert rep["plan_unreadable"] is False and rep["verdict"] == "clean"


def test_doctor_classifies_symlink_escape_as_bad_path(tmp_path):
    # apply 가 영원히 거부할 엔트리를 "아직 안 됨"으로 보고하면 사람이 헛돌게 됨.
    outside = tmp_path.parent / "outside_doctor"
    outside.mkdir(exist_ok=True)
    try:
        (tmp_path / "docs").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("심링크 생성 권한 없음")
    h = _harness(tmp_path)
    plan = {"files": [{"path": "docs/research/escaped.md", "action": "create"}]}
    (h / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["plan_bad_paths"] == ["docs/research/escaped.md"]
    assert rep["plan_unapplied"] == []


def test_doctor_surfaces_plan_paths_apply_would_reject(tmp_path):
    # 산출물이 전부 거부된 실행이 clean 으로 보이면 안 됨.
    h = _harness(tmp_path)
    plan = {"files": [{"path": "docs/x/.claude/vway-kit/.harness/r/x.md", "action": "create"}]}
    (h / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert rep["plan_bad_paths"] == ["docs/x/.claude/vway-kit/.harness/r/x.md"]
    assert rep["plan_unapplied"] == [] and rep["verdict"] == "dirty"


def test_doctor_flags_residue_at_cleanup_time_without_manifest(tmp_path):
    # manifest 는 Step 8 — cleanup(7.5) 재확인 시점엔 아직 없음. 계획분이 전부 자리에
    # 있으면 그때도 apply 는 끝난 것이므로 남은 사본은 잔해.
    h = _harness(tmp_path)
    plan = {"files": [{"path": "docs/sds/README.md", "action": "create"}]}
    (h / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (tmp_path / "docs" / "sds").mkdir(parents=True)
    (tmp_path / "docs" / "sds" / "README.md").write_text("x", encoding="utf-8")
    (h / "research").mkdir()
    (h / "research" / "researcher_x.md").write_text("조사", encoding="utf-8")
    rep = hs.doctor(tmp_path)
    assert any("researcher_x.md" in r for r in rep["research_residue"])
    assert rep["verdict"] == "dirty"


def test_main_doctor_outputs_json_exit0(tmp_path, capsys):
    rc = hs.main(["doctor", "--root", str(tmp_path)])
    assert rc == 0  # FAIL-OPEN: 진단이지 게이트 아님
    assert json.loads(capsys.readouterr().out)["verdict"] == "clean"
