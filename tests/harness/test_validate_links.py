"""링크 프래그먼트 판정 — `#앵커` 가 대상 문서에 실제로 있는가.

GitHub 슬러그를 그대로 재현해야 살아 있는 링크를 죽었다고 부르지 않음: 렌더된
텍스트를 슬러그하고(인라인 코드·엔티티는 살고 태그는 죽음), 중복 헤딩은 `-1` 로
번호가 붙고, `#L42` 는 앵커가 아니라 줄 참조. 대상 본문의 출처는 디스크 우선.
"""

import pytest

import scripts.harness_scaffold as hs
from tests.harness._helpers import _baseline_entry, _conv_entry


def _linking_plan(target_content, link):
    return {
        "files": [
            _baseline_entry(),
            {"path": "docs/sds/README.md", "action": "create", "content": f"[FR]({link})"},
            {"path": "docs/srs/README.md", "action": "create", "content": target_content},
        ]
    }


def _anchor_issues(tmp_path, target_content, link):
    rep = hs.validate_plan(tmp_path, _linking_plan(target_content, link))
    return [i for i in rep["issues"] if i["kind"] == "dead-anchor"]


def test_dead_anchor_warns(tmp_path):
    hits = _anchor_issues(tmp_path, '<a id="fr-001"></a>FR-001\n', "../srs/README.md#fr-999")
    assert len(hits) == 1 and hits[0]["severity"] == "warn"


def test_explicit_anchor_resolves(tmp_path):
    assert _anchor_issues(tmp_path, '<a id="fr-001"></a>FR-001\n', "../srs/README.md#fr-001") == []


def test_heading_slug_resolves(tmp_path):
    # <a id> 만 보면 이 저장소 자기 문서의 헤딩 링크가 전부 오탐이 됨.
    assert (
        _anchor_issues(
            tmp_path, "## Requirements Coverage\n", "../srs/README.md#requirements-coverage"
        )
        == []
    )


def test_hangul_heading_slug_resolves(tmp_path):
    # GitHub 는 슬러그에 유니코드 글자를 남김 — ASCII 만 남기면 한글 헤딩 링크가 전부 오탐.
    assert _anchor_issues(tmp_path, "## 요구 추적\n", "../srs/README.md#요구-추적") == []


def test_link_without_fragment_is_not_checked(tmp_path):
    assert _anchor_issues(tmp_path, "no anchors here\n", "../srs/README.md") == []


def test_anchor_check_skips_an_unresolvable_target(tmp_path):
    # 플랜에도 디스크에도 없는 대상은 이미 dead-link — 같은 원인으로 두 번 보고하면 소음.
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": "docs/sds/README.md",
                "action": "create",
                "content": "[FR](../nope/README.md#fr-001)",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not [i for i in rep["issues"] if i["kind"] == "dead-anchor"]


def test_slugify_strips_inline_markup():
    assert hs._slugify("`code` and **bold**") == "code-and-bold"


def test_slugify_unwraps_a_link():
    assert hs._slugify("[FR-001](../srs/README.md) 매핑") == "fr-001-매핑"


def test_github_line_fragment_is_not_an_anchor(tmp_path):
    # `#L42`·`#L42-L51` 은 문서 앵커가 아니라 GitHub 줄 참조 — 이 저장소 CLAUDE.md 가
    # 코드 인용에 그 형태를 지시함. 앵커로 읽으면 그런 링크가 전부 걸림.
    assert _anchor_issues(tmp_path, "no anchors here\n", "../srs/README.md#L153") == []
    assert _anchor_issues(tmp_path, "no anchors here\n", "../srs/README.md#L42-L51") == []


def test_slugify_keeps_underscores():
    # github-slugger 의 제거 집합에는 `-` 도 `_` 도 없어 `## vdev_gate_check` 는
    # `vdev_gate_check` 로 앵커됨. `_` 를 지우면 snake_case 헤딩 링크가 전부 죽은 것이 됨.
    assert hs._slugify("vdev_gate_check") == "vdev_gate_check"


def test_slugify_replaces_each_space_separately():
    # 구두점 제거가 공백→하이픈보다 **먼저**라, em dash 를 감싸던 공백 둘이 남아 GitHub 는
    # 하이픈 둘을 냄. 공백 런을 접으면 이 저장소의 지배적 헤딩 스타일에서 GitHub 와 갈림.
    assert hs._slugify("Step 1 — Classify the task") == "step-1--classify-the-task"


