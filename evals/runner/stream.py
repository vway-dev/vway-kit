"""Parse one `claude -p --output-format stream-json` session into what it says about a skill.

Judged by content, never by exit code. Everything that would let an unscorable session pass
as "the skill did not fire" raises here instead.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.runner import config

# A rate-limited session scored as "the skill did not fire" poisons the baseline
# permanently — but only an actual REFUSAL is that session. Warning-level statuses
# ride on a request that succeeded, and this was an allowlist of four guessed spellings
# until the sister repo measured what that costs: every run started late in the five-hour
# window aborted on its first healthy session, which from the operator's chair looks
# exactly like a real throttle.
#
# Fail-open here is safe in a way it usually is not in this repo, because the poisoning
# path has a second guard downstream: a genuinely refused request cannot produce a scorable
# session — it ends on a subtype outside `SCORABLE_SUBTYPES` and `SessionFailure` stops the
# run at exit 5. So an unknown throttled-but-not-"rejected" status still fails loudly; it
# fails on the evidence of the session rather than on a spelling this file guessed.
FATAL_RATE_LIMIT_STATUSES = frozenset({"rejected"})


class NoInit(config.MalformedStream):
    """The stream never reached `system/init` — the session did not start, so nothing about the
    skill can be read from it."""


# The only two `result.subtype` values that describe a session whose OUTCOME is about the
# skill. Everything else is a failure of the run, and scoring one silently subtracts from
# `invoke_rate` — the exact defect `SessionFailure` exists to prevent.
#
# The CLI's schema (extracted from the 2.1.212 binary) is:
#
#     subtype: "success" | "error_during_execution" | "error_max_turns"
#              | "error_max_budget_usd" | "error_max_structured_output_retries"
#
# An earlier guard here keyed on `subtype == "success" and is_error`, which caught auth
# expiry and let the other three error subtypes through as ordinary non-firing sessions.
# An engine crash mid-run (`[engine] turn ended in error: error_during_execution`) then
# cost 0.04 of `invoke_rate` per session AND landed in the denominator of `truncated` as
# "had room and declined" — quieting the very metric whose job is to say the score is
# untrustworthy.
#
# Membership, not a blocklist: a subtype this harness has never seen is unscorable by
# definition, so a future CLI release that adds one stops the run instead of averaging it
# into a score.
SCORABLE_SUBTYPES = frozenset({"success", "error_max_turns"})


@dataclass
class ParsedSession:
    """What one `claude -p` stream tells us."""

    loaded_skills: list[str] = field(default_factory=list)
    fired_skills: list[str] = field(default_factory=list)
    saw_result: bool = False
    result_subtype: str | None = None
    model: str | None = None
    # Reported by `--dry-run`-style diagnostics and by the probes that calibrate the turn
    # budget; nothing scores against it. It carried the fair-chance rationale in a comment
    # until measurement retired that test — the two cases it claimed to separate
    # are not both reachable, because a capped session has always made at least
    # `max_turns` tool calls.
    tool_calls: int = 0
    # `Skill` tool calls this parser declined to read a skill name from. Counted rather
    # than merely skipped: the skip is the ONE place where a stream event that should have
    # said "this skill fired" turns into silence instead, and silence lands in
    # `invoke_rate` as a miss. See the `input.skill` branch in `parse_stream`.
    aborted_skill_calls: int = 0
    # Set when the runner killed the session at SESSION_TIMEOUT_S and the stream was read
    # only as far as it got (`parse_stream(killed=True)`).
    timed_out: bool = False
    # 세션이 마지막으로 부른 도구 — kill 된 세션이 어디서 멈췄는지(`diagnose` 가 기록).
    last_tool: dict | None = None
    # 채점된 타임아웃의 진단 기록 경로 — `run_arm` 이 콘솔 줄에 붙임.
    record: Path | None = None

    def plugin_skill_count(self) -> int:
        return sum(1 for name in self.loaded_skills if name.startswith(config.SKILL_PREFIX))

    def offered(self, skill_id: str) -> bool:
        return skill_id in self.loaded_skills

    def fired(self, skill_id: str) -> bool:
        return skill_id in self.fired_skills

    def hit_turn_cap(self) -> bool:
        """Whether the session ended by exhausting `--max-turns` (measured subtype)."""
        return self.result_subtype == "error_max_turns"

    def cut_short(self) -> bool:
        """Whether the session stopped before it was done — out of turns, or killed at
        SESSION_TIMEOUT_S. Either way a session that had not fired might have one turn
        later, so both feed `truncated` rather than reading as a decided miss."""
        return self.hit_turn_cap() or self.timed_out

    def ended_voluntarily(self) -> bool:
        """Whether the session stopped because it was done rather than out of turns."""
        return self.saw_result and not self.hit_turn_cap()


def _walk(node: Any) -> Iterator[dict]:
    """Yield every dict nested anywhere in a decoded event.

    The runner matches on shape rather than on a fixed path so that a CLI release
    that re-nests an event changes nothing here — and, more importantly, so that
    EVERY `tool_use` in the stream is seen. Looking at the first one only produces
    false negatives that land straight in `invoke_rate`.
    """
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _skill_id(entry: Any) -> str:
    """Normalize one entry of the `init` event's `skills` array."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for key in ("name", "id", "skill", "skillId"):
            value = entry.get(key)
            if isinstance(value, str):
                return value
    raise config.MalformedStream(f"unrecognized entry in init.skills: {entry!r}")


