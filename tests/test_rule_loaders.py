"""`.claude/rules/` 로더 — 이 저장소 자신을 편집할 때 무엇이 로드되는가.

소비자에게 가는 `rules/` 와 다름: 그쪽은 플러그인이 출하하는 규율이고, 이쪽은 **그 규율을
구현하는 파일을 편집할 때** 그것을 끌어오는 트리거임. 로더가 조용히 틀리는 방식은 둘 —
`paths` 가 아무것도 안 잡거나(트리거가 죽음), 본문이 지목하는 룰·파일이 사라짐(안내가 거짓).
둘 다 편집 세션에서는 "규율이 안 걸렸다" 와 구분되지 않으므로 기계로 봄.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
LOADERS = sorted((REPO / ".claude" / "rules").glob("*.md"))
LOADER_IDS = [p.stem for p in LOADERS]


def _front(path: Path) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", path.read_text(encoding="utf-8"), re.DOTALL)
    assert m, f"{path.name}: frontmatter 가 없음 — 트리거 없이 로드되지 않음"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), f"{path.name}: frontmatter 가 매핑이 아님"
    return data


def test_the_repo_has_rule_loaders_at_all():
    """디렉터리가 비면 아래 전부가 공허하게 통과함."""
    assert LOADERS, ".claude/rules/ 에 로더가 없음"


@pytest.mark.parametrize("loader", LOADERS, ids=LOADER_IDS)
def test_every_declared_path_matches_something(loader: Path):
    """`paths` 글롭이 0개를 잡으면 그 줄은 트리거가 아니라 죽은 텍스트임 — 파일을 개명한
    커밋이 남기는 흔한 모양이고, 편집 세션에서는 규율이 없는 것과 똑같이 보임."""
    for pattern in _front(loader).get("paths", []):
        assert list(REPO.glob(pattern)), f"{loader.name}: `{pattern}` 가 아무것도 안 잡음"


@pytest.mark.parametrize("loader", LOADERS, ids=LOADER_IDS)
def test_every_link_in_the_body_resolves(loader: Path):
    """본문이 대는 룰·문서가 실재해야 함. 로더의 값은 "무엇을 읽어야 하는지" 하나뿐이라,
    링크가 끊기면 남는 것이 없음."""
    text = loader.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", text):
        if target.startswith(("http://", "https://")):
            continue
        assert (loader.parent / target).resolve().exists(), f"{loader.name}: `{target}` 가 없음"


def test_the_spec_map_triggers_on_every_file_it_names():
    """표에 적힌 파일은 `paths` 에도 있어야 함. 둘이 갈리면 그 행은 **아무도 안 읽는 안내**가
    됨 — 파일을 열어도 로더가 안 걸리므로, 표가 있다는 사실 자체가 잘못된 안심을 팜.

    표의 파일 이름은 인라인 코드 스팬으로만 셈(산문 속 언급은 트리거를 요구하지 않음)."""
    spec = REPO / ".claude" / "rules" / "specs.md"
    assert spec.exists(), "specs.md 가 없음"
    patterns = _front(spec).get("paths", [])
    named = {
        token
        for line in spec.read_text(encoding="utf-8").splitlines()
        if line.startswith("|")
        for token in re.findall(r"`([^`]+)`", line.split("|")[1] if "|" in line else "")
        if "/" in token or token.endswith((".yaml", ".yml", ".py", ".sh", ".md"))
    }
    assert named, "표에서 파일 이름을 하나도 못 읽음 — 형식이 바뀌었는지 확인"
    for token in sorted(named):
        # 덮임 판정은 글롭이라 유령 이름도 통과함(`scripts/alm_*.py` 가 없는 파일을 덮음).
        # 실재는 따로 물어야 하고, 이것이 개명·삭제가 표에 남는 유일한 방어임.
        assert list(REPO.glob(token.rstrip("/"))), f"표가 없는 `{token}` 를 댐"
    for token in sorted(named):
        # 표는 디렉터리를 `agents/` 처럼 대고 `paths` 는 그 안을 `agents/*.md` 로 잡음 —
        # 덮임은 양방향임: 토큰이 글롭에 맞거나, 글롭이 그 디렉터리 밑을 가리키거나.
        covered = any(
            Path(token) == Path(p) or Path(token).match(p) or p.startswith(token.rstrip("/") + "/")
            for p in patterns
        )
        assert covered, f"표가 `{token}` 를 대는데 `paths` 가 그 파일에서 안 걸림"
