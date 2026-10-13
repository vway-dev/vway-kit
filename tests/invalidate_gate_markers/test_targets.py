"""편집이 **어느 트리의** 증거를 낡게 만드는가 — 경로 읽기·루트 걸음·worktree 합집합·등록."""

import json
import re
from pathlib import Path

from tests.invalidate_gate_markers._helpers import (
    KEPT,
    MARKERS,
    REPO,
    SCRIPT,
    payload,
    pytestmark,  # noqa: F401 — 모듈 수준 skip 은 이 이름으로만 걸림
    repo,
    run,
    vdev,
    worktree_of,
)


def test_edit_inside_the_project_voids_both_markers(project: Path):
    out = run(project, payload(str(project / "src" / "app.py")))
    assert out.returncode == 0, out.stderr
    for name in MARKERS:
        assert not (vdev(project) / name).exists(), (
            f"{name} 이 편집을 넘겼다 — 게이트 통과 뒤의 수정이 그 위에서 커밋된다"
        )


def test_the_other_gates_markers_are_left_alone(project: Path):
    run(project, payload(str(project / "src" / "app.py")))
    for name in KEPT:
        assert (vdev(project) / name).exists(), (
            f"{name} 이 지워졌다: bump·security 는 깨끗한 트리에서 내리는 승격 시점 결정이고, "
            f"다시 묻는 것은 이 훅이 벌지 않은 마찰이다"
        )


def test_an_edit_outside_the_project_is_not_an_edit_to_this_repo(project: Path, tmp_path: Path):
    """스크래치패드 파일 위에는 vway-kit 프로젝트가 없으니 무효화할 증거도 없음."""
    run(project, payload(str(tmp_path / "scratchpad" / "note.md")))
    for name in MARKERS:
        assert (vdev(project) / name).exists(), (
            f"{name} 이 스크래치패드 쓰기에 무효화됐다 — 임시 파일마다 재리뷰 비용이 붙는다"
        )


def test_a_write_into_the_evidence_dir_does_not_void_the_evidence(project: Path):
    run(project, payload(str(vdev(project) / "tier")))
    for name in MARKERS:
        assert (vdev(project) / name).exists(), f"{name} 이 증거 디렉터리 쓰기에 무효화됐다"


def test_a_backslash_spelled_write_into_the_evidence_dir_is_still_exempt(project: Path):
    """면제는 글로브이고 JSON 은 백슬래시를 두 배로 만듦: 하나씩 변환하면 경로는 세그먼트마다
    `//` 를 달고 도착하는데, 파일시스템은 삼키지만 어떤 글로브도 매치하지 않음."""
    win = str(vdev(project) / "tier").replace("/", chr(92))
    run(project, json.dumps({"tool_input": {"file_path": win}}))
    for name in MARKERS:
        assert (vdev(project) / name).exists(), f"{name} 이 증거 디렉터리 쓰기에 무효화됐다"


def test_a_payload_without_a_path_voids(project: Path):
    """편집이 어디 떨어졌는지 알 수 없음 → 지움. 반대는 아무도 보지 않은 편집 위에 마커를
    남기는 것이고, 그것이 이 훅이 절대 틀리면 안 되는 방향임."""
    run(project, payload(None))
    for name in MARKERS:
        assert not (vdev(project) / name).exists(), f"{name} 이 판정 불가 페이로드를 넘겼다"


def test_an_unparseable_payload_voids(project: Path):
    run(project, "not json at all")
    for name in MARKERS:
        assert not (vdev(project) / name).exists(), f"{name} 이 파싱 불가 페이로드를 넘겼다"


def test_a_windows_spelled_path_still_names_its_own_tree(project: Path, tmp_path: Path):
    """페이로드는 OS 자신의 철자를 실음: Windows 에서는 JSON 이스케이프된 백슬래시 경로.
    변환하지 않으면 어떤 구분자도 구분자가 아니고, 훅은 편집 위치를 못 잡아 세션의 프로젝트
    디렉터리로 물러서서 엉뚱한 트리를 무효화하며, 편집된 트리는 증거를 그대로 가짐.
    프로젝트 디렉터리만 보는 단언으로는 그걸 볼 수 없음 — 폴백도 거기 떨어지기 때문."""
    worktree = repo(tmp_path / "project-feature")
    wt_vdev = vdev(worktree)

    win = str(worktree).replace("/", chr(92)) + chr(92) + "src" + chr(92) + "app.py"
    run(project, json.dumps({"tool_input": {"file_path": win}}))

    for name in MARKERS:
        assert not (wt_vdev / name).exists(), f"{name} 이 백슬래시 철자 경로를 넘겼다"
        assert (vdev(project) / name).exists(), f"{name} 이 죽었다: 편집이 엉뚱한 트리에 떨어졌다"


