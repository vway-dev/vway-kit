"""integration §3.4 가 출하하는 판정 스니펫을 **문서에서 뽑아 실제로 돌림**.

스니펫은 문서 안에 있어 아무 테스트도 안 돎. 눈으로 읽는 리뷰는 라이브러리의 실제 의미를
놓침 — 정적 대조 3라운드가 "`stats` 가 전부 0 이면 PASS + exit 0" 과 "`spec.ok()` 는 skipped
에도 true" 를 못 잡았고, 픽스처로 돌린 라운드가 잡음. 방향이 나쁨: 둘 다 **통과 쪽으로**
틀려 승격 게이트가 그 판정을 근거로 씀.

여기서 재는 것은 §3.4 두 블록뿐. 회차 생성(alm-trace)·필드 점검(vdev-init)은
`scripts/skill_sandbox.py` 의 `OUT_OF_REACH` 가 적은 이유 그대로 픽스처가 못 세움.

블록은 bash 로 통째 돌림 — JS 만 떼어 `node` 에 넘기면 셸 인용이 검사에서 빠지고, `$` 나
백틱이 스니펫에 들어온 날 출하본은 깨지는데 테스트는 녹색으로 남음.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests._bash import BASH
from tests._proc import run_bounded
from tests.skill_docs._helpers import REPO, bash_blocks, body

SKILL = REPO / "skills/integration/SKILL.md"

# 두 스니펫 각각의 지문 — 사본 탐지가 읽는 것. 출력 문구가 아니라 **하는 일**을 고름:
# 문구로 잡으면 철자만 바꾼 사본이 그대로 빠져나가고, 케이스별 블록은 아예 안 보임.
_SNIPPET_ANCHORS = ("readFileSync('results.json'", "rows.push([tag")


def _verdict_section() -> str:
    """§3.4 본문. 절이 개명되면 여기서 멈춤 — 스니펫이 사라져도 조용하지 않게."""
    text = body(SKILL)
    m = re.search(r"^### 3\.4 .*?$(.*?)^### 3\.5 ", text, re.M | re.S)
    assert m, "integration SKILL.md: §3.4 (결과 파싱) 절을 못 찾음 — 제목이 바뀜"
    return m.group(1)


def _node_blocks() -> tuple[str, str]:
    """(집계 블록, 케이스별 블록). 순서는 문서 순서이고 개수는 정확히 둘."""
    blocks = [b for b in bash_blocks(_verdict_section()) if b.lstrip().startswith("node -e")]
    assert len(blocks) == 2, (
        f"§3.4 의 node 판정 블록이 {len(blocks)}개 — 집계와 케이스별 둘이어야 함"
    )
    return blocks[0], blocks[1]


def _bash() -> str:
    if BASH is None:
        pytest.skip("no usable bash on this host")
    if shutil.which("node") is None:
        pytest.skip("no node on this host")
    return BASH


def test_the_runtime_these_snippets_need_is_present_in_ci():
    """조용히 스킵된 가드는 가드가 아님. 개발자 머신에서는 node 부재가 스킵으로 지나가도
    되지만, CI 에서 같은 일이 벌어지면 판정 스니펫이 아무 데서도 안 돌게 됨 — GitHub
    ubuntu 러너는 node 를 기본 탑재하므로 부재는 러너 변경이지 정상이 아님."""
    if not os.environ.get("CI"):
        pytest.skip("not CI")
    assert shutil.which("node"), "CI runner has no node — every snippet test skipped silently"
    assert BASH, "CI runner has no usable bash"


def _run(block: str, cwd: Path) -> subprocess.CompletedProcess:
    """출하 텍스트를 그대로 bash 에 먹임 — 바이트로 넘기는 이유는
    `tests/skill_docs/_discovery.run_discovery` 와 같음(Windows 인용·개행 훼손).

    스크립트는 파일로 주고 stdin 은 비움: 블록이 자기 스크립트 스트림을 볼 일이 없어짐. 출력을
    파이프가 아니라 파일로 받는 근거는 `tests/_proc.py`. (여기 블록은 에이전트가 세션에서 치는
    명령이지 CI 스텝이 아님 — 러너 형태를 근거로 삼는 쪽은
    `tests/test_doc_style_targets.py::_bash_script`.)"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        script = Path(tmp) / "block.sh"
        script.write_bytes(block.encode("utf-8"))
        return run_bounded([_bash(), script.as_posix()], cwd=cwd, timeout=120)


