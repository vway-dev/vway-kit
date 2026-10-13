""".gitignore 라인 관리와 이미 추적 중인 증거의 추적 해제.

라인만 넣으면 **이미 추적 중인** `.vdev` 증거는 빠지지 않음 — 그 footgun 복구
(`git rm --cached`)와, 팀 공유로 바뀐 파일의 stale ignore 제거가 여기 모임.
"""

import subprocess
from pathlib import Path

from scripts.vdev_init_setup import (
    GITIGNORE_LINES,
    GITIGNORE_UNIGNORE,
    append_gitignore,
    unignore_shared,
    untrack_vdev_evidence,
)
from tests.vdev_init._helpers import (
    _git,
    _init_repo,
)


def test_append_gitignore_preserves_existing(tmp_path: Path):
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n", encoding="utf-8")
    append_gitignore(tmp_path)
    content = gi.read_text(encoding="utf-8")
    assert "node_modules/" in content
    assert ".claude/vway-kit/.vdev/" in content


def test_unignore_shared_removes_stale_line(tmp_path: Path):
    # 예전 설치: vdev-config.yaml 이 .gitignore 에 있음 → 능동 제거(팀 공유 전환).
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\nvdev-config.yaml\n.claude/vway-kit/.vdev/\n", encoding="utf-8")
    out = unignore_shared(tmp_path)
    assert any("공유 전환" in line for line in out)
    content = gi.read_text(encoding="utf-8")
    assert "vdev-config.yaml" not in content
    assert "node_modules/" in content  # 다른 라인 보존
    assert ".claude/vway-kit/.vdev/" in content


def test_unignore_shared_idempotent_when_absent(tmp_path: Path):
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n", encoding="utf-8")
    assert unignore_shared(tmp_path) == []  # 제거할 게 없으면 빈 결과
    assert gi.read_text(encoding="utf-8") == "node_modules/\n"  # 무변
    # GITIGNORE_UNIGNORE 가 GITIGNORE_LINES 와 겹치지 않아야(추가하면서 제거하는 모순 방지).
    assert not (set(GITIGNORE_UNIGNORE) & set(GITIGNORE_LINES))


def test_untrack_vdev_evidence_removes_tracked(tmp_path: Path):
    # 예전 설치(또는 init 전 vdev): .vdev 증거가 이미 git 에 추적 중 → 인덱스에서 제거,
    # 작업 트리 파일은 보존(.gitignore 라인만으론 이미 추적된 파일이 안 빠지는 footgun 복구).
    _init_repo(tmp_path)
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:master", encoding="utf-8")
    (vdev / "doc-sync.done").touch()
    _git(tmp_path, "add", "-A")  # .gitignore 없으니 증거가 추적됨
    assert ".claude/vway-kit/.vdev/tier" in _git(tmp_path, "ls-files").stdout

    out = untrack_vdev_evidence(tmp_path)
    assert any("추적 해제" in line for line in out)
    assert ".claude/vway-kit/.vdev/" not in _git(tmp_path, "ls-files").stdout  # 인덱스에서 빠짐
    assert (vdev / "tier").is_file()  # 작업 트리 파일 보존


def test_untrack_vdev_evidence_idempotent_when_untracked(tmp_path: Path):
    # 추적된 적 없으면(정상 흐름: .gitignore 가 선제 차단) 아무것도 안 함.
    _init_repo(tmp_path)
    assert untrack_vdev_evidence(tmp_path) == []


def test_untrack_vdev_evidence_failopen_without_git_repo(tmp_path: Path):
    # git 저장소가 아니어도(또는 git 부재) 게이트 셋업을 막지 않음 — FAIL-OPEN.
    assert untrack_vdev_evidence(tmp_path) == []


def test_untrack_vdev_evidence_reports_rm_failure(tmp_path: Path, monkeypatch):
    # ls-files 는 성공(추적분 있음)인데 rm 만 실패하면, 거짓 성공이 아니라 [!] 를 보고.
    import scripts.vdev_init_setup as mod

    _init_repo(tmp_path)
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("dev:master", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    real_run = subprocess.run

    def fake_run(args, **kwargs):
        if "rm" in args:  # rm 단계만 실패로 위조
            return subprocess.CompletedProcess(args, 1, "", "permission denied")
        return real_run(args, **kwargs)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    out = untrack_vdev_evidence(tmp_path)
    assert any("실패" in line for line in out)
    assert not any("[-]" in line for line in out)  # 거짓 성공 메시지 없음


def test_append_gitignore_creates_and_idempotent(tmp_path: Path):
    first = append_gitignore(tmp_path)
    assert any("+=" in line for line in first)
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for line in GITIGNORE_LINES:
        assert line in content
    second = append_gitignore(tmp_path)
    assert any("이미 최신" in line for line in second)
    # vdev-config.yaml 은 팀 공유라 무시 목록에서 제외 — 추가되지 않음.
    assert "vdev-config.yaml" not in content
    assert content.count(".claude/vway-kit/.vdev/") == 1


def test_prune_stale_gitignore_removes_flow_line(tmp_path: Path):
    # #6: 옛 .claude/vway-kit/.flow/ gitignore 죽은 라인 제거(다른 라인 보존)
    from scripts.vdev_init_setup import prune_stale_gitignore

    gi = tmp_path / ".gitignore"
    gi.write_text(
        "node_modules/\n.claude/vway-kit/.flow/\n.claude/vway-kit/.vdev/\n", encoding="utf-8"
    )
    prune_stale_gitignore(tmp_path)
    content = gi.read_text(encoding="utf-8")
    assert ".claude/vway-kit/.flow/" not in content
    assert "node_modules/" in content
    assert ".claude/vway-kit/.vdev/" in content
