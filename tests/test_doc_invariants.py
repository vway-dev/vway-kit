"""문서 재작성 대조기 — 무엇을 손실로 부르고 무엇을 부르지 않는가.

이 도구의 값은 정확도가 아니라 **신호 대 잡음**에 있음. 재작성마다 열 줄씩 오탐을 뱉으면
사람은 두 번째 실행부터 출력을 안 읽고, 그때부터 진짜 손실도 같이 안 읽힘. 그래서 여기
테스트의 절반은 "이건 손실이 아니다"를 고정 — 정상 편집(펜스 안 한 줄 수정·접힘 폭
변경)이 error 로 올라오는 순간 이 도구는 꺼진 것과 같음.

나머지 절반은 실제로 잃은 것(펜스 통째·링크·front matter 키)이 error 로 올라오는지 잼.
두 케이스 모두 이 repo 의 문체 전환 커밋에서 실측된 모양을 그대로 씀.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.doc_invariants import (
    check_changed,
    code_fences,
    compare,
    headings,
    inline_codes,
    links,
)

REPO = Path(__file__).resolve().parent.parent

DOC = """---
name: sample
description: 한 줄 설명
---

# 제목

본문에 [링크](../rules/doc-style.md)와 `코드 스팬` 하나.

```bash
echo hello
echo world
```

## 둘째 절

- 항목 하나
- 항목 둘
"""


def _run_cli(args: list[str], cwd: Path | None = None, stdin: str | None = None):
    root = cwd or REPO
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "doc_invariants.py"), *args],
        cwd=str(root),
        input=stdin,
        # `host_root` 는 CLAUDE_PROJECT_DIR 를 먼저 읽음 — 세션이 채워 둔 값이 임시 저장소를 가림.
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        capture_output=True,
        text=True,
        encoding="utf-8",  # Invariant #2 — 한글 출력이 cp949 로 디코드되면 리더가 죽음
        timeout=30,
    )


def test_an_unchanged_document_reports_nothing():
    assert compare(DOC, DOC) == ([], [])


def test_editing_a_line_inside_a_fence_is_not_a_lost_block():
    """실측된 오탐의 정본. 펜스 본문을 통째로 비교하면 `echo world` 한 줄만 고쳐도 "블록
    사라짐"이 되고, 자기 문체 전환에서 8개 파일이 그렇게 잡힘."""
    after = DOC.replace("echo world", "echo mundo")
    errors, warnings = compare(DOC, after)
    assert errors == []
    assert any("펜스 안" in w for w in warnings)


def test_a_deleted_fence_is_an_error():
    after = DOC.replace("```bash\necho hello\necho world\n```\n", "")
    errors, _ = compare(DOC, after)
    assert any("코드펜스" in e and "사라짐" in e for e in errors)


def test_refolding_a_code_span_across_lines_is_not_a_loss():
    """재작성은 같은 문장을 다른 폭으로 접음. 접힘이 스팬 한가운데를 지나가면 줄 단위
    추출은 멀쩡한 스팬을 잃었다고 말함 — `_unfold` 가 그 앞에 섬."""
    before = "본문에 `python3 wiki_graph.py --neighbors` 를 실행한다.\n"
    after = "본문에 `python3 wiki_graph.py\n  --neighbors` 실행.\n"
    errors, _ = compare(before, after)
    assert errors == []


def test_an_unbalanced_backtick_does_not_swallow_the_next_bullet():
    """홀수 백틱 하나가 다음 항목의 문장 반쪽을 스팬으로 삼키면, 그 반쪽이 문체 전환마다
    "사라진 코드"로 보고된다(task-sync 에서 실측)."""
    text = "- `update` 가 GET 을 수행.\n- 결과가 여러 개면 사용자 선택.\n"
    assert set(inline_codes(text)) == {"update"}


def test_a_dropped_link_is_an_error_but_an_anchor_is_not():
    after = DOC.replace("[링크](../rules/doc-style.md)", "링크")
    errors, _ = compare(DOC, after)
    assert any("링크/URL" in e for e in errors)

    anchored = DOC.replace("(../rules/doc-style.md)", "(#절)")
    assert links(anchored) == links(anchored.replace("[링크](#절)", "링크"))


def test_a_dropped_frontmatter_key_is_an_error():
    """압축하는 LLM 이 front matter 를 다시 쓰는 것은 caveman 도 겪은 실패. 여기서는
    `description` 이 사라지면 스킬이 발화하지 않게 되므로 손실 중에서도 값이 큼."""
    after = DOC.replace("description: 한 줄 설명\n", "")
    errors, _ = compare(DOC, after)
    assert any("front matter" in e for e in errors)


def test_a_deleted_heading_is_an_error():
    """헤딩은 문서의 뼈대 — 절이 통째로 빠져도 남은 산문은 그대로 읽혀 사람 눈에 안 걸림."""
    after = DOC.replace("## 둘째 절\n\n", "")
    errors, _ = compare(DOC, after)
    assert any("헤딩" in e for e in errors), errors


