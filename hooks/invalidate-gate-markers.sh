#!/usr/bin/env bash
# PostToolUse 훅 — 편집은 review·doc-sync 증거를 무효화함.
#
# 이 둘은 워킹트리를 판정하는 게이트이고, 마커는 자기를 쓴 커밋보다 오래 삶 — 커밋이 그것을
# 지우지 않고, `tier` 마커와 달리 브랜치에도 안 매임.
# 그대로 두면 통과 뒤에 넣은 수정이, 어떤 리뷰어도 어떤 문서 정합화도 본 적 없는 코드 위에서
# 번 증거로 커밋됨. 둘이 한 쌍인 이유는 서로를 무효화하기 때문 — 리뷰 지적을 doc-sync 뒤에
# 고치면 그 수정은 문서에 없음 — 그래서 성립하는 상태는 "둘 다 기록됨, 그 뒤 편집 없음" 뿐.
#
# 지우는 쪽이 안전한 방향: 살아남았어야 할 마커를 지우면 재실행 한 번이지만, 사라졌어야 할
# 마커를 남기면 리뷰 안 된 커밋이 통과함. 그래서 판정 못 하는 경우는 오타 난 훅 엔트리까지
# 전부 지우고, 이 훅 자체의 실패는 마커를 건드리지 않음(FAIL-OPEN — 게이트는 이미 가진 더
# 엄격한 답을 유지).
#
# bump·security 는 일부러 여기 없음 — 깨끗한 트리에서 내리는 승격 시점 결정이라, 무효화할
# 편집이 뒤따르지 않음.

set -uo pipefail