def test_duplicate_heading_gets_a_counter_suffix(tmp_path):
    # GitHub 는 반복 슬러그를 -1, -2 로 가름. 슬러그를 집합으로 모으면 이것을 죽었다고 부름.
    body = "## Overview\n\n## Overview\n"
    assert _anchor_issues(tmp_path, body, "../srs/README.md#overview-1") == []


def test_heading_inside_a_code_fence_is_not_an_anchor(tmp_path):
    body = "```bash\n# Probe the branch point\n```\n"
    hits = _anchor_issues(tmp_path, body, "../srs/README.md#probe-the-branch-point")
    assert len(hits) == 1


def test_setext_heading_resolves(tmp_path):
    body = "Requirements Coverage\n=====\n"
    assert _anchor_issues(tmp_path, body, "../srs/README.md#requirements-coverage") == []


def test_percent_encoded_fragment_resolves(tmp_path):
    # 한글 헤딩을 GitHub 에서 복사한 앵커 URL 의 모양.
    link = "../srs/README.md#%EC%9A%94%EA%B5%AC-%EC%B6%94%EC%A0%81"
    assert _anchor_issues(tmp_path, "## 요구 추적\n", link) == []


def test_data_id_is_not_an_explicit_anchor(tmp_path):
    body = '<a href="x" data-id="fr-001"></a>\n'
    hits = _anchor_issues(tmp_path, body, "../srs/README.md#fr-001")
    assert len(hits) == 1


