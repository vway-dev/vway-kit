"""doc-style 런타임 게이트 — 경고만 하는 프로세스 내부 단계.

wiki 와 같은 채널을 타지만 **차단 권한이 없다는** 점이 다름. 판정은 트리 전체를 보는
CI(`doc-style.yml`) 몫이고, 여기서 막으면 규칙을 조인 순간 아무도 예측 못 한 커밋들이
거부됨. 그래서 이 파일이 재는 것은 둘 — 위반을 **보고**하는가, 그리고 어떤
경우에도 **exit 2 를 내지 않는가**.

세 번째로 재는 것은 채널 자체: 통과하는 커밋의 stdout 은 러너가 그대로 내보내므로
JSON 객체가 **하나**여야 함. wiki 경고와 문체 경고가 함께 날 때 둘을 따로 print 하면
러너 쪽에서 파싱이 깨짐.
"""

import json
import os
import shutil
import sys
from pathlib import Path

from scripts._vway_paths import RUNTIME_GATES
from scripts.vdev_gate_check import doc_style_gate, missing_gates
from scripts.wiki_graph import cmd_build
from tests._proc import run_bounded
from tests.gate_check._helpers import (
    _classify_docs,
    _init_repo,
    _main_gate,
    _rg,
    _wiki_host,
    requires_git,
)

DIRTY = "게이트가 커밋을 막는다.\n"  # ENDING 위반 한 줄
CLEAN = "게이트가 커밋을 막음.\n"


def _doc_style_host(root: Path, extra: str = "") -> None:
    cfgdir = root / ".claude" / "vway-kit" / "config"
    cfgdir.mkdir(parents=True, exist_ok=True)
    (cfgdir / "vdev-config.yaml").write_text(
        'doc_style:\n  enable: true\n  paths: ["**/*.md"]\n' + extra, encoding="utf-8"
    )


def test_doc_style_is_a_runtime_gate_needing_no_marker(tmp_path: Path):
    assert "doc-style" in RUNTIME_GATES
    vdev = tmp_path / ".vdev"
    vdev.mkdir()
    assert "doc-style" not in missing_gates(vdev, ["doc-style", "doc-sync"])


@requires_git
def test_gate_reports_a_violation_in_a_changed_file(tmp_path: Path):
    _init_repo(tmp_path)
    _doc_style_host(tmp_path)
    (tmp_path / "a.md").write_text(DIRTY, encoding="utf-8")
    _rg(["add", "a.md"], tmp_path)
    note = doc_style_gate(tmp_path, ["doc-style"])
    assert note is not None
    assert "a.md:1" in note and "ENDING" in note


@requires_git
def test_gate_says_nothing_about_a_file_this_commit_does_not_touch(tmp_path: Path):
    # 트리 전체를 보는 것은 CI 몫. 여기서 그러면 남의 위반이 내 커밋에 붙음.
    _init_repo(tmp_path)
    _doc_style_host(tmp_path)
    (tmp_path / "old.md").write_text(DIRTY, encoding="utf-8")
    _rg(["add", "old.md"], tmp_path)
    _rg(["commit", "-m", "seed", "--no-verify"], tmp_path)
    (tmp_path / "new.md").write_text(CLEAN, encoding="utf-8")
    _rg(["add", "new.md"], tmp_path)
    assert doc_style_gate(tmp_path, ["doc-style"]) is None


@requires_git
def test_exclude_holds_for_the_hook_arm_too(tmp_path: Path):
    # 범위 리더가 하나라는 계약. exclude 가 CI 에만 걸리면 훅이 CI 가 보지도 않을 파일로 경고함.
    _init_repo(tmp_path)
    _doc_style_host(tmp_path, extra='  exclude: ["CHANGELOG.md"]\n')
    (tmp_path / "CHANGELOG.md").write_text(DIRTY, encoding="utf-8")
    _rg(["add", "CHANGELOG.md"], tmp_path)
    assert doc_style_gate(tmp_path, ["doc-style"]) is None


@requires_git
def test_gate_is_silent_without_the_config_block(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "a.md").write_text(DIRTY, encoding="utf-8")
    _rg(["add", "a.md"], tmp_path)
    assert doc_style_gate(tmp_path, ["doc-style"]) is None


@requires_git
def test_gate_is_silent_when_the_tier_does_not_list_it(tmp_path: Path):
    _init_repo(tmp_path)
    _doc_style_host(tmp_path)
    (tmp_path / "a.md").write_text(DIRTY, encoding="utf-8")
    _rg(["add", "a.md"], tmp_path)
    assert doc_style_gate(tmp_path, ["doc-sync"]) is None
    assert doc_style_gate(tmp_path, None) is None


