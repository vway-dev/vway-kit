#!/usr/bin/env bash
# PostToolUse 훅 — 편집은 review·doc-sync 증거를 무효화함.
#
# 두 마커는 워킹트리를 판정하고, 자기를 쓴 커밋보다 오래 삶(커밋이 안 지우고 브랜치에도 안 매임).
# 그대로 두면 통과 뒤의 수정이 아무도 본 적 없는 코드 위의 증거로 커밋됨. 둘은 서로를 무효화하므로
# (doc-sync 뒤에 고친 리뷰 지적은 문서에 없음) 성립하는 상태는 "둘 다 기록됨, 그 뒤 편집 없음" 뿐.
#
# 지우는 쪽이 안전한 방향: 잘못 지운 마커는 재실행 한 번, 잘못 남긴 마커는 리뷰 안 된 커밋 통과.
# 그래서 판정 못 하는 경우(오타 난 훅 엔트리 포함)는 전부 지우고, 훅 자체의 실패는 마커를 안 건드림
# (FAIL-OPEN — 게이트는 이미 가진 더 엄격한 답을 유지).
#
# bump·security 는 대상 아님 — 깨끗한 트리에서 내리는 승격 결정이라 뒤따르는 편집이 없음.
# 스크립트는 16 KiB 아래로 유지 — 마켓 디렉터리 검증기가 18,312 B 판을 "끝까지 못 읽음" 으로
# 거부했고 15,864 B 인 inject-risk-tiers.sh 는 통과함.

set -uo pipefail

# exit 2 는 stderr 를 에이전트에 넘김 — 인쇄 가능한 ASCII 만. 서브셸이라 LC_ALL 이 새지 않음.
printable() {
  (
    LC_ALL=C
    a="$*"
    printf '%s' "${a//[![:print:]]/?}"
  )
}

# 하네스는 훅 엔트리가 이름 댐 — Codex 도 CLAUDE_PLUGIN_ROOT 를 주므로 환경에서 추측 안 함.
# 인자 없음 = Claude Code. 그 밖의 인자는 오타 난 엔트리: 편집 자리를 못 대므로 세션의 트리를
# 무효화하고 exit 2 — 고칠 때까지 호출마다 에이전트 앞에 섬.
HARNESS=claude
if [ "$#" -gt 0 ]; then
  case "$#:$1:${2:-}" in
    2:--harness:claude | 2:--harness:codex) HARNESS=$2 ;;
    *)
      HARNESS=unknown
      ARGS=$(printable "$@")
      ;;
  esac
fi
bad_args() {
  [ "$HARNESS" = unknown ] || return 0
  printf '%s: 알 수 없는 인자 "%s" (기대: --harness claude|codex); 무효화: %s\n' \
    "${0##*/}" "$ARGS" "${voided:-없음}" >&2
  exit 2
}
voided=""  # bad_args 가 루프보다 먼저 읽음 — 내보낸 환경값이 새어 들면 안 됨

MARKERS="review.done doc-sync.done"
EVIDENCE=".claude/vway-kit/.vdev"
CONFIG=".claude/vway-kit/config/vdev-config.yaml"
NL=$'\n'
# 목록은 줄 단위로 `for` 가 나눔(heredoc 없이 — 디렉터리 검증기가 heredoc 든 스크립트를 못 읽음).
# 글로브는 끔: 나뉜 경로가 파일 이름으로 확장되면 안 됨.
set -f

# 정규식은 변수로: `[[ =~ ]]` 오른쪽의 리터럴 `#`·`(`·`|` 를 셸 외 판독기가 잘못 읽음.
RE_TOP_KEY='^[^[:space:]#]'
RE_HEADER='^gate_evidence[[:space:]]*:[[:space:]]*(#.*)?$'
RE_CHILD='^([[:space:]]+)[^[:space:]#]'
RE_OFF='^[[:space:]]+invalidate_on_edit[[:space:]]*:[[:space:]]+false([[:space:]]+#.*)?[[:space:]]*$'
RE_SWITCH='^[[:space:]]+invalidate_on_edit[[:space:]]*:'
# 큰따옴표는 변수로 철자함 — 작은따옴표 문자열 안의 짝 없는 `"` 를 같은 판독기가 잘못 짝지음.
dq=\"
RE_EDIT_PATH="${dq}(file|notebook)_path${dq}[[:space:]]*:[[:space:]]*${dq}([^${dq}]*)${dq}"
RE_CWD="${dq}cwd${dq}[[:space:]]*:[[:space:]]*${dq}([^${dq}]*)${dq}"

