"""테스트가 실제로 쓸 수 있는 bash 실행 파일을 하나의 규칙으로 고름.

**이름으로 부르면 안 됨.** 파이썬 `subprocess` 는 Windows 에서 `shell=False` 일 때
`CreateProcess` 의 검색 순서를 쓰는데, 그 순서는 PATH 보다 `System32` 가 **앞**임.
`C:\\Windows\\System32\\bash.exe`(WSL 스텁)가 깔린 호스트에서는 PATH 를 어떻게 깔아도,
`shutil.which("bash")` 가 Git Bash 를 옳게 답해도, 인자를 `"bash"` 로 넘기는 순간 스텁이
잡힘. 스텁은 `wsl.exe` 를 띄우고 WSL 은 stdin 을 물고 놓지 않아 **테스트가 영원히
매달림**(실측: `pytest` 전체 실행이 74분간 진행 없이 hang, CPU 는 거의 0).

그래서 호출부는 언제나 이 모듈이 돌려주는 **절대 경로**를 넘김.

고르는 순서와 근거:
1. `git` 실행 파일의 형제 bash — Git Bash 는 항상 `<Git>/bin/bash.exe` 나
   `<Git>/usr/bin/bash.exe` 로 함께 깔리므로, git 위치가 곧 결정론적 앵커.
2. `shutil.which("bash")` — 단, System32 밑이면 버림(그게 스텁). 실제 머신 PATH 는
   Git 보다 System32 가 앞이라 `which` 만 믿으면 스텁을 집음.
3. 알려진 Git 설치 위치.
POSIX 에서는 1·3 이 자연히 비고 2 가 그대로 답이 됨.
"""

import os
import shutil
from pathlib import Path

_GIT_RELATIVE = ("bin/bash.exe", "usr/bin/bash.exe")
_KNOWN = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
)


def _is_wsl_stub(path: str) -> bool:
    """`System32\\bash.exe` 인가. 이름이 아니라 **위치**로 판별 — 스텁의 파일명은
    진짜 bash 와 같고, 다른 것은 어느 디렉터리에 있느냐뿐임."""
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    try:
        return Path(path).resolve().parent == system32.resolve()
    except OSError:
        return False


def find_bash() -> str | None:
    """쓸 수 있는 bash 의 절대 경로. 없으면 None(호출부가 skip 하라는 뜻)."""
    git = shutil.which("git")
    if git:
        for parent in Path(git).resolve().parents:
            for rel in _GIT_RELATIVE:
                candidate = parent / rel
                if candidate.is_file():
                    return str(candidate)
    which = shutil.which("bash")
    if which and not _is_wsl_stub(which):
        return which
    for candidate in _KNOWN:
        if Path(candidate).is_file():
            return candidate
    return None


BASH = find_bash()
