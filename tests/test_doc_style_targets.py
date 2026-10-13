"""doc-style 이 **어느 파일을 보는가** — 목록이 조용히 줄면 판정이 통째로 빠짐.

`lint_paths` 는 못 읽는 경로를 건너뜀(FAIL-OPEN 은 호출자 `doc_style_gate` 가 보장). 그래서
목록을 만드는 쪽이 경로 하나를 조각내면 그 파일은 **초록인 채로** 문체 게이트 밖에 남음.
CLAUDE.md 상 이 CI 가 트리 전체의 유일한 판정자라, 그 손실을 다른 층이 안 받아 줌.

재는 것은 목록 산출 둘 — 워크플로의 셸 파이프라인, 그리고 경로 목록을 git 에 묻는 파이썬
호출부 전부. 검사기 자체의 판정은 `tests/doc_style/` 가 잼.
"""

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

import scripts._vway_paths as _vway_paths
from tests._bash import BASH
from tests._proc import run_bounded
from tests.skill_docs._helpers import _runnable

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/doc-style.yml"

# 목록을 조각내는 두 경로 모양. 공백은 낱말 분할로, 비ASCII 는 git 의 C-인용(`core.quotePath`
# 기본값)으로 깨짐 — 한글이 기본인 저장소에서 뒤쪽은 가정이 아니라 예정된 일.
_SPACED = "sub dir/space name.md"
_HANGUL = "한글 문서.md"
_VIOLATION = "# t\n\n이 문서는 산문이다.\n"


