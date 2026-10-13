"""세션 스텁과 통조림 측정치 — 모델을 부르지 않고 러너를 돌리는 재료.

`_stub_sessions`(프롬프트 이름이 happy 면 발화) · `_canned_run`(진짜 `run_session` 에
고정 스트림) · `_no_sessions`(기록하고 거부) 세 층으로 나뉨.
"""

from __future__ import annotations

import json
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from evals.runner import config, invocation, ratchet, session, stream
from evals.runner.baseline import (
    read_frontmatter,
)
from evals.runner.case_corpus import (
    load_cases,
)
from evals.runner.config import (
    REPO_ROOT,
    EvalError,
)
from evals.runner.session import (
    DEFAULT_CWD_LABEL,
)
from tests.eval_harness._checks import Declaration, Verdict, check


# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
def _model_invocable(skill_dir: Path) -> bool:
    return read_frontmatter(skill_dir / "SKILL.md").get("disable-model-invocation") is not True


# --------------------------------------------------------------- hook-assisted honesty
#
# The plugin's own SessionStart hook (hooks/claude/hooks.json -> inject-risk-tiers.sh) injects
# rules/risk-tiers.md, wrapped in a hardcoded preamble, into EVERY session -- eval sessions
# included, because --plugin-dir loads the hook with the skills and isolating
# CLAUDE_CONFIG_DIR does not remove it. A skill that text tells the agent to run is measured
# with help no consumer-free reading would give it. That is deliberate (consumers get the
# hook too) but it costs two things per affected skill: its rate is not comparable to the
# unassisted skills, and its ratchet is partly blind to its own description, since the hook
# can hold the number up while the description rots. The hook text IS in `description_sha`
# for a skill that declares `hook_assisted`, so an edit to it forces a re-measure; what the
# hash cannot see is the description rotting underneath it. So the caveat is a declared
# field, checked against the injected text, not a comment: vdev, doc-sync and task-sync
# already narrate it in their expect_why prose, and prose is exactly what was wrong twice in
# the sister repo (a hand-counted "flow is the only one" that missed /doc-sync, then a
# hand-counted number that was also wrong). Ported from harness-tier tests/test_evals.py.


def _injected_session_text() -> str:
    """Everything the SessionStart hook puts into a session, not the rule file alone.

    `hooks/inject-risk-tiers.sh` wraps `rules/risk-tiers.md` in its own text -- the Codex
    mapping line, the prose block -- and a slash name it adds reaches the session as surely
    as the rule's. Reading only the rule file would miss one, and would also report "the help
    is gone" if someone rewrote the rule file's slash forms into prose while the hook kept
    naming the skill.

    None of it reaches a session unless `hooks.json` still registers the script for a
    session-start matcher. Narrowing that matcher would end the help while both files still
    named the skills, so this returns "" in that case -- the reverse check then reports the
    caveat as stale, which is what it would be."""
    hooks = json.loads((REPO_ROOT / "hooks/claude/hooks.json").read_text(encoding="utf-8"))
    registered = any(
        "startup" in (entry.get("matcher") or "")
        and any("inject-risk-tiers" in h.get("command", "") for h in entry.get("hooks") or [])
        for entry in hooks.get("hooks", {}).get("SessionStart") or []
    )
    if not registered:
        return ""
    return "\n".join(
        (REPO_ROOT / p).read_text(encoding="utf-8")
        for p in ("hooks/inject-risk-tiers.sh", "rules/risk-tiers.md")
    )


def _skills_named_as_commands(text: str) -> set[str]:
    """Measured skills the injected text tells the agent to run, by their `/name` form.

    Intersected with the measured set rather than returned raw: a bare `/([a-z-]+)` matches
    `and/or`, `lint/static/import_lint/test` and `integration/staging/production` -- most of
    which are not invocations. Left unrestricted, reordering one branch-role list to
    `staging/integration` would force a false `hook_assisted` onto the `integration` skill,
    which the same file explicitly calls a branch role and not a skill.

    The boundary has to exclude a following hyphen, not only a following word character:
    `\\b` matches between `w` and `-`, so `/vdev` would be found inside `/vdev-init`,
    `/vdev-uninstall` and the link `](../vdev-tiers.yaml)` -- leaving `vdev` permanently in
    the named set and disabling the reverse stale check for it."""
    _, cases = load_cases()
    return {name for name in cases if re.search(rf"/{re.escape(name)}(?![\w-])", text)}


