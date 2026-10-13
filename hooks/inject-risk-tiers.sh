#!/usr/bin/env bash
# SessionStart hook — 룰을 세션 컨텍스트에 주입 + 편집 중인 소스 repo 가 이 세션이 로드한
# 빌드가 아닐 때 플러그인 개발자에게 알림.
#
# 플러그인 rules/ 는 자동 로드 안 됨(ras_llm 의 .claude/rules 자동 로드와 다름) → 이 hook 이
# always-on rule 역할을 대신해 매 세션 risk-tiers.md 전문과 doc-style.md 의 쓰기 시점 요약을 주입
# (요약은 이전 /vdev-init 이 호스트 .claude/rules/ 에 남긴 사본이 있는 Claude 세션에선 생략).
# 파일 부재·읽기 실패는 빈 주입으로 조용히 통과(FAIL-OPEN). doc-style 은 risk-tiers 와 달리
# 부재해도 계속 — 게이트가 아니라 문체 규율이라 없으면 없는 대로 세션이 성립.
#
# Claude Code 는 10,000자를 넘는 `additionalContext` 를 파일 경로와 2,000자 미리보기로 바꿈 —
# 오류 없이 룰 본문이 사라짐. 주입 전체가 그 한도 밑이어야 함
# (tests/inject_risk_tiers/test_rule_injection.py 가 출하 룰로 잼).
#
# 출력 규약(superpowers session-start 패턴):
#   - Cursor      : additional_context (snake_case, top-level)
#   - Claude Code : hookSpecificOutput.additionalContext (nested)
#   - 그 외(SDK)  : additionalContext (top-level)
# heredoc 은 bash 5.3+ 에서 hang 이슈 → printf 로 출력.
#
# `--harness codex` 는 Codex SessionStart(`/vdev-init` 이 호스트 `.codex/hooks.json` 에 등록)의
# 호출 — 같은 두 블록 앞에 슬래시 이름을 `$name` 으로 읽으라는 한 줄을 얹고
# `rules/harness-tools/codex.md` 를 뒤에 붙여 위 Claude 모양으로 냄.
# 인자 없음 = Claude Code(모든 기존 호스트) — `--harness claude` 와 같은 출력.

set -uo pipefail
# 내내 바이트 단위: 여기 패턴은 전부 ASCII 이고 출력은 전부 바이트 복사. 멀티바이트 로캘에선
# bash `${s//…}` 가 매치마다 문자열을 다시 훑어 비ASCII 룰에서 2차. 한 번만 둠 — 호출마다
# `local LC_ALL` 이면 돌아갈 때마다 호출자 로캘을 다시 읽음.
LC_ALL=C

# 페이로드를 보낸 하네스. 인자 없음 = Claude Code.
# 그 밖의 인자는 오타 난 훅 엔트리. 세션은 그래도 Claude 판 룰을 받음 — 룰이 아예 없는 것이
# 틀린 호출 철자보다 나쁨 — 그리고 잘못된 엔트리를 지목하는 블록도 받아, 첫 차단 커밋이 아니라
# 세션 시작에 보임.
HARNESS=claude
if [ "$#" -gt 0 ]; then
  case "$#:$1:${2:-}" in
    2:--harness:claude | 2:--harness:codex) HARNESS=$2 ;;
    *)
      HARNESS=unknown
      printf '%s: 알 수 없는 인자 "%s" (기대: --harness claude|codex)\n' "${0##*/}" "$*" >&2
      # 인쇄 가능한 ASCII 만: escape_for_json 은 다른 제어 바이트·깨진 UTF-8 을 그대로 넘기고,
      # 어느 쪽이든 주입 전체를 파싱 불가로 만듦. `<`·`>` 도 빼야 인자가 자기를 감싼 블록을 못 닫음.
      ARGS="$*"
      ARGS="${ARGS//[![:print:]]/?}"
      ARGS="${ARGS//[<>]/?}"
      ;;
  esac
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
[ -n "$PLUGIN_ROOT" ] || PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULE_FILE="${PLUGIN_ROOT}/rules/risk-tiers.md"
STYLE_FILE="${PLUGIN_ROOT}/rules/doc-style.md"
SRC_MANIFEST="${CLAUDE_PROJECT_DIR:-}/.claude-plugin/plugin.json"

# 아래 헬퍼는 전부 `$(...)` 가 아니라 호출자가 지목한 변수로 돌려줌: 명령 치환 하나가 fork
# 하나. 상류 harness-tier 실측(Git Bash 5.2, 출하 룰, 7회 중앙값): 치환 열 개면 세션 시작마다
# 1050 ms, 없으면 126 ms, 빈 `bash -c :` 가 105 ms.

