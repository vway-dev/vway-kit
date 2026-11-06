#!/usr/bin/env bash
# Claude Code PreToolUse hook — git commit/merge 게이트 (vway-kit).
#
# 두 단계로 커밋을 검사하고, 차단할 때만 stdout 으로 deny JSON 을 냄:
#   1) vdev 게이트 + wiki 런타임 게이트 — vdev_gate_check.py(플러그인) 가 선언된 티어/
#      라이프사이클 브랜치의 필수 게이트 증거를 확인하고, vdev-config.wiki 가 켜져 있으면
#      같은 프로세스에서 지식 그래프까지 검증한다(spawn 2→1; --wiki-check 는 호환 alias 로
#      존치). 둘 중 하나라도 미충족이면 exit 2 + 사유 → deny.
#   2) 모듈 사전검사 — 변경 모듈의 every-commit 타이밍 검사(+승격 시 전체 모듈 promotion
#      타이밍)를 실행. 관습 키(lint/static/import_lint/test/security) 외 임의 커스텀 검사도
#      checks 의 when 으로 버킷을 지정함. 파싱 실패/명령 없음은 FAIL-OPEN(skip), 실패면 deny.
# `git merge` 는 위 두 단계 **앞**에서, 그리고 `git status` 조기 종료 앞에서 따로 검사함
# (--merge-check) — 머지는 정의상 깨끗한 트리에서 돌기 때문임. 머지이면서 커밋이기도 한
# 명령(`git merge --squash X && git commit -m …`)은 그 순서로 **둘 다** 검사받음.
#
# 경로 규약(플러그인은 호스트 밖에 설치됨):
#   - 호스트 저장소 루트 → CLAUDE_PROJECT_DIR (없으면 git toplevel)
#   - 플러그인 스크립트  → CLAUDE_PLUGIN_ROOT/scripts (없으면 이 스크립트 위치)
#
# 차단 규약: PreToolUse 차단은 exit 2 + stderr 사유로 한다(이 빌드는
# permissionDecision JSON+exit0 을 무시함). 신버전 호환을 위해 JSON 도 함께 냄.
# 변경 없음 / 검사 통과 시: exit 0 → 커밋 허용. 전이적 내부 오류는
# FAIL-OPEN(검사 skip, 커밋 허용)으로 처리해 깨진 게이트가 커밋을 막지 않게 함.
# 단, python3/PyYAML 같은 필수 도구 부재는 FAIL-CLOSED(차단)다 — 비-Python 팀에서
# 게이트가 조용히 무력화되는 것을 막기 위함(설치 후 재커밋).
#
# 디버그: VWAY_PRECOMMIT_DRYRUN=1 이면 실행할 테스트 명령만 출력하고 실행하지 않음.
set -uo pipefail

# Windows 훅 환경은 cp1252/cp949 로캘이라 Python 기본 I/O 가 UTF-8 이 아님.
# 한글 사유 print() / UTF-8 설정파일 open() 이 인코딩 오류로 FAIL-OPEN 되는 것을
# 막기 위해 모든 자식 python 에 UTF-8 모드를 강제한다(상속됨).
export PYTHONUTF8=1
# 스크립트는 호스트의 추적 트리에 있음 — 옆에 생기는 바이트코드가 그 트리를 더럽힘.
export PYTHONDONTWRITEBYTECODE=1

