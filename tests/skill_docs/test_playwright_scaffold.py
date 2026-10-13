"""스캐폴드가 쓰는 config — CI 가 포트를 바꿔 넣을 수 있고, 트레이스 정책이 정해져 있는가.

이 스킬이 쓰는 `playwright.config` 는 `.github/workflows/e2e.yml` 이 그대로 실행하는 대상.
그래서 여기서 정해지는 두 가지가 워크플로 쪽 결정을 좌우함: baseURL 을 환경변수로 읽어야
CI 스택이 자기 포트를 넘길 수 있고, 트레이스·비디오 정책이 서 있어야 리포트 업로드가
안전한지 판정할 수 있음.
"""

from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "playwright-scaffold" / "SKILL.md"
REFERENCE = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "integration"
    / "references"
    / "web-playwright.md"
)


def test_scaffolded_config_reads_the_base_url_from_the_environment():
    # 같은 플러그인의 web-playwright.md 가 `process.env.BASE_URL` 을 규정함 — 스캐폴드가
    # 리터럴만 쓰면 산출물 둘이 어긋나고, CI 스택은 다른 포트를 넘길 방법이 없음.
    text = SKILL.read_text(encoding="utf-8")
    assert "process.env.BASE_URL" in REFERENCE.read_text(encoding="utf-8")
    # 스캐폴드 블록의 baseURL 줄 자체를 못박음: 환경변수로 읽고 리터럴은 `??` 폴백으로만.
    # "리터럴이 문서에 없다" 는 식의 약한 검사는 리터럴 줄이 다른 곳에 그대로 남아도 통과함.
    assert "baseURL: process.env.BASE_URL ?? 'http://localhost:3000'," in text


def test_scaffolded_config_declares_a_trace_policy():
    # 트레이스는 요청·응답 본문과 세션 토큰을 실어 나름 — 워크플로의 아티팩트 업로드가
    # 안전한지는 저기가 아니라 여기서 정해짐.
    text = SKILL.read_text(encoding="utf-8")
    assert "retain-on-failure" in text
    assert "video:" in text


def test_scaffold_reports_projects_when_a_config_already_exists():
    # 다중 앱 팬아웃은 Playwright 자신의 projects[] 몫이고, 전달 경로는 이 스킬임 —
    # 그래서 **자기가 쓰지 않는** 경우에도 무언가 말해야 함. 낱말 "projects" 만 보는
    # 검사는 이 변경 없이도 기존 산문이 만족시키므로, 이 편집이 실제로 더한 두 자리를
    # 각각 못박음: 스캐폴드 config 안의 projects[] 모양과, 보고 항목의 문구.
    text = SKILL.read_text(encoding="utf-8")
    assert "projects: [" in text
    assert "`projects[]` 모양" in text