# 헬퍼들의 `printf -v` 대상 — ShellCheck 가 대입을 볼 수 있는 자리에 선언.
rule_escaped="" rules_dir_escaped="" notice_escaped="" args_escaped=""
tools_escaped="" manifest_name="" manifest_version=""

# 룰 파일이 없으면 주입할 것이 없으므로 조용히 종료(FAIL-OPEN).
# `$(<file)` 은 bash 5.2 부터 셸 안에서 읽음 — `read -d ''` 는 msys 에서 바이트마다 syscall.
[ -f "$RULE_FILE" ] || exit 0
{ rule_content="$(<"$RULE_FILE")"; } 2>/dev/null || exit 0

# 같은 이스케이프를 치환 다섯 번 대신 awk 프로세스 하나로 — bash 3(macOS /bin/bash)용. bash 3 은
# 매치마다 문자열 전체를 복사함. 상류 실측(출하 룰, WSL 네이티브 파일시스템의 bash 3.2.57, 15회
# 중앙값): 훅 전체가 치환으로 290 ms, awk 로 11 ms. bash 4.4 에선 두 경로가 잡음 안에서 같아
# bash 4 이상은 치환을 유지하고, Git Bash(5.2)는 거기에 fork 를 안 씀.
# 끝의 x 는 마지막 개행이 마지막 레코드의 끝으로 읽히지 않게 둠.
# shellcheck disable=SC2016 # awk 자신의 프로그램 텍스트 — 셸이 확장할 것이 없음.
json_escape_awk='{
  if (NR > 1) printf "%s", "\\n"
  n = length($0); out = ""
  for (i = 1; i <= n; i++) {
    c = substr($0, i, 1)
    if (c == "\\") c = "\\\\"
    else if (c == "\"") c = "\\\""
    else if (c == "\r") c = "\\r"
    else if (c == "\t") c = "\\t"
    out = out c
  }
  printf "%s", out
}'

# bash 파라미터 치환으로 JSON 문자열 escape (문자 단위 루프보다 빠름).
# 이스케이프는 전부 ASCII 이고 UTF-8 연속 바이트는 ASCII 가 아니므로, C 로캘의 바이트 단위
# 처리가 문자 단위 처리와 같은 출력을 냄. awk 가 실패하면 bash 경로로 감.
escape_for_json() { # <변수> <값>
  local _s
  if [ "${BASH_VERSINFO[0]}" -lt 4 ] &&
    _s="$(printf '%sx' "$2" | LC_ALL=C awk "$json_escape_awk")"; then
    printf -v "$1" '%s' "${_s%x}"
    return 0
  fi
  _s="$2"
  _s="${_s//\\/\\\\}"
  _s="${_s//\"/\\\"}"
  _s="${_s//$'\n'/\\n}"
  _s="${_s//$'\r'/\\r}"
  _s="${_s//$'\t'/\\t}"
  printf -v "$1" '%s' "$_s"
}

# --- 플러그인 버전 불일치 알림 -------------------------------------------------
# 여기까지 오는 것은 이 플러그인의 개발자뿐임. 소스 repo 에서 연 세션도 플러그인은 설치
# 캐시에서 로드하므로, version 을 올리고 재설치하지 않았다면 눈앞의 편집은 실행되는 것이
# 아님. 소비자 프로젝트에는 플러그인 매니페스트가 없어 비교에 아예 닿지 않음. 불확실한
# 분기는 전부 조용함: FAIL-OPEN — 세션보다 먼저 도는 훅은 절대 세션을 지연시키거나
# 깨뜨리면 안 됨.

