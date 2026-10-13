"""커밋이 실제로 도는 디렉터리 — `git -C` 와 선행 `cd` 읽기.

워크트리 재지정은 **커밋 경로 전용**이고 FAIL-OPEN — 불확실하면 `CLAUDE_PROJECT_DIR`
을 유지함. 형제 접두(`/repo` 와 `/repo-old`)를 같은 것으로 읽으면 안 됨.
"""

import os
import subprocess
from pathlib import Path

import pytest

import scripts._vway_paths as vp
from tests.vway_paths._helpers import (
    _repo_with_worktree,
)


def test_working_root_parses_git_dash_c(tmp_path: Path):
    main, wt = _repo_with_worktree(tmp_path)
    cmd = f'git -C "{wt}" commit -m "msg"'
    got = vp.working_root(project_dir=main, command=cmd)
    assert os.path.samefile(got, wt)


def test_working_root_parses_leading_cd(tmp_path: Path):
    main, wt = _repo_with_worktree(tmp_path)
    cmd = f'cd "{wt}" && git commit -m "msg"'
    got = vp.working_root(project_dir=main, command=cmd)
    assert os.path.samefile(got, wt)


def test_working_root_uses_hook_cwd(tmp_path: Path):
    main, wt = _repo_with_worktree(tmp_path)
    got = vp.working_root(project_dir=main, hook_cwd=str(wt), command="git commit -m x")
    assert os.path.samefile(got, wt)


def test_working_root_sibling_prefix_not_confused(tmp_path: Path):
    # wt 경로는 main 의 문자열 접두사를 포함(main-feature) — startswith 함정.
    main, wt = _repo_with_worktree(tmp_path)
    assert str(wt).startswith(str(main))  # 순진 prefix 라면 오탐
    got = vp.working_root(project_dir=main, command=f'git -C "{wt}" commit -m x')
    assert os.path.samefile(got, wt)  # common-dir 판정이라 정확


def test_working_root_unrelated_dir_falls_back(tmp_path: Path):
    main, _wt = _repo_with_worktree(tmp_path)
    outside = tmp_path / "outside"  # git repo 아님
    outside.mkdir()
    got = vp.working_root(project_dir=main, command=f'git -C "{outside}" commit -m x')
    assert os.path.samefile(got, main)  # 다른/무 repo → project_dir 폴백


def test_working_root_no_signal_returns_project_dir(tmp_path: Path):
    main, _wt = _repo_with_worktree(tmp_path)
    got = vp.working_root(project_dir=main, command="git commit -m x", hook_cwd=None)
    # 명령·cwd 신호 없음 → os.getcwd()(테스트 실행 repo)도 common-dir 불일치 → 폴백
    assert os.path.samefile(got, main)


def test_working_root_subdir_no_repoint(tmp_path: Path):
    # CLAUDE_PROJECT_DIR 이 git 루트의 하위 디렉터리(서브프로젝트에서 세션 시작):
    # worktree 가 아니므로 재지정 금지 — 루트로 끌어올리면 마커/‑config 위치가 어긋나
    # 정상 커밋을 fail-CLOSED 오차단함(리뷰 지적 회귀 방지).
    main, _wt = _repo_with_worktree(tmp_path)
    sub = main / "pkg" / "svc"
    sub.mkdir(parents=True)
    got = vp.working_root(project_dir=sub, hook_cwd=str(sub), command="git commit -m x")
    assert os.path.samefile(got, sub)  # 서브디렉터리 유지, 루트 이동 금지


def test_parse_git_dash_c_anchored_to_global_option():
    # 전역 옵션 위치(git 바로 뒤)의 -C 만 잡음.
    assert vp._parse_git_dash_c('git -C "/some/wt" commit -m x') == "/some/wt"
    # git commit -C <ref>(reuse-message)의 -C 는 잡지 않음(오탐 방지).
    assert vp._parse_git_dash_c("git commit -C HEAD -m x") is None


def test_git_survives_non_utf8_output(tmp_path: Path):
    # git 이 UTF-8 아닌 blob 을 뱉어도 _git 은 문자열을 돌려주고 예외를 넘기지 않음.
    # strict 디코드는 리더 스레드에서 터져 stdout 이 None 이 되고, try 밖의 .strip() 이
    # AttributeError 로 호출자를 뚫고 나가 wiki 게이트 전체(도장·drift·구조 위반)를
    # 그 커밋에서 통째로 건너뛰게 만듦 — Invariant #2 가 막으라는 바로 그 모양.
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)
    (tmp_path / "cp949.md").write_bytes("한글 본문\n".encode("cp949"))
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seed"],
        cwd=tmp_path,
        check=True,
    )
    out = vp._git(["show", "HEAD:cp949.md"], tmp_path)
    assert isinstance(out, str) and out  # 손상 문자여도 좋음 — 죽지만 않으면 됨


