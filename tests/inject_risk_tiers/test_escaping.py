"""SessionStart 훅의 JSON 이스케이프 — 비ASCII 룰을 로캘과 무관하게 바이트 그대로, 선형으로.

멀티바이트 로캘의 bash 패턴 치환은 매치마다 문자열을 다시 훑어 비ASCII 입력에서 2차가 됨.
훅은 세션이 열리기 전에 돌므로 그 지연이 곧 세션 시작 지연(macOS 7.6초, C 로캘 0.79초).
bash 3 은 awk 경로로 이스케이프하므로 그 프로그램의 출력이 bash 경로와 같은지도 여기서 잼.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.inject_risk_tiers._helpers import SCRIPT, _context, _manifest, _run

NON_ASCII_LINE = '- **규칙** — "인용" \\ 백슬래시\tтаб é 漢字 → 화살표\n'


def _non_ascii_plugin(tmp_path: Path) -> Path:
    plugin = _manifest(tmp_path / "cache", "vway-kit", None)
    body = NON_ASCII_LINE * (100 * 1024 // len(NON_ASCII_LINE.encode()))
    (plugin / "rules" / "risk-tiers.md").write_text(body, encoding="utf-8", newline="")
    return plugin


def test_a_utf8_locale_does_not_make_escaping_quadratic(tmp_path):
    """같은 100 KB 비ASCII 룰이 Linux bash 5.2 에서 UTF-8 로캘 2951 ms, C 로캘 25 ms(실측).
    절대 시간이 아니라 같은 머신의 비율로 판정 — Git Bash 는 이 입력에 어느 로캘이든 수 초를 씀."""
    plugin = _non_ascii_plugin(tmp_path)
    elapsed = {}
    for loc in ("C", "C.UTF-8"):
        start = time.perf_counter()
        assert "규칙" in _context(_run(plugin, None, extra_env={"LC_ALL": loc}))
        elapsed[loc] = time.perf_counter() - start
    assert elapsed["C.UTF-8"] < 3 * elapsed["C"] + 1, elapsed


@pytest.mark.parametrize("locale", ["C.UTF-8", "C"])
def test_a_non_ascii_rule_round_trips_through_the_escaping(tmp_path, locale):
    """이스케이프는 어느 로캘에서든 바이트 단위. 이스케이프 문자는 전부 ASCII 이고 UTF-8 연속
    바이트는 ASCII 가 아니므로, JSON 을 디코드하면 룰이 그대로 돌아옴. `$(<file)` 은 끝 개행을
    뗌."""
    plugin = _non_ascii_plugin(tmp_path)
    body = (plugin / "rules" / "risk-tiers.md").read_text(encoding="utf-8")
    assert body.rstrip("\n") in _context(_run(plugin, None, extra_env={"LC_ALL": locale}))


AWK_CASES = [
    "",
    "plain",
    "a\nb",
    "trailing\n",
    "two trailing\n\n",
    "\n\nleading blanks",
    "tab\there\t",
    "cr\r\nline\r\n",
    'quote " and \\ backslash \\\\ \\" \\\\"',
    "\\\n\\",
    NON_ASCII_LINE * 3,
]


def _json_string_body(value: str) -> str:
    """escape_for_json 이 쓰는 것: 이 다섯 이스케이프뿐."""
    for raw, escaped in (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"), ("\r", "\\r"), ("\t", "\\t")):
        value = value.replace(raw, escaped)
    return value


@pytest.mark.skipif(shutil.which("awk") is None, reason="PATH 에 awk 없음")
@pytest.mark.parametrize("value", AWK_CASES, ids=range(len(AWK_CASES)))
def test_the_awk_escaper_matches_the_bash_one(tmp_path, value):
    """bash 3(macOS /bin/bash 는 3.2)은 awk 로 이스케이프하는데 CI 의 bash 는 5 — 그래서 awk
    프로그램만 따로, 훅과 같은 끝 표지 처리로 돌림. 파일로 넘기는 것은 msys 가 Windows argv 의
    백슬래시를 고쳐 쓰기 때문."""
    if os.name == "nt" and "\r" in value:
        pytest.skip("Git for Windows 의 awk 는 stdin 을 텍스트 모드로 읽음 — Git Bash 는 bash 5")
    hook = SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")
    program = tmp_path / "escape.awk"
    awk_text = re.search(r"^json_escape_awk='(.*?)'$", hook, re.M | re.S).group(1)
    program.write_bytes(awk_text.encode())
    out = subprocess.run(
        [shutil.which("awk"), "-f", str(program)],
        input=(value + "x").encode(),
        capture_output=True,
        env={"LC_ALL": "C"},
        check=True,
        timeout=30,
    ).stdout.decode()
    assert out.removesuffix("x") == _json_string_body(value)
