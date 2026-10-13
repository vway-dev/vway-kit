"""호스트 템플릿의 출발점 — 선언 읽기 · 시드 · 순서 계약 · 정리.

무엇이 그 자리에 있어야 하는지를 **config 선언**에서만 읽는가, 이미 있는 호스트 사본을
**덮지 않는가**, 그리고 셋업이 두는 자리와 스킬이 찾는 자리가 같은가."""

from pathlib import Path

from scripts._vway_paths import vway_dir
from scripts.vdev_init_setup import (
    declared_template_rels,
    remove_vway_dir,
    run_setup,
    seed_host_templates,
    sync_host_templates,
)
from tests.vdev_init._helpers import _mk_example, _mk_host_config
from tests.vdev_init._template_helpers import CONFIG, _mk, _symlink_dir


def test_declared_rels_cover_handoff_kinds_and_alm_layers(tmp_path: Path):
    _mk_host_config(tmp_path, CONFIG)
    assert declared_template_rels(tmp_path) == [
        "handoff/summary.md",
        "handoff/qa.md",
        "custom/flag.md",
        "alm/requirement.md",
        "alm/task.md",
    ]


def test_declared_rels_include_a_disabled_kind(tmp_path: Path):
    """`enable: false` 도 선언 — 켜는 날 템플릿이 없으면 그때 다시 셋업을 돌려야 함."""
    _mk_host_config(tmp_path, "handoff:\n  qa:\n    enable: false\n    field: col22\n")
    assert declared_template_rels(tmp_path) == ["handoff/qa.md"]


def test_declared_rels_are_empty_without_a_config(tmp_path: Path):
    assert declared_template_rels(tmp_path) == []


def test_seed_copies_only_what_the_config_declares(tmp_path: Path):
    """선언 안 된 템플릿은 플러그인 폴백으로 남음 — 사본이 생기면 개선이 안 닿음."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    _mk(plugin / "templates" / "alm" / "task.md", "P")
    seed_host_templates(host, plugin)
    assert (vway_dir(host) / "templates" / "handoff" / "summary.md").is_file()
    assert not (vway_dir(host) / "templates" / "alm" / "task.md").exists()


def test_seed_never_overwrites_a_host_copy(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    _mk(vway_dir(host) / "templates" / "handoff" / "summary.md", "H")
    seed_host_templates(host, plugin)
    assert (vway_dir(host) / "templates" / "handoff" / "summary.md").read_text(
        encoding="utf-8"
    ) == "H"


def test_seed_reports_a_kind_the_plugin_does_not_ship(tmp_path: Path):
    """`qa` 처럼 출하본이 없는 종류는 오류가 아님 — instruction 만으로 도는 정상 경로."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(host, "handoff:\n  qa:\n    enable: true\n    field: col22\n")
    (plugin / "templates").mkdir(parents=True)
    report = seed_host_templates(host, plugin)
    assert any("handoff/qa.md" in line for line in report)
    assert not any(line.lstrip().startswith("[!]") for line in report)


def test_sync_migrates_before_it_seeds(tmp_path: Path):
    """이전이 먼저라야 옮겨 온 호스트 양식이 남음 — 시드가 먼저면 출하본이 자리를
    차지하고, 이전은 '신경로에 이미 있음' 으로 구경로 파일을 영원히 두고 감."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(host / "templates" / "handoff" / "summary.md", "host-edited")
    _mk(plugin / "templates" / "handoff" / "summary.md", "shipped")
    sync_host_templates(host, plugin)
    assert (vway_dir(host) / "templates" / "handoff" / "summary.md").read_text(
        encoding="utf-8"
    ) == "host-edited"


def test_uninstall_names_the_templates_it_deletes(tmp_path: Path):
    """호스트 템플릿은 사람이 쓴 산문이라, 사라진 사실이 보고에 이름으로 남아야 함
    (gitignore 밖이라 커밋해 둔 것은 복구되지만, 조용히 사라지면 되돌릴 생각을 못 함)."""
    _mk(vway_dir(tmp_path) / "templates" / "handoff" / "summary.md", "host")
    assert "템플릿" in remove_vway_dir(tmp_path)


def test_uninstall_message_omits_templates_when_there_are_none(tmp_path: Path):
    (vway_dir(tmp_path) / "config").mkdir(parents=True)
    assert "템플릿" not in remove_vway_dir(tmp_path)


def test_seed_does_not_write_through_a_link_in_the_host_copy_dir(tmp_path: Path):
    """호스트 사본 자리 안의 링크 너머는 저장소 밖 — 시드가 거기 파일을 만들면 안 됨."""
    host, plugin, outside = tmp_path / "host", tmp_path / "plugin", tmp_path / "outside"
    outside.mkdir()
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    (vway_dir(host) / "templates").mkdir(parents=True)
    _symlink_dir(vway_dir(host) / "templates" / "handoff", outside)
    seed_host_templates(host, plugin)
    assert not (outside / "summary.md").exists()


def test_seed_does_not_write_through_a_link_at_the_host_copy_root(tmp_path: Path):
    """`under_real_tree` 가 root 자신을 봐야 함 — 하위만 재는 테스트는 그것을 못 잡음."""
    host, plugin, outside = tmp_path / "host", tmp_path / "plugin", tmp_path / "outside"
    outside.mkdir()
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    vway_dir(host).mkdir(parents=True, exist_ok=True)
    _symlink_dir(vway_dir(host) / "templates", outside)
    seed_host_templates(host, plugin)
    assert not (outside / "handoff" / "summary.md").exists()


def test_seed_report_names_the_real_host_copy_location(tmp_path: Path):
    """보고 줄이 실제 자리를 가리켜야 함 — 상수만 있고 검증이 없으면 드리프트가 안 잡힘."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    report = seed_host_templates(host, plugin)
    written = vway_dir(host) / "templates" / "handoff" / "summary.md"
    assert written.is_file()
    named = written.relative_to(host).as_posix()
    assert any(named in line for line in report)


