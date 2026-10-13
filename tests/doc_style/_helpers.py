"""산문 게이트 테스트가 공유하는 것 — 저장소 루트와 코드 추출기.

`scripts/` 를 sys.path 에 얹지 않고 패키지로 임포트함: 그 디렉터리가 세션에 남으면
`scripts/*.py` 의 `try: import _vway_paths / except ImportError: import scripts._vway_paths`
가 뒤집혀 같은 파일이 두 모듈 정체로 실려 감(`tests/skill_docs/_helpers.py` 의 근거와 같음).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent  # tests/<분류>/_helpers.py
sys.path.insert(0, str(REPO))

from scripts.doc_style_check import lint_text  # noqa: E402

__all__ = ["REPO", "_codes", "lint_text"]


def _codes(path: Path, text: str, severity: str = "error") -> list[str]:
    return [code for level, _, code, _ in lint_text(path, text) if level == severity]
