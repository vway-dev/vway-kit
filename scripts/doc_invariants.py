#!/usr/bin/env python3
"""문서 재작성이 내용을 흘렸는지 기계로 대조(읽기 전용).

**왜 있는가**: 문서를 다시 쓰는 주체는 LLM — `doc-sync` Mode A/B 의 조화 편집,
`harness-init` 의 렌즈 `replace_section`, 문체 전환. 그 편집은 링크 하나·코드펜스 하나·
frontmatter 한 줄을 조용히 지울 수 있고, 산문은 그래도 읽히므로 사람 눈에도 안 걸림.
문체 규율([doc-style.md](../rules/doc-style.md))은 "어떻게 쓰는가"만 보고, `wiki_graph
--verify` 는 wiki 노드의 front matter 구조만 봄 — **재작성 전후로 같은 사실이 남아
있는가**를 재는 것은 이 스크립트뿐임.

**무엇을 재는가**: 압축·조화는 문장을 줄이지 사실을 줄이지 않는다는 전제. 그래서 산문이
아니라 **셀 수 있는 것들의 다중집합**만 봄 — front matter 키·헤딩·링크/URL·인라인 코드·
코드펜스. 개수가 줄면 error, 순서가 바뀌거나 펜스 안 줄이 사라지면 warning.

**게이트가 아님**(FAIL-OPEN 계열): 커밋 훅에 물리지 않음. 문서를 정당하게 줄이는
편집(중복 삭제·SSOT 통합)은 이 검사에 반드시 걸리는데, 그건 위반이 아니라 의도.
판정은 사람이 하고, 이 도구는 "무엇이 사라졌는지"만 이름으로 댐.

사용:
    python3 doc_invariants.py --changed [경로...]   # HEAD blob ↔ 워킹트리
    python3 doc_invariants.py --pair BEFORE AFTER   # AFTER 가 `-` 면 stdin
    [--json]                                        # 기계 소비용

종료 코드: 0 = 손실 없음(warning 은 포함될 수 있음) · 1 = 손실 있음 · 2 = 사용 오류.
`--changed` 의 경로가 저장소의 .md 를 못 가리키는 것도 사용 오류 — stderr 에 그 경로를 댐.
추적 중인 .md 가 그대로면 오류가 아니라 `[=] 변경 없음`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:  # 직접 실행(형제 import) — 호스트 사본은 단일 파일로 놓임
    from _vway_paths import _git, force_utf8_io, host_root
except ImportError:  # 패키지 import(테스트/개발)
    from scripts._vway_paths import _git, force_utf8_io, host_root

# front matter 는 파일 맨 앞의 `---` 블록만. 본문 중간의 `---` 는 수평선이라 대상이 아님.
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
FRONTMATTER_KEY = re.compile(r"^([A-Za-z_][\w-]*):", re.M)

FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
# ATX 헤딩은 한 줄짜리. `re.M` 이 없으면 여러 줄 문서에서 **아무 헤딩도** 안 잡히고, 줄 안
# 공백을 `\s` 로 두면 개행을 넘어 다음 줄 문장을 제목으로 삼음 — 어느 쪽이든 헤딩 축과 순서
# 경고가 조용히 죽음(실측: 절을 통째로 지워도 손실 0건). 끝의 `\r` 은 CRLF 문서의 줄끝이지
# 제목 글자가 아님. 선두 들여쓰기는 안 받음 — CommonMark 는 3칸까지 헤딩으로 보지만 이
# 저장소엔 그런 헤딩이 없고(펜스 밖 실측 0건), 들여쓴 `#` 줄은 제목보다 주석일 때가 많음.
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t\r]*$", re.M)
# 마크다운 링크의 **목적지**만 — 표시 텍스트는 산문이라 바뀌어도 사실이 아님.
LINK_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
BARE_URL = re.compile(r"(?<![(\[<])\bhttps?://[^\s)<>\]]+")
# 한 줄 안에서만 짝을 맞춤. 접힘을 넘는 스팬은 정규식이 아니라 _unfold 가 처리 —
# 줄바꿈을 정규식에 허용하면 홀수 백틱 하나가 다음 항목의 문장 반쪽을 스팬으로 삼킴(실측).
INLINE_CODE = re.compile(r"`([^`\n]{1,200})`")
BULLET = re.compile(r"^\s*([-*+]|\d+[.)])\s+\S", re.M)


def frontmatter_keys(text: str) -> Counter:
    """맨 앞 블록의 **최상위** 키. 값은 안 봄 — 값 편집은 정당한 갱신.

    들여쓴 줄을 건너뛰므로 중첩 키(`alm.teamer` 등)는 세지 않음. 목적은 "블록째
    사라졌거나 키가 증발했는가"이고, 그건 최상위만으로 잡힘.
    """
    m = FRONTMATTER.match(text)
    if not m:
        return Counter()
    return Counter(FRONTMATTER_KEY.findall(m.group(1)))


def code_fences(text: str) -> list[str]:
    """펜스 블록의 **본문**(여는/닫는 줄 제외) 목록.

    CommonMark: 닫는 펜스는 같은 문자에 길이가 여는 것 이상이어야 하고 뒤에 info 가 붙지
    않음. 그 규칙을 지켜야 4-백틱으로 3-백틱을 감싼 블록(이 repo 의 스킬 문서가 실제로
    쓰는 모양)을 하나로 읽음. 닫히지 않은 펜스는 버림 — 깨진 마크다운이고, 세면 그 아래
    문서 전체가 한 블록으로 잡혀 오탐이 됨.
    """
    blocks: list[str] = []
    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        opened = FENCE.match(lines[i])
        if not opened:
            i += 1
            continue
        char, width = opened.group(2)[0], len(opened.group(2))
        body: list[str] = []
        i += 1
        closed = False
        while i < n:
            closer = FENCE.match(lines[i])
            if (
                closer
                and closer.group(2)[0] == char
                and len(closer.group(2)) >= width
                and not closer.group(3).strip()
            ):
                closed = True
                i += 1
                break
            body.append(lines[i])
            i += 1
        if closed:
            blocks.append("\n".join(body).strip())
    return blocks


def fence_lines(bodies: list[str]) -> Counter:
    """펜스 안의 비어 있지 않은 줄 다중집합.

    블록을 통째로 비교하면 블록 **안의 한 줄**을 고친 편집이 "블록 하나 사라짐"으로 읽힘
    (자기 문체 전환에서 8개 파일이 그렇게 잡힘 — 실측). 개수는 아래에서 따로 세고, 내용은
    줄 단위로 봐서 진짜 사라진 줄만 이름을 댐.
    """
    return Counter(line.strip() for body in bodies for line in body.split("\n") if line.strip())


def _outside_code(text: str) -> str:
    """펜스 블록을 걷어낸 본문. 펜스 안의 URL·헤딩·백틱은 예시이지 문서의 사실이 아님."""
    kept: list[str] = []
    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        opened = FENCE.match(lines[i])
        if not opened:
            kept.append(lines[i])
            i += 1
            continue
        char, width = opened.group(2)[0], len(opened.group(2))
        i += 1
        while i < n:
            closer = FENCE.match(lines[i])
            i += 1
            if (
                closer
                and closer.group(2)[0] == char
                and len(closer.group(2)) >= width
                and not closer.group(3).strip()
            ):
                break
    return "\n".join(kept)


BLOCK_START = re.compile(r"^(#{1,6}\s|>|\||[-*+]\s|\d+[.)]\s)")


def _unfold(body: str) -> str:
    """문단·항목의 이어지는 줄을 앞줄에 붙임(펜스를 걷어낸 본문 전용).

    재작성은 같은 문장을 다른 폭으로 접음. 접힘이 코드 스팬 한가운데를 지나가면 `` `a
    b` `` 가 두 줄에 걸치고, 줄 단위 추출은 멀쩡한 스팬을 "사라짐"으로 보고함. 새 블록을
    여는 줄(헤딩·인용·표·불릿·번호)만 경계로 삼고 나머지는 앞줄에 이음 — 헤딩 **뒤에는**
    잇지 않음(헤딩 텍스트가 다음 문장을 삼키면 그 헤딩이 사라진 것으로 읽힘).
    """
    out: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        prev = out[-1].strip() if out else ""
        continues = bool(stripped) and not BLOCK_START.match(stripped)
        after_prose = bool(prev) and not prev.startswith("#") and not prev.startswith("|")
        if out and continues and after_prose:
            out[-1] = out[-1].rstrip() + " " + stripped
        else:
            out.append(line)
    return "\n".join(out)


def headings(body: str) -> Counter:
    return Counter(f"{h} {t}" for h, t in HEADING.findall(body))


def links(body: str) -> Counter:
    """링크 목적지 + 맨몸 URL. 앵커 전용(`#절`)은 같은 문서 안의 이동이라 제외함."""
    targets = [t for t in LINK_TARGET.findall(body) if not t.startswith("#")]
    return Counter(targets) + Counter(BARE_URL.findall(body))


def inline_codes(body: str) -> Counter:
    """코드 스팬. 접힘 폭은 사실이 아니므로 내부 공백을 한 칸으로 정규화해 비교함."""
    # 개행 2개 이상이면 접힌 스팬이 아니라 짝 안 맞는 백틱이 세 줄을 삼킨 것
    # (실측: 홀수 백틱이 섞인 목록에서 문장 반쪽이 스팬으로 잡힘).
    spans = (s for s in INLINE_CODE.findall(body) if s.count("\n") <= 1)
    return Counter(" ".join(s.split()) for s in spans if s.strip())


# 검사 축: (이름, 추출기, 입력 준비). 전부 "줄었으면 손실".
# 코드펜스는 개수와 줄 내용을 나눠 보므로 이 표에 없음(compare 가 직접 다룸).
def _raw(text: str) -> str:
    return text


def _prose(text: str) -> str:
    return _outside_code(text)


def _folded(text: str) -> str:
    return _unfold(_outside_code(text))


AXES = (
    ("front matter 키", frontmatter_keys, _raw),
    ("헤딩", headings, _prose),
    ("링크/URL", links, _folded),
    ("인라인 코드", inline_codes, _folded),
)


def _sample(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(repr(x[:60]) for x in items[:limit])
    return shown + (f" 외 {len(items) - limit}건" if len(items) > limit else "")


def compare(before: str, after: str) -> tuple[list[str], list[str]]:
    """(errors, warnings). 손실만 error — 늘어난 것은 보강이라 보고하지 않음."""
    errors: list[str] = []
    warnings: list[str] = []
    for name, extract, prepare in AXES:
        dropped = list((extract(prepare(before)) - extract(prepare(after))).elements())
        if dropped:
            errors.append(f"{name} {len(dropped)}건 사라짐: {_sample(dropped)}")

    old_fences, new_fences = code_fences(before), code_fences(after)
    if len(new_fences) < len(old_fences):
        errors.append(
            f"코드펜스 {len(old_fences) - len(new_fences)}개 사라짐 "
            f"({len(old_fences)} → {len(new_fences)})"
        )
    lost_lines = list((fence_lines(old_fences) - fence_lines(new_fences)).elements())
    if lost_lines:
        warnings.append(f"펜스 안 {len(lost_lines)}줄 사라짐: {_sample(lost_lines, 3)}")

    old_h, new_h = headings(_outside_code(before)), headings(_outside_code(after))
    if old_h == new_h and _heading_order(before) != _heading_order(after):
        warnings.append("헤딩 순서 변경 — 문서 뼈대가 바뀜")
    old_b = len(BULLET.findall(_outside_code(before)))
    new_b = len(BULLET.findall(_outside_code(after)))
    if new_b < old_b:
        warnings.append(f"불릿 {old_b - new_b}개 감소 ({old_b} → {new_b}) — 항목 유실 여부 확인")
    return errors, warnings


def _heading_order(text: str) -> list[str]:
    return [f"{h} {t}" for h, t in HEADING.findall(_outside_code(text))]


def _read(path: str) -> str | None:
    """`-` 는 stdin. 읽기 실패는 None — 없는 파일은 비교가 아니라 보고 대상."""
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _changed_docs(root: Path, limit: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(HEAD 에 있던 .md, HEAD 에 없던 .md, 지목했지만 둘 어디에도 없는 경로). 둘째는 새
    파일이라 비교 대상이 없음."""
    # `-z` 는 취향이 아님 — 기본 `core.quotePath` 에서 비ASCII 경로는 C-인용돼 오고 공백 든
    # 경로는 개행 분할을 견디지만 그 인용을 못 벗음. 그러면 그 문서는 "읽을 수 없음" 으로
    # 넘어가거나 `limit` 대조에서 통째로 빠져, 재작성 손실 확인이 조용히 그 파일만 건너뜀.
    tracked = _git(["diff", "--name-only", "-z", "HEAD", "--", "*.md"], root)
    untracked = _git(["ls-files", "--others", "--exclude-standard", "-z", "--", "*.md"], root)
    changed = [p for p in (tracked or "").split("\0") if p]
    added = [p for p in (untracked or "").split("\0") if p]
    if not limit:
        return changed, added, []
    # `removeprefix` 이지 `lstrip` 이 아님 — 후자는 문자집합을 벗겨 `.claude/x.md` 를
    # `claude/x.md` 로 만들어, 있는 문서를 지목해도 빗나감(`as_posix()` 가 이미 `./` 를
    # 떨구므로 남는 일은 그 손상뿐).
    wanted = list(dict.fromkeys(Path(p).as_posix().removeprefix("./") for p in limit))
    listed = {*changed, *added}
    return (
        [p for p in changed if p in wanted],
        [p for p in added if p in wanted],
        [p for p in wanted if p not in listed],
    )