def test_unquote_path_joins_the_pieces_of_one_shell_word():
    # 셸이 붙여 주는 형태를 게이트도 같은 경로로 읽어야 함. 단어 전체에서 따옴표 문자를
    # 지우는 것과 다름 — 조각별 내용만 이어 붙임.
    assert vp.unquote_path('"$WT"/wt') == "$WT/wt"
    assert vp.unquote_path("'$WT'/wt") == "$WT/wt"
    assert vp.unquote_path('"C:/My Project/wt"') == "C:/My Project/wt"
    assert vp.unquote_path("/plain/wt") == "/plain/wt"
    assert vp.unquote_path('pre"mid"post') == "premidpost"


def test_parse_git_dash_c_reads_a_glued_path():
    # 통짜 대안으로 읽으면 `<부모>` 만 잡고 `/wt` 를 버려, 게이트가 커밋이 실제로 도는
    # 트리가 아닌 곳을 검사함 — 그 트리가 깨끗하면 미분류 커밋이 그대로 통과함.
    assert vp._parse_git_dash_c('git -C "/tmp/x"/wt commit -m x') == "/tmp/x/wt"
    assert vp._parse_git_dash_c("git -C '/tmp/x'/wt commit -m x") == "/tmp/x/wt"
    assert vp._parse_git_dash_c('git -C "/tmp/My Project/wt" commit -m x') == "/tmp/My Project/wt"
    assert vp._parse_git_dash_c("git commit -m x") is None
    # Windows 경로의 `\` 는 경로 토큰 안에서 구분자로 남음 — 옵션 영역 전용 규칙이
    # 경로 토큰으로 새면 백슬래시가 뒤 공백을 이스케이프해 서브커맨드까지 삼켜짐.
    assert vp._parse_git_dash_c(r"git -C C:\Work\repo commit -m x") == r"C:\Work\repo"
    assert vp._parse_git_dash_c(r"git -c k=v -C C:\Work\repo commit -m x") == r"C:\Work\repo"
    # 끝이 `\`+공백이면 None. bash 는 그걸 이스케이프된 공백으로 읽어 `-C` 값이
    # `C:\Work\repo commit` 이 되고 서브커맨드가 없는 명령이 됨 — 게이트가 읽는 것은
    # 셸 텍스트이므로 셸을 따름. 셸 self-filter 는 ERE 라 여기서 단어를 잇지 못해 이
    # 명령을 커밋으로 넘기지만, 파이썬 층이 드롭하는 방향은 FAIL-OPEN 이라 허용됨
    # (레이어 방향 불변식). skills/commit 이 따옴표를 지시하는 이유이기도 함.
    assert vp._parse_git_dash_c(r"git -C C:\Work\repo\ commit -m x") is None


def test_parse_git_dash_c_looks_past_other_global_options():
    # `-C` 는 git 전역 옵션이라 다른 전역 옵션 뒤에 올 수 있음. 앵커를 `git` 바로 뒤로
    # 좁히면 워크트리를 못 찾고, 게이트가 커밋이 도는 트리가 아닌 곳의 status·티어 마커·
    # 모듈 lint 를 읽음 — 그쪽이 깨끗하면 미분류 커밋이 그대로 통과함.
    assert vp._parse_git_dash_c('git -c k=v -C "/tmp/My Project"/wt commit -m x') == (
        "/tmp/My Project/wt"
    )
    assert vp._parse_git_dash_c("git --no-pager -C /plain/wt commit -m x") == "/plain/wt"
    # 서브커맨드 뒤의 `-C` 는 reuse-message 라 디렉터리가 아님. 인자를 받지 않는 전역
    # 옵션에까지 인자 슬롯을 주면 서브커맨드가 그 슬롯으로 빨려 들어가고, 그 뒤 아무 데나
    # 있는 `-C` 가 디렉터리로 읽힘 — 아래 세 줄이 그 세 가지 모양.
    assert vp._parse_git_dash_c("git --no-pager commit -C HEAD~1") is None
    # `--exec-path` 는 인자를 따로 받지 않음(붙여 씀) — 목록에 넣으면 서브커맨드가
    # 그 슬롯으로 빨려 들어감.
    assert vp._parse_git_dash_c("git --exec-path commit -C HEAD") is None
    assert vp._parse_git_dash_c("git --no-pager grep -C 3 foo ; git -C /wt commit -m x") == "/wt"


def test_every_arg_taking_global_option_lets_dash_c_through():
    # 이 목록이 `-C` 해석을 좌우함: 빠진 옵션이 앞에 오면 워크트리를 못 찾고, 없는
    # 옵션이 들어 있으면 서브커맨드가 인자 슬롯으로 빨려 들어감. git 이 별도 토큰으로
    # 받는 것은 아래 여덟 개뿐임(git 2.47 실측).
    for opt in (
        "-c k=v",
        "--git-dir /tmp/g",
        "--work-tree /tmp/w",
        "--namespace ns",
        "--config-env u=A",
        "--attr-source HEAD",
        "--shallow-file /tmp/s",
    ):
        assert vp._parse_git_dash_c(f"git {opt} -C /wt commit -m x") == "/wt", opt
    assert vp._parse_git_dash_c("git -C /wt --no-pager commit -C HEAD") == "/wt"


