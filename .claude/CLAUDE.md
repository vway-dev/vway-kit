# CLAUDE.md

이 repo = **Claude Code 플러그인 자체**(소비자 아님). 사용법은 [README.md](../README.md)·
[USAGE.md](../USAGE.md)(인덱스, 본문은 `docs/usage/`).
컴포넌트 frontmatter 스펙은 모델 지식 아닌 공식 문서로 확인:
[plugins-reference](https://code.claude.com/docs/en/plugins-reference.md) · [hooks](https://code.claude.com/docs/en/hooks.md) · [skills](https://code.claude.com/docs/en/skills.md).

`C:\Work\llm_ai\harness-tier` 는 자매 저장소 — 소비자 설치본도, 옛 이름도 아님. 같은 규율과
게이트 스크립트를 따로 유지하고 **자동 전파는 양방향 다 없음**. evals·스킬검증 하네스는
그쪽이 상류라 개선이 거기서 먼저 나오고, 이쪽으로 옮기는 것은 그때마다 **별개 작업**임 —
대상 집합은 자매 개수를 베끼지 말고 이 저장소 파일에서 재계산(손으로 센 숫자는 틀림).
역방향은 포크 시점의 복사가 전부이고, 이후 역이식은 후보로만 남아 있음. 스킬명이 갈림:
그쪽 `flow`·`flow-init`·`flow-uninstall`·`flow-tiers.yaml` 이 이쪽
`vdev`·`vdev-init`·`vdev-uninstall`·`vdev-tiers.yaml`. 한쪽에만 있는 것도 있으므로(이쪽
`task-import`·`task-sync`·`alm-trace`·`alm-fetch`·`alm-docs`, 그쪽 `harness-deployments`) 이식 전에
두 `skills/` 를 대조할 것.

## Commands

`uv sync` · `uv run pytest` · `uv run ruff check` 는 적지 않음 — 추론되는 것이 아니라
비용이 붙는 것만 여기 둠.

```bash
uv run python -m evals.run --dry-run --all   # 세션 수 + 벽시계, 모델 호출 없음
uv run python -m evals.run                   # description 이 움직인 스킬만 다시 잼
uv run python -m evals.run --all             # 전량 497세션
uv run pre-commit run --all-files            # 훅이 설치돼 있어도 전량은 손으로
```

**먼저 `--dry-run`** — 헤드리스 세션 수백 개이고 5시간 창을 소진함. 떨어진 수치는 그 스킬을
한 번 더 재서 확인하므로 dry-run 이 광고한 세션 수가 그만큼 늘어남. 러너가 찍는 벽시계는
**상한**임 — 근거와 실측은 `evals/runner/config.py` 의 `SESSION_WALL_CLOCK_S`. 재는 동안 러너가 추적 파일
`evals/scores.json` 을 증분으로 쓰므로 **그 사이 커밋 금지**(pre-commit 의 stash 가 그 쓰기를
덮어씀). 조건은 `MODEL` 핀과 per-skill `reps` 가 정함.

`*.sh` 수정 시 ShellCheck 필수 — 훅 런타임이 Windows 라 버그가 FAIL-OPEN 으로 숨음.
**WSL 에서 돌릴 것**: 셸·PATH·shebang·파일 모드·경로 구분자는 거기서만 진짜로 확인됨.

개발 호스트는 Windows, CI 는 ubuntu — `core.autocrlf=true` 이고 `.gitattributes` 는 `*.sh`(LF)·
`*.cmd`(CRLF) 만 고정함. 그 밖의 추적 텍스트 파일은 워킹트리에서 CRLF, blob 에서 LF.
**추적 파일의 날바이트를 다이제스트하지 말 것** — 로컬 pytest 는 초록인데 CI 만 붉고 그 차이가
조용함. 새 해시를 만들 때마다 CRLF 를 접음(`evals/runner/baseline.py` 의 `description_sha` 가
그 보정을 가짐). `/vdev-init` 은 바이트 그대로 복사하므로 `.sh` 는 호스트에 LF 로 떨어지고,
그 뒤 호스트 자신의 체크아웃은 호스트의 `core.autocrlf` 를 따름.

## Conventions

- **문서·주석 문체 SSOT = [rules/doc-style.md](../rules/doc-style.md)** — 개조식·이력 금지·한 사실 한 곳.
  기계가 보는 절반은 `scripts/doc_style_check.py --lint`(게이트는 경고, 판정은 CI), 재작성 손실은 `doc_invariants.py`.
  이 저장소 자신의 검사 범위는 `.md`·`.py`·`.sh` — 주석·독스트링도 산문.
  그 범위의 SSOT 는 `.github/workflows/doc-style.yml` 의 `env` 두 값(테스트가 같은 값을 읽음).
  커밋 본문([commit-discipline](../rules/commit-discipline.md))·생성 하네스 산출물([harness-rules 5-2](../rules/harness-rules.md))도 같은 규율.
- 파일별 역할·근거는 각 소스 헤더 독스트링이 SSOT.
- **테스트는 500줄을 넘기면 분류 폴더로 쪼갬** — `tests/<주제>/`(`__init__.py` + 분류별 `test_*.py`
  + 공용 헬퍼 `_helpers.py`). 폴더가 있어야 파일명이 짧아도 안 겹치고, 실패 이름만으로 어느
  규율이 깨졌는지 가려짐. 파일마다 그 분류가 **무엇을 재는지** 헤더 독스트링에 적음.
  폴더 전체에 걸려야 하는 픽스처(모델 금지 가드 등)는 임포트가 아니라 `conftest.py` 로 —
  임포트를 빠뜨린 새 파일이 조용히 가드 밖으로 나감.
- **셸·러너를 띄우는 테스트는 `tests/_proc.py::run_bounded`** — 파이프로
  받으면 손자가 쥔 출력 핸들 때문에 Windows 에서 `timeout` 이 안 들어 스위트
  전체가 멈춤(근거·실측은 그 독스트링). 강제하는 폴더 목록은
  `tests/test_proc.py` 의 `_GUARDED`.

## Layout

`agents/`·`hooks/`·`skills/` 는 매니페스트에 경로 미선언 → 기본 위치 자동 발견(컴포넌트 추가 = 파일 추가).

```text
.claude-plugin/  플러그인 매니페스트 · 마켓플레이스 자기 노출(source 는 `plugin` 브랜치 커밋 불변 핀)
.codex-plugin/   Codex 매니페스트(훅 없음 — OpenAI 디렉터리가 훅 든 패키지를 거부) · .agents/plugins/ 는 Codex 마켓플레이스
assets/          목록 아이콘(두 매니페스트가 가리킴)
agents/          하네스 리서치·코드 분석·비판 서브에이전트
hooks/           SessionStart 룰 주입·구버전 빌드 경고 · PostToolUse 편집 시 review/doc-sync 증거 무효화 · Notification 알림·권한 승인 대기 시각 기록(`worklog.py record-wait`) — 등록은 claude/hooks.json(Codex 는 hooks/hooks.json 을 스스로 찾으므로 그 자리는 비움). Codex 는 같은 두 스크립트를 `/vdev-init` 이 호스트에 복사해 `.codex/hooks.json` 에 등록(codex/run-hook.cmd 는 그 Windows 래퍼)
skills/          /슬래시 스킬(스킬명 = 폴더명)
rules/           매 세션 주입되는 둘: 티어·게이트 용어집 SSOT(risk-tiers, 전문) ·
                 문체 SSOT(doc-style, 훅의 쓰기 시점 요약만). 주입 안 되는 다섯: 커밋 메시지(commit-discipline) ·
                 승격(promotion) · 머지 전략(merge-strategy) · 게이트 동작(gate-mechanics) ·
                 하네스 생성 규율 SSOT(harness-rules)
scripts/         게이트·도구 스크립트 — 호스트로 복사되는 SOURCE · harness/<name>/ 는 하네스별 설치자
github/          호스트용 GitHub Actions 템플릿(/vdev-init 이 vdev-config 로 렌더) — e2e 는
                 토큰 없는 그대로 복사, 이 repo 엔 브라우저 프런트가 없어 자기 인스턴스 없음
.github/         vway-kit 자체 CI · marketplace sha 핀·`plugin` 브랜치 생성 스크립트
.claude/         편집 대상에 따라 자동 로드되는 규율 — skills/** 에는 작성 룰,
                 그 밖의 파일에는 그것이 구현하는 rules/ 스펙(specs.md 의 paths·표)
templates/       ALM 템플릿 SOURCE — handoff/(요약 md, provider 공용) · alm/(계층 항목 본문)
                 호스트 사본은 `.claude/vway-kit/templates/`(같은 rel, 다른 루트)
tests/           컴포넌트별 pytest — 500줄 넘는 것은 분류 폴더(vdev_init/·gate_check/·eval_harness/·wiki/·vway_paths/·skill_docs/·deploy/·harness/·handoff/·alm_layers/·alm_plan_check/·srs_check/·md_anchors/·alm_docs/·doc_style/·invalidate_gate_markers/·harnesses/·inject_risk_tiers/·worklog/)
evals/           스킬 호출률 측정(모델 호출, 사람이 실행) + baseline 검사(모델 없음) · runner/ 가 러너 본체(run.py 는 CLI) · 채점 못 한 세션 기록은 .runs/(gitignored) · codex_probe/ 는 Codex 훅 재실측 도구
docs/            소비자 사용 설명서(usage/) · 마켓 자동 업데이트 진단(plugins/) · superpowers/ 설계 스펙·플랜(gitignored, 로컬 전용)
```

## Architecture

- **이중 경로**: 플러그인은 호스트 밖 캐시에 설치됨. `${CLAUDE_PLUGIN_ROOT}` = 읽기(템플릿·정책), `${CLAUDE_PROJECT_DIR}` = 쓰기. 플러그인 디렉터리에 쓰기 금지.
- **호스트 쓰기는 `.claude/vway-kit/` 아래**: `scripts/`(게이트 사본, 플러그인 소유) · `config/`(vdev-tiers.yaml 만 플러그인 소유, 나머지 호스트 소유) · `.vdev/`(게이트 증거, gitignored) · `templates/`(호스트가 고치는 양식, 호스트 소유).
  템플릿만 전파가 **선언 기반**(scripts/ 는 늘 덮고, templates/ 는 config 가 선언한 rel 만 한 번 시드) — 무엇을 내려주고 무엇을 두고 오는지는 [host-templates.md](../skills/vdev-init/references/host-templates.md).
  예외는 외부 도구가 위치를 강제하는 `.gitignore`·`.pre-commit-config.yaml`·`.claude/settings.json`·`.github/workflows/`, Codex 를 켠 호스트의 `.codex/hooks.json`·루트 `AGENTS.md` 관리 블록 뿐.
  **MCP 서버는 vway-kit 이 등록하지 않음** — 저장소 `.mcp.json`(project 스코프)은 팀 공유라 사람마다 다른 PAT 를 못 담고 git 에 실리면 토큰이 샘.
  사람이 `claude mcp add`(local 스코프 = `~/.claude.json` 의 프로젝트 경로 밑)로 넣고, `/vdev-init` 은 그 상태를 **읽어** 판정해 어긋난 것의 `remove`+`add` 명령만 찍음(PAT 는 묻지 않음).
- **전파 단방향**: `scripts/`·`vdev-tiers.yaml`(SOURCE) → 캐시 → 호스트 사본. 수정은 SOURCE 만. 동기화 = `/vdev-init` 재실행, 정리 = `/vdev-uninstall`.
- **정책 vs 환경값**: `vdev-tiers.yaml`(tier→gates, 불변) vs `vdev-config.yaml`(브랜치·modules·alm·deploy, 호스트가 편집).
  규율 자체의 SSOT 는 [rules/risk-tiers.md](../rules/risk-tiers.md) — 티어 분류·게이트 용어집·Hard gates. 커밋 메시지 규율은 [rules/commit-discipline.md](../rules/commit-discipline.md)(`/commit` 이 읽음). 머지 전략은 [rules/merge-strategy.md](../rules/merge-strategy.md), 게이트 동작 상세는 [rules/gate-mechanics.md](../rules/gate-mechanics.md)(둘 다 주입 안 됨). 어긋나면 다른 쪽을 맞춤.
  승격에서만 읽히는 절(승격 이벤트 정의·승격 절차·bump 선택·머지 커밋 메시지·백머지·검증 회차)은 [rules/promotion.md](../rules/promotion.md) 로 뺐음 — 주입되는 것은 risk-tiers·doc-style 둘뿐이라 일상 요청이 승격 바이트를 지지 않음.
- **커밋 게이트는 호스트 `settings.json` 에 등록**(플러그인 hooks.json 아님 — deny 신뢰성·`${CLAUDE_PLUGIN_ROOT}` 미해석).
  **Codex**: `vdev-config.harnesses`(부재 = `[claude]`)가 `codex` 를 적으면 게이트와 SessionStart·PostToolUse 세션 훅을 `.codex/hooks.json` 에도 등록(세션 훅은 `VWAY_DIR` 아래 `hooks/`·`rules/` 사본을 돌림) — 등록은 `scripts/harness/<name>/`, 두 하네스의 차이는 [codex.md](../docs/usage/codex.md), 근거는 `scripts/harness/codex/` 독스트링.
  **이 repo 는 `/vdev-init` 자기 적용 안 함**(순환) → 자기 커밋은 tier 게이트 미강제. 자기 규율 = pre-commit + CI + 수동 리뷰(CI 도 브랜치 보호 없인 merge 를 못 막음 — 저장소 설정, 미확인).
- **검증 3레이어**: ① pre-commit(위생·gitlint) ② vdev 게이트 `precommit-runner.sh` — 에이전트 세션(Claude Code·Codex)의 `git commit`·`git merge`(브랜치를 대는 `git pull` 포함)에만(PreToolUse). 미분류 차단 + tier gates(`precommit`·`security-scan`) + `--merge-check`.
  `wiki`·`doc-style` 검증은 이 프로세스 내부 단계(각각 `vdev-config.wiki`·`doc_style` 켜졌을 때만, 읽기 전용). 모듈 명령 채널로 돌리면 내부 오류가 모든 커밋을 막으므로 금지.
  둘의 경고는 **JSON 하나**로 합쳐 나감(객체 둘이면 러너가 못 읽음). `doc-style` 은 차단하지 않음 — 판정은 트리 전체를 보는 CI.
  그래프 생성 주체는 [gate-mechanics](../rules/gate-mechanics.md) 가 SSOT, 노드 집합은 git 인덱스, 훅은 워킹트리를 읽음 → `graph.yaml` 을 문서와 함께 스테이징. ③ CI — /vdev-init 이 렌더(계약·유닛·문체·e2e, `docs/srs/` 가 있으면 동의를 받아 `srs-verify.yml` 도), `wiki-verify.yml` 만 /wiki-init 이 그래프 `--verify` 통과 뒤 동의를 받아 렌더(`--render-wiki-verify`). 전자는 터미널 커밋 사각을 덮고, 후자는 레이어 2 가 경고만 하므로 **유일한 판정자** — 그래서 `doc_style.enable: false` 는 가벼운 검사가 아니라 검사 없음이고, 그 플래그가 렌더와 실행 양쪽을 켬.
- **`review`·`doc-sync` 마커는 자기를 쓴 커밋보다 오래 삶** → `hooks/invalidate-gate-markers.sh`(PostToolUse)가 편집마다 **둘 다** 지움. 통과는 고정점(둘 다 기록·이후 편집 없음)이라 Dev 는 doc-sync 를 먼저, 도메인 리뷰를 마지막에.
  대상은 편집된 파일의 repo 루트(걸음을 가두는 경계) + `CLAUDE_PROJECT_DIR` — 후자는 두 git 디렉터리가 **둘 다 존재하고 서로 다름**이 파일시스템으로 증명될 때만 뺌(게이트가 worktree 이름을 못 대면 프로젝트 디렉터리를 읽으므로 — Invariant 7). 판정 못 하는 경우는 전부 지우고, 훅 자체 실패는 남김(FAIL-OPEN). `bump`·`security` 는 깨끗한 트리의 승격 결정이라 대상 아님.
  Codex 갈래(`--harness codex`)는 `CLAUDE_PROJECT_DIR` 자리에 페이로드 `cwd` 의 루트를 씀 — 같은 규칙으로 합집합, 경로를 못 대면 그 루트만.
  훅은 플러그인이 등록해 버전만으로 켜지므로 호스트가 `gate_evidence.invalidate_on_edit: false` 로 끌 수 있음 — 읽는 규칙·대가는 [gate-mechanics](../rules/gate-mechanics.md) SSOT.
- **리뷰 에이전트에게 리터럴 `VERDICT: PASS` / `VERDICT: FAIL` 한 줄을 요구할 것** — 애매한
  보고는 통과로 읽히고, 그러면 마커가 **일어나지 않은 리뷰**를 기록함. 체크리스트도 닫아서
  발행함: 열린 감사는 끝나지 않고, 끝나지 않은 리뷰는 마커를 못 벌음.
- **`rules/` 는 자동로드 안 됨** → `hooks/inject-risk-tiers.sh` 가 SessionStart 에 risk-tiers 전문·doc-style 요약 주입.
  Claude Code 는 10,000자를 넘는 훅 컨텍스트를 2,000자 미리보기로 바꿔 룰이 조용히 사라짐 — 상한은
  `tests/inject_risk_tiers/` 가 잼. Dev 오버레이·도메인 리뷰 절차는 주입 밖 [dev-overlays](../skills/vdev/references/dev-overlays.md).
  이전 `/vdev-init` 이 남긴 `.claude/rules/vway-kit/` 는 재동기화가 지움(매 세션 통째로 로드되므로). 같은 훅이 소스 repo 의 plugin.json version 이 설치 캐시와 다르면 경고(개발자 세션은 캐시를 실행). FAIL-OPEN, 소비자 무음.
- **버전·릴리스**: plugin.json `version` 이 재설치 게이팅(sha 변경만으론 전파 X). `release.yml`(semantic-release)이 main/stage 의 feat/fix 를 파싱해 bump·tag, main 은 런타임 파일만 고른 `plugin` 브랜치 커밋을 만들고 marketplace `source.sha` 를 그것으로 불변 핀.
  런타임 파일을 새로 두면 `.github/scripts/plugin_dist.py` 의 `INCLUDE` 에도 — 빠진 파일은 소비자 설치에서 조용히 사라짐.
  그래서 소비자에 닿는 `.md`(rules/skills) 변경은 `docs` 아닌 `feat`/`fix`. 브랜치 `feature/*`→dev→stage→main. 릴리스(`release.yml` = 버전·태그)와 배포(`deploy.yml`→`deploy-<target>.yml`, vdev-config.deploy 가 SSOT)는 분리.
- **ALM 은 provider 추상화**: `vdev-config.alm.provider` 를 요청 텍스트가 덮어씀 — 해석 순서 SSOT 는 [vdev](../skills/vdev/SKILL.md) Phase 0.
  **task-id 모양만으론 아무 ALM 도 안 침.** 마커 `.vdev/alm` 은 링크당 한 줄(형식 SSOT: [task-import](../skills/task-import/SKILL.md)).
  handoff `field` 는 문자열(Teamer 어휘) 또는 provider 별 dict — `handoff_resolve.py --provider` 가 평탄화.
  Recoble 은 스페이스별 MCP 서버(local 스코프 PAT 헤더)이고 **도구 접두는 고정 아님** — 해석 절차 SSOT 는
  [recoble-server.md](../skills/task-import/references/recoble-server.md). 그 문서가 이름 조립을 금하므로 서버 이름 철자는 여기 안 적음.
  항목 상태 전이 판정 SSOT 는 [recoble-status.md](../skills/task-import/references/recoble-status.md) — 근거는 보드
  `list_workboard_statuses` 플래그이지 config 키 이름이 아님(키를 안 쓰는 호스트에서 가드가 통째로 빠짐).
  계층 추적은 `alm.recoble.spaces.*.layers` 선언으로 켜짐(미선언 시 task-import 경로) — 그중 `defect: true` 가
  **결함 진입**을, `run: true` 가 **검증 회차**를, `feature_design: true` 가 **기능별 설계 항목**(전파 밖)을 켬.
  선언 자체의 판정은 `alm_layers.py`, 셋업이 `[ALM 계층 점검]` 으로
  미리 보임. 계층·링크·모델 선택은 [alm-trace](../skills/alm-trace/SKILL.md) 가 SSOT.
  본문 독자·자기완결 규칙 SSOT 는 [item-body](../skills/task-import/references/item-body.md).
  상태 전파 SSOT 는 [recoble-propagation.md](../skills/task-sync/references/recoble-propagation.md) — 순회는
  `alm-fetch` 에 위임하고 `alm_plan_check.py` 가 규칙을 확인함, 종료 코드 처리는 [task-sync](../skills/task-sync/SKILL.md) R6.
  **ALM 실패는 게이트 아님** — 해당 단계만 건너뜀.
  `docs/srs` 의 FR·C 와 `requirement` 계층의 대조는 [alm-docs](../skills/alm-docs/SKILL.md) —
  매칭 키는 repo 가 짐(앵커 줄 끝의 `<!-- alm: <스페이스>/<id> -->`), 판정은 `alm_docs.py` 가 쥔
  결정적 코드이고 모델은 보드 열거만 함. 옮기는 것은 사람이 고른 한 방향뿐이고 게이트 아님.

## Invariants (깨면 게이트가 조용히 무력화됨)

`scripts/*`·`hooks/*.sh` 수정 시 보존. 근거는 `precommit-runner.sh`·`_vway_paths` 주석, 강제는 `tests/gate_check/`(실제 셸 구동)·`tests/skill_docs/`(출하 지시 문서 전체).

1. **FAIL-OPEN, 단 셋은 fail-CLOSED** — 내부 오류는 통과. 차단: ① `python3`≥3.8·`PyYAML` 부재(러너; python3 없이도 raw stdin grep 으로 커밋 탐지, `pull` 낱말만 든 명령과 `$'` 없이 `$` 옆 백슬래시만으로 띄운 명령은 제외 — 걸면 그 호스트의 `git pull`·`printf "$x\n"` 이 전부 막힘) ② 정책·설정이 **파싱 성공**하는데 `tier` 마커 없는 미분류 커밋(기준은 파일 존재가 아니라 파싱 성공 — 깨지면 fail-open) ③ `merge_strategy` 규칙의 필수 플래그 누락·금지 플래그 — `git merge` 와, 브랜치를 대는 `git pull`(rebase 해도 머지 플래그 없음으로 판정 대상; 근거가 명령어 문자열뿐이라 내부 오류 여지 없음, 저장소 상태는 경고 경로만).
   규칙·키 부재·detached HEAD·다른 worktree 는 fail-open. superpowers 는 셸에서 감지 불가 → `/vdev`·`/vdev-init` 가드.
2. **Windows 인코딩** — 훅 Python 은 cp949. 한글 `print()`·기본 `open()`·**stdin 읽기**가 인코딩 오류로 FAIL-OPEN 되어 막아야 할 커밋을 통과시킴. `PYTHONUTF8=1`·`force_utf8_io()`·`encoding="utf-8"` 유지 — 러너가 자식에 주는 `PYTHONUTF8=1` **하나로는 부족**하므로 방어는 `force_utf8_io` 에 둠. 축별 조건과 실측은 그 독스트링이 SSOT, 강제는 `tests/gate_check/test_non_utf8_host.py`.
   `force_utf8_io()` 는 자식 출력 디코딩을 못 바꿈 → `subprocess` 의 `text=True` 는 호출마다
   `encoding=`(루트를 정하는 경로는 `_GIT_PATH_ENCODING`), 스킬의 인라인 `python3 -c` 는 `-X utf8`.
3. **차단 = exit 2 + stderr 사유**(JSON `permissionDecision` 은 보조).
4. **settings.json 게이트 훅에 `if` 필드 금지** — 빌드별로 발화가 막힘. 필터는 러너의 stdin 사전 필터로.
5. **`/vdev-init` 멱등** — settings.json 훅·pre-commit id·.gitignore 라인 match-then-skip.
6. **Teamer 자격증명은 keyring** — 평문 파일·모델 컨텍스트·트랜스크립트에 id/pw/token 노출 금지(에러도 redact). `teamer_api.py`(stdlib+keyring)가 인증·검색·GET·PUT 을 프로세스 내부에서 하고 최소 JSON 만 출력(PUT 은 urllib multipart UTF-8, curl/Node 아님).
   번호는 `vdev-config.alm.teamer` 에서 인자로(하드코딩 폴백 금지). 세팅은 터미널 `teamer_api.py setup` 만(AskUserQuestion 금지).
7. **호출 판정의 권위는 `vdev_gate_check.py --classify` 하나** — 러너 stdin 필터는 띄울지만 정하므로 진짜 문법보다 **좁아질 수 없게** 거칠게(`*git*` + `commit|merge` 낱말, 인용을 지운 사본도 함께 봄). 과다 매칭 비용은 spawn 하나, 과소 매칭 비용은 게이트 전체 — 길이 상한을 넘는 입력은 필터를 건너뛰고 그냥 띄움(사본 만들기가 따옴표 수 × 길이라 2차). 판정이 아예 없으면(`ok=1` 부재) 러너가 스스로 게이팅.
   아래는 고칠 때 **보존할 규칙**만 — 근거·실측치는 `_vway_paths`·`vdev_gate_check`·`vdev_init_setup`·`precommit-runner.sh` 주석이 SSOT.
   - **인용의 권위도 하나** — 인용·이스케이프·주석·heredoc 은 `mask_literals` 에서만 읽고, 낱말은 `operand_end` 가 끝냄.
   - **인용된 텍스트는 무언가 그것을 실행하기 전까지만 데이터** — 치환(`$( )`·백틱)·인터프리터의 `-c` 인자·명령 자리의 인용 span·확장이 켜진 heredoc 본문은 리터럴이 아니라 **명령**으로 스캔(`_expanding`·`_code_span`·`_executed_span`).
   - **낱말 안의 인용은 데이터가 아니라 그 낱말의 철자** — `git 'commit'`·`gi't' commit` 도 진짜 커밋. 같은 문법을 낱말 단위로 한 번 더 봄(`_spelled_with_quotes`), 그 문법은 **선두 고정**.
     **인용을 지운** 판도 읽음(`_unquoted_readings` — 다 지우는 판 하나 + bash 그대로 겹마다 벗긴 판, 큰따옴표 안 백슬래시는 남김) — `$'commit'`·낱말 한가운데의 줄이음은 낱말 단위로 못 이음. 셸 분할 판독기(`operand_words` 등)는 `requote_ansi_c` 를 거침. 판독기인 `git` 자신은 명령 자리마다(마스크로 판정, 인용 안 공백·탭은 낱말 안 글자 — 개행은 줄이음일 수 있어 그대로), 그물은 원소 전체.
     러너 필터의 인용 지운 사본은 같은 것(줄이음·따옴표·`$`·백슬래시)을 지우고 `$'` 이나 `$` 옆 백슬래시가 있으면 무조건 띄워 문법보다 거칠게 남음 — 강제는 `tests/skill_docs/test_invocations.py` 가 문법 corpus 넷을 필터에 통과시킴.
   - **명령 자리 판정 둘은 같은 답** — `at_command_start`(정밀한 읽기)와 `_COMMAND_START`(그물). 한쪽만 넓히면 둘이 같은 물음에 반대로 답함.
   - **둘째 읽기는 명령 리스트 원소 단위**(`_list_elements`) — **면제가 목록이지 게이팅이 목록이 아님**. 면제는 파이프라인 **단계마다** 묻고, 이름을 못 댄 자리가 하나라도 있는 단계는 못 받음. 원소 경계와 면제 취소 조건은 `_list_elements`·`_reads_only`·`_runs_by_flag` 주석이 SSOT.
   - **판을 가르는 것은 면제이지 인터프리터 이름이 아님** — 면제를 못 받은 원소는 인용 텍스트도 heredoc 본문도 스크립트로 다시 읽힘. `_RUNS_TEXT` 가 정하는 것은 탐지가 아니라 **마스크**: 이름이 빠지면 merge 전략 플래그와 `-C` 판정이 fail-open 으로 떨어짐(Invariant 1 이 금지한 셋 중 하나). 오차단 비용과 `xargs`·`parallel` 예외는 `is_invocation` 주석.
   - **면제는 명령 자리마다 프로그램을 읽어 정함**(`_program_spans` 걸음 **하나** — 둘이면 서로 다른 답을 냄) — 이름을 못 댄 자리는 **빼지 않고 `None`**, 대입·리다이렉션 뒤도 `None`, `!` 만 예외. 이름이 면제를 얻는 조건 = 자기 인자에 적힌 명령도 **자기 환경이 지목하는 명령**도 돌릴 방법이 없을 것. 치환은 **자리를 묻지 않고** 원소 어디에 있든 면제를 취소. 갈래별 근거는 그 함수 독스트링.
   - **성능 계약: 훅 타임아웃 = 조용히 건너뛴 게이트** — 앵커이면서 동시에 별표의 먹이인 글자(마스크 채움 문자 NUL 포함)를 별표 앞에 두지 않고, 정규식 갈래는 전부 리터럴로, 낱말은 스트림 seek + 개수 상한으로 읽고, 명령 자리마다 `search` 를 새로 걸지 않음. `search` 는 첫 매치에서 반환하므로 시간 가드가 **루프**도 재야 함(`tests/vway_paths/test_linearity.py`·`test_quoted_spelling.py`·`test_quote_removal.py`). 패턴별 기법과 실측치는 각 정규식 주석.
   - **merge 전략은 이름으로 하는 모든 머지를 판정**(`_judged` — 소스를 지목하는 `git merge`·`git pull`) — 인용 제거 뒤 철자까지 함께 읽고, 플래그는 git 처럼 읽음(축약, 반대 옵션은 나중 것, 명령줄 `-c merge.ff`·`pull.ff`). 명령줄 `-c branch.<target>.mergeoptions` 도 셈. rebase 하는 pull 도 소스를 들이므로 판정(머지 플래그 없음으로). target 은 머지마다 **그 머지 앞**의 switch, switch 도 디렉터리도 셸 이동도 없으면 훅 cwd 의 트리 브랜치(재지정 아님 — 정책은 root 것, 막을 수 있음). 명령 자리 밖 호출은 다시 파싱되거나(`eval`·`watch`·`ssh`) 면제 못 받은 단계에서만 셈(`_BuriedRuns`), 다시 파싱되는 피연산자는 그 파싱이 세운 구분자에서 끝남(`call_operands`). git config 는 명령줄이 정하지 않은 pull 의 rebase 여부만 읽고, 그것도 플래그 없는 읽기를 **더할** 뿐(둘 중 하나라도 어기면 막음). 판정에서 빠지는 fail-open 다섯은 [gate-mechanics](../rules/gate-mechanics.md#merge-전략-판정의-fail-open) 가 SSOT. 판정이 예외로 끝나거나 rebase 선행이 안 보이는 통과는 `systemMessage` 통지 — 러너가 쥐었다가 커밋 단계 통지와 **JSON 하나**로 냄. 읽은 호출이 bash 가 실제로 돌린 것과 같은지는 `tests/gate_check/test_merge_bash_agreement.py` 오라클이 잼(POSIX 전용, 알고 남긴 틈은 strict xfail).
   - worktree 재지정은 커밋 경로 전용·FAIL-OPEN(불확실하면 `CLAUDE_PROJECT_DIR` 유지), merge 경로는 재지정 안 함. 커밋 하나가 다른 저장소(`--git-common-dir` 다름)에서 돈다는 것이 명령 모양으로 증명되면 커밋으로 안 읽음(`_commits_in_another_repo`) — 증명 못 하면 게이팅.
     재지정은 **새로 차단하면 안 됨**. 선언된 예외 하나: **커밋 트리를 한 곳으로 못 박는 명령은 그래도 게이팅**함 —
     어느 트리로 풀리든 그 트리가 깨끗하다는 사실이 아무것도 말해 주지 않기 때문. 해당하는 경우와 값 정규화는
     `commit_tree_unresolved`·`_cd_hop_before_bare_commit`·`_norm_dir` 독스트링이 SSOT — 디렉터리 판독기가 못 보는 커밋
     (인용·백슬래시·ANSI-C 이스케이프가 철자한 낱말·인터프리터에 건넨 스크립트 안, `_net_only_commit`)도 그 집합에 듦. 불확실 집합은 작게 유지.
     계약은 `--classify` 의 `unresolved=1` 한 줄이고, 러너는 그 줄이 서면 **깨끗한 트리 조기 종료를 건너뜀** —
     안 건너뛰면 진짜 커밋에서 모든 게이트가 조용히 빠짐. 호스트 복사는 `vdev_gate_check.py` 를 러너보다
     먼저(`COPY_FILES`). 게이트 훅은 settings.json 에서 **Bash 에 발화하는 자기 엔트리**를 가짐(`register_gate`).
     **`/vdev-init` 의 완료 문구·exit 0 은 호스트에 도는 게이트가 있을 때만** — 근거는 `vdev_init_setup` 독스트링.
   - **역방향 의무**: 스킬·룰이 발행하는 `git commit`·`git merge`·`git pull` 은 플래그를 리터럴로, 공백 든 인자는 따옴표로 — 훅은 셸 확장 *전* 텍스트를 받음(강제는 `tests/skill_docs/test_issued_commands.py`).
   - 의도된 잔여 다섯: 프로그램이 아닌 낱말(`eval`·`echo` 등) 뒤에 머지 경로 호출이 늘어선 명령은 호출마다 명령 끝까지 읽어 길이의 제곱(끊으면 치환 출력이 뒤 호출을 `-m` 값으로 삼킨 머지가 플래그를 잃음 — 타임아웃은 수백 KB 명령에서나) · `_EXEMPT` 밖 프로그램에 커밋처럼 생긴 텍스트를 건네면(heredoc 본문 포함) 아무것도 안 돌아도 게이팅(안전한 방향) · `$( )` 중첩이 파이썬 재귀 한계를 넘으면 러너 백스톱이 게이팅 · python3·PyYAML 없는 호스트에선 `commit`·`merge` 낱말이나 `$'` 만 담은 명령이 의존성 fail-CLOSED · 실행 플래그의 값이 `=` 뒤에 붙은 `rg --pre=git` 은 낱말 그물이 못 봄(`=` 는 토큰 경계가 아님 — 경계로 넣으면 대입 값이 전부 프로그램으로 읽힘).