def _spec(title: str, tests: list[dict]) -> dict:
    return {"title": title, "tests": tests}


def _test(status: str, results: list[dict]) -> dict:
    return {"status": status, "results": results}


def _report(suites: list[dict], stats: dict, errors: list[dict] | None = None) -> dict:
    return {"suites": suites, "stats": stats, "errors": errors or []}


def _stats(expected=0, unexpected=0, flaky=0, skipped=0) -> dict:
    """실측 모양 — Playwright 는 집계 넷 옆에 `startTime`·`duration` 을 늘 실음. 넷만 담으면
    "stats 는 전부 0" 같은 틀린 문장이 이 파일을 근거로 다시 자람."""
    return {
        "startTime": "2026-09-08T00:00:00.000Z",
        "duration": 1243.7,
        "expected": expected,
        "unexpected": unexpected,
        "flaky": flaky,
        "skipped": skipped,
    }


def _passed(duration=1200) -> dict:
    return {"status": "passed", "duration": duration}


def _failed(message: str, duration=800) -> dict:
    return {"status": "failed", "duration": duration, "error": {"message": message}}


# 픽스처는 이름 → (results.json 내용 또는 raw 문자열). 리뷰 4라운드가 손으로 돌린 집합과
# 같고, 거기에 파싱 실패 갈래 둘과 중첩 suite 하나를 더함.
FIXTURES: dict[str, object] = {
    "ok": _report(
        [
            {
                "title": "auth.spec.ts",
                "specs": [
                    _spec("로그인 @TC-1", [_test("expected", [_passed(1500)])]),
                    _spec("로그아웃 @TC-2", [_test("expected", [_passed(900)])]),
                ],
            }
        ],
        _stats(expected=2),
    ),
    # 글로벌 셋업이 죽은 실행. 집계 넷이 전부 0 이고 사유는 errors 에만 남음 — 0 은 숫자라
    # `typeof s.expected === 'number'` 를 통과하고 unexpected 도 0.
    "setup-failed": _report(
        [], _stats(), errors=[{"message": "Error: globalSetup failed: ECONNREFUSED"}]
    ),
    # 필터가 전부 걸러낸 실행. errors 는 비었으므로 0개 검사만이 이것을 잡음.
    "zero-cases": _report([], _stats()),
    # 재시도로 통과한 케이스. 마지막 시도가 결론이라 표도 PASS 여야 집계(unexpected 0)와 맞음.
    "flaky": _report(
        [
            {
                "title": "checkout.spec.ts",
                "specs": [
                    _spec(
                        "결제 @TC-3",
                        [_test("flaky", [_failed("timeout", 3000), _passed(1100)])],
                    )
                ],
            }
        ],
        _stats(flaky=1),
    ),
    # project 둘. 첫 test 만 보면 chromium 통과가 그 케이스의 판정이 되고 firefox 실패가 사라짐.
    "multi-project": _report(
        [
            {
                "title": "cart.spec.ts",
                "specs": [
                    _spec(
                        "장바구니 @TC-4",
                        [
                            _test("expected", [_passed(1000)]),
                            _test("unexpected", [_failed("expected 1 to be 2", 2200)]),
                        ],
                    )
                ],
            }
        ],
        _stats(expected=1, unexpected=1),
    ),
    # 결과 배열이 빈 케이스. Playwright 는 결과가 하나도 없는 test 의 status 를 `skipped`
    # 로 계산하므로(teleReceiver 의 computeTestCaseOutcome) `expected` 인 채로 비어 있는
    # 모양은 실재하지 않음 — 실재하는 모양으로 둠. `!runs.length` 갈래는 중단된 실행에
    # 대한 여분 방어이고 이 픽스처 하나만으로는 단독 검증이 안 됨.
    "empty-results": _report(
        [
            {
                "title": "profile.spec.ts",
                "specs": [_spec("프로필 @TC-5", [_test("skipped", [])])],
            }
        ],
        _stats(skipped=1),
    ),
    # 셋업 훅에서 멈춘 케이스. 본문 실패가 아니므로 FAIL 이 아니라 BLOCKED.
    "hook-failure": _report(
        [
            {
                "title": "admin.spec.ts",
                "specs": [
                    _spec(
                        "관리자 @TC-6",
                        [
                            _test(
                                "unexpected",
                                [_failed('"beforeAll" hook timeout of 30000ms exceeded.', 400)],
                            )
                        ],
                    )
                ],
            }
        ],
        _stats(unexpected=1),
    ),
    # 건너뛴 케이스. 안 돈 것에 PASS 가 박히면 커버리지가 거짓이 됨.
    "skipped": _report(
        [
            {
                "title": "beta.spec.ts",
                "specs": [_spec("베타 @TC-7", [_test("skipped", [{"status": "skipped"}])])],
            }
        ],
        _stats(skipped=1),
    ),
    # describe 블록은 suite 를 중첩함 — 워커가 재귀를 잃으면 이 케이스만 조용히 사라짐.
    "nested": _report(
        [
            {
                "title": "search.spec.ts",
                "suites": [
                    {
                        "title": "필터",
                        "specs": [_spec("카테고리 @TC-8", [_test("expected", [_passed(700)])])],
                    }
                ],
            }
        ],
        _stats(expected=1),
    ),
    # 절반만 돈 회차 — 직렬 중단·`--max-failures` 의 잔여가 이 모양. 집계는 여기서 판정을
    # 못 가름(아래 전용 테스트가 그 경계를 못박음).
    "mixed": _report(
        [
            {
                "title": "orders.spec.ts",
                "specs": [
                    _spec("목록 @TC-9", [_test("expected", [_passed(600)])]),
                    _spec("상세 @TC-10", [_test("skipped", [{"status": "skipped"}])]),
                ],
            }
        ],
        _stats(expected=1, skipped=1),
    ),
    # 태그가 제목 **앞**에 선 케이스. Playwright 는 자리를 안 가림 — 정규식이 헐거워지면
    # 태그가 제목 전체를 집어삼키고, 회차 표의 케이스 키가 통째로 틀림.
    "tag-first": _report(
        [
            {
                "title": "login.spec.ts",
                "specs": [
                    _spec("@TC-11 로그인 후 대시보드 확인", [_test("expected", [_passed(800)])])
                ],
            }
        ],
        _stats(expected=1),
    ),
    # 태그 없는 케이스 — 빈 키로 한 줄 차지해야 커버리지 분모가 안 줄어듦.
    "untagged": _report(
        [
            {
                "title": "misc.spec.ts",
                "specs": [_spec("이름만 있는 케이스", [_test("expected", [_passed(500)])])],
            }
        ],
        _stats(expected=1),
    ),
    # 0건 검사가 errors 검사를 포섭하지 못하는 유일한 증거 — 사유는
    # `test_the_aggregate_fails_a_run_whose_own_teardown_died` 가 듦.
    "teardown-failed": _report(
        [
            {
                "title": "billing.spec.ts",
                "specs": [
                    _spec("청구 @TC-12", [_test("expected", [_passed(1000)])]),
                    _spec("환불 @TC-13", [_test("expected", [_passed(1200)])]),
                ],
            }
        ],
        _stats(expected=2),
        errors=[{"message": "Error: globalTeardown blew up: cleanup failed"}],
    ),
    "no-stats": {"suites": [], "errors": []},
    "unparsable": "{ this is not json",
}