def test_the_first_path_in_the_payload_is_the_one_that_was_edited(project: Path, tmp_path: Path):
    """`tool_response` 가 `tool_input` 뒤에 자기 경로를 한 번 더 실음. 마지막을 읽으면 응답
    필드가 판정하고, 다른 곳을 가리키는 응답이 마커를 살려 줌."""
    body = {
        "tool_input": {"file_path": str(project / "src" / "app.py")},
        "tool_response": {"file_path": str(tmp_path / "elsewhere" / "app.py")},
    }
    run(project, json.dumps(body))
    for name in MARKERS:
        assert not (vdev(project) / name).exists(), f"{name} 이 살았다: tool_response 가 판정했다"


def test_an_edit_in_a_worktree_voids_the_worktree_s_own_evidence(project: Path, tmp_path: Path):
    """게이트는 `git -C <wt> commit` 이 지목하는 worktree 로 ROOT 를 재지정하므로, 거기서 읽는
    마커는 그 worktree 의 것. CLAUDE_PROJECT_DIR 만 아는 훅은 바로 그것들을 살려 둠 —
    리뷰는 worktree 에서 통과하고, 수정도 거기 떨어지고, 스킬이 스스로 지시하는 커밋이 아무도
    다시 벌지 않은 증거 위로 통과함."""
    worktree = worktree_of(project, tmp_path / "project-feature")

    run(project, payload(str(worktree / "src" / "app.py")))

    for name in MARKERS:
        assert not (vdev(worktree) / name).exists(), f"{name} 이 자기 worktree 의 편집을 넘겼다"


def test_an_edit_in_a_worktree_also_voids_the_tree_the_gate_falls_back_to(
    project: Path, tmp_path: Path
):
    """게이트는 올라탄 브랜치에서 worktree 이름을 댐. detached HEAD 나 worktree 엔트리에 없는
    브랜치는 세션의 프로젝트 디렉터리로 되돌림(Invariant 7 이 그 불확실성을 main 쪽으로 겨눠
    둠). 두 트리 모두 가능한 답이므로, 편집된 쪽만 무효화하면 게이트는 편집이 닿지 않은
    마커를 읽음."""
    worktree = worktree_of(project, tmp_path / "project-feature")

    run(project, payload(str(worktree / "src" / "app.py")))

    for name in MARKERS:
        assert not (vdev(project) / name).exists(), (
            f"{name} 이 게이트가 물러서는 트리에 남았다 — 같은 repo 안의 편집인데도"
        )


def test_a_sibling_directory_is_not_inside_the_project(project: Path, tmp_path: Path):
    """`…/project-feature` 는 문자열로는 `…/project` 로 시작함. 접두 매칭이면 안쪽이라고
    부르고 엉뚱한 트리의 증거를 무효화함."""
    sibling = repo(tmp_path / "project-feature")
    run(project, payload(str(sibling / "src" / "app.py")))
    for name in MARKERS:
        assert (vdev(project) / name).exists(), f"{name} 이 형제 repo 의 편집에 무효화됐다"


def test_a_notebook_edit_is_an_edit(project: Path, tmp_path: Path):
    """`NotebookEdit` 는 `notebook_path` 로 적음. 읽지 않으면 경로가 아예 없는 페이로드가 됨:
    세션의 증거는 자기 안에 없던 편집 때문에 죽고, 편집된 트리는 그 편집이 낡게 만든 증거를
    그대로 가짐 — 두 방향이 한꺼번에 틀림."""
    worktree = repo(tmp_path / "project-feature")

    run(project, payload(str(worktree / "nb" / "analysis.ipynb"), key="notebook_path"))

    for name in MARKERS:
        assert not (vdev(worktree) / name).exists(), f"{name} 이 노트북 편집을 넘겼다"
        assert (vdev(project) / name).exists(), f"{name} 이 죽었다: 노트북은 다른 곳에 있었다"


