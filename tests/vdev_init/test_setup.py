"""vdev-init 셋업의 뼈대 — 산출물 복사 · 마켓플레이스 등록 · pre-commit · 라운드트립.

게이트 훅(`test_gate_hook.py`)·워크플로 렌더(`test_workflow_*.py`)·설정 슬롯
(`test_config.py`) 처럼 자기 규율을 가진 단계는 각자의 파일에 있음. 여기 남은 것은
그 단계들이 딛고 서는 복사·등록과, setup↔uninstall 이 서로의 역연산인지.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml as _yaml

from scripts.vdev_init_setup import (
    CLAUDE_MD_BEGIN,
    GITIGNORE_KEEP,
    GITIGNORE_LINES,
    RULES_DEST,
    append_gitignore,
    check_precommit,
    copy_artifacts,
    main,
    register_gate,
    register_marketplace,
    remove_claude_md_block,
    remove_gitignore_lines,
    remove_rules,
    remove_vway_dir,
    run_setup,
    run_uninstall,
    unregister_gate,
    unregister_marketplace,
)
from tests.vdev_init._helpers import (
    PLUGIN,
    _gate_commands,
    _is_gate,
)


def test_copy_artifacts_includes_shared_helper(tmp_path: Path):
    # _vway_paths.py 가 COPY_FILES 에서 빠지면 호스트로 복사된 게이트 스크립트가
    # 형제 import 실패(ImportError)로 조용히 무력화됨. 누락 회귀 방지.
    copy_artifacts(PLUGIN, tmp_path)
    scripts_dir = tmp_path / ".claude" / "vway-kit" / "scripts"
    assert (scripts_dir / "_vway_paths.py").is_file()


def test_doc_style_check_is_copied_to_the_host(tmp_path: Path):
    # 같은 이유로 doc_style_check.py 도 형제여야 함 — 빠지면 vdev_gate_check 의 import 가
    # None 으로 떨어지고 doc-style 게이트가 크래시 없이 조용히 아무것도 보고하지 않음.
    copy_artifacts(PLUGIN, tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / "scripts" / "doc_style_check.py").is_file()


def test_wiki_graph_is_copied_to_the_host(tmp_path: Path):
    # wiki 런타임 게이트는 vdev_gate_check 가 형제 wiki_graph.py 를 import 할 수 있을 때만
    # 판정함 — COPY_FILES 에서 빠지면 import 가 None 으로 떨어져 게이트가 조용히 통과만
    # 함(FAIL-OPEN 설계상 크래시가 아니라 무동작이라 더 알아채기 어려움). 누락 회귀 방지.
    copy_artifacts(PLUGIN, tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / "scripts" / "wiki_graph.py").is_file()


def test_md_anchors_is_copied_to_the_host(tmp_path: Path):
    # srs_check.py 가 형제 _md_anchors.py 를 import 함 — COPY_FILES 에서 빠지면
    # srs_check.py 자체가 호스트에서 ImportError 로 죽음(형제 import 둘 다 실패).
    copy_artifacts(PLUGIN, tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / "scripts" / "_md_anchors.py").is_file()


def test_srs_check_is_copied_to_the_host(tmp_path: Path):
    # 빠지면 `/vdev` 증분 단계는 파일 없음 경고만 내고, 소비자 CI 는 srs-verify.yml 템플릿의
    # 가드가 스크립트 부재에 exit 0 — 크래시 없이 양쪽 다 조용히 무검증.
    # alm_docs.py 는 조용하지 않음: 모듈 최상위에서 이 파일을 import 하므로 `/alm-docs` 의
    # 네 하위 명령이 전부 ModuleNotFoundError 로 죽음.
    copy_artifacts(PLUGIN, tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / "scripts" / "srs_check.py").is_file()


def test_alm_docs_is_copied_to_the_host(tmp_path: Path):
    # /alm-docs 의 네 하위 명령이 전부 이 파일 하나를 부름 — COPY_FILES 에서 빠지면
    # 스킬의 첫 단계가 "파일 없음" 으로 떨어지고, 왕복이 통째로 조용히 안 돎.
    copy_artifacts(PLUGIN, tmp_path)
    assert (tmp_path / ".claude" / "vway-kit" / "scripts" / "alm_docs.py").is_file()


def test_copied_gate_imports_shared_helper(tmp_path: Path):
    # 호스트 단일파일 복사 환경 end-to-end: 복사된 scripts/ 에서 vdev_gate_check.py 를
    # 직접 실행하면 형제 _vway_paths.py 를 import 해 정상 동작해야 함. import 양립
    # 블록이 깨지면 ImportError 크래시(returncode 1 + stderr Traceback)로 즉시 잡힘.
    # 게이트 판정 자체는 이 테스트의 관심사가 아니므로, 미분류 fail-closed 차단(정책
    # 존재 + tier 마커 부재 → exit 2)에 걸리지 않게 docs 티어 + 증거를 두어 정상 통과
    # (exit 0) 경로로 import 양립만 확인.
    copy_artifacts(PLUGIN, tmp_path)
    (tmp_path / ".claude").mkdir(exist_ok=True)
    vdev = tmp_path / ".claude" / "vway-kit" / ".vdev"
    vdev.mkdir(parents=True)
    (vdev / "tier").write_text("docs:", encoding="utf-8")
    (vdev / "doc-sync.done").touch()
    scripts_dir = tmp_path / ".claude" / "vway-kit" / "scripts"
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, str(scripts_dir / "vdev_gate_check.py")],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"import 양립 실패 의심: {result.stderr}"


def test_copied_gate_reads_tiers_from_config(tmp_path: Path):
    # 호스트 복사 환경 end-to-end: 복사된 scripts/vdev_gate_check.py 의 __file__ 은
    # tmp/.claude/vway-kit/scripts/ → 형제 config/ 의 vdev-tiers.yaml 을 해석해야 함.
    # config/→scripts/ 회귀(형제 탐색이 옛 scripts/ 를 보면) 시 이 경로가 깨짐.
    copy_artifacts(PLUGIN, tmp_path)
    scripts_dir = tmp_path / ".claude" / "vway-kit" / "scripts"
    config_tiers = tmp_path / ".claude" / "vway-kit" / "config" / "vdev-tiers.yaml"
    assert config_tiers.is_file()  # copy 가 config/ 에 넣음
    code = (
        "from pathlib import Path;"
        "from vdev_gate_check import tiers_path;"
        "import sys; sys.stdout.write(str(tiers_path(Path(sys.argv[1]))))"
    )
    env = {**os.environ, "PYTHONPATH": str(scripts_dir), "PYTHONIOENCODING": "utf-8"}
    env.pop("CLAUDE_PLUGIN_ROOT", None)  # ① 분기 비활성화 → ② config/ 탐색 검증
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(config_tiers)


def test_uninstall_round_trip(tmp_path: Path):
    # setup 등록물을 uninstall 이 모두 되돌림
    register_gate(tmp_path)
    register_marketplace(tmp_path)
    append_gitignore(tmp_path)
    vd = tmp_path / ".claude" / "vway-kit"
    (vd / "scripts").mkdir(parents=True)
    (vd / "scripts" / "precommit-runner.sh").write_text("x", encoding="utf-8")

    assert "해제" in unregister_gate(tmp_path)
    assert "해제" in unregister_marketplace(tmp_path)
    assert "제거" in remove_gitignore_lines(tmp_path)
    assert "삭제" in remove_vway_dir(tmp_path)

    assert not (tmp_path / ".claude" / "settings.json").exists()
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {line for line in GITIGNORE_LINES if line in gi} == GITIGNORE_KEEP, gi
    assert not vd.exists()


def test_uninstall_idempotent(tmp_path: Path):
    # 아무것도 없을 때 uninstall 은 안전하게 skip
    assert "skip" in unregister_gate(tmp_path)
    assert "skip" in unregister_marketplace(tmp_path)
    assert "skip" in remove_gitignore_lines(tmp_path)
    assert "skip" in remove_vway_dir(tmp_path)


def test_uninstall_preserves_other_settings(tmp_path: Path):
    # 게이트 외 다른 PreToolUse 훅은 보존
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo other"}]}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [other]}}), encoding="utf-8")
    register_gate(tmp_path)
    unregister_gate(tmp_path)
    cmds = _gate_commands(settings)
    assert "echo other" in cmds
    assert not any(_is_gate(c) for c in cmds)


def test_remove_claude_md_block(tmp_path: Path):
    cm = tmp_path / "CLAUDE.md"
    cm.write_text(
        f"# Host\n\nkeep before\n\n{CLAUDE_MD_BEGIN} (managed) -->\nmanaged body\n"
        "<!-- vway-kit:teams END -->\n\nkeep after\n",
        encoding="utf-8",
    )
    assert "제거" in remove_claude_md_block(tmp_path)
    text = cm.read_text(encoding="utf-8")
    assert "keep before" in text and "keep after" in text
    assert "managed body" not in text and CLAUDE_MD_BEGIN not in text
    assert "skip" in remove_claude_md_block(tmp_path)  # 멱등(이미 없음)


def test_check_precommit_creates_when_absent(tmp_path: Path):
    report = check_precommit(PLUGIN, tmp_path)
    assert (tmp_path / ".pre-commit-config.yaml").is_file()
    assert any("생성" in line for line in report)


def test_check_precommit_creates_never_reports_module_hooks(tmp_path: Path):
    # 모듈 훅은 레이어2 소관 → modules 선언돼도 pre-commit 에 모듈 훅을 보고하지 않음.
    cfg_dir = tmp_path / ".claude" / "vway-kit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "vdev-config.yaml").write_text(
        "modules:\n  - name: api\n    path: services/api/\n"
        "    checks:\n      lint: 'ruff check services/api'\n",
        encoding="utf-8",
    )
    report = check_precommit(PLUGIN, tmp_path)
    assert (tmp_path / ".pre-commit-config.yaml").is_file()
    assert any("생성" in line for line in report)
    assert not any("모듈 훅" in line for line in report)


def test_check_precommit_all_present(tmp_path: Path):
    check_precommit(PLUGIN, tmp_path)  # 생성(예시 전체 복사)
    report = check_precommit(PLUGIN, tmp_path)  # 모든 항목 존재
    assert any("이미 충족" in line for line in report)


def test_check_precommit_reports_missing_without_modifying(tmp_path: Path):
    # 이미 있는 config 는 절대 수정하지 않고(주석/포맷 보존), 빠진 항목만 보고
    dest = tmp_path / ".pre-commit-config.yaml"
    original = "# 팀 주석 — 보존되어야 함\nrepos: []\n"
    dest.write_text(original, encoding="utf-8")
    report = check_precommit(PLUGIN, tmp_path)
    assert any("병합하지 않음" in line for line in report)
    assert dest.read_text(encoding="utf-8") == original  # 파일 불변


def test_check_precommit_flags_deprecated_local_hooks(tmp_path: Path):
    # 폐기된 레이어1 모듈 훅(repo: local 의 lint 등)이 남아 있으면 제거 권장 안내(자동 편집 X).
    # 사용자 커스텀 훅은 화이트리스트 밖이라 오탐하지 않음.
    dest = tmp_path / ".pre-commit-config.yaml"
    original = (
        "# 팀 주석 — 보존\n"
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: lint\n"
        "        name: lint\n"
        "        entry: ruff check\n"
        "        language: system\n"
        "      - id: my-custom-hook\n"
        "        name: custom\n"
        "        entry: echo hi\n"
        "        language: system\n"
    )
    dest.write_text(original, encoding="utf-8")
    report = check_precommit(PLUGIN, tmp_path)
    assert any("폐기된 레이어1 모듈 훅" in line and "lint" in line for line in report)
    assert not any("my-custom-hook" in line for line in report)  # 커스텀 훅 오탐 안 함
    assert dest.read_text(encoding="utf-8") == original  # 자동 편집 안 함(파일 불변)


def test_check_precommit_no_deprecated_note_when_clean(tmp_path: Path):
    # 폐기 훅이 없으면 폐기 안내를 내지 않는다(정상 config 에 잡음 금지).
    check_precommit(PLUGIN, tmp_path)  # 예시 전체 복사(폐기 id 없음)
    report = check_precommit(PLUGIN, tmp_path)
    assert not any("폐기된 레이어1 모듈 훅" in line for line in report)


def test_register_marketplace_creates(tmp_path: Path):
    msg = register_marketplace(tmp_path)
    assert "autoUpdate" in msg
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    vway = data["extraKnownMarketplaces"]["vway"]
    assert vway["autoUpdate"] is True
    assert vway["source"]["source"] == "github"
    assert vway["source"]["repo"] == "vway-dev/vway-kit"


def test_register_marketplace_idempotent(tmp_path: Path):
    register_marketplace(tmp_path)
    msg = register_marketplace(tmp_path)
    assert "이미" in msg


def test_register_marketplace_repairs_flag_preserving_source(tmp_path: Path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    payload = {"extraKnownMarketplaces": {"vway": {"source": {"source": "git", "url": "keep-me"}}}}
    settings.write_text(json.dumps(payload), encoding="utf-8")
    msg = register_marketplace(tmp_path)
    assert "보정" in msg
    vway = json.loads(settings.read_text(encoding="utf-8"))["extraKnownMarketplaces"]["vway"]
    assert vway["autoUpdate"] is True
    assert vway["source"]["url"] == "keep-me"  # 소스 보존


def test_copy_artifacts(tmp_path: Path):
    copy_artifacts(PLUGIN, tmp_path)
    vd = tmp_path / ".claude" / "vway-kit"
    assert (vd / "scripts" / "precommit-runner.sh").is_file()
    assert (vd / "scripts" / "vdev_gate_check.py").is_file()
    # 정책 파일은 config/ 로, scripts/ 에는 두지 않음.
    assert (vd / "config" / "vdev-tiers.yaml").is_file()
    assert not (vd / "scripts" / "vdev-tiers.yaml").exists()


def test_merge_strategy_policy_reaches_host(tmp_path: Path):
    # merge 게이트는 호스트 config 의 vdev-tiers.yaml 에서 정책을 읽음. 정책과 게이트
    # 스크립트가 같은 copy_artifacts 로 함께 이동하므로 마이그레이션은 불필요하지만,
    # 정책만 전파에서 빠지면 게이트가 조용히 fail-open 함(키 부재 → 검사 없음).
    copy_artifacts(PLUGIN, tmp_path)
    dest = tmp_path / ".claude" / "vway-kit" / "config" / "vdev-tiers.yaml"
    data = _yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert isinstance(data.get("merge_strategy"), list)
    assert any(r.get("require") == "--squash" for r in data["merge_strategy"])


def test_the_answerer_is_copied_before_the_runner_that_questions_it():
    # 한쪽이 다른 쪽에 묻는 곳에서는 복사 순서가 계약. precommit-runner.sh 는
    # vdev_gate_check.py --classify 의 답으로 분기하므로, 새 러너가 옛 스크립트에 묻는
    # 상태(순서를 뒤집으면 생김)는 판정을 못 읽는 러너 = 아무것도 게이팅하지 않는 러너.
    from scripts.vdev_init_setup import COPY_FILES

    files = COPY_FILES
    assert files.index("scripts/vdev_gate_check.py") < files.index("scripts/precommit-runner.sh")


def test_main_setup_then_uninstall_dispatch(tmp_path: Path, monkeypatch):
    # argparse 분기 + run_setup 순서(copy→register→migrate) end-to-end
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
    monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py"])
    main()
    vd = tmp_path / ".claude" / "vway-kit"
    settings = tmp_path / ".claude" / "settings.json"
    assert (vd / "scripts" / "precommit-runner.sh").is_file()
    assert (vd / "config" / "vdev-tiers.yaml").is_file()
    assert any(_is_gate(c) for c in _gate_commands(settings))
    # --uninstall 분기 → 역연산
    monkeypatch.setattr(sys, "argv", ["vdev_init_setup.py", "--uninstall"])
    main()
    assert not vd.exists()
    assert not settings.exists()


def test_setup_removes_the_rule_copy_an_older_setup_left(tmp_path: Path):
    """출하 문체 룰은 훅의 짧은 블록으로 세션에 닿음 — .claude/rules/ 아래 사본은 매 세션 통째로
    로드됨. 재동기화는 vway-kit 의 것만 지우고 호스트의 것은 안 건드림."""
    stale = tmp_path / RULES_DEST / "doc-style.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old copy", encoding="utf-8")
    own = tmp_path / ".claude" / "rules" / "doc-style.md"
    own.write_text("host's own", encoding="utf-8")
    for _ in range(2):  # Invariant 5: 재실행은 지울 것이 없어도 통과
        run_setup(tmp_path, PLUGIN)
    assert not (tmp_path / RULES_DEST).exists()
    assert own.read_text(encoding="utf-8") == "host's own"


def test_setup_copies_no_rule_into_a_fresh_host(tmp_path: Path):
    run_setup(tmp_path, PLUGIN)
    assert not (tmp_path / RULES_DEST).exists()


def test_uninstall_removes_only_the_rule_copy(tmp_path: Path):
    assert "skip" in remove_rules(tmp_path)
    stale = tmp_path / RULES_DEST / "doc-style.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old copy", encoding="utf-8")
    own = tmp_path / ".claude" / "rules" / "mine.md"
    own.write_text("x", encoding="utf-8")
    run_uninstall(tmp_path)
    assert not (tmp_path / RULES_DEST).exists()
    assert own.is_file()


def test_the_hook_looks_for_the_rule_where_setup_cleans_it_up():
    """한 경로에 리터럴 둘 — 어긋나면 옛 사본이 남은 호스트가 그 룰 전문과 주입 요약을 둘 다
    받고, 셋업은 훅이 보지 않는 디렉터리를 지움."""
    hook = (PLUGIN / "hooks" / "inject-risk-tiers.sh").read_text(encoding="utf-8")
    assert f"{RULES_DEST}/doc-style.md" in hook