def _write(name: str, root: Path) -> Path:
    """픽스처를 `results.json` 으로 씀. 스니펫이 그 이름을 리터럴로 읽음(§3.3 의 환경변수)."""
    cwd = root / name
    cwd.mkdir(parents=True, exist_ok=True)
    payload = FIXTURES[name]
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    (cwd / "results.json").write_text(text, encoding="utf-8")
    return cwd


# 집계 블록의 계약: (종료 코드, stdout 에 있어야 하는 조각).
AGGREGATE_EXPECTED = {
    "ok": (0, "PASS: 2"),
    "setup-failed": (1, "실행 자체가 오류로 끝남"),
    "zero-cases": (1, "실행된 케이스가 0개"),
    # 재시도로 통과한 회차 — 통과 칸에 실려야 종료 코드(0)와 문구가 같은 말을 함.
    "flaky": (0, "PASS: 1"),
    "multi-project": (1, "FAIL: 1"),
    "empty-results": (1, "실행된 케이스가 0개"),
    "hook-failure": (1, "FAIL: 1"),
    "skipped": (1, "실행된 케이스가 0개"),
    "nested": (0, "PASS: 1"),
    "mixed": (0, "SKIP: 1"),
    "tag-first": (0, "PASS: 1"),
    "untagged": (0, "PASS: 1"),
    "teardown-failed": (1, "실행 자체가 오류로 끝남"),
    "no-stats": (1, "stats 필드가 없음"),
    "unparsable": (1, "읽거나 파싱할 수 없음"),
}


