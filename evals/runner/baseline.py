"""The recorded baseline: `evals/scores.json` read and written, the description fingerprint it
is keyed on, and whether an entry still describes the skill and corpus as they stand.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import yaml

from evals.runner import case_corpus, config


def read_frontmatter(path: Path) -> dict:
    """Parse one SKILL.md's YAML frontmatter block.

    Exported because the gate needs `disable-model-invocation` to decide which skills
    owe eval cases, and that flag has to be read by the same parser `description_sha`
    uses. Two independent readers of one block drift, and a drifted reader is how a
    model-invocable skill ends up with no cases and nobody notices.
    """
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        raise config.EvalError(f"{path}: no frontmatter block")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise config.EvalError(f"{path}: frontmatter is not a mapping")
    return data


def _hook_assisted(name: str) -> bool:
    """cases.yaml 이 이 스킬의 호출률을 주입된 룰에 기댄다고 선언했는가.

    부재·파싱 실패는 False. 그것이 안전한 쪽이라서가 아님 — 기록된 해시는 주입 바이트를
    이미 담고 있으므로 입력을 하나 빼면 **다른** 값이 나와 5개가 전부 stale 로 잡힘.
    시끄러운 거짓 stale 이지 조용한 누락이 아니라서 이 방향을 고름. 여기서 예외를 던지면
    측정과 무관한 이유로 하네스 전체가 섬.
    """
    try:
        data = yaml.safe_load(config.CASES_PATH.read_text(encoding="utf-8")) or {}
        return bool(((data.get("skills") or {}).get(name) or {}).get("hook_assisted"))
    except (OSError, yaml.YAMLError):
        return False


def description_sha(skill_dir: Path) -> str:
    """호출을 정하는 것 전부의 SHA-256.

    대부분의 스킬에서는 `description` **하나**. 본문은 일부러 뺌 — 호출은 설명문이
    정하므로, 본문 편집마다 전량 재측정을 요구하면 신선도 검사가 순전한 잡음이 되고,
    잡음이 된 게이트는 사람이 건너뛰는 법을 배움. 값은 YAML 파싱 **뒤**에 취하므로
    설명문을 다시 따옴표 치는 것으로는 해시가 안 움직임.

    `hook_assisted` 스킬은 입력이 하나 더 있고 그쪽이 더 셈: 상류 harness-tier 에서
    같은 스킬이 **같은 설명문**으로 0.82(n=55)와 0.55(n=65)를 냈고, 차이는 주입되는
    룰의 명령문 옆에 두 줄이 붙은 것뿐이었음(2026-09-08). 설명문만 해시하면 그런 변경이
    아무 신호도 없이 착지함 — cases.yaml 이 이미 "이 스킬의 회귀는 설명문과 훅을 함께
    읽으라" 고 적어 두고도 그것을 기계로 붙잡는 것이 없었음. 그래서 주입 텍스트가 그
    스킬들의 해시에 함께 들어가고, 거기 대한 편집은 설명문 편집과 똑같이 재측정을 요구함.
    키 이름은 `description_sha` 그대로 — 바꾸면 기록된 모든 항목과 모든 테스트 헬퍼를
    이 독스트링이 이미 말한 것을 말하려고 다시 쓰게 됨.

    `tests/eval_harness/_checks.py` 가 같은 방식으로 해시해 `scores.json` 이 아직 현재
    스킬을 기술하는지 판정하므로, 구현이 하나인 것이 둘의 drift 를 막음.
    """
    path = skill_dir if skill_dir.is_file() else skill_dir / "SKILL.md"
    if not path.is_file():
        raise config.EvalError(f"{path}: no SKILL.md to fingerprint")
    description = read_frontmatter(path).get("description")
    if not isinstance(description, str) or not description.strip():
        raise config.EvalError(f"{path}: frontmatter has no usable `description`")
    digest = hashlib.sha256(description.encode("utf-8"))
    if _hook_assisted(path.parent.name):
        for injected in config.INJECTED_PATHS:
            try:
                raw = injected.read_bytes()
            except OSError as exc:  # 형제 분기(위 no SKILL.md)와 같은 모양으로 이름을 댐
                raise config.EvalError(f"{injected}: injected file unreadable ({exc})") from exc
            # CRLF 를 접어서 해시함. 이 체크아웃은 Windows 에서 CRLF, ubuntu 러너에서 LF —
            # 날바이트로 해시하면 내용이 아니라 **체크아웃**을 해시하게 되어, 한쪽에서 기록한
            # 값이 다른 쪽 CI 에서 전부 stale 로 잡히고 고정점이 없음(설명문 쪽은 read_text 의
            # universal newlines 를 거치므로 이미 플랫폼 무관).
            digest.update(raw.replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def load_scores() -> dict:
    if not config.SCORES_PATH.is_file():
        return {"skills": {}}
    data = json.loads(config.SCORES_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        raise config.EvalError(
            f"{config.SCORES_PATH}: malformed — expected an object with a `skills` map"
        )
    return data


def write_scores(scores: dict) -> None:
    """Persist the whole file. Called after EACH skill, never once at the end.

    A full run takes hours and can cross a 5h rate-limit window; a single final
    write would lose every skill measured before the wall. Written via a temp file
    and `os.replace` so an interrupt cannot leave a half-written baseline behind.

    **Nothing above `skills`.** A file-level `measured_at` or `reps` is a claim about
    EVERY entry made by a run that measured ONE — the
    default mode is incremental, so measuring `vdev` alone re-dates every other entry and
    re-declares their sample size. The reader that misleads is the one who most needs the
    truth: someone asking "how old is this number?" before trusting a score gets today's date
    for a measurement that could be months stale. Nothing errors, the file stays
    well-formed, and the wrong answer is the confident one.

    The header `reps` had a defence the date never did — it equalled `cases.yaml`'s `reps`
    and a gate asserted so — but that defence expired the moment a skill could declare its
    own sample size. The assertion would have kept passing while no longer holding for the
    overriding skill: a gate whose message outlives its meaning, which is worse than no gate.
    So the gate moved instead of the feature being refused. It now checks EACH entry's `reps`
    against that skill's `effective_reps`, which is strictly stronger — it catches a
    per-skill edit the one-number check could not see at all.

    Provenance therefore lives entirely on the entry (`measure_skill` stamps both), matching
    the sister repo: its `measure()` stamps the same two per entry and names the fault in a
    comment (harness-tier `evals/run.py`), and its `save()` writes nothing
    file-level, "because an incremental run only knows the provenance of what it measured".
    Those two claims come from different functions there; read both rather than the first
    one the file offers.

    `corpus_sha` deliberately does NOT absorb `reps`: that fingerprint pins the QUESTIONS
    asked, and asking the same question more times does not change them (the reasoning that
    also excludes `kind` and `why`). A `reps` change is the same experiment run longer, which
    is exactly why the exact binomial can compare across it.
    """
    ordered = {
        "skills": {name: scores["skills"][name] for name in sorted(scores["skills"])},
    }
    config.SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.SCORES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, config.SCORES_PATH)


def measurement_is_current(entry: dict, name: str, spec: dict) -> bool:
    """Whether a recorded entry still describes the skill AND the corpus as they stand.

    BOTH fingerprints, because `invoke_rate` has more than one input. Reading only
    `description_sha` is what let a batch of rewritten prompts and new fixture overrides
    land with the runner announcing there was nothing to measure.

    A MISSING `corpus_sha` counts as stale. An entry written before the fingerprint existed
    cannot vouch for prompts nobody hashed, and the usual "absence is not a change"
    tolerance (see `incomparable_conditions`) is wrong here for the opposite reason it is
    right there: tolerating a missing CONDITION preserves a comparison, while tolerating a
    missing FINGERPRINT preserves a claim of freshness that was never checked. The cost of
    being wrong is also asymmetric — a needless re-measure costs one skill's sessions, a
    skipped one costs a baseline that silently describes a corpus nobody is running any more.
    """
    return entry.get("description_sha") == description_sha(config.SKILLS_DIR / name) and entry.get(
        "corpus_sha"
    ) == case_corpus.corpus_sha(spec)
