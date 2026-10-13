"""docs/srs 의 채번과 무결성 — 요구 텍스트의 SSOT.

자기 진입점인 이유는 사람이 손으로 고친 SRS 를 읽는 주체가 달리 없음 — `_has_anchor`
는 생성된 플랜을 보는 `validate_plan` 안에서만 돌고, `doc_invariants` 는 링크를 세기만
할 뿐 해석하지 않으며, `wiki_graph --verify` 는 front matter edge 만 봄. 증분 편집이
만드는 죽은 앵커에는 오늘 독자가 없음.

게이트 아님. docs/srs 부재는 exit 0 무출력, 모든 검사는 막지 않고 보고만 함 — 판정은
srs-verify 워크플로의 몫.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from _vway_paths import force_utf8_io
except ImportError:
    from scripts._vway_paths import force_utf8_io

try:
    from _md_anchors import _ANCHOR_ID_RE, _CODE_FENCE_RE, _HTML_COMMENT_RE, _has_anchor
except ImportError:
    from scripts._md_anchors import (
        _ANCHOR_ID_RE,
        _CODE_FENCE_RE,
        _HTML_COMMENT_RE,
        _has_anchor,
    )

SRS_REL = "docs/srs"
INDEX_STEM = "README"
_H1_RE = re.compile(r"^[ \t]{0,3}#[ \t]+(.+)$", re.MULTILINE)
_FRONT_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def srs_dir(root: Path) -> Path | None:
    d = root / SRS_REL
    return d if d.is_dir() else None


def _title(text: str) -> str:
    body = _FRONT_RE.sub("", text)
    m = _H1_RE.search(body)
    return m.group(1).strip() if m else ""


def area_files(root: Path) -> list[Path]:
    d = srs_dir(root)
    if d is None:
        return []
    return sorted(p for p in d.glob("*.md") if p.stem != INDEX_STEM)


def areas(root: Path) -> list[tuple[str, str]]:
    return [(p.stem, _title(p.read_text(encoding="utf-8"))) for p in area_files(root)]


def _strip_examples(text: str) -> str:
    """펜스 코드·HTML 주석 제거 — 저작 예시가 사는 자리.

    `_anchors`(정의)와 `_check_links`(이 파일 자신의 outgoing 링크)가 공유 — 같은
    주석 안의 예시 앵커와 예시 링크를 같은 방식으로 제외함. `_md_anchors._HTML_TAG_RE`
    는 재사용하지 않음 — 진짜 `<a>` 태그까지 벗겨내어 정의 스캔에 부적합.
    """
    return _HTML_COMMENT_RE.sub("", _CODE_FENCE_RE.sub("", text))


def _anchors(text: str) -> list[str]:
    """이 파일이 정의하는 앵커.

    `_has_anchor`(`_check_links` 안에서 링크의 TARGET 을 푸는 쪽)와 일부러 비대칭 —
    DESTINATION 파일의 주석 안에만 정의된 진짜 앵커도 유효한 링크 타깃으로 풀림.
    `_has_anchor` 는 주석을 벗기지 않고, 그쪽은 관대한 방향이 더 안전함. 이 파일
    자신의 정의와 자신의 outgoing 링크(`_strip_examples`)가 엄격한 쪽.
    """
    return [a.lower() for a in _ANCHOR_ID_RE.findall(_strip_examples(text))]


def _default_scope(path: Path) -> str | None:
    """영역 파일의 scope 는 자기 stem, 인덱스는 무scope.

    정하는 주체는 파일이지 kind 가 아님 — 그래서 KIND 집합이 열려 있음.
    """
    return None if path.stem == INDEX_STEM else path.stem


class ScopeRequired(Exception):
    """이 파일에서 `kind` 가 이미 축을 지니므로, 무scope 호출은 모호함."""


def _scope_established(text: str, kind: str) -> bool:
    """`text` 가 `kind` 를 bare 번호가 아니라 축 아래로 이미 앵커했으면 True.

    읽는 대상은 파일 자신의 앵커뿐, `kind` 자체는 절대 안 읽음 — 그래야 KIND 집합이
    열려 있음: scope 이력이 없는 kind 는 flat 하게 시작할 자유가 있음. `<a
    id="kind-axis">` 섹션 앵커는 그 아래 번호 붙은 항목이 하나도 없어도 그 자체로
    셈 — scaffold 만 되고 아직 빈 축인 상태가 정확히 그 모양.
    """
    prefix = f"{kind.lower()}-"
    return any(a.startswith(prefix) and not a[len(prefix) :].isdigit() for a in _anchors(text))


def next_id(path: Path, kind: str, scope: str | None = None) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if scope is None:
        scope = _default_scope(path)
    if scope is None and _scope_established(text, kind):
        raise ScopeRequired(f"{path}: existing {kind} anchors carry an axis — pass --scope")
    prefix = f"{kind}-{scope}-" if scope else f"{kind}-"
    pat = re.compile(rf"^{re.escape(prefix.lower())}(\d+)$")
    used = [int(m.group(1)) for a in _anchors(text) if (m := pat.match(a))]
    return f"{prefix.upper()}{max(used, default=0) + 1:03d}"


# 다른 SRS 문서로의 링크, 또는 이 파일 안의 bare fragment. 이미지(`![…]`)는 제외 —
# 앵커를 지니지 않음. target/fragment 뒤의 옵션 title(`"…"`)은
# `harness_scaffold._MD_LINK_RE` 와 거울상 — 없으면 title 붙은 링크가 아예 매치되지
# 않아 그 앵커가 검사에서 빠짐.
_LINK_RE = re.compile(
    r"(?<!!)\[[^\]]*\]\(\s*([^)\s#]*)(?:#([^)\s]*))?(?:\s+[\"'][^\")]*[\"'])?\s*\)"
)


def _files(root: Path, paths: list[Path] | None) -> list[Path]:
    d = srs_dir(root)
    if d is None:
        return []
    if paths:
        return [p for p in paths if p.is_file()]
    return sorted(d.glob("*.md"))


def _check_duplicates(texts: dict[Path, str]) -> list[str]:
    out, seen = [], {}
    for path, text in texts.items():
        local = set()
        for anchor in _anchors(text):
            if anchor in local:
                out.append(f"{path}: duplicate anchor '{anchor}' in this file")
            local.add(anchor)
            if anchor in seen and seen[anchor] != path:
                out.append(f"{path}: anchor '{anchor}' also defined in {seen[anchor]}")
            seen.setdefault(anchor, path)
    return out


def _check_prefix(path: Path, text: str) -> list[str]:
    """영역 파일의 id 는 자기 stem 을 지님. 인덱스의 id 는 영역을 전혀 지니지 않음."""
    if path.stem == INDEX_STEM:
        return []
    want = path.stem.lower()
    out = []
    for anchor in _anchors(text):
        parts = anchor.rsplit("-", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        head = parts[0]
        if "-" not in head or not head.split("-", 1)[1] == want:
            out.append(f"{path}: anchor '{anchor}' does not carry the area prefix '{want}'")
    return out


def _check_links(path: Path, text: str, texts: dict[Path, str]) -> list[str]:
    out = []
    for target, frag in _LINK_RE.findall(_strip_examples(text)):
        if not frag or target.startswith(("http://", "https://", "/", "\\")):
            continue
        # resolve 된 경로로 키잉 — 이 파일 자신도 포함. bare `#frag` 는 자기 자신을
        # 가리킴.
        dest = path.resolve() if not target else (path.parent / target).resolve()
        body = texts.get(dest)
        if body is None:
            continue  # docs/srs 밖 — 다른 검사기의 몫
        if not _has_anchor(body, frag):
            shown = f"{target}#{frag}" if target else f"#{frag}"
            out.append(f"{path}: dead link '{shown}'")
    return out


def verify(root: Path, paths: list[Path] | None = None) -> list[str]:
    report_files = _files(root, paths)
    if not report_files:
        return []
    # 링크 타깃은 `paths` 가 보고 범위를 좁혀도 디렉터리 전체를 대상으로 resolve —
    # 아니면 이 호출이 묻지 않은 타깃이 "docs/srs 밖"으로 읽혀 그리로 가는 죽은
    # 링크가 조용히 검사를 빠져나감. 중복·접두 검사는 좁힌 채로 둠 — 이 호출이 이름을
    # 대지 않은 두 파일 사이에만 사는 결함은 이 호출의 일이 아님.
    link_files = _files(root, None)
    texts = {p.resolve(): p.read_text(encoding="utf-8") for p in {*link_files, *report_files}}
    report_texts = {p: texts[p.resolve()] for p in report_files}
    out = _check_duplicates(report_texts)
    for path, body in report_texts.items():
        out += _check_prefix(path, body)
        out += _check_links(path, body, texts)
    return out


def main(argv: list[str] | None = None) -> int:
    force_utf8_io()
    parser = argparse.ArgumentParser(description="docs/srs numbering and integrity")
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--next-id", metavar="FILE", help="issue the next id for --kind")
    parser.add_argument("--kind", help="id kind (FR, C, NFR, CON, ROLE, …) — an open set")
    parser.add_argument("--scope", help="counter scope within the file (an NFR axis stem)")
    parser.add_argument("--areas", action="store_true", help="list area stem and title")
    parser.add_argument(
        "--verify",
        nargs="*",
        metavar="PATH",
        default=None,
        help="check anchors and links under docs/srs (default: all of them)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.next_id:
        if not args.kind:
            parser.error("--next-id requires --kind")
        try:
            got = next_id(Path(args.next_id), args.kind, args.scope)
        except ScopeRequired as exc:
            parser.error(str(exc))
        if got:
            print(got)
        return 0
    if args.areas:
        for stem, title in areas(root):
            print(f"{stem}\t{title}")
    if args.verify is not None:
        problems = verify(root, [Path(p) for p in args.verify] or None)
        for line in problems:
            print(line, file=sys.stderr)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