def check_changed(root: Path, limit: list[str]) -> dict:
    changed, added, unlisted = _changed_docs(root, limit)
    findings = []
    for rel in changed:
        before = _git(["show", f"HEAD:{rel}"], root)
        after = _read(str(root / rel))
        if before is None or after is None:
            findings.append({"path": rel, "skipped": "읽을 수 없음(삭제·이동·권한)"})
            continue
        errors, warnings = compare(before, after)
        findings.append({"path": rel, "errors": errors, "warnings": warnings})
    # 지목했는데 변경 목록에 없는 경로는 둘 중 하나. 추적 중인 .md 가 그대로면 잃은 것이 없다는
    # 답이고, 저장소의 .md 가 아니면(오타·대소문자·절대경로) 사용 오류 — 버리면 "변경된 .md
    # 없음" 에 exit 0 이라 손실이 있어도 초록. 대조는 git 목록과 문자열로: Windows 파일시스템은
    # 대소문자가 틀린 이름도 열어 줘, 그쪽으로 재면 틀린 지목이 통과함.
    listing = _git(["ls-files", "-z", "--", "*.md"], root) if unlisted else None
    known = {p for p in (listing or "").split("\0") if p}
    findings += [{"path": rel, "unchanged": True} for rel in unlisted if rel in known]
    unmatched = [rel for rel in unlisted if rel not in known]
    return {"findings": findings, "new_files": added, "unmatched": unmatched}