def test_parse_leading_cd_reads_a_glued_path():
    assert vp._parse_leading_cd('cd "/tmp/x"/wt && git commit -m x') == "/tmp/x/wt"
    assert vp._parse_leading_cd("git commit -m x") is None


# --- 커밋 트리를 한 곳으로 못 박는 명령 (Invariant 7 의 선언된 예외) ---


@pytest.mark.parametrize(
    "command,expected",
    [
        # `.` 는 "디렉터리 없음" 과 같은 답 — 두 판정이 이걸 다르게 읽으면 선두 `cd` 를
        # 안 읽고 깨끗한 main 을 검사함.
        ("cd /wt && git -C . commit -m x && git commit --amend", "/wt"),
        # `;` 로 이은 선두 `cd` 도 선두임. 안 읽으면 훅 cwd 기준으로 미분류 차단이 남.
        ("cd /main; git commit -m x", "/main"),
        ("cd /x;git commit -m x", "/x"),
        # 첫 `;` 에서 멈춰야 함. 탐욕이면 그것을 지나쳐 `/a;b` 를 답하는데, 셸이 실제로
        # 옮겨 가는 곳은 `/a` 임 — 앞의 두 케이스는 탐욕도 되감아 같은 답을 내므로 못 잡음.
        ("cd /a;b;git commit -m x", "/a"),
        # 안 펼쳐진 값은 디렉터리가 아님 — 명령에서 읽지 않고 다음 단계로.
        ('for d in a b; do git -C "$d" commit -m x; done', None),
        ("git -C 'wt-*' commit -m x", None),
        # 선두 `cd` 의 값도 같은 정규화를 받아야 함. `-C` 만 덮으면 안 펼쳐진 텍스트가
        # 디렉터리 이름으로 나가고, 해석기가 그것을 못 찾아 깨끗한 main 에 남음 —
        # 러너가 거기서 조기 종료해 진짜 커밋에서 게이트가 통째로 빠짐(실측: rc 2 → 0).
        ("cd $WT && git commit -m x", None),
        ("cd $(pwd) && git commit -m x", None),
        ("cd 'wt-*' && git commit -m x", None),
        ("cd /wt/$BR && git commit -m x", None),
    ],
    ids=[
        "dot-normalised",
        "cd-semicolon",
        "cd-semicolon-glued",
        "cd-semicolon-two-commands",
        "unexpanded",
        "glob",
        "cd-unexpanded",
        "cd-substitution",
        "cd-glob",
        "cd-embedded-var",
    ],
)
def test_dir_from_command_pins_the_tree_or_declines(command: str, expected: str | None):
    assert vp._dir_from_command(command) == expected


def test_a_tilde_is_expanded_rather_than_read_as_a_directory_named_tilde():
    assert vp._dir_from_command("git -C ~/wt commit -m x") == os.path.expanduser("~/wt")
    # 선두 `cd` 도 같음 — 뜻이 하나인 `~` 는 펼치고, 뜻이 여럿인 `$`·백틱·glob 만 미해결.
    assert vp._dir_from_command("cd ~/wt && git commit -m x") == os.path.expanduser("~/wt")


@pytest.mark.parametrize(
    "command",
    [
        # 따라갈 수 없는 디렉터리 이동이 인자 없는 커밋 앞에 섬.
        "cd /wt1 && git commit -m x; cd /wt2 && git commit -m y",
        "(cd /wt && git commit -m x)",
        "pushd /wt && git commit -m x",
        # 안 펼쳐진 `-C`.
        'for d in a b; do git -C "$d" commit -m x; done',
        "git -C $(pwd) commit -m x",
        "git -C 'wt-*' commit -m x",
        # 안 펼쳐진 선두 `cd` — 어느 트리로 풀리든 그 트리가 깨끗하다는 사실이
        # 이 명령이 커밋하는지에 대해 아무것도 말해 주지 않음.
        "cd $WT && git commit -m x",
        "cd $(pwd) && git commit -m x",
        "cd 'wt-*' && git commit -m x",
        # 호출들이 서로 다른 트리를 지목.
        "git -C /a commit -m x && git -C /b commit -m y",
    ],
)
def test_commit_tree_unresolved_when_the_tree_cannot_be_pinned(command: str):
    assert vp.commit_tree_unresolved(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m x",
        "git -C /wt commit -m x",
        "cd /wt && git commit -m x",
        "cd /wt && git -C . commit -m x && git commit --amend",
        # `~` 는 뜻이 하나라 펼쳐지고, 그러면 트리를 댄 것임.
        "cd ~/wt && git commit -m x",
        # 커밋 **뒤**의 이동은 그 커밋이 어디서 도는지 안 바꿈.
        "git commit -m x && cd ..",
        # 따옴표·heredoc 본문 안의 `cd` 는 마스크에서 지워짐.
        "git commit -m 'cd /elsewhere'",
    ],
)
def test_commit_tree_resolved_for_a_command_that_names_one_tree(command: str):
    assert vp.commit_tree_unresolved(command) is False
