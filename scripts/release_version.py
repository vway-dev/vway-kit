"""릴리스 워크플로의 다음 버전 — `Release-Level:` 트레일러와 태그 목록으로 정함.

렌더된 release 템플릿 다섯(`github/release.*`)이 호스트 사본을 부름. 템플릿마다 셸로 같은
계산을 두면 한 곳만 고쳐도 도구마다 같은 트레일러가 다른 버전을 냄 — 규칙은 여기 한 곳.
자매 저장소 harness-tier 의 `bump_version.py` 가 상류.

- `next`: prerelease push 의 rc. 대기 rc 가 있으면 `continue` = `rc.N+1`, patch/minor/major =
  그 base 를 올린 `rc.1`. 없으면 마지막 정식 태그 기준 `rc.1`. 트레일러 없음·`auto` → `auto`.
  `--auto-level <level>` 이면 그 경우도 rc 를 냄 — 대기 rc 가 있으면 `continue`, 없으면 그 레벨.
  커밋 타입으로 레벨을 못 정하는 도구(PSR 외 넷)가 트레일러 없는 staging push 에서도 rc 를 내게.
  낼 rc 태그가 이미 있으면 실패 — 중복 태그.
- `stable`: 도달 가능한 rc 가 없는 stable push(hotfix)의 정식 버전. patch/minor/major 만 받고,
  트레일러 없으면 `--default` 레벨, 그것도 없으면 `auto`.
- `finalize --rc vX.Y.Z-rc.N`: 머지된 rc 의 정식 `X.Y.Z`. 그 태그가 이미 있거나 최신 정식보다
  낮으면 실패 — hotfix 가 같은 base 나 더 높은 base 를 먼저 냈다는 뜻이고, 그대로 가면 중복
  태그나 하향 릴리스가 됨. 해법은 staging 을 patch 이상으로 재승격.
- `state`: 대기 rc 와 레벨마다 `next` 가 낼 버전 — `/release-commit` 의 선택지 라벨.
  `--tags` 없이 `git tag --list` 를 스스로 읽음: 인자 없는 형태만 `allowed-tools` 로
  사전승인할 수 있음(`$(git tag --list)` 인자는 규칙에 안 맞음).

대기 rc = 같은 base 의 정식 태그가 없고 base 가 마지막 정식 태그보다 큰 최고 `X.Y.Z-rc.N`.
도달 가능성이 아니라 태그 목록으로 봄 — staging back-merge 가 FF 거부로 skip 된 브랜치에서도
이미 정식화된 rc 를 대기로 읽지 않고, 정식보다 낮아진 rc 는 버려진 시리즈로 봄.

쓸 수 없는 입력(어휘 밖·트레일러 충돌·대기 rc 없는 `continue`·stable 의 `continue`·정식화할
수 없는 rc)은 exit 2 + stderr 사유 — skip·auto 로 떨어지면 승격이 끝난 것처럼 보이고 rc 는 없음.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import TYPE_CHECKING

try:
    from _vway_paths import force_utf8_io
except ImportError:
    from scripts._vway_paths import force_utf8_io

LEVELS = ("auto", "continue", "patch", "minor", "major")
# git 은 트레일러 키를 대소문자 구분 없이 읽음 — `release-level: minor` 도 강제 레벨.
_TRAILER = re.compile(r"^Release-Level[ \t]*:(.*)$", re.MULTILINE | re.IGNORECASE)
_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z]+)\.(\d+))?$")

# 주석 전용 별칭 — 모듈 최상위 `tuple[...]` 는 import 때 평가되어 python 3.8 호스트에서 TypeError.
if TYPE_CHECKING:
    Core = tuple[int, int, int]


def parse_level(message: str) -> str:
    """커밋 메시지의 트레일러 값, 없으면 `auto`. 어휘 밖·빈 값·서로 다른 둘은 ValueError."""
    values = {v.strip() for v in _TRAILER.findall(message)}
    if not values:
        return "auto"
    if len(values) > 1:
        raise ValueError(f"Release-Level 트레일러가 서로 다름: {sorted(values)}")
    (value,) = values
    if value not in LEVELS:
        raise ValueError(f"Release-Level {value!r} 은 {'|'.join(LEVELS)} 가 아님")
    return value


def _parse_tags(tags: list[str], token: str) -> tuple[set[Core], list[tuple[Core, int]]]:
    stable: set[Core] = set()
    rcs: list[tuple[Core, int]] = []
    for t in tags:
        m = _TAG.match(t.strip())
        if not m:
            continue
        core = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m.group(4) is None:
            stable.add(core)
        elif m.group(4) == token:
            rcs.append((core, int(m.group(5))))
    return stable, rcs


def _fmt(core: Core) -> str:
    return ".".join(str(x) for x in core)


def _bump(core: Core, level: str) -> Core:
    major, minor, patch = core
    if level == "major":
        return (major + 1, 0, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def last_stable(tags: list[str]) -> Core:
    stable, _ = _parse_tags(tags, "rc")
    return max(stable) if stable else (0, 0, 0)


def pending_rc(tags: list[str], token: str = "rc") -> tuple[Core, int] | None:
    stable, rcs = _parse_tags(tags, token)
    floor = max(stable) if stable else (0, 0, 0)
    open_rcs = [rc for rc in rcs if rc[0] not in stable and rc[0] > floor]
    return max(open_rcs) if open_rcs else None


def next_version(
    message: str, tags: list[str], token: str = "rc", auto_level: str | None = None
) -> str:
    """prerelease push 의 다음 rc, 레벨을 도구에 맡기면 `auto`."""
    level = parse_level(message)
    pending = pending_rc(tags, token)
    if level == "auto":
        if auto_level is None:
            return "auto"
        level = "continue" if pending else auto_level
    if level == "continue":
        if pending is None:
            raise ValueError("Release-Level continue — 이어 갈 대기 rc 가 없음")
        core, n = pending
    else:
        core, n = _bump(pending[0] if pending else last_stable(tags), level), 0
    if (core, n + 1) in _parse_tags(tags, token)[1]:
        raise ValueError(f"v{_fmt(core)}-{token}.{n + 1} 이 이미 있음 — 중복 태그")
    return f"{_fmt(core)}-{token}.{n + 1}"


def stable_version(message: str, tags: list[str], default: str | None = None) -> str:
    """도달 가능한 rc 가 없는 stable push 의 정식 버전, 레벨을 도구에 맡기면 `auto`."""
    level = parse_level(message)
    if level == "auto":
        if default is None:
            return "auto"
        level = default
    if level == "continue":
        raise ValueError("Release-Level continue 는 prerelease 전용 — stable 은 rc 를 finalize")
    return _fmt(_bump(last_stable(tags), level))


def finalize_version(rc_tag: str, tags: list[str]) -> str:
    """머지된 rc 의 정식 버전. 이미 있거나 최신 정식보다 낮으면 ValueError."""
    m = _TAG.match(rc_tag.strip())
    if not m or m.group(4) is None:
        raise ValueError(f"{rc_tag!r} 은 rc 태그가 아님")
    core = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    stable, _ = _parse_tags(tags, "rc")
    hint = "staging 을 Release-Level: patch 이상으로 재승격한 뒤 릴리스할 것"
    if core in stable:
        raise ValueError(f"v{_fmt(core)} 이 이미 있음 — hotfix 가 이 base 를 먼저 냄. {hint}")
    if stable and core < max(stable):
        raise ValueError(
            f"v{_fmt(core)} 은 최신 정식 v{_fmt(max(stable))} 보다 낮음 — 하향 릴리스. {hint}"
        )
    return _fmt(core)


def state(tags: list[str], token: str = "rc") -> list[str]:
    """대기 rc 한 줄, 이어서 레벨마다 `next` 가 낼 버전(또는 실패 사유)."""
    pending = pending_rc(tags, token)
    lines = [f"pending: v{_fmt(pending[0])}-{token}.{pending[1]}" if pending else "pending: none"]
    for level in ("continue", "patch", "minor", "major"):
        try:
            lines.append(f"{level}: v{next_version(f'Release-Level: {level}', tags, token)}")
        except ValueError as e:
            lines.append(f"{level}: 불가 — {e}")
    return lines


def git_tags() -> list[str]:
    """`git tag --list` — `changelog_section.py` 도 이것을 씀."""
    r = subprocess.run(
        ["git", "tag", "--list"], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or f"git tag --list exit {r.returncode}")
    return r.stdout.splitlines()


def main(argv: list[str]) -> int:
    force_utf8_io()
    parser = argparse.ArgumentParser(prog="release_version")
    sub = parser.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("next")
    n.add_argument("--message", required=True)
    n.add_argument("--tags", required=True)
    n.add_argument("--auto-level", choices=["patch", "minor", "major"], default=None)
    s = sub.add_parser("stable")
    s.add_argument("--message", required=True)
    s.add_argument("--tags", required=True)
    s.add_argument("--default", choices=["patch", "minor", "major"], default=None)
    f = sub.add_parser("finalize")
    f.add_argument("--rc", required=True)
    f.add_argument("--tags", required=True)
    st = sub.add_parser("state")
    st.add_argument("--tags", default=None, help="줄 단위 태그 목록 — 없으면 git tag --list")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "state":
            tags = args.tags.splitlines() if args.tags is not None else git_tags()
            print("\n".join(state(tags)))
            return 0
        if args.cmd == "next":
            version = next_version(args.message, args.tags.splitlines(), auto_level=args.auto_level)
        elif args.cmd == "stable":
            version = stable_version(args.message, args.tags.splitlines(), args.default)
        else:
            version = finalize_version(args.rc, args.tags.splitlines())
    except (ValueError, OSError) as e:
        print(f"release_version: {e}", file=sys.stderr)
        return 2
    print(version)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