manifest_pair() { # <file> -> manifest_name, manifest_version: 각각 **첫** 값, 없으면 ""
  # fork 없이 읽음: 키마다 grep|head|sed 파이프라인이면 훅의 나머지 전부보다 비쌈.
  # 첫 매치가 이기므로 실제 매니페스트 배치에서 중첩된 것(`author.name` 은 최상위 `name`
  # 뒤에 옴)이 아니라 최상위 키를 집음. 구조적 보장은 아니고 순서 의존 — 키 순서를 뒤집은
  # 매니페스트는 중첩된 값을 낼 수 있지만, 그 결과는 이름 불일치라 조용한 무동작으로
  # 끝남(FAIL-OPEN). 한 줄짜리 매니페스트도 정규식이 맨 왼쪽 매치를 잡아 같은 답.
  # 묶음 바깥의 `2>/dev/null` 이 열기 실패(권한 없음)까지 가둠 — `done <f 2>/dev/null` 은 입력
  # 리다이렉션이 먼저 실패해 오류가 그대로 찍힘.
  local line
  manifest_name="" manifest_version=""
  { while IFS= read -r line || [ -n "$line" ]; do
    if [ -z "$manifest_name" ] &&
      [[ $line =~ \"name\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
      manifest_name="${BASH_REMATCH[1]}"
    fi
    if [ -z "$manifest_version" ] &&
      [[ $line =~ \"version\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
      manifest_version="${BASH_REMATCH[1]}"
    fi
    [ -n "$manifest_name" ] && [ -n "$manifest_version" ] && break
  done <"$1"; } 2>/dev/null
}

safe_token() { # <변수> <값>: 짧고 name/version 문자만 있으면 그 값, 아니면 ""
  # 매니페스트는 세션이 열린 repo 의 것이라 여기서 유일하게 신뢰할 수 없는 입력이고,
  # 이스케이프가 아니라 폐기함. 날 제어 바이트는 escape_for_json 이 호스트가 파싱 못 할
  # JSON 을 내게 만들어 **룰 주입까지** 앗아가고, `<`/`>` 는 값이 알림 태그를 닫고 컨텍스트에
  # 직접 쓰게 함.
  # 길이도 같이 막음. 문자 집합만으로는 부족 — `.`·`-` 를 낱말 구분자로 쓰면 허용
  # 문자만으로 읽히는 영어를 쓸 수 있고, 그 값은 "전달하라"는 지시 아래 주입 컨텍스트
  # **맨 앞**에 놓임(4000회 반복으로 132KB 를 실어 보내는 것을 실측). 이름도 버전도
  # 실제로는 짧으므로 64자를 넘으면 그 값은 이 알림이 말하려던 것이 아님.
  printf -v "$1" '%s' ""
  case "$2" in
  "" | *[!A-Za-z0-9._+-]*) return 0 ;;
  esac
  [ "${#2}" -le 64 ] || return 0
  printf -v "$1" '%s' "$2"
}

version_notice() { # -> notice: 버전 불일치 한 줄, 또는 ""
  local loaded src_name loaded_name src_ver loaded_ver
  notice=""
  loaded="${PLUGIN_ROOT}/.claude-plugin/plugin.json"
  [ -f "$loaded" ] || return 0
  manifest_pair "$SRC_MANIFEST"
  safe_token src_name "$manifest_name"
  safe_token src_ver "$manifest_version"
  manifest_pair "$loaded"
  safe_token loaded_name "$manifest_name"
  safe_token loaded_ver "$manifest_version"
  # **다른** 플러그인을 개발 중인 repo 가 이걸 건드리면 안 됨.
  { [ -n "$src_name" ] && [ "$src_name" = "$loaded_name" ]; } || return 0
  { [ -n "$src_ver" ] && [ -n "$loaded_ver" ]; } || return 0
  [ "$src_ver" != "$loaded_ver" ] || return 0
  printf -v notice '[%s] 소스 %s != 로드된 %s — 이 세션이 실행하는 것은 %s 입니다. 둘을 맞추려면 플러그인을 재설치하거나 소스 브랜치를 확인하세요.' \
    "$loaded_name" "$src_ver" "$loaded_ver" "$loaded_ver"
}

# 이 세션이 플러그인 자신의 소스 트리에 있지 않으면 비교할 것이 없으므로, stdin 을 건드리기
# 전에 그것부터 판정 — 소비자는 그 읽기 비용을 아예 안 냄. `-f` 는 그 경로의 FIFO 가
# 훅을 영원히 막는 것도 함께 막음(뒤쪽엔 타임아웃이 없음).
# 비교 대상이 Claude 설치 캐시의 매니페스트라 Codex 에선 안 냄 — Codex 가 실행하는 빌드와 무관함.
# 오타 난 엔트리는 Claude 판을 받으므로 알림도 받음.
notice=""
if [ "$HARNESS" != codex ] && [ -f "$SRC_MANIFEST" ]; then
  # 새 세션에서만 알림 — clear/compact 마다 되풀이하면 소음. 읽기에 타임아웃을 두는
  # 것은 안 닫히는 파이프가 세션 시작을 hang 시키면 안 되기 때문이고, source 를 못 읽으면
  # 조용해지는 대신 알림: 아무도 필요 없던 알림이, 조용히 멈춘 기능보다 나음.
  hook_stdin=""
  IFS= read -r -t 1 -d '' hook_stdin 2>/dev/null || true
  if ! [[ $hook_stdin =~ \"source\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] ||
    [ "${BASH_REMATCH[1]}" = "startup" ]; then
    version_notice
  fi
fi

# 훅의 `systemMessage` 는 이것을 관측할 수 있는 채널에 닿지 않으므로, 알림은 주입 컨텍스트
# 안에 자기 태그로 실려 가고 전달 지시를 함께 실음.
notice_block=""
if [ -n "$notice" ]; then
  escape_for_json notice_escaped "$notice"
  notice_block="<vway-kit-stale-build>\nRelay this to the user before doing anything else:\n${notice_escaped}\n</vway-kit-stale-build>\n\n"
fi

# 룰은 분리된 형제를 확장자만 남긴 bare filename 으로 링크하는데,
# 플러그인은 버전 캐시에 살아 세션엔 그것을 붙일 디렉터리가 없음. 경로는 룰 **뒤**에
# 댐 — mandate 옆에 놓인 텍스트는 측정된 스킬 호출률을 움직이고, 경로는 그만한 값이
# 아님.
escape_for_json rule_escaped "$rule_content"
escape_for_json rules_dir_escaped "${PLUGIN_ROOT}/rules"
# 지시는 룰 자신의 Principle 이 실음. Codex 는 슬래시 이름을 자기 철자로 읽으라는 한 줄만 받음 —
# 그 줄이 없으면 모델이 `/vdev` 철자로 답함(실측).
harness_line=""
if [ "$HARNESS" = codex ]; then
  # shellcheck disable=SC2016 # $vdev 는 Codex 의 스킬 호출 철자 — 확장되면 안 되는 리터럴.
  harness_line='On Codex a slash command below that names a vway-kit skill is that skill, invoked as $name: start with $vdev, open its SKILL.md and follow it in full.'"\n\n"
fi
session_context="${notice_block}<vway-kit-risk-tiers>\n${harness_line}${rule_escaped}\n\nThe files this rule links by bare filename live in ${rules_dir_escaped} — read one there when it sends you to it.\n</vway-kit-risk-tiers>"

# 문체 규율은 자기 태그로 뒤에 붙음 — 앞의 게이트 지시와 섞이면 "커밋 전 /vdev" 가 문체
# 조언처럼 읽힘. 전문이 아니라 쓰는 순간 필요한 요약이고, 전문은 경로로 가리킴. 플러그인에
# 파일이 없으면 블록 자체가 없음. 이전 /vdev-init 이 같은 파일을 호스트 .claude/rules/ 에
# 남겼으면(vdev_init_setup.py 의 RULES_DEST) 재동기화가 지울 때까지 Claude Code 가 그것을 직접
# 로드하므로 건너뜀 — 두 경로 리터럴은 함께 움직임. Codex 는 .claude/rules/ 를 읽지 않아 유지.
host_rule="${CLAUDE_PROJECT_DIR:-.}/.claude/rules/vway-kit/doc-style.md"
if [ -f "$STYLE_FILE" ] && { [ "$HARNESS" = codex ] || [ ! -f "$host_rule" ]; }; then
  session_context="${session_context}\n\n<vway-kit-doc-style>\nApply this to every piece of prose you write or edit here — .md files, rules, comments, docstrings, commit bodies; restate it in the user's language when you surface it. Code, commands and error strings stay verbatim.\n\nWrite the fact in force, as bullets ending in a noun form (\`~함\`·\`~됨\`·\`~없음\`, never \`~한다\`·\`~이다\`; a manual that addresses its reader keeps \`~니다\`). One fact in one place; link the rest. No change history, commit sha, plan pointer, filler, revision field, or line number after a filename. A number only as a contract or a measurement with its conditions. Prefer code that raises (an assert, a bound, a type) over a comment, and never explain how. A trap with no runtime moment gets the box, its keys untranslated and on adjacent lines:\n  CRITICAL TRAP: / Trigger: / Symptom:\n\nFull rule: ${rules_dir_escaped}/doc-style.md\n</vway-kit-doc-style>"
fi

# 맨 뒤 — 문체 블록을 떼어 둔 것과 같은 이유: mandate 옆에 새 텍스트를 두지 않음.
if [ "$HARNESS" = unknown ]; then
  escape_for_json args_escaped "$ARGS"
  session_context="${session_context}\n\n<vway-kit-hook-error>\nRelay this to the user before doing anything else: the vway-kit SessionStart hook entry passed unknown arguments \\\"${args_escaped}\\\" (expected --harness claude|codex), so the rule above is in its Claude Code form. Fix the hook entry.\n</vway-kit-hook-error>"
fi

# Codex 도구 노트는 두 룰 뒤 자기 태그로 — 파일이 없으면 블록만 빠지고 룰 주입은 그대로(FAIL-OPEN).
if [ "$HARNESS" = codex ]; then
  tools_file="${PLUGIN_ROOT}/rules/harness-tools/codex.md"
  if [ -f "$tools_file" ] && { tools_content="$(<"$tools_file")"; } 2>/dev/null; then
    escape_for_json tools_escaped "$tools_content"
    session_context="${session_context}\n\n<vway-kit-codex-tools>\n${tools_escaped}\n</vway-kit-codex-tools>"
  fi
  printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$session_context"
  exit 0
fi

if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  printf '{\n  "additional_context": "%s"\n}\n' "$session_context"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
  printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$session_context"
else
  printf '{\n  "additionalContext": "%s"\n}\n' "$session_context"
fi

exit 0
