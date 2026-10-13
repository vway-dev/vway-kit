#!/usr/bin/env bash
# Codex 의 커밋 게이트 훅. Codex 는 러너의 deny JSON 을 따르지만, Windows 에서 훅을 도는
# PowerShell 이 exit 2 를 1 로 바꾸고 Codex 는 1 을 실패한 훅으로 읽어 명령을 통과시킴 —
# 그래서 러너의 2 를 여기서 0 으로 바꾸고 JSON 만으로 막음. 나머지 종료 코드는 그대로.
# 러너는 Claude Code 와 공유라 스킬을 `/vdev…`, 게이트 위치를 settings.json 으로 부름 —
# 나가는 길에 Codex 의 `$vdev…`·.codex/hooks.json 으로 바꿈. 바꾸기가 실패하면 러너 원문을
# 그대로 찍음: JSON 이 곧 차단이라 사라지면 안 됨.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$(bash "$here/../../precommit-runner.sh")"
rc=$?
if [ -n "$out" ]; then
  reworded="$(printf '%s\n' "$out" | sed -E -e 's#(^|[ (])/(vdev[a-z-]*)#\1$\2#g' \
    -e 's#settings\.json 의 게이트 훅#.codex/hooks.json 의 게이트 훅#g')" && [ -n "$reworded" ] \
    || reworded="$out"
  printf '%s\n' "$reworded"
fi
[ "$rc" -eq 2 ] && exit 0
exit "$rc"
