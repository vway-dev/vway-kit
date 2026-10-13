"""구경로 `templates/` 에서의 이전 — 무엇을 옮기고 무엇을 두고 오나.

남의 파일·빈 디렉터리·링크 너머를 건드리지 않는가, 그리고 저장소 밖으로 새지 않는가."""

from pathlib import Path

from scripts._vway_paths import vway_dir
from scripts.vdev_init_setup import (
    migrate_host_templates,
    sync_host_templates,
)
from tests.vdev_init._helpers import _mk_host_config
from tests.vdev_init._template_helpers import CONFIG, _junction, _mk, _symlink_dir


def test_migrate_moves_a_legacy_override_into_the_vway_dir(tmp_path: Path):
    _mk(tmp_path / "templates" / "handoff" / "summary.md", "host")
    report = migrate_host_templates(tmp_path)
    moved = vway_dir(tmp_path) / "templates" / "handoff" / "summary.md"
    assert moved.read_text(encoding="utf-8") == "host"
    assert not (tmp_path / "templates" / "handoff" / "summary.md").exists()
    assert any("handoff/summary.md" in line for line in report)


def test_migrate_leaves_foreign_files_in_the_repo_root_templates(tmp_path: Path):
    """저장소 루트 `templates/` 는 남의 것일 수 있음 — Django·Flask 앱 템플릿이 삶.

    vway-kit 이 이름을 댈 수 있는 것(handoff/·alm/·config 가 지목한 rel)만 옮김."""
    _mk(tmp_path / "templates" / "index.html", "app")
    _mk(tmp_path / "templates" / "emails" / "welcome.html", "app")
    # Jekyll 저장소의 `templates/*.md` — 열거 글롭이 `*.md` 라, 서브트리 제한이 없으면
    # 이것들이 vway-kit 것으로 셈해짐. 남의 `.md` 가 없는 픽스처는 그 제한을 못 잼.
    _mk(tmp_path / "templates" / "README.md", "app")
    _mk(tmp_path / "templates" / "posts" / "2026-01-01-hello.md", "app")
    _mk(tmp_path / "templates" / "alm" / "task.md", "host")
    migrate_host_templates(tmp_path)
    assert (tmp_path / "templates" / "index.html").is_file()
    assert (tmp_path / "templates" / "emails" / "welcome.html").is_file()
    assert (tmp_path / "templates" / "README.md").is_file()
    assert (tmp_path / "templates" / "posts" / "2026-01-01-hello.md").is_file()
    assert not (tmp_path / "templates" / "alm").exists()


def test_migrate_moves_a_custom_rel_named_by_the_config(tmp_path: Path):
    """`template:` 이 지목한 자리는 handoff/·alm/ 밖일 수 있음."""
    _mk_host_config(tmp_path, CONFIG)
    _mk(tmp_path / "templates" / "custom" / "flag.md", "host")
    migrate_host_templates(tmp_path)
    assert (vway_dir(tmp_path) / "templates" / "custom" / "flag.md").is_file()


def test_migrate_keeps_the_existing_host_copy(tmp_path: Path):
    """신경로에 이미 있으면 이동하지 않음 — 호스트가 고친 쪽이 이김."""
    _mk(tmp_path / "templates" / "handoff" / "summary.md", "old")
    _mk(vway_dir(tmp_path) / "templates" / "handoff" / "summary.md", "new")
    migrate_host_templates(tmp_path)
    assert (vway_dir(tmp_path) / "templates" / "handoff" / "summary.md").read_text(
        encoding="utf-8"
    ) == "new"
    assert (tmp_path / "templates" / "handoff" / "summary.md").is_file()


def test_migrate_is_idempotent_on_a_fresh_host(tmp_path: Path):
    assert migrate_host_templates(tmp_path) == []
    assert not (vway_dir(tmp_path) / "templates").exists()


def test_migrate_leaves_a_foreign_empty_dir(tmp_path: Path):
    """빈 디렉터리도 남의 것 — 옮긴 파일의 조상만 정리함."""
    (tmp_path / "templates" / "partials").mkdir(parents=True)
    (tmp_path / "templates" / "cache" / "nested").mkdir(parents=True)
    _mk(tmp_path / "templates" / "alm" / "task.md", "host")
    migrate_host_templates(tmp_path)
    assert (tmp_path / "templates" / "partials").is_dir()
    assert (tmp_path / "templates" / "cache" / "nested").is_dir()
    assert not (tmp_path / "templates" / "alm").exists()