deny() {  # $1=사유 → 커밋 차단 (exit 2 가 실제 차단 수단, JSON 은 신버전 호환용)
  # 사유는 JSON 문자열 안으로 보간되므로 먼저 이스케이프해야 함. 사유에는 실패한 명령이
  # 그대로 실리는데 모듈 명령은 임의의 호스트 텍스트이고, wiki 게이트의 사유는 큰따옴표를,
  # Windows 에선 백슬래시까지 포함함. 이스케이프 없이 넣으면 `"` 가 JSON 문자열을 조기에
  # 닫고 `\r`·`\P` 는 잘못된 escape 라, 하필 게이트가 차단하는 바로 그 순간 페이로드가
  # 깨짐. 순수 bash 치환인 이유: python3 가 없는 deny 경로가 존재함(아래 첫 deny 들은
  # *python3 부재 때문에* 발화함). 순서가 중요함 — 백슬래시를 먼저 처리해야 뒤에 추가한
  # escape 가 다시 escape 되지 않고, 제어문자 일괄 치환을 마지막에 둬야 짧은 escape 가 있는
  # 세 문자가 그것을 유지함.
  _deny_json=${1//\\/\\\\}
  _deny_json=${_deny_json//\"/\\\"}
  _deny_json=${_deny_json//$'\n'/\\n}
  _deny_json=${_deny_json//$'\r'/\\r}
  _deny_json=${_deny_json//$'\t'/\\t}
  # JSON 은 U+0020 미만의 raw 문자를 전부 금지함(위 셋만이 아님). wiki 게이트는 git 제목
  # 줄을 사유에 인용해 오는데, 제목에는 붙여넣어진 무엇이든 들어갈 수 있음 — ESC 한 글자면
  # 이스케이프 안 한 따옴표와 똑같이 페이로드가 깨짐.
  _deny_json=${_deny_json//[[:cntrl:]]/ }
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$_deny_json"
  printf 'vway-kit 게이트 차단: %s\n' "$1" >&2
  exit 2
}

# 보류해 둔 비차단 통지를 내보내고 명령을 통과시킴. 커밋 단계 통지가 merge 통지를 이미
# 싣고 있으므로 둘 중 하나만 냄 — 훅 stdout 에 JSON 객체가 둘이면 파싱되지 않음.
allow() {
  if [ -n "${gate_note:-}" ]; then
    printf '%s\n' "$gate_note"
  elif [ -n "${merge_note:-}" ]; then
    printf '%s\n' "$merge_note"
  fi
  exit 0
}

# PreToolUse stdin(tool_input JSON)을 읽어 `git commit`/`git merge`(브랜치를 대는 pull 포함)만 게이트함. settings.json
# `if` 필드에 의존하지 않고 스크립트가 직접 self-filter 한다(빌드별 `if` 동작 차이 회피).
_hook_input="$(timeout 5 cat 2>/dev/null || true)"

# 커밋/머지 여부 판별. python3 가 있으면 tool_input.command 를 정확히 추출함. 추출이
# 비거나(python3 손상) python3 자체가 없으면 raw stdin 으로 거칠게 폴백함 —
# "python3 문제 → 커밋 탐지 실패 → 게이트 자가무력화"를 막기 위함(부재/손상은
# 아래 의존성 검사에서 fail-closed 로 막힘).
_hook_cmd=""
if command -v python3 >/dev/null 2>&1; then
  _hook_cmd="$(printf '%s' "$_hook_input" | python3 -c "import sys, json
try:
    print((json.load(sys.stdin).get('tool_input') or {}).get('command', ''))
except Exception:
    print('')" 2>/dev/null || true)"
fi
# 거친 사전 필터. 여기서 정하는 것은 **게이트를 띄울지 말지 하나뿐**이고, 이 명령이
# 무엇인지는 아래 vdev_gate_check.py --classify 가 한 번에 정함.
# 이 셸 패턴과 파이썬 문법이 같은 물음에 **각자** 답하면 둘이 합의해야 하고, 한쪽만
# 받아 주는 철자는 좁은 게이트가 아니라 조용히 꺼진 게이트임. `/usr/bin/git … commit` 은
# 이 필터를 통과하고도 worktree 를 못 풀어 ROOT 를 깨끗한 main 에 남긴 채 exit 0 하고,
# 경로 속 `'\''` 는 여기서 옵션 토큰을 끝내 러너를 **모든 게이트보다 앞에서** 종료시킴.
# 답은 둘 다 더할 철자가 아니라 지울 두 번째 문법. 그래서 이 필터는 진짜 문법보다
# **좁아질 수 없게** 씀: 파이썬 호출 문법은 리터럴 `git` 과 공백 뒤 `commit`/`merge`/`pull`
# 낱말(브랜치를 대는 pull 은 그 브랜치의 머지)을
# 요구하므로, 둘 다 없는 명령은 호출일 수 없음. 나머지는 전부 넘겨 판정받음.
# 과다 매칭의 비용은 python spawn 한 번이고 판정은 없음. 과소 매칭의 비용은 게이트 전체.
# 따옴표·백슬래시를 **지운 판도 함께** 봄. 셸은 모든 낱말에 인용 제거를 하므로
# `git com''mit -m x` 는 진짜 커밋인데(실측: 실제 bash argv 에 `commit`), 원문에는
# `commit` 낱말이 없어 이 필터가 문법보다 좁아짐 — 러너가 판정 전에 exit 0 함(실측).
# 둘 다 보는 것은 지우기가 낱말을 **깨는** 경우( `'commit'x` )까지 덮기 위함.
# 줄이음(`co\<개행>mmit`)과 `$`(`$'commit'` 의 여는 것보다 거칠게 전부)도 지움 — 문법의
# 인용 제거 판이 이어 붙이는 낱말을 이 필터도 봐야 함.
# 순수 bash 치환이라 프로세스를 하나도 더 띄우지 않음. 다만 치환은 일치마다 문자열을
# 새로 만들어 **따옴표 수 × 길이**다 — `'a'`×k 의 러너 wall 이 32KB 753ms·64KB 2.4초·
# 512KB 115초였다(실측, 배가마다 약 4배; 훅 timeout 600초 = 약 1.1MB 부터 판정 없음).
# 긴 인용 인자는 병리 입력이 아니라 평범한 명령이라 상한을 둠. 넘는 입력은 필터를
# 통째로 건너뛰고 게이트를 띄움 — 필터는 넓어질 수만 있고, 그 비용은 spawn 하나.
# 상한이 새로 파이썬에 보내는 것은 16KB 를 넘으면서 `git` 이 없거나 `commit`·`merge`·`pull`
# 낱말이 없는 명령임. spawn 값은 명령 **모양**에 달림(실측, 러너 wall 512KB): 이
# 상한이 겨냥한 따옴표 빽빽한 모양은 115초에서 3.0초로 내려가고, 인용 없는 긴 낱말
# (`git log --oneline ` + x×k)은 8.2초이며 배가마다 커짐 — 뒤엣것은 파이썬 스캐너
# 쪽 비용이고, 성장률이 일정하지 않아 어느 크기에서 timeout 인지는 외삽하지 않음.
_filter_src="${_hook_cmd:-$_hook_input}"
if [ "${#_filter_src}" -le 16384 ]; then
  _filter_bare="${_filter_src//\\$'\r\n'/}"
  _filter_bare="${_filter_bare//\\$'\n'/}"
  # `$'…'` 은 이스케이프로 아무 글자나 철자함(`$'\x63ommit'`) — 지운 사본으로도 못 읽으니 넘김.
  # 그 `$'` 가 인터프리터용 인용으로 갈라져 있을 수도 있음(`"\$"'\x63ommit'`) — 그래서 `$`
  # 옆의 백슬래시도 넘김. 뒤엣것은 흔한 모양(`printf "$x\n"`)이라 pull 처럼 넘겨, python
  # 없는 호스트의 의존성 차단에 걸지 않음.
  _ansi_c=
  case "$_filter_bare" in
    *"\$'"*) _ansi_c=commit ;;
    *\$*\\* | *\\*\$*) _ansi_c=pull ;;
  esac
  _filter_bare="${_filter_bare//\"/}"
  _filter_bare="${_filter_bare//\'/}"
  _filter_bare="${_filter_bare//\$/}"
  _filter_bare="${_filter_bare//\\/}"
  [ -z "$_ansi_c" ] || _filter_bare="$_filter_bare git $_ansi_c"
  case "$_filter_src$_filter_bare" in
    *git*) ;;
    *) exit 0 ;;
  esac
  # 낱말 앞의 **공백을 요구하지 않음**. 문법의 둘째 읽기는 인용을 지운 판에서 도는데
  # 거기서는 따옴표가 구분자가 되므로, `eval 'git'commit` 은 게이트에게 호출인데 공백을
  # 앵커로 삼은 필터는 그것을 떨어뜨림 — 문법보다 좁은 필터는 조용히 꺼진 게이트임.
  _word_re='(commit|merge|pull)($|[^[:alnum:]_-])'
  [[ "$_filter_src" =~ $_word_re || "$_filter_bare" =~ $_word_re ]] || exit 0
  _cm_re='(commit|merge)($|[^[:alnum:]_-])'
  [[ "$_filter_src" =~ $_cm_re || "$_filter_bare" =~ $_cm_re ]] || _pull_only=1
fi

# `pull` 낱말만 든 명령은 아래 의존성 차단에 걸지 않음 — python 없이는 호출과 언급을
# 가릴 수 없어, 걸면 그 호스트의 `git pull` 이 전부 막힘. 그런 호스트에서 브랜치를 대는
# pull 은 판정 없이 지나감(pull 판정이 생기기 전과 같음). 넘기는 조건은 아래 검사 셋과 같음.
if [ "${_pull_only:-0}" -eq 1 ]; then
  command -v python3 >/dev/null 2>&1 &&
    python3 -c "import sys, yaml; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" \
      >/dev/null 2>&1 || exit 0
fi

# 의존성 FAIL-CLOSED — 하니스는 python3 + PyYAML 을 요구한다(프로젝트 언어 무관).
# 누락 시 조용히 통과(fail-open)하면 비-Python 팀에서 게이트가 무력화되므로, "필수
# 도구 부재"는 전이적 내부 오류와 달리 커밋을 차단한다(설치 후 재커밋).
#
# DRY 예외(의도된 중복): 아래 부트스트랩 체크의 floor(3, 8)·PyYAML 설치 명령은
# check-deps.sh 와 동일 값이지만 코드 공유가 불가함 — (1) 게이트가 부르는 bare
# python3 를 직접 검증하므로 파이썬 헬퍼(_vway_paths)로 옮기면 순환이고, (2) 이 스크립트는
# self-contained 가 Invariant(외부 source 실패 시 FAIL-OPEN 으로 게이트 무력화)라 셸끼리도
# 공유 못 함. 그래서 값 SSOT 는 check-deps.sh 로 두고 여기 floor·설치 명령을 그것과
# 동기화함(한쪽만 바꾸면 사전점검과 차단 기준이 어긋남).
if ! command -v python3 >/dev/null 2>&1; then
  deny "게이트에 python3 가 필요합니다. 설치 후 다시 커밋하세요(불가하면 settings.json 의 게이트 훅을 제거)."
fi
# floor = python 3.8 (SSOT: check-deps.sh — 변경 시 양쪽 동기화)
if ! python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
  # Microsoft Store 의 앱 실행 별칭은 `command -v python3` 에 답하지만 python 을 돌리지 않음.
  case "$(command -v python3)" in
    *WindowsApps*) deny "python3 가 Microsoft Store 별칭이라 python 이 실행되지 않습니다. Python install manager(winget install 9NQ7512CXL7T 후 py install 3.12)로 설치하거나 '앱 실행 별칭 관리'에서 python3 별칭을 끄세요." ;;
  esac
  deny "게이트에 python 3.8+ 가 필요합니다(현재 버전 미만). 업그레이드 후 다시 커밋하세요."
fi
# PyYAML 설치 명령 = check-deps.sh 와 동일 문자열로 유지
if ! python3 -c "import yaml" >/dev/null 2>&1; then
  deny "게이트에 PyYAML 이 필요합니다. python3 -m pip install pyyaml 후 다시 커밋하세요(점검: .claude/vway-kit/scripts/check-deps.sh)."
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SCRIPTS="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts}"
PLUGIN_SCRIPTS="${PLUGIN_SCRIPTS:-$SCRIPT_DIR}"

# 이 명령에 대한 게이트 자신의 판정: 커밋인가, 머지인가, 커밋이 도는 worktree 는 어디인가.
# spawn 하나, 문법 하나, 권위 하나 — --classify 참조. 둘 다 아니라는 판정은 거친 필터가
# 과다 매칭했고 게이팅할 것이 없다는 뜻임. 침묵(읽을 수 없는 페이로드, 죽은 python)도 같은
# 말이고 그것이 FAIL-OPEN 임: 이 단계가 새로 무언가를 차단하는 일은 없어야 한다(Invariant #1).
# 의존성 검사 **뒤**에 둠 — --classify 자체가 python 이라, python 없이는 호출과 언급을
# 가릴 수 없어 거친 필터의 과다 매칭까지 거기서 차단됨. 그 방향이 fail-CLOSED 이고,
# 어차피 모든 진짜 커밋이 막히는 호스트에서만 닿으며, 차단 사유가 유일한 해법을 지목함.
_verdict="$(printf '%s' "$_hook_input" | CLAUDE_PROJECT_DIR="$ROOT" \
  python3 "$PLUGIN_SCRIPTS/vdev_gate_check.py" --classify 2>/dev/null || true)"
_is_commit=0
_is_merge=0
_answered=0
_unresolved=0
_wt=""
while IFS= read -r _line; do
  # Windows 훅 호스트에서 python 의 print() 는 CRLF 를 내고, 그중 **마지막 줄의 CR 만**
  # 명령 치환이 먹음 — 그 앞 줄은 전부 CR 을 달고 옴. CR 없이 쓴 case 갈래는 조용히
  # 아무것도 매칭하지 않는다(Invariant #2, 실측).
  _line="${_line%$'\r'}"
  case "$_line" in
    ok=1) _answered=1 ;;
    commit=1) _is_commit=1 ;;
    merge=1) _is_merge=1 ;;
    worktree=?*) _wt="${_line#worktree=}" ;;
    unresolved=1) _unresolved=1 ;;
  esac