def _render(report: dict) -> int:
    """사람이 읽는 보고. 반환은 손실 줄 수 — 종료 코드는 `main` 이 정함."""
    lost = 0
    for item in report["findings"]:
        path = item["path"]
        if item.get("unchanged"):
            print(f"[=] {path} — 변경 없음(HEAD 와 같음)")
            continue
        if "skipped" in item:
            print(f"[-] {path} — {item['skipped']}")
            continue
        errors, warnings = item["errors"], item["warnings"]
        if not errors and not warnings:
            print(f"[=] {path} — 보존됨")
            continue
        mark = "[!]" if errors else "[~]"
        print(f"{mark} {path}")
        for line in errors:
            print(f"      손실: {line}")
            lost += 1
        for line in warnings:
            print(f"      경고: {line}")
    for path in report["new_files"]:
        print(f"[+] {path} — HEAD 에 없음(새 문서), 비교 대상 없음")
    if not report["findings"] and not report["new_files"] and not report.get("unmatched"):
        print("변경된 .md 없음")
    return lost


def main(argv: list[str] | None = None) -> int:
    force_utf8_io()
    parser = argparse.ArgumentParser(
        prog="doc_invariants.py", description="문서 재작성 전후 내용 보존 대조(읽기 전용)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--changed", action="store_true", help="HEAD blob ↔ 워킹트리 .md 대조")
    mode.add_argument(
        "--pair", nargs=2, metavar=("BEFORE", "AFTER"), help="두 파일 대조(`-`=stdin)"
    )
    parser.add_argument("paths", nargs="*", help="--changed 대상 축소(저장소 기준 상대경로)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args(argv)

    if args.pair:
        before, after = _read(args.pair[0]), _read(args.pair[1])
        if before is None or after is None:
            print("파일을 읽을 수 없습니다: " + " ".join(args.pair), file=sys.stderr)
            return 2
        errors, warnings = compare(before, after)
        report = {
            "findings": [{"path": args.pair[1], "errors": errors, "warnings": warnings}],
            "new_files": [],
        }
    else:
        report = check_changed(host_root(), args.paths)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        lost = any(f.get("errors") for f in report["findings"])
    else:
        lost = _render(report)
    unmatched = report.get("unmatched", [])
    for path in unmatched:
        print(f"[?] {path} — 저장소의 .md 가 아님(오타·대소문자·절대경로)", file=sys.stderr)
    if unmatched:
        return 2
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