def test_migrate_keeps_the_repo_root_templates_dir(tmp_path: Path):
    """옮길 것이 없으면 아무것도 지우지 않음 — 통째 소멸은 남의 트리를 없애는 길."""
    (tmp_path / "templates" / "cache").mkdir(parents=True)
    assert migrate_host_templates(tmp_path) == []
    assert (tmp_path / "templates" / "cache").is_dir()


def test_migrate_does_not_reach_through_a_symlinked_subtree(tmp_path: Path):
    """`handoff/`·`alm/` 이 링크면 그 너머는 남의 디렉터리 — 파일을 꺼내오지 않음."""
    outside = tmp_path / "outside"
    _mk(outside / "task.md", "someone else")
    (tmp_path / "templates").mkdir()
    _symlink_dir(tmp_path / "templates" / "alm", outside)
    migrate_host_templates(tmp_path)
    assert (outside / "task.md").is_file()
    assert (tmp_path / "templates" / "alm").exists()


def test_sync_reports_a_declaration_that_escapes_the_templates_dir(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(
        host,
        "handoff:\n  qa:\n    enable: true\n    field: col22\n    template: ../../SECRET.md\n",
    )
    (plugin / "templates").mkdir(parents=True)
    report = sync_host_templates(host, plugin)
    assert any("../../SECRET.md" in line and "[!]" in line for line in report)


def test_an_escaping_declaration_moves_nothing_outside(tmp_path: Path):
    host = tmp_path / "host"
    _mk(tmp_path / "SECRET.md", "secret")
    _mk_host_config(
        host,
        "handoff:\n  qa:\n    enable: true\n    field: col22\n    template: ../../SECRET.md\n",
    )
    (host / "templates").mkdir()
    migrate_host_templates(host)
    assert (tmp_path / "SECRET.md").read_text(encoding="utf-8") == "secret"


def test_no_report_line_names_a_drive_qualified_path(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(
        host,
        "handoff:\n  qa:\n    enable: true\n    field: col22\n    template: C:/x/y.md\n",
    )
    (plugin / "templates").mkdir(parents=True)
    assert not any(
        "C:/x/y.md" in line and "[=]" in line for line in sync_host_templates(host, plugin)
    )


def test_migrate_ignores_a_legacy_root_that_is_a_link(tmp_path: Path):
    """구경로 루트 자신이 링크면 그 아래 전부가 남의 트리 — 아무것도 옮기지 않음."""
    outside = tmp_path / "outside"
    _mk(outside / "alm" / "task.md", "someone else")
    host = tmp_path / "host"
    host.mkdir()
    _symlink_dir(host / "templates", outside)
    migrate_host_templates(host)
    assert (outside / "alm" / "task.md").is_file()
    assert not (vway_dir(host) / "templates").exists()


def test_migrate_does_not_reach_through_a_junction(tmp_path: Path):
    """정션은 `is_symlink()` 가 False — 그것만 물으면 그물이 통째로 새어 나감."""
    outside = tmp_path / "outside"
    _mk(outside / "task.md", "someone else")
    (tmp_path / "templates").mkdir()
    _junction(tmp_path / "templates" / "alm", outside)
    migrate_host_templates(tmp_path)
    assert (outside / "task.md").is_file()
    assert (tmp_path / "templates" / "alm").exists()


def test_prune_never_removes_the_legacy_root(tmp_path: Path):
    """구경로 루트는 정리 대상 밖 — 그 경계가 없으면 호스트 루트까지 후보가 됨."""
    _mk(tmp_path / "templates" / "handoff" / "summary.md", "host")
    migrate_host_templates(tmp_path)
    assert (tmp_path / "templates").is_dir()
    assert not (tmp_path / "templates" / "handoff").exists()


def test_sync_reports_a_falsy_non_string_declaration(tmp_path: Path):
    """`template: 0` 도 적은 것 — 진리값으로 물으면 그 거절이 조용해짐."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(host, "handoff:\n  qa:\n    enable: true\n    field: col22\n    template: 0\n")
    (plugin / "templates").mkdir(parents=True)
    assert any("[!]" in line and "qa" in line for line in sync_host_templates(host, plugin))


def test_migrate_does_not_move_through_a_link_at_the_host_copy_root(tmp_path: Path):
    """이동은 쓰기이자 삭제 — 목적지가 링크 너머면 호스트 양식이 저장소 밖으로 나감."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    outside.mkdir()
    _mk(host / "templates" / "handoff" / "summary.md", "mine")
    vway_dir(host).mkdir(parents=True, exist_ok=True)
    _symlink_dir(vway_dir(host) / "templates", outside)
    report = migrate_host_templates(host)
    assert (host / "templates" / "handoff" / "summary.md").is_file()
    assert not (outside / "handoff" / "summary.md").exists()
    assert any("[!]" in line for line in report)


def test_migrate_does_not_move_through_a_link_below_the_host_copy_root(tmp_path: Path):
    host, outside = tmp_path / "host", tmp_path / "outside"
    outside.mkdir()
    _mk(host / "templates" / "handoff" / "summary.md", "mine")
    (vway_dir(host) / "templates").mkdir(parents=True)
    _symlink_dir(vway_dir(host) / "templates" / "handoff", outside)
    migrate_host_templates(host)
    assert (host / "templates" / "handoff" / "summary.md").read_text(encoding="utf-8") == "mine"
    assert not (outside / "summary.md").exists()


def test_migrate_source_guard_holds_for_a_config_declared_rel(tmp_path: Path):
    """열거 가드(`handoff/`·`alm/` 서브트리)는 config 가 지목한 rel 을 안 거름 —
    그 rel 을 막는 것은 이동 루프의 출발지 판정 하나뿐."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    _mk(outside / "task.md", "someone else")
    _mk_host_config(
        host,
        "alm:\n  recoble:\n    spaces:\n      dev3:\n        layers:\n"
        "          task:\n            workboard: b\n",
    )
    (host / "templates").mkdir()
    _symlink_dir(host / "templates" / "alm", outside)
    migrate_host_templates(host)
    assert (outside / "task.md").is_file()
    assert not (vway_dir(host) / "templates" / "alm" / "task.md").exists()


def test_migrate_source_guard_holds_for_a_nested_junction(tmp_path: Path):
    """정션은 `rglob` 이 따라가므로 열거에 섞여 들어옴 — 출발지 판정이 막음."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    _mk(outside / "deep.md", "someone else")
    (host / "templates" / "alm").mkdir(parents=True)
    _junction(host / "templates" / "alm" / "sub", outside)
    migrate_host_templates(host)
    assert (outside / "deep.md").is_file()
    assert not (vway_dir(host) / "templates" / "alm" / "sub" / "deep.md").exists()


def test_migrate_leaves_a_plugin_source_repo_alone(tmp_path: Path):
    """매니페스트가 있는 저장소의 루트 `templates/` 는 출하본 — 옮기면 그 플러그인이
    자기 출하 SOURCE 를 잃음. 경고를 끈 판정과 같은 답이어야 함."""
    manifest = tmp_path / "\x2eclaude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name": "x"}', encoding="utf-8")
    _mk(tmp_path / "templates" / "handoff" / "summary.md", "ship")
    assert migrate_host_templates(tmp_path) == []
    assert (tmp_path / "templates" / "handoff" / "summary.md").is_file()


def test_migrate_never_leaves_the_host_for_an_escaping_config_key(tmp_path: Path):
    """종류명·계층키에 `../` 가 들어가도 저장소 밖 파일은 그대로."""
    host = tmp_path / "host"
    _mk(tmp_path / "victim.md", "someone else")
    _mk_host_config(
        host,
        "alm:\n  recoble:\n    spaces:\n      dev3:\n        layers:\n"
        '          "../../victim":\n            workboard: b\n',
    )
    (host / "templates" / "alm").mkdir(parents=True)
    migrate_host_templates(host)
    assert (tmp_path / "victim.md").read_text(encoding="utf-8") == "someone else"


def test_migrate_names_a_destination_it_cannot_take(tmp_path: Path):
    """신경로에 파일 아닌 것이 앉아 있으면 경고는 계속 나는데 셋업은 아무 말도 안 함 —
    수렴하지 않는 조용한 루프. 막힌 자리를 이름으로 대야 사람이 풀 수 있음."""
    _mk(tmp_path / "templates" / "handoff" / "summary.md", "mine")
    (vway_dir(tmp_path) / "templates" / "handoff" / "summary.md").mkdir(parents=True)
    report = migrate_host_templates(tmp_path)
    assert any("[!]" in line and "summary.md" in line for line in report)
    assert (tmp_path / "templates" / "handoff" / "summary.md").is_file()


def test_migrate_takes_only_markdown_out_of_the_shipped_subtrees(tmp_path: Path):
    """서브트리 안이라도 `.md` 만 — 팀이 거기 둔 이미지·스크립트는 남의 것."""
    _mk(tmp_path / "templates" / "alm" / "logo.png", "binary-ish")
    _mk(tmp_path / "templates" / "alm" / "task.md", "host")
    migrate_host_templates(tmp_path)
    assert (tmp_path / "templates" / "alm" / "logo.png").is_file()
    assert (vway_dir(tmp_path) / "templates" / "alm" / "task.md").is_file()


def test_prune_clears_a_whole_emptied_chain(tmp_path: Path):
    """깊은 것부터 지워야 사슬이 다 비워짐 — 얕은 것부터면 부모가 아직 안 비어 남음."""
    _mk(tmp_path / "templates" / "alm" / "sub" / "deep.md", "host")
    migrate_host_templates(tmp_path)
    assert not (tmp_path / "templates" / "alm").exists()
    assert (tmp_path / "templates").is_dir()


def test_migrate_is_quiet_on_a_fresh_host_that_declares_kinds(tmp_path: Path):
    """선언된 rel 은 구경로에 없어도 목록에 듦 — 존재 검사가 없으면 깨끗한 신규 설치가
    선언 수만큼 가짜 `[!] 이전 실패` 를 냄(스킬은 그 줄을 고치라고 지시함)."""
    _mk_host_config(tmp_path, CONFIG)
    (tmp_path / "templates").mkdir()
    assert migrate_host_templates(tmp_path) == []


def test_migrate_names_a_legacy_form_it_cannot_reach(tmp_path: Path):
    """`거기 아무것도 없음` 과 `양식은 있는데 링크 너머라 못 옮김` 은 다른 사실 —
    뒤엣것이 조용하면 소비자 경고가 재실행해도 안 사라지고 이유도 안 나옴(목적지 쪽
    가드 둘은 이미 그 대칭을 가짐)."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    _mk(outside / "summary.md", "mine")
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    (host / "templates").mkdir(parents=True)
    _symlink_dir(host / "templates" / "handoff", outside)
    report = migrate_host_templates(host)
    assert any("[!]" in line and "summary.md" in line for line in report)
    assert (outside / "summary.md").read_text(encoding="utf-8") == "mine"


def test_migrate_names_a_legacy_root_it_cannot_reach(tmp_path: Path):
    """구경로 루트 자신이 링크인 형태도 같은 대칭 — 조용히 빠지면 소비자 경고가
    재실행해도 안 사라지고, 같은 실행의 다른 단계가 그 반대를 말함."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    _mk(outside / "handoff" / "summary.md", "mine")
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    host.mkdir(exist_ok=True)
    _symlink_dir(host / "templates", outside)
    report = migrate_host_templates(host)
    assert any("[!]" in line and "templates/ 가 링크" in line for line in report), report
    assert (outside / "handoff" / "summary.md").read_text(encoding="utf-8") == "mine"


def test_migrate_is_silent_when_there_is_no_legacy_root(tmp_path: Path):
    """없는 것은 알릴 일이 아님 — 깨끗한 신규 설치가 조용해야 함."""
    _mk_host_config(tmp_path, CONFIG)
    assert migrate_host_templates(tmp_path) == []


def test_migrate_names_a_linked_shipped_subtree(tmp_path: Path):
    """선언이 없어도(암묵 summary 경로) 그 서브트리가 링크면 알려야 함 — 열거에서
    빠지는 rel 은 per-rel 보고에 닿지 못해, 소비자 경고만 영원히 남음."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    _mk(outside / "summary.md", "mine")
    (host / "templates").mkdir(parents=True)
    _symlink_dir(host / "templates" / "handoff", outside)
    report = migrate_host_templates(host)
    assert any("[!]" in line and "handoff" in line for line in report), report
    assert (outside / "summary.md").read_text(encoding="utf-8") == "mine"


def test_migrate_root_link_report_stays_quiet_in_a_plugin_source_repo(tmp_path: Path):
    """출하 저장소는 그 `templates/` 가 링크여도 알릴 일이 아님 — 남의 일이 아니라
    자기 출하본임."""
    outside = tmp_path / "outside"
    outside.mkdir()
    host = tmp_path / "host"
    manifest = host / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name": "x"}', encoding="utf-8")
    _symlink_dir(host / "templates", outside)
    assert migrate_host_templates(host) == []


def test_migrate_is_quiet_about_a_dangling_legacy_link(tmp_path: Path):
    """끊긴 링크는 옮길 양식이 없는 것 — 헛경고를 내면 고칠 것 없는 줄이 매번 남음."""
    host = tmp_path / "host"
    host.mkdir()
    _symlink_dir(host / "templates", tmp_path / "gone")
    assert migrate_host_templates(host) == []


def test_migrate_does_not_move_through_a_link_above_the_host_copy_root(tmp_path: Path):
    """`.claude/vway-kit` 자체가 링크여도 사람이 쓴 양식이 저장소를 떠나면 안 됨 —
    가드 경계가 `templates/` 까지면 그 위 한 칸이 그대로 구멍."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    outside.mkdir()
    _mk(host / "templates" / "handoff" / "summary.md", "mine")
    (host / ".claude").mkdir(parents=True, exist_ok=True)
    _symlink_dir(host / ".claude" / "vway-kit", outside)
    migrate_host_templates(host)
    assert (host / "templates" / "handoff" / "summary.md").read_text(encoding="utf-8") == "mine"
    assert not (outside / "templates" / "handoff" / "summary.md").exists()


def test_migrate_never_moves_a_directory_named_by_a_declaration(tmp_path: Path):
    """`template:` 이 디렉터리를 지목할 수 있음 — 파일 판정이 없으면 그 서브트리가
    통째로 옮겨져 남의 `.png`·`.sh` 까지 따라감."""
    _mk_host_config(
        tmp_path, "handoff:\n  qa:\n    enable: true\n    field: c\n    template: sub\n"
    )
    _mk(tmp_path / "templates" / "sub" / "logo.png", "binary-ish")
    _mk(tmp_path / "templates" / "sub" / "deep" / "build.sh", "#!/bin/sh\n")
    migrate_host_templates(tmp_path)
    assert (tmp_path / "templates" / "sub" / "logo.png").is_file()
    assert (tmp_path / "templates" / "sub" / "deep" / "build.sh").is_file()
    assert not (vway_dir(tmp_path) / "templates" / "sub").exists()


def test_migrate_does_not_list_files_behind_a_linked_subtree(tmp_path: Path):
    """서브트리가 링크면 그 안을 훑지 않음 — 남의 디렉터리 파일명이 보고에 실리고,
    공유·네트워크 드라이브를 통째로 `rglob` 하는 I/O 도 함께 붙음."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    _mk(outside / "foreign.md", "someone else")
    _mk(outside / "private" / "inner.md", "someone else")
    (host / "templates").mkdir(parents=True)
    _symlink_dir(host / "templates" / "handoff", outside)
    report = migrate_host_templates(host)
    assert not any("foreign.md" in line or "inner.md" in line for line in report), report


def test_migrate_is_quiet_about_a_link_with_nothing_behind_it(tmp_path: Path):
    """옮길 양식이 없는 링크는 고칠 편집이 없음 — 알리면 매 실행 지워지지 않는 줄이 남음
    (끊긴 링크를 조용히 두는 것과 같은 이유)."""
    host, outside = tmp_path / "host", tmp_path / "outside"
    outside.mkdir()
    host.mkdir()
    _symlink_dir(host / "templates", outside)
    assert migrate_host_templates(host) == []


def test_migrate_is_quiet_about_a_linked_subtree_with_nothing_behind_it(tmp_path: Path):
    host, outside = tmp_path / "host", tmp_path / "outside"
    outside.mkdir()
    (host / "templates").mkdir(parents=True)
    _symlink_dir(host / "templates" / "alm", outside)
    assert migrate_host_templates(host) == []