done <<< "$_verdict"
if [ "$_answered" -ne 1 ]; then
  # 판정이 없음 = 이 스크립트가 답을 못 냈음(깨졌거나 없거나, 페이로드가 예상 모양이
  # 아니거나). 명령을 떨어뜨리지 말고 **게이팅함**: 아래 단계들은 각자 fail-open 하지만,
  # 여기서 exit 0 하면 그 단계들에 닿지도 못함.
  _is_commit=1
  # merge 검사도 들어감 — `_is_merge` 로만 닿는 경로이고, merge 전략 위반은 이 게이트가
  # 절대 fail-open 하면 안 되는 셋 중 하나. 스크립트 **존재**를 조건으로 다는 것은 그
  # 단계만이 사유를 stderr 에서 읽기 때문임: `python3 <없는 파일>` 은 인터프리터 자신의
  # 불평을 거기 쓰고 exit 2 하므로, 반쯤 복사된 호스트가 그것을 모든 커밋에 대한 merge
  # 판정으로 내놓게 됨.
  [ -f "$PLUGIN_SCRIPTS/vdev_gate_check.py" ] && _is_merge=1
fi
[ "$_is_commit" -eq 1 ] || [ "$_is_merge" -eq 1 ] || exit 0

# merge 게이트 — 머지는 깨끗한 트리에서 돌므로 아래 `git status` 조기 종료보다, 그리고
# worktree 재지정보다 앞에서 검사해야 한다(Invariant "worktree 재지정은 커밋 경로 전용":
# merge 경로는 정책을 CLAUDE_PROJECT_DIR 에서 읽고, 다른 트리에서는 브랜치만 읽음). `.done`
# 마커도 모듈 검사도 쓰지 않음 — 옮겨지는 내용물은 커밋 게이트가 이미 심사함.
# merge 검사는 commit 검사와 배타적이지 **않음**: `git merge X && git commit -m …` 이 정규
# squash 관용구인데 이를 "커밋"으로만 게이팅하면 merge 판정이 통째로 스킵되고(그 다음 깨끗한
# 트리에서 조기 종료됨). 그래서 머지를 항상 **먼저** 검사하고, 커밋이기도 한 명령은 아래
# 커밋 경로로 떨어뜨려 둘 다 적용함.
if [ "$_is_merge" -eq 1 ]; then
  # 차단 사유·경고는 stdout 으로만 캡처한다(커밋 게이트와 같은 규약). stderr(게이트 스크립트를
  # 못 여는 등의 인터프리터 오류)는 버림 — 그래서 인터프리터 오류(stderr + exit 2)는 사유가
  # 비어 deny 되지 않고 fail-open 한다(Invariant #1). 차단(exit 2)과 통지(exit 0)는 exit code 로
  # 가름: 차단이면 deny, 통지(systemMessage JSON)면 통과할 때까지 보류 — exit 0 인 훅의
  # stderr 는 사용자에게 닿지 않음.
  merge_reason="$(printf '%s' "$_hook_input" | CLAUDE_PROJECT_DIR="$ROOT" \
    python3 "$PLUGIN_SCRIPTS/vdev_gate_check.py" --merge-check 2>/dev/null)"
  merge_rc=$?
  if [ "$merge_rc" -eq 2 ] && [ -n "$merge_reason" ]; then
    deny "$merge_reason"
  fi
  [ "$merge_rc" -eq 0 ] && merge_note="$merge_reason"
  [ "$_is_commit" -eq 1 ] || allow
