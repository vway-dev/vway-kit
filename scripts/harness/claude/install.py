"""Claude Code 호스트의 settings.json 에 커밋 게이트와 vway 마켓을 등록·해제함.

- 게이트 엔트리는 `harness.gate_spec.GATE` 에서 렌더 — 값은 기존 호스트가 이미 가진
  엔트리와 바이트 단위로 같아야 함(`tests/harnesses/claude/`).
- `vdev_init_setup` 은 옛 이름(`register_gate`·`_gate_hook_remains` …)으로 이것을
  re-export 하고, 게이트 파일 존재 검사(`_installed`)만 자기 쪽에 둠.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

try:
    from harness.gate_spec import GATE
except ImportError:
    from scripts.harness.gate_spec import GATE

try:
    from harness.jsonfile import load_json_object, why, write_json, write_or_remove
except ImportError:
    from scripts.harness.jsonfile import load_json_object, why, write_json, write_or_remove

# settings.json 에 등록할 커밋 게이트(호스트 경로로 HOST 사본 실행). `if` 필드는
# 넣지 않음 — precommit-runner.sh 가 stdin 을 직접 걸러냄(빌드별 차이 회피).
# 어떤 훅 command 가 게이트 자신의 것인가. 스크립트 이름만으로는 부족 — 자기
# `tools/precommit-runner.sh` 훅을 가진 호스트의 것이 이 플러그인이 쓴 것처럼 이 경로로
# 고쳐 쓰이고 자기 엔트리 밖으로 옮겨짐. 두 낱말을 함께 보면 호스트 어디에 스크립트가
# 놓였든 매칭이 유지됨(구버전 평면 경로 `.claude/vway-kit/precommit-runner.sh` 도 잡음).
GATE_MARKER = ("vway-kit", "precommit-runner.sh")
GATE_COMMAND = f'bash "${{CLAUDE_PROJECT_DIR:-.}}/{GATE.runner_rel}"'
GATE_STATUS = GATE.status  # 재명명 시 register 가 보정
GATE_ENTRY = {
    "matcher": "Bash",
    "hooks": [
        {
            "type": "command",
            "shell": "bash",
            "command": GATE_COMMAND,
            "timeout": GATE.timeout,
            "statusMessage": GATE_STATUS,
        }
    ],
}

# vway 마켓을 호스트 settings.json 의 extraKnownMarketplaces 에 autoUpdate=true 로
# 등록함. 배포자는 marketplace.json 으로 자동 업데이트를 강제할 수 없는 보안 경계라
# (서드파티가 동의 없이 코드를 자동 fetch+실행하게 막음), 호스트가 명시적으로 켜는 이
# 경로가 유일. 호스트 repo 에 커밋되면 팀원 모두 auto-update 를 켠 채 마켓을
# 등록받음. source 는 `github`+repo 로 둠(`git`+url 은 자동갱신 신뢰성이 낮음 —
# 표준/권장 형식이자 plugin.json source 와 일치). 비공개 repo 백그라운드 fetch 는 결국
# git clone/fetch 로 동작하는데 git 은 GITHUB_TOKEN 을 직접 읽지 않으므로, env 토큰을
# 넘기는 github.com 자격증명 헬퍼가 필요 — detect_autoupdate_auth 가 토큰·자격증명
# 헬퍼·insteadOf 충돌을 점검·안내함.
MARKETPLACE_NAME = "vway"
MARKETPLACE_REPO = "vway-dev/vway-kit"
MARKETPLACE_URL = f"https://github.com/{MARKETPLACE_REPO}"  # insteadOf 예외 안내용(.git 없이)
MARKETPLACE_ENTRY = {
    "source": {"source": "github", "repo": MARKETPLACE_REPO},
    "autoUpdate": True,
}


def load_settings(host: Path) -> tuple[Path, dict | None, str | None]:
    """settings.json 경로·파싱결과를 반환. 읽을 수 없으면 (path, None, 에러메시지) —
    `data is None` 이면 사유는 **반드시** 있으므로 호출부는 그것을 그대로 보고함."""
    settings = host / ".claude" / "settings.json"
    try:
        settings.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return settings, None, f"  [!] .claude 를 만들지 못했습니다({why(exc)}) — 수동 확인 필요"
    data, err = load_json_object(settings, "settings.json")
    return settings, data, err


def is_gate_hook(hook: object) -> bool:
    """게이트 자신의 훅인가. 호스트가 문자열 아닌 것으로 쓴 `command` 는 그것이
    아니고, 그것에 `in` 을 묻는 것은 raise 함."""
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return False
    return all(word in hook["command"] for word in GATE_MARKER)


# 매처를 **이름**으로 남게 하는 알파벳(hooks 레퍼런스). 그 안에서는 두 방언이 일치함 —
# `|` 는 양쪽에서 대안이고 나머지는 전부 리터럴이라 — 같은 문자열을 양쪽으로 읽고 답을
# 비교할 수 있음.
_EXACT_MATCHER_RE = re.compile(r"[A-Za-z0-9_\- ,|]*")


def covers_bash(matcher: object) -> bool | None:
    """PreToolUse 매처가 Bash 에 발화하는가 — 커밋이 도착하는 유일한 도구.
    True·False, 또는 이 스크립트가 말할 수 없으면 None.

    hooks 레퍼런스가 정의하는 대로 세 갈래로 읽음: `*`·빈 매처·매처 부재는 모든 도구,
    이름 알파벳으로만 철자된 매처는 도구 이름 하나 또는 `|`/`,` 목록, 그 밖은 JavaScript
    정규식. 여기서 정할 수 있는 것은 앞의 둘뿐 — 파이썬 방언은 JavaScript 의 것이
    아니고(`(?i)`·`\\Z` 는 파이썬만의 것), 쉼표 구분자와 이름 주변 공백은 이것이 도는 가장
    오래된 호스트보다 나중 것이라 거기서는 같은 텍스트가 패턴으로 읽힘. 둘 다 미판정.

    미판정은 "발화하지 않음" 이 아님: 그렇게 다루면 호스트가 일부러 앵커한 `^Bash$` 밑에서
    게이트 훅이 뽑혀 나오고 보고는 그 엔트리가 발화한 적 없다고 말하는데, 거짓. 미판정은
    엔트리와 그 매처를 그대로 두고 게이트 자신의 엔트리를 더함 — 그래서 어느 쪽이든 게이트는
    존재함. 그 안의 게이트 훅은 여전히 현재 경로로 끌어올려짐, 그 엔트리에서 이 플러그인이
    쓴 유일한 것이 그것이므로.
    """
    if matcher is None or matcher in ("", "*"):
        return True
    if not isinstance(matcher, str):
        return None
    if not _EXACT_MATCHER_RE.fullmatch(matcher):
        return None
    as_list = GATE_ENTRY["matcher"] in [name.strip() for name in re.split(r"[|,]", matcher)]
    as_pattern = re.search(matcher, GATE_ENTRY["matcher"]) is not None
    return as_list if as_list == as_pattern else None


def register(host: Path) -> str:
    """커밋 게이트를 .claude/settings.json 에 등록. 이미 있으면 skip, 명령 경로가
    구버전이면 최신 경로로 보정(평면→scripts/ 이전 시 깨지지 않게)."""
    settings, data, err = load_settings(host)
    if data is None:
        return err
    if not isinstance(data.get("hooks", {}), dict):
        return "  [!] settings.json hooks 형식 비정상 — 게이트 미등록(수동 확인)"
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    if not isinstance(pre, list):
        return "  [!] hooks.PreToolUse 형식 비정상 — 게이트 미등록(수동 확인)"
    entries = [e for e in pre if isinstance(e, dict)]
    # 매처가 훅의 발화 여부를 정하므로, Bash 를 놓치는 매처 아래 있는 게이트 훅은 게이트가
    # 아님 — 그것을 게이트로 세면 호스트가 갖고 있지도 않은 게이트를 등록됐다고 읽음.
    # 그 엔트리 자체는 **호스트의 것**: 호스트 자신의 훅을 담고 있을 수 있고 매처가 여러
    # 도구를 나열하고 있을 수도 있음. 그래서 발화하지 않는 엔트리에서 게이트 훅만 빼 오고
    # 나머지는 전부 그대로 둠 — 매처도, `hooks` 옆의 키들도, 비워진 엔트리 자체도.
    # 매처를 고쳐 쓰면 호스트가 그 엔트리에 넣어 둔 다른 훅 전부가 다른 도구를 겨냥하게 됨.
    moved = undecided = 0
    for entry in entries:
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            continue
        covers = covers_bash(entry.get("matcher"))
        if covers is None:
            undecided += sum(1 for h in hooks if is_gate_hook(h))
        elif not covers:
            kept = [h for h in hooks if not is_gate_hook(h)]
            moved += len(hooks) - len(kept)
            entry["hooks"] = kept
    gate_hooks = [
        h
        for e in entries
        if isinstance(e.get("hooks"), list)
        for h in e["hooks"]
        if is_gate_hook(h)
    ]
    # 발화한다고 **알려진** 매처 아래의 훅만 게이트. 이 스크립트가 판정할 수 없는 매처
    # 아래의 것은 이미 그 일을 하고 있을 수도 있어 그대로 두지만, 아닐 수도 있어 게이트로
    # 세지 않음.
    firing = [
        h
        for e in entries
        if isinstance(e.get("hooks"), list) and covers_bash(e.get("matcher"))
        for h in e["hooks"]
        if is_gate_hook(h)
    ]
    added = not firing
    if added:
        pre.append(copy.deepcopy(GATE_ENTRY))
    # 이미 등록됨 — 구버전 경로를 가리키는 **모든** 엔트리를 최신 경로로 보정함
    # (첫 엔트리만 고치면 중복 stale 엔트리가 삭제된 flat 경로를 영구히 가리킴).
    # 이 플러그인이 쓰는 훅이 아닌 것은 전부 그것으로 수리함. command 와 상태 줄은
    # 플러그인 업데이트에서 흘러가지만, 정작 문제가 되는 필드는 호스트가 **더할** 수 있는
    # 것들: 게이트 훅의 `if` 는 빌드별로 발화를 막고(Invariant 4), `async` 는 그것을
    # deny 할 수 없는 자리로 옮기며, `command` 아닌 `type` 은 다른 것을 돌림 — 하나같이
    # 등록됐다고 보고되면서 아무것에도 발화하지 않는 게이트.
    stock = GATE_ENTRY["hooks"][0]
    stale = [h for h in gate_hooks if h != stock]
    note = ""
    if data.get("disableAllHooks") is True:
        note += ", settings.json 의 disableAllHooks 로 훅이 전혀 실행되지 않습니다"
    if len(firing) > 1:
        note += f", 발화하는 게이트 훅 {len(firing)}개 — 커밋마다 그만큼 실행됩니다"
    if undecided:
        note += (
            f", 판정할 수 없는 matcher 아래 게이트 훅 {undecided}개"
            " — 발화한다면 그만큼 더 실행됩니다"
        )
    if not added and not stale and not moved:
        return f"  [=] 커밋 게이트 이미 등록됨 (skip{note})"
    for hook in stale:
        hook.clear()
        hook.update(copy.deepcopy(stock))
    failed = write_json(settings, data, host)
    if failed:
        return failed
    if added and moved:
        return (
            "  [+] 커밋 게이트 등록 (settings.json, Bash 에 발화하지 않는 항목에서 "
            f"{moved}건 이동{note})"
        )
    if added:
        return f"  [+] 커밋 게이트 등록 (settings.json{note})"
    return (
        f"  [+] 커밋 게이트 보정 (settings.json, {len(stale) + moved}건 — 게이트 훅은"
        f" 플러그인 원형으로 교체{note})"
    )


def register_marketplace(host: Path) -> str:
    """vway 마켓을 .claude/settings.json extraKnownMarketplaces 에 autoUpdate=true 로
    등록(없으면 추가, 있으면 autoUpdate 만 보정, 이미 true 면 skip). 소스는 보존함."""
    settings, data, err = load_settings(host)
    if data is None:
        return err
    mkts = data.setdefault("extraKnownMarketplaces", {})
    if not isinstance(mkts, dict):
        return "  [!] extraKnownMarketplaces 형식 비정상 — 마켓 미등록(수동 확인)"
    existing = mkts.get(MARKETPLACE_NAME)
    if isinstance(existing, dict):
        if existing.get("autoUpdate") is True:
            return "  [=] vway 마켓 autoUpdate 이미 켜짐 (skip)"
        existing["autoUpdate"] = True  # 소스는 보존, autoUpdate 만 보정
        msg = "  [+] vway 마켓 autoUpdate=true 보정"
    else:
        mkts[MARKETPLACE_NAME] = dict(MARKETPLACE_ENTRY)
        msg = "  [+] vway 마켓 등록 + autoUpdate=true"
    failed = write_json(settings, data, host)
    if failed:
        return failed
    return msg


def _strip_gate_hooks(entry: object) -> int:
    """엔트리 하나에서 게이트 자신의 훅만 뗌 — 몇 개인지 돌려주고, 엔트리는 남김.

    `register` 는 이미 Bash 에 발화하는 호스트 엔트리 안에는 게이트 훅을 그대로 두므로,
    게이트를 담은 엔트리가 호스트의 훅을 함께 담고 있을 수 있음 — 엔트리째 가져가면 그것들도
    함께 사라짐.
    """
    if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
        return 0
    hooks = entry["hooks"]
    entry["hooks"] = [h for h in hooks if not is_gate_hook(h)]
    return len(hooks) - len(entry["hooks"])


def _is_own_empty_entry(entry: object) -> bool:
    """이 플러그인이 쓰고 방금 비운 엔트리 — 호스트의 것이 하나도 들어 있지 않음."""
    return (
        isinstance(entry, dict)
        and set(entry) == set(GATE_ENTRY)
        and entry.get("matcher") == GATE_ENTRY["matcher"]
        and entry.get("hooks") == []
    )


def _save_or_drop(settings: Path, data: dict, host: Path, done: str) -> str:
    failed, dropped = write_or_remove(settings, data, host, "settings.json")
    return failed or (f"{done} — 남은 설정이 없어 settings.json 삭제" if dropped else done)


def unregister(host: Path) -> str:
    """settings.json 의 커밋 게이트 훅을 제거(없으면 skip)."""
    settings, data, err = load_settings(host)
    if data is None:
        return err
    hooks = data.get("hooks") if isinstance(data, dict) else None
    pre = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    if not isinstance(pre, list):
        return "  [=] 게이트 훅 없음 (skip)"
    if not sum(_strip_gate_hooks(entry) for entry in pre):
        return "  [=] 게이트 훅 없음 (skip)"
    hooks["PreToolUse"] = [e for e in pre if not _is_own_empty_entry(e)]
    if not hooks["PreToolUse"]:
        del hooks["PreToolUse"]
    if not hooks:
        del data["hooks"]
    return _save_or_drop(settings, data, host, "  [-] 커밋 게이트 해제 (settings.json)")


def unregister_marketplace(host: Path) -> str:
    """settings.json extraKnownMarketplaces 에서 vway 마켓 등록을 제거(없으면 skip)."""
    settings, data, err = load_settings(host)
    if data is None:
        return err
    mkts = data.get("extraKnownMarketplaces")
    if not isinstance(mkts, dict) or MARKETPLACE_NAME not in mkts:
        return "  [=] vway 마켓 등록 없음 (skip)"
    del mkts[MARKETPLACE_NAME]
    if not mkts:
        del data["extraKnownMarketplaces"]
    return _save_or_drop(settings, data, host, "  [-] vway 마켓 등록 해제 (settings.json)")


def problems(host: Path) -> list[str]:
    """커밋 게이트가 돌지 않을 이유 중 settings.json 만으로 말할 수 있는 것.

    실행이 남긴 것에서 되읽음: 파싱할 수 없는 settings.json, 없거나 발화하지 않는 매처
    아래 있는 게이트 훅, 그리고 나머지가 다 맞아도 그것을 침묵시키는 `disableAllHooks`.
    질문의 파일 절반 — 훅이 지목하는 스크립트가 디스크에 있는가 — 은 호출부가 물음.
    """
    out: list[str] = []
    _settings, data, _err = load_settings(host)
    if data is None:
        out.append(
            "settings.json 을 읽지 못해 커밋 게이트를 확인할 수 없습니다 — 위 [!] 를"
            " 해결한 뒤 /vdev-init 를 다시 실행하세요."
        )
        return out
    hooks = data.get("hooks")
    pre = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    # 훅은 이 플러그인이 쓰는 그것이어야 함, 단지 이 플러그인의 것 중 하나가 아니라:
    # `if` 를 도로 떼는 수리는 쓰기가 내려앉을 때만 내려앉고, 판정할 수 없는 매처는
    # 발화하지 못하는 매처가 아님 — `^Bash$` 를 앵커한 호스트에게는 게이트가 있고,
    # 아니라고 말하는 것은 고장나지 않은 것을 고치러 보내는 일.
    firing = any(
        covers_bash(entry.get("matcher")) is not False
        and any(h == GATE_ENTRY["hooks"][0] for h in entry["hooks"])
        for entry in (pre if isinstance(pre, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list)
    )
    if not firing:
        out.append(
            "커밋 게이트가 settings.json 에 없습니다 — 위 [!] 를 해결한 뒤 /vdev-init 를"
            " 다시 실행하세요."
        )
    if data.get("disableAllHooks") is True:
        out.append(
            "settings.json 의 disableAllHooks 가 켜져 있어 커밋 게이트를 포함한 모든"
            " 훅이 실행되지 않습니다 — 끄세요."
        )
    return out


def hook_remains(host: Path) -> bool:
    """호스트 settings.json 에 게이트 훅이 남아 있을 수 있는가.

    읽지 못하는 파일은 지우지도 못한 파일이고, 실행은 그 훅이 지목하는 스크립트를 이미
    지움 — 그래서 못 읽음은 남은 것으로 셈. 거기서 아니라고 답하면 아무것도 가리키지
    않는 훅 위에 `정리 완료.` 가 찍히고, 그것이 이 함수가 막으려는 거짓말."""
    _settings, data, _err = load_settings(host)
    if data is None:
        return True
    hooks = data.get("hooks")
    pre = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    return any(
        is_gate_hook(h)
        for entry in (pre if isinstance(pre, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list)
        for h in entry["hooks"]
    )