def test_headings_are_read_line_by_line():
    """`^`·`$` 가 줄 단위가 아니면 한 줄짜리 문서 말고는 아무 헤딩도 안 잡히고(실측: 빈 결과),
    그러면 헤딩 축과 순서 경고가 함께 죽음."""
    text = "# 제목\n\n본문.\n\n## 둘째 절\n\n내용.\n"
    assert dict(headings(text)) == {"# 제목": 1, "## 둘째 절": 1}


def test_a_hash_alone_does_not_take_the_next_line_as_its_text():
    """`#` 뒤 공백을 줄 안에 가두지 않으면 개행을 넘어 다음 줄 문장을 제목으로 읽음 — 그 문장이
    바뀔 때마다 없던 헤딩 손실이 뜸."""
    assert dict(headings("#\n본문.\n")) == {}


def test_reordering_headings_is_a_warning_not_an_error():
    """순서 변경은 재작성의 정상 결과 — error 로 올리면 조화 편집마다 붉어짐."""
    before = "# 제목\n\n## 가\n\n본문.\n\n## 나\n\n본문.\n"
    after = "# 제목\n\n## 나\n\n본문.\n\n## 가\n\n본문.\n"
    errors, warnings = compare(before, after)
    assert errors == []
    assert any("헤딩" in w for w in warnings), warnings


def test_a_url_inside_a_fence_is_not_counted():
    """펜스 안의 URL·헤딩은 예시. 세면 예시를 고친 편집이 전부 손실로 잡힘."""
    before = DOC.replace("echo hello", "curl https://example.com/a")
    after = DOC.replace("echo hello", "curl https://example.com/b")
    errors, _ = compare(before, after)
    assert errors == []


def test_nested_fences_read_as_one_block():
    """이 repo 의 스킬 문서가 실제로 4-백틱으로 3-백틱을 감쌈. 안쪽을 닫는 펜스로 읽으면
    블록 개수가 어긋나 정상 편집이 손실로 잡힘."""
    text = "````md\n```bash\necho x\n```\n````\n"
    assert len(code_fences(text)) == 1


def test_an_unclosed_fence_is_ignored():
    text = "# 제목\n\n```bash\necho x\n"
    assert code_fences(text) == []


def test_bullet_loss_is_a_warning_not_an_error():
    after = DOC.replace("- 항목 둘\n", "")
    errors, warnings = compare(DOC, after)
    assert errors == []
    assert any("불릿" in w for w in warnings)


# ── git 경로(--changed) ────────────────────────────────────────────────────────


def _repo(tmp_path: Path) -> Path:
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _commit(root: Path, message: str = "seed"):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True, capture_output=True)


def test_changed_compares_the_worktree_against_the_head_blob(tmp_path: Path):
    root = _repo(tmp_path)
    doc = root / "guide.md"
    doc.write_text(DOC, encoding="utf-8")
    _commit(root)
    doc.write_text(DOC.replace("[링크](../rules/doc-style.md)", "링크"), encoding="utf-8")

    report = check_changed(root, [])
    assert [f["path"] for f in report["findings"]] == ["guide.md"]
    assert any("링크/URL" in e for e in report["findings"][0]["errors"])


def test_a_new_file_is_listed_rather_than_compared(tmp_path: Path):
    """HEAD 에 없는 문서는 비교 대상이 아님 — 조용히 빼면 "검사했다"는 착시가 남음."""
    root = _repo(tmp_path)
    (root / "seed.md").write_text("# seed\n", encoding="utf-8")
    _commit(root)
    (root / "fresh.md").write_text(DOC, encoding="utf-8")

    report = check_changed(root, [])
    assert report["new_files"] == ["fresh.md"]
    assert report["findings"] == []


def test_paths_narrow_the_scope(tmp_path: Path):
    root = _repo(tmp_path)
    for name in ("a.md", "b.md"):
        (root / name).write_text(DOC, encoding="utf-8")
    _commit(root)
    for name in ("a.md", "b.md"):
        (root / name).write_text(DOC.replace("# 제목", "# 다른 제목"), encoding="utf-8")

    report = check_changed(root, ["b.md"])
    assert [f["path"] for f in report["findings"]] == ["b.md"]


def test_a_dot_prefixed_path_narrows_to_itself_rather_than_to_nothing(tmp_path: Path):
    """점으로 시작하는 디렉터리의 문서도 지목이 닿아야 함.

    `lstrip("./")` 은 접두가 아니라 문자집합을 벗겨 `.claude/x.md` 를 `claude/x.md` 로 만듦.
    그 이름은 git 목록에 없으므로 그 문서만 조용히 필터 밖에 남고, 손실이 있는데도 보고가
    비어 나감 — 이 저장소의 `.claude/rules/` 가 그 자리에 있음."""
    root = _repo(tmp_path)
    (root / ".claude").mkdir()
    doc = root / ".claude" / "x.md"
    doc.write_text(DOC, encoding="utf-8")
    _commit(root)
    doc.write_text(DOC.replace("[링크](../rules/doc-style.md)", "링크"), encoding="utf-8")

    unfiltered = check_changed(root, [])
    assert [f["path"] for f in unfiltered["findings"]] == [".claude/x.md"]
    narrowed = check_changed(root, [".claude/x.md"])
    assert [f["path"] for f in narrowed["findings"]] == [".claude/x.md"], (
        "점 접두 경로가 지목에서 사라짐 — 필터가 이름을 망가뜨림"
    )