def _bash_script(script: str, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    """스텝을 러너와 같은 꼴로 돌림 — `shell:` 미지정 스텝은 `bash -e <파일>`, stdin 없음.

    이 저장소의 워크플로는 `shell:` 을 하나도 안 적으므로 전부 그 기본값. 그래서 검사도 같은
    꼴이어야 판정이 러너의 판정과 같음. 출력을 파이프 대신 파일로 받는 근거는 `tests/_proc.py`."""
    assert BASH is not None, "no usable bash — 호출측 skipif 가 빠짐"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "step.sh"
        path.write_bytes(script.encode("utf-8"))
        return run_bounded(
            [BASH, "-e", path.as_posix()],
            cwd=cwd,
            timeout=300,
            env={**os.environ, **{k: str(v) for k, v in env.items()}, "PYTHONUTF8": "1"},
        )


def _lint_step() -> str:
    """워크플로의 `Lint prose` 스텝 본문. 이름이 바뀌면 여기서 멈춤."""
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["doc-style"]["steps"]
    named = [s for s in steps if s.get("name") == "Lint prose"]
    assert len(named) == 1, f"`Lint prose` 스텝이 {len(named)}개 — 이름이 바뀜"
    return named[0]["run"]


def _env() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["doc-style"]["env"]


def test_the_lint_step_carries_the_nul_separator_through_every_stage():
    """`-z`·`grep -z`·`xargs -0` 는 셋이 한 묶음 — 하나만 빠지면 더 나빠짐.

    `ls-files -z` 만 켜면 뒤의 두 단계가 NUL 을 낱말 구분으로 안 읽어 목록 전체가 인자
    **하나**로 뭉치고, 그러면 아무 파일도 안 열림. 하나씩 고치는 편집을 막으려고 셋을 함께 잼."""
    # 주석을 지우고 봄 — 사유 주석이 같은 낱말을 담고 있어, 날 텍스트로 재면 명령에서
    # 플래그를 빼도 검사가 통과함. 줄 전체 주석과 꼬리 주석 **둘 다** 그러므로, 무엇이
    # 주석인지는 게이트 자신의 인용 권위가 정함(`_runnable`).
    step = _runnable(_lint_step())
    for fragment in ("ls-files -z", "grep -z", "xargs -0", "-o pipefail"):
        assert fragment in step, (
            f"`Lint prose` 명령에 {fragment!r} 가 없음 — 목록이 조각나거나 빈 목록이 초록이 됨"
        )


@pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
def test_the_lint_step_reaches_a_file_whose_name_needs_quoting(tmp_path: Path):
    """출하 파이프라인을 **그대로** 돌려, 이름이 인용을 요구하는 파일까지 닿는지 봄.

    위 테스트는 철자를 재고 이것은 결과를 잼 — 셋을 다 적어 놓고도 파이프 순서가 어긋나면
    철자 검사는 통과함. 위반은 한글 이름 파일에만 심으므로, 목록이 그 파일을 놓치면 종료
    코드가 0 이 되고 그것이 곧 이 버그의 증상임."""
    repo = tmp_path / "host"
    (repo / "sub dir").mkdir(parents=True)
    (repo / "plain.md").write_text("# t\n\n제목만 있는 문서.\n", encoding="utf-8")
    (repo / _SPACED).write_text("# t\n\n제목만 있는 문서.\n", encoding="utf-8")
    (repo / _HANGUL).write_text(_VIOLATION, encoding="utf-8")
    for cmd in (["init", "-q", "."], ["add", "-A"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)

    env = _env()
    script = (REPO / "scripts/doc_style_check.py").as_posix()
    run = _lint_step().replace(
        "uv run python scripts/doc_style_check.py", f'"{sys.executable}" "{script}"'
    )
    assert run != _lint_step(), (
        "검사기 호출 철자가 바뀜 — 임시 저장소에서 `uv run` 이 돌아 판정이 딴 것을 잼"
    )
    proc = _bash_script(run, repo, env)
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert "ENDING" in out, f"인용이 필요한 이름의 파일이 검사에서 빠짐 — {out!r}"
    # `xargs` 는 자식이 1-125 로 죽으면 123 을 냄. CI 는 0 이 아닌 것만 보므로 값이 아니라
    # 0 이 아님을 잼 — 값을 못박으면 배치가 갈리는 날 사유 없이 붉어짐.
    assert proc.returncode != 0, f"위반이 있는데 통과 — {out!r}"


@pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
def test_an_empty_target_list_is_red_not_green(tmp_path: Path):
    """목록이 통째로 비면 실패여야 함 — 이 잡의 초록은 "산문이 규율을 지켰다" 는 뜻이므로.

    검사기는 인자 0개에 exit 0 을 냄(`nargs="*"`). 그래서 목록을 만드는 쪽이 무너진 것과
    트리가 깨끗한 것이 CI 에서 같은 색이 됨 — 위 테스트가 막는 손실의 극단이 이것."""
    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "plain.md").write_text("# t\n\n제목만 있는 문서.\n", encoding="utf-8")
    for cmd in (["init", "-q", "."], ["add", "-A"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)

    env = _env()
    env["DOC_STYLE_EXCLUDE"] = "."  # 모든 레코드가 걸려 선택이 0건
    script = (REPO / "scripts/doc_style_check.py").as_posix()
    run = _lint_step().replace(
        "uv run python scripts/doc_style_check.py", f'"{sys.executable}" "{script}"'
    )
    assert run != _lint_step(), (
        "검사기 호출 철자가 바뀜 — 임시 저장소에서 `uv run` 이 돌아 판정이 딴 것을 잼"
    )
    proc = _bash_script(run, repo, env)
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert proc.returncode != 0, f"고른 파일이 0건인데 통과 — {out!r}"


def test_the_runner_keeps_whitespace_that_belongs_to_a_name(tmp_path: Path):
    """`_git` 이 `-z` 를 보고 `.strip()` 을 거르는지 결과로 잼.

    재는 것이 없으면 `return out.stdout.strip()` 로 만드는 편집이 조용히 통과함. 선두 공백은
    이름의 일부라, 먹히면 그 경로는 존재하지 않게 되고 그 파일만 검사에서 빠짐."""
    repo = tmp_path / "lead"
    repo.mkdir()
    (repo / " lead.md").write_text("x\n", encoding="utf-8")
    for cmd in (["init", "-q", "."], ["add", "-A"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)

    assert _vway_paths._git(["ls-files", "-z"], repo) == " lead.md\0", (
        "`-z` 출력이 stripped 됨 — 선두 공백을 가진 경로가 목록에서 사라짐"
    )
    # 부정 분기는 목록형이 아닌 명령으로 잼 — `ls-files` 를 `-z` 없이 적으면 이 파일의
    # 다른 가드가 그 리터럴을 결함으로 읽음. `config --get` 은 경로를 안 내므로 대상 밖.
    assert _vway_paths._git(["config", "--get", "core.bare"], repo) == "false", (
        "`-z` 없는 출력까지 원문으로 나옴 — 파생 조건이 뒤집힘"
    )


# 경로 값을 **하나씩 소비하는** git 호출 전부. 목록이 비었는지만 보는 호출과 인자 매처는
# 대상이 아님 — 개별 경로를 안 읽으므로 조각나도 잃는 것이 없음. 소비자 템플릿
# `github/doc-style.workflow.example.yml` 도 빠짐: `--lint-config` 가 `os.walk` 로 트리를
# 걸어 셸 분할을 안 거침.
_PATH_LISTERS = (
    ".github/scripts/plugin_dist.py",
    "scripts/doc_invariants.py",
    "scripts/vdev_gate_check.py",
    "scripts/wiki_graph.py",
    "scripts/worklog.py",
    "tests/doc_style/test_scope_and_cli.py",
    "tests/test_doc_style_targets.py",
    "tests/test_plugin_dist.py",
    "tests/skill_docs/test_report_parsing.py",
    "tests/skill_docs/test_sandbox_fixtures.py",
    "tests/vdev_init/test_shell_line_endings.py",
)

# 경로 목록을 내는 git 철자. 한 자리에 둔 이유는 아래 둘이 서로 다른 집합을 보면 훑기가
# 지목하지 않는 호출부를 판독기가 영영 안 읽기 때문. 리스트·튜플 리터럴이 아니라 쪼갠
# 문자열인 것도 의도 — 리터럴로 두면 `_argv_literals` 가 이 상수를 git 호출로 읽음.
_LISTING_WORDS = tuple(
    "ls-files ls-tree diff-tree diff-index --name-only --name-status --porcelain --short".split()
)

# 경로 목록을 묻되 **소비는 안 하는** 자리. 사유를 적어 두는 이유는 위 목록이 조용히
# 미완성이 되는 것을 막기 위함 — 아래 XOR 검사가 둘 중 어디에도 없는 파일을 실패로 만듦.
_NOT_CONSUMED = {
    "scripts/skill_sandbox.py": "산문 — OUT_OF_REACH 사유문에 명령 이름만 등장함",
    "scripts/vdev_init_setup.py": "`stdout.strip()` 진위만 봄. 지울 대상은 경로 상수",
    "tests/eval_harness/_presuppositions.py": "출력이 비었는지만 봄(#git:has-staged 플래그)",
    "tests/inject_risk_tiers/test_hook_registration.py": "모드 칸만 읽음, 경로 분해 없음",
    "tests/vdev_init/test_gitignore.py": "stdout 전체에 대한 부분문자열 검사, 분해 없음",
    "tests/skill_docs/_helpers.py": "출하 문서의 명령 텍스트를 걷는 정규식 — git 출력이 아님",
    "tests/skill_docs/test_issued_commands.py": "출하 문서의 명령 텍스트를 읽음 — git 출력이 아님",
    "tests/wiki/test_node_set.py": "monkeypatch 인자 매처 — 호출부가 아님",
    "tests/wiki/test_stamp_renames.py": "주석 산문 — 그 인용 동작을 서술만 함",
}


def _argv_literals(text: str) -> list[list[str]]:
    """소스에 적힌 git 인자 리터럴 중 **경로 목록을 내는 것**만.

    정규식이 아니라 AST 로 읽음 — 철자를 재는 검사는 형식이 바뀌면 매치 0개가 되고, 그
    0개가 곧 초록이라 가드가 공허해짐. `_git([...])` 헬퍼 꼴과 `subprocess.run(["git", ...])`
    꼴이 저장소에 함께 있어 어느 한쪽 철자로는 못 덮음."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.List | ast.Tuple):
            continue
        words = [
            e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if any(word in words for word in _LISTING_WORDS):
            out.append(words)
    return out


@pytest.mark.parametrize("rel", _PATH_LISTERS, ids=_PATH_LISTERS)
def test_every_path_listing_call_asks_git_to_separate_by_nul(rel: str):
    """경로 목록을 개행으로 받으면 그 목록이 조각남 — 한 자리만 남아도 그쪽이 눈을 잃음."""
    path = REPO / rel
    assert path.is_file(), f"{rel} 이 없음 — 목록이 없는 제품을 서술함"
    calls = _argv_literals(path.read_text(encoding="utf-8"))
    # 매치 0개는 초록이 아니라 실패 — 다른 철자를 쓰는 파일은 이 판독기도 함께 고쳐야 함.
    assert calls, f"{rel}: 경로 목록 호출을 못 찾음 — 등록을 지우거나 판독기를 고칠 것"
    for words in calls:
        assert "-z" in words, f"{rel}: {words} 에 -z 가 없음"


def test_every_file_that_asks_git_for_paths_is_registered_or_exempted():
    """등록부 자체가 조용히 미완성이 되는 것을 막음 — 위 검사들은 등록된 파일만 봄.

    추적되는 `*.py` 를 훑어 git 에 경로를 묻는 파일을 모으고(셸·워크플로는 범위 밖 — 그쪽
    호출부는 위의 파이프라인 검사가 직접 잼), 각각이 `_PATH_LISTERS` 이거나
    `_NOT_CONSUMED` 이거나 **둘 중 하나**임을 요구(`skill_sandbox.OUT_OF_REACH` 와 같은 꼴).
    둘 다이거나 둘 다 아니면 실패 — 새 호출부가 커버리지 결정을 강제로 받게 됨."""
    listers, exempt = set(_PATH_LISTERS), set(_NOT_CONSUMED)
    tracked = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "*.py"],
        capture_output=True,
        text=True,
        # `errors="replace"` 가 없으면 UTF-8 아닌 경로 하나에 리더 스레드가 죽고 `stdout` 이
        # None 이 되어, 뒤의 `.split` 이 사유를 못 대는 AttributeError 로 바뀜.
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    for rel in (p for p in tracked.split("\0") if p):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if not any(word in text for word in _LISTING_WORDS):
            continue
        registered, listed = rel in listers, rel in exempt
        assert registered != listed, (
            f"{rel}: `_PATH_LISTERS` 이거나 `_NOT_CONSUMED` 이거나 둘 중 하나 — 지금은 "
            f"{'둘 다' if registered and listed else '어느 쪽도 아님'}"
        )
    stale = sorted((listers | exempt) - {p for p in tracked.split("\0") if p})
    assert not stale, f"등록부가 없는 파일을 지목함: {stale}"


def test_git_is_available_because_the_pipeline_check_needs_it():
    """git 부재는 스킵이 아니라 실패 — 출하 파이프라인을 실제로 돌리는 위 테스트가 못 돎."""
    assert shutil.which("git"), "no git on this host"
