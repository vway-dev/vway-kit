"""wiki 런타임 게이트 — 모듈 명령이 아니라 vdev 게이트의 프로세스 내부 단계.

모듈 명령 채널로 돌리면 내부 오류가 모든 커밋을 막으므로 금지. 마커도 없음.
`vdev-config.wiki` 가 켤 때만 돌고, 내부 실패는 FAIL-OPEN.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import yaml

import scripts.vdev_gate_check as fgc
from scripts import wiki_graph
from scripts._vway_paths import RUNTIME_GATES
from scripts.vdev_gate_check import (
    missing_gates,
    module_commands,
)
from scripts.wiki_graph import cmd_build
from tests._proc import run_bounded
from tests.gate_check._helpers import (
    _classify_docs,
    _classify_worktree_module,
    _init_repo,
    _main_gate,
    _rg,
    _run_runner,
    _wiki_host,
    requires_bash_git,
    requires_git,
)


def test_wiki_is_a_runtime_gate_needing_no_marker(tmp_path: Path):
    assert "wiki" in RUNTIME_GATES
    vdev = tmp_path / ".vdev"
    vdev.mkdir()
    assert "wiki" not in missing_gates(vdev, ["wiki", "doc-sync"])


def test_wiki_gate_blocks_a_drifted_graph_on_the_docs_tier(tmp_path: Path):
    # docs 티어는 module_commands 가 조기 종료하는 지점이라 wiki 게이트는 일부러 거기 살지
    # 않음. 그래프 drift 는 그 자체가 문서 커밋이므로 여전히 차단돼야 함.
    _wiki_host(tmp_path)
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )  # graph.yaml 을 만든 적 없음 → drift
    assert fgc.wiki_gate(tmp_path, ["doc-sync", "wiki"]) is True


def test_wiki_gate_passes_a_built_graph(tmp_path: Path):
    _wiki_host(tmp_path)
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    assert cmd_build(tmp_path) == 0
    assert fgc.wiki_gate(tmp_path, ["precommit", "wiki"]) is False


def test_wiki_gate_is_not_a_module_command(tmp_path: Path):
    # 모듈 사전검사 채널을 타면 안 됨: 저쪽에선 비영 종료가 곧 "검사 실패"라 내부 오류
    # 하나가 모든 커밋을 막음(Invariant #1). 모듈 결과는 wiki 게이트가 없던 때와
    # 비트 단위로 같아야 함.
    _wiki_host(tmp_path)
    assert module_commands(tmp_path, "docs", ["doc-sync", "wiki"]) == ([], [])
    assert module_commands(tmp_path, "dev", ["precommit", "wiki"]) == ([], [])


def test_no_wiki_gate_when_wiki_absent(tmp_path: Path):
    cfgdir = tmp_path / ".claude" / "vway-kit" / "config"
    cfgdir.mkdir(parents=True)
    (cfgdir / "vdev-config.yaml").write_text("branches:\n  integration: dev\n", encoding="utf-8")
    assert fgc.wiki_gate(tmp_path, ["precommit", "wiki"]) is False


def test_no_wiki_gate_when_gate_not_listed(tmp_path: Path):
    # 티어의 gates 가 이름을 대지 않은 wiki 는 drift 가 있어도 막으면 안 됨 —
    # vdev-tiers.yaml 이 on/off 스위치.
    _wiki_host(tmp_path)
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    assert fgc.wiki_gate(tmp_path, ["precommit"]) is False
    assert fgc.wiki_gate(tmp_path, None) is False


def test_wiki_gate_internal_failure_is_fail_open(tmp_path: Path, monkeypatch):
    # 이 게이트가 모듈 채널을 떠난 이유 그 자체: 내부 실패는 반드시 통과여야 함. 여기서는
    # cmd_verify 자신이 예외를 던지는데, 모듈 채널이었다면 방출된 명령의 비영 종료로 드러나
    # 저장소의 모든 커밋을 거부함.
    _wiki_host(tmp_path)
    monkeypatch.setattr(fgc, "cmd_verify", lambda root: 1 / 0)
    assert fgc.wiki_gate(tmp_path, ["wiki"]) is False


def test_gate_script_runs_without_the_wiki_sibling(tmp_path: Path):
    # vdev_gate_check 는 모듈 스코프에서 wiki_graph 를 import 하는데, 플러그인 스크립트는
    # 호스트로 *한 파일씩* 복사되므로 그 형제 없이 이 파일만 가진 호스트가 정당하게 성립함.
    # 가드가 없으면 ImportError 가 게이트 스크립트 전체를 실행 불가로 만들고, 러너는 그것을
    # 내부 오류로 읽어 FAIL-OPEN 해 wiki 뿐 아니라 tier·마커 게이트까지 조용히 꺼짐.
    # 정말 필요한 두 파일만 복사.
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    repo = Path(__file__).resolve().parent.parent.parent
    for name in ("vdev_gate_check.py", "_vway_paths.py"):
        shutil.copy(repo / "scripts" / name, scripts_dir / name)
    assert not (scripts_dir / "wiki_graph.py").exists()
    host = tmp_path / "host"
    host.mkdir()
    r = run_bounded(
        [sys.executable, str(scripts_dir / "vdev_gate_check.py"), "--wiki-check"],
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(host), "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_wiki_gate_lookup_failure_is_fail_open(tmp_path: Path, monkeypatch):
    def _boom(_root):
        raise RuntimeError("broken vdev-config.wiki")

    _wiki_host(tmp_path)
    monkeypatch.setattr(wiki_graph, "load_wiki_config", _boom)
    assert fgc.wiki_gate(tmp_path, ["wiki"]) is False


@requires_bash_git
def test_deny_json_survives_a_quote_bearing_command(tmp_path: Path):
    # deny() 는 실패한 명령을 permissionDecisionReason JSON 문자열로 보간함. wiki 게이트의
    # 사유는 큰따옴표를 **항상** 담고 Windows 에선 백슬래시까지 담는 첫 플러그인 생성 문자열
    # — 날것이면 `"` 가 문자열을 조기에 닫고 `\r` 은 잘못된 JSON escape 라, 하필 게이트가
    # 차단하는 그 순간 페이로드가 깨짐. ESC 는 JSON 이 raw 로 금지하면서 짧은 escape 도 없는
    # 나머지 C0 영역의 대표: wiki 게이트는 git 제목 줄을 사유에 인용하고, 제목에는 붙여넣어진
    # 무엇이든 들어감.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    command = 'echo "C:\\repo" \x1b >/dev/null; exit 1'
    (wt / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        yaml.safe_dump(
            {"modules": [{"name": "api", "path": "services/api/", "checks": {"lint": command}}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    r = _run_runner(main, f"git -C {wt} commit -m x", dryrun=False)
    assert r.returncode == 2
    payload = json.loads(r.stdout.strip())  # 이스케이프 안 된 따옴표/백슬래시/제어문자면 raise
    reason = payload["hookSpecificOutput"]["permissionDecisionReason"]
    assert 'echo "C:\\repo"' in reason  # …그리고 명령은 이스케이프를 거쳐도 온전함
    assert "\x1b" not in reason  # 제어문자는 밀반입되지 않고 제거됨


@requires_bash_git
def test_runner_wiki_step_denies_and_carries_the_report(tmp_path: Path):
    # 실제 훅을 통한 e2e: drift 난 그래프는 exit 2 여야 하고, 차단 사유는 모듈 채널의
    # "모듈 사전검사 실패: <명령>" 이 아니라 cmd_verify 자신의 리포트여야 함.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    (wt / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "wiki:\n  enable: true\n  root: docs/\n", encoding="utf-8"
    )
    (wt / "docs").mkdir()
    (wt / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    _rg(["add", "docs/index.md"], wt)  # 문서는 스테이징됨으로써 wiki 에 들어옴
    r = _run_runner(main, f"git -C {wt} commit -m x", dryrun=False)  # 빌드한 적 없음 → drift
    assert r.returncode == 2
    payload = json.loads(r.stdout.strip())
    reason = payload["hookSpecificOutput"]["permissionDecisionReason"]
    assert "wiki graph 검증 실패" in reason
    assert "모듈 사전검사" not in reason


@requires_bash_git
def test_runner_wiki_step_shows_warnings_on_a_passing_commit(tmp_path: Path):
    # 경고(orphan / max_lines / defect→rule)는 이 게이트의 품질 신호인데, exit 0 이면 훅의
    # stdout·stderr 가 **둘 다** 디버그 로그로만 감 — systemMessage 가 "사용자에게 보인다"고
    # 문서화된 유일한 필드이므로, 통과하는 커밋은 그것을 내야 함.
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    (wt / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "wiki:\n  enable: true\n  root: docs/\n", encoding="utf-8"
    )
    (wt / "docs").mkdir()
    (wt / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    (wt / "docs" / "lonely.md").write_text(
        "---\nwiki_id: lonely\ntitle: Lonely\n---\nbody\n", encoding="utf-8"
    )  # index 에서 도달 불가 → orphan 경고, 그러나 차단은 아님
    _rg(["add", "docs"], wt)
    assert cmd_build(wt) == 0
    _rg(["add", "docs/graph/graph.yaml"], wt)
    r = _run_runner(main, f"git -C {wt} commit -m x", dryrun=False)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert "orphan" in payload["systemMessage"]


@requires_git
def test_main_runs_wiki_gate_in_process_and_blocks(tmp_path: Path):
    # spawn 2→1: vdev 게이트 자체 호출이 wiki 판정까지 실어야 함 — exit 2 에 사유는 stdout
    # (러너의 1단계 채널). 별도 --wiki-check 호출이 필요 없음.
    _init_repo(tmp_path)
    _wiki_host(tmp_path)
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    _rg(["add", "docs/index.md"], tmp_path)  # 스테이징돼야 노드로 편입됨
    _classify_docs(tmp_path)  # 그래프 미빌드 → drift
    r = _main_gate(tmp_path)
    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "wiki graph 검증 실패" in r.stdout


@requires_git
def test_main_emits_system_message_on_passing_wiki_warnings(tmp_path: Path):
    _init_repo(tmp_path)
    _wiki_host(tmp_path)
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "lonely.md").write_text(
        "---\nwiki_id: lonely\ntitle: Lonely\n---\nbody\n", encoding="utf-8"
    )  # orphan → 경고만
    _rg(["add", "docs"], tmp_path)
    assert cmd_build(tmp_path) == 0
    _classify_docs(tmp_path)
    r = _main_gate(tmp_path)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert "orphan" in payload["systemMessage"]


@requires_git
def test_main_skips_wiki_under_dryrun(tmp_path: Path):
    _init_repo(tmp_path)
    _wiki_host(tmp_path)
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    _rg(["add", "docs/index.md"], tmp_path)
    _classify_docs(tmp_path)  # drift — 그래도 DRYRUN 은 wiki 게이트를 돌리지 않음
    r = _main_gate(tmp_path, {"VWAY_PRECOMMIT_DRYRUN": "1"})
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stdout == ""


@requires_git
def test_wiki_check_alias_keeps_the_old_contract(tmp_path: Path):
    # 반쯤 복사된 호스트가 --wiki-check 를 부르는 옛 러너를 들고 있을 수 있음 — alias 는 옛
    # 계약(exit 2 + stdout 사유)을 그대로 답해야 함.
    _init_repo(tmp_path)
    _wiki_host(tmp_path)
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    _rg(["add", "docs/index.md"], tmp_path)
    _classify_docs(tmp_path)
    repo = Path(__file__).resolve().parent.parent.parent
    r = run_bounded(
        [sys.executable, str(repo / "scripts" / "vdev_gate_check.py"), "--wiki-check"],
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(repo),
            "PYTHONIOENCODING": "utf-8",
        },
    )
    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "wiki graph 검증 실패" in r.stdout


@requires_bash_git
def test_runner_wiki_step_fails_open_when_the_gate_script_is_missing(tmp_path: Path):
    # `python3 <없는 파일>` 은 exit 2 에 stderr 로 불평함 — 이 단계가 stderr 를 읽었다면
    # 차단과 구별되지 않음. 스크립트 복사가 반쯤 실패한 호스트는 그러면 인터프리터 오류를
    # 사유로 모든 커밋을 거부당하는데, 그것이야말로 Invariant #1 이 이 게이트에 금지하는
    # 유일한 것. 인터프리터가 절대 쓰지 않는 stdout 만 읽는 것이 해법.
    main = tmp_path / "main"
    _init_repo(main)
    _classify_worktree_module(main)  # 더러운 트리 → 러너가 wiki 단계까지 도달
    empty_plugin = tmp_path / "no-scripts"
    (empty_plugin / "scripts").mkdir(parents=True)  # 존재하지만 게이트 스크립트는 없음
    r = _run_runner(main, "git commit -m x", dryrun=False, plugin_root=empty_plugin)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


@requires_bash_git
def test_runner_wiki_step_reads_the_committing_worktree(tmp_path: Path):
    # CLAUDE_PROJECT_DIR 은 세션 시작 위치 = main 에 고정됨. worktree 커밋은 **worktree 의**
    # 그래프로 검증돼야 하므로(Invariant 7), main 에 drift 난 wiki 를 두고 worktree 에는 깨끗한
    # 것을 줌: 이 단계가 main 을 읽었다면 여기서 새로 차단이 남.
    main = tmp_path / "main"
    _init_repo(main)
    _wiki_host(main)  # wiki 켜짐, graph.yaml 은 만든 적 없음 → 읽히면 확실히 drift
    (main / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    wt = tmp_path / "wt"
    _rg(["worktree", "add", "-b", "feature/x", str(wt)], main)
    _classify_worktree_module(wt)
    (wt / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        "wiki:\n  enable: true\n  root: docs/\n", encoding="utf-8"
    )
    (wt / "docs").mkdir()
    (wt / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    _rg(["add", "docs"], wt)
    assert cmd_build(wt) == 0
    _rg(["add", "docs/graph/graph.yaml"], wt)
    r = _run_runner(main, f"git -C {wt} commit -m x", dryrun=False)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
