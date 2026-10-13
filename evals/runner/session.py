"""Spawn one headless `claude -p` session, isolated from this machine's config, and verify it
measured what was asked (plugin loaded, skill offered, model pinned).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.runner import config, stream
from scripts import skill_sandbox as sandbox

# Recorded beside every score. A measured session is a real agent in a real directory,
# and many happy prompts presume a project ("기존 e2e 스위트", "Next.js 앱인데"); in an
# empty directory a skill can fail to fire for reasons that have nothing to do with its
# description. `description_sha` pins the text under measurement, this pins the
# environment it was measured in — scores from different cwds are not comparable.
#
# The label carries THREE things now, and they all ride on this one key on purpose.
# Isolation and the project fixture both move a score, so both are conditions —
# but `incomparable_conditions` treats a key that is missing on either side as "not
# changed", deliberately, so that entries written before a condition existed do not
# switch the ratchet off everywhere at once. That tolerance is exactly what would make a
# NEW `isolated:` or `fixture:` key useless: it is absent from every pre-isolation entry,
# so it could never differ from one, and a baseline measured against 95 visible skills in
# an empty directory would be compared silently with one measured against ~30 inside a web
# project. Folding both into `cwd` — a key every existing entry already carries — is what
# makes the change mechanically visible. Every pre-isolation entry reads "<empty temp
# dir>" and every new one reads "isolated:...", so the ratchet skips exactly once and the
# new value becomes the baseline.
FIXTURELESS_LABEL = "<empty temp dir>"
DEFAULT_CWD_LABEL = f"isolated:{FIXTURELESS_LABEL}"


def environment_label(fixtures: Iterable[str | None], explicit: Path | None = None) -> str:
    """The `cwd` value recorded beside a skill's scores.

    Derived from the fixtures the sessions RAN in rather than passed in beside
    them: the two would otherwise drift, and a label that disagrees with the directories is
    worse than none — it asserts a condition nobody measured under.

    Per-case overrides mean one skill can span several fixtures, so the label names
    the set. Sorted, because a run must not produce a different string for the same corpus.
    """
    if explicit is not None:
        # `--cwd` names one real directory and suppresses fixtures; still isolated, so the
        # prefix stays and a score taken this way is never confused with a fixture run.
        return f"isolated:{explicit}"
    seen = sorted({fixture or FIXTURELESS_LABEL for fixture in fixtures}) or [FIXTURELESS_LABEL]
    return "isolated:" + "+".join(seen)


def _claude_binary() -> str:
    found = shutil.which("claude")
    if not found:
        raise config.EvalError("`claude` CLI not found on PATH — measurement needs the real CLI")
    return found


def session_env(config_dir: Path) -> dict[str, str]:
    """The environment one measured session runs in — provider variables removed.

    The config directory alone does not isolate anything. One `ANTHROPIC_BASE_URL` sends
    every session through a proxy, and `ANTHROPIC_API_KEY` moves authentication off the
    credential `isolated_config_dir` copied. Either one turns the committed baseline
    into a fact about one developer's shell, which is the same objection that applies to
    an inherited model.

    A BLACKLIST rather than a whitelist, because the two lists differ in how knowable they
    are. The system variables the CLI needs to start at all vary by platform and we do not
    know the set — a whitelist that is wrong stops the session, or worse starts it and
    changes its behaviour. The contamination surface, though, is exactly two provider
    prefixes and can be enumerated. Enumerate what is known, not what is not.

    `CLAUDE_CONFIG_DIR` is written AFTER the stripping and the order is load-bearing: it
    carries the very prefix being removed, so setting it first would have the isolation
    erase its own instruction while every other check here still passed.

    `PYTHONUTF8` is set explicitly rather than left to survive the filter. It does survive
    (it matches neither prefix), but only if the parent process has it — and that depends
    on `_force_utf8_io()` having run, which is true under `main()` and not true of any
    other caller. This host is cp949 and a child that loses the flag raises
    `UnicodeEncodeError` on the Korean prompts mid-run (CLAUDE.md Invariant 2), so the
    guarantee is made here rather than inherited.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not (key.startswith("ANTHROPIC_") or key.startswith("CLAUDE_"))
    }
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    env["PYTHONUTF8"] = "1"
    return env