def test_lens_upsert_target_is_read_from_disk(tmp_path):
    # lens_upsert 엔트리는 `stack`·`lenses` 만 들고 `content` 가 아예 없으며, 이미 있는
    # 파일을 고침. `.get("content", "")` 를 파일 대신 세우면 그 안의 앵커가 전부 죽었다고 나옴.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "bp.md").write_text("## Security\n", encoding="utf-8")
    plan = {
        "files": [
            _baseline_entry(),
            {"path": "docs/sds.md", "action": "create", "content": "[BP](bp.md#security)"},
            {
                "path": "docs/bp.md",
                "action": "lens_upsert",
                "stack": "go",
                "lenses": [{"lens": "security", "body": "### Security\n- x"}],
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not [i for i in rep["issues"] if i["kind"] == "dead-anchor"]


def test_marker_upsert_target_is_read_from_disk(tmp_path):
    # 다른 부분 액션으로 나는 같은 실패: 그 `content` 는 마커 본문뿐임.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "idx.md").write_text("## Rules\n", encoding="utf-8")
    plan = {
        "files": [
            _baseline_entry(),
            {"path": "docs/sds.md", "action": "create", "content": "[R](idx.md#rules)"},
            {
                "path": "docs/idx.md",
                "action": "marker_upsert",
                "marker_id": "harness:baseline",
                "content": "body only\n",
            },
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not [i for i in rep["issues"] if i["kind"] == "dead-anchor"]


def test_bom_target_resolves_its_first_heading(tmp_path):
    # BOM 은 선두 `#` 에 붙어 있고 U+FEFF 는 `\s` 가 아니라, utf-8(비 sig) 로 읽으면 첫
    # 헤딩이 매칭 불가가 됨 — Windows 에서만 나는 오탐(Invariant 2).
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "t.md").write_text("## Overview\n", encoding="utf-8-sig")
    plan = {
        "files": [
            _baseline_entry(),
            {"path": "docs/sds.md", "action": "create", "content": "[O](t.md#overview)"},
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not [i for i in rep["issues"] if i["kind"] == "dead-anchor"]


def test_inline_code_heading_resolves(tmp_path):
    # GitHub 는 **렌더된** 헤딩을 슬러그하므로 백틱 든 식별자가 살아남음. 인라인 스팬을
    # 슬러그 전에 걷어내면 이 살아 있는 링크를 죽었다고 보고함 — 이 저장소와 그것이 생성하는
    # 문서의 지배적 헤딩 스타일임. `_slugify` 단독 테스트로는 부족: 본문 전처리를 못 보는데,
    # 버그가 살던 자리가 거기임.
    body = "## `vdev_gate_check` resolution\n"
    link = "../srs/README.md#vdev_gate_check-resolution"
    assert _anchor_issues(tmp_path, body, link) == []


def test_html_entity_heading_resolves(tmp_path):
    # `&amp;` 는 `&` 로 렌더되고 그것을 구두점 제거가 지움 — 감싸던 공백 둘이 남음.
    assert _anchor_issues(tmp_path, "## Tips &amp; Tricks\n", "../srs/README.md#tips--tricks") == []


def test_html_tag_in_heading_is_not_slugged(tmp_path):
    assert _anchor_issues(tmp_path, "## <code>x</code> y\n", "../srs/README.md#x-y") == []


def test_target_front_matter_is_not_a_heading(tmp_path):
    # front matter 안의 `#` 줄은 헤딩이 아니라 주석. 이것을 세면 없는 앵커가 풀리고 뒤쪽
    # 중복 카운터까지 밀림 — `sds.template.md` 가 그런 줄을 여럿 싣고 나감.
    body = "---\n# sources: the code paths\nwiki_id: x\n---\n\n## Real\n"
    hits = _anchor_issues(tmp_path, body, "../srs/README.md#sources-the-code-paths")
    assert len(hits) == 1


def test_front_matter_does_not_shift_the_duplicate_counter(tmp_path):
    body = "---\n# Overview\nwiki_id: x\n---\n\n## Overview\n\n## Overview\n"
    assert _anchor_issues(tmp_path, body, "../srs/README.md#overview-1") == []


def test_entry_without_an_action_key_is_whole_file_content(tmp_path):
    # `apply_plan` 은 없는 `action` 을 "create" 로 봄 — 그 `content` 가 곧 파일임.
    # 제외하면 아직 없는 디스크 파일로 조회가 새어 검사 자체가 빠짐.
    plan = {
        "files": [
            _baseline_entry(),
            {"path": "docs/sds.md", "action": "create", "content": "[R](t.md#gone)"},
            {"path": "docs/t.md", "content": "## Present\n"},
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert len([i for i in rep["issues"] if i["kind"] == "dead-anchor"]) == 1


def test_plan_content_keys_are_normalized(tmp_path):
    plan = {
        "files": [
            _baseline_entry(),
            {"path": "docs/sds.md", "action": "create", "content": "[R](t.md#gone)"},
            {"path": "./docs/t.md", "action": "create", "content": "## Present\n"},
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    # 아무것도 보고되지 않았음이 아니라 대상의 **검사 여부**를 단언: 정규화 안 된 키는 조회를
    # 놓치고 없는 디스크 파일로 새어 아무것도 보고하지 않는데, 앵커가 진짜 죽지 않는 한
    # 깨끗한 통과와 구별되지 않음.
    assert len([i for i in rep["issues"] if i["kind"] == "dead-anchor"]) == 1


def test_atx_closing_hashes_are_trimmed(tmp_path):
    assert _anchor_issues(tmp_path, "## Overview ##\n", "../srs/README.md#overview") == []


def test_a_heading_followed_by_a_rule_is_not_a_setext(tmp_path):
    # `(?!\s{0,3}#)` 가드가 없으면 `---` 가 ATX 줄을 슬러그가 해시로 시작하는 두 번째
    # 유령 헤딩으로 만듦.
    hits = _anchor_issues(tmp_path, "## A\n---\n", "../srs/README.md#-a")
    assert len(hits) == 1


def test_existing_disk_target_wins_over_plan_content(tmp_path):
    # `apply_plan` 의 `create` 는 이미 있는 파일을 덮지 않음 — conflict 로 적고 둠. 플랜의
    # content 를 대상의 미래로 읽으면 conflict 난 파일의 앵커가 전부 죽었다고 나옴.
    # 브라운필드 /harness-init 재실행이 바로 그 모양임.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "srs.md").write_text("## Requirements Coverage\n", encoding="utf-8")
    plan = {
        "files": [
            _baseline_entry(),
            {
                "path": "docs/sds.md",
                "action": "create",
                "content": "[FR](srs.md#requirements-coverage)",
            },
            {"path": "docs/srs.md", "action": "create", "content": "## Something Else\n"},
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not [i for i in rep["issues"] if i["kind"] == "dead-anchor"]


def test_create_entry_without_content_key_is_not_authoritative(tmp_path):
    # `content` 없는 엔트리의 `.get("content", "")` 는 "" 이고, "" 는 무엇을 물어도
    # "앵커 없음" 이라 답함. 대상이 디스크에 **없어야** 함 — 있으면 디스크 갈래가 먼저
    # 답해 이 경계에 닿지 못함.
    plan = {
        "files": [
            _baseline_entry(),
            {"path": "docs/sds.md", "action": "create", "content": "[R](t.md#present)"},
            {"path": "docs/t.md", "action": "create"},
        ]
    }
    rep = hs.validate_plan(tmp_path, plan)
    assert not [i for i in rep["issues"] if i["kind"] == "dead-anchor"]


def test_slugify_keeps_a_generic_type_heading():
    # `<K,V>` 는 제대로 된 태그가 아니라 어느 렌더러도 지우지 않음 — GitHub 는 `mapkv` 를 냄.
    # 느슨한 `<[^>]+>` 제거는 `map` 을 내고 제네릭 헤딩 링크를 전부 죽었다고 부름.
    assert hs._slugify("Map<K,V>") == "mapkv"
    assert hs._slugify("Result<T, E>") == "resultt-e"
    assert hs._slugify("2 < 3 and 4 > 5") == "2--3-and-4--5"


def test_slugify_strips_a_real_html_tag():
    assert hs._slugify("<code>x</code> y") == "x-y"


def test_slugify_decodes_an_escaped_tag_without_eating_it():
    # `&lt;script&gt;` 는 **텍스트** `<script>` 로 렌더되고 그것을 구두점 제거가 지움 —
    # 낱말은 살아남음. 태그 제거보다 먼저 디코드하면 통째로 잃음.
    assert hs._slugify("&lt;script&gt; handling") == "script-handling"


def test_slugify_leaves_a_semicolonless_entity_alone():
    # CommonMark 는 세미콜론을 요구하지만 `html.unescape` 는 아님. `## Notes &amp` 는
    # GitHub 에서 `notes-amp` 로 앵커됨.
    assert hs._slugify("Notes &amp") == "notes-amp"
    assert hs._slugify("A &copy B") == "a-copy-b"


def test_explicit_anchor_inside_a_code_fence_is_not_an_anchor(tmp_path):
    body = '```html\n<a id="ghost"></a>\n```\n'
    hits = _anchor_issues(tmp_path, body, "../srs/README.md#ghost")
    assert len(hits) == 1


def test_slugify_drops_an_html_comment():
    # `srs.template.md` 는 뒤에 `<!-- ... -->` 가 붙은 헤딩을 싣고 나감.
    assert hs._slugify("A <!-- x --> B") == "a--b"


def test_percent_encoded_fragment_resolves_an_explicit_anchor(tmp_path):
    link = "../srs/README.md#%EC%9A%94%EA%B5%AC"
    assert _anchor_issues(tmp_path, '<a id="요구"></a>\n', link) == []


def test_a_long_whitespace_run_in_a_heading_stays_linear():
    # `\s*#*\s*$` 가 공백 런 하나를 두 갈래로 가르는 동안 lazy `(.+?)` 가 그 위로 다시
    # 자랐음 — 세제곱, 이 입력에 18초. **회귀를 잡는 것은 벽시계 단언 쪽**: 옛 패턴도
    # 같은 모양을 내놓고(82초 뒤) 시간만 다름. 실측 여유가 10만배(0.01ms 대 상한 1s)라
    # 흔들리지 않으므로 지우지 말 것. 모양 단언은 캡처가 줄 끝까지 간다는 특성화.
    import time

    start = time.perf_counter()
    assert hs._HEADING_RE.findall("## H" + " " * 4000 + ".") == ["H" + " " * 4000 + "."]
    assert time.perf_counter() - start < 1.0


def test_a_closing_hash_run_still_comes_off(tmp_path):
    assert _anchor_issues(tmp_path, "## Title ##\n", "../srs/README.md#title") == []


def test_a_backslash_absolute_link_is_never_read(tmp_path):
    # Windows 에서 드라이브 루트에 걸림: `Path(rel).parent / link` 가 왼쪽을 버려 target 이
    # `/Users/...` 로 정규화됨 — root 밖인데 `..` 로 시작하지 않음.
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret Heading\n", encoding="utf-8")
    # 떨어지는 것은 드라이브 문자이지 경로가 아님: `\Users\…\outside.md` 는 드라이브
    # 루트에 다시 걸려 진짜 파일에 닿음. 맨 basename 이면 안 닿고, 가드를 지워도 통과함.
    if ":" not in str(outside):
        pytest.skip("드라이브에 걸리는 경로는 Windows 모양")
    link = "\\" + str(outside).split(":", 1)[-1].lstrip("\\/")
    entry = {
        "path": ".claude/rules/x-conventions.md",
        "action": "create",
        # 그 바깥 파일에 **없는** 프래그먼트. 있는 것을 물으면 어느 쪽이든 통과함 —
        # 가드가 걸렀거나, 가드가 닫아 두려던 그 파일을 읽어 찾았거나.
        "content": f"[x]({link}#not-in-that-file)\n",
    }
    rep = hs.validate_plan(tmp_path / "root", {"files": [_baseline_entry(), entry]})
    assert not [i for i in rep["issues"] if i["kind"] in ("dead-link", "dead-anchor")]


def test_one_target_is_read_once_however_many_links_point_at_it(tmp_path):
    (tmp_path / "docs" / "srs").mkdir(parents=True)
    (tmp_path / "docs" / "srs" / "README.md").write_text("# FR 001\n", encoding="utf-8")
    reads = []
    original = hs.Path.read_text

    def counting(self, *a, **kw):
        reads.append(str(self))
        return original(self, *a, **kw)

    hs.Path.read_text = counting
    try:
        body = "".join(f"[a{i}](../../docs/srs/README.md#fr-001)\n" for i in range(5))
        hs.validate_plan(tmp_path, {"files": [_baseline_entry(), _conv_entry(body)]})
    finally:
        hs.Path.read_text = original
    assert len([r for r in reads if r.endswith("README.md")]) == 1


def test_a_data_id_attribute_is_still_not_an_anchor(tmp_path):
    hits = _anchor_issues(tmp_path, '<a data-id="ghost"></a>\n', "../srs/README.md#ghost")
    assert len(hits) == 1


def test_a_crlf_setext_heading_still_resolves():
    # `[ \t]*$` 는 `===\r\n` 의 `\r` 을 못 넘음 — 옛 `\s*$` 는 넘겼음. 디스크 경로는
    # `read_text` 가 개행을 정규화해 안전하지만 플랜 `content` 는 날것으로 들어오므로,
    # CRLF 로 쓴 setext 헤딩을 가리키는 링크가 허위 dead-anchor 로 보고됨(Invariant 2).
    assert hs._SETEXT_RE.findall("T\r\n===\r\n") == ["T\r"]
    assert hs._has_anchor("My Title\r\n========\r\n", "my-title")
    # 빈 줄 판정 쪽 `\r?`. 위 두 단언은 그것 없이도 통과하므로, 빠지면 CRLF 빈 줄이
    # 빈 슬러그의 유령 제목이 되어 뒤따르는 같은 슬러그의 `-1` 번호를 밀어냄.
    assert hs._SETEXT_RE.findall("\r\n===\r\n") == []


def test_a_drive_relative_link_is_never_read(tmp_path):
    # 콜론 뒤에 구분자가 없는 링크(`C:../../outside.md`)는 `Path(rel).parent / link` 가 통째로
    # 남기고, 같은 드라이브의 `root / target` 이 root 밑에 이어 붙여 `..` 가 진짜 파일로 기어오름.
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret Heading\n", encoding="utf-8")
    drive = str(tmp_path).split(":", 1)[0]
    if len(drive) != 1:
        pytest.skip("드라이브-상대 경로는 Windows 모양")
    # 바깥 파일에 **없는** 프래그먼트 — 읽으면 dead 로 보고됨.
    entry = _conv_entry(f"[x]({drive}:../../outside.md#not-in-that-file)\n")
    rep = hs.validate_plan(tmp_path / "a" / "root", {"files": [_baseline_entry(), entry]})
    assert not [i for i in rep["issues"] if i["kind"] in ("dead-link", "dead-anchor")]


@pytest.mark.parametrize("link", ["C:x.md", "c:docs/x.md", "D:../x.md"])
def test_any_drive_prefix_reads_as_outside_root(link):
    assert hs._DRIVE_PREFIX_RE.match(link)
