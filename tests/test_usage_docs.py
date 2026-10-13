"""소비자 사용 설명서 = 인덱스 `USAGE.md` 하나 + `docs/usage/` 주제 문서.

나뉜 설명서는 파일 하나로는 안 보이는 방식으로 깨짐 — 인덱스가 주제 하나를 안 대거나,
링크가 다른 파일로 옮겨 간 절을 여전히 가리킴. 여기서 재는 것은 셋: 주제 목록 = 디렉터리,
인덱스가 주제 전부를 링크, README·USAGE·주제 문서의 상대 링크·앵커가 전부 풀림.
"""

import re
from pathlib import Path

import pytest

from scripts._md_anchors import _has_anchor, _strip_code

ROOT = Path(__file__).resolve().parents[1]
USAGE_DIR = ROOT / "docs" / "usage"
TOPICS = (
    "getting-started",
    "configuration",
    "tiers-and-gates",
    "daily-work",
    "promotion-and-release",
    "ci-workflows",
    "project-harness",
    "alm",
    "codex",
    "teams",
    "troubleshooting",
    "update-and-removal",
)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def test_the_topic_list_is_the_directory():
    """디스크에만 있는 주제는 인덱스 검사를 영영 안 받음."""
    assert {p.stem for p in USAGE_DIR.glob("*.md")} == set(TOPICS)


def test_the_index_links_every_topic():
    text = (ROOT / "USAGE.md").read_text(encoding="utf-8")
    missing = [t for t in TOPICS if f"docs/usage/{t}.md)" not in text]
    assert not missing, f"USAGE.md 가 {missing} 를 링크하지 않음"


def _docs() -> list[Path]:
    return [ROOT / "README.md", ROOT / "USAGE.md", *sorted(USAGE_DIR.glob("*.md"))]


@pytest.mark.parametrize("doc", _docs(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_relative_link_and_anchor_resolves(doc: Path):
    text = doc.read_text(encoding="utf-8")
    broken = []
    for target in LINK.findall(_strip_code(text)):
        if re.match(r"^[a-z]+:", target):
            continue
        path, _, frag = target.partition("#")
        dest = (doc.parent / path).resolve() if path else doc
        if not dest.exists():
            broken.append(target)
        elif frag and dest.suffix == ".md":
            if not _has_anchor(dest.read_text(encoding="utf-8"), frag):
                broken.append(target)
    assert not broken, f"{doc.relative_to(ROOT).as_posix()} 의 끊긴 링크: {broken}"