@contextmanager
def isolated_config_dir() -> Iterator[Path]:
    """A `CLAUDE_CONFIG_DIR` holding credentials and nothing else.

    Measured: an `init` event on this host offers 95 skills from 17 plugins, of which 12
    are vway-kit's — so 83 have nothing to do with this repo. An empty config dir brings
    the same session to ~30. A score measured against the wider set is a fact about the
    measurer's plugin set, and recording that fact does not help: unlike `cwd`, `model` and
    `max_turns`, the installed plugin set lives outside the runner, so the next person
    cannot reproduce it from the record — they can only learn that the conditions differed,
    which leaves the conditions incomparable and switches the ratchet off.

    The credentials are the one thing that must cross the isolation. An empty config dir
    emits a well-formed `init`, skills array included, and then ends "Not logged in" (the run
    catches it at exit 5); without that guard every session would score 0.0 for a reason
    that has nothing to do with any description. Absence is a `SystemExit` naming the
    reason rather than a fallback to the real config dir, because the fallback would
    silently un-isolate the whole run.

    The copy is a live credential in a world-writable temp tree for the length of the run,
    so it is written through `os.open` at 0o600 rather than `shutil.copy2` (which would
    carry the source mode across and leave the file briefly readable in between) and
    unlinked in a `finally`. Permissions are advisory on Windows, which is why the unlink
    matters more than the mode here.

    **Known hazard, not fixed here.** The copy is one-way. If the CLI refreshes the token
    mid-run it writes the new one into this temp copy, and the `unlink` below then discards
    it while the host's real `~/.claude/.credentials.json` still holds the token the run
    started with. That is harmless if refresh tokens are reusable and costs the operator a
    re-login if they rotate — which of the two is true here has NOT been measured, and a
    run of several hours is long enough for it to matter. Copying the refreshed credential
    back is deliberately not done: it would have a measurement write to the host's live
    authentication, and a bad write there is worse than a re-login. The hazard is recorded
    so an operator whose session expires after a long run knows where to look.
    """
    with tempfile.TemporaryDirectory(prefix="vway-eval-cfg-", ignore_cleanup_errors=True) as root:
        config_dir = Path(root) / "cfg"
        config_dir.mkdir(exist_ok=True)
        source = Path.home() / ".claude" / ".credentials.json"
        if not source.is_file():
            raise SystemExit(
                f"no credentials at {source} — an isolated session cannot authenticate, and "
                f"an unauthenticated one records 0.0 for every skill. This can be "
                f"absent legitimately: a macOS Keychain login and API-key auth both leave "
                f"this file unwritten. Measurement currently needs a host whose "
                f"subscription login wrote it (Windows/Linux)."
            )
        copied = config_dir / source.name
        handle = os.open(copied, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "wb") as out:
            out.write(source.read_bytes())
        try:
            yield config_dir
        finally:
            copied.unlink(missing_ok=True)


@dataclass(frozen=True)
class Raw:
    """What the process left behind, kept for `diagnose.record` whatever the stream says."""

    text: str
    err: str
    returncode: int | None
    elapsed: float
    timed_out: bool


@dataclass(frozen=True)
class Workspace:
    """Where measured sessions run: a parent for their per-session directories, the
    isolated config dir they authenticate against, and an optional `--cwd` override.

    `explicit` suppresses fixtures — the operator named a directory, and building a
    sandbox inside it would both surprise them and write to a tree they own.
    """

    root: Path
    config_dir: Path
    explicit: Path | None = None


