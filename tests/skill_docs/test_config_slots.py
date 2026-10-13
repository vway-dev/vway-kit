"""vdev-config 슬롯과 그 값을 읽는 스킬은 한 쌍 — 한쪽만 개명되면 조용히 끊어짐.

슬롯은 `vdev-config.example.yaml` 이 광고해야 `/vdev-init` Step 2.5 의 backfill 이 기존
호스트에 실어 나르고, 같은 철자를 스킬 본문이 조회해야 값이 실제로 쓰임. 어느 쪽의 개명도
실패를 안 냄 — 조회가 빈 값을 돌려주고 스킬은 자기 일반론으로 떨어지며, 호스트가 우선시키려던
사실은 영영 안 읽힘.

레지스트리는 **닫힌 목록** — 스킬 전부에서 슬롯처럼 생긴 낱말을 긁는 열린 감사는 끝나지 않고,
새 슬롯을 여기 적는 것 자체가 커버리지 결정임.
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from tests._bash import BASH
from tests._non_utf8 import non_utf8_env
from tests._proc import run_bounded
from tests.skill_docs._helpers import REPO, bash_blocks, body

EXAMPLE = REPO / "vdev-config.example.yaml"


@dataclass(frozen=True)
class Slot:
    """선언 하나 = config 키 하나와 그것을 읽는 스킬들."""

    key: str
    # 스킬 본문에 그대로 서 있어야 하는 조회 철자. 키 이름과 다를 수 있음 — 중첩 키는
    # 스킬이 경로로 적고, 코드로 조회하는 것은 따옴표까지 철자의 일부.
    lookup: str
    readers: tuple[str, ...]
    # 키가 없을 때의 폴백을 그 스킬이 적어 둔 자리. 폴백이 안 적히면 슬롯 부재가 결함처럼
    # 읽히고, 슬롯을 안 쓰는 호스트에서 스킬이 멈추는 절차가 만들어짐.
    fallback: str
    # example 에서 활성 키인가. False = 주석 블록(값이 호스트마다 달라 활성으로 두면
    # /vdev-init 이 남의 값을 심음).
    active: bool


SLOTS = (
    Slot(
        key="commit_guide",
        lookup="'commit_guide'",
        readers=("skills/commit/SKILL.md",),
        fallback="no host guide",
        active=True,
    ),
    Slot(
        key="issue_tracker_guide",
        lookup="issue_tracker_guide",
        readers=(
            "skills/alm-trace/SKILL.md",
            "skills/task-import/SKILL.md",
            "skills/task-sync/SKILL.md",
        ),
        fallback="없으면 그대로 진행",
        active=True,
    ),
    Slot(
        key="alm",
        lookup="alm.worklog",
        readers=("skills/task-sync/SKILL.md",),
        fallback="`alm.worklog` 가 없거나 false",
        active=True,
    ),
    Slot(
        key="promotion_verification",
        lookup="promotion_verification.exit_criteria",
        readers=("skills/release-commit/SKILL.md",),
        fallback="No key",
        active=False,
    ),
)

SLOT_IDS = [s.key for s in SLOTS]


def _example_text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


def _example_keys() -> dict:
    data = yaml.safe_load(_example_text())
    assert isinstance(data, dict), "vdev-config.example.yaml no longer parses as a mapping"
    return data


def _flat(path: str) -> str:
    """줄바꿈을 지운 본문 — 산문의 앵커는 100자 줄바꿈에 걸려 두 줄로 쪼개져 있음."""
    return re.sub(r"\s+", " ", body(REPO / path))


def _spells(text: str, token: str) -> bool:
    """`token` 이 낱말 하나로 서 있는가. 부분문자열 검사로는 접미 개명이 안 잡힘 —
    `issue_tracker_guide_path` 는 옛 이름을 통째로 품고 있으면서 다른 키임."""
    return re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text) is not None


@pytest.mark.parametrize("slot", SLOTS, ids=SLOT_IDS)
def test_the_example_advertises_every_declared_slot(slot: Slot):
    """활성 슬롯은 파싱되는 키로, 비활성 슬롯은 주석으로 — 둘 다 example 에 있어야 함.

    backfill 은 example 이 광고하는 슬롯만 제안하므로, 키가 사라지면 기존 호스트는 그 슬롯을
    영영 못 받음. 비활성 슬롯이 주석에서마저 사라지면 호스트는 그런 키가 있는 줄도 모름."""
    keys = _example_keys()
    if slot.active:
        assert slot.key in keys, (
            f"vdev-config.example lost its `{slot.key}` slot — /vdev-init's backfill only "
            f"offers slots the example advertises, so existing hosts stop receiving it"
        )
    else:
        assert slot.key not in keys, (
            f"`{slot.key}` became an active key — /vdev-init would then plant this "
            f"example's value in every host, where it names things that do not exist"
        )
        assert re.search(rf"^#\s*{slot.key}:", _example_text(), re.M), (
            f"`{slot.key}` is neither active nor commented in the example — the slot is "
            f"unreachable for a host that never reads the skill"
        )


@pytest.mark.parametrize("slot", SLOTS, ids=SLOT_IDS)
def test_every_declared_slot_still_has_the_readers_it_claims(slot: Slot):
    """레지스트리가 지목한 스킬 전부가 그 철자를 조회하고, 부재 시 폴백을 적어야 함."""
    for rel in slot.readers:
        assert (REPO / rel).is_file(), f"{slot.key}: reader {rel} no longer exists"
        text = _flat(rel)
        assert _spells(text, slot.lookup), f"{rel} no longer reads the `{slot.key}` slot"
        assert slot.fallback in text, (
            f"{rel} stopped documenting what happens with no `{slot.key}` — a host that "
            f"never sets the slot is the common case, not a failure"
        )


def test_the_slot_registry_covers_every_guide_slot_the_example_ships():
    """반대 방향 — example 이 광고하는 `*_guide` 슬롯 중 레지스트리에 없는 것.

    위 테스트들은 레지스트리에서 출발하므로 **새로 생긴** 슬롯을 영원히 못 봄. 그것이
    `commit_guide` 가드가 홀로 서 있던 동안 `issue_tracker_guide` 가 가드 없이 출하된 경로임."""
    declared = {s.key for s in SLOTS}
    shipped = {k for k in _example_keys() if k.endswith("_guide")}
    assert shipped <= declared, (
        f"example ships guide slot(s) with no reader guard: {sorted(shipped - declared)} — "
        f"add them to SLOTS with the skills that read them"
    )


# 슬롯 값을 인라인 인터프리터로 꺼내 stdout 으로 넘기는 블록 — (문서, 키, 기대 출력).
# `commit` 블록은 받은 경로의 파일을 cat 하므로 기대 출력이 그 본문임.
_GUIDE = "docs/운영/규약.md"
_PRINTED_SLOTS = (
    ("skills/alm-trace/SKILL.md", "issue_tracker_guide", _GUIDE),
    ("skills/commit/SKILL.md", "commit_guide", "규약 본문"),
)


@pytest.mark.parametrize(
    ("rel", "key", "expected"), _PRINTED_SLOTS, ids=[key for _, key, _ in _PRINTED_SLOTS]
)
def test_a_korean_guide_path_survives_a_non_utf8_locale(
    tmp_path: Path, rel: str, key: str, expected: str
):
    """값은 호스트가 적는 것이라 한글 경로가 정상 입력임. 로캘이 UTF-8 이 아닌 호스트에서 `print`
    는 그 값을 로캘 코드페이지로 적고 에이전트는 UTF-8 로 읽음 — 경로가 깨지거나, 인코딩 오류를
    `2>/dev/null` 이 삼켜 `commit` 이 "no host guide" 로 떨어짐."""
    if BASH is None:
        pytest.skip("no usable bash on this host")
    blocks = [b for b in bash_blocks(body(REPO / rel)) if key in b]
    assert len(blocks) == 1, f"{rel}: `{key}` 를 읽는 bash 블록이 {len(blocks)}개"
    config = tmp_path / ".claude" / "vway-kit" / "config"
    config.mkdir(parents=True)
    (config / "vdev-config.yaml").write_text(f"{key}: {_GUIDE}\n", encoding="utf-8")
    (tmp_path / _GUIDE).parent.mkdir(parents=True)
    (tmp_path / _GUIDE).write_text("규약 본문\n", encoding="utf-8")
    # 블록의 `python3` 을 이 테스트의 인터프리터로 — 시스템 python3 엔 PyYAML 이 없을 수 있음.
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python3").write_text(
        f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    (shim / "python3").chmod(0o755)
    env = non_utf8_env(PATH=f"{shim}{os.pathsep}{os.environ.get('PATH', '')}")
    proc = run_bounded([BASH, "-s"], input=blocks[0].encode("utf-8"), cwd=tmp_path, env=env)
    stderr = proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode("utf-8", "replace").strip() == expected, stderr


def test_the_commit_guide_default_points_at_a_generated_document():
    """`commit_guide` 만 생성기를 가짐 — 기본값이 harness-authoring 이 실제로 만드는 경로."""
    assert _example_keys()["commit_guide"] == "docs/operations/commit-versioning-guide.md"
    guide = (REPO / "skills/harness-authoring/references/tech-doc-guide.md").read_text(
        encoding="utf-8"
    )
    assert _example_keys()["commit_guide"] in guide, (
        "tech-doc-guide no longer generates the doc the commit_guide default points at"
    )


def test_the_issue_tracker_guide_default_is_declared_host_authored():
    """`issue_tracker_guide` 는 생성기가 **없는** 것이 의도 — 그 사실이 example 에 적혀야 함.

    commit_guide 의 기본값은 harness-authoring 이 만드는 파일이지만 이쪽 기본값을 만드는
    주체는 없음. 적어 두지 않으면 다음 사람이 그것을 결함으로 읽고 생성기를 붙이거나, 반대로
    호스트가 오지 않을 문서를 기다리며 슬롯을 통째로 버림."""
    default = _example_keys()["issue_tracker_guide"]
    assert default == "docs/operations/issue-tracker.md"
    assert "호스트가 직접 저작" in _example_text(), (
        "the example no longer says the issue_tracker_guide document is host-authored, so "
        "its default reads like a broken pointer to a file something ought to generate"
    )
    generator = (REPO / "skills/harness-authoring/references/tech-doc-guide.md").read_text(
        encoding="utf-8"
    )
    assert default not in generator, (
        f"something now generates {default} — drop the host-authored note and give this "
        f"slot the same generated-document assertion commit_guide has"
    )


def test_the_promotion_verification_block_records_why_it_stays_commented():
    """주석 블록의 세 키가 그대로 있고, 주석인 이유가 그 자리에 적혀야 함.

    이유가 없으면 다음 편집자가 "왜 주석이지" 로 읽고 활성화하며, 그 순간 모든 호스트의
    exit criteria 가 이 예시의 suite 이름을 요구해 영구 미충족이 됨."""
    text = _example_text()
    block = re.search(r"(?:^#.*\n)*^# promotion_verification:\n(?:^#.*\n)+", text, re.M)
    assert block, "the commented promotion_verification block is gone from the example"
    for key in ("exit_criteria:", "scope:", "allow_blocked:"):
        assert key in block.group(0), f"the commented block lost `{key}`"
    assert "주석 유지" in block.group(0), (
        "the block no longer says why it is commented — the next editor uncomments it"
    )


def test_the_example_advertises_the_worklog_switch_off():
    """기본 꺼짐 — 켜진 채 백필되면 모든 호스트가 transcript 를 읽기 시작함."""
    assert _example_keys()["alm"]["worklog"] is False
