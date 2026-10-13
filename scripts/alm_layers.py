"""vdev-config 의 `alm.recoble.spaces[*].layers` 선언 → 계층별 결정(JSON).

`handoff_resolve` 의 형제 — 결정만 하고 MCP 호출·본문 생성은 호출자(`alm-trace`
스킬)가 함. 그래야 계층 그래프의 판정이 단위 테스트로 고정됨.

계층 키는 자유 문자열. 이 모듈은 `requirement`·`design` 같은 이름을 알지 못하며,
계층 간 의미는 `derives_from`·`verifies`·`marker`·`feature_design` 선언에서만 나옴 — 프로젝트마다
계층 어휘가 다르기 때문.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from _vway_paths import config_path as _config_path
    from _vway_paths import (
        force_utf8_io,
        host_root,
        legacy_template_path,
        plugin_root,
        template_rel,
        templates_lookup,
    )
except ImportError:
    from scripts._vway_paths import config_path as _config_path
    from scripts._vway_paths import (
        force_utf8_io,
        host_root,
        legacy_template_path,
        plugin_root,
        template_rel,
        templates_lookup,
    )


def load_layers_config(config_path: Path, space: str | None) -> tuple[dict, str | None]:
    """(layers 트리, 해석된 스페이스 키). 부재·비dict·파싱 실패는 ({}, space).

    space 가 None 이면 `alm.recoble.default` 를 씀 — /vdev Phase 0 가 스페이스를
    이미 해석했을 때는 그 값을 넘기고, 직접 실행은 config 기본값으로 떨어짐."""
    import yaml

    if not config_path.is_file():
        return {}, space
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}, space
    if not isinstance(data, dict):
        return {}, space
    alm = data.get("alm")
    recoble = alm.get("recoble") if isinstance(alm, dict) else None
    if not isinstance(recoble, dict):
        return {}, space
    key = space or recoble.get("default")
    spaces = recoble.get("spaces")
    if not isinstance(spaces, dict) or not isinstance(spaces.get(key), dict):
        return {}, key
    layers = spaces[key].get("layers")
    return (layers if isinstance(layers, dict) else {}), key


# 선언 가능한 키 전부. 여기 없는 키는 경고로 드러남 — 조용히 버리면 구버전 플러그인을 쓰는
# 호스트에서 새 선언이 통째로 무시돼도 아무도 모르고, 그 계층은 선언한 적 없는 것처럼 돎.
_LAYER_KEYS = frozenset(
    {
        "workboard",
        "template",
        "derives_from",
        "verifies",
        "marker",
        "status",
        "category",
        "defect",
        "fields",
        "run",
        "runs",
        "feature_design",
    }
)

# 필드 **역할** 이름. 보드의 실제 필드 key 는 호스트가 정하므로 그것을 여기 고정하면 이름이
# 다른 호스트에서 판정이 통째로 빠짐. 역할은 이 집합이 소유하고 key 는 `fields` 가 이음.
_FIELD_ROLES = frozenset(
    {
        "module",  # 설계 — 어느 배포·검증 단위
        "feature",  # 설계 — 어느 기능(코드 디렉터리와 1:1)
        "result",  # 실행 — 회차 판정
        "scope",  # 실행 — 이 회차가 돌기로 한 suite 집합(커버리지 분모)
        "build",  # 실행 — 검증 대상 커밋
        "environment",  # 실행 — 어느 환경
        "latest_result",  # 케이스 — 최신 판정
        "latest_run",  # 케이스 — 그 판정을 낸 회차
        "suite",  # 케이스 — 소속 suite
        "covers",  # 케이스 — 검증하는 수용 기준
        "coverage_status",  # 요구사항 — 상태와 분리된 커버리지 사실
    }
)


def _field_map(spec: dict) -> dict:
    """역할 → 보드 필드 key. 모르는 역할·빈 값은 빠진다(경고는 resolve_layers 가 냄)."""
    raw = spec.get("fields")
    if not isinstance(raw, dict):
        return {}
    return {role: str(key) for role, key in raw.items() if role in _FIELD_ROLES and key}


def _field_warnings(key: str, spec: dict) -> list[str]:
    raw = spec.get("fields")
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return [f"{key}.fields 가 dict 가 아니라 무시한다"]
    unknown = sorted(str(role) for role in set(raw) - _FIELD_ROLES)
    return [f"{key}.fields 의 '{role}' 는 모르는 역할 — 무시한다" for role in unknown]


def normalize_layer(key: str, spec: object, plugin: Path, host: Path) -> dict | None:
    """계층 선언 한 줄 → 결정 dict. spec 이 dict 가 아니면 None(호출자가 경고함).

    `workboard` 가 비어도 dict 를 돌려줌 — 그 판정은 그래프 검증(resolve_layers)이
    한 곳에서 하고, 여기서는 모양만 맞춤."""
    if not isinstance(spec, dict):
        return None
    return {
        "key": key,
        "workboard": str(spec.get("workboard") or ""),
        "template": templates_lookup(template_rel(key, spec, "alm"), host, plugin),
        "derives_from": spec.get("derives_from") or None,
        "verifies": spec.get("verifies") or None,
        "marker": spec.get("marker") is True,
        "status": spec.get("status") or None,
        "category": spec.get("category") or None,
        "defect": spec.get("defect") is True,
        "fields": _field_map(spec),
        "run": spec.get("run") is True,
        "runs": spec.get("runs") or None,
        "feature_design": spec.get("feature_design") is True,
        "direct_from": None,
    }


def _relations(layer: dict) -> list[str]:
    """이 계층이 참조하는 다른 계층 키들(순서 고정)."""
    return [layer[field] for field in ("derives_from", "verifies") if layer[field]]


def _topological(layers: list[dict]) -> list[dict] | None:
    """참조되는 계층이 먼저 오도록 정렬. 순환이면 None.

    앵커가 없으면 링크를 걸 대상이 없으므로 생성 순서가 곧 정확성임. 선언 순서를
    쓰지 않는 이유가 이것 — YAML 의 키 순서는 사람이 읽기 좋은 순서일 뿐."""
    remaining = {x["key"]: x for x in layers}
    ordered: list[dict] = []
    done: set[str] = set()
    while remaining:
        ready = [k for k, v in remaining.items() if all(r in done for r in _relations(v))]
        if not ready:
            return None
        for key in sorted(ready):
            ordered.append(remaining.pop(key))
            done.add(key)
    return ordered


def resolve_layers(config_path: Path, space: str | None, plugin: Path, host: Path) -> dict:
    """계층 선언 → 위상 정렬된 결정 리스트 + errors/warnings.

    errors 는 실행 중단(설정이 깨짐), warnings 는 그 항목만 빼고 진행. 이
    비대칭이 스펙의 중심 — 미선언은 옵트아웃이지만, 선언해 놓고 깨진 것은
    사용자가 쓰려던 기능이 조용히 꺼지는 것이라 알려야 함."""
    raw, resolved_space = load_layers_config(config_path, space)
    result = {
        "space": resolved_space,
        "configured": bool(raw),
        "layers": [],
        "errors": [],
        "warnings": [],
    }
    if not raw:
        return result

    layers: list[dict] = []
    for key, spec in raw.items():
        norm = normalize_layer(str(key), spec, plugin, host)
        if norm is None:
            result["warnings"].append(f"{key}: 선언이 dict 가 아니라 건너뛴다")
            continue
        for unknown in sorted(str(u) for u in set(spec) - _LAYER_KEYS):
            result["warnings"].append(f"{key}: 모르는 선언 '{unknown}' — 무시한다")
        result["warnings"].extend(_field_warnings(str(key), spec))
        if not norm["workboard"]:
            result["errors"].append(f"{key}: workboard 가 없다 — 만들 보드를 알 수 없다")
        if norm["template"] is None:
            result["warnings"].append(f"{key}: 템플릿 없음 — 본문을 서술로 만든다")
        # 호스트 사본의 자리가 VWAY_DIR 밑으로 옮겨졌으므로, 셋업을 아직 안 돌린
        # 저장소는 자기 양식을 잃고 출하본으로 떨어짐. 조용하면 원인을 못 찾음.
        if legacy_template_path(template_rel(str(key), spec, "alm"), host):
            result["warnings"].append(
                f"{key}: 구경로 templates/ 의 양식은 더 읽지 않는다 — "
                "/vdev-init 을 다시 돌려 옮겨라"
            )
        layers.append(norm)

    known = {x["key"] for x in layers}
    for layer in layers:
        for field in ("derives_from", "verifies"):
            target = layer[field]
            if target and target not in known:
                result["warnings"].append(f"{layer['key']}.{field} '{target}' 미선언 — 링크 생략")
                layer[field] = None

    # 회차 계층은 그래프의 노드이되 **전파의 하위가 아님** — relates_to 로만 붙음. 링크를
    # 그으면 옛 회차가 영원히 상위의 하위집합에 남아, 하위집합이 단조 증가해 페이지를 넘기고
    # 전파가 스스로 꺼짐. 선언에 링크가 서면 지우고 그 사실을 알림.
    runs = [x["key"] for x in layers if x["run"]]
    if len(runs) > 1:
        result["errors"].append(f"run 계층이 둘 이상이다: {', '.join(sorted(runs))}")
    run_keys = set(runs)
    for layer in layers:
        for field in ("derives_from", "verifies"):
            target = layer[field]
            # 나가는 링크(회차 자신이 건 것)와 들어오는 링크(남이 회차를 가리킨 것) 둘 다 막음 —
            # 한쪽만 막으면 `verifies: <회차>` 가 살아남아 회차가 그대로 하위집합에 쌓임.
            if layer["run"] and target:
                result["warnings"].append(
                    f"{layer['key']}.{field} 무시 — 회차는 전파 분모 밖이라 링크를 안 검"
                )
                layer[field] = None
            elif target in run_keys:
                result["warnings"].append(
                    f"{layer['key']}.{field} '{target}' 무시 — 회차를 가리키는 링크는 안 검"
                )
                layer[field] = None
        if not layer["run"]:
            continue
        if layer["runs"] and layer["runs"] not in known:
            result["warnings"].append(f"{layer['key']}.runs '{layer['runs']}' 미선언 — 무시함")
            layer["runs"] = None
        # defect 가 verifies 미선언을 경고하는 것과 같은 꼴 — 켜 놓고 못 쓰게 된 선언을 알림.
        if not layer["runs"]:
            result["warnings"].append(
                f"{layer['key']}: runs 미선언 — 이 회차가 어느 케이스 계층을 담는지 모름"
            )

    # 기능 설계 계층은 기능마다 한 항목이 오래 사는 설계서 — 여러 요구사항·작업이 공유하므로
    # 전파의 상위·하위가 될 수 없음(한 요구사항의 작업이 끝나 설계가 닫히면 그 설계를 공유한
    # 다른 요구사항도 닫힘). 그래서 설계에서 도출되는 계층에는 설계를 건너뛴 직접 도출 링크의
    # 대상을 계산해 둠 — 전파는 그 직접 링크를 타고 오름.
    designs = [x for x in layers if x["feature_design"]]
    if len(designs) > 1:
        names = ", ".join(sorted(x["key"] for x in designs))
        result["errors"].append(f"feature_design 계층이 둘 이상이다: {names}")
    for design in designs:
        clash = [flag for flag in ("marker", "defect", "run") if design[flag]]
        if clash:
            result["errors"].append(
                f"{design['key']}: feature_design 은 {', '.join(clash)} 플래그와 한 계층에 못 선다"
            )
    if len(designs) == 1:
        design = designs[0]
        if not design["derives_from"]:
            result["warnings"].append(
                f"{design['key']}: derives_from 미선언 — 작업을 요구사항에 직접 잇지 못한다"
            )
        for layer in layers:
            if layer["derives_from"] == design["key"]:
                layer["direct_from"] = design["derives_from"]
            # 설계를 검증하는 계층은 전파에서 설계와 함께 빠짐 — 켜 놓고 조용히 안 도는 선언.
            if layer["verifies"] == design["key"]:
                result["warnings"].append(
                    f"{layer['key']}.verifies '{design['key']}' — 기능 설계는 전파 밖이라 "
                    "이 검증은 아무것도 닫지 않는다"
                )

    markers = [x["key"] for x in layers if x["marker"]]
    if len(markers) > 1:
        result["errors"].append(f"marker 가 둘 이상이다: {', '.join(sorted(markers))}")
    elif not markers:
        result["warnings"].append("marker 계층 없음 — .vdev/alm 마커를 쓰지 않는다")

    # 결함 진입은 `defect: true` 계층 하나가 켬(marker 와 같은 꼴) — 미선언이면 결함 분기
    # 자체가 없고 모든 요청이 신규 요구사항으로 감(옵트인). 켠 뒤 못 쓰게 되는 조건 둘을
    # 여기서 잡는 이유는 alm-trace 가 그것을 실행 도중, 사람이 "결함" 을 고른 다음에야
    # 만나기 때문 — 그때 남는 선택지는 중단뿐임.
    defects = [x["key"] for x in layers if x["defect"]]
    if len(defects) > 1:
        result["errors"].append(f"defect 계층이 둘 이상이다: {', '.join(sorted(defects))}")
    elif defects:
        defect = next(x for x in layers if x["defect"])
        if not defect["verifies"]:
            result["warnings"].append(
                f"{defect['key']}: verifies 미선언 — 결함을 걸 계층이 없어 링크를 생략한다"
            )
        if not markers:
            result["warnings"].append(
                f"{defect['key']}: marker 계층이 없어 결함의 수정 작업을 만들 자리가 없다"
            )

    if result["errors"]:
        return result

    ordered = _topological(layers)
    if ordered is None:
        result["errors"].append("계층 참조가 순환한다 — 만들 순서를 정할 수 없다")
        return result
    result["layers"] = ordered
    return result


def main() -> None:
    force_utf8_io()
    parser = argparse.ArgumentParser(description="ALM 계층 선언의 해석 결과를 JSON 으로 출력")
    parser.add_argument("config", nargs="?", help="vdev-config.yaml 경로")
    parser.add_argument("--space", default=None, help="Recoble 스페이스 키 (생략 시 config 기본값)")
    ns = parser.parse_args()
    config = Path(ns.config) if ns.config else _config_path(host_root())
    print(
        json.dumps(
            resolve_layers(config, ns.space, plugin_root(), host_root()),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
