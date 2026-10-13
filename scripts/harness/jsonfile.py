"""설치자가 호스트에서 손대는 JSON 파일의 읽기·쓰기 — 반쯤 쓰인 파일을 남기지 않음."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

ACCESS_ENTRIES = "system.posix_acl_access"


def why(exc: BaseException) -> str:
    """보고 줄에 담을 사유. errno 없이 raise 된 OSError 는 `strerror` 가 없음."""
    return getattr(exc, "strerror", None) or str(exc) or type(exc).__name__


def confine(host: Path, path: Path) -> Path:
    """`path` 그대로. 링크를 전부 따라간 끝이 호스트 밖이면 거절(OSError)."""
    root = os.path.normcase(os.path.realpath(host))
    real = os.path.normcase(os.path.realpath(path))
    try:
        inside = os.path.commonpath([root, real]) == root
    except ValueError:  # 다른 드라이브
        inside = False
    if not inside:
        raise OSError(f"호스트 밖을 가리킴: {path}")
    return path


def access_entries(path: Path) -> bytes | None:
    """호스트가 갖고 있다면 그 파일의 POSIX access 항목. rename **전에** 읽음 —
    그 뒤에는 항목이 속한 inode 가 사라짐."""
    try:
        return os.getxattr(path, ACCESS_ENTRIES)
    except (AttributeError, OSError):
        return None


def _default_mode(tmp: Path) -> None:
    """이 스크립트가 **만드는** 파일이 가져야 할 모드. `mkstemp` 는 소유자만 읽을 수
    있는 파일을 만들고 rename 이 그것을 옮김: 세션이 다른 uid 로 도는 빌드 머신에서
    0600 으로 깔린 settings.json 은 결코 로드되지 않는 게이트."""
    try:
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
    except OSError:
        pass


def _carry_over(before: os.stat_result, acl: bytes | None, tmp: Path) -> None:
    """rename 이 옮기지 못하는 것을 `tmp` 에 돌려놓음. best effort — 이런 것을 하나도
    갖지 않는 파일시스템이나 파일을 남에게 줄 권한이 없는 프로세스는 있던 것을 유지함."""
    try:
        os.chmod(tmp, stat.S_IMODE(before.st_mode))
    except OSError:
        pass
    if acl is not None:
        try:
            os.setxattr(tmp, ACCESS_ENTRIES, acl)
        except (AttributeError, OSError):
            pass
    try:
        if before.st_uid != os.getuid() or before.st_gid != os.getgid():
            os.chown(tmp, before.st_uid, before.st_gid)
    except (AttributeError, OSError):
        pass


def write_json(path: Path, data: dict, host: Path) -> str | None:
    """쓰거나, 대신 보고할 줄을 반환.

    호스트 밖으로 풀리는 경로는 거부 — 저장소는 믿을 수 없는 입력이고,
    `~/.claude/settings.json` 으로 링크된 커밋된 `.claude/settings.json` 은 그 사용자가 여는
    모든 프로젝트에 게이트를 실어 나름.

    임시 파일과 rename 하나를 거침 — 쓰기로 여는 것이 먼저 truncate 하기 때문:
    꽉 찬 디스크, 끊어진 공유, 호스트 자신의 데이터에 든 고립 서로게이트 하나가 그러지
    않으면 더 이상 파싱되지 않는 조각을 호스트 설정으로 남김 — 게다가 이것은 남은
    단계들이 무방비인 셋업의 중간에서 돎. 쓰기가 실패할 수 있는 모든 길을 잡음,
    본 적 있는 길만이 아니라: 인코딩은 ValueError 를, 나머지는 OSError 를 던짐.

    rename 은 **이름**을 갈아치우므로, settings.json 을 저장소 안 다른 파일로 향하는 심링크로
    두는 호스트는 그것이 평범한 파일로 돌아오고 링크된 사본은 옛 내용을 유지함. 그래서
    rename 은 링크가 **가리키는 쪽**에 내려앉음 — 호스트를 떠나는 링크는 dotfiles 링크를
    포함해 위에서 거부됨. 임시 파일이 유일한 이름을 갖는 것은 그 옆의 고정된 이름이
    호스트 자신의 파일이었고 이것이 조용히 그것을 삼켰기 때문.

    rename 이 옮기지 못하는 것은 그것이 대체하는 파일. 모드·소유자·access 항목이
    전부 임시 파일의 것 — 쓴 쪽만의 것 — 이 됨: `sudo /vdev-init` 은 호스트 설정을
    root 소유로 남기고, `st_mode` 는 group 비트에 ACL **마스크**를 보고하므로 그것을
    평범한 모드로 되돌리는 것은 소유자가 이름 붙은 사용자 하나에게 준 파일에 group
    쓰기를 주는 일. 셋 다 넘김, 모드보다 항목을 **먼저** — 반대면 마스크가
    리셋됨. 호스트가 읽기 전용으로 잠근 파일은 거부 — 쓰기 비트가 막지 못하는
    root 는 예외. 새 inode 가 지킬 수 없는 것은 아무도 못 지킴: 둘째 하드링크,
    타임스탬프, `user.*` 속성, 그리고 소유자를 돌려줘야 하는 곳의 setuid 비트.
    호스트 안의 심링크는 살아남음.
    """
    try:
        confine(host, path)
    except OSError as exc:
        return f"  [!] {path.name} 쓰기 거부({why(exc)}) — 수동 확인 필요"
    target = Path(os.path.realpath(path)) if path.is_symlink() else path
    if target.is_file() and not os.access(target, os.W_OK):
        return f"  [!] {path.name} 이 쓰기 금지 상태입니다 — 수동 확인 필요"
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        before = target.stat() if target.is_file() else None
    except OSError:  # 묻는 것과 답 사이에 사라짐
        before = None
    acl = access_entries(target) if before is not None else None
    tmp = None
    try:
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".new")
        tmp = Path(name)  # 디스크립터가 닫히기 전에 이름을 잡음: 정리 경로가 `tmp` 를 읽음
        os.close(fd)
        tmp.write_text(payload, encoding="utf-8")
        if before is not None:
            _carry_over(before, acl, tmp)
        else:
            _default_mode(tmp)
        os.replace(tmp, target)
        tmp = None
    except (OSError, ValueError) as exc:
        return f"  [!] {path.name} 을 쓰지 못했습니다({why(exc)}) — 수동 확인 필요"
    finally:
        # 쓰기가 던지는 둘만이 아님: 여기를 지나는 인터럽트는 호스트가 추적하는
        # 그들의 `.claude/` 에 파일을 남김.
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
    return None


def write_or_remove(path: Path, data: dict, host: Path, label: str) -> tuple[str | None, bool]:
    """`data` 를 쓰거나, 제거가 빈 객체를 남겼으면 파일을 지움 — 호스트가 쓴 적 없는 `{}` 는 잔재.
    (실패 시 보고할 줄, 지웠는가) 를 반환.

    링크는 지우지 않고 너머로 씀 — 지우면 다른 경로로 여전히 읽히는 그 대상이 제거한 것을 쥔 채
    남음. 읽기 전용으로 잠긴 파일은 그것을 거부하는 writer 로 보냄."""
    if data or path.is_symlink() or not os.access(path, os.W_OK):
        return write_json(path, data, host), False
    try:
        confine(host, path.parent)
        path.unlink()
    except OSError as exc:
        return f"  [!] {label} 삭제 실패({why(exc)}) — 수동 확인 필요", False
    return None, True


def load_json_object(path: Path, label: str) -> tuple[dict | None, str | None]:
    """`path` 를 JSON 객체로 파싱. 없으면 ({}, None), 읽을 수 없거나 객체가 아니면
    (None, 보고할 줄) — `data is None` 이면 사유는 **반드시** 있음. `label` 이 그 줄에
    파일 이름으로 들어감."""
    try:
        exists = path.is_file()
    except OSError as exc:  # 호스트가 닫아 둔 상위 디렉터리 — `is_file` 이 이것을 삼키지 않음
        return None, f"  [!] {label} 을 읽지 못했습니다({why(exc)}) — 수동 확인 필요"
    if not exists:
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        return None, f"  [!] {label} 이 UTF-8 이 아닙니다 — 수동 확인 필요"
    except (json.JSONDecodeError, RecursionError):
        return None, f"  [!] {label} 파싱 실패 — 수동 확인 필요"
    except OSError as exc:
        return None, f"  [!] {label} 을 읽지 못했습니다({why(exc)}) — 수동 확인 필요"
    # `null` 은 호스트 자신의 도구가 "아직 아무것도 설정 안 됨" 으로 쓰는 값. 우연히
    # falsy 인 나머지 — `0`·`[]`·빈 문자열 — 는 전부 데이터이고, 그것을 빈 객체로 읽는
    # 것은 깨끗한 등록을 보고하면서 호스트 파일을 덮어쓰는 일.
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, f"  [!] {label} 이 객체가 아닙니다 — 수동 확인 필요"
    return data, None