fi

# worktree 재지정(case B): 커밋이 실제로 도는 worktree 로 ROOT 를 옮긴다(FAIL-OPEN, 커밋
# 경로 전용 — merge 는 CLAUDE_PROJECT_DIR 기준 판정이라 위 merge 게이트를 먼저 돌림).
# CLAUDE_PROJECT_DIR 은 세션 시작 위치(보통 main)에 고정돼, main 세션 안에서 만든 worktree 의
# 커밋이 main 을 검사당하는 문제를 푼다(staged diff 안 보임 · 브랜치 바인딩된 tier 마커
# 불일치 · 상대 경로 모듈 lint 가 worktree 파일을 놓침). 위 --classify 가 브랜치 키로
# 탐지했고, 빈 답은 ROOT 를 main 에 남김.
if [ -n "$_wt" ] && [ -d "$_wt" ]; then
  ROOT="$_wt"
fi

cd "$ROOT" || allow

status="$(git status --porcelain 2>/dev/null)" || allow
# 깨끗한 ROOT = 커밋할 것이 없음 — 단, 명령이 **이름 댈 수 없는 곳**에서 커밋하지 않을 때만.
# `--classify` 가 `unresolved=1` 로 그것을 말함: 명령이 트리를 둘 이상 대거나 따라갈 수 없는
# 이동을 담고 있으면 ROOT 는 해석기가 떨어진 아무 트리이고, 그것이 깨끗하다는 사실은 커밋이
# 도는지에 대해 아무것도 말하지 않음. 그걸 "게이팅할 것 없음"으로 읽으면 진짜 커밋에서 모든
# 게이트가 조용히 건너뛰어짐 — 그래도 ROOT 를 게이팅하는 쪽이 덜 틀림.
if [ -z "$status" ] && [ "$_unresolved" -eq 0 ]; then
  allow