# ------------------------------------------------------------------- gate has teeth
#
# A gate whose checks cannot go red is worse than no gate: it reports safety it does
# not provide. Each check below is fed a baseline built to break it. Everything is
# in-memory or tmp_path -- these never touch the committed evals/scores.json.


def _verdict(name: str = "s", sha: str = "s" * 64, expect: float | None = 0.5, **entry) -> Verdict:
    """One `check` call on an entry that is healthy except for what the caller breaks."""
    return check(name, _measurement(**entry), sha, Declaration(expect, "declared"), n_skills=9)


# ------------------------------------------------------------------ the safety flag
#
# `uv run python -m evals.run` starts a measurement billing for hours: the most expensive action
# available is the default, and it has no confirmation prompt (one would make the
# runner unusable non-interactively). What stands in for that prompt is a plan printed
# before the first session, plus a --dry-run that prints it and stops. Both are only
# worth anything if they hold, so both are pinned. Sessions are stubbed out; a test in
# this file must never reach a model.


def _stub_isolation(monkeypatch) -> None:
    """Neutralise `isolated_config_dir` for tests that drive `measure()`.

    The real one copies `~/.claude/.credentials.json` and exits when it is absent, which is
    correct for a measurement and fatal for a test suite: CI has no credentials, and every
    test below stubs the sessions out long before authentication could matter.
    """

    @contextmanager
    def _stub():
        with tempfile.TemporaryDirectory() as cfg:
            yield Path(cfg)

    monkeypatch.setattr(session, "isolated_config_dir", _stub)


def _no_sessions(monkeypatch) -> list[str]:
    """Replace the session runner with a stub that records and refuses."""
    started: list[str] = []

    def _stub(prompt: str, **_: object):
        started.append(prompt)
        raise EvalError("stub session: a test must never call the CLI")

    monkeypatch.setattr(session, "_claude_binary", lambda: "stub-claude")
    monkeypatch.setattr(session, "run_session", _stub)
    _stub_isolation(monkeypatch)
    return started


# ------------------------------------------------------------------- the runner itself
#
# Everything above reads a recorded number. These read the code that PRODUCES it, which
# until now was covered only by comments. The failure mode is specific: a runner bug
# does not turn this suite red, it writes a wrong number into scores.json (or refuses to
# write any), and every check above then passes on it. Streams are hand-built, so none
# of this touches a model.


def _stream(*events: dict) -> str:
    """A JSONL session stream, the shape `claude -p --output-format stream-json` emits."""
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"


INIT = {"type": "system", "subtype": "init", "skills": ["vway-kit:vdev", "other:thing"]}

# The three terminating shapes, measured on this host 2026-07-18. They are kept apart
# deliberately: two of them carry `is_error: true` and only ONE of those is scorable, so
# a fixture that blurs them lets the runner treat an unscorable session as a real zero.
#
# `subtype="success", is_error=true` is what a session with no valid credentials emits, NOT
# the turn-capped session -- a measurement that records `is_error` without the subtype
# invites that mislabel. A single RESULT of that shape standing in for "the turn-capped
# session" makes the suite's idea of a normal session the one shape that must never be
# scored at all.
RESULT = {"type": "result", "subtype": "success", "is_error": False}
RESULT_TURN_CAP = {
    "type": "result",
    "subtype": "error_max_turns",
    "is_error": True,
    "terminal_reason": "max_turns",
}
RESULT_NOT_LOGGED_IN = {
    "type": "result",
    "subtype": "success",
    "is_error": True,
    "result": "Not logged in · Please run /login",
}
# The remaining `result.subtype` values the CLI can emit, from the enum in the 2.1.212
# binary: subtype: "success" | "error_during_execution" | "error_max_turns" |
# "error_max_budget_usd" | "error_max_structured_output_retries". Only the first two of
# those five are scorable, and the fixtures above covered exactly the two the runner
# happened to handle -- so the suite could not see the three that fell through.
RESULT_ENGINE_CRASH = {
    "type": "result",
    "subtype": "error_during_execution",
    "is_error": True,
    "errors": ["Sandbox required but unavailable"],
}
RESULT_OVER_BUDGET = {"type": "result", "subtype": "error_max_budget_usd", "is_error": True}

