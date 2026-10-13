"""훅이 이름을 대는 스킬은 훅 보조를 선언해야 함.

SessionStart 주입문이 슬래시 이름으로 부르는 스킬은 그 도움을 받은 채 측정됨 —
선언하지 않으면 측정치가 무엇의 성적인지 알 수 없음.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

from evals.runner import config
from evals.runner.baseline import (
    description_sha,
)
from evals.runner.case_corpus import (
    load_cases,
)
from evals.runner.config import (
    CASES_PATH,
    SKILLS_DIR,
)

# A skill over the ceiling hijacks sessions it has no business in -- a shipped
# defect at any calibration, because a skill that intercepts a fifth of its
# neighbours' prompts is wrong however rarely it fires on its own.
from tests.eval_harness._stubs import (
    _injected_session_text,
    _skills_named_as_commands,
)


def test_the_hook_scan_does_not_match_a_longer_name_or_a_path():
    """`/vdev` must not be found inside `/vdev-init`, `/vdev-uninstall`, or a markdown link
    like `](../vdev-tiers.yaml)` -- all of which the shipped rule file and hook contain.

    A `\\b` boundary matches immediately before a hyphen, so it read all three as
    invocations, which would keep `vdev` in the named set from a relative link alone and make
    the reverse "the help is gone" branch unable to fire for the skill it matters most for.
    vway-kit is the sharper case than the sister repo: `vdev`, `vdev-init` and
    `vdev-uninstall` are three real sibling skills, so the boundary earns its keep here."""
    assert _skills_named_as_commands("see [vdev-tiers.yaml](../vdev-tiers.yaml)") == set()
    assert _skills_named_as_commands("run /vdev-uninstall to remove the gate") == set()
    assert _skills_named_as_commands("`/vdev-init` copies the scripts") == set()
    # ...while still finding the real ones, punctuation and all.
    assert _skills_named_as_commands("enter `/vdev` first") == {"vdev"}
    assert _skills_named_as_commands("2. Run /doc-sync to harmonize.") == {"doc-sync"}


def test_every_skill_the_injected_rule_names_declares_hook_assisted():
    """The SessionStart hook injects its text into EVERY session, so a skill it tells the
    agent to run is measured with help that no consumer-free reading would give it. That is
    deliberate -- consumers get the hook too -- but it has two consequences per affected
    skill: its rate is not comparable to the others, and its ratchet is partly blind to its
    own description, since the hook can hold the number up while the description rots.

    Checked rather than commented because prose rots silently: vdev, doc-sync and task-sync
    already narrate the hook's help in their expect_why, and prose is exactly what was wrong
    twice in the sister repo. No count is written here -- the check reads the injected text
    (the hook's preamble as well as the rule file it wraps) and the declared fields, both
    directions."""
    named = _skills_named_as_commands(_injected_session_text())
    _, cases = load_cases()
    measured = set(cases)
    for name in sorted(named & measured):
        assert cases[name].get("hook_assisted") is True, (
            f"{name}: the injected session text names /{name}, and it reaches every eval "
            f"session -- declare `hook_assisted: true` in {CASES_PATH.name} and say in the "
            f"entry what the hook does for it."
        )
    for name in sorted(measured):
        if cases[name].get("hook_assisted") and name not in named:
            raise AssertionError(
                f"{name}: declares hook_assisted but nothing the SessionStart hook injects "
                f"names /{name} any more -- the help is gone, so the caveat is stale and the "
                f"rate is now comparable to the unassisted skills."
            )


def test_a_hook_assisted_skill_rehashes_when_the_injected_text_changes(tmp_path):
    """주입 룰 편집은 `hook_assisted` 스킬의 기록된 점수를 무효로 만들어야 함.

    상류 harness-tier 실측(2026-09-08): 같은 스킬이 **바이트가 같은 설명문**으로 0.82(n=55)와
    0.55(n=65)를 냈고, 차이는 `rules/risk-tiers.md` 의 FIRST-action 명령문 바로 앞에 두 줄이
    붙은 것뿐이었음. `description_sha` 가 설명문만 해시하던 동안 그 하락은 아무 신호 없이
    착지해 네 커밋을 살아남았음 — cases.yaml 은 이미 "이 스킬의 회귀는 설명문과 훅을 함께
    읽으라" 고 적어 두었지만 그것을 기계로 붙잡는 것이 없었음.

    주입 텍스트를 제자리에서 고치지 않고 monkeypatch 하는 이유: 이 스위트는 더러운 트리에서도
    돌아야 하고, 해시를 재려고 출하 룰 파일을 덮어쓰는 테스트는 실행이 한 번 끊기면 그것을
    덮어쓴 채로 남김.
    """
    _, cases = load_cases()
    names = sorted(cases)
    before = {n: description_sha(SKILLS_DIR / n) for n in names}

    edited = tmp_path / "risk-tiers.md"
    edited.write_text("# 출하된 룰이 아님\n", encoding="utf-8")
    with mock.patch.object(config, "INJECTED_PATHS", (edited,)):
        after = {n: description_sha(SKILLS_DIR / n) for n in names}

    assisted = [n for n in names if (cases[n] or {}).get("hook_assisted")]
    assert assisted, "cases.yaml 이 hook_assisted 스킬을 하나도 선언 안 함 — 이 테스트는 공허함"
    for name in assisted:
        assert before[name] != after[name], (
            f"{name}: hook_assisted 를 선언했는데 해시가 바뀐 주입 룰을 안 읽음 — "
            f"rules/risk-tiers.md 편집이 낡은 점수를 게이트에 통과시킴."
        )
    for name in names:
        if name not in assisted:
            assert before[name] == after[name], (
                f"{name}: hook_assisted 가 아닌데 주입 룰이 해시를 움직임 — "
                f"그 파일 편집마다 불필요한 재측정을 강요함."
            )


def test_the_hash_inputs_match_what_the_hook_injects():
    """해시에 넣는 파일 목록은 훅이 실제로 읽는 것에서 **유도**돼야 함.

    어긋나면 "재측정하라" 는 요구의 근거가 거짓이 됨 — 주입 안 되는 파일을 담으면 헛된
    재측정을, 주입되는 파일을 빠뜨리면 조용한 stale 을 만듦.

    이름을 손으로 적어 넣는 포함 검사로는 **빠진 것**을 못 잡음. 실제로 그렇게 놓쳤음:
    자매 저장소 훅에는 `doc-style.md` 가 없어 그쪽 목록(둘)을 그대로 베꼈고, 이 훅이
    읽는 셋째 파일이 조용히 빠졌음. 그래서 훅의 `*_FILE=` 대입에서 집합을 만들어
    **양방향**으로 비교함.
    """
    hook_path = Path(config.REPO_ROOT) / "hooks" / "inject-risk-tiers.sh"
    hook = hook_path.read_text(encoding="utf-8")
    # 훅이 플러그인 루트 기준으로 읽는 파일 전부. 매니페스트(.claude-plugin/plugin.json)는
    # 버전 비교용이라 세션에 안 실림 — 주입되는 것만 셈.
    read_by_hook = {
        m.group(1)
        for m in re.finditer(r'^[A-Z_]+="\$\{PLUGIN_ROOT\}/(\S+?)"', hook, re.MULTILINE)
        if m.group(1).startswith("rules/")
    }
    assert read_by_hook, "훅에서 룰 파일 대입을 하나도 못 읽음 — 이 테스트가 공허해짐"

    listed = {p.relative_to(config.REPO_ROOT).as_posix() for p in config.INJECTED_PATHS}
    hook_rel = hook_path.relative_to(config.REPO_ROOT).as_posix()
    assert hook_rel in listed, "훅 자신의 서문도 세션에 실림 — 목록에 있어야 함"

    assert listed - {hook_rel} == read_by_hook, (
        f"해시가 읽는 목록과 훅이 읽는 목록이 다름 — 빠짐 {read_by_hook - listed}, "
        f"군더더기 {listed - read_by_hook - {hook_rel}}"
    )
    for injected in config.INJECTED_PATHS:
        assert injected.is_file(), f"{injected} 가 없음 — 해시가 못 읽는 파일을 가리킴"


def test_the_hash_folds_crlf_so_it_does_not_fingerprint_the_checkout(tmp_path):
    """줄바꿈이 다른 두 체크아웃이 같은 해시를 내야 함.

    이 저장소는 Windows 에서 CRLF, ubuntu 러너에서 LF 로 체크아웃됨(`core.autocrlf`).
    날바이트로 해시하면 한쪽에서 기록한 값이 다른 쪽 CI 에서 전부 stale 로 잡히고,
    어느 쪽에서 재측정해도 반대쪽이 깨지므로 **고정점이 없음**.
    """
    name = next(n for n, v in load_cases()[1].items() if (v or {}).get("hook_assisted"))
    lf, crlf = tmp_path / "lf.md", tmp_path / "crlf.md"
    lf.write_bytes(b"line one\nline two\n")
    crlf.write_bytes(b"line one\r\nline two\r\n")

    with mock.patch.object(config, "INJECTED_PATHS", (lf,)):
        as_lf = description_sha(SKILLS_DIR / name)
    with mock.patch.object(config, "INJECTED_PATHS", (crlf,)):
        as_crlf = description_sha(SKILLS_DIR / name)
    assert as_lf == as_crlf, (
        f"{name}: 같은 내용이 줄바꿈 때문에 다른 해시를 냄 — 기록된 점수가 체크아웃 "
        f"플랫폼에 종속되고, Windows 와 ubuntu 중 한쪽은 항상 빨감."
    )


def test_an_unreadable_injected_file_is_named_not_a_bare_traceback():
    """없는 주입 파일은 `EvalError` 로 이름을 대야 함 — 형제 분기(no SKILL.md)와 같은 모양.

    OSError 로 새어 나가면 `_checks.py` 도 `main()` 도 EvalError 만 잡으므로 스킬별 판정
    대신 raw 트레이스백이 뜸.
    """
    name = next(n for n, v in load_cases()[1].items() if (v or {}).get("hook_assisted"))
    missing = Path(config.REPO_ROOT) / "rules" / "이런-파일은-없음.md"
    with mock.patch.object(config, "INJECTED_PATHS", (missing,)):
        with pytest.raises(config.EvalError) as excinfo:
            description_sha(SKILLS_DIR / name)
    assert missing.name in str(excinfo.value)