def test_a_nested_repo_answers_for_itself(project: Path):
    """다른 repo 안에 체크아웃된 repo 는 자기 게이트를 가진 자기 트리임. 걸음은 첫 루트에서
    멈추므로, 이 파일들을 한 번도 덮은 적 없는 바깥 프로젝트의 증거는 남음."""
    inner = repo(project / "vendor" / "sub")

    run(project, payload(str(inner / "src" / "lib.py")))

    for name in MARKERS:
        assert not (vdev(inner) / name).exists(), f"{name} 이 자기를 위한 repo 의 편집을 넘겼다"
        assert (vdev(project) / name).exists(), f"{name} 이 그 파일을 본 적 없는 트리에서 죽었다"


def test_a_project_above_this_one_keeps_its_evidence(tmp_path: Path):
    """첫 repo 루트가 아니라 첫 증거 디렉터리까지 걸으면 편집된 repo 밖으로 나가, 그 편집과
    아무 상관 없는 프로젝트의 게이트를 되돌림."""
    parent = repo(tmp_path / "parent")
    child = repo(tmp_path / "parent" / "child", evidence=False)

    run(child, payload(str(child / "src" / "app.py")))

    for name in MARKERS:
        assert (vdev(parent) / name).exists(), f"{name} 이 더 위 프로젝트에서 무효화됐다"


def test_a_tree_with_no_repo_root_voids_nothing(tmp_path: Path):
    """파일 위에 루트가 없으니 그 편집을 주장하는 트리도 없음 — 그 마커를 읽을 게이트가
    존재하지 않음."""
    loose = tmp_path / "loose"
    vdev(loose).mkdir(parents=True)
    for name in MARKERS:
        (vdev(loose) / name).touch()

    out = run(None, payload(str(loose / "src" / "app.py")))

    assert out.returncode == 0
    for name in MARKERS:
        assert (vdev(loose) / name).exists(), f"{name} 이 어떤 repo 밖에서도 무효화됐다"


def test_a_relative_worktree_pointer_still_names_one_repo(project: Path, tmp_path: Path):
    """`git worktree add --relative-paths` 는 포인터를 worktree 기준 상대 경로로, `..` 까지
    붙여 씀. 텍스트로 비교하면 다른 repo 이고 디렉터리로 비교하면 같은 repo 인데, 그 차이가
    게이트가 물러서는 트리에 낡은 마커가 남는지를 정함."""
    worktree = worktree_of(
        project,
        tmp_path / "project-feature",
        gitdir=f"../{project.name}/.git/worktrees/project-feature",
    )

    run(project, payload(str(worktree / "src" / "app.py")))

    for name in MARKERS:
        assert not (vdev(project) / name).exists(), (
            f"{name} 이 폴백 트리에 남았다: 상대 포인터를 다른 repo 로 읽었다"
        )


def test_a_crlf_pointer_file_still_names_one_repo(project: Path, tmp_path: Path):
    """CRLF 로 다시 쓰인 포인터는 경로에 CR 을 달아 놓아 아무 디렉터리도 가리키지 않음 —
    그것은 두 루트가 다르다는 증명이 못 되고, 합집합은 그래도 일어나야 함. 프로젝트 자신의
    포인터여야 함: worktree 쪽 포인터라면 CR 이 읽기가 잘라내는 `/worktrees/…` 안에 앉음."""
    external = tmp_path / "gitdata"
    external.mkdir()
    (project / ".git").rmdir()
    (project / ".git").write_text(
        f"gitdir: {external.as_posix()}" + chr(13) + chr(10), encoding="utf-8"
    )
    worktree = worktree_of(
        project, tmp_path / "project-feature", gitdir=f"{external.as_posix()}/worktrees/wt"
    )

    run(project, payload(str(worktree / "src" / "app.py")))

    for name in MARKERS:
        assert not (vdev(project) / name).exists(), f"{name} 이 남았다: CR 이 repo 를 잃었다"
        assert not (vdev(worktree) / name).exists(), f"{name} 이 편집된 트리에 남았다"