def test_declared_rels_dedupe_across_spaces(tmp_path: Path):
    """스페이스 둘이 같은 계층 키를 선언하는 것은 흔함 — 중복을 안 접으면 한 실행이
    같은 rel 에 대해 `[+] 시드` 와 `[=] 이미 있음` 을 함께 찍어 보고가 자기모순이 됨."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(
        host,
        "alm:\n  recoble:\n    spaces:\n"
        "      a:\n        layers:\n          task:\n            workboard: b1\n"
        "      b:\n        layers:\n          task:\n            workboard: b2\n",
    )
    assert declared_template_rels(host) == ["alm/task.md"]
    _mk(plugin / "templates" / "alm" / "task.md", "P")
    report = seed_host_templates(host, plugin)
    assert len(report) == 1, report


def test_the_consumer_finds_exactly_what_the_seed_placed(tmp_path: Path):
    """셋업이 두는 자리와 스킬이 찾는 자리가 같은 rel 을 쓰는지 — 그 배선이 이 변경의
    전부임. 갈리면 시드한 호스트 양식이 영영 안 읽히고, 거절했어야 할 `template:` 값이
    소비자 쪽에서 저장소 밖을 읽음."""
    from scripts.alm_layers import normalize_layer
    from scripts.handoff_resolve import resolve_template_path

    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(
        host,
        "handoff:\n"
        "  a/b:\n    enable: true\n    field: col1\n"
        "  esc:\n    enable: true\n    field: col2\n    template: ../../SECRET.md\n"
        "alm:\n  recoble:\n    spaces:\n      dev3:\n        layers:\n"
        "          c/d:\n            workboard: x\n",
    )
    _mk(tmp_path / "SECRET.md", "secret")
    for rel in ("handoff/a_b.md", "handoff/esc.md", "alm/c_d.md"):
        _mk(plugin / "templates" / rel, "P")
    seed_host_templates(host, plugin)

    for kind in ("a/b", "esc"):
        found = resolve_template_path(
            {"template": "../../SECRET.md"} if kind == "esc" else {}, kind, plugin, host
        )
        assert found is not None, kind
        assert (
            Path(found) == vway_dir(host) / "templates" / "handoff" / f"{kind.replace('/', '_')}.md"
        )
    layer = normalize_layer("c/d", {"workboard": "x"}, plugin, host)
    assert layer is not None and layer["template"] is not None
    assert Path(layer["template"]) == vway_dir(host) / "templates" / "alm" / "c_d.md"


def test_run_setup_reports_the_template_step(tmp_path: Path, capsys):
    """단계가 목록에 배선돼 있는지 — 함수만 재면 그 줄을 지워도 초록."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    plugin.mkdir()
    _mk_example(plugin, "branches:\n  integration: dev\n")
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    run_setup(host, plugin)
    assert "[템플릿]" in capsys.readouterr().out


def test_declarations_survive_a_scalar_where_a_dict_belongs(tmp_path: Path):
    """`summary: just-a-string` 하나가 예외를 흘리면 `_step` 이 못 잡아 셋업 전체가
    죽고 뒤 단계(pre-commit·gitignore·게이트 판정)가 안 돎."""
    _mk_host_config(
        tmp_path,
        "handoff:\n  summary: just-a-string\n"
        "alm:\n  recoble:\n    spaces:\n      dev3:\n        layers:\n          task: nope\n",
    )
    assert declared_template_rels(tmp_path) == []


