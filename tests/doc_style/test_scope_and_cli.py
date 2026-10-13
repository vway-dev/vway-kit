"""산문 검사기의 스코프와 CLI — 훅과 CI 가 같은 함수로 범위를 읽는가.

그게 갈리면 소비자가 쓴 `exclude` 가 한쪽에만 걸림. 설정이 없거나 깨졌을 때 두 팔이 어느
쪽으로 떨어지는지(훅은 FAIL-OPEN, CI 는 붉은 잡)도 여기서 잼.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml as _yaml

from scripts.doc_style_check import (
    DEFAULT_GLOBS,
    NEVER_LINTED,
    REVIEW_EXCLUDES,
    _match,
    config_paths,
    in_scope,
    main,
    scope_rules,
)
from tests._proc import run_bounded
from tests.doc_style._helpers import REPO


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return run_bounded(
        [sys.executable, str(REPO / "scripts" / "doc_style_check.py"), *args],
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or REPO),
    )


# ---------- 스코프: 훅과 CI 가 같은 리더를 씀 ----------


def write_config(root: Path, body: str) -> None:
    (root / ".claude" / "vway-kit" / "config").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "vway-kit" / "config" / "vdev-config.yaml").write_text(
        body, encoding="utf-8"
    )


def test_absent_config_is_no_scope_not_an_error(tmp_path):
    assert scope_rules(tmp_path) is None
    assert in_scope(tmp_path, [tmp_path / "a.md"]) == []
    assert config_paths(tmp_path) == []


def test_disabled_block_is_no_scope(tmp_path):
    write_config(tmp_path, "doc_style:\n  enable: false\n")
    assert scope_rules(tmp_path) is None


def test_enabled_block_falls_back_to_the_default_scope(tmp_path):
    write_config(tmp_path, "doc_style:\n  enable: true\n")
    assert scope_rules(tmp_path) == (DEFAULT_GLOBS, ())


def test_the_default_scope_names_docstrings_and_comments_too():
    """기본값을 **값으로** 고정 — `DEFAULT_GLOBS` 와만 비교하는 단언은 조용한 축소를 통과시킴.

    [doc-style.md](../../rules/doc-style.md) 의 적용 줄이 주석·독스트링을 산문에 넣으므로,
    `.md` 에서 멈추는 기본값은 규칙과 그 기계 절반이 서로 다른 말을 하게 함. 확장자 집합은
    `prose_of` 가 읽을 줄 아는 것과 같음 — 추출기가 아는데 기본값이 안 고르면 조용한 구멍.
    """
    assert set(DEFAULT_GLOBS) == {"**/*.md", "**/*.py", "**/*.sh", "**/*.bash"}


def test_a_config_without_paths_puts_a_docstring_in_scope(tmp_path):
    """`paths` 를 안 적은 소비자에게도 독스트링·주석이 닿음 — 기본값이 무엇을 뜻하는지의 계약."""
    write_config(tmp_path, "doc_style:\n  enable: true\n")
    names = {
        "m.py": '"""경로를 돌려준다."""\n',
        "h.sh": "# 마커를 지운다\n",
        "h.bash": "# 마커를 지운다\n",
    }
    for name, body in names.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    got = {p.name for p in in_scope(tmp_path, [tmp_path / n for n in names])}
    assert got == set(names)


def test_the_shipped_defaults_match_the_code():
    """소비자가 받는 두 사본(설정 템플릿·사용 설명서 설정 예시)이 `DEFAULT_GLOBS` 와 같음.

    셋 다 같은 사실을 말하므로 말없이 갈릴 수 있음 — 코드가 확장자를 더해도 소비자가 복사하는
    쪽은 옛 목록인 채로 남고, 그 저장소는 기본값을 안 쓰므로 새 확장자가 영영 안 걸림.
    """
    template = _yaml.safe_load((REPO / "vdev-config.example.yaml").read_text(encoding="utf-8"))
    guide = REPO / "docs" / "usage" / "configuration.md"
    usage = re.search(r"```yaml\n(.*?)```", guide.read_text(encoding="utf-8"), re.S)
    assert usage, "configuration.md 의 설정 예시 펜스를 못 찾음"
    for source, cfg in (("example", template), ("usage", _yaml.safe_load(usage.group(1)))):
        assert tuple(cfg["doc_style"]["paths"]) == DEFAULT_GLOBS, source
    # 꺼진 저장소의 리뷰 범위(`--scope`)가 같은 제외를 씀 — 갈리면 켠 저장소에선 빠지는 파일을
    # 끈 저장소의 리뷰가 고침.
    assert tuple(template["doc_style"]["exclude"]) == REVIEW_EXCLUDES
    assert tuple(_yaml.safe_load(usage.group(1))["doc_style"]["exclude"]) == REVIEW_EXCLUDES


def test_github_forms_are_never_linted_and_the_default_reaches_nested_changelogs(tmp_path):
    """PR·이슈 템플릿의 체크리스트는 양식 자체라 호스트 설정과 무관하게 빠지고, 패키지의
    CHANGELOG 는 루트 것처럼 재생성되므로 기본 `exclude` 가 깊이 무관하게 뺌."""
    write_config(
        tmp_path,
        "doc_style:\n  enable: true\n  exclude: " + repr(list(REVIEW_EXCLUDES)) + "\n",
    )
    tree = [
        "a.md",
        "CHANGELOG.md",
        "packages/core/CHANGELOG.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/pull_request_template.md",
        "docs/Pull_Request_Template.md",
        ".github/PULL_REQUEST_TEMPLATE/feature.md",
        ".github/ISSUE_TEMPLATE/bug.md",
        ".github/issue_template.md",
        "ISSUE_TEMPLATE/feature.md",
        "docs/pull_request_template/fix.md",
        ".github/CONTRIBUTING.md",
    ]
    for rel in tree:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n", encoding="utf-8")
    got = sorted(p.relative_to(tmp_path).as_posix() for p in config_paths(tmp_path))
    assert got == [".github/CONTRIBUTING.md", "a.md"]


def test_exclude_wins_over_paths(tmp_path):
    write_config(
        tmp_path,
        'doc_style:\n  enable: true\n  paths: ["**/*.md"]\n  exclude: ["CHANGELOG.md"]\n',
    )
    for name in ("a.md", "CHANGELOG.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    got = {p.name for p in in_scope(tmp_path, [tmp_path / "a.md", tmp_path / "CHANGELOG.md"])}
    assert got == {"a.md"}


@pytest.mark.parametrize(
    "body",
    [
        'doc_style:\n  enable: true\n  paths: "**/*.md"\n',  # 문자열 하나 — 글자 단위로 쪼개짐
        "doc_style:\n  enable: true\n  exclude: 5\n",
        "doc_style:\n  enable: true\n  paths: [1, 2]\n",
    ],
)
def test_a_glob_list_of_the_wrong_shape_is_an_error_not_a_silent_narrowing(tmp_path, body):
    """`paths: "**/*.md"` 는 특히 위험 — 조용히 최상위 파일만 남기고 CI 는 초록."""
    write_config(tmp_path, body)
    assert in_scope(tmp_path, [tmp_path / "a.md"]) == []  # 훅 — FAIL-OPEN
    with pytest.raises(ValueError):
        in_scope(tmp_path, [tmp_path / "a.md"], fail_open=False)


def test_an_empty_list_falls_back_to_the_default_globs(tmp_path):
    write_config(tmp_path, "doc_style:\n  enable: true\n  paths: []\n")
    assert scope_rules(tmp_path) == (DEFAULT_GLOBS, ())


def test_malformed_config_fails_open_for_the_hook_and_raises_for_ci(tmp_path):
    write_config(tmp_path, "doc_style: [unclosed\n")
    assert in_scope(tmp_path, [tmp_path / "a.md"]) == []  # 훅 — Invariant #1
    with pytest.raises(ValueError):
        in_scope(tmp_path, [tmp_path / "a.md"], fail_open=False)


def test_a_config_that_never_opted_in_stays_green_when_it_does_not_parse(tmp_path):
    """YAML 이 못 읽는 파일은 `doc_style` 블록을 가졌는지 말하지 못하므로 원문에 물음. 없으면
    이 저장소는 켠 적이 없고, 아무도 켜지 않은 기능이 자기 소유도 아닌 파일의 다른 곳 오타로
    빌드를 붉히면 안 됨."""
    write_config(tmp_path, "branches:\n  - [unbalanced\n")
    assert scope_rules(tmp_path) is None
    assert config_paths(tmp_path) == []


@pytest.mark.parametrize("key", ['"doc_style"', "'doc_style'"])
def test_the_opt_in_is_recognised_however_the_key_is_quoted(tmp_path, key):
    """YAML 에게 `doc_style:`·`"doc_style":`·`'doc_style':` 는 같은 키라, 따옴표 친 쪽을 쓴
    저장소도 똑같이 켜 달라고 한 것. 맨 철자만 읽으면 바로 그 저장소가 붉은 잡이 막으려던
    침묵을 받음."""
    write_config(tmp_path, f"{key}:\n  enable: true\nb:\n  - [oops\n")
    with pytest.raises(SystemExit):
        config_paths(tmp_path)


def test_a_config_that_did_opt_in_still_exits_loudly_when_it_does_not_parse(tmp_path):
    """반대 절반. 여기서 침묵은 "꺼짐"으로 읽혀 붉은 잡 없이 CI 팔을 내림 — 애초에 크게
    실패하도록 고른 이유."""
    write_config(tmp_path, "doc_style:\n  enable: true\nbranches:\n  - [oops\n")
    with pytest.raises(SystemExit):
        config_paths(tmp_path)


@pytest.mark.parametrize("enable", ["true", "false"])
def test_an_unparseable_config_says_it_is_the_config_not_the_prose(tmp_path, enable):
    """잡 이름이 doc-style 이라 붉은 이유를 문체로 읽기 쉬움. `enable: false` 인 저장소도 붉게 둠 —
    설정이 깨진 동안 커밋 게이트는 미분류 커밋도 통과시키고(`test_main_allows_when_config_corrupt`),
    그것을 드러내는 것이 이 잡뿐임. 그래서 메시지가 원인·결과·할 일을 직접 말함."""
    write_config(tmp_path, f"doc_style:\n  enable: {enable}\nbranches:\n  - [oops\n")
    out = run_cli("--root", str(tmp_path), "--lint-config", cwd=tmp_path)
    assert out.returncode == 1, out.stderr
    for phrase in ("vdev-config.yaml", "YAML", "미분류 커밋", "설정부터 고칠 것", "flow sequence"):
        assert phrase in out.stderr, (phrase, out.stderr)


def test_vendored_directories_are_never_linted(tmp_path):
    write_config(tmp_path, 'doc_style:\n  enable: true\n  paths: ["**/*.md"]\n')
    for name in NEVER_LINTED:
        (tmp_path / name).mkdir()
        (tmp_path / name / "a.md").write_text("x", encoding="utf-8")
    assert config_paths(tmp_path) == []


def test_usage_lists_exactly_the_guarded_trees():
    """사용 설명서가 소비자에게 대는 이름 목록이 `NEVER_LINTED` 와 같음.

    소비자가 무엇을 `exclude` 에 적어야 하는지 판단하는 근거라 사본이 하나 필요하고, 사본은
    말없이 갈림 — 코드가 이름을 더해도 문서는 모름. 여기서 묶어 둠.
    """
    text = (REPO / "docs/usage/daily-work.md").read_text(encoding="utf-8")
    listed = re.search(r"가상환경·벤더 트리\((.*?)\)는", text, re.S)
    assert listed, "daily-work.md 의 가드 목록 문장을 못 찾음 — 문구가 바뀌면 이 테스트도 따라감"
    assert set(re.findall(r"`([^`]+)`", listed.group(1))) == set(NEVER_LINTED)


def test_the_guard_names_the_trees_that_carry_third_party_python(tmp_path):
    """가드를 기본 범위 + `.py` 로 잼 — `.md` 만 볼 때 무해하던 이름들이 여기서 폭발함.

    가상환경·도구 환경 안의 서드파티 `.py` 는 실측으로 `FILLER` 를 냄(`site-packages/yaml`).
    소비자가 고칠 편집이 없으므로, 그게 범위에 들면 CI 가 영구히 붉고 이 잡은 무시됨.
    `.venv` 만 막으면 `venv` 라 이름 붙인 흔한 배치가 그대로 새어 들어옴.
    """
    write_config(tmp_path, "doc_style:\n  enable: true\n")  # 기본 범위
    for name in ("venv", "site-packages", ".tox", ".nox", "third_party"):
        assert name in NEVER_LINTED, f"{name} 가 가드에 없음"
    for name in NEVER_LINTED:
        (tmp_path / name).mkdir(exist_ok=True)
        (tmp_path / name / "m.py").write_text("# 이건 게이트가 아니다\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("# 이건 게이트가 아니다\n", encoding="utf-8")
    got = [p.relative_to(tmp_path).as_posix() for p in config_paths(tmp_path)]
    assert got == ["src/m.py"]


@pytest.mark.parametrize(
    ("rel", "pattern", "hit"),
    [
        ("a.md", "**/*.md", True),
        ("docs/a.md", "**/*.md", True),
        ("docs/x/a.md", "docs/**/*.md", True),
        ("docs/a.md", "docs/**/*.md", True),  # 전체 세그먼트 `**` 는 0개도 이음
        ("docs/a.md", "docs/*", True),
        ("docs/x/a.md", "docs/*", False),
        ("docs/x/a.md", "docs/**", True),
        ("a.py", "**/*.md", False),
    ],
)
def test_glob_matcher(rel, pattern, hit):
    assert _match(rel, pattern) is hit


def test_unusable_glob_raises_rather_than_matching_nothing(tmp_path):
    write_config(tmp_path, 'doc_style:\n  enable: true\n  paths: ["[z-a]"]\n')
    assert in_scope(tmp_path, [tmp_path / "a.md"]) == []
    with pytest.raises(SystemExit):
        config_paths(tmp_path)


def test_config_paths_and_in_scope_answer_the_same(tmp_path):
    """CI 와 훅이 갈리면 소비자가 쓴 exclude 가 한쪽에만 걸림."""
    write_config(
        tmp_path,
        'doc_style:\n  enable: true\n  paths: ["docs/**/*.md"]\n  exclude: ["docs/x/**"]\n',
    )
    (tmp_path / "docs" / "x").mkdir(parents=True)
    (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "x" / "b.md").write_text("x", encoding="utf-8")
    (tmp_path / "top.md").write_text("x", encoding="utf-8")
    walked = config_paths(tmp_path)
    asked = in_scope(tmp_path, sorted(tmp_path.rglob("*.md")))
    assert walked == asked
    assert [p.name for p in walked] == ["a.md"]


# ---------- CLI ----------


def test_cli_lint_reports_and_exits_1(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("This was previously wrong\n", encoding="utf-8")
    out = run_cli("--root", str(tmp_path), "--lint", str(doc))
    assert out.returncode == 1
    assert "HIST" in out.stderr
    assert "a.md:1" in out.stderr


def test_cli_lint_config_is_green_without_the_block(tmp_path):
    (tmp_path / "a.md").write_text("This was previously wrong\n", encoding="utf-8")
    out = run_cli("--root", str(tmp_path), "--lint-config")
    assert out.returncode == 0, out.stderr


def test_cli_warning_alone_does_not_fail(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("가" * 101 + "\n", encoding="utf-8")
    out = run_cli("--root", str(tmp_path), "--lint", str(doc))
    assert out.returncode == 0
    assert "LONG" in out.stderr


def test_this_repos_ci_covers_the_same_extensions_as_the_default():
    """자기 CI 의 `env` 목록이 `DEFAULT_GLOBS` 와 같은 확장자를 덮음.

    워크플로 주석이 "같게 둠"을 선언하지만 재는 것이 없으면 한쪽만 확장자를 잃음. 추적되는
    `.bash` 파일이 0개라 `env` 에서 그 글롭을 지워도 대상 수가 그대로고 아무도 못 봄 —
    `test_this_repo_is_clean` 이 `env` 를 SSOT 로 읽으므로 그 축소를 초록으로 통과시킴.
    """
    workflow = _yaml.safe_load(
        (REPO / ".github" / "workflows" / "doc-style.yml").read_text(encoding="utf-8")
    )
    globs = workflow["jobs"]["doc-style"]["env"]["DOC_STYLE_GLOBS"].split()
    assert {Path(g).suffix for g in globs} == {Path(g).suffix for g in DEFAULT_GLOBS}


def test_this_repo_is_clean():
    """이 저장소 자신의 산문이 규율을 지킴.

    대상 목록을 여기 적지 않고 CI 워크플로의 `env` 에서 읽음 — 목록이 둘이면 이 테스트가
    green 인 채로 CI 가 붉어질 수 있고, 그 어긋남을 아무도 못 봄. 글롭은 `git ls-files` 에
    인자로 넘겨 git 이 풀게 함(셸을 거치지 않으므로 `*` 가 `/` 를 넘음).
    """
    workflow = _yaml.safe_load(
        (REPO / ".github" / "workflows" / "doc-style.yml").read_text(encoding="utf-8")
    )
    env = workflow["jobs"]["doc-style"]["env"]
    exclude = re.compile(env["DOC_STYLE_EXCLUDE"])
    raw = run_bounded(
        ["git", "ls-files", "-z", *env["DOC_STYLE_GLOBS"].split()],
        cwd=str(REPO),
        encoding="utf-8",
        errors="replace",
    ).stdout
    # NUL 로 끊음 — 개행으로 끊으면 공백 든 경로가 쪼개지고 비ASCII 경로는 C-인용된 채로 와
    # 존재하지 않는 경로가 됨. 그러면 이 테스트는 green 인 채로 그 파일만 검사 밖에 남음.
    tracked = [rel for rel in raw.split("\0") if rel]
    targets = [REPO / rel for rel in tracked if not exclude.search(rel)]
    # 글롭이 조용히 아무것도 못 고르면 위 lint 가 무조건 통과함 — 빈 대상은 그 자체로 실패.
    assert len(targets) > 100, f"대상이 {len(targets)}개뿐 — 글롭이 깨짐"
    out = run_cli("--root", str(REPO), "--lint", *[str(p) for p in targets])
    assert out.returncode == 0, out.stderr


# ---------- --scope: 리뷰의 파일 목록 ----------

SCOPE_TREE = ["a.md", "src/m.py", "CHANGELOG.md", "docs/superpowers/plans/p.md", "legacy/v.md"]


def _scope_out(root: Path, capsys) -> list[str]:
    """`/` 로 쓴 루트 상대 경로 — Windows 의 `docs\\x.md` 를 따옴표 없이 다음 bash 명령에 넘기면
    백슬래시가 사라지고, 린트는 아무것도 못 읽은 채 통과함."""
    for rel in SCOPE_TREE:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n", encoding="utf-8")
    assert main(["--root", str(root), "--scope", *(str(root / r) for r in SCOPE_TREE)]) == 0
    return sorted(capsys.readouterr().out.splitlines())


def test_scope_keeps_the_hosts_paths_and_exclude(tmp_path, capsys):
    """prose-review 는 여기 찍힌 것을 사람 없이 고침 — 프로젝트가 문체 범위에서 뺀 파일은 닿으면
    안 됨."""
    write_config(
        tmp_path,
        "doc_style:\n  enable: true\n  paths: ['**/*.md', '**/*.py']\n  exclude: ['legacy/**']\n",
    )
    assert _scope_out(tmp_path, capsys) == [
        "CHANGELOG.md",
        "a.md",
        "docs/superpowers/plans/p.md",
        "src/m.py",
    ]


@pytest.mark.parametrize("config", [None, "doc_style:\n  enable: false\n"])
def test_scope_falls_back_to_the_default_where_doc_style_is_off(tmp_path, capsys, config):
    """규율은 린트 게이트가 켜졌든 아니든 출하되는 `.md` 와 모든 주석을 묶음 — 꺼졌거나 없는
    블록은 아무것도 안 보는 대신 검사기가 읽을 수 있는 것을, 예시 설정의 기본 `exclude` 를
    빼고 봄."""
    if config is not None:
        write_config(tmp_path, config)
    assert _scope_out(tmp_path, capsys) == ["a.md", "legacy/v.md", "src/m.py"]