@pytest.mark.parametrize("name", sorted(AGGREGATE_EXPECTED), ids=sorted(AGGREGATE_EXPECTED))
def test_the_aggregate_snippet_judges_each_report_shape(name: str, tmp_path: Path):
    """집계 블록이 승격 근거를 냄 — 통과 쪽으로 틀리면 안 돈 실행이 릴리스를 세움."""
    code, fragment = AGGREGATE_EXPECTED[name]
    proc = _run(_node_blocks()[0], _write(name, tmp_path))
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == code, f"{name}: exit {proc.returncode} ≠ {code} — {out}{err}"
    assert fragment in out, f"{name}: {fragment!r} 가 없음 — {out!r}"


def test_the_aggregate_snippet_never_passes_a_run_with_nothing_in_it(tmp_path: Path):
    """따로 세운 이유는 이것이 게이트의 방향이기 때문 — 한 건도 안 돈 실행 셋 전부가
    **실패**여야 함. 위 표는 조각 문자열까지 재므로 문구를 고치면 흔들리지만, 이 셋의
    종료 코드는 문구와 무관하게 1 이어야 함."""
    for name in ("setup-failed", "zero-cases", "skipped", "empty-results"):
        proc = _run(_node_blocks()[0], _write(name, tmp_path))
        assert proc.returncode == 1, (
            f"{name}: 한 건도 안 돈 실행이 exit 0 — 승격 게이트가 이것을 근거로 씀"
        )


def test_the_aggregate_fails_a_run_whose_own_teardown_died(tmp_path: Path):
    """`errors` 검사가 0건 검사와 **겹치지 않는** 자리 — 이것 없이는 전자를 지워도 조용함.

    셋업이 죽으면 집계 넷이 0 이라 두 검사가 같은 답을 내지만, 티어다운이 죽으면 케이스는
    다 돌아 0건 검사가 통과함. 그때 판정을 세우는 것은 `errors` 하나뿐이고, Playwright 자신도
    그 회차를 exit 1 로 냄."""
    proc = _run(_node_blocks()[0], _write("teardown-failed", tmp_path))
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 1, f"티어다운이 죽은 회차가 통과로 나감 — {out!r}"
    assert "PASS:" not in out, f"집계 줄이 먼저 나와 오류가 묻힘 — {out!r}"


