"""srs_check 테스트가 공유하는 헬퍼 — SRS 파일 쓰기, CLI 호출."""

from pathlib import Path

import scripts.srs_check as sc

REPO = Path(__file__).resolve().parent.parent.parent


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def run(argv: list[str], capsys) -> tuple[int, str]:
    """두 스트림을 합쳐 반환 — 문제는 stderr, 목록은 stdout."""
    try:
        code = sc.main(argv)
    except SystemExit as exc:
        code = exc.code or 0
    cap = capsys.readouterr()
    return code, cap.out + cap.err
