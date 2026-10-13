"""`.github/scripts/plugin_dist.py` — `plugin` 브랜치가 런타임에 필요한 것을 빠짐없이, 개발 전용은
하나도 싣지 않는지 잼. 목록에 없는 새 런타임 파일은 소비자 설치에서 조용히 사라짐."""

from __future__ import annotations

import importlib.util
import json
import posixpath
import re
import zipfile
from pathlib import Path

import pytest

from tests._proc import run_bounded

REPO = Path(__file__).resolve().parents[1]
_SCRIPT = REPO / ".github" / "scripts" / "plugin_dist.py"
_spec = importlib.util.spec_from_file_location("plugin_dist", _SCRIPT)
dist = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dist)


def _git_files() -> list[str]:
    out = run_bounded(
        ["git", "-c", "core.quotePath=false", "ls-files", "-z", "--cached", "--others"]
        + ["--exclude-standard"],
        cwd=str(REPO),
        check=True,
    ).stdout
    return sorted({p for p in out.decode("utf-8").split("\0") if p and (REPO / p).is_file()})


FILES = _git_files()
SHIPPED = [p for p in FILES if dist.shipped(p)]
SHIPPED_SET = set(SHIPPED)
SHIPPED_DIRS = {posixpath.dirname(p) for p in SHIPPED} | {
    "/".join(p.split("/")[:i]) for p in SHIPPED for i in range(1, p.count("/") + 1)
}


@pytest.mark.parametrize(
    "dev_only",
    [
        "tests/",
        "evals/",
        ".github/",
        ".claude/",
        "docs/plugins/",
        "docs/superpowers/",
        "pyproject.toml",
        "uv.lock",
        "CHANGELOG.md",
        "scripts/skill_sandbox.py",
    ],
)
def test_dev_only_paths_stay_out(dev_only):
    leaked = [p for p in SHIPPED if p == dev_only or p.startswith(dev_only)]
    assert not leaked, leaked


def test_the_manifests_and_hooks_ship():
    for path in (
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        "hooks/claude/hooks.json",
        "assets/icon.png",
        dist.CLAUDE_MARKET,
        dist.CODEX_MARKET,
    ):
        assert path in SHIPPED_SET, path


def _resolves(target: str) -> bool:
    return target in SHIPPED_SET or target.rstrip("/") in SHIPPED_DIRS


_MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
# 호스트에 생성될 문서의 예시 링크 — 호스트의 docs/ 에서 풀림.
_HOST_DOC_EXAMPLES = {
    "rules/harness-rules.md",
    "skills/harness-authoring/references/tech-doc-guide.md",
}


def test_every_relative_link_in_a_shipped_doc_stays_inside_dist():
    broken = []
    for path in SHIPPED:
        if not path.endswith(".md") or path in _HOST_DOC_EXAMPLES or "/templates/" in path:
            continue
        text = _FENCE.sub("", (REPO / path).read_text(encoding="utf-8"))
        for target in _MD_LINK.findall(text):
            if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith(("#", "<")):
                continue
            rel = posixpath.normpath(posixpath.join(posixpath.dirname(path), target.split("#")[0]))
            if not _resolves(rel):
                broken.append(f"{path} -> {target}")
    assert not broken, broken


_PLUGIN_PATH = re.compile(r"\$\{?(?:CLAUDE_)?PLUGIN_ROOT\}?\"?/([\w./-]+)")


