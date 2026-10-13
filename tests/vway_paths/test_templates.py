"""템플릿 조회 — 호스트 사본이 플러그인 원본을 이기고, 그 사본은 VWAY_DIR 아래 삶."""

from pathlib import Path

import scripts._vway_paths as vp


def test_templates_lookup_host_wins(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    (vp.vway_dir(host) / "templates" / "alm").mkdir(parents=True)
    (vp.vway_dir(host) / "templates" / "alm" / "requirement.md").write_text(
        "host", encoding="utf-8"
    )
    (plugin / "templates" / "alm").mkdir(parents=True)
    (plugin / "templates" / "alm" / "requirement.md").write_text("plugin", encoding="utf-8")
    found = vp.templates_lookup("alm/requirement.md", host, plugin)
    assert found is not None
    assert Path(found).read_text(encoding="utf-8") == "host"


def test_templates_lookup_ignores_host_repo_root_templates(tmp_path: Path):
    """저장소 루트 `templates/` 는 호스트 후보가 아님 — 그 이름은 남의 것일 수 있음.

    Django·Flask·Jekyll 프로젝트의 `templates/` 가 그 자리에 삶. 거기를 읽으면
    호스트가 둔 적 없는 파일이 요약 템플릿으로 승격됨."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    (host / "templates" / "alm").mkdir(parents=True)
    (host / "templates" / "alm" / "requirement.md").write_text("app", encoding="utf-8")
    (plugin / "templates" / "alm").mkdir(parents=True)
    (plugin / "templates" / "alm" / "requirement.md").write_text("plugin", encoding="utf-8")
    found = vp.templates_lookup("alm/requirement.md", host, plugin)
    assert found is not None
    assert Path(found).read_text(encoding="utf-8") == "plugin"


def test_templates_lookup_plugin_fallback(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    host.mkdir()
    (plugin / "templates").mkdir(parents=True)
    (plugin / "templates" / "x.md").write_text("plugin", encoding="utf-8")
    assert vp.templates_lookup("x.md", host, plugin) is not None


def test_templates_lookup_missing_returns_none(tmp_path: Path):
    assert vp.templates_lookup("nope.md", tmp_path, tmp_path) is None


def test_template_rel_defaults_to_subdir_and_name():
    """선언에 template 이 없으면 <서브디렉터리>/<이름>.md — handoff·alm 이 같은 규칙."""
    assert vp.template_rel("qa", {}, "handoff") == "handoff/qa.md"
    assert vp.template_rel("design", {"workboard": "설계"}, "alm") == "alm/design.md"


def test_template_rel_keeps_an_explicit_value_verbatim():
    """적힌 값은 확장자까지 그대로 — 암묵 탐색만 md 로 고정됨."""
    assert vp.template_rel("qa", {"template": "custom/x.md"}, "handoff") == "custom/x.md"


def test_template_rel_treats_a_blank_template_as_absent():
    """빈 문자열은 '지정했음' 이 아님 — 빈 rel 은 templates/ 디렉터리 자신을 가리킴."""
    assert vp.template_rel("qa", {"template": ""}, "handoff") == "handoff/qa.md"
    assert vp.template_rel("qa", {"template": "   "}, "handoff") == "handoff/qa.md"


# ── rel 안전성 ─────────────────────────────────────────────────────────────────


def test_template_rel_rejects_a_value_that_escapes_the_templates_dir():
    """`..` 는 기본값으로 떨어짐 — 그 rel 은 셋업이 **이동**에도 쓰므로, 통과시키면
    저장소 밖 파일이 옮겨짐(원위치에서 사라짐)."""
    assert vp.template_rel("qa", {"template": "../../SECRET.md"}, "handoff") == "handoff/qa.md"
    assert vp.template_rel("qa", {"template": "a/../../b.md"}, "handoff") == "handoff/qa.md"


def test_template_rel_rejects_an_absolute_or_drive_path():
    for value in ("C:/x/y.md", "/etc/passwd", r"\\server\share\x.md", "C:x.md"):
        assert vp.template_rel("qa", {"template": value}, "handoff") == "handoff/qa.md"


def test_template_rel_rejects_a_non_string_value():
    """YAML 은 `template: 3` 도 받음 — 숫자를 경로로 이으면 셋업이 엉뚱한 자리를 만짐."""
    for value in (3, True, ["a.md"], {"path": "a.md"}):
        assert vp.template_rel("qa", {"template": value}, "handoff") == "handoff/qa.md"


def test_template_rel_keeps_a_nested_relative_value():
    """거절은 탈출뿐 — 평범한 하위 경로는 그대로 통과."""
    assert vp.template_rel("qa", {"template": "custom/deep/x.md"}, "handoff") == "custom/deep/x.md"


def test_is_safe_template_rel_names_what_it_rejects():
    assert vp.is_safe_template_rel("handoff/qa.md")
    assert not vp.is_safe_template_rel("../x.md")
    assert not vp.is_safe_template_rel("C:/x.md")
    assert not vp.is_safe_template_rel("")


# ── 구경로 폴백 알림 ───────────────────────────────────────────────────────────


def test_legacy_template_path_finds_an_unmigrated_override(tmp_path: Path):
    """호스트가 구경로에 양식을 둔 채 셋업을 안 돌렸으면, 그 사실을 소비자가 댈 수
    있어야 함 — 아니면 요약이 아무 신호 없이 출하본으로 바뀜."""
    (tmp_path / "templates" / "handoff").mkdir(parents=True)
    (tmp_path / "templates" / "handoff" / "summary.md").write_text("old", encoding="utf-8")
    assert vp.legacy_template_path("handoff/summary.md", tmp_path) is not None


def test_legacy_template_path_is_silent_once_migrated(tmp_path: Path):
    for root in (tmp_path / "templates", vp.vway_dir(tmp_path) / "templates"):
        (root / "handoff").mkdir(parents=True)
        (root / "handoff" / "summary.md").write_text("x", encoding="utf-8")
    assert vp.legacy_template_path("handoff/summary.md", tmp_path) is None


def test_legacy_template_path_is_silent_on_a_fresh_host(tmp_path: Path):
    assert vp.legacy_template_path("handoff/summary.md", tmp_path) is None


def test_is_safe_template_rel_rejects_a_non_string_without_raising():
    """직접 부르는 쪽이 있으므로 술어 자신이 형을 봐야 함 — `template: 3` 이
    AttributeError 로 새면 셋업 전체가 죽음(`_step` 이 못 잡는 예외)."""
    for value in (3, True, None, ["a"], {"b": 1}):
        assert not vp.is_safe_template_rel(value)


def test_is_safe_template_rel_reads_backslashes_as_separators():
    r"""Windows 에서 쓴 config 가 `..\..\X` 를 담음 — 슬래시만 보면 탈출이 통과함."""
    assert not vp.is_safe_template_rel(r"..\..\SECRET.md")
    assert not vp.is_safe_template_rel(r"a\..\..\b.md")


def test_is_reparse_point_names_a_link(tmp_path: Path):
    import pytest

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("이 호스트에서 디렉터리 심볼릭 링크를 만들 수 없음")
    assert vp.is_reparse_point(link)
    assert not vp.is_reparse_point(target)
    assert not vp.is_reparse_point(tmp_path / "absent")


def _junction(link: Path, target: Path):
    """Windows 정션 — `is_symlink()` 가 False 라 나머지 두 분기만이 답할 수 있음."""
    import os
    import subprocess

    import pytest

    if os.name != "nt":
        pytest.skip("정션은 Windows 전용")
    if subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
    ).returncode:
        pytest.skip("이 호스트에서 정션을 만들 수 없음")


def test_is_reparse_point_detects_a_junction_without_isjunction(tmp_path, monkeypatch):
    """`os.path.isjunction` 은 3.12+ — 지원 하한 3.8 에선 st_file_attributes 가 유일한
    정션 검출기이고, CI 가 3.12 라 그 경로를 안 밟으므로 여기서 고정함."""
    import os

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _junction(link, target)
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    assert vp.is_reparse_point(link)


def test_is_reparse_point_detects_a_junction_without_file_attributes(tmp_path, monkeypatch):
    """st_file_attributes 가 없는 판(POSIX·구형 stat)에서는 isjunction 이 유일한 답."""
    real_lstat = Path.lstat

    class _NoFileAttributes:
        def __init__(self, stat_result):
            self.st_mode = stat_result.st_mode

    monkeypatch.setattr(Path, "lstat", lambda self: _NoFileAttributes(real_lstat(self)))
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _junction(link, target)
    assert vp.is_reparse_point(link)


def test_is_reparse_point_stays_false_for_a_plain_dir_on_every_branch(tmp_path, monkeypatch):
    """분기를 지워도 평범한 디렉터리는 계속 False — 가드가 모든 이전을 막으면 안 됨."""
    import os

    plain = tmp_path / "plain"
    plain.mkdir()
    assert not vp.is_reparse_point(plain)
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    assert not vp.is_reparse_point(plain)


def test_legacy_template_path_is_silent_in_the_plugin_source_repo(tmp_path: Path):
    """플러그인을 출하하는 저장소의 `templates/` 는 출하본이지 누가 두고 간 오버라이드가
    아님. 알리면 그 권고를 따랐을 때 셋업이 출하 SOURCE 를 VWAY_DIR 밑으로 옮겨 버림.

    판정은 매니페스트로 함 — 개발자 세션은 설치 캐시를 실행하므로 host 와 plugin 경로를
    맞대 보면 늘 다름."""
    (tmp_path / "templates" / "handoff").mkdir(parents=True)
    (tmp_path / "templates" / "handoff" / "summary.md").write_text("ship", encoding="utf-8")
    manifest = tmp_path / vp.PLUGIN_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"name": "x"}', encoding="utf-8")
    assert vp.legacy_template_path("handoff/summary.md", tmp_path) is None


def test_legacy_template_path_still_names_a_real_override(tmp_path: Path):
    """매니페스트가 없는 평범한 소비자 저장소에선 그대로 알림."""
    host = tmp_path / "host"
    (host / "templates" / "handoff").mkdir(parents=True)
    (host / "templates" / "handoff" / "summary.md").write_text("mine", encoding="utf-8")
    assert vp.legacy_template_path("handoff/summary.md", host) is not None


def test_template_rel_never_returns_an_escaping_rel_for_any_name():
    """이름은 config 의 **키**(handoff 종류·ALM 계층) — 값과 달리 검사를 안 거치는 자리.
    `../` 가 든 키 하나가 셋업의 이동·삭제를 저장소 밖으로 끌고 감."""
    for name in ("../../SECRET", r"..\..\SECRET", "a/../..", "..", ".", "sub/deep"):
        rel = vp.template_rel(name, {}, "alm")
        assert vp.is_safe_template_rel(rel), rel


def test_template_rel_keeps_an_ordinary_name_readable():
    """가두는 것은 구분자와 점 조각뿐 — 한글·기호 키는 그대로 읽힘."""
    assert vp.template_rel("요약", {}, "handoff") == "handoff/요약.md"
    assert vp.template_rel("done_flag", {}, "handoff") == "handoff/done_flag.md"


def test_plugin_manifest_names_the_real_manifest_path():
    """이 상수 하나가 SOURCE 저장소 판정의 전부 — 값이 어긋나면 판정이 통째로 빠짐."""
    assert vp.PLUGIN_MANIFEST == ".claude-plugin/plugin.json"
    assert (Path(__file__).resolve().parents[2] / vp.PLUGIN_MANIFEST).is_file()


def test_one_segment_converges_names_that_are_not_names():
    """빈 값·공백만·점 조각은 서로 다른 파일로 갈리면 안 됨 — 이름이 아닌 것은 하나로.
    안전 판정만 물어서는 `handoff/.md`·`handoff/..md` 를 통과시키므로 여기서 잼."""
    for name in ("", "   ", ".", "..", "...", " . "):
        assert vp.template_rel(name, {}, "handoff") == "handoff/_.md"


def test_one_segment_trims_surrounding_space():
    assert vp.template_rel("  qa  ", {}, "handoff") == "handoff/qa.md"


def test_legacy_template_path_ignores_a_directory_at_that_rel(tmp_path: Path):
    """그 자리에 디렉터리가 앉으면 옮길 양식이 없는 것 — 셋업은 `old.is_file()` 로
    조용히 넘기므로, 여기만 넓히면 재실행이 절대 못 없애는 경고가 남음."""
    (tmp_path / "templates" / "handoff" / "summary.md").mkdir(parents=True)
    assert vp.legacy_template_path("handoff/summary.md", tmp_path) is None
