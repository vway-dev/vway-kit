"""출하 산문의 문체 — 개조식, 선언형 군더더기 없이."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

# `scripts/` must not linger on sys.path after this import: scripts/teams_alert.py (and
# friends) resolve `_vway_paths` with `try: import _vway_paths / except ImportError:
# import scripts._vway_paths` (see that module's docstring) so tests can `import
# scripts.xxx` as a package. A `scripts/` dir left on sys.path for the rest of the
# session flips that try-branch for every test file collected afterward (alphabetically,
# that is most of them), loading `_vway_paths` a SECOND time under a different module
# identity — `scripts.teams_alert._host_root is scripts._vway_paths.host_root` then
# reads False even though both come from the same file.
sys.path.pop(0)


from scripts.doc_style_check import lint_text
from tests.skill_docs._helpers import (
    REPO,
)
from tests.skill_docs._invocations import (
    CODE_FENCE,
    FRONTMATTER,
    PROSE_DOC_IDS,
    PROSE_DOCS,
)


@pytest.mark.parametrize("doc", PROSE_DOCS, ids=PROSE_DOC_IDS)
def test_shipped_prose_stays_terse(doc: Path):
    """[doc-style.md](rules/doc-style.md) 1의 강제 지점 — 그 룰은 SessionStart 로 주입될 뿐
    아무것도 막지 못해, 다음 편집이 서술형으로 되돌려도 스위트는 초록.

    판정은 `doc_style_check.lint_text` 에 위임 — 같은 룰의 리더는 하나. 트리 전체는
    `tests/doc_style/test_scope_and_cli.py` 가 한 번에 재고, 여기서는 문서별로 실패 이름이 서서
    어느 문서가 되돌아갔는지가 바로 보임.

    frontmatter 제외: `description` 은 산문이 아니라 스킬 발화를 정하는 측정 대상이고,
    `evals/scores.json` 이 그 텍스트의 sha 로 점수를 고정 — 여기서 문체를 강제하면 문장을
    다듬을 때마다 모델을 태우는 재측정이 따라붙음. 코드 펜스도 제외: 명령·출력·인용은
    원문이 곧 사실.
    """
    body = CODE_FENCE.sub("", FRONTMATTER.sub("", doc.read_text(encoding="utf-8"), count=1))
    where = doc.relative_to(REPO).as_posix()
    lines = body.splitlines()
    offenders = [
        f"  {n}: {lines[n - 1].strip()[:90]}"
        for _sev, n, code, _msg in lint_text(doc, body)
        if code == "ENDING"
    ]
    assert not offenders, (
        f"{where}: 서술형 종결 잔존 — rules/doc-style.md 1 은 개조식(`~함`·`~됨`·`금지`·"
        f"`필요`) 요구. 줄 번호는 frontmatter·코드펜스를 걷어낸 본문 기준:\n" + "\n".join(offenders)
    )