def test_the_aggregate_cannot_tell_a_half_run_suite_from_a_deliberate_skip(tmp_path: Path):
    """집계가 **막지 못하는** 것을 못박음 — 위 테스트의 경계.

    Playwright 의 `stats.skipped` 는 `test.skip()` 과 중단된 실행의 잔여를 같은 칸에 담음.
    건너뜀 하나로 실패를 내면 `test.skip()` 을 쓰는 모든 스위트가 승격을 못 함. 그래서 절반만
    돈 회차는 집계에서 통과로 나가고, 얼마나 돌아야 충분한지는 케이스별 표의 NOT_RUN 줄과
    `promotion_verification.exit_criteria` 가 정함(release-commit 3단계). 이 사실을 여기 적어
    두지 않으면 다음 사람이 집계를 그 판정자로 오해함."""
    proc = _run(_node_blocks()[0], _write("mixed", tmp_path))
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "SKIP: 1" in out, f"건너뛴 케이스가 증거에 안 실림 — {out!r}"
    assert ("@TC-10", "NOT_RUN") in [(r[0], r[2]) for r in _rows("mixed", tmp_path)]


def _rows(name: str, tmp_path: Path) -> list[list[str]]:
    proc = _run(_node_blocks()[1], _write(name, tmp_path))
    err = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, f"{name}: 케이스별 블록이 실패 — {err}"
    out = proc.stdout.decode("utf-8", "replace")
    return [[c.strip() for c in ln.split("|")] for ln in out.splitlines() if ln.strip()]


# 케이스별 블록의 계약: 이름 → (태그, 판정) 목록. 열 순서는 templates/alm/run.md 의 고정
# 스키마와 같음(케이스 | 제목 | 판정 | 소요).
PER_CASE_EXPECTED = {
    "ok": [("@TC-1", "PASS"), ("@TC-2", "PASS")],
    "flaky": [("@TC-3", "PASS")],
    "multi-project": [("@TC-4", "FAIL")],
    "empty-results": [("@TC-5", "NOT_RUN")],
    "hook-failure": [("@TC-6", "BLOCKED")],
    "skipped": [("@TC-7", "NOT_RUN")],
    "nested": [("@TC-8", "PASS")],
    # 집계가 못 가르는 것을 표는 가름 — 안 돈 케이스가 자기 줄로 남음.
    "mixed": [("@TC-9", "PASS"), ("@TC-10", "NOT_RUN")],
    "tag-first": [("@TC-11", "PASS")],
    "untagged": [("", "PASS")],
}


@pytest.mark.parametrize("name", sorted(PER_CASE_EXPECTED), ids=sorted(PER_CASE_EXPECTED))
def test_the_per_case_snippet_gives_each_case_its_verdict(name: str, tmp_path: Path):
    """케이스별 판정이 `latest_result` 로 보드에 박힘 — 틀리면 리그레션 기록이 거짓이 됨."""
    rows = _rows(name, tmp_path)
    assert [(r[0], r[2]) for r in rows] == PER_CASE_EXPECTED[name], rows


def test_the_per_case_snippet_reports_four_columns_in_the_run_template_order(tmp_path: Path):
    """열 넷·순서 고정 — `templates/alm/run.md` 의 표를 이 출력이 채우고, 읽는 쪽은 이름이
    아니라 순서로 판정을 찾음."""
    rows = _rows("ok", tmp_path)
    assert all(len(r) == 4 for r in rows), rows
    assert [r[1] for r in rows] == ["로그인 @TC-1", "로그아웃 @TC-2"]
    assert rows[0][3] == "1.5s", f"소요는 마지막 시도의 초 표기 — {rows[0]}"


def test_the_per_case_snippet_keeps_untagged_cases_in_the_table(tmp_path: Path):
    """태그 없는 케이스도 빈 키로 한 줄 차지 — 빠지면 커버리지 분모가 조용히 줄어듦."""
    assert _rows("untagged", tmp_path) == [["", "이름만 있는 케이스", "PASS", "0.5s"]]


