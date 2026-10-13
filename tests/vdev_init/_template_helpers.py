"""호스트 템플릿 테스트가 공유하는 것 — 픽스처 config 와 링크·정션 만들기."""

from pathlib import Path

CONFIG = """
handoff:
  summary:
    enable: true
    field: item_content
  qa:
    enable: false
    field: col22
  done_flag:
    enable: true
    field: col31
    template: custom/flag.md
alm:
  recoble:
    spaces:
      dev3:
        workboard: "작업"
        layers:
          requirement:
            workboard: "요구사항"
          task:
            workboard: "개발 작업"
            marker: true
"""


def _mk(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _symlink_dir(link: Path, target: Path):
    import pytest

    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("이 호스트에서 디렉터리 심볼릭 링크를 만들 수 없음")


def _junction(link: Path, target: Path):
    """Windows 정션 — 관리자 권한이 필요 없어 심볼릭 링크보다 흔한 꼴."""
    import os
    import subprocess

    import pytest

    if os.name != "nt":
        pytest.skip("정션은 Windows 전용")
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
    )
    if made.returncode != 0:
        pytest.skip("이 호스트에서 정션을 만들 수 없음")
