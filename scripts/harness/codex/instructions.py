"""호스트의 Claude Code 지침을 루트 AGENTS.md 의 관리 블록 하나로 렌더.

- Codex 는 AGENTS.md 를 세션 디렉터리와 그 조상에서만 읽음 — `.claude/rules/`·하위 디렉터리의
  CLAUDE.md 는 안 읽음. 그래서 루트 파일이 룰을 싣고 나머지는 가리킴.
- Claude Code 는 루트 CLAUDE.md 가 없을 때만 AGENTS.md 를 직접 읽음 — 그때 렌더된 룰이
  `.claude/rules/` 와 겹치는 것은 수용.
- 호스트에서 돌므로 게이트의 Python 하한(3.8)을 지킴. 호스트 사본은 `harness/`·`_vway_paths.py`
  와 함께 내려앉음(`vdev_init_setup.HARNESS_COPY_FILES`).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TARGET = "AGENTS.md"
# harness.instructions.ROOT_FILES 를 `_shared_source` 용으로 다시 적음(둘은 테스트가 고정).
ROOT_SOURCES = ("CLAUDE.md", ".claude/CLAUDE.md")
OVERRIDE = "AGENTS.override.md"
_TAG = "<!-- vway-kit:codex-instructions"
# 표식을 인용한 원본은 눈에 보이는 이스케이프를 받음 — 블록이 표식 줄을 품지 않게.
_TAG_ESCAPED = "<!- - vway-kit:codex-instructions"
_BEGIN_PREFIX = f"{_TAG} BEGIN"
BEGIN = f"{_BEGIN_PREFIX} — generated; edit CLAUDE.md or .claude/rules -->"
END = f"{_TAG} END -->"
# Codex 의 기본 `project_doc_max_bytes` — 넘치면 말없이 잘림.
MAX_BYTES = 32768


class MissingModule(Exception):
    """렌더러가 import 하는 모듈이 이 Python 에 없음."""


def _import(sibling: str, packaged: str):
    """호스트 사본이 보는 `sibling`, 아니면 저장소 안의 패키지 경로.

    - 그 둘이 import 하는 모듈 자체가 없으면(PyYAML) 폴백의 실패 대신 그 이름을 댐.
    """
    import importlib

    def own(name: str | None, path: str) -> bool:
        return name is not None and (path == name or path.startswith(name + "."))

    try:
        return importlib.import_module(sibling)
    except ModuleNotFoundError as exc:
        if not own(exc.name, sibling):
            raise MissingModule(exc.name) from exc
    try:
        return importlib.import_module(packaged)
    except ModuleNotFoundError as exc:
        if not own(exc.name, packaged):
            raise MissingModule(exc.name) from exc
        raise


def _missing(exc: MissingModule) -> str:
    name = "PyYAML" if exc.args[0] == "yaml" else exc.args[0]
    return f"{name} 가 이 python3 에 없습니다 — 설치한 뒤 다시 실행하세요"


def _model():
    return _import("harness.instructions", "scripts.harness.instructions")


def _collect(host: Path, keep: set, found=None):
    model = _model()
    try:
        return model.collect(host, keep_imports=keep, found=found)
    except ModuleNotFoundError as exc:
        raise MissingModule(exc.name) from exc


def _sources(host: Path):
    """Claude 원본 전부의 (kind, path) — 아무것도 읽거나 파싱하지 않고 나열."""
    return _model().sources(host.resolve())


def _source_rels(host: Path, found) -> list[str]:
    root = host.resolve()
    return [path.relative_to(root).as_posix() for _, path in found]


def _rule_index(doc) -> str:
    if doc.paths:
        return f"Before editing files matching `{', '.join(doc.paths)}`, read `{doc.source}`."
    return f"Before editing any file, read `{doc.source}`."


def _rule_section(doc) -> str:
    applies = ", ".join(doc.paths) if doc.paths else "all files"
    head = f"### Rule: {doc.source}\nApplies to: {applies}"
    body = doc.body.strip("\n")
    return f"{head}\n\n{body}" if body else head


def _block(docs, rule_bodies: bool) -> str:
    rules = [d for d in docs if d.kind == "rule"]
    modules = [d for d in docs if d.kind == "module"]
    sections = [d.body.strip("\n") for d in docs if d.kind == "root"]
    if rule_bodies:
        sections.extend(_rule_section(d) for d in rules)
    elif rules:
        sections.append("### Rules\n" + "\n".join(_rule_index(d) for d in rules))
    if modules:
        lines = [f"Before working under `{d.scope_dir}/`, read `{d.source}`." for d in modules]
        sections.append("### Directory instructions\n" + "\n".join(lines))
    inner = "\n\n".join(s for s in sections if s).replace(_TAG, _TAG_ESCAPED)
    return "\n".join([BEGIN, inner, END])


def _spans(text: str) -> list[tuple[int, int]]:
    """관리 블록 전부(END 의 줄바꿈 포함), 파일 순서대로.

    - BEGIN 줄은 전체 문구가 아니라 `_BEGIN_PREFIX` 로 알아봄 — 예전 문구로 쓰인 블록도 찾아
      바꾸고, 새 블록 옆에 고아로 남기지 않음.
    """
    pos, start, found = 0, None, []
    for line in text.split("\n"):
        nxt = min(pos + len(line) + 1, len(text))
        bare = line[:-1] if line.endswith("\r") else line
        if start is None and bare.startswith(_BEGIN_PREFIX):
            start = pos
        elif start is not None and bare == END:
            found.append((start, nxt))
            start = None
        pos = nxt
    if start is not None:
        raise ValueError(f"{TARGET} 에 Codex 지침 블록의 END 표식이 없습니다")
    return found


def _without(text: str, span: tuple[int, int], nl: str) -> str:
    before, after = text[: span[0]], text[span[1] :]
    if not after and before.endswith(nl * 2):
        before = before[: -len(nl)]
    return before + after


def _compose(existing: str, block: str | None) -> str:
    """`existing` 의 첫 블록을 바꾸거나(없으면 끝에 붙임) 나머지 블록은 버림.

    - `block` 이 None 이면 블록을 전부 버림.
    - 뒤에서부터 버려 블록마다 앞의 빈 줄이 함께 빠짐.
    """
    nl = "\r\n" if "\r\n" in existing else "\n"
    spans = _spans(existing)
    for span in reversed(spans if block is None else spans[1:]):
        existing = _without(existing, span, nl)
    if block is None:
        return existing
    rendered = block.replace("\n", nl) + nl
    if spans:
        return existing[: spans[0][0]] + rendered + existing[spans[0][1] :]
    if not existing:
        return rendered
    return existing + (nl if existing.endswith("\n") else nl * 2) + rendered


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _collect_docs(host: Path, found):
    """`found` 의 Claude 원본 전부를 파싱 — 읽거나 디코딩하지 못한 원본은 여기서 raise 해
    호출부의 단일 오류 경계로 감."""
    return _collect(host, {host / TARGET}, found)


def _plan(host: Path, docs) -> tuple[str | None, str | None, list[str]]:
    """(현재 텍스트, 원하는 텍스트, 안내) — 텍스트 None 은 파일 없음. `docs` 는
    `_collect_docs(host, found)`."""
    path = host / TARGET
    current = path.read_bytes().decode("utf-8") if path.is_file() else None
    if not docs:
        if current is None or not _spans(current):
            return current, current, []
        desired = _compose(current, None)
        return current, (desired if desired.strip() else None), []
    desired = _compose(current or "", _block(docs, rule_bodies=True))
    if _size(desired) > MAX_BYTES:
        desired = _compose(current or "", _block(docs, rule_bodies=False))
    notes = []
    if _size(desired) > MAX_BYTES:
        notes.append(
            f"  [!] {TARGET} 가 {_size(desired)} bytes 로 Codex 한도 {MAX_BYTES} bytes 를 넘습니다"
            " — 넘친 부분은 Codex 가 읽지 않으니 CLAUDE.md 를 줄이세요"
        )
    if (host / OVERRIDE).is_file():
        notes.append(f"  [!] {OVERRIDE} 가 있어 Codex 는 {TARGET} 를 읽지 않습니다")
    return current, desired, notes


def _same_file(host: Path, rels) -> str | None:
    """`rels` 중 AGENTS.md 와 같은 파일(어느 방향의 링크든, 하드링크든)인 첫 경로.

    - 파일 동일성만 비교 — 원본을 읽지 않으므로 PyYAML 부재도 디코딩 실패도 막지 못함.
    """
    path = host / TARGET
    target = os.path.normcase(os.path.realpath(path))
    for rel in rels:
        source = host / rel
        try:
            if os.path.normcase(os.path.realpath(source)) == target:
                return rel
            if path.exists() and source.exists() and os.path.samefile(path, source):
                return rel
        except OSError:
            continue
    return None


def _shared_source(host: Path) -> str | None:
    """AGENTS.md 와 같은 파일인 루트 원본 — 그런 호스트는 이미 Codex 에 Claude 텍스트를 주고,
    어떤 쓰기든 그 원본 안에 떨어짐."""
    return _same_file(host, ROOT_SOURCES)


def _shared_note(rel: str) -> str:
    return (
        f"  [!] {TARGET} 가 {rel} 와 같은 파일입니다 — Codex 가 그 내용을 이미 읽으므로"
        " 렌더하지 않습니다"
    )


def _is_multiply_linked(path: Path) -> bool:
    """AGENTS.md 가 symlink(끊긴 것 포함)이거나 다른 디렉터리 항목과 inode 를 나눔(하드링크).

    - `_shared_source` 는 상대가 `ROOT_SOURCES` 일 때만 알아봄 — 룰 파일·모듈 CLAUDE.md 로 이어진
      경우는 여기서 잡힘, Claude 원본 이름을 전부 몰라도.
    """
    if path.is_symlink():
        return True
    try:
        return path.stat().st_nlink > 1
    except OSError:
        return False


def _linked_note() -> str:
    return (
        f"  [!] {TARGET} 가 다른 파일과 연결되어 있습니다(symlink 또는 hard link) — Claude 산출물"
        "일 수 있어 그 파일을 통해 쓰지 않습니다"
    )


def _reverse_shared_source(host: Path, rels: list[str]) -> str | None:
    """`rels`(룰·모듈 CLAUDE.md·루트 파일) 중 자신이 AGENTS.md 로 풀리는 링크인 것.

    - `_shared_source` 의 반대 방향 — AGENTS.md 에 쓰면 밑에서 같은 파일인 그 원본도 바뀜.
    - `rels` 는 `_source_rels` 에서 옴(읽지 않고 나열).
    """
    return _same_file(host, rels)


def _reverse_shared_note(rel: str) -> str:
    return (
        f"  [!] {rel} 가 {TARGET} 와 같은 파일입니다 — 쓰면 그 Claude 산출물도 함께 바뀌므로"
        " 렌더하지 않습니다"
    )


def render(host: Path) -> list[str]:
    path = host / TARGET
    shared = _shared_source(host)
    if shared:
        return [_shared_note(shared)]
    if _is_multiply_linked(path):
        return [_linked_note()]
    try:
        found = _sources(host)
        reverse = _reverse_shared_source(host, _source_rels(host, found))
        if reverse:
            return [_reverse_shared_note(reverse)]
        current, desired, notes = _plan(host, _collect_docs(host, found))
        if desired == current:
            return [f"  [=] {TARGET} Codex 지침 블록 최신", *notes]
        if desired is None:
            path.unlink()
            return [f"  [-] {TARGET} 삭제(렌더할 지침 없음)", *notes]
        path.write_bytes(desired.encode("utf-8"))
    except MissingModule as exc:
        return [f"  [!] {TARGET} 렌더 불가: {_missing(exc)}"]
    except (OSError, ValueError) as exc:
        return [f"  [!] {TARGET} 렌더 실패({exc}) — 수동 확인 필요"]
    return [f"  [+] {TARGET} Codex 지침 블록 갱신", *notes]


def check(host: Path) -> tuple[bool, str]:
    """AGENTS.md 가 `render` 가 쓸 내용 그대로면 (True, "") — 아무것도 쓰지 않음.

    - AGENTS.md 가 애초에 이 렌더러가 관리할 것이 아니면(루트 원본과 공유·다른 파일로의
      링크) (True, note). `render` 가 고칠 수 있는 drift 가 아니므로 실패도 아님 — `--check` 는
      exit 0, CLI 는 `note`(render 의 `[!]` 줄)를 stderr 로 전함.
    """
    shared = _shared_source(host)
    if shared:
        return True, _shared_note(shared)
    if _is_multiply_linked(host / TARGET):
        return True, _linked_note()
    try:
        found = _sources(host)
        reverse = _reverse_shared_source(host, _source_rels(host, found))
        if reverse:
            return True, _reverse_shared_note(reverse)
        current, desired, _ = _plan(host, _collect_docs(host, found))
    except MissingModule as exc:
        return False, f"{TARGET} 점검 불가: {_missing(exc)}"
    except (OSError, ValueError) as exc:
        return False, f"{TARGET} 점검 실패({exc})"
    if desired == current:
        return True, ""
    return False, (
        f"{TARGET} 의 Codex 지침 블록이 CLAUDE.md·.claude/rules 와 다릅니다 — render 를 실행하세요"
    )


def remove(host: Path) -> str:
    path = host / TARGET
    if not path.is_file():
        return f"  [=] {TARGET} 없음"
    shared = _shared_source(host)
    if shared:
        return f"  [=] {TARGET} 가 {shared} 와 같은 파일 — 건드리지 않음 (skip)"
    if _is_multiply_linked(path):
        return f"  [=] {TARGET} 가 다른 파일과 연결되어 있어 건드리지 않음 (skip)"
    try:
        reverse = _reverse_shared_source(host, _source_rels(host, _sources(host)))
        verified = True
    except (MissingModule, OSError, ValueError):
        # 제거는 AGENTS.md 자신의 바이트만 읽으므로 원본을 나열 못 해도 멈추지 않음. 다만 원본이
        # AGENTS.md 로 링크하는지 모르게 되므로 비어도 파일은 남김 — 지우면 그 링크가 끊김.
        reverse, verified = None, False
    if reverse:
        return f"  [=] {reverse} 가 {TARGET} 와 같은 파일 — 건드리지 않음 (skip)"
    try:
        text = path.read_bytes().decode("utf-8")
        if not _spans(text):
            return f"  [=] {TARGET} 에 Codex 지침 블록 없음"
        remaining = _compose(text, None)
        if not remaining.strip() and verified:
            path.unlink()
            return f"  [-] {TARGET} 삭제(Codex 지침 블록만 있었음)"
        path.write_bytes(remaining.encode("utf-8"))
    except (OSError, ValueError) as exc:
        return f"  [!] {TARGET} 블록 제거 실패({exc}) — 수동 확인 필요"
    if not verified:
        return f"  [-] {TARGET} Codex 지침 블록 제거(원본을 다 읽지 못해 파일은 남김)"
    return f"  [-] {TARGET} Codex 지침 블록 제거"


def main(argv: list[str]) -> int:
    paths = _import("_vway_paths", "scripts._vway_paths")
    paths.force_utf8_io()
    parser = argparse.ArgumentParser(description="CLAUDE.md·.claude/rules → AGENTS.md (Codex)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    render_cmd = sub.add_parser("render", help="블록 갱신")
    render_cmd.add_argument("--check", action="store_true", help="다르면 exit 1, 쓰지 않음")
    remove_cmd = sub.add_parser("remove", help="블록 삭제")
    for cmd in (render_cmd, remove_cmd):
        cmd.add_argument("--host", help="호스트 루트(기본: 현재 저장소)")
    args = parser.parse_args(argv)
    host = Path(args.host) if args.host else paths.host_root()
    if args.cmd == "remove":
        print(remove(host))
        return 0
    if args.check:
        ok, reason = check(host)
        if reason:
            # 진짜 drift 는 stdout(CLI 가 내는 조치 한 줄), 관리 대상 아님 안내(`ok` 가 이미
            # True — 렌더러가 고칠 것 없음)는 stderr — `--check` 가 exit 0 이면서 이유는 말함.
            print(reason, file=sys.stderr if ok else sys.stdout)
        return 0 if ok else 1
    for line in render(host):
        print(line)
    return 0


if __name__ == "__main__":
    # 여기서만, import 시점엔 절대 안 함: sys.path[0] 은 이 파일의 디렉터리이고 harness
    # 패키지와 _vway_paths 는 두 단계 위에 있음.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main(sys.argv[1:]))
