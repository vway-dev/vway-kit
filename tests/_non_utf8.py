"""UTF-8 이 아닌 자식 환경 — 축 **둘**.

`non_utf8_env` 는 로캘을 비UTF-8 로 **세움**(아래 설명). `stdio_host_env` 는 반대로 인코딩
변수 둘을 **지워** 호스트가 직접 세운 것만 남김 — 그쪽 독스트링 참조.

로캘을 세우는 축 — `PYTHONUTF8` 없는 한국어 Windows(cp949)의 대역.

`PYTHONUTF8=0` 은 명시 해제. 지우기만 하면 POSIX 의 C 로캘에서 파이썬이 UTF-8 모드를 스스로
켬(PEP 540). 명령행 `-X utf8` 은 이 값을 이김.
POSIX 는 `LC_ALL=C` 와 `PYTHONCOERCECLOCALE=0` 이 함께 있어야 ASCII 로캘이 됨 — 강제 해제가
없으면 C 로캘을 C.UTF-8 로 올림(PEP 538). Windows 의 파이썬은 `LC_ALL` 을 안 보고 ANSI 코드페이지를
쓰므로 거기선 `PYTHONUTF8=0` 하나로 충분.
POSIX 대역은 파일시스템 인코딩까지 ASCII 로 바꿈 — 자식이 git 에서 받은 비ASCII 경로로 파일에
닿는 검사엔 대역이 안 됨(Windows 는 PEP 529 로 파일시스템 인코딩이 늘 UTF-8).
ANSI 코드페이지가 이미 UTF-8(65001)인 Windows 에서는 이 환경이 결함을 못 드러냄.
"""

import os


def non_utf8_env(**extra: str) -> dict[str, str]:
    """현재 환경 + 비UTF-8 로캘. `extra` 가 마지막에 덮음."""
    env = dict(os.environ, PYTHONUTF8="0")
    if os.name != "nt":
        env.update(LC_ALL="C", PYTHONCOERCECLOCALE="0")
    env.update(extra)
    return env


def stdio_host_env(**overrides: str) -> dict[str, str]:
    """현재 환경에서 **인코딩 변수 둘을 걷어낸** 자식 환경, 그 위에 `overrides`.

    `non_utf8_env` 와 다른 축임 — 그쪽은 로캘을 비UTF-8 로 **세우고**, 이쪽은 두 변수를
    **지워** 호스트가 직접 세운 것만 남김. 지우는 것이 필요한 이유는 이 머신의 사용자 env 에
    `PYTHONUTF8=1` 이 서 있어, 그대로 물려주면 `PYTHONIOENCODING` 단독 호스트를 못 재기
    때문임(결함이 로컬에서만 안 보임).
    """
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(overrides)
    return env
