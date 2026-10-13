---
name: harness-insight
description: 지난 기간의 Claude Code 활동에서 개발/하네스 인사이트를 뽑거나, 누적된 프로젝트 메모리를 정리할 때 사용. "지난 N일/주 인사이트", "이번 주 뭐 했는지 정리", "하네스 후보 뽑아줘", "반복 지시 찾아줘", "활동 핫스팟", "메모리 정리해줘" 같은 요청.
argument-hint: "기간 (예: 7일, 2주, 30일 — 기본 7일)"
---

# Harness-Insight — 기간별 개발/하네스 인사이트

대상 프로젝트(이 스킬을 호출한 cwd)의 Claude Code 트랜스크립트를 집계해 **4섹션
인사이트 리포트를 대화로 출력**하고(Step 4), 이어서 누적된 **프로젝트 메모리를 검토해
정리**(Step 5). **리포트 파일(.md) 생성 금지.** 리포트용 **중간 생성물(txt
2개)만 임시로** 만들고 출력이 끝나면 삭제. 단 Step 5 는 사용자 승인 후 대상
프로젝트의 `rules/`·`docs/` 에 쓰고 메모리를 정리한다(리포트 산출물이 아니라 SSOT 갱신·
정리 — 성격이 다름). 프로젝트 비종속 — 어떤 저장소에서나 동작(명령어 그룹·핫스팟·
메모리 경로·문서 형식은 데이터/대상 프로젝트에서 도출).

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## 경로
```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
PLUGIN="${CLAUDE_PLUGIN_ROOT}"
TMP="${ROOT}/.claude/vway-kit/.vdev/insight"   # 중간 생성물 (작업 후 삭제)
```
각 Bash 호출은 새 셸임 — 뒤의 블록마다 이 대입을 다시 열지 않으면 거기서 이 변수들이 빔.
`TMP` 가 고정 경로인 이유도 그것 — `mktemp` 디렉터리는 블록마다 달라짐. 거기엔 사용자 프롬프트가
담기므로 Step 2 가 먼저 `.claude/vway-kit/.vdev/` 를 `.gitignore` 에 넣음 — Step 6 전에 끊긴 실행도
`git add` 가 집을 것을 남기지 않음.
중간 txt 는 임시 디렉터리에만 기록(프로젝트 루트 오염 금지). 플러그인 디렉터리 쓰기 금지.
**로컬 처리만** — 트랜스크립트·메모리 데이터는 기기 밖으로 안 나감.

## Step 1 — 기간 파싱
인자(`$ARGUMENTS`)를 **일수(days)** 로 환산. 인자가 없으면 **7**.
- `N일`/`N day(s)` → N · `N주`/`N week(s)` → N×7 · `N개월`/`N month(s)` → N×30 · `오늘` → 1
- 숫자만 오면 일수로 봄. 모호하면 7로 두고 리포트 머리에 가정한 기간을 밝힘.

## Step 2 — 집계 (스크립트, 중간 생성물 생성)
```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
PLUGIN="${CLAUDE_PLUGIN_ROOT}"
TMP="${ROOT}/.claude/vway-kit/.vdev/insight"
tr -d '\r' 2>/dev/null < "${ROOT}/.gitignore" | grep -qxF '.claude/vway-kit/.vdev/' \
  || printf '\n.claude/vway-kit/.vdev/\n' >> "${ROOT}/.gitignore"
python3 "${PLUGIN}/scripts/harness_insight.py" --days <DAYS> --out-dir "${TMP}"
```
임시 디렉터리에 파일 둘을 만듦:
- `prompts.txt` — 내가 보낸 사용자 프롬프트(의도, 노이즈 제거됨)
- `activity.txt` — 실제 tool_use 집계(세션·프롬프트 수, 도구 분포, top 명령, 핫스팟 디렉터리/파일)

`no project dir found` 로 종료하면 cwd 가 Claude Code 로 작업한 적 없는 프로젝트 —
사용자에게 알리고 중단(추측 금지).

> **데이터 출처·추출 규칙 = [`references/transcript-data.md`](references/transcript-data.md)** —
> JSONL 위치/스키마, 노이즈 필터, 명령어 정규화·핫스팟 도출, 기간 필터가 거기 박제됨.
> 추출이 어긋나면(트랜스크립트 포맷 변경 등) 이 reference 를 SSOT 로 확인·갱신.