@contextmanager
def session_cwd(workspace: Workspace, fixture: str | None) -> Iterator[Path]:
    """The directory ONE session runs in, built fresh and removed after.

    Per session, not per skill, for two independent reasons. `sandbox.build` rmtree's its
    target before rebuilding it, so eight concurrent sessions sharing a root would delete
    each other's working directory mid-run and the wreckage would land in `invoke_rate` as
    descriptions that did not fire. And a measured session is a real agent with real
    tools — one that edits its fixture would change the conditions for every session after
    it.

    `build()` creates `root/<scenario>` and returns THAT path; the session runs there. The
    parent holds a single subdirectory, which is precisely the empty-cwd condition
    the fixture exists to remove, so stopping one level up would reintroduce it.

    `ignore_cleanup_errors`: measured on Windows — the CLI child can still hold a handle on
    its cwd when the context manager exits, and a teardown failure must not make a
    completed measurement look like a crashed one.
    """
    if workspace.explicit is not None:
        yield workspace.explicit
        return
    workspace.root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workspace.root, ignore_cleanup_errors=True) as session:
        root = Path(session)
        yield sandbox.build(sandbox.BY_NAME[fixture], root) if fixture else root


# `signal.SIGKILL` is POSIX-only — on Windows the attribute does not exist at all, and the
# branch below that uses it is unreachable there. Resolved once, with a fallback, so that
# the POSIX path can be exercised by a test from either platform. Without this the kill
# path is covered by whichever OS the suite happens to run on and the other half is only
# ever read, which is how the drain-before-kill bug survived in the first place.
_POSIX_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


