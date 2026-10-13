"""Codex AGENTS.md 렌더러 테스트가 함께 쓰는 배치 헬퍼."""

from pathlib import Path

BEGIN = "<!-- vway-kit:codex-instructions BEGIN — generated; edit CLAUDE.md or .claude/rules -->"
END = "<!-- vway-kit:codex-instructions END -->"
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "harness" / "codex" / "instructions.py"


def _write(host: Path, rel: str, text: str, newline: str = "\n") -> Path:
    path = host / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def _agents(host: Path) -> bytes:
    return (host / "AGENTS.md").read_bytes()


def _sample(host: Path) -> None:
    _write(host, "CLAUDE.md", "# Project\nroot rule\n")
    _write(host, ".claude/rules/py.md", "---\npaths: ['**/*.py', 'tests/**']\n---\nuse ruff\n")
    _write(host, ".claude/rules/all.md", "always true\n")
    _write(host, "services/api/CLAUDE.md", "api notes\n")
