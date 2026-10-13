"""플랜 적용 — 마커 블록 upsert 와 멱등성.

`create` 는 기존 파일을 **절대** 덮지 않고, 마커 블록은 제자리에서 갈아끼우며 바깥은
보존함. BEGIN 만 있고 END 가 없으면 truncate 하지 않고 예외.
"""

import json

import pytest

import scripts.harness_scaffold as hs


def test_marker_created_when_file_absent(tmp_path):
    p = tmp_path / "CLAUDE.md"
    assert hs.upsert_marker_block(p, "harness:baseline", "RULE A") == "created"
    text = p.read_text(encoding="utf-8")
    assert "harness:baseline BEGIN" in text and "RULE A" in text and "harness:baseline END" in text


def test_marker_inserted_when_no_marker(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text("# Existing\n\nuser content\n", encoding="utf-8")
    assert hs.upsert_marker_block(p, "harness:baseline", "RULE A") == "inserted"
    text = p.read_text(encoding="utf-8")
    assert "user content" in text and "RULE A" in text


def test_marker_replaced_in_place_preserves_outside(tmp_path):
    p = tmp_path / "CLAUDE.md"
    hs.upsert_marker_block(p, "harness:baseline", "OLD")
    p.write_text("PRE\n" + p.read_text(encoding="utf-8") + "POST\n", encoding="utf-8")
    assert hs.upsert_marker_block(p, "harness:baseline", "NEW") == "replaced"
    text = p.read_text(encoding="utf-8")
    assert "NEW" in text and "OLD" not in text
    assert text.startswith("PRE") and text.rstrip().endswith("POST")


def test_marker_idempotent_same_content(tmp_path):
    p = tmp_path / "CLAUDE.md"
    hs.upsert_marker_block(p, "harness:baseline", "RULE A")
    before = p.read_text(encoding="utf-8")
    hs.upsert_marker_block(p, "harness:baseline", "RULE A")
    assert p.read_text(encoding="utf-8") == before


def test_marker_begin_without_end_raises(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text(
        "PRE\n<!-- harness:baseline BEGIN (managed by /harness-init "
        "— edits inside are overwritten) -->\nOLD body without end\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        hs.upsert_marker_block(p, "harness:baseline", "NEW")


def test_apply_creates_when_absent(tmp_path):
    plan = {
        "files": [{"path": ".claude/rules/baseline.md", "action": "create", "content": "RULES"}]
    }
    report = hs.apply_plan(tmp_path, plan)
    assert report["created"] == [".claude/rules/baseline.md"]
    assert (tmp_path / ".claude/rules/baseline.md").read_text(encoding="utf-8") == "RULES"


def test_apply_never_overwrites_existing_create(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text("ORIGINAL", encoding="utf-8")
    plan = {"files": [{"path": "CLAUDE.md", "action": "create", "content": "NEW"}]}
    report = hs.apply_plan(tmp_path, plan)
    assert report["conflicts"] == ["CLAUDE.md"]
    assert report["created"] == []
    assert target.read_text(encoding="utf-8") == "ORIGINAL"  # 불변식


def test_apply_marker_upsert_updates(tmp_path):
    plan = {
        "files": [
            {
                "path": "CLAUDE.md",
                "action": "marker_upsert",
                "marker_id": "harness:baseline",
                "content": "B",
            }
        ]
    }
    report = hs.apply_plan(tmp_path, plan)
    assert report["updated"] == ["CLAUDE.md"]
    assert "harness:baseline BEGIN" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_apply_idempotent_rerun(tmp_path):
    plan = {
        "files": [
            {"path": ".claude/rules/baseline.md", "action": "create", "content": "RULES"},
            {
                "path": "CLAUDE.md",
                "action": "marker_upsert",
                "marker_id": "harness:baseline",
                "content": "B",
            },
        ]
    }
    hs.apply_plan(tmp_path, plan)
    snapshot = {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file()}
    report2 = hs.apply_plan(tmp_path, plan)
    assert report2["created"] == [] and report2["conflicts"] == [".claude/rules/baseline.md"]
    after = {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file()}
    assert snapshot == after  # 재실행해도 내용 동일


def test_apply_lens_upsert_additive(tmp_path):
    p = tmp_path / "docs/code-style/react.md"
    p.parent.mkdir(parents=True)
    p.write_text("## 베스트 프랙티스\n", encoding="utf-8")
    plan = {
        "files": [
            {
                "path": "docs/code-style/react.md",
                "action": "lens_upsert",
                "stack": "react",
                "mode": "additive",
                "lenses": [{"key": "ux", "body": "### UX\n- guard"}],
            }
        ]
    }
    rep = hs.apply_plan(tmp_path, plan)
    assert "docs/code-style/react.md" in rep["updated"]
    assert "code-style:lens:react:ux BEGIN" in p.read_text(encoding="utf-8")


def test_apply_lens_upsert_idempotent_rerun(tmp_path):
    p = tmp_path / "docs/code-style/react.md"
    p.parent.mkdir(parents=True)
    p.write_text("## 베스트 프랙티스\n", encoding="utf-8")
    plan = {
        "files": [
            {
                "path": "docs/code-style/react.md",
                "action": "lens_upsert",
                "stack": "react",
                "mode": "additive",
                "lenses": [{"key": "ux", "body": "### UX\n- guard"}],
            }
        ]
    }
    hs.apply_plan(tmp_path, plan)
    txt1 = p.read_text(encoding="utf-8")
    rep2 = hs.apply_plan(tmp_path, plan)
    txt2 = p.read_text(encoding="utf-8")
    assert "docs/code-style/react.md" in rep2["updated"]
    assert txt2 == txt1  # 재실행해도 바이트 동일(무변경 시 쓰기 스킵)


def test_apply_lens_upsert_replace_section(tmp_path):
    p = tmp_path / "docs/code-style/react.md"
    p.parent.mkdir(parents=True)
    p.write_text("## 베스트 프랙티스\n- 옛 산문\n\n## 툴체인\n- t\n", encoding="utf-8")
    plan = {
        "files": [
            {
                "path": "docs/code-style/react.md",
                "action": "lens_upsert",
                "stack": "react",
                "mode": "replace_section",
                "lenses": [{"key": "correctness", "body": "### 정확성\n- c"}],
            }
        ]
    }
    rep = hs.apply_plan(tmp_path, plan)
    assert "docs/code-style/react.md" in rep["updated"]
    txt = p.read_text(encoding="utf-8")
    assert "옛 산문" not in txt and "## 툴체인" in txt
    assert "code-style:lens:react:correctness BEGIN" in txt


def test_apply_lens_upsert_nonstandard_skips_with_warning(tmp_path):
    p = tmp_path / "docs/code-style/react.md"
    p.parent.mkdir(parents=True)
    p.write_text("## 툴체인\n- t\n", encoding="utf-8")  # BP 헤딩 없음
    plan = {
        "files": [
            {
                "path": "docs/code-style/react.md",
                "action": "lens_upsert",
                "stack": "react",
                "mode": "replace_section",
                "lenses": [{"key": "ux", "body": "### UX"}],
            }
        ]
    }
    rep = hs.apply_plan(tmp_path, plan)
    assert "docs/code-style/react.md" in rep["skipped"]
    assert rep["warnings"]


_BP = "## 베스트 프랙티스\n"


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "a.md", "action": "create", "content": "Title\r\n=====\r\nbody\r\n"},
        {"path": "a.md", "action": "create", "content": "Title\r\r\n=====\rbody\r"},
        {"path": "a.md", "action": "marker_upsert", "marker_id": "m", "content": "l1\r\nl2\r\n"},
        {
            "path": "a.md",
            "action": "lens_upsert",
            "stack": "go",
            "mode": "additive",
            "lenses": [{"key": "performance", "body": "### Performance\r\n- p\r\n"}],
        },
        {
            "path": "a.md",
            "action": "lens_upsert",
            "stack": "go",
            "mode": "replace_section",
            "lenses": [{"key": "performance", "body": "### Performance\r\n- p\r\n"}],
        },
    ],
    ids=["create", "create-stray-cr", "marker_upsert", "lens-additive", "lens-replace"],
)
def test_apply_writes_plan_text_without_a_carriage_return(tmp_path, monkeypatch, entry):
    # 텍스트 모드는 "\n" 마다 플랫폼 줄끝을 써서 플랜 JSON 의 "\r\n" 이 Windows 에서
    # "\r\r\n"(setext 헤딩 밑 빈 줄)이 됨. 쓰기 직전 문자열을 잡아 os.linesep 과 무관하게 잼.
    if entry["action"] == "lens_upsert":
        (tmp_path / "a.md").write_text(_BP, encoding="utf-8")
    written = []
    original = hs.Path.write_text

    def spy(self, data, *args, **kwargs):
        written.append(data)
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(hs.Path, "write_text", spy)
    rep = hs.apply_plan(tmp_path, {"files": [entry]})
    assert written, f"apply_plan 이 아무것도 안 씀: {rep}"
    assert not any("\r" in text for text in written)
    assert b"\r\r" not in (tmp_path / "a.md").read_bytes()


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "a.md", "action": "create", "content": 1},
        {
            "path": "a.md",
            "action": "lens_upsert",
            "stack": "s",
            "lenses": [{"key": "k", "body": 1}],
        },
    ],
    ids=["content", "lens-body"],
)
def test_apply_skips_non_string_plan_text(tmp_path, entry):
    if entry["action"] == "lens_upsert":
        (tmp_path / "a.md").write_text(_BP, encoding="utf-8")
    rep = hs.apply_plan(tmp_path, {"files": [entry]})
    assert rep["skipped"] == ["a.md"] and rep["warnings"]


