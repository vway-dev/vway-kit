#!/usr/bin/env python3
"""이 저장소가 내보내는 플러그인 전용 트리와, 그것을 가리키는 마켓플레이스 핀.

  build [--source REV] [--parent SHA] --message MSG [--codex-zip PATH]
      소스 커밋에서 출하 파일만 골라 `plugin` 브랜치용 커밋을 만들고 sha 를 출력.
      `--codex-zip` 이면 그 커밋에서 OpenAI 디렉터리용 ZIP 도 만듦.
  pin <sha>
      두 마켓플레이스(Claude·Codex)를 `plugin` 브랜치의 <sha> 로 핀.

저장소 루트에는 소비자가 돌리지 않는 테스트·CI·eval 이 있고, 디렉터리 검사기는 플러그인
소스가 가리키는 파일을 전부 읽음 — 소비자는 이 트리가 루트인 `plugin` 브랜치에서 설치함.

작업 트리를 거치지 않고 git 트리를 직접 거름(임시 인덱스 → write-tree → commit-tree):
blob 바이트와 파일 모드(`.sh` 의 실행 비트)가 소스 그대로 남고, 호스트 OS·autocrlf 와 무관함.
push 는 호출측(release.yml)이 맡음.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "vway-dev/vway-kit"
GIT_URL = f"https://github.com/{REPO}.git"
BRANCH = "plugin"
CLAUDE_MARKET = ".claude-plugin/marketplace.json"
CODEX_MARKET = ".agents/plugins/marketplace.json"

# 소비자 세션·/vdev-init·README 독자가 닿는 것 전부. 디렉터리는 `/` 로 끝남.
INCLUDE = (
    ".gitattributes",
    ".claude-plugin/",
    ".codex-plugin/",
    CODEX_MARKET,
    "assets/",
    "agents/",
    "hooks/",
    "skills/",
    "rules/",
    "scripts/",
    "templates/",
    "github/",
    "vdev-tiers.yaml",
    "vdev-config.example.yaml",
    "pre-commit-hooks.example.yaml",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "USAGE.md",
    "docs/usage/",
)
# INCLUDE 안이지만 테스트·eval 만 쓰는 파일.
EXCLUDE = ("scripts/skill_sandbox.py",)
# OpenAI 디렉터리는 라이프사이클 훅을 실은 패키지를 거부함 — Claude 매니페스트가 훅을 선언하고,
# 마켓 파일은 디렉터리 패키지의 일부가 아님.
CODEX_ZIP_SKIP = (".claude-plugin/", ".agents/", "hooks/claude/")


def shipped(path: str) -> bool:
    if path in EXCLUDE:
        return False
    return any(path.startswith(p) if p.endswith("/") else path == p for p in INCLUDE)


def _git(args: list[str], env: dict | None = None, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    ).stdout.strip()


def _market(text: str, source: object) -> str:
    data = json.loads(text)
    (entry,) = data["plugins"]
    entry["source"] = source
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# 브랜치 안에서는 플러그인이 곧 마켓플레이스 루트. Codex 는 `url` 소스를 git 원격으로 읽으므로
# 클론이 아닌 루트에는 `local` 이 필요함.
IN_BRANCH_SOURCE = {CLAUDE_MARKET: "./", CODEX_MARKET: {"source": "local", "path": "./"}}


def tree_entries(source: str) -> list[str]:
    """`git ls-tree -r` 줄 중 출하 대상만, 마켓 파일은 브랜치용 소스로 바꾼 blob 으로.

    줄 형식: `<mode> <type> <sha>\\t<path>`."""
    out = _git(["-c", "core.quotePath=false", "ls-tree", "-r", "-z", source])
    rows = []
    for row in (r for r in out.split("\0") if r):
        meta, path = row.split("\t", 1)
        if not shipped(path):
            continue
        if path in IN_BRANCH_SOURCE:
            mode, kind, blob = meta.split(" ")
            text = _market(_git(["cat-file", "blob", blob]), IN_BRANCH_SOURCE[path])
            blob = _git(["hash-object", "-w", "--stdin"], stdin=text)
            row = f"{mode} {kind} {blob}\t{path}"
        rows.append(row)
    return rows


def build(source: str, parent: str | None, message: str) -> str:
    entries = tree_entries(source)
    assert entries, f"{source}: 출하할 파일이 없음"
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        _git(["read-tree", "--empty"], env=env)
        _git(["update-index", "-z", "--index-info"], env=env, stdin="\0".join(entries) + "\0")
        tree = _git(["write-tree"], env=env)
    if parent and _git(["rev-parse", f"{parent}^{{tree}}"]) == tree:
        return parent
    args = ["commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    return _git(args)


def codex_zip(commit: str, zip_path: Path) -> None:
    excludes = [f":(exclude){p.rstrip('/')}" for p in CODEX_ZIP_SKIP]
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    _git(["archive", "--format=zip", "-o", str(zip_path), commit, "--", ".", *excludes])


_SHA = re.compile(r"[0-9a-f]{40}")


def pin(root: Path, sha: str) -> None:
    if not _SHA.fullmatch(sha):
        raise SystemExit(f"전체 소문자 커밋 sha 가 아님: {sha!r}")
    sources = {
        CLAUDE_MARKET: {"source": "github", "repo": REPO, "ref": BRANCH, "sha": sha},
        CODEX_MARKET: {"source": "url", "url": GIT_URL, "ref": BRANCH, "sha": sha},
    }
    for rel, source in sources.items():
        path = root / rel
        path.write_text(_market(path.read_text(encoding="utf-8"), source), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", default="HEAD")
    b.add_argument("--parent", default="", help="이전 plugin 브랜치 커밋(없으면 루트 커밋)")
    b.add_argument("--message", required=True)
    b.add_argument("--codex-zip", type=Path)
    p = sub.add_parser("pin")
    p.add_argument("sha")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        commit = build(args.source, args.parent or None, args.message)
        if args.codex_zip:
            codex_zip(commit, args.codex_zip)
        print(commit)
    else:
        pin(Path.cwd(), args.sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
