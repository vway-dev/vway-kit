#!/usr/bin/env bash
# Notification 훅 — 사용자 입력·권한 승인 대기를 personal Teams 채널에 알림.
# 웹훅 URL 해석과 실패 무시는 scripts/teams_alert.py 가 맡음.
exec python3 "${BASH_SOURCE[0]%/*}/../scripts/teams_alert.py" --channel personal --event waiting