def test_every_plugin_root_path_a_shipped_file_names_ships():
    missing = []
    for path in SHIPPED:
        try:
            text = (REPO / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for target in _PLUGIN_PATH.findall(text):
            target = target.rstrip(".")
            if not _resolves(target):
                missing.append(f"{path} -> {target}")
    assert not missing, missing


_MARKET = {"name": "m", "plugins": [{"name": "vway-kit", "source": {"source": "x"}}]}


@pytest.fixture
def source_repo(tmp_path, monkeypatch):
    """출하·비출하 파일과 두 마켓이 든 최소 저장소 — cwd 를 그 안으로 옮김."""

    def git(*args: str) -> str:
        return run_bounded(["git", *args], cwd=str(tmp_path), check=True).stdout.decode().strip()

    files = {
        "hooks/x.sh": "#!/bin/sh\n",
        "hooks/claude/hooks.json": "{}\n",
        ".claude-plugin/plugin.json": "{}\n",
        dist.CLAUDE_MARKET: json.dumps(_MARKET),
        dist.CODEX_MARKET: json.dumps(_MARKET),
        "skills/s/SKILL.md": "s\n",
        "tests/t.py": "",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    git("init", "-q")
    git("add", ".")
    git("update-index", "--chmod=+x", "hooks/x.sh")
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "t")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "t@t")
    git("commit", "-q", "-m", "src")
    monkeypatch.chdir(tmp_path)
    return git


def test_build_keeps_modes_and_drops_the_rest(source_repo):
    first = dist.build("HEAD", None, "plugin")
    tree = source_repo("ls-tree", "-r", "--name-only", first).splitlines()
    assert "tests/t.py" not in tree and "hooks/x.sh" in tree
    assert "100755 " + source_repo("rev-parse", f"{first}:hooks/x.sh") in source_repo(
        "ls-tree", "-r", first
    ).replace(" blob ", " ")
    assert dist.build("HEAD", first, "plugin") == first, "트리가 같으면 새 커밋을 만들지 않음"


def test_build_turns_both_marketplaces_into_the_branch_root(source_repo):
    """브랜치에서는 플러그인이 곧 마켓 루트 — Codex 는 `url` 을 git 원격으로 읽으므로 `local`."""
    first = dist.build("HEAD", None, "plugin")
    claude = json.loads(source_repo("show", f"{first}:{dist.CLAUDE_MARKET}"))
    codex = json.loads(source_repo("show", f"{first}:{dist.CODEX_MARKET}"))
    assert claude["plugins"][0]["source"] == "./"
    assert codex["plugins"][0]["source"] == {"source": "local", "path": "./"}


def test_codex_zip_carries_no_lifecycle_hook(source_repo, tmp_path):
    """OpenAI 디렉터리는 훅 든 패키지를 거부함 — Claude 매니페스트·훅과 마켓 파일은 빠짐."""
    first = dist.build("HEAD", None, "plugin")
    out = tmp_path / "out" / "codex.zip"
    dist.codex_zip(first, out)
    names = zipfile.ZipFile(out).namelist()
    assert "hooks/x.sh" in names and "skills/s/SKILL.md" in names
    assert not [n for n in names if n.startswith(dist.CODEX_ZIP_SKIP)], names


def test_pin_points_both_marketplaces_at_the_plugin_branch(source_repo, tmp_path):
    sha = "a" * 40
    dist.pin(tmp_path, sha)
    claude = json.loads((tmp_path / dist.CLAUDE_MARKET).read_text(encoding="utf-8"))
    codex = json.loads((tmp_path / dist.CODEX_MARKET).read_text(encoding="utf-8"))
    assert claude["plugins"][0]["source"] == {
        "source": "github",
        "repo": dist.REPO,
        "ref": "plugin",
        "sha": sha,
    }
    assert codex["plugins"][0]["source"] == {
        "source": "url",
        "url": dist.GIT_URL,
        "ref": "plugin",
        "sha": sha,
    }
    with pytest.raises(SystemExit):
        dist.pin(tmp_path, "HEAD")


def test_shipped_marketplaces_are_pinned_to_the_plugin_branch():
    for rel in (dist.CLAUDE_MARKET, dist.CODEX_MARKET):
        (entry,) = json.loads((REPO / rel).read_text(encoding="utf-8"))["plugins"]
        assert entry["source"]["ref"] == "plugin", rel
        assert re.fullmatch(r"[0-9a-f]{40}", entry["source"]["sha"]), rel
