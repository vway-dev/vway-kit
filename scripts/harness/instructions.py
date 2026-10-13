"""호스트의 프로젝트 지침을 Claude Code 파일에서 읽어 만든 하네스 중립 모델.

- 원본은 Claude 산출물뿐(루트 CLAUDE.md·`.claude/rules/**/*.md`·디렉터리별 CLAUDE.md) — 읽기만
  하고 쓰지 않음. 하네스마다 렌더러가 이 모델을 그 하네스가 읽는 파일로 바꿈.
- 호스트에서 돌므로 게이트의 Python 하한(3.8)을 지킴.
- 읽기는 전부 UTF-8 + CRLF→LF(Invariant 2 · 추적 파일은 워킹트리에서 CRLF).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # `sources` 는 아무것도 파싱하지 않고 나열만 함 — 필요한 것은 `collect`
    yaml = None

MAX_IMPORT_DEPTH = 5
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", ".claude"})
_IMPORT_RE = re.compile(r"@(\S+)")
_FENCE_RE = re.compile(r"\s{0,3}(```|~~~)")
_FRONTMATTER_RE = re.compile(r"---\n(?:(.*?)\n)?---[ \t]*(?:\n|\Z)", re.DOTALL)
ROOT_FILES = ("CLAUDE.md", ".claude/CLAUDE.md")


@dataclass(frozen=True)
class InstructionDoc:
    kind: str  # "root" | "rule" | "module"
    source: str  # Claude 산출물의 repo 상대 POSIX 경로
    scope_dir: str  # repo 루트면 "", 아니면 repo 상대 디렉터리
    paths: tuple[str, ...]  # 룰의 `paths:` glob — () 는 늘 적용
    body: str  # frontmatter 뒤 본문, @import 전개, LF 줄끝


def _read(path: Path) -> str:
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return text[1:] if text.startswith("\ufeff") else text


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1) or "")
    except yaml.YAMLError:
        meta = None
    return (meta if isinstance(meta, dict) else {}), text[m.end() :]


def _split_globs(value: str) -> list[str]:
    """쉼표로 구분한 `paths:` 문자열 — `{…}` 안의 쉼표는 glob 의 일부."""
    out, depth, cur = [], 0, ""
    for ch in value:
        depth += (ch == "{") - (ch == "}")
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [g.strip() for g in out if g.strip()]


def _paths(meta: dict) -> tuple[str, ...]:
    raw = meta.get("paths")
    if isinstance(raw, str):
        return tuple(_split_globs(raw))
    if isinstance(raw, list):
        return tuple(str(g).strip() for g in raw if str(g).strip())
    return ()


def _import_target(line: str, base: Path, host: Path) -> Path | None:
    m = _IMPORT_RE.fullmatch(line.strip())
    if not m or m.group(1).startswith("~"):
        return None
    target = (base / m.group(1)).resolve()
    if not target.is_file() or host not in target.parents:
        return None
    return target


def _expand(text: str, file: Path, host: Path, chain: tuple[Path, ...], keep) -> str:
    """`@<상대경로>` 한 줄을 그 파일 본문으로 바꿈.

    - 펜스 안·없는 파일·호스트 밖·순환·`keep` 대상·깊이 초과는 줄을 그대로 둠.
    """
    out: list[str] = []
    fence = None
    for line in text.split("\n"):
        m = _FENCE_RE.match(line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
        target = None if fence else _import_target(line, file.parent, host)
        if target is None or target in chain or target in keep or len(chain) > MAX_IMPORT_DEPTH:
            out.append(line)
            continue
        body = _split_frontmatter(_read(target))[1]
        expanded = _expand(body, target, host, (*chain, target), keep)
        out.append(expanded[:-1] if expanded.endswith("\n") else expanded)
    return "\n".join(out)


def _doc(kind: str, path: Path, host: Path, keep) -> InstructionDoc:
    meta, body = _split_frontmatter(_read(path))
    rel = path.relative_to(host).as_posix()
    scope = path.parent.relative_to(host).as_posix() if kind == "module" else ""
    return InstructionDoc(
        kind=kind,
        source=rel,
        scope_dir="" if scope == "." else scope,
        paths=_paths(meta) if kind == "rule" else (),
        body=_expand(body, path, host, (path.resolve(),), keep),
    )


def _git_ignored(host: Path, rels: list[str]) -> set[str]:
    if not rels or not shutil.which("git"):
        return set()
    try:
        out = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=host,
            input="\0".join(rels) + "\0",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return set(filter(None, out.stdout.split("\0"))) if out.returncode == 0 else set()


def _modules(host: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(host):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        path = Path(dirpath) / "CLAUDE.md"
        # `is_file()` 이 끊긴 symlink 를 버림 — `collect` 가 끊긴 룰을 버리는 것과 같게.
        if "CLAUDE.md" in filenames and Path(dirpath) != host and path.is_file():
            found.append(path)
    rels = [p.relative_to(host).as_posix() for p in found]
    ignored = _git_ignored(host, rels)
    return [p for p, rel in zip(found, rels) if rel not in ignored]


def collect(host: Path, keep_imports=frozenset(), found=None) -> list[InstructionDoc]:
    """ROOT_FILES 순서대로, 이어 룰, 이어 모듈 — 묶음마다 경로순.

    `keep_imports` 는 `@import` 줄을 리터럴로 둘 파일 — 렌더러가 자기 출력 파일을 넘겨, 그것을
    import 하는 CLAUDE.md 가 렌더 결과를 다시 끌어들이지 않게 함.
    `found` 는 호출자가 이미 나열한 `sources(host)`.
    """
    if yaml is None:
        raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
    host = host.resolve()
    keep = {Path(p).resolve() for p in keep_imports}
    if found is None:
        found = sources(host)
    return [_doc(kind, path, host, keep) for kind, path in found]


# 이전 /vdev-init 이 복사해 둔 플러그인 자신의 룰(vdev_init_setup.py 의 RULES_DEST) — 재동기화가
# 지울 때까지 남음. Codex 는 그 요약을 SessionStart 훅 주입으로 받으므로, 여기서도 렌더하면
# AGENTS.md 예산을 중복에 쓰고 호스트 자신의 룰 본문을 밀어낼 수 있음.
PLUGIN_RULES_DIR = ".claude/rules/vway-kit"


def sources(host: Path) -> list[tuple[str, Path]]:
    """`collect` 가 읽는 모든 파일의 (kind, path) — 같은 순서, 아무것도 읽지 않고 찾음."""
    host = host.resolve()
    out = [("root", host / rel) for rel in ROOT_FILES if (host / rel).is_file()]
    rules_dir = host / ".claude" / "rules"
    plugin_rules = host / PLUGIN_RULES_DIR
    rules = sorted(
        (p for p in rules_dir.rglob("*.md") if plugin_rules not in p.parents),
        key=lambda p: p.relative_to(host).as_posix(),
    )
    out.extend(("rule", p) for p in rules if p.is_file())
    modules = sorted(_modules(host), key=lambda p: p.relative_to(host).as_posix())
    out.extend(("module", p) for p in modules)
    return out