# 호스트 자신의 스위치를 **대상 트리마다** 물음. 플러그인이 등록한 훅이라 버전만으로 모든 소비자에게
# 켜지므로, 옛 순서(리뷰 → 작은 수정 → 커밋)를 원하는 팀이 끌 수 있어야 함. 끈 프로젝트는 자기
# 증거만 대신 말함.
#
# YAML 파서(프로세스 하나) 대신 줄 단위로 읽음. 스위치는 평범한 블록을 여는 최상위
# `gate_evidence:` 밑의 `false` 하나 — 다른 값·다른 자리·읽을 수 없는 파일은 전부 켜짐
# (`rules/gate-mechanics.md` 의 약속). 흐름 매핑·블록 스칼라 헤더는 블록을 열지 않음.
opted_out() {
  # `line` 도 초기화: 첫 `read` 가 실패하면 빈 변수가 `set -u` 로 훅을 죽여 마커가 남음.
  local root=$1 line="" indent child="" in_block=0 answer=1
  [ -n "$root" ] && [ -r "$root/$CONFIG" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    # CRLF 설정의 끝 CR 은 `[[:space:]]` 로 읽혀 각 패턴이 거기서 끝남.
    # 0열의 키(`#` 제외 — 헤더와 키 사이 주석)는 블록을 열고 앞 블록을 닫음. 빈 줄·들여쓴 줄은 통과.
    if [[ $line =~ $RE_TOP_KEY ]]; then
      if [[ $line =~ $RE_HEADER ]]; then
        in_block=1
        answer=1  # 중복 블록은 질문을 다시 엶 — 답을 정하는 것은 그 블록 자신의 줄뿐
      else
        in_block=0
      fi
      child=""
      continue
    fi
    [ "$in_block" -eq 1 ] || continue
    [[ $line =~ $RE_CHILD ]] || continue  # 빈 줄, 또는 들여쓴 주석
    indent=${BASH_REMATCH[1]}
    # 블록의 키는 첫 키의 들여쓰기에 앉음. 더 깊은 줄(중첩 매핑, 블록 스칼라 본문)은 이 설정이 아님.
    [ -n "$child" ] || child=$indent
    [ "$indent" = "$child" ] || continue
    # 끝까지 훑음: YAML 처럼 중복은 마지막이 답. 값 앞·주석 앞 공백은 YAML 이 요구함 —
    # `invalidate_on_edit:false`·`false# x` 는 긴 문자열이라 끈 것이 아님.
    if [[ $line =~ $RE_OFF ]]; then
      answer=0
    elif [[ $line =~ $RE_SWITCH ]]; then
      answer=1
    fi
  done < "$root/$CONFIG"
  return $answer
}

# 낡은 증거는 편집된 파일 **자신의** repo 루트에 있음 — 게이트가 커밋이 발행된 루트로 판정하므로
# (Invariant 7). 첫 증거 디렉터리가 아니라 루트까지만 걷는 것이 경계: 스크래치패드 파일 위에는
# 루트가 없고, 상위 프로젝트가 하위 repo 편집으로 증거를 잃지 않음.
root_for() {
  local dir="$1"
  while [ -n "$dir" ]; do
    if [ -e "$dir/.git" ]; then  # 클론은 디렉터리, worktree 는 파일 — 둘 다 루트임
      printf '%s' "$dir"
      return 0
    fi
    case "$dir" in
      */*) dir="${dir%/*}" ;;
      *) return 1 ;;
    esac
  done
  return 1
}

# 루트의 공통 git 디렉터리 — 같은 repo 의 모든 worktree 가 공유하는 답이고 "두 repo" 와
# "한 repo 의 두 시점" 을 가름. 편집마다 돌므로 `git` 대신 파일을 읽음.
common_dir() {
  local root="$1" line
  if [ -d "$root/.git" ]; then
    printf '%s' "$root/.git"
    return 0
  fi
  [ -f "$root/.git" ] || return 1
  IFS= read -r line < "$root/.git" || return 1
  case "$line" in gitdir:*) line="${line#gitdir:}" ;; *) return 1 ;; esac
  line="${line# }"
  line="${line%/worktrees/*}"                  # 링크된 worktree 는 공통 디렉터리 안을 가리킴
  case "$line" in /*|?:/*) ;; *) line="$root/$line" ;; esac  # 상대 gitdir 는 루트 기준
  printf '%s' "$line"
}

# 두 루트가 한 repo 일 수 있는가 — 파일시스템에 물음(상대 gitdir·`..`·대소문자 철자는 텍스트로만
# 다름). "다름" 은 둘 다 **존재**할 때만 증명: `-ef` 는 없는 경로에 거짓이고 그 거짓은 증거 아님.
# 증명 못 하면 같은 repo — 마커를 남기는 쪽이 리뷰 안 된 커밋을 통과시키는 방향.
maybe_same_repo() {
  local here there
  here=$(common_dir "$1") || here=""
  there=$(common_dir "$2") || there=""
  if [ -e "$here" ] && [ -e "$there" ] && [ ! "$here" -ef "$there" ]; then
    return 1
  fi
  return 0
}

add_target() {
  case "$NL$targets$NL" in
    *"$NL$1$NL"*) ;;
    *) targets="${targets:+$targets$NL}$1" ;;
  esac
}

# 읽기·매치는 셸이 직접 함 — Windows 에서는 프로세스 하나가 그 일보다 비쌈.
# 64 KB 상한: 뒤의 매치가 크기에 비례하고 죽은 훅은 마커를 남김.
# 상류 실측: 16 MB 는 10초 예산에 약 4.8초, 64 KB 는 0.25초. 경로는 `tool_input` 안이라 상한보다 몇 자릿수 앞. 상한 너머는 경로
# 없는 페이로드로 읽혀 프로젝트 마커만 지워짐(다른 repo 것은 남음).
# `read -N` 이 아니라 `head -c`: 그 옵션은 bash 4.1+ 이고 macOS 는 3.2.
payload=$(head -c 65536) || payload=""
# **첫** 매치(`=~` 는 가장 왼쪽): `tool_response` 가 경로를 한 번 더 실음. `NotebookEdit` 는
# `notebook_path`.
path=""
if [[ "$payload" =~ $RE_EDIT_PATH ]]; then
  path="${BASH_REMATCH[2]}"
fi
# 비교하는 모든 경로의 단일 철자. JSON 이 백슬래시를 두 배로 만들어 구분자가 `//` 로 오는데,
# 아래 증거 디렉터리 면제 글로브는 그것을 못 맞춤. 선두 연속은 지정: 하나는 절대 경로, 둘 이상은
# 공유(share) — 두 배로 분 공유 쌍은 넷으로 옴.
to_slash() {
  local s="${1//\\//}" lead rest
  lead="${s%%[!/]*}"
  rest=${s:${#lead}}  # 길이로 자름 — 따옴표 안에 따옴표를 중첩하면 디렉터리 검증기가 못 읽음
  case "$lead" in "" | /) ;; *) lead="//" ;; esac
  while [[ "$rest" == *//* ]]; do rest="${rest//\/\///}"; done  # `tr -s /` 를 프로세스 없이
  s="$lead$rest"
  printf '%s' "${s%/}"
}

# 페이로드 `cwd` 의 repo 루트 — 세션 자신의 트리.
payload_cwd_root() {
  local cwd
  [[ "$payload" =~ $RE_CWD ]] || return 1
  cwd="${BASH_REMATCH[1]}"
  cwd="${cwd//\\\\/\\}"  # JSON 은 경로의 백슬래시를 둘로 씀 — to_slash 전에 접음
  cwd=$(to_slash "$cwd")
  root_for "$cwd"
}

# Codex 는 편집을 `apply_patch`(셸로 돌리면 Bash 명령)로 알림 — file_path 모양은 안 옴.
# - 사전 필터(따옴표 친 tool_name 값 또는 패치 마커)는 JSON 공백 모양과 무관하고, hook_io.py 를
#   띄울지만 정함. 무엇이 편집인지는 hook_io.py 의 답.
# - 그 밖의 것(평범한 `git add -A`)은 마커 전에 끝남 — 스테이징 전에 지우면 증거가 자기를 번
#   커밋보다 먼저 사라짐.
if [ "$HARNESS" = codex ]; then
  case "$payload" in
    *'"apply_patch"'* | *'*** Begin Patch'*) ;;
    *) exit 0 ;;
  esac
  # Codex 는 호스트 사본(`/vdev-init` 이 복사한 VWAY_DIR/hooks)을 돌림 — 플러그인 트리는 그 위.
  # 실행 경로를 `${CLAUDE_PLUGIN_ROOT}/...` 리터럴로 적어야 디렉터리 검증기가 무엇이 도는지 읽음.
  hook_src=$(dirname "${BASH_SOURCE[0]}")
  CLAUDE_PLUGIN_ROOT=$(cd "$hook_src/.." && pwd)
  # 종료 코드는 hook_io.py 독스트링: 0 은 경로를 찍었거나 "편집 아님", 그 밖은 자리를 못 댄 편집
  # 또는 실패한 실행. here-string 아닌 파이프 — Git Bash 의 here-string 은 64 KB 에서 멈춤(상류 실측).
  unplaced=0
  edited=$(printf '%s' "$payload" | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness/codex/hook_io.py" edited-paths 2>/dev/null) || unplaced=1
  targets=""
  IFS=$NL
  for one in $edited; do
    one=$(to_slash "$one")
    case "$one" in */"$EVIDENCE"/*|"") continue ;; esac
    root=$(root_for "${one%/*}") || continue
    add_target "$root"
  done
  unset IFS
  # 자리를 못 댄 편집이나 돌지 못한 hook_io.py(python3 부재)는 `cwd` 루트 증거를 지움 — Codex 에는
  # CLAUDE_PROJECT_DIR 폴백이 없고, 실측한 모든 페이로드에서 `cwd` 는 `tool_input` 앞이라 64 KB
  # 잘림에서 살아남음. 잘린 페이로드도 hook_io.py 가 도구 이름·남은 명령으로 판정함.
  # 자리를 댄 편집도 cwd 루트와 한 repo 일 수 있으면 함께 지움 — 게이트가 worktree 를 못 대면
  # 세션 트리로 물러서므로.
  if cwd_root=$(payload_cwd_root); then
    if [ "$unplaced" -eq 1 ]; then
      add_target "$cwd_root"
    else
      IFS=$NL
      for root in $targets; do
        case "$root" in "" | "$cwd_root") continue ;; esac
        maybe_same_repo "$root" "$cwd_root" && add_target "$cwd_root"
      done
      unset IFS
    fi
  fi
fi

# 오타 난 훅 엔트리는 편집 자리를 못 댐: 세션이 판정받을 수 있는 두 트리를 다 지움.
if [ "$HARNESS" = unknown ]; then
  targets=""
  project=$(to_slash "${CLAUDE_PROJECT_DIR:-}")
  [ -z "$project" ] || add_target "$project"
  if cwd_root=$(payload_cwd_root); then
    add_target "$cwd_root"
  fi
fi

if [ "$HARNESS" = claude ]; then
  path=$(to_slash "$path")
  case "$path" in
    */"$EVIDENCE"/*) exit 0 ;;  # 증거 디렉터리는 자기 파일을 스스로 씀
  esac

  # 게이트가 읽을 수 있는 모든 트리: 편집된 파일의 루트, 그리고 **같은** repo 일 수 있는 세션
  # 프로젝트 디렉터리 — 게이트는 커밋의 worktree 를 못 대면(detached HEAD 등) 그쪽으로 물러섬
  # (Invariant 7). 둘 다 지워야 게이트의 어느 답에도 상위집합이 됨.
  targets=""
  case "$path" in
    */*)
      edited=$(root_for "${path%/*}") || edited=""
      project=$(to_slash "${CLAUDE_PROJECT_DIR:-}")
      if [ -n "$edited" ]; then
        targets="$edited"
        # 둘이 **다른** repo 임이 증명되지 않는 한 합집합(판정은 maybe_same_repo).
        if [ -n "$project" ] && [ "$project" != "$edited" ] &&
          maybe_same_repo "$edited" "$project"; then
          targets="$targets$NL$project"
        fi
      fi
      ;;
    *)
      # 경로가 없거나 자리를 못 잡는 맨 이름: 편집 위치를 모르므로 프로젝트 증거를 지움.
      targets=$(to_slash "${CLAUDE_PROJECT_DIR:-}")
      ;;
  esac
fi
[ -n "$targets" ] || bad_args
[ -n "$targets" ] || exit 0

IFS=$NL
for target in $targets; do
  [ -n "$target" ] || continue
  # 이 트리가 스위치를 껐음: 마커가 편집을 넘어 삶. 같은 목록의 다른 트리는 자기가 답함.
  opted_out "$target" && continue
  evidence_dir="$target/$EVIDENCE"
  [ -d "$evidence_dir" ] || continue
  unset IFS
  for marker in $MARKERS; do
    [ -e "$evidence_dir/$marker" ] || continue
    rm -f "$evidence_dir/$marker" 2>/dev/null || continue
    case ", $voided, " in
      *", ${marker%.done}, "*) ;;
      *) voided="${voided}${voided:+, }${marker%.done}" ;;
    esac
  done
done
unset IFS
bad_args
[ -n "$voided" ] || exit 0

# 실제로 무효화했을 때만 알림 — 편집마다 말하면 소음, 안 말하면 에이전트가 게이트를 다시 안 밟음.
printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s"}}\n' \
  "vway-kit: 이 편집이 ${voided} 게이트 증거를 무효화했습니다. 커밋 전에 해당 게이트를 다시 밟으세요."
