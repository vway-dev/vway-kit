"""전파 변경 계획(JSON) 검산 — `alm-fetch` 가 낸 것을 부모가 쓰기 전에 기계로 읽음.

`alm_layers` 의 형제 — 판정만 하고 MCP 는 안 침. 이 경로의 집계 층이 여기 하나뿐인 이유는
Recoble PAT 가 local MCP 스코프라 스크립트가 보드를 못 치기 때문이고, 계획 파일은 로컬이라
칠 수 있음.

키 집합의 SSOT 는 `skills/alm-fetch/references/plan-schema.md`. 여기서 그 문서에 없는 키를
요구하면 fetch 가 못 만드는 것을 요구하는 것이고, 그것이 조용한 전파 중단이 됨.

종료 코드는 **둘로 갈림**. `3` 은 계획이 규칙과 어긋난다는 뜻이고 부모는 중단함. 그 밖의
비영 코드는 전부 내부 오류라 부모가 기존 경로로 폴백함 — 파이썬 미포착 예외(1)와 argparse
사용법 오류(2)가 그리로 떨어져야 하므로 규칙 위반이 그 둘을 쓰면 안 됨.

`propagate` 는 `--propagate <json>` 또는 `--config <vdev-config.yaml>` 로 옴. 후자에서
`alm.recoble.propagate` 를 꺼냄 — `propagate.json` 을 만드는 단계가 계획 전체에 없어서고,
둘 다 오면 `--propagate` 가 이김. `propagate.depth`·`status`·`progress` 가 실려 있으면 그것이
권위임 — 계획의 같은 값과 어긋나거나, `off` 인 축에 제안이 있으면 위반. `propagate` 가 `{}`
(둘 다 안 옴)면 이 셋은 판정하지 않음 — 무엇이 맞는지 모르는 채로 계획을 의심할 근거가
없어서임. PyYAML 은 `--config` 를 실제로 쓸 때만 임포트 — 없는 호스트에서도 `--propagate`
경로는 그대로 삶. `--status-off` 는 불러온 블록의 `status` 만 task-sync 전파 전용
모드를 위해 `off` 로 만듦.

`progress`·`coverage_status` 는 검증하지 않고 **도출**함 — 검산된 `ratio` 가 있으면 정답을
스크립트가 알고, fork 의 산술을 믿을 이유도 거부할 이유도 없어서임. 어긋나면 경고 한 줄에
도출값을 쓰고 종료 코드는 그대로 0. 식의 SSOT 는 `recoble-propagation.md` 「판정」.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from _vway_paths import force_utf8_io
except ImportError:
    from scripts._vway_paths import force_utf8_io

VIOLATION = 3
INTERNAL = 4
# SSOT: skills/task-sync/references/recoble-propagation.md 「연쇄」의 멈춤 문장("판정한 상위가
# 100 에 닿았는데 …") — 숫자를 고치면 그 문장도 같이 고침. 드리프트는 tests/alm_plan_check 가
# 그 문장에서 숫자를 직접 읽어 여기와 대조.
VISIT_CAP = 100


def _status_meta(board: dict) -> dict[str, dict]:
    """상태 key → `list_workboard_statuses` 원소(`done`·`statusGroup`·`sortOrder`)."""
    return {s["key"]: s for s in board.get("statuses", [])}


def _grade(statuses: dict[str, dict], key: str | None) -> int | None:
    """`recoble-status.md` 「등급」— 보드 플래그만으로 매길 수 있는 셋(0·1·3).

    검토(2)는 보드별 `status_review` config 를 알아야 정해지고, 그 config 의 보드 id·이름
    해석을 여기 한 벌 더 두면 SSOT 가 경고하는 "키 열거 가드" 드리프트가 생김 — 그래서
    스크립트는 검토를 매기지 않음. 못 매기면 `None` — 그 항목의 전진은 판정 보류, 부모의
    쓰기 직전 재대조가 SSOT 전 절차를 밟는 마지막 방어선."""
    if key is None:
        return None
    meta = statuses.get(key)
    if meta is None:
        return None
    if meta.get("done") is True:
        return 3
    if "done" not in meta and meta.get("statusGroup") == "DONE":
        return 3
    if meta.get("statusGroup") == "TODO":
        return 0
    if meta.get("statusGroup") == "IN_PROGRESS":
        siblings = [s for s in statuses.values() if s.get("statusGroup") == "IN_PROGRESS"]
        if meta.get("sortOrder", 0) == min(s.get("sortOrder", 0) for s in siblings):
            return 1
    return None


def _layers_declaring(layers: dict, field: str) -> set[str]:
    """`fields` 에 `field` 를 선언한 계층 키.

    `alm_layers.py` 의 `resolve_layers()` 출력을 그대로 받음 — `layers["layers"]` 는
    `{key, fields, ...}` 원소의 **리스트**(딕셔너리 아님)."""
    declared = layers.get("layers") or []
    return {
        layer["key"]
        for layer in declared
        if isinstance(layer, dict) and (layer.get("fields") or {}).get(field)
    }


def _field_layers(layers: dict) -> set[str]:
    """`latest_result` 를 선언한 계층 — 그 하위의 판정 근거는 상태가 아니라 그 필드."""
    return _layers_declaring(layers, "latest_result")


def _feature_design_layers(layers: dict) -> set[str]:
    """`feature_design` 계층 키 — 기능마다 공유되는 설계서라 전파의 상위도 하위도 아님."""
    declared = layers.get("layers") or []
    return {
        layer["key"]
        for layer in declared
        if isinstance(layer, dict) and layer.get("feature_design") is True
    }


def _derive_progress(done: int, total: int) -> int | None:
    """`⌊done×100/total + ½⌋` — 0.5 는 올림(1/8 → 13).

    정수 식이라 부동소수 오차도 파이썬 `round` 의 은행가 반올림도 없음. 하위가 없으면
    비율이 없으므로 `None`."""
    if total <= 0:
        return None
    return (done * 200 + total) // (total * 2)


def _derive_coverage(done: int, total: int) -> str:
    """하위집합이 비면 `UNCOVERED`, 전부 끝나면 `COVERED`, 하나라도 남으면 `NOT_COVERED`."""
    if total == 0:
        return "UNCOVERED"
    return "COVERED" if done == total else "NOT_COVERED"


def _topological_order(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """(위상 순 목록, 순환에 갇혀 못 정렬된 id 목록) — 후자가 비면 정상.

    각 row 는 `id` 와 `depends_on`(필드명 → id 목록) 을 가짐. 참조가 이 rows 밖의 id 면
    이미 끝난 것으로 침 — 전파 계획 밖 항목에까지 쓰기 순서를 강제할 수 없어서임."""
    by_id = {r["id"]: r for r in rows}
    remaining = {
        r["id"]: {d for ids in (r.get("depends_on") or {}).values() for d in ids if d in by_id}
        for r in rows
    }
    done: set[str] = set()
    ordered: list[dict] = []
    while remaining:
        ready = sorted(k for k, deps in remaining.items() if deps <= done)
        if not ready:
            return ordered, sorted(remaining)
        for key in ready:
            ordered.append(by_id[key])
            done.add(key)
            del remaining[key]
    return ordered, []


def check_plan(plan: dict, layers: dict, propagate: dict) -> list[str]:
    """규칙 위반 사유 목록. 빈 목록이면 통과."""
    problems: list[str] = []
    boards = plan.get("boards") or {}
    entries = plan.get("entries") or []
    ids = {e["item"]["id"] for e in entries}
    fielded = _field_layers(layers)
    shared = _feature_design_layers(layers)

    config_depth = propagate.get("depth")
    plan_depth = plan.get("depth", 0)
    if isinstance(config_depth, int):
        if plan_depth != config_depth:
            problems.append(
                f"계획의 depth {plan_depth} 가 config 의 propagate.depth {config_depth} 와 다르다"
            )
        depth = config_depth
    else:
        depth = plan_depth

    status_off = propagate.get("status") == "off"
    progress_off = propagate.get("progress") == "off"

    if len(entries) > VISIT_CAP:
        problems.append(f"방문이 {len(entries)}개로 상한 {VISIT_CAP} 을 넘었다")
    if plan.get("visit_cap_hit") and len(entries) != VISIT_CAP:
        problems.append(
            f"visit_cap_hit 이 true 인데 방문이 {len(entries)}개다(상한 {VISIT_CAP} 이어야 한다)"
        )

    for e in entries:
        who = e["item"]["id"]
        enum = e.get("enumeration") or {}
        proposed = e.get("proposed")

        if not enum.get("complete", False) and proposed is not None:
            problems.append(f"{who}: enumeration 이 불완전한데 제안이 있다")

        children = e.get("children") or []
        ratio = e.get("ratio") or {}
        done = sum(1 for c in children if c.get("done"))
        if (ratio.get("done"), ratio.get("total")) != (done, len(children)):
            problems.append(f"{who}: ratio {ratio} 가 children {done}/{len(children)} 과 다르다")

        total_r = ratio.get("total")
        if total_r:
            done_r = ratio.get("done")
            if done_r == total_r:
                implied = "full"
            elif done_r and 0 < done_r < total_r:
                implied = "partial"
            else:
                implied = "none"
            branch = e.get("branch")
            if branch != implied:
                problems.append(
                    f"{who}: branch {branch} 는 ratio {ratio} 가 뜻하는 {implied} 와 다르다"
                )

        if depth and e.get("level", 0) > depth:
            problems.append(f"{who}: level {e.get('level')} 이 depth {depth} 를 넘는다")

        if e.get("layer_mode") == "declared":
            for c in children:
                if c.get("layer") in fielded and c.get("basis") != "latest_result":
                    problems.append(
                        f"{who}: 케이스 하위 {c.get('id')} 를 latest_result 아닌 것으로 판정했다"
                    )

        if shared:
            if e.get("layer_mode") != "declared":
                problems.append(f"{who}: 기능 설계 계층이 선언됐는데 계층을 해석하지 않고 판정했다")
            if e.get("layer") in shared:
                problems.append(f"{who}: 기능 설계 항목을 전파 상위로 판정했다")
            for c in children:
                if c.get("layer") in shared:
                    problems.append(f"{who}: 기능 설계 항목 {c.get('id')} 를 하위로 셌다")

        if proposed:
            if status_off and proposed.get("status"):
                problems.append(f"{who}: propagate.status 가 off 인데 제안 상태가 있다")
            if progress_off and proposed.get("progress") is not None:
                problems.append(f"{who}: propagate.progress 가 off 인데 제안 progress 가 있다")

            for dep_ids in (proposed.get("depends_on") or {}).values():
                for dep in dep_ids:
                    if dep not in ids:
                        problems.append(f"{who}: depends_on 이 계획에 없는 {dep} 를 지목한다")

            if proposed.get("status"):
                board = boards.get(e["item"].get("projectId")) or {}
                statuses = _status_meta(board)
                target = proposed["status"]
                if target not in statuses:
                    problems.append(f"{who}: 제안 상태 {target} 가 그 보드에 없다")
                else:
                    now = (e.get("current") or {}).get("status")
                    now_grade = _grade(statuses, now)
                    target_grade = _grade(statuses, target)
                    if (
                        now_grade is not None
                        and target_grade is not None
                        and target_grade <= now_grade
                    ):
                        problems.append(f"{who}: {now} → {target} 는 전진이 아니다")

    write_rows = [
        {"id": e["item"]["id"], "depends_on": (e.get("proposed") or {}).get("depends_on")}
        for e in entries
        if e.get("proposed")
    ]
    _, stuck = _topological_order(write_rows)
    if stuck:
        problems.append(f"depends_on 이 순환한다: {', '.join(stuck)}")

    return problems


def minimal_writes(
    plan: dict,
    layers: dict | None = None,
    propagate: dict | None = None,
    warnings: list[str] | None = None,
) -> list[dict]:
    """부모가 읽을 최소 목록. 제안이 없는 항목은 쓰기가 아니므로 빠짐.

    위상 순 — `depends_on` 이 앞선 항목을 먼저 냄. `check_plan` 이 순환을 이미 막았어야
    하므로, 여기서 순환이 남으면(직접 호출 등) 방어적으로 원래 순서를 그대로 냄.

    `progress` 는 `propagate.progress == "rollup"` 일 때, `coverage_status` 는 항목의 계층을
    `layers` 에서 알 수 있을 때 `ratio` 에서 다시 도출해 제안을 덮음. 계층을 알면 선언이 없는
    것도 답이라 `None` 을 씀. 근거가 없으면(설정 없음 · `layer` 가 `None` · `layer_mode` 가
    `fallback` · `layers` 없음) 제안을 그대로 둠. 덮은 값이 제안과 다르면 `warnings` 에 한 줄."""
    rollup = (propagate or {}).get("progress") == "rollup"
    covered = _layers_declaring(layers, "coverage_status") if layers else set()
    rows = []
    for e in plan.get("entries") or []:
        proposed = e.get("proposed")
        if not proposed:
            continue
        out = {k: v for k, v in proposed.items() if k != "depends_on"}
        ratio = e.get("ratio") or {}
        done, total = ratio.get("done"), ratio.get("total")
        if isinstance(done, int) and isinstance(total, int):
            derived: dict = {}
            if rollup:
                derived["progress"] = _derive_progress(done, total)
            if layers and e.get("layer_mode") == "declared" and e.get("layer"):
                derived["coverage_status"] = (
                    _derive_coverage(done, total) if e["layer"] in covered else None
                )
            for key, value in derived.items():
                if out.get(key) != value and warnings is not None:
                    warnings.append(
                        f"{e['item']['id']}: {key} 제안 {out.get(key)!r} 대신 "
                        f"도출값 {value!r} 를 씀"
                    )
                out[key] = value
        rows.append(
            {
                "id": e["item"]["id"],
                "name": e["item"].get("name"),
                "projectId": e["item"].get("projectId"),
                "level": e.get("level"),
                "current": e.get("current"),
                "proposed": out,
                "depends_on": proposed.get("depends_on") or {},
            }
        )
    ordered, stuck = _topological_order(rows)
    return rows if stuck else ordered


def _plan_shape_ok(plan: dict) -> bool:
    """스키마 필수 최상위 키가 다 있고 모양이 맞는가.

    `entries: []` 는 정당한 "할 일 없음" — 이 검사는 그 값이 아니라 **키의 존재와 형**만 봄.
    부재·오형은 계획이 아예 못 만들어진 것(내부 오류)이지 규칙 위반이 아님."""
    return (
        isinstance(plan, dict)
        and isinstance(plan.get("space"), str)
        and isinstance(plan.get("boards"), dict)
        and isinstance(plan.get("entries"), list)
    )


def _load(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_config_propagate(path: str) -> dict:
    """`--config` 로 받은 vdev-config.yaml 에서 `alm.recoble.propagate` 만 꺼냄.

    부재·비dict 는 `{}`. YAML 파싱 실패는 `ValueError` 로 바꿔 던짐 — 호출부의
    `_load` 실패 처리와 같은 자리에서 잡히게.
    """
    import yaml

    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(data, dict):
        return {}
    alm = data.get("alm")
    recoble = alm.get("recoble") if isinstance(alm, dict) else None
    if not isinstance(recoble, dict):
        return {}
    propagate = recoble.get("propagate")
    return propagate if isinstance(propagate, dict) else {}


def main(argv: list[str] | None = None) -> int:
    force_utf8_io()
    ap = argparse.ArgumentParser(description="전파 변경 계획 검산")
    ap.add_argument("plan")
    ap.add_argument("--layers")
    ap.add_argument("--propagate")
    ap.add_argument("--config")
    ap.add_argument("--status-off", action="store_true")
    args = ap.parse_args(argv)

    if args.status_off and not (args.config or args.propagate):
        ap.error("--status-off needs --config or --propagate")

    try:
        plan = _load(args.plan)
        layers = _load(args.layers)
        if args.propagate:
            propagate = _load(args.propagate)
        elif args.config:
            propagate = _load_config_propagate(args.config)
        else:
            propagate = {}
        if args.status_off:
            propagate = {**(propagate or {}), "status": "off"}
    except (OSError, ValueError, ImportError) as exc:
        print(f"계획을 읽지 못했다: {exc}", file=sys.stderr)
        return INTERNAL

    if not _plan_shape_ok(plan):
        print("계획이 스키마 최상위 키(space·boards·entries)를 갖추지 못했다", file=sys.stderr)
        return INTERNAL

    problems = check_plan(plan, layers, propagate)
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return VIOLATION

    warnings: list[str] = []
    rows = minimal_writes(plan, layers, propagate, warnings)
    for w in warnings:
        print(w, file=sys.stderr)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