# The shape measured on this host on 2026-07-18. `overageStatus: "rejected"` is what a
# HEALTHY session on a subscription with overage disabled carries -- it sits directly
# beside the real `status` and reads like a refusal.
HEALTHY_RATE_LIMIT = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "rateLimitType": "five_hour",
        "overageStatus": "rejected",
        "isUsingOverage": False,
        "resetsAt": 1_760_000_000,
    },
}

# The same event with the decoy listed FIRST. Key order belongs to the CLI, not to us,
# and a lax `*status*` scan reads whichever it meets first -- so against the dict above
# alone it would pass by luck, and this test would certify a check it never exercised.
HEALTHY_RATE_LIMIT_DECOY_FIRST = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "overageStatus": "rejected",
        "isUsingOverage": False,
        "status": "allowed",
        "rateLimitType": "five_hour",
    },
}


def _skill_use(skill: str) -> dict:
    return {"type": "tool_use", "name": "Skill", "id": "tu_2", "input": {"skill": skill}}


def _assistant(*content: dict) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": list(content)}}


def _canned_run(monkeypatch, stdout: str):
    """Point the real `run_session` at a fixed stream instead of the CLI.

    Patches `Popen` rather than `subprocess.run`: the timeout path had to stop using
    `run()` (its drain is unbounded — see the tree-kill test), and `subprocess.run` is now
    only reached for `taskkill`. A stub left on `run` would have gone quietly unused while
    every test that depends on it still passed.
    """

    class _Process:
        returncode = 1
        pid = 1234

        def communicate(self, timeout=None):
            return stdout, ""

    monkeypatch.setattr(session.subprocess, "Popen", lambda *a, **k: _Process())


def _arm_stub(monkeypatch, cut: str) -> None:
    """A session runner where nothing ever fires and one named arm's prompts run out of
    turns while the other's finish voluntarily.

    Nothing firing is what makes this legible: every session is a miss, so
    `cut_share_of_misses` reads 1.0 on the cut arm and 0.0 on the clean one, and the two
    metrics cannot agree by coincidence the way they can when one of them is null.
    """

    def _stub_session(prompt: str, **_: object):
        return stream.ParsedSession(
            loaded_skills=["vway-kit:vdev"],
            fired_skills=[],
            saw_result=True,
            result_subtype="error_max_turns" if prompt.startswith(cut) else "success",
        )

    monkeypatch.setattr(session, "run_session", _stub_session)


def _both_arms(monkeypatch, tmp_path: Path, cut: str) -> dict:
    _arm_stub(monkeypatch, cut)
    return invocation.measure_skill(
        "vdev",
        {"happy": [{"prompt": "happy-0"}], "negative": [{"prompt": "negative-0"}]},
        reps=1,
        workspace=session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg"),
        binary="stub-claude",
        max_turns=config.DEFAULT_MAX_TURNS,
        model=config.MODEL,
    )


def _canned_corpus(monkeypatch, tmp_path: Path) -> Path:
    """A one-skill `cases.yaml` plus an empty baseline, both redirected.

    Lets a test drive the REAL `measure()` -- plan, `measure_skill`, ratchet, write, and the
    reporting that follows it -- without the eleven-skill corpus (575 stub sessions) and
    without going anywhere near the committed `scores.json`, which a test that wrote it
    would corrupt for the gate that reads it.
    """
    corpus = tmp_path / "cases.yaml"
    corpus.write_text(
        "reps: 1\n"
        "skills:\n"
        "  vdev:\n"
        "    fixture: null\n"
        "    expect_invoke: 0.8\n"
        "    expect_why: not what this corpus is for; the loader requires it\n"
        "    happy:\n"
        "      - prompt: happy-0\n"
        "    negative:\n"
        "      - prompt: negative-0\n",
        encoding="utf-8",
    )
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps({"skills": {}}), encoding="utf-8")
    monkeypatch.setattr(config, "CASES_PATH", corpus)
    monkeypatch.setattr(config, "SCORES_PATH", scores)
    monkeypatch.setattr(session, "_claude_binary", lambda: "stub-claude")
    _stub_isolation(monkeypatch)
    return scores