def _check_rate_limit(event: dict) -> None:
    """Stop the run unless every rate-limit report in the event reads as normal.

    Measured shape (2026-07-18)::

        {"type": "rate_limit_event",
         "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour",
                             "overageStatus": "rejected", "isUsingOverage": false, ...}}

    Only `status` decides. `overageStatus` sits right next to it and reads
    "rejected" on a normal subscription session (this org disables overage), so a
    check that matched any `*status*` key would abort every run on a healthy host.
    Do not "generalize" this lookup.
    """
    for node in _walk(event):
        payload = node.get("rate_limit_event") if node.get("type") != "rate_limit_event" else node
        if not isinstance(payload, dict):
            continue
        info = payload.get("rate_limit_info")
        if not isinstance(info, dict):
            info = payload  # tolerate a flattened variant
        status = info.get("status")
        if not isinstance(status, str):
            raise config.MalformedStream(
                f"rate_limit_event without a status field: {payload!r} — refusing to "
                "guess whether the session was throttled"
            )
        if status in FATAL_RATE_LIMIT_STATUSES:
            raise config.RateLimitAbort(
                f"rate_limit_event status={status!r} — stopping before a throttled "
                "session gets recorded as 'the skill did not fire'"
            )


def parse_stream(stdout: str, *, killed: bool = False) -> ParsedSession:
    """Parse one JSONL session stream.

    Judged by content, never by exit code: a `--max-turns 3` session ends rc=1 with
    `is_error: true` while the stream already contains the fired `Skill` event.

    `killed` is for a stream the runner cut at SESSION_TIMEOUT_S: everything before the
    kill already happened, so it is read as far as it got — no `result` is required and the
    half-written last line the kill leaves is dropped. The sister repo reads such streams
    the same way, but its `cut_early` additionally counts a killed miss with three or more
    tool calls as decided; here every killed miss is cut, because the first fault recorded
    against `FIRE_BY_TOOL_CALL` (firings observed at the fourth to sixth tool call) holds for
    a kill as much as for the turn cap. Only the runner's own kill earns this: a stream
    that merely ends early is still malformed.
    """
    session = ParsedSession(timed_out=killed)
    saw_init = False
    lines = stdout.splitlines()
    last = max((n for n, line in enumerate(lines, start=1) if line.strip()), default=0)

    for lineno, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            if killed and lineno == last:
                break
            raise config.MalformedStream(f"line {lineno} is not JSON: {exc}") from exc
        if not isinstance(event, dict):
            raise config.MalformedStream(f"line {lineno} is not a JSON object")

        _check_rate_limit(event)

        if event.get("type") == "system" and event.get("subtype") == "init":
            saw_init = True
            model = event.get("model")
            session.model = model if isinstance(model, str) else None
            skills = event.get("skills")
            if not isinstance(skills, list):
                raise config.MalformedStream(
                    "init event carries no `skills` array — the arm (plugin on/off) "
                    "cannot be verified, and an unverified OFF arm is indistinguishable "
                    "from a plugin that loaded anyway"
                )
            session.loaded_skills = [_skill_id(entry) for entry in skills]

        if event.get("type") == "result":
            session.saw_result = True
            subtype = event.get("subtype")
            session.result_subtype = subtype if isinstance(subtype, str) else None
            if subtype not in SCORABLE_SUBTYPES or (subtype == "success" and event.get("is_error")):
                detail = str(event.get("result") or event.get("api_error_status") or "")
                errors = event.get("errors")
                if not detail and isinstance(errors, list):
                    detail = "; ".join(str(item) for item in errors)
                raise config.SessionFailure(
                    f"session ended with subtype={subtype!r}"
                    f"{f': {detail.strip()[:200]!r}' if detail else ''} — not scored, "
                    "because this is a failure of the session, not of the skill"
                )

        for node in _walk(event):
            if node.get("type") != "tool_use":
                continue
            session.tool_calls += 1
            session.last_tool = {"name": node.get("name"), "input": node.get("input")}
            if node.get("name") != "Skill":
                continue
            payload = node.get("input")
            skill = payload.get("skill") if isinstance(payload, dict) else None
            if skill is None:
                # An ABORTED Skill call, not a malformed stream: the CLI serialises one as
                # `{"skill": null}` (or with the `input` object not yet filled in). It is a
                # normal event, and raising on it threw away an entire session that had
                # parsed perfectly — fatally, since `MalformedStream` stops the run, so one
                # aborted call could end a 575-session measurement.
                #
                # The tool call above is still counted, because it happened. What is skipped
                # is only the claim that a named skill fired.
                #
                # This branch is the harness's one sanctioned silent negative, and the
                # reason it is COUNTED is that its safety rests on an unmeasured premise:
                # that a `Skill` event without a readable `input.skill` is always an abort
                # rather than a schema that moved. If the CLI ever re-nests `input` or
                # emits it unfilled on the way to a real firing, every firing would read as
                # a miss here and the run would report plausible zeros. The `invoke_hits
                # == 0` floor catches that only when it is total.
                #
                # Neither reading can be told from the other without a measurement, so the
                # choice made is to keep the tolerant behaviour (a fatal here can end hours
                # of work over one aborted call) and make its cost VISIBLE instead: this
                # counter reaches `scores.json`, and a nonzero value beside a low
                # `invoke_rate` is the signal to go and read a raw stream before believing
                # the number.
                session.aborted_skill_calls += 1
                continue
            if not isinstance(skill, str):
                # A non-string, non-null value is a different animal: the schema moved, and
                # guessing what it now means is how a false negative gets averaged in.
                raise config.MalformedStream(
                    f"Skill tool_use with a non-string input.skill: {node!r}"
                )
            session.fired_skills.append(skill)

    if not saw_init:
        raise NoInit("stream contains no system/init event")
    if not session.saw_result and not killed:
        # A truncated stream looks exactly like a session where nothing fired.
        raise config.MalformedStream("stream ended without a `result` event (truncated session?)")
    return session