# ── 지목이 아무것도 못 가리킬 때 ─────────────────────────────────────────────────


def _narrowing_repo(tmp_path: Path) -> Path:
    """`docs/a.md` 는 링크를 잃음 · `docs/b.md` 는 추적 중이고 그대로 · `docs/n.txt` 는 .md 아님."""
    root = _repo(tmp_path)
    (root / "docs").mkdir()
    for name in ("a.md", "b.md"):
        (root / "docs" / name).write_text(DOC, encoding="utf-8")
    (root / "docs" / "n.txt").write_text("x", encoding="utf-8")
    _commit(root)
    (root / "docs" / "a.md").write_text(
        DOC.replace("[링크](../rules/doc-style.md)", "링크"), encoding="utf-8"
    )
    return root


@pytest.mark.parametrize(
    "arg",
    ["doc/a.md", "docs/A.md", "absolute", "docs/n.txt"],
    ids=["typo", "wrong-case", "absolute", "not-md"],
)
def test_a_path_that_names_no_document_is_named_and_exits_2(tmp_path: Path, arg: str):
    """못 가리킨 지목을 조용히 버리면 "변경된 .md 없음" 에 exit 0 — 손실이 있는데도 초록.
    대소문자가 특히 위험: Windows 파일시스템은 같은 파일로 열어 줘 틀린 줄 모르는데 git 목록은
    대소문자를 가림."""
    root = _narrowing_repo(tmp_path)
    if arg == "absolute":
        arg = (root / "docs" / "a.md").as_posix()
    result = _run_cli(["--changed", arg], cwd=root)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert arg in result.stderr
    assert "변경된 .md 없음" not in result.stdout


def test_a_mixed_list_reports_the_match_and_still_names_the_miss(tmp_path: Path):
    root = _narrowing_repo(tmp_path)
    result = _run_cli(["--changed", "docs/a.md", "typo/zz.md"], cwd=root)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "[!] docs/a.md" in result.stdout
    assert "typo/zz.md" in result.stderr


def test_naming_an_unchanged_tracked_document_says_so_and_exits_0(tmp_path: Path):
    """추적 중인 문서가 그대로면 잃은 것도 없음 — 사용 오류가 아니라 답임. 그 답을 "변경된
    .md 없음" 으로 뭉개면 지목이 닿았는지 빗나갔는지 구별이 안 됨."""
    root = _narrowing_repo(tmp_path)
    result = _run_cli(["--changed", "docs/b.md"], cwd=root)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "[=] docs/b.md" in result.stdout
    assert result.stderr == ""


def test_json_mode_lists_the_miss_and_keeps_the_exit_code(tmp_path: Path):
    root = _narrowing_repo(tmp_path)
    result = _run_cli(["--changed", "typo.md", "--json"], cwd=root)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["unmatched"] == ["typo.md"]


# ── CLI 계약 ───────────────────────────────────────────────────────────────────


def test_pair_reads_the_after_side_from_stdin(tmp_path: Path):
    before = tmp_path / "before.md"
    before.write_text(DOC, encoding="utf-8")
    result = _run_cli(["--pair", str(before), "-"], stdin=DOC)
    assert result.returncode == 0
    assert "보존됨" in result.stdout


def test_a_loss_exits_nonzero_and_names_what_went(tmp_path: Path):
    before = tmp_path / "before.md"
    before.write_text(DOC, encoding="utf-8")
    after = tmp_path / "after.md"
    after.write_text(DOC.replace("`코드 스팬`", "코드 스팬"), encoding="utf-8")

    result = _run_cli(["--pair", str(before), str(after)])
    assert result.returncode == 1
    assert "인라인 코드" in result.stdout


def test_json_output_is_machine_readable(tmp_path: Path):
    before = tmp_path / "before.md"
    before.write_text(DOC, encoding="utf-8")
    after = tmp_path / "after.md"
    after.write_text(DOC, encoding="utf-8")

    result = _run_cli(["--pair", str(before), str(after), "--json"])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["findings"][0]["errors"] == []


def test_an_unreadable_file_is_a_usage_error(tmp_path: Path):
    result = _run_cli(["--pair", str(tmp_path / "missing.md"), str(tmp_path / "also-missing.md")])
    assert result.returncode == 2


@pytest.mark.parametrize("argv", [[], ["--changed", "--pair", "a", "b"]])
def test_a_mode_is_required_and_exclusive(argv: list[str]):
    result = _run_cli(argv)
    assert result.returncode == 2


def test_the_script_is_copied_to_the_host():
    """doc-sync 는 소비자 프로젝트에서 돌아감 — 호스트 사본이 없으면 스킬이 지시하는 명령이
    `No such file` 로 끝나고, 그 실패는 조용히 "검사 없음"이 됨."""
    from scripts.vdev_init_setup import COPY_FILES

    assert "scripts/doc_invariants.py" in COPY_FILES
