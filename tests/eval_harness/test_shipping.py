"""소비자에게 무엇이 실리는가 — eval 하네스는 실리지 않음.

매니페스트가 `evals/` 를 내보내면 소비자가 측정 코퍼스와 점수를 받음.
"""

from __future__ import annotations

import json

import pytest

from evals.runner.config import (
    REPO_ROOT,
)
from tests.eval_harness._presuppositions import (
    MANIFESTS,
    _manifest_strings,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.


@pytest.mark.parametrize("manifest", MANIFESTS)
def test_the_eval_harness_never_ships_to_consumers(manifest: str):
    """Prevention, not a live break: neither manifest names `evals` today.

    That is exactly the state the sister repo describes as dangerous (harness-tier
    `tests/test_evals.py`) -- a Global Constraint that holds because of how the files
    happen to look right now, with nothing to stop the next person from listing a path.
    vway-kit installs the same way: a GitHub source pinned to an immutable sha, with
    components auto-discovered from their default locations. Both manifests are metadata
    only and carry no path list at all, which is precisely why `evals/` is safe today and
    why nothing was stopping a `files` key from shipping a 520-session runner, a corpus of
    Korean prompts and this repo's own measured scores to every consumer.
    """
    text = (REPO_ROOT / manifest).read_text(encoding="utf-8")
    assert "evals" not in text, f"{manifest} mentions evals/ -- it must not ship to consumers"

    # The raw scan above is total and is the real assertion. Walking the parsed shape as
    # well keeps this test meaningful if a manifest ever grows nested component paths, where
    # a substring scan of the whole file would still pass on a comment or a description that
    # merely used the word.
    named = [s for s in _manifest_strings(json.loads(text)) if "evals" in s]
    assert not named, f"{manifest} names {named} -- the eval harness must not ship"