def test_a_pointer_to_a_repo_that_moved_proves_nothing(project: Path, tmp_path: Path):
    """메인 repo 가 이사하거나 개명된 worktree 는 `git worktree repair` 전까지 사라진 디렉터리를
    가리킴. 두 경로가 같은지 파일시스템에 물으면 아무것도 가리키지 않는 경로에는 아니오가
    돌아오는데, 그 아니오는 다름의 증명이 아님. 게이트도 그 worktree 를 해석하지 못해
    프로젝트 디렉터리를 읽음: 마커를 남기면 안 되는 바로 그 트리."""
    worktree = worktree_of(
        project,
        tmp_path / "project-feature",
        gitdir=f"{tmp_path.as_posix()}/gone/.git/worktrees/wt",
    )

    run(project, payload(str(worktree / "src" / "app.py")))

    for name in MARKERS:
        assert not (vdev(project) / name).exists(), (
            f"{name} 이 남았다: 아무데도 없는 곳을 가리키는 포인터를 다른 repo 로 읽었다"
        )


def test_a_session_opened_below_the_repo_root_is_still_this_tree(project: Path):
    """`/vdev-init` 은 세션의 프로젝트 디렉터리에 증거를 설치하고, 그 자리가 repo 루트일 필요는
    없음. 그 디렉터리는 루트가 아니므로 다른 repo 라는 증명이 서지 않음 — 그리고 게이트가
    읽는 것이 그 증거."""
    below = project / "services" / "api"
    vdev(below).mkdir(parents=True)
    for name in MARKERS:
        (vdev(below) / name).touch()

    run(below, payload(str(project / "src" / "app.py")))

    for name in MARKERS:
        assert not (vdev(below) / name).exists(), f"{name} 이 게이트가 읽는 디렉터리에 남았다"


def test_no_project_dir_is_quiet(tmp_path: Path):
    out = run(None, payload(str(tmp_path / "a.py")))
    assert out.returncode == 0 and out.stdout.strip() == ""


def test_no_evidence_dir_is_quiet(tmp_path: Path):
    (tmp_path / "bare").mkdir()
    out = run(tmp_path / "bare", payload(str(tmp_path / "bare" / "a.py")))
    assert out.returncode == 0 and out.stdout.strip() == ""


def test_it_says_so_only_when_it_actually_voided_something(project: Path):
    """편집마다 컨텍스트를 붙이면 소음이고, 한 번도 안 붙이면 에이전트는 자기가 잃은 줄 모르는
    게이트를 다시 밟지 않음."""
    first = run(project, payload(str(project / "src" / "app.py")))
    assert "review" in json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"]
    second = run(project, payload(str(project / "src" / "app.py")))
    assert second.stdout.strip() == "", "무효화할 마커가 없는데 또 말했다"


def test_voiding_two_trees_names_each_gate_once(tmp_path: Path):
    main = repo(tmp_path / "main")
    wt = worktree_of(main, tmp_path / "wt")
    out = run(main, payload(str(wt / "a.txt")))
    assert not any((vdev(t) / m).exists() for t in (main, wt) for m in MARKERS)
    context = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "이 편집이 review, doc-sync 게이트 증거를" in context, context


HOOKS_JSON = REPO / "hooks" / "claude" / "hooks.json"
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def test_the_hook_is_registered_for_every_tool_that_edits_a_file():
    """아무도 부르지 않는 스크립트는 조용히 꺼진 게이트임. 매처가 곧 등록의 전부 — 거기 빠진
    도구는 증거를 세워 둔 채 파일을 편집함."""
    entries = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
    registered = [
        (e["matcher"], h["command"])
        for e in entries
        for h in e["hooks"]
        if SCRIPT.name in h["command"]
    ]
    assert registered, f"{SCRIPT.name} 이 어떤 PostToolUse 엔트리에도 등록되지 않았다"
    matcher, command = registered[0]
    named = set(matcher.split("|"))
    assert set(EDIT_TOOLS) <= named, (
        f"{set(EDIT_TOOLS) - named} 는 파일을 편집하는데 증거를 안 지운다"
    )

    # 훅은 파일 이름을 적은 한 줄의 텍스트: 이름이 명령에 보인다고 경로가 풀린다는 증명이
    # 되지 않고, 아무것도 가리키지 않는 명령은 조용히 아무것도 실행하지 않음.
    quoted = re.fullmatch(r'"\$\{CLAUDE_PLUGIN_ROOT\}"/(\S+)', command)
    assert quoted, f"명령이 플러그인 루트 아래 경로를 가리키지 않는다: {command}"
    named_file = REPO / quoted.group(1)
    assert named_file.is_file(), f"등록된 명령이 가리키는 {named_file} 가 없다"