# --------------------------------------------------------- the confirmation re-measure
#
# Spec 6 판정 2. delta = 0.10 is ~1 sigma at 25 samples, so ONE measurement crosses it by
# chance about 15% of the time; the design's 0.02 false-alarm rate is 0.15 squared and
# exists only if the second measurement runs. Without it the ratchet cries wolf
# six times more often, `--accept --reason` becomes reflex, and the ratchet is ceremony.


def _measurement(**metrics) -> dict:
    """One entry shaped exactly as `measure_skill` returns it.

    Both gated metrics are always present, counts included, because the real function
    always writes all of them; a fixture that omits one would let a KeyError in the runner
    pass as a green test.

    A caller that overrides only a rate gets the matching integers derived for it, and vice
    versa. That keeps every fixture in a state the runner could have produced --
    an entry whose counts and rate tell different stories is the hand-edit the gate exists
    to catch, so it must be written on purpose rather than arrived at by forgetting.
    """
    entry = {
        "description_sha": "s" * 64,
        "cwd": DEFAULT_CWD_LABEL,
        "invoke_hits": 24,
        "invoke_n": 25,
        "false_hits": 1,
        "false_n": 25,
        "truncated": 0.0,
        "truncated_quiet": 0.0,
        "restricted": 1.0,
        "max_turns": config.DEFAULT_MAX_TURNS,
        "model": config.MODEL,
    }
    entry.update(metrics)
    for rate_key, (hits_key, n_key, _) in ratchet.COUNTS_FOR_METRIC.items():
        total = entry.get(n_key)
        if rate_key in metrics and hits_key not in metrics:
            rate = metrics[rate_key]
            entry[hits_key] = round(rate * total) if isinstance(rate, int | float) else None
        elif rate_key not in metrics:
            hits = entry.get(hits_key)
            entry[rate_key] = round(hits / total, 4) if isinstance(hits, int) and total else None
    return entry


def _canned_measurements(monkeypatch, tmp_path: Path, baseline: dict, results: list[dict]):
    """Drive `measure()` with pre-canned per-skill results and a throwaway scores.json.

    `runner.SCORES_PATH` is redirected first: a test that wrote the committed baseline
    would corrupt the very file the gate reads.
    """
    scores_path = tmp_path / "scores.json"
    scores_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "SCORES_PATH", scores_path)
    monkeypatch.setattr(session, "_claude_binary", lambda: "stub-claude")
    monkeypatch.setattr(session, "run_session", lambda *a, **k: pytest.fail("a session started"))
    _stub_isolation(monkeypatch)

    pending = list(results)
    calls: list[dict] = []

    def _stub(name: str, spec: dict, **kwargs: object) -> dict:
        calls.append(dict(kwargs, name=name))
        assert pending, f"measure_skill was called more times than planned (at {name})"
        planned = pending.pop(0)
        # A planned exception stands in for a session-level abort (a rate limit, an auth
        # failure) at a chosen point in the run, which is the only way to test what the
        # runner does with the skills it had not reached yet.
        if isinstance(planned, Exception):
            raise planned
        return planned

    monkeypatch.setattr(invocation, "measure_skill", _stub)
    return scores_path, calls


def _baseline(**metrics) -> dict:
    return {"skills": {"vdev": _measurement(**metrics)}}


def _stub_sessions(monkeypatch) -> list[tuple[str, object]]:
    """Replace `run_session` with one that fires only on the prompt literally named
    "happy", and record what each arm asked for.

    Keyed on the prompt rather than on call order: the arms run their sessions through a
    thread pool, so an iterator would be both racy and silently order-dependent.
    """
    seen: list[tuple[str, object]] = []

    def _stub_session(prompt: str, **kwargs: object):
        seen.append((prompt, kwargs.get("allowed_tools")))
        return stream.ParsedSession(
            loaded_skills=["vway-kit:vdev"],
            fired_skills=["vway-kit:vdev"] if prompt == "happy" else [],
            saw_result=True,
            result_subtype="success",
        )

    monkeypatch.setattr(session, "run_session", _stub_session)
    return seen


# What a phrase in a prompt PRESUPPOSES about the project it is asked in, and the evidence
# that would make it true. Spec 4.5: a prompt that contradicts its fixture produces a sample
# no description rewrite can recover -- the agent spends its turns reconciling, and the miss
