"""CHANGELOG.md 의 릴리스 절을 버전 제목으로 읽고 다시 씀.

절 = 버전으로 시작하는 `# `·`## ` 제목과 다음 제목 직전까지. PSR 의 `## v1.2.0 (date)`,
Node 의 `# [1.2.0](compare-url) (date)`(minor·major)와 `## [1.2.1](…)`(patch)를 모두 받음.
버전이 없는 제목(파일 표제 포함)은 절이 아님. `vX.Y.Z-<token>.N` 은 프리릴리스, 그 밖의
접미사는 어느 쪽도 아님.

- `pending`: `since: v<마지막 정식 태그>` 한 줄과, 정식 릴리스가 접어 넣을 rc 절들(base 가
  마지막 정식보다 위인 rc 절 전부).
- `fold`: 그 rc 절들을 지우고 주어진 본문으로 `## vX.Y.Z (date)` 절 하나를 릴리스 목록 맨
  위(PSR 이 새 절을 넣는 자리)에 씀 — 이후로도 PSR 이 같은 파일을 이어 갱신함.
- `extract`: 정식 절의 본문. 릴리스 워크플로가 GitHub Release 본문으로 실음. 없으면 exit 1.

태그는 `--tags` 가 없으면 `git tag --list` 를 스스로 읽음.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from _vway_paths import force_utf8_io
    from release_version import git_tags, last_stable
except ImportError:
    from scripts._vway_paths import force_utf8_io
    from scripts.release_version import git_tags, last_stable

# 주석 전용 별칭 — 3.8 호스트 import 를 지키는 이유는 release_version.py 의 같은 줄.
if TYPE_CHECKING:
    Core = tuple[int, int, int]

_HEADING = re.compile(r"^#{1,2} \[?v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z]+)\.(\d+))?(?![-.\w])")
_OPENS = re.compile(r"(?m)^(?=#{1,2} \[?v?\d+\.\d+\.\d+)")
_ANY_HEADING = re.compile(r"(?m)^#{1,2} ")
# 머지 충돌 표시 — 열린 승격 머지에서 도는 단계라 CHANGELOG 가 충돌한 채일 수 있음. 그대로
# 접으면 표시 절반만 지워진 파일이 승격 커밋에 실림(`=======` 는 Setext 제목과 겹쳐 제외).
_CONFLICT = re.compile(r"(?m)^(<<<<<<< |>>>>>>> )")
_NEW_FILE = "# CHANGELOG\n\n<!-- version list -->\n\n"


def _split(text: str) -> tuple[str, list[str]]:
    """머리말과 버전 절들 — 절은 글자 그대로 보존."""
    parts = _OPENS.split(text)
    if parts and not _HEADING.match(parts[0]):
        return parts[0], parts[1:]
    return "", parts


def _version(section: str) -> tuple[Core, str | None] | None:
    m = _HEADING.match(section)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4)


def _is_pending(section: str, top: Core, token: str) -> bool:
    v = _version(section)
    return bool(v) and v[1] == token and v[0] > top


def pending_sections(text: str, tags: list[str], token: str = "rc") -> list[str]:
    """base 가 마지막 정식 태그보다 위인 `token` 절들 — 파일 순서."""
    top = last_stable(tags)
    return [s for s in _split(text)[1] if _is_pending(s, top, token)]


def _stable_section(text: str, version: str) -> str | None:
    core = tuple(int(x) for x in version.split("."))
    for section in _split(text)[1]:
        if _version(section) == (core, None):
            return section
    return None


def extract(text: str, version: str) -> str | None:
    """정식 `version` 절의 본문, 없거나 비면 None."""
    section = _stable_section(text, version)
    if section is None:
        return None
    body = section.split("\n", 1)[1].strip() if "\n" in section else ""
    return body or None


def fold(text: str, version: str, body: str, tags: list[str], date: str, token: str = "rc") -> str:
    """대기 중인 `token` 절들을 `body` 를 담은 정식 `version` 절 하나로 바꿈."""
    if _CONFLICT.search(text):
        raise ValueError("CHANGELOG 에 머지 충돌 표시가 있음 — 먼저 해소할 것")
    if not body.strip():
        raise ValueError("릴리스 노트 본문이 비었음")
    if _ANY_HEADING.search(body):
        raise ValueError("본문에 `#`·`##` 제목이 있음 — 거기서 절이 끝나 버림")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"--version {version!r} 은 맨 `X.Y.Z` 가 아님")
    top = last_stable(tags)
    if tuple(int(x) for x in version.split(".")) <= top:
        raise ValueError(f"v{version} 은 마지막 정식 태그 v{'.'.join(str(x) for x in top)} 이하임")
    if _stable_section(text, version) is not None:
        raise ValueError(f"CHANGELOG 에 v{version} 절이 이미 있음")
    preamble, sections = _split(text or _NEW_FILE)
    kept = [s for s in sections if not _is_pending(s, top, token)]
    new = f"## v{version} ({date})\n\n{body.strip()}\n"
    if kept:
        new += "\n\n"
    return preamble + new + "".join(kept)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="changelog_section")
    parser.add_argument("--file", default="CHANGELOG.md")
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--version", required=True)
    p = sub.add_parser("pending")
    p.add_argument("--tags", default=None)
    f = sub.add_parser("fold")
    f.add_argument("--version", required=True)
    f.add_argument("--body-file", required=True)
    f.add_argument("--tags", default=None)
    f.add_argument("--date", default=None)
    args = parser.parse_args(argv)

    # 한글 CHANGELOG 줄·실패 사유가 cp949 에서 죽지 않도록(CLAUDE.md Invariant 2 의 SSOT).
    force_utf8_io()

    path = Path(args.file)
    try:
        raw = path.read_bytes().decode("utf-8") if path.exists() else ""
    except (OSError, UnicodeDecodeError) as e:
        if args.cmd == "extract":
            return 1
        print(f"changelog_section: {e}", file=sys.stderr)
        return 2
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")

    if args.cmd == "extract":
        body = extract(text, args.version)
        if body is None:
            return 1
        print(body)
        return 0

    try:
        tags = args.tags.splitlines() if args.tags is not None else git_tags()
        if args.cmd == "pending":
            print(f"since: v{'.'.join(str(x) for x in last_stable(tags))}")
            for section in pending_sections(text, tags):
                print(section.rstrip("\n") + "\n")
            return 0
        body = Path(args.body_file).read_bytes().decode("utf-8").replace("\r\n", "\n")
        out = fold(text, args.version, body, tags, args.date or datetime.date.today().isoformat())
    except (OSError, ValueError) as e:
        print(f"changelog_section: {e}", file=sys.stderr)
        return 2
    path.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
