"""The eval merge gate — reads `evals/scores.json`, calls no model.

`evals/run.py` (`evals/runner/`) measures whether a skill fires; that costs hours of real
sessions. This package is the other half: it checks the recorded result in milliseconds,
so the expensive half runs on a laptop when a description changes and the cheap half
runs on every `uv run pytest`. Nothing in it may import a session, a CLI, or a network.

Three judgements, in order of how much they matter:

1. **Freshness** is the load-bearing one. The other two check the numbers; this one
   checks that the numbers describe the skill that is in the tree right now. Without
   it you edit a description and coast on a green measured against the old text.
2. **Absolute thresholds** — `false_fire <= 0.20`. The `invoke_rate` floor is
   deliberately uncalibrated (`None`) until a measured baseline exists to set it from.
3. **Corpus integrity** — the analogue of `tests/skill_docs/`'s covered-XOR-registered
   rule, applied to eval cases: a new model-invocable skill cannot arrive with no
   cases, and a `disable-model-invocation` skill cannot arrive with cases that can
   never fire.

Unmeasured is a WARNING, not a failure. A harness that turns the suite red on
the day it lands trains everyone to read red as normal, and then the freshness
failure above — the one worth reading — arrives into an audience that has stopped
looking. The same applies to a newly added skill: warning until it is measured.

Checks are written as `*_failures(scores) -> list[str]` rather than bare asserts so
that a gate with no teeth is itself detectable: the meta-tests in `test_gate_teeth.py` feed
each check a doctored baseline and require it to come back red.
"""