def test_sync_says_so_when_nothing_is_declared(tmp_path: Path):
    """빈 보고는 `[템플릿]` 헤더만 남겨 사람이 단계가 돌았는지 모름."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    plugin.mkdir()
    assert sync_host_templates(host, plugin) == ["  [=] 선언된 템플릿 없음 (skip)"]


def test_declarations_survive_a_scalar_where_a_container_belongs(tmp_path: Path):
    """컨테이너 다섯도 spec 둘과 같은 위험 — `handoff: nope` 하나가 `.items()` 로
    AttributeError 를 던지면 `_step` 이 못 잡아 셋업이 `[템플릿]` 에서 죽고 그 뒤
    단계(pre-commit·gitignore·워크플로·게이트 판정)가 통째로 안 돎."""
    for body in (
        "handoff: nope\n",
        "alm:\n  recoble: nope\n",
        "alm:\n  recoble:\n    spaces: nope\n",
        "alm:\n  recoble:\n    spaces:\n      s: nope\n",
        "alm:\n  recoble:\n    spaces:\n      s:\n        layers: nope\n",
    ):
        _mk_host_config(tmp_path, body)
        assert declared_template_rels(tmp_path) == [], body


def test_seed_still_runs_in_a_plugin_source_repo(tmp_path: Path):
    """출하 저장소는 이전·경고만 무음 — 시드는 그대로 돎. 그 저장소의 루트 `templates/`
    는 자기 플러그인 것이고 시드가 쓰는 자리와 겹치지 않음."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    manifest = host / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name": "x"}', encoding="utf-8")
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(host / "templates" / "handoff" / "summary.md", "authors own")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    sync_host_templates(host, plugin)
    assert (vway_dir(host) / "templates" / "handoff" / "summary.md").is_file()
    assert (host / "templates" / "handoff" / "summary.md").read_text(encoding="utf-8") == (
        "authors own"
    )


def test_seed_does_not_write_through_a_link_above_the_host_copy_root(tmp_path: Path):
    """`.claude/vway-kit` 자체가 링크인 경우도 이전과 같은 경계 — 그 위 한 칸이
    빠지면 시드가 저장소 밖에 파일을 만듦."""
    host, plugin, outside = tmp_path / "host", tmp_path / "plugin", tmp_path / "outside"
    outside.mkdir()
    (host / ".claude").mkdir(parents=True)
    _symlink_dir(host / ".claude" / "vway-kit", outside)
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    seed_host_templates(host, plugin)
    assert not (outside / "templates" / "handoff" / "summary.md").exists()


def test_seed_says_it_kept_an_existing_host_copy(tmp_path: Path):
    """보고가 없으면 `sync` 의 빈보고 폴백이 발화해, 선언이 있는 호스트를 없다고 말함."""
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    _mk(plugin / "templates" / "handoff" / "summary.md", "P")
    _mk(vway_dir(host) / "templates" / "handoff" / "summary.md", "H")
    report = sync_host_templates(host, plugin)
    assert any("이미 있음" in line and "summary.md" in line for line in report), report
    assert not any("선언된 템플릿 없음" in line for line in report), report


def test_seed_leaves_a_rel_the_migration_could_not_reach(tmp_path: Path):
    """이전이 링크로 막은 자리를 시드가 채우면 안 됨 — never-overwrite 라, 링크를
    고치고 다시 돌려도 그 양식은 영영 안 옮겨지고 경고만 조용해짐."""
    host, plugin, outside = tmp_path / "host", tmp_path / "plugin", tmp_path / "outside"
    _mk(outside / "summary.md", "MY OWN FORM")
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    (host / "templates").mkdir(parents=True)
    _symlink_dir(host / "templates" / "handoff", outside)
    _mk(plugin / "templates" / "handoff" / "summary.md", "SHIPPED")
    sync_host_templates(host, plugin)
    assert not (vway_dir(host) / "templates" / "handoff" / "summary.md").exists()


def test_seed_fills_a_rel_that_has_nothing_behind_the_link(tmp_path: Path):
    """링크가 있어도 그 자리에 양식이 없으면 막을 것이 없음 — 시드는 정상."""
    host, plugin, outside = tmp_path / "host", tmp_path / "plugin", tmp_path / "outside"
    outside.mkdir()
    _mk_host_config(host, "handoff:\n  summary:\n    enable: true\n    field: item_content\n")
    (host / "templates").mkdir(parents=True)
    _symlink_dir(host / "templates" / "handoff", outside)
    _mk(plugin / "templates" / "handoff" / "summary.md", "SHIPPED")
    sync_host_templates(host, plugin)
    assert (vway_dir(host) / "templates" / "handoff" / "summary.md").is_file()
