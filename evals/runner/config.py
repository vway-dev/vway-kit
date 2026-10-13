"""Paths, pinned measurement conditions and the error types every runner module shares.

The constants here are conditions a score is a fact about (model, turn budget, timeout,
concurrency); each carries the measurement that set it. Modules read them as `config.X`, so a
test that patches one here reaches every call site.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
CASES_PATH = REPO_ROOT / "evals" / "cases.yaml"
SCORES_PATH = REPO_ROOT / "evals" / "scores.json"
# SessionStart 훅이 매 세션 앞에 붙이는 것 전부: 훅이 읽는 룰 파일 **둘**과, 그것을 감싸는
# `inject-risk-tiers.sh` 의 서문. 합쳐서 `hook_assisted` 스킬의 호출을 정하는 **두 번째
# 입력**이고, 이전까지 아무 해시도 이것을 안 읽었음. 목록은 훅이 실제로 읽는 것에서
# **다시 계산**해야 함 — 자매 저장소 훅에는 `doc-style.md` 가 없어서 그쪽 목록을 그대로
# 베끼면 여기서 한 파일이 빠지고, 그 파일 편집이 낡은 점수를 통과시킴
# (`test_the_hash_inputs_match_what_the_hook_injects` 가 훅에서 유도해 강제).
# `rules/promotion.md` 는 주입 안 되므로 여기 없음.
INJECTED_PATHS = (
    REPO_ROOT / "hooks" / "inject-risk-tiers.sh",
    REPO_ROOT / "rules" / "risk-tiers.md",
    REPO_ROOT / "rules" / "doc-style.md",
)

# The expected skill id is DERIVED from the cases.yaml key (`vway-kit:<key>`);
# cases.yaml carries no `expect:` field, so a typo cannot silently score a skill
# against the wrong id. It is also the plugin name the OFF arm must shadow.
PLUGIN_NAME = "vway-kit"
SKILL_PREFIX = f"{PLUGIN_NAME}:"

# Measured 2026-07-18: 1 turn is too short — the agent sometimes runs `ls` first and
# invokes the skill on the next turn. The budget then sat at 3 for two weeks on the
# reasoning that a probe had shown six turns changing nothing.
#
# That probe was right and its conclusion was wrong, because the budget does not act alone.
# Measured 2026-07-20 on `playwright-scaffold`, n=25 per cell:
#
#     empty cwd,   3 turns -> 0.16      empty cwd,   6 turns -> 0.07
#     empty-web,   3 turns -> 0.16      empty-web,   6 turns -> 0.96
#
# Neither variable explains anything on its own; together they explain everything. This
# skill fires on "a web project with no specs yet", which is a condition the agent has to
# LOOK to discover — with nothing on disk there is nothing more turns can find, and with
# the project present but three turns to spend it runs out before it can answer. Six turns
# inside the fixture leaves one miss out of twenty-five.
#
# The general lesson, and the reason this comment is long: a design that eliminates one
# cause at a time cannot see an interaction. Every earlier probe here varied a single
# factor and each concluded, correctly, that its factor did not matter.
DEFAULT_MAX_TURNS = 6

# A 3-turn session measured at 33.5s. The ceiling is for a hung CLI: a kill at this mark
# is scored as far as the stream got (`parse_stream(killed=True)`) rather than discarded,
# because "no output" is not "did not fire" -- a stream that never reached `init` still
# raises instead of being scored, since that much genuinely cannot be read.
#
# Sessions are NOT cut short to save time, and this is the strongest-evidenced decision in
# the file because TWO repositories reached it independently, from different data.
#
# vway-kit measured it directly: a 30s cutoff destroys the score, 0.80 falling to 0.52,
# with firing times spread 19.2-30.0s and the maximum sitting exactly ON the cutoff —
# which is what a censored distribution looks like. The cause is CONTENTION, not startup
# (measured 2026-07-19, 8 samples each):
#
#                     serial      8 concurrent
#     init             5.2s          22.3s      <- 4.3x, and this is pure contention
#     Skill fired     13.7s          28.6s
#     session total   56.0s          93.6s
#
# Startup is 5.2s; the CLI is not slow to boot. Running eight sessions at once is what
# pushes firing past 30s.
#
# The sister repo (harness-tier) ships NO 30s kill — `evals/run.py` reads
# `SESSION_TIMEOUT = 180` and calls it "a hang guard, not a measurement bound".
# Its stated reason is the same mechanism reached from the other
# side of the same experiment: the 30s figure came from a SOLO session where firing landed
# 0.3-1.0s into the response, and that generalised across environments when it should not
# have — under eight-way load the mean session runs 58s, not 45s, and at a 30s cap
# 75-100% of every miss is a session stopped before it could decide.
#
# So this is not a divergence to defend. One repo found the censoring by watching the
# firing-time distribution pile up on the cutoff; the other found it by watching the miss
# rate; both concluded that a cutoff tuned on serial timings measures the cutoff once
# sessions run concurrently. Two environments and two routes to the same verdict is a
# better warrant than either measurement alone.
#
# What follows from it here: a cutoff and concurrency fight each other, and a safe cutoff
# would have to be derived from the contended tail rather than the serial one. Not done —
# the gain (~70% of each session is post-firing) is real but the failure mode is silently
# censoring the score, which is the exact class of defect this harness exists to catch,
# and 8-way concurrency already cut the serial wall-clock of the full run by ~4.8x.
SESSION_TIMEOUT_S = 300

# Sessions share little — separate processes, separate prompts, a per-session cwd nobody
# else writes to — so serial execution was an unexamined default rather than a requirement.
#
# They do NOT share nothing, and the config directory is not read-only: the CLI writes
# `.claude.json`, `history.jsonl`, `.session-stats.json` and `projects/*` into whatever
# `CLAUDE_CONFIG_DIR` names (verified against this host's real `~/.claude`), and
# `isolated_config_dir` builds ONE such directory for the whole run, so eight concurrent
# sessions share it. The concurrency argument holds anyway, but only on the narrow
# claim: nothing this harness SCORES is read back out of that
# directory. A lost history entry or a raced `.claude.json` costs a throwaway config its
# bookkeeping, not a score its meaning. Two sessions racing on the same fixture directory
# WOULD corrupt a score, and that is why `session_cwd` is per session rather than per skill.
#
# 8 is not free and not tuned. Per-session time rises 56s -> 93.6s under it (measured),
# so the real speedup is ~4.8x rather than 8x, and whether 4 or 6 would beat it on
# wall-clock has not been measured. Fast enough that the full run fits inside the quote
# `--dry-run` prints, and the speedup is recorded here so the next person knows 8 is a
# floor-tested default rather than an analysed optimum. The full run's duration is NOT
# written down anywhere: it moves with the corpus and the turn budget, so a figure in
# prose goes stale the next time either changes.
CONCURRENCY = 8

# Wall-clock budgeting only: the measured per-session time divided by how many run
# at once. Answers "how long will this take?" BEFORE the first session rather
# than after. Scales linearly with the turn budget, which makes the quote an UPPER BOUND:
# a session that returns before the cap takes the same time whether the cap is 3 or 6, so
# the linear scaling over-quotes by exactly the budget nobody spent. The 2026-09-11 full
# run quoted 163 minutes at six turns and took 50. Quote the bound anyway — under-quoting
# a bill is the failure this constant exists to prevent.
#
# This is the CONTENDED figure (93.6s measured at concurrency 8), not the serial 56s.
# Budgeting from the serial number under-quotes the bill by 1.7x, which is how the
# first estimate of this run said 45min and the run took 1.7x that.
SESSION_WALL_CLOCK_S = 94

# The turn budget the figure above was measured AT, and a separate constant from the
# current default on purpose. Tying the divisor to `DEFAULT_MAX_TURNS` makes raising
# the default from 3 to 6 silently re-read the anchor as "94s at six turns", so a run
# doubled in length keeps quoting the shorter run's bill. A measured constant whose
# meaning moves when an unrelated constant moves is the defect this file exists to catch.
SESSION_WALL_CLOCK_MEASURED_AT_TURNS = 3


def wall_clock_per_session(max_turns: int, concurrency: int = CONCURRENCY) -> float:
    """Effective seconds per session at a given turn cap and concurrency.

    Measured anchor: ~94s per session at 3 turns, 8 at a time. Linear in the cap is
    close enough for a bill printed to two significant figures, and the point of the
    estimate is only to let the operator abort early, not to predict the run.
    """
    scaled = SESSION_WALL_CLOCK_S * max_turns / SESSION_WALL_CLOCK_MEASURED_AT_TURNS
    return scaled / max(concurrency, 1)


# Recorded, never gated. Read as a share of the MISSES: above this, enough of what the
# score counts against the description is a session cut short — turn cap or killed at
# SESSION_TIMEOUT_S — that the runner says so out loud. Applied to BOTH arms — see
# `truncated_quiet`.
TRUNCATED_WARN = 0.20

# This runner briefly carried a `FIRE_BY_TOOL_CALL = 3` fair-chance test: a capped session
# counted as truncated only if it had made fewer than three tool calls. Measurement killed
# it (2026-07-19, 45 sessions across three skills). Two independent faults:
#
#   1. The threshold was wrong. It assumed firing always lands by the third tool call;
#      firings were observed at 4, 5 and 6.
#   2. Raising it would not have helped, because the conjunction is UNSATISFIABLE. Every
#      capped session had >= 3 tool calls and every session under 3 ended `success` —
#      exhausting three turns requires acting on each one, and an action is a tool call.
#      So `hit_turn_cap` implies `tool_calls >= max_turns`, and the fair-chance test is
#      empty for any threshold at or below the turn budget.
#
# The tool-call count and the turn budget are the same quantity here, so no threshold over
# the former can qualify the latter. What remains measurable is whether a session that did
# not fire ran out of road, reported below as a share of the misses.

# Pinned, not inherited. A measured `claude -p` child adopts the CALLING session's model
# (verified 2026-07-18: a subprocess launched from an opus-4-8[1m] session reported
# `model: "claude-opus-4-8[1m]"` in its own init event). The sister repo measured the
# same case at 4/4 on sonnet-5, 0/4 on opus-4-8 and 1/5 on opus-4-8[1m] -- a swing wider
# than any threshold this harness sets. Unpinned, a committed score is a fact about
# whoever ran the measurement, and the next person's re-measurement reads as a
# regression the ratchet cannot tell from a real one.
#
# This value is what vway-kit's own baseline is measured against, and the sister repo pins the
# same one so a figure carries across. Changing it invalidates every recorded score exactly
# as editing a description does -- the gate reads red from the re-pin until the re-measure
# lands, which is the forcing function, not a state to work around.
MODEL = "claude-sonnet-5"


GATED_METRICS = ("invoke_rate", "false_fire")

# 채점 못 한 세션의 사유 — `diagnose` 기록의 `reason` 값. `session` 이 `diagnose` 를 import 하지
# 않고 쓰도록 여기 둠.
TIMEOUT = "timeout"
ERRORED = "errored"
NO_INIT = "no_init"
MISSING_SKILL = "missing_skill"


class EvalError(RuntimeError):
    """Configuration or measurement fault that must stop the run."""


class MalformedStream(EvalError):
    """The CLI stream could not be parsed.

    Deliberately fatal. Scoring an unparseable session as "did not fire" is the
    exact silent failure this harness exists to prevent.
    """


class RateLimitAbort(EvalError):
    """The stream reported a non-normal rate-limit status."""


class SessionFailure(EvalError):
    """The session failed for a reason that has nothing to do with the skill.

    Auth expiry is the dangerous one because it does not look like a failure to a
    parser. Measured 2026-07-18 on this host::

        not logged in : subtype="success"          is_error=true   "Not logged in ..."
        turn cap hit  : subtype="error_max_turns"  is_error=true   terminal_reason="max_turns"

    The unauthenticated session emits a well-formed `init` (skills and all) and a
    well-formed `result`, so every check this runner had would pass and the session
    would score as "the skill did not fire" — zeros indistinguishable from a genuinely
    unresponsive description. The sister repo recorded ten such sessions into a
    baseline before noticing. A run spanning hours can outlive its credentials, so
    this stops the run rather than scoring it.
    """


def _force_utf8_io() -> None:
    """Reconfigure stdout/stderr to UTF-8 (CLAUDE.md Invariant #2).

    This host's console is cp949; Korean prompts and reasons in the progress log
    would raise UnicodeEncodeError mid-run and lose hours of measurement.

    Deliberately NOT `scripts._vway_paths.force_utf8_io`: `evals/` ships to no host, so it
    carries no dependency on the gate scripts. It also omits the stdin half that one has,
    because nothing here reads stdin — the runner takes its input from `cases.yaml` and the
    CLI. Adding a stdin read to this module means taking that half too.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # already closed / not reconfigurable
                pass


def _log(message: str) -> None:
    """Progress goes to stderr so stdout stays free for anything piped."""
    print(message, file=sys.stderr, flush=True)


def _tail(err: str, lines: int = 5) -> str:
    """The last few lines of a dead session's stderr, for the error that reports it.

    Ported from the sister repo (harness-tier `evals/run.py`), whose comment names
    the fault in one sentence: "captured but never read is how the cause of an unusable
    session got thrown away." `run_session` pipes stderr on every session, so the cause is
    always in hand — it was dropped on three of the four paths that raise, and those
    three are precisely the ones where "why was this session unusable?" is the only
    question a reader has (the plugin did not load / the skill was not offered / the model
    came back wrong). A CLI that explains itself on stderr and a runner that discards it
    leaves an operator re-running hours of measurement to see a message that already
    existed.

    Blank lines are dropped before taking the tail: the CLI pads its diagnostics, and five
    lines of padding carries none of the five lines of cause.
    """
    kept = [line for line in err.strip().splitlines() if line.strip()][-lines:]
    return "\n  stderr: " + "\n          ".join(kept) if kept else ""