@requires_git
def test_a_violation_never_blocks_the_commit(tmp_path: Path):
    # 이 게이트의 정의 — 보고는 하되 exit 2 는 wiki 만 낼 수 있음.
    _init_repo(tmp_path)
    _doc_style_host(tmp_path)
    (tmp_path / "a.md").write_text(DIRTY, encoding="utf-8")
    _rg(["add", "a.md"], tmp_path)
    _classify_docs(tmp_path)
    r = _main_gate(tmp_path)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert "a.md:1" in payload["systemMessage"]


@requires_git
def test_both_runtime_notices_ride_one_json_object(tmp_path: Path):
    # 러너는 통과한 커밋의 stdout 을 그대로 내보냄. 객체가 둘이면 그 stdout 이 파싱되지 않음.
    _init_repo(tmp_path)
    _wiki_host(tmp_path)
    _doc_style_host(tmp_path, extra="wiki:\n  enable: true\n  root: docs/\n")
    (tmp_path / "docs" / "index.md").write_text(
        "---\nwiki_id: index\ntitle: Index\n---\nbody\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "lonely.md").write_text(
        "---\nwiki_id: lonely\ntitle: Lonely\n---\nbody\n", encoding="utf-8"
    )  # orphan → wiki 경고
    (tmp_path / "a.md").write_text(DIRTY, encoding="utf-8")  # → 문체 경고
    _rg(["add", "docs", "a.md"], tmp_path)
    assert cmd_build(tmp_path) == 0
    _classify_docs(tmp_path)
    r = _main_gate(tmp_path)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())  # 객체가 둘이면 여기서 깨짐
    assert "orphan" in payload["systemMessage"]
    assert "a.md:1" in payload["systemMessage"]


@requires_git
def test_a_sibling_that_raises_at_import_does_not_kill_the_gate(tmp_path: Path):
    """import 가드가 `except ImportError` 가 아니라 `except Exception` 인 이유.

    형제가 import 중에 무엇이든 던지면(호스트 python 이 못 읽는 문법, 잘못된 모듈 수준
    표현식) 좁은 가드는 그걸 안 잡고 vdev_gate_check.py 를 함께 죽임. 아예 안 도는
    게이트는 조용히 꺼진 게이트이고, 거기엔 **미분류 커밋 fail-CLOSED 차단**도 포함됨 —
    그래서 이 테스트가 재는 것은 doc-style 이 아니라 그 차단이 살아 있는가.
    """
    repo = Path(__file__).resolve().parents[2]
    host = tmp_path / ".claude" / "vway-kit"
    (host / "scripts").mkdir(parents=True)
    (host / "config").mkdir(parents=True)
    for name in ("_vway_paths.py", "vdev_gate_check.py", "wiki_graph.py"):
        shutil.copyfile(repo / "scripts" / name, host / "scripts" / name)
    shutil.copyfile(repo / "vdev-tiers.yaml", host / "config" / "vdev-tiers.yaml")
    (host / "config" / "vdev-config.yaml").write_text("branches:\n  integration: dev\n", "utf-8")
    (host / "scripts" / "doc_style_check.py").write_text(
        'raise RuntimeError("import 중 폭발")\n', encoding="utf-8"
    )
    host_scripts = host / "scripts"
    _init_repo(tmp_path)
    (tmp_path / "a.md").write_text(CLEAN, encoding="utf-8")
    _rg(["add", "a.md"], tmp_path)  # tier 마커 없음 → 미분류 커밋
    r = run_bounded(
        [sys.executable, str(host_scripts / "vdev_gate_check.py")],
        text=True,
        encoding="utf-8",
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path), "PYTHONIOENCODING": "utf-8"},
    )
    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "분류되지 않은" in r.stdout


@requires_git
def test_the_compat_alias_still_emits_its_warning_json(tmp_path: Path):
    """`--wiki-check` 는 옛 러너를 든 반쪽 설치를 위해 남아 있음.

    `_wiki_stage` 는 print 대신 return 하므로, 경고를 JSON 으로 감싸는 책임은 호출부에
    있음. 여기서 그걸 빠뜨리면 그 호스트에서는 경고가 영영 안 보임.
    """
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
    repo = Path(__file__).resolve().parents[2]
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
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "orphan" in json.loads(r.stdout.strip())["systemMessage"]


@requires_git
def test_dry_run_writes_no_notice(tmp_path: Path):
    _init_repo(tmp_path)
    _doc_style_host(tmp_path)
    (tmp_path / "a.md").write_text(DIRTY, encoding="utf-8")
    _rg(["add", "a.md"], tmp_path)
    _classify_docs(tmp_path)
    r = _main_gate(tmp_path, {"VWAY_PRECOMMIT_DRYRUN": "1"})
    assert r.returncode == 0
    assert r.stdout.strip() == ""