def test_main_detect_outputs_json(tmp_path, capsys):
    (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
    rc = hs.main(["detect", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "brownfield"
    assert "frameworks" in out and "existing" in out


def test_main_apply_reads_plan_file(tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps({"files": [{"path": "a.md", "action": "create", "content": "X"}]}),
        encoding="utf-8",
    )
    rc = hs.main(["apply", "--root", str(tmp_path), "--plan", str(plan_file)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["created"] == ["a.md"]


# ------------------------------------------------------- 경로 봉쇄(root 밖 쓰기 금지)


def test_apply_rejects_absolute_path_entry(tmp_path):
    # 절대경로는 `root / rel` 이 root 를 통째로 버림 — 쓰기 전에 거부해야 함.
    outside = tmp_path.parent / "escaped.md"
    plan = {"files": [{"path": str(outside), "action": "create", "content": "x"}]}
    rep = hs.apply_plan(tmp_path, plan)
    assert not outside.exists()
    # path 는 정규화(validate·doctor 와 대조 가능), raw 는 **다를 때만** 원문으로 함께 —
    # 그래서 `r["raw"]` 를 무조건 읽으면 POSIX 에서만 KeyError 다(절대경로가 자기 자신으로
    # 정규화돼 키가 안 실림). 계약대로 읽어야 두 OS 에서 같은 것을 잼.
    assert any(r.get("raw", r["path"]) == str(outside) for r in rep["rejected"])
    assert rep["created"] == []


def test_apply_rejects_parent_traversal(tmp_path):
    plan = {"files": [{"path": "../escaped.md", "action": "create", "content": "x"}]}
    rep = hs.apply_plan(tmp_path, plan)
    assert not (tmp_path.parent / "escaped.md").exists()
    assert any("../escaped.md" in r["path"] for r in rep["rejected"])


def test_apply_rejects_writing_into_harness_evidence_dir(tmp_path):
    # 증거 디렉터리는 gitignored — 산출물이 거기 떨어지면 cleanup 이 지우거나 링크가 깨짐.
    rel = ".claude/vway-kit/.harness/research/leaked.md"
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    assert not (tmp_path / rel).exists()
    assert any(r["path"] == rel for r in rep["rejected"])


def test_apply_rejects_nested_harness_tree_under_docs(tmp_path):
    # 링크를 문서 기준 상대로 잘못 이어붙였을 때 나오는 유령 경로.
    rel = "docs/requirements/.claude/vway-kit/.harness/research/x.md"
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    assert not (tmp_path / "docs" / "requirements" / ".claude").exists()
    assert any(r["path"] == rel for r in rep["rejected"])


def test_apply_still_writes_normal_paths(tmp_path):
    # 봉쇄가 정상 경로를 막지 않음(회귀 방지).
    plan = {"files": [{"path": "docs/research/README.md", "action": "create", "content": "ok"}]}
    rep = hs.apply_plan(tmp_path, plan)
    assert (tmp_path / "docs" / "research" / "README.md").read_text(encoding="utf-8") == "ok"
    assert rep["created"] == ["docs/research/README.md"] and rep["rejected"] == []


def test_apply_normalizes_backslash_path(tmp_path):
    # 모델이 Windows 구분자를 섞어 써도 같은 파일 하나로 떨어짐.
    plan = {"files": [{"path": r"docs\research\a.md", "action": "create", "content": "ok"}]}
    rep = hs.apply_plan(tmp_path, plan)
    assert (tmp_path / "docs" / "research" / "a.md").exists()
    assert rep["created"] == ["docs/research/a.md"] and rep["rejected"] == []


def test_apply_rejects_uppercase_harness_segment(tmp_path):
    # Windows·macOS 기본 FS 에서 `.HARNESS` 는 같은 디렉터리 — 철자만 보면 그대로 새어 듦.
    rel = ".CLAUDE/VWAY-KIT/.HARNESS/research/leaked.md"
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    assert not (tmp_path / rel).exists()
    assert any(r["path"] == rel for r in rep["rejected"])


def test_apply_rejects_trailing_harness_segment(tmp_path):
    # 끝에 선 `.harness` — 뒤에 슬래시가 없어 접두 문자열 검사로는 안 잡힘.
    rel = "docs/x/.harness"
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    assert not (tmp_path / rel).exists()
    assert any(r["path"] == rel for r in rep["rejected"])


def test_apply_rejects_drive_relative_path(tmp_path):
    # `PureWindowsPath('D:/proj') / 'C:x'` 는 `C:x` — 구분자가 없어도 절대 경로.
    rel = "C:evil.md"
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    assert any(r["path"] == rel for r in rep["rejected"]) and rep["created"] == []


def test_apply_rejects_symlink_escape(tmp_path):
    # 철자는 멀쩡한데 실제 위치가 root 밖 — realpath 로만 보임.
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    try:
        (tmp_path / "docs").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("심링크 생성 권한 없음")
    rel = "docs/research/escaped.md"
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    assert not (outside / "research" / "escaped.md").exists()
    assert any(r["path"] == rel for r in rep["rejected"])


@pytest.mark.parametrize(
    "rel",
    [
        ".claude/vway-kit/.harness./research/leaked.md",  # 후행 점 — Windows 가 잘라냄
        ".claude/vway-kit/.harness /research/leaked.md",  # 후행 공백 — 마찬가지
        "docs/x/.HARNESS./y.md",  # 접기 셋(대소문자·점·경로)이 겹친 경우
    ],
)
def test_apply_rejects_harness_segment_after_windows_folding(tmp_path, rel):
    # Windows 는 후행 점·공백을 잘라낸 뒤 해석 — 대소문자만 접으면 같은 디렉터리에 그대로
    # 떨어짐. 실제 착지 위치로 확인함(철자 비교는 이 사고를 못 본 바로 그 검사).
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    landed = [p for p in tmp_path.rglob("leaked.md")] + [p for p in tmp_path.rglob("y.md")]
    assert landed == [], f"증거 디렉터리에 착지함: {landed}"
    assert any(r["path"] == rel for r in rep["rejected"])


@pytest.mark.parametrize(
    "rel",
    [
        "docs/x\x00.md",  # 널 문자 — 파이썬이 ValueError 를 던짐
        "docs/" + ("d" * 300) + "/x.md",  # OS 이름 길이 한계
    ],
)
def test_apply_reports_os_hostile_path_instead_of_crashing(tmp_path, rel):
    # 예외로 올리면 이미 적용된 엔트리만 남은 반쯤 쓰인 트리가 생김 — doctor 가 덮으려는
    # 그 상태를 apply 스스로 만드는 셈. 뒤 엔트리는 계속 적용돼야 함.
    plan = {
        "files": [
            {"path": rel, "action": "create", "content": "x"},
            {"path": "docs/research/after.md", "action": "create", "content": "ok"},
        ]
    }
    rep = hs.apply_plan(tmp_path, plan)
    assert rep["rejected"], "거부 보고 없이 통과했거나 예외로 죽었다"
    assert rep["created"] == ["docs/research/after.md"]


def test_apply_reports_missing_path_key(tmp_path):
    # 키가 없어도 조용히 삼키지 않음 — 사유와 함께 rejected 로 나옴.
    rep = hs.apply_plan(tmp_path, {"files": [{"action": "create", "content": "x"}]})
    assert len(rep["rejected"]) == 1 and "빈 경로" in rep["rejected"][0]["reason"]


def test_apply_rejects_short_name_alias(tmp_path):
    # 8.3 단축명은 Windows 가 긴 이름으로 되푸는 별칭 — 이름 접기로는 정체를 못 봄.
    rel = ".claude/vway-kit/HARNES~1/r/leaked.md"
    rep = hs.apply_plan(tmp_path, {"files": [{"path": rel, "action": "create", "content": "x"}]})
    assert list(tmp_path.rglob("leaked.md")) == []
    assert any(r["path"] == rel for r in rep["rejected"])


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "docs/a.md", "action": "marker_upsert"},  # marker_id 누락
        {"path": "docs/a.md", "action": "lens_upsert"},  # stack 누락
        {"path": "docs/a.md", "action": "lens_upsert", "stack": "s", "lenses": [{}]},
        {"path": "docs/a.md", "action": "create", "content": 7},  # content 가 문자열 아님
        {"path": "docs/a.md", "action": "create", "content": "\ud800"},  # 인코딩 불가
    ],
)
def test_apply_survives_malformed_entry_and_keeps_going(tmp_path, entry):
    # plan 은 모델이 씀 — 키 누락·타입 불일치가 조작된 경로보다 흔함. 실행을 죽이면
    # 앞 엔트리만 적용된 반쯤 쓰인 트리가 남아 doctor 가 덮으려는 상태를 apply 가 만듦.
    plan = {
        "files": [entry, {"path": "docs/research/after.md", "action": "create", "content": "ok"}]
    }
    rep = hs.apply_plan(tmp_path, plan)
    assert rep["created"] == ["docs/research/after.md"]
    assert rep["skipped"] == ["docs/a.md"] and rep.get("warnings")


def test_reject_carries_raw_only_when_normalization_changed_it():
    """`raw` 는 원문이 정규화와 **다를 때만** 실림.

    이 계약을 테스트가 무조건 `r["raw"]` 로 읽으면 한 OS 에서만 통과함 — POSIX 는 절대경로가
    자기 자신으로 정규화돼 키가 없고, Windows 는 백슬래시가 접혀 키가 있음. 플랫폼에 기대지
    않고 계약 자체를 여기서 고정함.
    """
    report: dict = {"rejected": []}
    windows_raw = "a" + chr(92) + "b.md"  # 리터럴 백슬래시 — 이스케이프로 적으면 조용히 접힘
    hs._reject(report, "a/b.md", "a/b.md", "사유")
    hs._reject(report, "a/b.md", windows_raw, "사유")
    assert "raw" not in report["rejected"][0]
    assert report["rejected"][1]["raw"] == windows_raw