fi

# 1) vdev 게이트 + 런타임 게이트(wiki·doc-style) — 프로세스 **하나**. vdev_gate_check.py 는
#    CLAUDE_PROJECT_DIR 로 호스트 루트를 읽고 내부 오류 시 FAIL-OPEN(exit 0). vdev 판정
#    뒤에 같은 인터프리터에서 그 게이트들을 돌린다(tier 를 한 번만 해석 — spawn 2→1,
#    --wiki-check 는 호환 alias 로만 남음). 어느 쪽이든 exit 2 + stdout 사유면 deny.
#    그것들을 아래 모듈 명령 채널에 두지 않는 이유는 오류 계약이 양립하지 않기 때문임:
#    저쪽에선 비영 종료가 곧 "검사 실패"지만, 런타임 게이트는 진짜 판정이 아닌 모든 것에
#    FAIL-OPEN 해야 함(Invariant #1 — 둘 다 fail-closed 3대 예외가 아님).
#    stdout 전용이 결정적임: `python3 <없는 파일>` **도** exit 2 에 stderr 로 불평하므로
#    여기서 stderr 를 읽으면 반쪽 복사된 설치가 저장소 전체 차단으로 바뀜. exit 0 일 때의
#    비어있지 않은 stdout 은 그것들을 합친 systemMessage JSON — 객체 **하나**이고, 커밋이
#    허용될 때까지 보류한다(exit 0 이면 훅의 stdout·stderr 가 둘 다 디버그 로그로만 가므로,
#    systemMessage 가 사용자에게 실제로 보이는 유일한 문서화된 필드).
#    merge 단계가 보류한 통지는 VWAY_MERGE_NOTE 로 넘겨 그 객체 하나에 함께 실림.
#    VWAY_PRECOMMIT_DRYRUN 은 스크립트 안에서 소비됨(통지 단계들이 스스로 건너뜀).
flow_reason="$(VWAY_MERGE_NOTE="${merge_note:-}" CLAUDE_PROJECT_DIR="$ROOT" \
  python3 "$PLUGIN_SCRIPTS/vdev_gate_check.py" 2>/dev/null)"
