"""Skill-invocation eval harness — development-only, but distributed all the same.

It is never *loaded* into a consumer session: Claude Code loads `agents/`, `skills/`
and `hooks/` as plugin components and nothing else, so nothing here runs or costs
context on a consumer's machine. It is still *shipped*, because `marketplace.json`
pins the plugin to a github source + sha and there is no ignore mechanism — the whole
repo at that sha lands in the consumer cache, exactly as `tests/`, `docs/` and
`scripts/` already do. Saying "not shipped to consumers" would be inaccurate.

A regular package rather than a namespace package so that both entry points —
``uv run python -m evals.run`` and ``from evals.runner.baseline import description_sha`` in
``tests/eval_harness/`` — resolve the same modules.
"""
