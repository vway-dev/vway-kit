"""vdev 게이트 테스트가 공유하는 헬퍼 — 저장소 만들기 · 러너 구동 · 파라미터 표.

게이트는 실제 셸에서 도는 것이 계약이라, 여기 헬퍼는 대부분 진짜 git 저장소와 진짜
bash 를 세움. 분류별 테스트 파일이 같은 저장소 모양을 쓰기 때문에 여기가 그 SSOT.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.vdev_gate_check as fgc
from tests._non_utf8 import stdio_host_env
from tests._proc import run_bounded


def _run(args, cwd):
    run_bounded(args, cwd=str(cwd), check=True, text=True)


def _repo_with_worktree(tmp_path: Path):
    """main repo + feature/x 체크아웃한 형제 worktree 를 만들어 (main, wt) 반환."""
    main = tmp_path / "main"
    main.mkdir()
    _run(["git", "init", "-b", "main"], main)
    _run(["git", "config", "user.email", "t@t"], main)
    _run(["git", "config", "user.name", "t"], main)
    (main / "f.txt").write_text("x", encoding="utf-8")
    _run(["git", "add", "."], main)
    _run(["git", "commit", "-m", "init"], main)
    wt = tmp_path / "main-feature"
    _run(["git", "worktree", "add", str(wt), "-b", "feature/x"], main)
    return main, wt


def _run_main(root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root), "PYTHONIOENCODING": "utf-8"}
    return run_bounded(
        [sys.executable, "scripts/vdev_gate_check.py"],
        cwd=Path(__file__).resolve().parent.parent.parent,
        env=env,
        text=True,
        encoding="utf-8",
    )


_MODCFG = (
    "branches:\n  production: main\n"
    "modules:\n"
    "  - name: api\n    path: services/api/\n"
    "    checks:\n"
    "      lint: 'ruff check services/api'\n"
    "      test: 'pytest services/api'\n"
    "      security: 'bandit -r services/api'\n"
    "  - name: web\n    path: services/web/\n"
    "    checks:\n      lint: 'eslint web'\n"
)


def _write_modcfg(tmp_path: Path) -> None:
    cfg = tmp_path / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(_MODCFG, encoding="utf-8")


# 확장 형식({run, when}) + 문자열 혼합 — 하위호환·라우팅·오류값 검증용
_TIMINGCFG = (
    "modules:\n"
    "  - name: api\n    path: services/api/\n"
    "    checks:\n"
    "      lint: 'ruff check services/api'\n"  # 문자열 → every-commit
    "      security: 'bandit -r services/api'\n"  # 문자열 security → promotion
    "      license-check: { run: 'reuse lint', when: every-commit }\n"  # 확장 → every-commit
    "      perf-bench: { run: 'pytest bench', when: promotion }\n"  # 확장 → promotion
    "      typecheck: { run: 'mypy services/api' }\n"  # when 생략 → 키기본 every-commit
    "      audit: { run: 'pip-audit', when: bogus }\n"  # 오류값 → 키기본 every-commit
)


def _write_timingcfg(tmp_path: Path) -> None:
    cfg = tmp_path / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(_TIMINGCFG, encoding="utf-8")


# 위의 모든 merge 테스트는 체인을 `&&` 로 쓰는데, 셸은 개행이나 `;` 로도 똑같이 명령을 가름.
# 그 사각지대는 초록불로 지나감: `\n` 이 빠진 _SHELL_SEP_RE 에서는 피연산자 영역이 줄
# 끝을 넘어가 모든 switch 가 불명확으로 읽히고, 개행으로 나뉜 모든 merge 가 HEAD 폴백으로
# 떨어져 게이트를 통과함. 그래서 구분자는 케이스 작성자의 서식 취향이 아니라 **명시적 축**.
_SEPS = pytest.mark.parametrize("sep", [" && ", "\n", "; "], ids=["and", "newline", "semicolon"])

# merge-strategy 의 "Merging feature/* → integration" 블록 그대로: 개행으로 나뉜 3줄.
_DOC_IDIOM = ["git switch dev", "git pull --ff-only origin dev", "git merge --squash feature/x"]


BRANCHES = {
    "integration": "dev",
    "staging": "stage",
    "production": "main",
    "feature_prefix": "feature/",
}

RULES = [
    {
        "source": "feature/*",
        "target": "integration",
        "require": "--squash",
        "warn_unless_rebased": True,
    },
    {"source": "integration", "target": "staging", "require": "--no-ff"},
    {"source": "hotfix/*", "target": "production", "require": "--squash"},
    {"source": "staging", "target": "production", "require": "--no-ff"},
    {"source": "fix/*", "target": "integration", "forbid": "--no-ff"},
]


def _write_policy(tmp_path: Path) -> Path:
    """호스트 레이아웃: .claude/vway-kit/config/{vdev-tiers,vdev-config}.yaml"""
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-tiers.yaml").write_text(
        "tiers:\n  dev:\n    gates: [review]\n"
        "merge_strategy:\n"
        '  - source: "feature/*"\n'
        "    target: integration\n"
        '    require: "--squash"\n'
        "    warn_unless_rebased: true\n"
        "  - source: integration\n"
        "    target: staging\n"
        '    require: "--no-ff"\n'
        "  - source: staging\n"
        "    target: production\n"
        '    require: "--no-ff"\n'
        # 출하 정책의 forbid 행. 이것이 없으면 forbid 쪽 경로를 이 픽스처로 잴 수 없음.
        '  - source: "fix/*"\n'
        "    target: integration\n"
        '    forbid: "--no-ff"\n',
        encoding="utf-8",
    )
    (cfg_dir / "vdev-config.yaml").write_text(
        "branches:\n  integration: dev\n  staging: stage\n  production: main\n"
        '  feature_prefix: "feature/"\n',
        encoding="utf-8",
    )
    return tmp_path


def _run_merge_check(monkeypatch, tmp_path: Path, command: str, branch):
    """stdin/브랜치를 스텁한 채 merge_check_output 을 호출하고 SystemExit 코드를 반환함."""
    import io

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # 판정이 git config 의 `pull.rebase` 를 읽으므로 개발자 머신의 전역 설정을 가림.
    empty = tmp_path / ".gitconfig-empty"
    empty.touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    fgc._rebase_config.cache_clear()
    monkeypatch.setattr(fgc, "_current_branch", lambda root: branch)
    monkeypatch.setattr(fgc, "_is_rebased", lambda root, source, target: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": command}})))
    with pytest.raises(SystemExit) as exc:
        fgc.merge_check_output()
    return exc.value.code


MULTI_MERGE = [
    # 소스를 지목하지 않는 머지가 앞에 서면, 그 뒤의 진짜 머지가 통째로 미판정으로 남음 —
    # 전략 판정은 이 게이트가 fail-open 하면 안 되는 셋 중 하나(Invariant #1 예외 3).
    ("git merge --abort && git merge --no-ff stage", [({"--no-ff"}, "stage")]),
    ("git merge --continue; git merge stage", [(set(), "stage")]),
    (
        "git merge feature/a && git merge --no-ff stage",
        [(set(), "feature/a"), ({"--no-ff"}, "stage")],
    ),
    # 닫는 괄호는 낱말을 끝냄. 안 끝내면 소스가 `stage)` 가 되고, 어떤 규칙에도 안 맞아
    # 판정이 사라짐.
    ("(git merge --no-ff stage)", [({"--no-ff"}, "stage")]),
    ("git merge --no-ff stage )", [({"--no-ff"}, "stage")]),
]


MERGE_SPELLINGS = [
    # `--classify` 는 이것들을 merge 로 답하는데 전략 판정만 조용히 비어 있음 —
    # fail-CLOSED 예외가 열린 채(실측: 러너 exit 0, 실제 git 은 부모 둘짜리 커밋).
    "git 'merge' --no-ff fix/x",
    'git "merge" --no-ff fix/x',
    "git \\merge --no-ff fix/x",
    'git merge"" --no-ff fix/x',
    "gi't' merge --no-ff fix/x",
    # 리다이렉션은 프로그램 **앞에** 서는 낱말이고, 피연산자 자리의 낱말도 아님.
    ">/dev/null git merge --no-ff fix/x",
    "git merge>/dev/null --no-ff fix/x",
    "git merge --no-ff>/dev/null fix/x",
    "git merge 2>&1 --no-ff fix/x",
    # 반대 옵션이 함께 서면 git 처럼 나중 것이 이김 — 여기선 `--no-ff`.
    "git merge --ff --no-ff fix/x",
]


ABBREVIATED_FLAGS = [
    # git 은 모호하지 않은 접두를 받음 — 실제 git 에서 `--no-f` 가 `--no-ff` 로 해석돼
    # 머지 커밋이 생김(실측). 정확한 문자열만 보면 그 한 글자로 forbid 가 비켜 감.
    ("git merge --no-ff fix/x", "dev", True),
    ("git merge --no-f fix/x", "dev", True),
    ("git merge --no fix/x", "dev", True),
    ("git merge fix/x", "dev", False),
    # require 쪽에도 같은 규칙 — 축약을 안 받으면 정상 명령이 오차단됨.
    ("git merge --squash feature/x", "dev", False),
    ("git merge --squa feature/x", "dev", False),
    ("git merge feature/x", "dev", True),
]


# ── 셸 러너 e2e (precommit-runner.sh 를 실제 bash 로 구동) ──────────────────────
# 셸 필터를 실행하는 테스트가 없으면 부분문자열 glob 이 `git -C <wt> commit` 을 놓치는
# 버그가 살아남음. 훅 런타임이 Windows 라 깨진 게이트는 FAIL-OPEN 으로 조용히 통과하므로,
# 셸을 실제로 돌리지 않으면 다음 파손도 드러나지 않음.


def _git_ok() -> bool:
    try:
        run_bounded(["git", "--version"], timeout=5)
        return True
    except Exception:
        return False


requires_git = pytest.mark.skipif(not _git_ok(), reason="git 필요")


def _rg(args: list[str], cwd: Path) -> None:
    run_bounded(["git", *args], cwd=str(cwd), text=True, check=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _rg(["init", "-b", "main"], path)
    _rg(["config", "user.email", "t@e.st"], path)
    _rg(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("x", encoding="utf-8")
    _rg(["add", "-A"], path)
    _rg(["commit", "-m", "init"], path)


def _repo_bash() -> str | None:
    """저장소 경로를 실제로 볼 수 있는 bash(Windows 의 Git Bash / POSIX 의 native bash).

    Windows PATH 는 `bash` 를 WSL 로 잡는 일이 잦은데 WSL 은 ``C:/…`` 경로에 접근하지 못하므로,
    후보를 직접 프로브하고 알려진 Git Bash 위치로 폴백함. None → 쓸 수 있는 bash 없음(skip)."""
    repo = Path(__file__).resolve().parent.parent.parent
    probe = f"{repo.as_posix()}/scripts/precommit-runner.sh"
    which = shutil.which("bash")
    candidates = [
        which,
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    for bash in candidates:
        if not bash or not (bash == which or Path(bash).exists()):
            continue
        try:
            r = run_bounded([bash, "-c", f'test -f "{probe}"'], timeout=10)
            if r.returncode == 0:
                return bash
        except Exception:
            continue
    return None


_REPO_BASH = _repo_bash()
requires_bash_git = pytest.mark.skipif(
    not (_REPO_BASH and _git_ok()), reason="저장소를 볼 수 있는 bash + git 필요"
)


def _classify_worktree_module(wt: Path) -> None:
    """worktree 에 dev tier 마커+증거와, staged 파일을 커버하는 모듈 하나를 줌."""
    vdev = wt / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:feature/x", encoding="utf-8")
    (vdev / "review.done").touch()
    (vdev / "doc-sync.done").touch()
    cfg = wt / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(
        "modules:\n  - name: api\n    path: services/api/\n"
        '    checks:\n      lint: "echo LINT_RAN"\n',
        encoding="utf-8",
    )
    (wt / "services" / "api").mkdir(parents=True)
    (wt / "services" / "api" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _rg(["add", "services/api/a.py"], wt)


def _run_runner(
    main: Path,
    command: str,
    dryrun: bool = True,
    plugin_root: Path | None = None,
    hook_cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    r"""러너를 실제 bash 로 구동.

    `env_extra` 는 호스트 인코딩을 흉내 내는 용도 — 기본값이 `PYTHONIOENCODING=utf-8` 을
    못 박고 있어서, 그 변수가 다르게 선 호스트를 이 하네스가 **볼 수 없었음**(Invariant 2 가
    바로 그 호스트를 말하는데도). 덮어쓸 수 있어야 그 호스트를 잼.

    페이로드는 `ensure_ascii=False` 로 씀. 비-ASCII 를 `\uXXXX` 로 도망시키면 바이트가 통째로
    ASCII 가 되어 인코딩 경로가 아예 실행되지 않고, 훅을 쓰는 쪽이 그렇게 해 주리라고 게이트가
    기대할 근거도 없음.
    """
    repo = Path(__file__).resolve().parent.parent.parent
    # 자식 env 는 `stdio_host_env` 로 지음 — `os.environ` 을 그대로 물려주면 세션 어딘가에서
    # `force_utf8_io()` 를 인프로세스로 부른 테스트가 남긴 `PYTHONUTF8` 이 딸려 와,
    # `PYTHONIOENCODING` 만 세운 호스트를 재려던 행이 둘 다 세운 행으로 무너짐(실측: 전량
    # 실행에서 실제로 그럼). 두 변수를 걷어낸 뒤 이 호출이 원하는 것만 세움.
    env = stdio_host_env(
        **{
            "CLAUDE_PROJECT_DIR": str(main),
            "CLAUDE_PLUGIN_ROOT": (plugin_root or repo).as_posix(),
            "VWAY_PRECOMMIT_DRYRUN": "1" if dryrun else "0",
            "PYTHONIOENCODING": "utf-8",  # 기본은 UTF-8 호스트 — `env_extra` 가 덮음
            **(env_extra or {}),
        }
    )
    hook = json.dumps(
        {"cwd": str(hook_cwd or main), "tool_input": {"command": command}}, ensure_ascii=False
    )
    # bash 는 argv 경로의 백슬래시를 먹으므로(C:\a\b → C:ab) 슬래시 경로로 넘김.
    return run_bounded(
        [_REPO_BASH, f"{repo.as_posix()}/scripts/precommit-runner.sh"],
        input=hook,
        env=env,
        text=True,
        encoding="utf-8",
    )


def _merge_repo(tmp_path: Path, *, branch: str | None, config: str) -> Path:
    """`config` 를 vdev-config.yaml 로 실은 깨끗한 저장소(선택적으로 새 `branch` 위).

    머지는 정의상 깨끗한 트리에서 돌므로 vdev-config 는 **커밋되어야** 함(/vdev-init 규약상
    git 추적 대상) — untracked 로 두면 트리가 더러워져 무관한 게이트가 먼저 막고 merge
    판정을 가림.
    """
    root = tmp_path / "main"
    _init_repo(root)
    if branch:
        _rg(["checkout", "-b", branch], root)
    cfg = root / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True)
    (cfg / "vdev-config.yaml").write_text(config, encoding="utf-8")
    _rg(["add", "-A"], root)
    _rg(["commit", "-m", "cfg"], root)
    return root


# ── wiki 런타임 게이트 (모듈 명령이 아니라 vdev 게이트의 프로세스 내부 단계) ──────
def _wiki_host(tmp_path: Path) -> Path:
    cfgdir = tmp_path / ".claude" / "vway-kit" / "config"
    cfgdir.mkdir(parents=True)
    (cfgdir / "vdev-config.yaml").write_text(
        "wiki:\n  enable: true\n  root: docs/\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    return tmp_path


def _classify_docs(root: Path) -> None:
    """docs tier 마커(현재 브랜치에 바인딩) + doc-sync 증거."""
    vdev = root / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True, exist_ok=True)
    branch = run_bounded(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        text=True,
        check=True,
    ).stdout.strip()
    (vdev / "tier").write_text(f"docs:{branch}", encoding="utf-8")
    (vdev / "doc-sync.done").touch()


def _main_gate(root: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    repo = Path(__file__).resolve().parent.parent.parent
    # `_run_runner` 와 같은 이유로 `stdio_host_env` 를 지남 — `env_extra` 를 받는 헬퍼는
    # 호스트 인코딩을 흉내 낼 수 있다는 뜻이고, `os.environ` 을 그대로 물려주면 세션에 남은
    # `PYTHONUTF8` 이 딸려 와 `PYTHONIOENCODING` 만 세운 호스트가 조용히 둘 다 세운 호스트가 됨.
    # 지금 호출자들은 그 키를 안 넘기므로 잠복이지만, 같은 두 줄로 닫힘.
    env = stdio_host_env(
        **{
            "CLAUDE_PROJECT_DIR": str(root),
            "CLAUDE_PLUGIN_ROOT": str(repo),
            "PYTHONIOENCODING": "utf-8",
            **(env_extra or {}),
        }
    )
    return run_bounded(
        [sys.executable, str(repo / "scripts" / "vdev_gate_check.py")],
        text=True,
        encoding="utf-8",
        env=env,
    )


# ── --classify: 이 명령이 무엇인가에 대한 유일한 권위 ─────────────────────────


def _classify(command: str, cwd: str | None = None, project: Path | None = None) -> str:
    repo = Path(__file__).resolve().parent.parent.parent
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    payload: dict[str, object] = {"tool_input": {"command": command}}
    if cwd:
        payload["cwd"] = cwd
    r = run_bounded(
        [sys.executable, str(repo / "scripts" / "vdev_gate_check.py"), "--classify"],
        input=json.dumps(payload),
        env=env,
        text=True,
        encoding="utf-8",
    )
    return r.stdout
