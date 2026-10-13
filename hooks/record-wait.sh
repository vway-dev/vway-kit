#!/usr/bin/env bash
# Notification 훅 — 권한 승인 대기 시각을 worklog 에 기록(scripts/worklog.py record-wait).
exec python3 "${BASH_SOURCE[0]%/*}/../scripts/worklog.py" record-wait
