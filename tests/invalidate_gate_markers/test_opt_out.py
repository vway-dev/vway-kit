"""`gate_evidence.invalidate_on_edit` — 호스트 자신의 답을 줄 단위로 읽음."""

from pathlib import Path

from tests.invalidate_gate_markers._helpers import (
    MARKERS,
    payload,
    pytestmark,  # noqa: F401 — 모듈 수준 skip 은 이 이름으로만 걸림
    repo,
    run,
    vdev,
)

NL = chr(10)


def _switch(project: Path, body: str) -> None:
    cfg = project / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "vdev-config.yaml").write_text(body, encoding="utf-8")


def test_the_host_can_keep_its_markers_through_an_edit(project: Path):
    """이 훅은 **플러그인**이 등록하므로 버전만 올라가도 모든 소비자에게 켜짐 — `/vdev-init`
    재실행도, 누가 동의한 단계도 없음. 영향을 받는 팀이 거절할 수 있어야 함."""
    _switch(project, "gate_evidence:" + NL + "  invalidate_on_edit: false" + NL)
    run(project, payload(str(project / "src" / "a.py")))
    for name in MARKERS:
        assert (vdev(project) / name).exists(), name


def test_the_switch_has_to_be_asked_for(project: Path):
    """켜짐이 기본이고, 스위치가 아닌 것은 전부 켜진 채로 둠(`rules/gate-mechanics.md` 가
    소비자에게 약속한 것). 아래 각 모양은 스위치를 겨냥했지만 빗나간 철자 — 설정 없음, 값이
    true, 실험 중 주석 처리한 줄, 이 리더의 낱말이 아닌 YAML 거짓, 이름이 블록 이름으로
    끝나기만 하는 키, `yaml.safe_load` 도 이 설정으로 읽지 않을 자리 — 중첩 키 밑, 블록
    스칼라 안, 뒤의 중복에 덮인 것, 값·주석 앞에 YAML 이 요구하는 공백이 빠진 것. 흐름
    매핑이나 블록 스칼라를 단 헤더는 블록을 열지 않으므로 그 밑은 읽지 않음. 끄라고 적지 않은
    파일에서 "꺼짐"을 추론하면 게이트가 소리 없이 스스로 꺼짐."""
    for body in (
        None,
        "gate_evidence:" + NL + "  invalidate_on_edit: true" + NL,
        "gate_evidence:" + NL + "  # invalidate_on_edit: false" + NL,
        "gate_evidence:" + NL + "  invalidate_on_edit: no" + NL,
        "gate_evidence:" + NL + "  invalidate_on_edit: off" + NL,
        "gate_evidence:" + NL + "  invalidate_on_edit: False" + NL,
        "invalidate_on_edit: false" + NL,
        "doc_sync:" + NL + "  invalidate_on_edit: false" + NL,
        "foo_gate_evidence:" + NL + "  invalidate_on_edit: false" + NL,
        "gate_evidence:" + NL + "  nested:" + NL + "    invalidate_on_edit: false" + NL,
        "gate_evidence:" + NL + "  note: |" + NL + "    invalidate_on_edit: false" + NL,
        "gate_evidence:"
        + NL
        + "  invalidate_on_edit: false"
        + NL
        + "  invalidate_on_edit: true"
        + NL,
        "gate_evidence:" + NL + "  invalidate_on_edit: false# keep" + NL,
        "gate_evidence:" + NL + "  invalidate_on_edit:false" + NL,
        "gate_evidence: |" + NL + "  invalidate_on_edit: false" + NL,
        "gate_evidence: {invalidate_on_edit: false}" + NL,
        "gate_evidence:"
        + NL
        + "  invalidate_on_edit: false"
        + NL
        + "gate_evidence:"
        + NL
        + "  other: 1"
        + NL,
        "gate_evidence:"
        + NL
        + "  invalidate_on_edit: true"
        + NL
        + "doc_sync:"
        + NL
        + "  invalidate_on_edit: false"
        + NL,
    ):
        for name in MARKERS:
            (vdev(project) / name).touch()
        if body is not None:
            _switch(project, body)
        run(project, payload(str(project / "src" / "a.py")))
        for name in MARKERS:
            assert not (vdev(project) / name).exists(), (body, name)