def _kill_process_tree(proc: Any) -> None:
    """Kill a session and everything it spawned.

    The child is `claude`, which spawns its own children; killing only the direct child
    leaves grandchildren holding the inherited pipe write handles, and the drain that
    follows then never returns. Windows walks the tree with `taskkill /T`; POSIX kills the
    process group `run_session` put the child in with `start_new_session`.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
        )
        return
    try:
        os.killpg(proc.pid, _POSIX_KILL_SIGNAL)
    except ProcessLookupError:
        proc.kill()  # the group is already gone; reap whatever is left


def run_session(
    prompt: str,
    *,
    plugin_dir: Path,
    cwd: Path,
    config_dir: Path,
    binary: str,
    max_turns: int,
    model: str,
    skill_id: str,
    allowed_tools: str | None = None,
    on_unscored: Callable[[Raw, stream.ParsedSession | None, str], Path | None] | None = None,
) -> stream.ParsedSession:
    """Run one measured session and return what the stream says.

    `--plugin-dir` points at the working tree and needs no install, which is what makes
    this usable as a merge gate: unreleased changes are exactly what needs scoring. It
    also fully overrides the same-named installed plugin (measured 2026-07-18 — a stub
    named `vway-kit` holding one marker skill produced exactly that one skill in
    `init.skills`), so a developer's own installed copy cannot leak into the numbers.

    `on_unscored` receives every session this cannot score as-is — killed at the timeout,
    failed, never reached `init`, or missing the skill — with its reason (`config.TIMEOUT` …),
    and returns where it kept the record. The path is appended to the error that reports the
    session, or set on the returned session when a killed one is still scored.
    """

    def keep(raw: Raw, parsed: stream.ParsedSession | None, reason: str) -> Path | None:
        # A record that cannot be written must not replace the failure it was describing.
        if on_unscored is None:
            return None
        try:
            return on_unscored(raw, parsed, reason)
        except (OSError, UnicodeError):
            return None

    def named(path: Path | None) -> str:
        return f"\n  record: {path}" if path else ""

    argv = [
        binary,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",  # stream-json only emits the per-event stream with --verbose
        "--max-turns",
        str(max_turns),
        "--model",
        model,
        "--plugin-dir",
        str(plugin_dir),
    ]
    if allowed_tools is not None:
        argv += ["--allowed-tools", allowed_tools]
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=session_env(config_dir),
        # `< /dev/null`: without it the CLI waits on stdin and the run hangs.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        # POSIX: a fresh process group so the timeout path can kill the whole tree with one
        # `killpg`. Ignored on Windows, where `taskkill /T` walks the tree instead.
        start_new_session=os.name != "nt",
    )
    try:
        out, err = proc.communicate(timeout=config.SESSION_TIMEOUT_S)
        timed_out = False
    except subprocess.TimeoutExpired:
        # `subprocess.run(timeout=)` was here, and its timeout path is the bug: it kills
        # only the DIRECT child and then drains the pipes with an UNBOUNDED
        # `communicate()`. A surviving grandchild still holding the inherited write handles
        # blocks that read forever — so the guard against a hung session becomes the hang
        # itself, and this module already has its own Windows evidence (see the temp-dir
        # `ignore_cleanup_errors` note) that children outlive the kill here.
        #
        # Kill the tree FIRST, then drain: with every writer dead the pipes close and the
        # second `communicate()` is bounded.
        _kill_process_tree(proc)
        out, err = proc.communicate()
        timed_out = True
    raw = Raw(out, err, proc.returncode, time.monotonic() - started, timed_out)
    if timed_out:
        # Scored as far as it got, as the sister repo does (`harness-tier evals/run.py`
        # falls through from the kill into its stream reader). A prompt that tells the agent
        # to get started keeps it working past the denied Skill call, and at the turn
        # latency under eight-way load that crossed 300s on the same vdev case in run after
        # run — each time after the skill had already fired on turn one, and each time
        # throwing away the whole run. "No output" is still not "did not fire": a stream
        # that never reached `init` cannot be scored, and that alone re-raises.
        try:
            session = stream.parse_stream(out, killed=True)
        except config.MalformedStream:
            path = keep(raw, None, config.TIMEOUT)
            raise subprocess.TimeoutExpired(
                argv, config.SESSION_TIMEOUT_S, output=out, stderr=err + named(path)
            ) from None
        session.record = keep(raw, session, config.TIMEOUT)
    else:
        # `proc.returncode` is deliberately not consulted — see parse_stream.
        if not out.strip():
            raise config.MalformedStream(
                f"empty stream (rc={proc.returncode}): {err.strip()[:400]}"
                + named(keep(raw, None, config.NO_INIT))
            )
        try:
            session = stream.parse_stream(out)
        except stream.NoInit as exc:
            raise stream.NoInit(f"{exc}{named(keep(raw, None, config.NO_INIT))}") from None
        except config.SessionFailure as exc:
            raise config.SessionFailure(f"{exc}{named(keep(raw, None, config.ERRORED))}") from None

    # "The plugin did not load" and "the description failed to fire" both score 0.0.
    # Only the init event separates them, so the load is verified before scoring.
    if session.plugin_skill_count() == 0:
        raise config.MalformedStream(
            f"loaded 0 {config.SKILL_PREFIX}* skills — the plugin did not load, so every "
            f"case in this run would score 0.0 for the wrong reason{config._tail(err)}"
            + named(keep(raw, session, config.NO_INIT))
        )
    # The plugin loading is not enough: ONE skill whose frontmatter stopped parsing is
    # dropped while its siblings load, so the count check passes and that skill scores a
    # clean 0.00 — indistinguishable from a description that stopped working. This is the
    # same silent zero the check above exists for, one level down.
    if not session.offered(skill_id):
        raise config.MalformedStream(
            f"the plugin loaded {session.plugin_skill_count()} skills but {skill_id!r} was "
            f"not among them — its frontmatter most likely failed to parse. Refusing to "
            f"record a 0.0 that is not about the description.{config._tail(err)}"
            + named(keep(raw, session, config.MISSING_SKILL))
        )
    # Asserted, not assumed, for the same reason the skill count is: `--model` silently
    # falling back would produce a full run of plausible numbers measured on the wrong
    # model, and the model moves the score more than anything else here. A MISSING model
    # is treated the same as a wrong one — this guard once read `is not None and !=`,
    # which made a CLI release that renamed or re-nested the field turn the assertion into
    # a no-op, leaving the one condition wider than any threshold unchecked.
    if session.model != model:
        raise config.MalformedStream(
            f"asked for --model {model!r} but the session reports {session.model!r} — "
            f"scores measured on an unrequested model are not comparable to the "
            f"baseline{config._tail(err)}"
        )
    return session