def test_the_tag_regex_takes_the_key_and_leaves_the_title(tmp_path: Path):
    """태그는 제목 어디에나 설 수 있음. 정규식이 헐거워지면 제목 전체를 케이스 키로 집어
    보드에 없는 key 가 회차 표에 박힘 — 픽스처 제목이 전부 태그로 끝나면 안 재짐."""
    assert _rows("tag-first", tmp_path) == [
        ["@TC-11", "@TC-11 로그인 후 대시보드 확인", "PASS", "0.8s"]
    ]


def test_the_flaky_case_agrees_with_the_aggregate(tmp_path: Path):
    """같은 회차의 표와 집계가 갈리면 어느 쪽이 맞는지 사람이 못 정함. flaky 는 집계에서
    unexpected 0(통과)이므로 표도 PASS 여야 함 — 첫 시도를 읽으면 여기서 갈림."""
    assert _rows("flaky", tmp_path)[0][2] == "PASS"
    assert _run(_node_blocks()[0], _write("flaky", tmp_path)).returncode == 0


def test_only_one_shipped_document_carries_the_aggregate_verdict():
    """판정 스니펫의 사본이 둘이면 낡은 쪽이 통과 방향으로 틀림 — 실제로 그렇게 됨.

    `references/web-playwright.md` 가 §3.4 의 옛 판이었고, `errors` 검사도 0건 검사도 없어
    글로벌 셋업이 죽은 실행을 PASS 로 냈음. 이 테스트가 재는 것은 사본의 부재이고, 여기서
    돌리는 것은 SKILL.md 하나뿐이므로 사본이 생기면 아무 테스트도 그것을 안 봄."""
    # 출하 표면 전부 — `skills/` 만 보면 templates·USAGE·rules 에 생긴 사본이 안 잡힘.
    # 목록을 git 에서 받는 이유는 둘: `docs/` 밖의 미추적 스크래치(.superpowers/ 등)가 가드를
    # 흔들지 못하게, 그리고 출하되는 것과 재는 것이 같은 집합이 되게. `docs/` 는 설계·플랜
    # 이력이라 옛 판을 담는 것이 그 문서의 일이고 아무도 실행 안 함.
    # `-z` 는 취향이 아니라 정확성 — 기본 출력은 공백에서 쪼개지고, 비ASCII 경로는 git 이
    # C-인용해 내보냄(core.quotePath). 한글 문서가 기본인 저장소에서 첫 한글 파일명이
    # 사유 없는 붉은 줄이 됨.
    tracked = [
        rel
        for rel in run_bounded(
            ["git", "-C", str(REPO), "ls-files", "-z", "*.md"],
            text=True,
            # `replace` — UTF-8 아닌 경로 하나가 디코드 예외로 이 가드를 통째로 끝내지 않게.
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.split("\0")
        if rel
    ]
    carriers = sorted(
        rel
        for rel in tracked
        if not rel.startswith("docs/")
        and any(a in (REPO / rel).read_text(encoding="utf-8") for a in _SNIPPET_ANCHORS)
    )
    assert carriers == ["skills/integration/SKILL.md"], (
        f"판정 스니펫이 여러 문서에 실려 있음: {carriers} — SSOT 하나만 두고 나머지는 링크"
    )


def test_the_snippets_carry_nothing_the_shell_would_expand():
    """블록은 큰따옴표 안에 JS 를 담음 — `$` 나 백틱이 들어오면 bash 가 먼저 먹어 출하본만
    깨짐. 위 테스트들이 bash 로 돌리므로 깨진 것은 잡히지만, 사유가 판정 결함처럼 보임."""
    for block in _node_blocks():
        assert "$" not in block, "스니펫에 `$` — bash 가 확장함"
        assert "`" not in block, "스니펫에 백틱 — bash 가 명령 치환으로 읽음"
