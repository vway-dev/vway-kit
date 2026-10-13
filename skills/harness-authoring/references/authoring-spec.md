# 컴포넌트 작성법 (SSOT: 공식문서)

모델 지식이 아니라 공식문서를 SSOT로 확인:
[plugins-reference](https://code.claude.com/docs/en/plugins-reference.md) ·
[hooks](https://code.claude.com/docs/en/hooks.md) ·
[skills](https://code.claude.com/docs/en/skills.md).

> **커맨드 작성 금지.** harness 산출물에 `.claude/commands/` 미포함
> ([harness-rules.md](../../../rules/harness-rules.md) #9). 아래는 생성 대상 컴포넌트뿐.

- **agent** (`.claude/agents/<name>.md`): frontmatter `name`·`description`(+호출 예시)
  ·`model`(선택) + 단일 책임 시스템 프롬프트.
- **skill** (`.claude/skills/<name>/SKILL.md`): frontmatter `name`·`description`
  (트리거 신호 포함) + 트리거·절차. Progressive Disclosure(상세는 references/).
  **`allowed-tools` 는 권한 사전승인이지 제한이 아님** — 공식문서 "Tools Claude can use
  **without asking permission** during the turn that invokes this skill". 목록에 없는 도구도
  그대로 호출된다(평소 권한 규칙만 적용). 도구를 실제로 **빼는** 필드는 `disallowed-tools` 다.
  이름이 제한처럼 읽혀 오해가 잦음 — "선언이 없어서 못 한다"고 진단하기 전에 공식문서로 확인.
- **rule** (`.claude/rules/<name>.md`): frontmatter 는 **선택적 `paths`(glob 리스트)만** —
  `name`/`description` 필드는 쓰지 않는다(룰은 컴포넌트가 아니라 CLAUDE.md 계열 instructions).
  `paths` 없으면 매 세션 자동 로드(`.claude/CLAUDE.md` 우선순위), 있으면 매칭 파일 작업 시 로드.
  템플릿의 `{{PATHS_FRONTMATTER_OR_REMOVE}}` 는 경로 한정 룰이면 `---`/`paths:`/`---` 블록으로,
  전역 룰이면 빈 문자열로 치환. **필수 룰 5종은 확실성을 위해 CLAUDE.md baseline 본문에 주입**.

- **doc 템플릿** (`docs/**`): `{{ID}}` 는 `wiki_id` 값(wiki 노드 id)이고, 그 파일 자신의 **출력 경로**에서
  [wiki-init](../../wiki-init/SKILL.md) 5단계 규칙으로 파생 — 규칙의 소유자는 거기
  ([harness-rules.md](../../../rules/harness-rules.md) 8-2). 절대 손으로 고르지 않음:
  이 템플릿들은 영역마다 한 번씩 복제되므로, 손으로 고른 슬러그가 복제본들에서 반복되면
  id 가 충돌해 wiki 가 생긴 순간부터 모든 커밋이 막힘. 각 템플릿의 YAML 주석에
  자기 출력 경로에 대한 예시 포함.

## `context: fork` 은 Agent 도구의 `fork` 와 반대말

낱말만 같고 뜻이 반대. Agent 도구의 fork 서브에이전트 타입은 부모 대화를 **복사**하고 모델
지정을 무시하지만, 스킬 frontmatter 의 `context: fork` 는 **새** 컨텍스트로 뜸 —
"It won't have access to your conversation history"
([공식문서](https://code.claude.com/docs/en/skills.md) *Run skills in a subagent*). 그래서
이쪽이 부른 세션의 비용을 낮추는 쪽이고, `model:` 은 그
서브에이전트의 모델이 됨. SKILL.md 본문이 통째로 그 서브에이전트의 프롬프트가 되므로 절차인
스킬에 맞고 안내에 그치는 스킬에는 안 맞음. 부른 쪽 의도는 `$ARGUMENTS` 로만 닿음.

같이 서는 세 필드:

- `allowed-tools` 는 fork 에도 **닿음** — 상류 harness-tier 실측으로 fork 세션 6회 중 5회.
  공식문서가 정하는 것은 "The `agent` field determines the execution environment (model,
  tools, and permissions)"(*Run skills in a subagent* 의 "When this skill runs" 3항, 그 아래
  산문 아님) 뿐이라 열려 있던 자리. 없으면 게이트 스킬이 자기 마커에 프롬프트를 띄움 —
  fork 는 그 프롬프트를 못 받음.
- `agent` 는 빌트인(`Explore`·`Plan`·`general-purpose`)이거나 하네스의 `.claude/agents/`
  (플러그인이면 자동 발견되는 `agents/`)에 실재하는 이름. 없는 이름은 오류가 아니라
  **기본 agent 로 폴백**이라 저자가 고르지 않은 곳에서 돎.
- `background: false` 는 게이트 스킬에 필수. 셋 중 하나씩으로도 충분한 근거 — 마커가 스킬을
  부른 그 턴 안에 떨어져야 `/vdev` 가 읽음, background fork 는 도구셋이 좁은 쪽으로 잘림,
  그쪽 편집은 세션 체크포인트 밖이라 `/rewind` 가 못 닿음.

`agent`·`background` 는 `context: fork` 없이는 불활성이고(`allowed-tools` 는 모든 스킬에서
동작), 어긋나는 방식이 전부 조용함. 강제는 `tests/skill_docs/test_fork_skills.py`.

**공통 규율 — 중복 금지(한 사실 한 곳)**: 한 사실(정의·수치·메커니즘·규율)은
**정확히 한 곳(canonical)** 에만 둠. 다른 절·다른 파일에서 그 사실이 필요하면
restate 하지 말고 canonical 위치를 **링크/참조**한다(파일 내 절 간·파일 간 모두).
룰·문서를 **쓰거나 편집할 때 능동적 de-dup 패스**를 돌려, 같은 정의·문장이 2곳 이상이면
한 곳으로 합치고 나머지는 참조로 바꾼다(예: 게이트 정의는 정의 절 1곳, 나머지는 이름만).
전역 원칙(간결·lean, 룰=구조/문서=행위 분리)은 [SKILL.md](../SKILL.md) 원칙 절 참조.
