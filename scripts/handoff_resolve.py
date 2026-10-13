"""handoff 종류별 결정 로직 — 순수 함수. /task-sync · /task-import 가 호출해
각 종류의 (source_mode, write_mode, template_path, ...) 를 JSON 으로 받아 소비.

커밋 게이트가 아니므로 강제 차단과 무관. 결정 로직만 담고 실제 내용 생성(AI
대필, AskUserQuestion, Teamer PUT)은 호출자(커맨드/에이전트) 몫. 파싱/입력
오류 시 빈 결과를 돌려 호출자가 기존 동작으로 떨어지게 함.

각 함수는 인자로 받은 값만으로 결과를 반환하므로 단위 테스트 가능.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# 인코딩 방어·루트 폴백·config 경로는 공용 SSOT(_vway_paths)에서 가져옴(중복 정의
# 금지). handoff_resolve 는 플러그인 위치에서 실행되므로 형제 import 가 기본이고,
# 패키지(테스트)에서는 scripts._vway_paths 로 떨어짐.
try:
    from _vway_paths import (
        VWAY_DIR,
        force_utf8_io,
        host_root,
        legacy_template_path,
        plugin_root,
        template_rel,
        templates_lookup,
    )
    from _vway_paths import config_path as _config_path
except ImportError:
    from scripts._vway_paths import (
        VWAY_DIR,
        force_utf8_io,
        host_root,
        legacy_template_path,
        plugin_root,
        template_rel,
        templates_lookup,
    )
    from scripts._vway_paths import config_path as _config_path

AI_AUTHORS = {"ai", "llm", "agent"}

# 문자열 `field` 는 colXX·item_content 라는 Teamer 어휘로 굳어 있어 Recoble 이 해석할
# 수 없음 — 그래서 기본 대상인 댓글로 감. `literal`(value 보유)만 예외로 이 폴백을
# 타지 않음(resolve_field 참조).
RECOBLE_DEFAULT_FIELD = "comment"
# Recoble 에서 값이 쌓이는 대상: 댓글은 늘 새 댓글, 본문은 말미에 이어붙임.
RECOBLE_APPEND_FIELDS = {"comment", "description"}


def load_handoff_config(config_path: Path) -> dict:
    """vdev-config.yaml 의 handoff 트리(dict). 파일/키 없음·파싱 실패 시 {}."""
    import yaml

    if not config_path.is_file():
        return {}
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    handoff = data.get("handoff")
    return handoff if isinstance(handoff, dict) else {}


def is_ai_author(author: str) -> bool:
    """author 가 AI 주체(ai/llm/agent, 대소문자 무시)면 True."""
    return str(author).strip().lower() in AI_AUTHORS


def resolve_source_mode(spec: dict) -> str:
    """종류 spec → source_mode. value 최우선(literal), 다음 AskUserQuestion 토글·author."""
    if spec.get("value") is not None:
        return "literal"
    ai = is_ai_author(spec.get("author", ""))
    ask = spec.get("AskUserQuestion") is True
    if ai:
        return "ai_guided" if ask else "ai_auto"
    return "human_ask" if ask else "human_doc"


def resolve_field(spec: dict, provider: str) -> str | None:
    """이 provider 가 쓸 필드. dict 는 provider 별 명시 선언이므로, 키가 없으면
    None — 그 provider 에는 이 종류를 보내지 않음."""
    field = spec.get("field")
    if isinstance(field, dict):
        value = field.get(provider)
        return None if value is None else str(value)
    if provider == "recoble":
        # 문자열 field 는 Teamer 어휘라 Recoble 에선 기본 대상으로 떨어짐 — 단
        # `literal`(value 보유)은 예외. 특정 필드에 값을 꽂으라는 선언이지 할 말이
        # 아니어서, 폴백을 태우면 `done_flag: {field: col31, value: "완료"}` 가 본문이
        # "완료" 한 단어인 댓글로 매 sync 마다 쌓임. Recoble 로 보내려면 provider 별
        # dict 로 대상을 명시해야 하고, 그건 위 분기가 이미 통과시킴.
        return None if spec.get("value") is not None else RECOBLE_DEFAULT_FIELD
    return "" if field is None else str(field)


def resolve_write_mode(field: str, append: object = None, provider: str = "teamer") -> str:
    """append 가 불리언이면 우선(True→append, False→replace).
    아니면 provider 별 field 폴백."""
    if isinstance(append, bool):
        return "append" if append else "replace"
    if provider == "recoble":
        return "append" if field in RECOBLE_APPEND_FIELDS else "replace"
    return "append" if field == "item_content" else "replace"


def resolve_template_path(spec: dict, kind: str, plugin: Path, host: Path) -> str | None:
    """template 파일 해석 — rel 규칙은 `template_rel`, 탐색은 `templates_lookup` 이 소유.
    호스트 사본 우선·플러그인 폴백이고, 어느 쪽에도 없으면 None.

    확장자가 md 고정인 것은 본문 형식이 provider·필드와 무관하게 Markdown 하나이기
    때문 — 한 템플릿을 Teamer 필드도 Recoble 댓글·본문도 함께 씀. 형식이 갈리면 같은
    규칙을 담은 자매 파일 둘이 생기고, 한쪽만 고친 순간 두 ALM 이 다른 요약을 받음."""
    return templates_lookup(template_rel(kind, spec, "handoff"), host, plugin)


def legacy_template_warnings(config_path: Path, host: Path, provider: str = "teamer") -> list[str]:
    """구경로 `<host>/templates/` 에만 남은 양식을 종류 이름과 함께 알림.

    호스트 사본의 자리가 옮겨졌으므로 셋업을 아직 안 돌린 저장소는 자기 양식을 잃고
    출하본으로 떨어짐. 그것이 조용하면 나가는 요약이 자기 양식이 아님을 알 길이 없음 —
    `/vdev-init` 재실행이 이 알림과 원인을 함께 없앰.

    대상은 `resolve_handoff` 가 이 provider 로 실제 내보내는 것과 같은 집합임(시드가 선언
    전부를 보는 것과 갈리는 지점): `enable: true` 이고 이 provider 를 겨냥한 종류들, 그리고
    `handoff` 설정이 **아예 없을 때** 돌아가는 암묵 `summary`. 켜지 않았거나 다른 provider
    를 겨냥한 종류까지 알리면 아무것도 안 나가는데 나간다고 말하고(스킬은 같은 줄에서 '쓰지
    마라' 를 지시받음), 미설정 호스트를 빼면 정작 그 폴백을 타는 쪽이 조용해짐."""
    handoff = load_handoff_config(config_path)
    kinds: list[tuple[str, dict]] = (
        [
            (k, s)
            for k, s in handoff.items()
            if isinstance(s, dict)
            and s.get("enable") is True
            and resolve_field(s, provider) is not None
        ]
        if handoff
        else [("summary", {})]
    )
    warnings: list[str] = []
    for kind, spec in kinds:
        rel = template_rel(str(kind), spec, "handoff")
        if legacy_template_path(rel, host):
            warnings.append(
                f"{kind}: 구경로 templates/{rel} 은 더 읽지 않음 — "
                f"/vdev-init 을 다시 돌려 {VWAY_DIR}/templates/ 로 옮기세요"
            )
    return warnings


def resolve_handoff(
    config_path: Path, plugin: Path, host: Path, provider: str = "teamer"
) -> list[dict]:
    """enable:true 종류만 결정 결과 리스트로. 입력 이상은 건너뜀.

    provider 기본값이 teamer 인 것은 하위호환 — 문자열 `field` 어휘가 Teamer 의
    것이므로 인자 없는 호출은 그 어휘로 읽음."""
    handoff = load_handoff_config(config_path)
    result: list[dict] = []
    for kind, spec in handoff.items():
        if not isinstance(spec, dict) or spec.get("enable") is not True:
            continue
        field = resolve_field(spec, provider)
        if field is None:
            continue
        result.append(
            {
                # 경계에서 형을 맞춤 — YAML 은 `2024-01-01:` 를 date 로, `on:` 을 bool 로
                # 줌. 그대로 실으면 json 직렬화가 터져 handoff 단계 전체가 죽음
                # (자매 `alm_layers` 가 계층 키에 같은 것을 함).
                "kind": str(kind),
                "provider": provider,
                "author": spec.get("author", ""),
                "field": field,
                "value": spec.get("value"),
                "source_mode": resolve_source_mode(spec),
                "write_mode": resolve_write_mode(field, spec.get("append"), provider),
                "template_path": resolve_template_path(spec, kind, plugin, host),
                "instruction": spec.get("instruction", ""),
            }
        )
    return result


def main() -> None:
    force_utf8_io()
    parser = argparse.ArgumentParser(description="handoff 종류별 결정 결과를 JSON 으로 출력")
    parser.add_argument("config", nargs="?", help="vdev-config.yaml 경로")
    parser.add_argument("--provider", default="teamer", help="recoble | teamer")
    ns = parser.parse_args()
    config = Path(ns.config) if ns.config else _config_path(host_root())
    # `kinds` 가 비는 이유가 둘이라 `configured` 를 따로 냄 — handoff 설정이 아예 없어
    # 예전 동작(summary 기본 대상)으로 떨어져야 하는 경우와, 설정이 있는데 이 provider 를
    # 겨냥한 종류가 없어 **아무것도 보내면 안 되는** 경우는 정반대 행동을 요구함.
    print(
        json.dumps(
            {
                "provider": ns.provider,
                "configured": bool(load_handoff_config(config)),
                "kinds": resolve_handoff(config, plugin_root(), host_root(), ns.provider),
                # 결정에는 안 쓰이고 사람에게만 감 — 이 목록이 비지 않으면 호스트가 쓴
                # 양식이 아니라 출하본이 나가는 중임.
                "warnings": legacy_template_warnings(config, host_root(), ns.provider),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