flow_rc=$?
if [ "$flow_rc" -eq 2 ] && [ -n "$flow_reason" ]; then
  deny "$flow_reason"
fi
[ "$flow_rc" -eq 0 ] && gate_note="$flow_reason"

# 2) 모듈 사전검사. tier 별로 변경 모듈의 every-commit 타이밍 검사(+승격 시 전체 모듈
#    promotion 타이밍 — 관습 키+커스텀)를 실행. 명령은 stdout, 미커버 리포트는 stderr 로 분리돼 옴
#    (stderr 는 캡처하지 않음 — 다만 훅의 stderr 는 훅이 비영으로 끝날 때만 사용자에게
#    닿으므로, 이 리포트는 deny 와 함께일 때만 보임). config 파싱 실패/명령 없음 시
#    FAIL-OPEN(skip). 하나라도 실패하면 deny.
mod_cmds="$(CLAUDE_PROJECT_DIR="$ROOT" python3 "$PLUGIN_SCRIPTS/vdev_gate_check.py" --module-commands)"
[ -n "$mod_cmds" ] || allow

if [ "${VWAY_PRECOMMIT_DRYRUN:-0}" = "1" ]; then
  echo "DRYRUN: 모듈 사전검사 명령 →" 1>&2
  printf '%s\n' "$mod_cmds" 1>&2
  allow
fi

LOG_DIR="${TMPDIR:-/tmp}"
mod_log="$LOG_DIR/vway-precommit-module.log"
while IFS= read -r mod_cmd; do
  mod_cmd="${mod_cmd%$'\r'}"   # Windows 호스트의 CRLF — 위 --classify 와 같은 이유
  [ -n "$mod_cmd" ] || continue
  echo "▶ 모듈 사전검사 실행: $mod_cmd …" 1>&2
  if ! bash -c "$mod_cmd" > "$mod_log" 2>&1; then
    cat "$mod_log" 1>&2
    deny "모듈 사전검사 실패: $mod_cmd. 위 출력을 확인해 수정한 뒤 다시 커밋하세요."
  fi
done <<< "$mod_cmds"

allow