# 어느 하네스가 보낸 페이로드인가 — 훅 엔트리가 이름 대고, 환경에서 추측하지 않음: Codex 도
# CLAUDE_PLUGIN_ROOT 를 줌. 인자 없음 = Claude Code(기존 호스트 전부).
# 그 밖의 인자는 오타 난 훅 엔트리 — Claude 로 읽으면 조용히 틀린 길로 감. 편집이 어디
# 떨어졌는지도 못 대므로 세션의 트리를 무효화하고 exit 2 — 누가 고칠 때까지 호출마다 잘못된
# 엔트리가 에이전트 앞에 섬.
HARNESS=claude
if [ "$#" -gt 0 ]; then
  case "$#:$1:${2:-}" in
    2:--harness:claude | 2:--harness:codex) HARNESS=$2 ;;
    *)
      HARNESS=unknown
      # exit 2 는 stderr 를 에이전트에 넘김 — 인쇄 가능한 ASCII 만.
      ARGS="$(LC_ALL=C; a="$*"; printf '%s' "${a//[![:print:]]/?}")"
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

# 호스트 자신의 스위치, **한 트리**에게 물음. 이 훅은 플러그인이 등록하므로 버전만 올라가도 모든
# 소비자에게 켜짐 — `/vdev-init` 재실행도, 누가 동의한 단계도 없음. 옛 순서(리뷰 → 작은 수정 →
# 커밋)를 원하는 팀이 그렇게 말할 수 있어야 하고, 재실행 비용을 치르는 쪽이 호스트이므로 답도
# 호스트에서 옴. 세션에 한 번이 아니라 아래 대상마다 묻는 이유도 같음 — 끈 프로젝트는 자기
# 증거만 대신 말하고 다른 repo 의 것은 대신 말하지 않음.
#
# 파싱이 아니라 줄 단위로 읽음: 편집마다 돌고, YAML 파서는 프로세스 하나.
# 스위치는 평범한 블록을 여는 최상위 `gate_evidence:` 밑의 `false` 하나 — 다른 값·다른 자리는
# 전부 켜진 채로 둠. `rules/gate-mechanics.md` 가 소비자에게 약속한 것이고, 읽을 수 없는 파일이
# 떨어져야 할 방향. 그 밖의 것을 단 헤더(흐름 매핑, 블록 스칼라)는 블록을 열지 않으므로 그 밑은
# 읽지 않음. 꺼짐은 요청받는 것이지 추론하는 것이 아님.
opted_out() {
  # `line` 도 초기화: 첫 `read` 가 실패하면(설정 자리가 디렉터리, I/O 오류) 빈 변수가 `set -u`
  # 에서 훅 전체를 죽여 마커가 남음 — 스위치 리더의 실패는 켜진 채로 떨어져야 함.
  local root=$1 line="" indent child="" in_block=0 answer=1
  [ -n "$root" ] && [ -r "$root/$CONFIG" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    # Windows 에서 고친 설정은 CRLF 로 오고 줄을 벗기지 않음: 끝의 CR 은 아래 모든
    # `[[:space:]]` 에게 공백이고, 각 패턴이 거기서 끝남.
    # 0열의 키는 블록을 열고 앞 블록을 닫음. `#` 을 빼는 이유는 헤더와 키 사이의 주석이 블록을
    # 끝내지 않게 하려는 것. 빈 줄과 들여쓴 줄은 통과해 블록을 그대로 둠.
    if [[ $line =~ ^[^[:space:]#] ]]; then
      if [[ $line =~ ^gate_evidence[[:space:]]*:[[:space:]]*(#.*)?$ ]]; then
        in_block=1
        answer=1  # 중복 블록은 질문을 다시 엶 — 답을 정하는 것은 그 블록 자신의 줄뿐
      else
        in_block=0
      fi
      child=""
      continue
    fi
    [ "$in_block" -eq 1 ] || continue
    [[ $line =~ ^([[:space:]]+)[^[:space:]#] ]] || continue  # 빈 줄, 또는 들여쓴 주석
    indent=${BASH_REMATCH[1]}
    # 블록의 키는 전부 첫 키가 정한 들여쓰기에 앉음. 더 깊으면 다른 것의 안 — 중첩 매핑, 블록
    # 스칼라의 본문 — 이고, 거기 줄은 아무리 이 설정처럼 보여도 이 설정이 아님(YAML 도 그렇게 안 읽음).
    [ -n "$child" ] || child=$indent
    [ "$indent" = "$child" ] || continue
    # 매치 뒤에도 계속 훑음: YAML 은 중복을 마지막 것으로 풀므로 여기서도 마지막이 답 — 키 중복도,
    # 블록 중복도(그래서 위 헤더가 들여쓰기와 함께 답도 지움). 아래 두 공백은 YAML 자신이 값 앞과
    # 주석 앞에 요구하는 것 — `invalidate_on_edit:false` 와 `false# x` 는 파서에게 각각 긴 문자열
    # 하나이므로 여기서도 스위치를 끈 것이 아님.
    if [[ $line =~ ^[[:space:]]+invalidate_on_edit[[:space:]]*:[[:space:]]+false([[:space:]]+#.*)?[[:space:]]*$ ]]; then
      answer=0
    elif [[ $line =~ ^[[:space:]]+invalidate_on_edit[[:space:]]*: ]]; then
      answer=1
    fi
  done < "$root/$CONFIG"
  return $answer
}

# 이 편집이 낡게 만든 증거가 어느 트리의 것인가 — 세션이 아니라 편집된 파일에게 물음.
# 게이트는 커밋이 발행된 repo 루트를 기준으로 판정하고 worktree 도 그렇게 봄(Invariant 7),
# 그래서 낡은 증거는 편집된 파일 **자신의** 루트에 있는 것. 첫 증거 디렉터리가 아니라 그
# 루트까지 걷는 것이 걸음을 가두는 장치 — 스크래치패드 파일 위에는 루트가 없고, 두 단계 위
# 프로젝트가 아래에서 난 편집 때문에 증거를 잃지 않음.
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

# 그 루트가 git 데이터를 두는 곳 — 같은 repo 의 모든 worktree 가 공유하는 하나의 답이고,
# 그것이 "두 repo" 와 "한 repo 의 두 시점" 을 가름. `git` 에게 묻지 않고 읽음: 편집마다
# 도는 훅이고, 파일에 적혀 있음.
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

# 두 루트가 한 repo 의 두 시점일 수 있는가 — 문자열이 아니라 파일시스템에 물음: 상대 `gitdir:`,
# 남아 있는 `..`, 대소문자만 다른 철자, 아예 루트가 아닌 프로젝트 디렉터리 — 전부 같은 repo 를
# 가리키면서 텍스트로는 다름. "다름" 이 증명이 되려면 둘 다 **존재**해야 함 — `-ef` 는 아무것도
# 가리키지 않는 경로에 대해 거짓이고(repo 가 이사한 worktree, 지워진 외부 git 디렉터리), 그 거짓은
# 아무 증거도 아님. 증명 안 되면 같은 repo 로 간주: 마커를 남기는 쪽이 리뷰 안 된 커밋을 통과시키는
# 방향.
maybe_same_repo() {
  local here there
  here="$(common_dir "$1")" || here=""
  there="$(common_dir "$2")" || there=""
  ! { [ -e "$here" ] && [ -e "$there" ] && [ ! "$here" -ef "$there" ]; }
}

add_target() {
  case $'\n'"$targets"$'\n' in
    *$'\n'"$1"$'\n'*) ;;
    *) targets="${targets:+$targets
}$1" ;;
  esac
}

# 읽기와 매치를 셸 자신이 함. 편집마다 돌고, Windows 에서는 띄운 프로세스 하나가 그 일보다
# 비쌈 — 하네스를 설치한 적 없는 repo 도 지울 것이 없다는 답을 얻으려고 파이프라인 전체를 치렀음.
#
# 상한을 두는 이유: 뒤따르는 모든 것이 받은 크기만큼 시간을 씀. 16 MB 페이로드 매치는 hooks.json
# 의 10초 예산에 약 4.8초, 64 KB 는 0.25초(상류 실측)이고, 죽은 훅은 마커를 남김 — 이 훅이 절대
# 틀리면 안 되는 방향. 경로는 `tool_input` 안에 있고 그 앞은 세션의 작은 필드뿐이라 상한은 그보다
# 몇 자릿수 멂. 상한 너머는 경로 없는 페이로드로 읽힘: 프로젝트의 마커는 지워지고 **다른** repo
# 의 것은 남음 — 안전하지 않은 절반이고, 상한을 흔한 페이로드가 아니라 실제 페이로드가 닿지 않는
# 자리에 둔 이유.
#
# bash 자신의 `read -N` 이 아니라 `head -c`: 그 옵션은 4.1 이상이고 macOS 는 3.2 를 실음. 거기서는
# 옵션이 오류라 페이로드가 비고 편집마다 엉뚱한 트리가 무효화됨. 프로세스 하나로 플랫폼 전체를
# 되사고, 예전 다섯 중 넷은 여전히 사라짐.
payload="$(head -c 65536)" || payload=""
# 마지막이 아니라 **첫** 매치: `tool_response` 가 `tool_input` 뒤에 자기 경로를 한 번 더
# 실으므로, 욕심껏 읽으면 응답이 편집 위치를 정함. `NotebookEdit` 는 키 철자가 다르고,
# 읽지 않으면 경로가 아예 없는 페이로드가 됨. `=~` 는 가장 왼쪽 매치를 잡음.
path=""
if [[ "$payload" =~ \"(file|notebook)_path\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
  path="${BASH_REMATCH[2]}"
fi
# 이 훅이 경로를 읽는 단 하나의 철자, 비교하는 모든 것에 적용: bash 는 OS 의 구분자 중
# 하나만 경로로 받고, 세션의 프로젝트 디렉터리는 페이로드가 아니라 OS 의 철자로 옴. JSON 은
# 백슬래시를 모두 두 배로 만들므로 구분자마다 `//` 로 도착하는데, 파일시스템은 삼키지만 글로브는
# 매치하지 않음 — 아래 증거 디렉터리 면제가 글로브. 선두의 연속은 압축이 아니라 지정:
# 슬래시 하나는 절대 경로, 둘은 공유(share)이고, 두 배로 불면 공유의 쌍이 넷으로 옴.
# (여기서 그 둘을 구분할 방법은 없음 — Linux 도 MSYS 도 근거로 삼을 공유를 내주지 않음 —
# 그래서 그 줄은 측정이 아니라 읽은 것.)
to_slash() {
  local s="${1//\\//}" lead rest
  lead="${s%%[!/]*}"
  case "$lead" in "" | /) ;; *) lead="//" ;; esac
  rest="${s#"${s%%[!/]*}"}"
  while [[ "$rest" == *//* ]]; do rest="${rest//\/\///}"; done  # `tr -s /` 를 프로세스 없이
  s="$lead$rest"
  printf '%s' "${s%/}"
}

# 페이로드 `cwd` 의 repo 루트 — 세션 자신의 트리.
payload_cwd_root() {
  local cwd
  [[ "$payload" =~ \"cwd\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] || return 1
  cwd="${BASH_REMATCH[1]}"
  cwd="${cwd//\\\\/\\}"  # JSON 은 경로의 백슬래시를 둘로 씀 — to_slash 전에 접음
  root_for "$(to_slash "$cwd")"
}

# Codex 는 편집을 전부 `apply_patch` 로, 모델이 셸로 apply_patch 를 돌리면 Bash 명령으로 알림 —
# 아래 Claude 블록이 읽는 file_path/notebook_path 모양은 절대 안 옴.
# - 사전 필터는 따옴표 친 tool_name 값 또는 패치 마커로 맞춤 → 페이로드 JSON 이 압축이든 콜론
#   주변에 공백이 있든 성립. 이것은 hook_io.py 를 띄울지만 정하고, 무엇이 편집인지는 hook_io.py 의 답.
# - 그 밖의 것(평범한 Bash 로 돈 `git add -A`)은 마커를 건드리기 전에 끝남 — 커밋이 스테이징하기
#   전에 기록된 증거를 지우면, 그 증거가 자기를 번 커밋보다 먼저 사라짐.
if [ "$HARNESS" = codex ]; then
  case "$payload" in
    *'"apply_patch"'* | *'*** Begin Patch'*) ;;
    *) exit 0 ;;
  esac
  hook_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # 무엇이 편집인지는 hook_io.py 가 정함(종료 코드는 그 독스트링): 0 은 경로를 찍었거나 "편집
  # 아님", 그 밖은 자리를 못 댄 편집이거나 실패한 실행. here-string 이 아니라 파이프 — Git Bash
  # 의 `<<<` 는 64 KB 입력에서 멈춤(상류 실측).
  unplaced=0
  edited="$(printf '%s' "$payload" | python3 "$hook_dir/../scripts/harness/codex/hook_io.py" edited-paths 2>/dev/null)" || unplaced=1
  targets=""
  while IFS= read -r one; do
    one="$(to_slash "$one")"
    case "$one" in */"$EVIDENCE"/*|"") continue ;; esac
    root="$(root_for "${one%/*}")" || continue
    add_target "$root"
  done <<EOF
$edited
EOF
  # hook_io.py 가 자리를 못 댄 편집, 또는 돌지 못한 hook_io.py(python3 부재)는 페이로드 `cwd` 의
  # 루트 증거를 지움.
  # - 64 KB 읽기 상한에서 잘린 페이로드는 hook_io.py 에 깨진 JSON 으로 가고, 그래도 도구 이름과
  #   살아남은 명령 텍스트로 판정됨.
  # - Codex 에는 아래 Claude 경로의 폴백인 CLAUDE_PROJECT_DIR 가 없고, 실측한 모든 Codex 페이로드
  #   에서 `cwd` 는 `tool_input` 앞이라 잘림에서 살아남음.
  # - repo 전체 증거를 지우는 쪽이 아무것도 안 지우는 쪽보다 안전한 방향.
  #
  # 자리를 댄 편집도, 편집 루트와 cwd 루트가 한 repo 의 두 시점일 수 있으면 cwd 루트를 함께 지움:
  # cwd 루트는 세션의 트리 — 아래 Claude 경로의 CLAUDE_PROJECT_DIR 자리 — 이고, 게이트는 커밋이
  # 속한 worktree 를 이름 대지 못하면 그쪽으로 물러섬.
  if cwd_root="$(payload_cwd_root)"; then
    if [ "$unplaced" -eq 1 ]; then
      add_target "$cwd_root"
    else
      while IFS= read -r root; do
        case "$root" in "" | "$cwd_root") continue ;; esac
        maybe_same_repo "$root" "$cwd_root" && add_target "$cwd_root"
      done <<EOF
$targets
EOF
    fi
  fi
fi

# 오타 난 훅 엔트리는 어느 하네스의 방식으로도 편집 자리를 못 댐: 페이로드 모양과 무관하게
# 세션이 판정받을 수 있는 두 트리를 다 지움.
if [ "$HARNESS" = unknown ]; then
  targets=""
  project="$(to_slash "${CLAUDE_PROJECT_DIR:-}")"
  [ -z "$project" ] || add_target "$project"
  if cwd_root="$(payload_cwd_root)"; then
    add_target "$cwd_root"
  fi
fi

if [ "$HARNESS" = claude ]; then
  path="$(to_slash "$path")"
  case "$path" in
    */"$EVIDENCE"/*) exit 0 ;;  # 증거 디렉터리는 자기 파일을 스스로 씀
  esac

  # 이 편집을 판정할 수 있는 게이트가 읽는 모든 트리. 첫째는 편집된 파일의 루트, 둘째는 세션의
  # 프로젝트 디렉터리 — 단 그것이 **같은** repo 의 다른 시점일 때만. 게이트가 커밋이 속한
  # worktree 를 늘 이름 댈 수 있는 것은 아니라서(detached HEAD, worktree 엔트리에 없는 브랜치)
  # 프로젝트 디렉터리를 읽는 쪽으로 물러서기 때문(Invariant 7 — 그 불확실성을 main 쪽으로
  # 겨눠 둠). 둘 다 무효화해야 이 훅이 게이트가 어느 답을 내든 그 상위집합이 됨. 하나만
  # 무효화하면 게이트는 아무 편집도 닿지 않은 마커를 읽음.
  targets=""
  case "$path" in
    */*)
      edited="$(root_for "${path%/*}")" || edited=""
      project="$(to_slash "${CLAUDE_PROJECT_DIR:-}")"
      if [ -n "$edited" ]; then
        targets="$edited"
        # 둘이 **다른** repo 임이 증명되지 않는 한 합집합(판정은 maybe_same_repo).
        if [ -n "$project" ] && [ "$project" != "$edited" ] &&
          maybe_same_repo "$edited" "$project"; then
          targets="$targets
$project"
        fi
      fi
      ;;
    *)
      # 경로가 없거나, 이 훅이 자리를 잡아 줄 수 없는 맨 이름: 편집이 어디 떨어졌는지 알 수
      # 없고, 아무도 보지 않은 편집 위에 마커를 남기는 것은 이 훅이 절대 틀리면 안 되는 방향임.
      targets="$(to_slash "${CLAUDE_PROJECT_DIR:-}")"
      ;;
  esac
fi
[ -n "$targets" ] || bad_args
[ -n "$targets" ] || exit 0

while IFS= read -r target; do
  [ -n "$target" ] || continue
  # 이 트리가 스위치를 껐음: 마커가 편집을 넘어 삶. 같은 목록의 다른 트리는 자기가 답함.
  opted_out "$target" && continue
  evidence_dir="$target/$EVIDENCE"
  [ -d "$evidence_dir" ] || continue
  for marker in $MARKERS; do
    [ -e "$evidence_dir/$marker" ] || continue
    rm -f "$evidence_dir/$marker" 2>/dev/null || continue
    case ", $voided, " in
      *", ${marker%.done}, "*) ;;
      *) voided="${voided}${voided:+, }${marker%.done}" ;;
    esac
  done
done <<EOF
$targets
EOF
bad_args
[ -n "$voided" ] || exit 0

# 실제로 무효화한 것이 있을 때만: 편집마다 말하면 소음이고, 한 번도 안 말하면 에이전트는
# 자기가 잃은 줄 모르는 게이트를 다시 밟지 않음.
printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s"}}\n' \
  "vway-kit: 이 편집이 ${voided} 게이트 증거를 무효화했습니다. 커밋 전에 해당 게이트를 다시 밟으세요."
