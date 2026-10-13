"""픽스처 — 프롬프트가 전제하는 프로젝트를 실제로 세움.

프로젝트를 전제하는 프롬프트는 픽스처를 선언해야 하고, 그 이름은 실재하는 샌드박스
시나리오여야 함. 동시 세션은 한 픽스처를 공유하되 디렉터리는 나눠 씀.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from evals.runner import case_corpus, config, invocation, ratchet, session
from evals.runner.case_corpus import (
    load_cases,
)
from evals.runner.config import (
    EvalError,
)
from evals.runner.session import (
    DEFAULT_CWD_LABEL,
)
from scripts import skill_sandbox
from tests.eval_harness._presuppositions import (
    PRESUPPOSES,
    PRESUPPOSES_ABSENCE,
    _fixture_evidence,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._stubs import (
    _stub_sessions,
)


def test_every_declared_fixture_names_a_real_sandbox_scenario():
    """A typo'd fixture name must not fall back to an empty directory. The run would still
    produce a number, and a wrong number is indistinguishable from a real score (spec 4.5).
    """
    _, cases = load_cases()  # load_cases itself must reject an unknown name
    declared = {
        case.fixture
        for spec in cases.values()
        for arm in ("happy", "negative")
        for case in case_corpus.arm_cases(spec, arm)
        if case.fixture is not None
    }
    unknown = sorted(declared - set(skill_sandbox.BY_NAME))
    assert not unknown, f"cases.yaml names fixture(s) skill_sandbox does not build: {unknown}"


def test_an_unknown_fixture_name_fails_closed(tmp_path, monkeypatch):
    """Fail-closed rather than fail-open, which is the opposite of this repo's default for
    gate scripts -- and deliberately so. A gate that fails open lets a commit through; a
    measurement that falls back to an empty directory writes a fabricated score into a
    committed baseline that everything downstream then trusts.
    """
    corpus = tmp_path / "cases.yaml"
    corpus.write_text(
        "reps: 1\nskills:\n  vdev:\n    fixture: no-such-scenario\n"
        "    expect_invoke: 0.9\n    expect_why: x\n    happy:\n      - prompt: p\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CASES_PATH", corpus)
    with pytest.raises(EvalError) as caught:
        load_cases()
    assert "no-such-scenario" in str(caught.value)


def test_a_prompt_that_presumes_a_project_declares_a_fixture():
    """Validity, not effect size (spec 4.5): playwright-scaffold's trigger is "a web project
    with no specs yet", and an empty directory has no web project. Whatever number comes out
    of that is not a measurement of the skill.

    The four skills below are the ones `skill_sandbox` can decide; the other five are keyed
    on vocabulary rather than project shape, so a fixture would only add wall-clock.
    """
    _, cases = load_cases()
    expected = {
        "integration": "custom-testdir",
        "playwright-scaffold": "empty-web",
        "performance": "perf-n-plus-one",
        "doc-sync": "doc-sync-drift",
    }
    for name, fixture in expected.items():
        assert cases[name].get("fixture") == fixture, f"{name} lost its default fixture"
    for name in ("vdev", "task-import", "task-sync", "harness-insight", "harness-authoring"):
        assert cases[name].get("fixture", "MISSING") is None, (
            f"{name}: `fixture: null` is a judgement (spec 4.5), so the key must be present"
        )


def test_no_prompt_contradicts_the_project_it_is_measured_in(tmp_path):
    """The check spec 4.5 demands and the corpus comment claims was done, made mechanical.

    Its predecessor asserted only how many skills carry a `fixture:` default and how many
    carry null -- it read no prompt text at all, so every prompt could have contradicted its
    fixture and it would still have passed. That is why three contradictions survived into a
    corpus whose own header claimed every skill had been cross-checked: a `performance`
    happy prompt asking for an EXPLAIN plan against three static files, and two negatives
    naming a pytest suite and a header component that neither fixture contains.

    Both arms, because the negative arm is where the earlier sweep stopped. A refuted
    negative writes a clean `0` into `false_fire` that the fixture caused rather than the
    description's precision -- and `false_fire` carries this harness's only surviving
    absolute threshold.

    `fixture: null` cases are skipped, and that is the doctrine rather than a gap: an empty
    directory shows no project, so it REFUTES nothing. A fixture holding a different stack
    is what refutes, which is why null is the corpus's escape hatch for a prompt no scenario
    can stand up.
    """
    _, cases = load_cases()
    evidence: dict[str, str] = {}
    problems: list[str] = []

    for name, spec in sorted(cases.items()):
        for arm in ("happy", "negative"):
            for index, case in enumerate(case_corpus.arm_cases(spec, arm), 1):
                if case.fixture is None:
                    continue
                if case.fixture not in evidence:
                    evidence[case.fixture] = _fixture_evidence(
                        case.fixture, tmp_path / case.fixture
                    )
                blob = evidence[case.fixture]
                where = f"{name}.{arm}[{index}] on fixture {case.fixture!r}"
                for pattern, presumes, wanted in PRESUPPOSES:
                    if re.search(pattern, case.prompt) and not any(w in blob for w in wanted):
                        problems.append(
                            f"{where} presumes {presumes}, which the fixture does not "
                            f"build. The agent spends turns on a referent that is not "
                            f"there, and that miss is unrecoverable by any description "
                            f"edit. Fix the prompt or override the case's fixture."
                        )
                for pattern, presumes, forbidden in PRESUPPOSES_ABSENCE:
                    if re.search(pattern, case.prompt) and any(w in blob for w in forbidden):
                        problems.append(
                            f"{where} presumes {presumes}, but the fixture contains it. A "
                            f"negative refuted this way can make the wrong answer correct, "
                            f"which moves false_fire for a reason that is not the "
                            f"description."
                        )
    assert not problems, "\n".join(problems)


def test_the_presupposition_table_would_have_caught_the_three_known_contradictions(tmp_path):
    """The test above passes on a corpus that was fixed, so on its own it cannot show
    it does anything. This one replays the prompts as they stood before each fix and requires
    each to be rejected -- the difference between a guard and a green light.

    Grown once already: the `commit` corpus reproduced the same class of contradiction months
    later, against git state rather than files, so the replays below cover both rounds.
    """
    evidence = {
        name: _fixture_evidence(name, tmp_path / name)
        for name in ("perf-n-plus-one", "empty-web", "custom-testdir", "commit-dirty-tree")
    }

    def rejected(prompt: str, fixture: str) -> bool:
        blob = evidence[fixture]
        return any(
            re.search(pattern, prompt) and not any(w in blob for w in wanted)
            for pattern, _, wanted in PRESUPPOSES
        ) or any(
            re.search(pattern, prompt) and any(w in blob for w in forbidden)
            for pattern, _, forbidden in PRESUPPOSES_ABSENCE
        )

    # Finding 3: an EXPLAIN plan wanted from pyproject.toml + two .py files.
    assert rejected("이 조인 쿼리 실행계획 떠서 느린 원인 플래깅해줘.", "perf-n-plus-one")
    # Finding 4: a pytest suite in a fixture with no test file and no pytest dependency.
    assert rejected("pytest 전체가 12분 걸려. 병렬로 돌려서 시간 줄여줘.", "perf-n-plus-one")
    # Finding 4: a header component in a fixture whose only markup is a one-line index.html.
    assert rejected("이 헤더 컴포넌트에 다크모드 스타일 입혀줘.", "empty-web")

    # And the absence direction, which is the one that can make a wrong answer correct:
    # "there are no cases" measured where two specs sit on disk.
    assert rejected("웹 프로젝트인데 Playwright 케이스가 하나도 없어.", "custom-testdir")
    assert not rejected("웹 프로젝트인데 Playwright 케이스가 하나도 없어.", "empty-web")

    # The commit corpus, whose first draft inherited `commit-dirty-tree` for all ten cases and
    # then presupposed three things that fixture refutes: a staged change against an empty
    # index, three commits against a single seed, and a rules/ directory that is not there.
    # The table saw none of them until git state became evidence, which is why these are
    # pinned here rather than only fixed in the corpus.
    assert rejected("스테이징한 변경에 맞는 커밋 메시지 써줘.", "commit-dirty-tree")
    assert rejected("최근 커밋 세 개를 하나로 squash 해줘.", "commit-dirty-tree")
    assert rejected(
        "rules 밑 .md 만 고쳤는데 docs 로 커밋하면 소비자한테 전파돼?", "commit-dirty-tree"
    )
    # ...while the prompts that replaced them are not rejected: a guard that fires on the
    # corpus it is guarding would force the corpus back to hypotheticals.
    assert not rejected("이 커밋 메시지 본문 초안 잡아줘.", "commit-dirty-tree")
    assert not rejected("마지막 커밋 되돌려줘.", "commit-dirty-tree")


def test_a_case_may_override_the_skill_level_fixture():
    """The sister repo froze `integration` at 4/15 because two happy prompts said "there is
    no automation yet" while the skill-level fixture shipped a real suite. The agent spent
    its turns reconciling the contradiction, and no description rewrite can recover those
    samples (spec 4.5) -- so the override has to exist and has to win.
    """
    spec = {
        "fixture": "custom-testdir",
        "happy": [{"prompt": "a"}, {"prompt": "b", "fixture": "empty-web"}],
        "negative": [{"prompt": "c", "fixture": None}],
    }
    assert case_corpus.arm_cases(spec, "happy") == [
        case_corpus.Case("a", "custom-testdir"),
        case_corpus.Case("b", "empty-web"),
    ]
    assert case_corpus.arm_cases(spec, "negative") == [case_corpus.Case("c", None)], (
        "an explicit null override must beat the skill-level default, not be read as absent"
    )


def test_the_session_runs_inside_the_built_fixture_rather_than_its_parent(tmp_path):
    """`sandbox.build` creates `root/<scenario>` and returns THAT path. Running in the parent
    puts the agent in a directory holding one subdirectory -- which is the empty-cwd
    condition this whole change removes, reintroduced one level up.
    """
    workspace = session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg")
    with session.session_cwd(workspace, "empty-web") as cwd:
        assert (cwd / "package.json").is_file(), f"the session would have run in {cwd}"
        assert (cwd / "playwright.config.ts").is_file()

    with session.session_cwd(workspace, None) as empty:
        assert list(empty.iterdir()) == [], "a fixtureless case runs in a genuinely empty dir"


def test_concurrent_sessions_on_one_fixture_do_not_share_a_directory(tmp_path):
    """`sandbox.build` rmtree's its target before rebuilding it. Eight sessions at a time
    against one root would delete each other's working directory mid-run, and the failures
    would land in `invoke_rate` as descriptions that did not fire.

    Genuinely concurrent, on `CONCURRENCY` threads, with a barrier holding every session
    inside its context while the others build. The version this replaces nested two context
    managers on ONE thread -- the sessions never overlapped, so the rmtree never had a
    neighbour to delete, and its `first != second` assertion was guaranteed by
    `tempfile.TemporaryDirectory` no matter what `session_cwd` did.

    The marker file is what makes it bite: each thread writes its own id and re-reads it
    after every other thread has finished building. A rebuild landing in a shared directory
    destroys the marker, and a directory handed out twice returns the wrong one.
    """
    workspace = session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg")
    threads = config.CONCURRENCY
    built = threading.Barrier(threads, timeout=60)

    def one(index: int) -> str:
        with session.session_cwd(workspace, "empty-web") as cwd:
            (cwd / "who.txt").write_text(str(index), encoding="utf-8")
            built.wait()  # nobody leaves until every session has built and marked
            assert (cwd / "package.json").is_file(), f"session {index} lost its fixture"
            assert (cwd / "who.txt").read_text(encoding="utf-8") == str(index), (
                f"session {index} is looking at another session's directory"
            )
            return str(cwd)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        directories = list(pool.map(one, range(threads)))
    assert len(set(directories)) == threads, "a directory was handed to two sessions"


def test_the_recorded_environment_names_both_the_isolation_and_the_fixture(monkeypatch, tmp_path):
    """The fixture is a measurement condition: the same description scores differently in a
    web project and in an empty directory, which is the entire premise of spec 4.5. If the
    label does not carry it, `incomparable_conditions` cannot see a fixture swap and reads
    the difference as a regression.
    """
    _stub_sessions(monkeypatch)
    workspace = session.Workspace(root=tmp_path, config_dir=tmp_path / "cfg")
    entry = invocation.measure_skill(
        "vdev",
        {"fixture": "empty-web", "happy": [{"prompt": "happy"}], "negative": [{"prompt": "neg"}]},
        reps=1,
        workspace=workspace,
        binary="stub-claude",
        max_turns=3,
        model=config.MODEL,
    )
    assert entry["cwd"] == "isolated:empty-web", entry["cwd"]

    mixed = invocation.measure_skill(
        "vdev",
        {
            "fixture": "empty-web",
            "happy": [{"prompt": "happy"}],
            "negative": [{"prompt": "neg", "fixture": "custom-testdir"}],
        },
        reps=1,
        workspace=workspace,
        binary="stub-claude",
        max_turns=3,
        model=config.MODEL,
    )
    assert mixed["cwd"] == "isolated:custom-testdir+empty-web", (
        "a per-case override changes the environment and has to show up in the label"
    )


def test_isolation_rides_on_the_cwd_condition_rather_than_on_a_new_key(monkeypatch):
    """Where the isolation flag is recorded is a real decision, and a new key is the wrong
    place for it.

    `incomparable_conditions` treats a key missing on EITHER side as "not changed" -- on
    purpose, so that entries written before a condition existed do not disable the ratchet
    everywhere at once. That tolerance is exactly what makes a NEW key useless here: it is
    absent from every pre-isolation entry, so it can never differ from one. Folding
    isolation into `cwd`, a key those entries all carry, is what makes the change visible.
    """
    old = {"model": config.MODEL, "max_turns": 3, "cwd": "<empty temp dir>"}
    isolated = {**old, "cwd": DEFAULT_CWD_LABEL}
    assert ratchet.incomparable_conditions(isolated, old) == {
        "cwd": ("<empty temp dir>", DEFAULT_CWD_LABEL)
    }

    monkeypatch.setattr(
        ratchet, "COMPARABLE_CONDITIONS", (*ratchet.COMPARABLE_CONDITIONS, "isolated")
    )
    assert ratchet.incomparable_conditions({**old, "isolated": True}, old) == {}, (
        "a new condition key is invisible against the baseline it exists to protect"
    )