def test_the_switch_survives_the_shapes_a_real_config_has(project: Path):
    """리더가 줄 단위라 손으로 고친 YAML 의 모양이 그대로 닿아야 함: Windows 편집기의 CRLF,
    키 위·옆의 주석, 자기가 앉은 블록을 닫으면 안 되는 0열 주석, 앞뒤의 다른 블록, YAML 이
    푸는 방식대로 이기는 뒤의 중복, YAML 파서 자신이 거부할 파일. 마지막이 줄 단위로 읽는
    이유 — 설정이 다른 곳에서 깨진 호스트도 이 답은 받음."""
    bodies = (
        "gate_evidence:" + chr(13) + NL + "  invalidate_on_edit: false" + chr(13) + NL,
        "gate_evidence:"
        + NL
        + "  # keep them until the commit"
        + NL
        + "  invalidate_on_edit: false"
        + NL,
        "branches:"
        + NL
        + "  integration: dev"
        + NL
        + "gate_evidence:"
        + NL
        + "  invalidate_on_edit: false"
        + NL
        + "doc_sync:"
        + NL
        + "  index: CLAUDE.md"
        + NL,
        "branches: [oops" + NL + "gate_evidence:" + NL + "  invalidate_on_edit: false" + NL,
        "gate_evidence:" + NL + "# trying this out" + NL + "  invalidate_on_edit: false" + NL,
        "gate_evidence:" + NL + "  invalidate_on_edit: false  # keep them until the commit" + NL,
        "gate_evidence:"
        + NL
        + "  invalidate_on_edit: true"
        + NL
        + "  invalidate_on_edit: false"
        + NL,
    )
    for body in bodies:
        for name in MARKERS:
            (vdev(project) / name).touch()
        _switch(project, body)
        run(project, payload(str(project / "src" / "a.py")))
        for name in MARKERS:
            assert (vdev(project) / name).exists(), (body, name)


def test_a_config_the_reader_cannot_read_leaves_the_hook_armed(project: Path):
    """설정 자리가 파일이 아니면(디렉터리) 첫 `read` 가 줄을 못 채움. 그 빈 변수가 `set -u` 에서
    훅 전체를 죽이면 마커가 남음 — 스위치를 쓴 적 없는 호스트가 이 훅이 절대 틀리면 안 되는
    방향으로 떨어짐. 스위치 리더의 실패는 켜진 채여야 함."""
    (project / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").mkdir(parents=True)
    out = run(project, payload(str(project / "src" / "a.py")))
    assert out.returncode == 0, out.stderr
    for name in MARKERS:
        assert not (vdev(project) / name).exists(), name


def test_each_block_sets_its_own_child_indent(project: Path):
    """블록의 키는 **그 블록의** 첫 키가 정한 들여쓰기에 앉음 — 앞선 `gate_evidence:` 의 깊이가
    뒤에서 무엇이 키인지 정하면 안 됨. YAML 은 중복 블록을 마지막 것으로 풀고 스위치는 거기
    있음. 첫 블록의 더 깊은 들여쓰기를 이어 받으면 그 스위치가 보는 깊이보다 얕아져, 마커를
    지키라고 한 호스트가 계속 잃음."""
    body = (
        "gate_evidence:"
        + NL
        + "    unrelated: 1"
        + NL
        + "doc_sync:"
        + NL
        + "  index: CLAUDE.md"
        + NL
        + "gate_evidence:"
        + NL
        + "  invalidate_on_edit: false"
        + NL
    )
    _switch(project, body)
    run(project, payload(str(project / "src" / "a.py")))
    for name in MARKERS:
        assert (vdev(project) / name).exists(), name


def test_one_repo_opting_out_does_not_speak_for_another(project: Path, tmp_path: Path):
    """스위치는 호스트가 다시 벌어야 할 **자기** 증거에 대해 하는 답이라, 이 편집이 낡게 만든
    트리마다 따로 물음. 끈 프로젝트의 세션이 끈 적 없는 repo 의 파일을 고치면, 그 repo 의
    마커가 그곳의 누구도 쓰지 않은 설정 때문에 남음."""
    other = repo(tmp_path / "other")
    _switch(project, "gate_evidence:" + NL + "  invalidate_on_edit: false" + NL)
    edited = other / "src" / "a.py"
    edited.parent.mkdir(parents=True, exist_ok=True)
    edited.write_text("x", encoding="utf-8")
    run(project, payload(str(edited)))
    for name in MARKERS:
        assert not (vdev(other) / name).exists(), f"{name}: 편집된 repo 가 마커를 지켰다"
        assert (vdev(project) / name).exists(), f"{name}: 끈 프로젝트가 마커를 잃었다"
