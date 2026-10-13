"""alm_docs 테스트가 공유하는 헬퍼 — 파일 쓰기, CLI 호출, JSON 읽기."""

import json
from pathlib import Path

import scripts.alm_docs as ad


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def run(argv: list, capsys) -> tuple:
    """두 스트림을 합쳐 반환 — 표는 stdout, 사유는 stderr."""
    try:
        code = ad.main(argv)
    except SystemExit as exc:
        code = exc.code or 0
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
