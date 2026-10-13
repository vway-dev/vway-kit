#!/usr/bin/env python3
"""Power Automate 웹훅으로 Teams 알림을 보냄. hook·스크립트에서 재사용.

채널별 웹훅 URL은 두 파일을 병합해 씀(local 이 tracked 를 덮어씀).
호스트 측 vway-kit 산출물은 .claude/vway-kit/ 아래 용도별로 모이고, 웹훅은
config/ 에 둠(호스트 루트 = CLAUDE_PROJECT_DIR, 없으면 git toplevel, 그다음
이 스크립트 위치 기준):
  - .claude/vway-kit/config/teams-webhooks.json        (git 추적: 감시 브랜치, 팀 공용)
  - .claude/vway-kit/config/.teams-webhooks.local.json (git 제외: personal·URL, 사용자별)

채널 용도:
  - personal        -> 응답 대기 / 중지 (사용자별, local 파일)
  - 그 외(브랜치명)  -> 같은 이름의 브랜치 push 시. tracked 파일은 모든 클론이 감시할
                       브랜치 이름을 쥐고, URL 은 --shared 로 등록하지 않는 한 local
                       파일에 남음 — Power Automate URL 이 `sig=` 자격증명을 실음.

personal 은 플러그인 옵션 `teams_webhook_personal`(plugin.json `userConfig`, sensitive)이
두 파일보다 우선 — Claude Code 가 훅 프로세스에 `PERSONAL_OPTION_ENV` 로 넘김.
채널의 URL 이 비었거나 없으면 조용히 skip 하므로 채널을 점진적으로 켤 수 있음.
알림 실패는 호출측으로 전파하지 않음 — 깨진 웹훅이 hook 을 막으면 안 됨.
personal 이 미설정이면 send() 가 stderr 로 등록 안내를 출력해 등록을 유도함.

사용법 (CLI):
  python teams_alert.py --channel personal --title "..." --text "..."
  python teams_alert.py --set personal https://...   # URL만 넣으면 자동 저장
  python teams_alert.py --set dev https://... [--shared]

사용법 (import):
  from teams_alert import send
  send("personal", "제목", "내용")
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# 호스트 루트 폴백·config 경로는 공용 SSOT(_vway_paths)에서 가져옴(중복 정의 금지).
# teams_alert 는 COPY_FILES 로 호스트에 복사돼 직접 실행되거나(형제 import) 테스트에서
# 패키지로 import 됨 — _vway_paths 모듈 docstring 의 양립 관용구 참조.
try:
    from _vway_paths import config_dir, force_utf8_io, host_root
except ImportError:
    from scripts._vway_paths import config_dir, force_utf8_io, host_root

# _host_root 는 옛 함수명. 하위호환(테스트·외부 참조)을 위해 공용 host_root 의 alias 로
# 노출. 폴백 로직(env → git toplevel → .claude 마커 → cwd)은 host_root 안에 있음.
_host_root = host_root

# 호스트 측 vway-kit config(웹훅)는 .claude/vway-kit/config/ 에 모임.
ROOT = host_root()
CONFIG_DIR = config_dir(ROOT)
TRACKED_FILE = CONFIG_DIR / "teams-webhooks.json"
LOCAL_FILE = CONFIG_DIR / ".teams-webhooks.local.json"
LOCAL_CHANNELS = {"personal"}  # gitignored local 파일에 저장하는 채널
# plugin.json userConfig 키 `teams_webhook_personal` 을 Claude Code 가 훅에 넘기는 이름.
PERSONAL_OPTION_ENV = "CLAUDE_PLUGIN_OPTION_TEAMS_WEBHOOK_PERSONAL"
# 호출당 초 — urlopen 의 값은 게시 전체가 아니라 소켓 대기 하나마다 걸림. hooks/claude/hooks.json 의
# Notification 훅 timeout 안에 게시가 끝나도록 맞춤(넘기면 훅이 보내기 전에 죽임).
GIT_TIMEOUT = 2
POST_TIMEOUT = 5

# 이벤트별 내장 메시지(제목, 본문). hook command 를 ASCII 로 유지하려고 여기 둠.
EVENT_MESSAGES = {
    "waiting": ("입력 대기", "Claude 가 입력 또는 권한 승인을 기다립니다."),
    "done": ("작업 완료", "Claude 가 응답을 마쳤습니다."),
}


def _load(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def resolve_webhook(channel: str) -> str | None:
    """채널의 웹훅 URL 을 반환(없으면 None). personal 은 플러그인 옵션이 먼저, 그다음 local 이
    tracked 를 덮어씀."""
    if channel == "personal":
        option = os.environ.get(PERSONAL_OPTION_ENV, "").strip()
        if option:
            return option
    merged = {**_load(TRACKED_FILE), **_load(LOCAL_FILE)}
    return merged.get(channel, "").strip() or None


def resolve_webhook_tracked(channel: str) -> str | None:
    """tracked 파일 하나만 `channel` 에 쥔 URL(없으면 None)."""
    return _load(TRACKED_FILE).get(channel, "").strip() or None


def push_channels() -> list[str]:
    """push 알림 대상 채널(=브랜치명) 목록. 두 파일의 키에서 동적으로 읽음.

    notify-push.sh 가 호출해 "어떤 브랜치를 push 했을 때 알릴지"를 결정.
    personal 등 local 전용 채널(LOCAL_CHANNELS)은 push 대상이 아님.
    """
    keys = dict.fromkeys([*_load(TRACKED_FILE), *_load(LOCAL_FILE)])
    return [k for k in keys if k not in LOCAL_CHANNELS]


def _write(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)  # .claude/vway-kit/config/ 보장
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def set_webhook(channel: str, url: str, shared: bool = False) -> Path:
    """채널 URL 을 저장하고 저장한 파일을 돌려줌.

    브랜치 URL 은 `shared` 가 아니면 gitignore 된 local 파일로 감. 그때 tracked 파일엔 그
    브랜치가 URL 없는 키로 들어가, 모든 클론이 그 브랜치를 감시하고 URL 을 쥔 클론이 알림.
    """
    local = channel in LOCAL_CHANNELS or not shared
    target = LOCAL_FILE if local else TRACKED_FILE
    data = _load(target)
    data[channel] = url.strip()
    _write(target, data)
    if local and channel not in LOCAL_CHANNELS:
        tracked = _load(TRACKED_FILE)
        if channel not in tracked:
            _write(TRACKED_FILE, {**tracked, channel: ""})
    return target


def _context_label() -> str:
    """알림 출처 식별용 라벨(프로젝트명 @ git 브랜치). 세션/작업 구별에 씀."""
    label = ROOT.name
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
        )
        branch = out.stdout.strip()
        if branch:
            label = f"{label} @ {branch}"
    except Exception:
        pass
    return label


def send(channel: str, title: str, text: str) -> bool:
    """채널 웹훅으로 알림을 POST. skip/실패 시 예외 없이 False 반환."""
    url = resolve_webhook(channel)
    if not url:
        if channel == "personal":
            try:
                sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            except Exception:
                pass
            print(
                "[teams_alert] personal 웹훅이 등록되지 않았습니다.\n"
                "  1) URL 만들기: Teams 채널 추가 > 우상단 볼렛 > Workflows(Power Automate) 에서\n"
                "     'send webhook` 검색 '채널에 웹후크 알림 보내기' 템플릿을 추가하고\n"
                "     생성된 HTTP POST URL 을 복사하세요.\n"
                "  2) 등록: 플러그인 옵션 teams_webhook_personal(보안 저장소, 권장) 또는\n"
                "     python .claude/vway-kit/scripts/teams_alert.py --set personal <복사한_URL>",
                file=sys.stderr,
            )
        return False
    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": title},
                        {"type": "TextBlock", "text": text, "wrap": True},
                        {
                            "type": "TextBlock",
                            "text": _context_label(),
                            "size": "Small",
                            "isSubtle": True,
                            "wrap": True,
                        },
                    ],
                },
            }
        ],
    }
    body = json.dumps(card).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=POST_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def main() -> None:
    # Invariant 2 — 사용법·오류 문구가 한글이라 로캘 코덱으로는 인코딩이 안 됨. argparse 는
    # `parse_args()` 안에서 사용법을 출력하므로 방어가 그보다 앞에 서야 함(실측: cp949·cp1252
    # 호스트에서 `--help` 가 UnicodeEncodeError 로 rc 1). 알림이 호출측 훅을 실패시키지
    # 않는다는 이 파일의 규율은, 그렇게 죽으면 시작도 못 함.
    # **import 시점이 아니라 여기임.** `force_utf8_io` 는 `os.environ` 과 이 프로세스의 스트림을
    # 바꾸므로, import 만으로 그것이 돌면 `from teams_alert import send` 한 쪽의 스트림과 그 쪽이
    # 나중에 띄우는 자식의 환경까지 바뀜 — 이 저장소의 pytest 세션이 실제로 그렇게 오염됐음.
    force_utf8_io()
    parser = argparse.ArgumentParser(description="Teams 알림 전송/등록")
    parser.add_argument(
        "--set",
        nargs=2,
        metavar=("CHANNEL", "URL"),
        help="채널 웹훅 URL 등록 (올바른 파일에 자동 저장)",
    )
    parser.add_argument(
        "--shared",
        action="store_true",
        help="브랜치 채널 URL을 git 추적 파일에 저장 (기본: gitignore 된 로컬 파일)",
    )
    parser.add_argument(
        "--list-push-channels",
        action="store_true",
        help="push 알림 대상 채널(브랜치) 목록 출력 — notify-push.sh 용",
    )
    parser.add_argument("--channel", help="personal | <공유 채널=브랜치명>")
    parser.add_argument("--event", choices=list(EVENT_MESSAGES), help="내장 메시지 (waiting/done)")
    parser.add_argument("--title", default="")
    parser.add_argument("--text", default="")
    args = parser.parse_args()

    if args.set:
        channel, url = args.set
        target = set_webhook(channel, url, shared=args.shared)
        print(f"[teams_alert] '{channel}' 등록됨 -> {target.name}")
        if target == LOCAL_FILE and resolve_webhook_tracked(channel):
            print(f"[teams_alert] {TRACKED_FILE.name} 에 '{channel}' URL 이 아직 남아 있습니다")
        if target == TRACKED_FILE and _load(LOCAL_FILE).get(channel, "").strip():
            # resolve_webhook 에서 local 이 이기므로 이 클론은 그 URL 로 계속 알림.
            print(f"[teams_alert] {LOCAL_FILE.name} 의 '{channel}' URL 이 이 URL 보다 우선합니다")
        sys.exit(0)

    if args.list_push_channels:
        print(" ".join(push_channels()))
        sys.exit(0)

    if not args.channel:
        parser.error("--channel 이 필요합니다 (또는 --set CHANNEL URL)")
    if args.event:
        title, text = EVENT_MESSAGES[args.event]
        send(args.channel, title, text)
    else:
        send(args.channel, args.title, args.text)
    sys.exit(0)  # 알림은 절대 호출측 hook 을 실패시키지 않음


if __name__ == "__main__":
    main()
