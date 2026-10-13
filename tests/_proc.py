"""테스트가 자식 프로세스를 띄우는 한 가지 방법 — 자식의 멈춤이 스위트 전체의 멈춤이 되지 않게.

**파이프로 받으면 `timeout` 이 안 들음(Windows).** `subprocess.run` 은 시간이 다 되면 직접 자식만
죽이고, Windows 에서는 그 뒤 파이프를 끝까지 다시 읽음. 파이프는 쓰기 끝이 전부 닫혀야 EOF 를
내므로, 자식이 띄운 손자 하나가 출력 핸들을 쥔 채 살아 있으면 그 손자가 끝날 때까지 기다림.
실측(timeout=3): 러너의 `--classify` 손자 19.6초 · `find … | wc -l` 의 `find` 16.3초 · 손자 없는
python 3.2초. 이 스위트가 실제로 그렇게 멈췄음(pytest 가 리더 스레드 join 에서 대기).
POSIX 의 `run` 은 죽인 뒤 다시 읽지 않아 이 결함이 안 보이지만, `timeout` 자체는 어디서나
필요함 — 없으면 직접 자식의 멈춤도 무한 대기.

그래서 stdin·stdout·stderr 를 전부 임시 파일로 돌림. 기다릴 파이프가 없으니 멈춤이 제때
`TimeoutExpired` 로 나옴 — 읽히지 않는 멈춤보다 실패가 나음.

`subprocess.run` 과 다른 점:
- 입력이 없으면 stdin 은 빈 파일 — 자식이 stdin 을 읽어도 테스트 프로세스의 입력을 안 기다림.
- `text` 모드의 기본 인코딩은 로캘이 아니라 UTF-8(Invariant 2). 입력의 개행은 그대로 두고, 출력은
  `run` 처럼 CRLF·CR 을 LF 로 맞춤.
- 임시 파일 정리 실패는 무시 — 살아남은 손자가 파일 핸들을 쥐고 있으면 Windows 에서
  `PermissionError` 가 나 타임아웃 진단을 덮음(실측).

이것으로만 띄우는 폴더는 `tests/test_proc.py` 의 `_GUARDED` 가 고정.
"""

import io
import subprocess
import tempfile
from pathlib import Path

# 정상 호출은 수 초. 넉넉히 잡되, 멈춘 호출 하나가 몇 분씩 먹지는 않게.
DEFAULT_TIMEOUT = 60


def _decode(data: bytes, encoding: str, errors: str) -> str:
    """`run(text=True)` 와 같은 보편 개행 읽기."""
    return io.TextIOWrapper(io.BytesIO(data), encoding=encoding, errors=errors).read()


def run_bounded(
    args: list,
    *,
    input: bytes | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    text: bool = False,
    encoding: str | None = None,
    errors: str | None = None,
    check: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess:
    """`subprocess.run(..., capture_output=True, timeout=...)` 의 자리.

    `cwd`·`env` 등 나머지 인자는 그대로 넘김."""
    text = text or encoding is not None or errors is not None
    encoding, errors = encoding or "utf-8", errors or "strict"
    data = input.encode(encoding, errors) if isinstance(input, str) else (input or b"")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        box = Path(tmp)
        (box / "in").write_bytes(data)
        with (
            open(box / "in", "rb") as stdin,
            open(box / "out", "wb") as out,
            open(box / "err", "wb") as err,
        ):
            proc = subprocess.run(
                args, stdin=stdin, stdout=out, stderr=err, timeout=timeout, **kwargs
            )
        stdout, stderr = (box / "out").read_bytes(), (box / "err").read_bytes()
    if text:
        stdout, stderr = _decode(stdout, encoding, errors), _decode(stderr, encoding, errors)
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, args, stdout, stderr)
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