## Step 3 — 읽기
1. `Read` 로 `${TMP}/prompts.txt`·`${TMP}/activity.txt` **둘 다** 읽기.
2. 섹션 2의 `(기존)` 판정을 위해 프로젝트의 기존 하네스를 확인한다(있는 것만):
   `Read ${ROOT}/CLAUDE.md` · `Glob ${ROOT}/{rules,.claude/rules}/**/*.md` ·
   `Glob ${ROOT}/{agents,.claude/agents}/**/*.md` · `Glob ${ROOT}/{skills,.claude/skills}/**/SKILL.md` ·
   `Glob ${ROOT}/.claude/commands/**/*.md`. 없으면 그 컴포넌트 종류는 후보 박제처에서 제외.
   여기서 확인한 `rules/`·`.claude/rules/`·`docs/` 존재 여부는 Step 5 승격 대상 판단에도 씀.
3. Step 5(메모리 정리)용으로 프로젝트 메모리를 읽음: 베이스 프로젝트 디렉터리(Step 2 가
   `scanning <dir>` 로 출력한 것 중 cwd 슬러그에 해당하는 경로)의 `memory/` 하위 —
   `Read <project_dir>/memory/MEMORY.md` · `Glob <project_dir>/memory/*.md` 후 각 파일 `Read`.
   메모리 디렉터리가 없거나 비어 있으면 Step 5 를 건너뜀.

## Step 4 — 리포트 작성 (대화로 출력 — 파일 미생성)
두 txt **만 근거로** 정확히 4섹션 리포트를 한국어로 **대화에 직접 출력**.
`<ISO주차>.md` 같은 파일로 저장 금지.

> **형식·작성 규율·예시 = [`references/report-format.md`](references/report-format.md)** (SSOT).
> 템플릿 골격과 채워진 예시가 거기 존재 — 형식 변경은 이 SKILL 사본이 아니라 reference 에서.

실행 요약(상세는 reference):
- 섹션 = `1. 한 일 분포` / `2. 하네스 후보`(반복 2회+ 만, 4컬럼 표: 반복 지시·빈도·박제 위치·해결방안,
  Step 3 의 기존 항목은 "(기존)") / `3. 활동 핫스팟`(명령·디렉터리/파일·도구 비율 + "판독:") /
  `4. 다음 주 제언`(2·3 에서 도출한 액션 3~5개).
- **이모티콘 금지 · 평가어 금지**(잘잘못 매기지 않음) · **데이터에 없으면 생략**(추측 금지).

## Step 5 — 메모리 정리 (검토 → 승인 → 적용)
Step 3 에서 읽은 프로젝트 메모리를 검토해 **삭제(prune)·SSOT 승격(promote)·유지(keep)**
로 분류하고, **사용자 승인 후** 승격(→ 프로젝트 `rules/`·`docs/`)·삭제·`MEMORY.md`
인덱스 갱신 적용. 메모리가 없으면 생략.

> **분류·대상·작성·승인 규율 = [`references/memory-consolidation.md`](references/memory-consolidation.md)** (SSOT).
> rules vs docs 기준, 승격 작성법(형식·언어 확인·간결·중복 금지·point-in-time 검증),
> 승인 게이트가 거기 박제됨 — 규율 변경은 이 SKILL 사본이 아니라 reference 에서.

실행 요약(상세는 reference):
- 각 메모리를 분류: **삭제**(무효/중복/repo 가 이미 기록) · **승격**(지속적 project/
  reference 지식 → 항상-적용 규율은 `rules/`, 참조성은 `docs/`) · **유지**(크로스 프로젝트·
  개인 습관인 user/feedback — 건드리지 않음).
- **제안 표**(`메모리 | 분류 | 대상 SSOT | 근거`)를 대화로 먼저 제시하고 ask the user (structured choice)
  로 승인 획득. **승인 없이 삭제·이관 금지**(부분 승인 지원).
- 승격은 대상 프로젝트의 **기존 문서 형식·언어를 확인**해 핵심만 간결히, **기존 문서 병합
  우선**(중복 금지). 적용 후 원본 메모리 삭제 + `MEMORY.md` 에 유지 항목만 남김.

## Step 6 — 중간 생성물 삭제 (필수)
리포트·메모리 정리가 끝나면 중간 생성물 삭제. 임시 산출물(txt) 잔존 금지.
```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
rm -rf "${ROOT}/.claude/vway-kit/.vdev/insight"
```
