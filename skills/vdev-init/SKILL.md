---
name: vdev-init
description: Idempotent setup & update wizard for a host repo — run after installing vway-kit, or re-run any time to re-sync the host scripts and reconfigure
disable-model-invocation: true
---

# Vdev-Init — vway-kit Setup Wizard

Run after installing the vway-kit plugin in a host repository — or re-run any time
to re-sync the host scripts and optionally reconfigure. It writes the host-side
config and wiring that the plugin's runtime pieces (`/vdev`, `vdev_gate_check.py`,
`precommit-runner.sh`, `teams_alert.py`) depend on.

**Split of labor**: the deterministic, error-prone wiring (file copies, idempotent
`settings.json` / pre-commit / `.gitignore` merges, auto-update auth detection) is done by
**`scripts/vdev_init_setup.py`** so it is repeatable and unit-tested. This command
(Claude) only does the **interactive / judgment** parts — gathering config,
collecting webhook URLs, writing the language-matched CLAUDE.md block — and
orchestrates by calling the scripts and relaying their reports.

**Idempotent**: safe to re-run. The setup script skips entries that already exist
(never double-appends); the interactive steps confirm before overwriting.

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## Path conventions

- **Read from the plugin** (templates/scripts): `${CLAUDE_PLUGIN_ROOT}/...` — read-only.
- **Write to the host repo** (config/wiring): `${CLAUDE_PROJECT_DIR}/...` — every write
  this skill makes lands under here.
- **All host-side vway-kit artifacts live under `${CLAUDE_PROJECT_DIR}/.claude/vway-kit/`**,
  classified by purpose (no root scatter):
  - `scripts/` — copied gate scripts (plugin-owned, git-tracked)
  - `config/` — `vdev-config.yaml`, `teams-webhooks.json`, `.teams-webhooks.local.json`
    (host-owned) + `vdev-tiers.yaml` (tier→gates policy — plugin-owned, do not edit)
  - `templates/` — the host's own ALM/handoff forms, seeded from what the config declares (host-owned, git-tracked — [host-templates.md](references/host-templates.md))
  - `.vdev/` — gate evidence (gitignored)

  The only host files that stay elsewhere are the ones external tools pin:
  `.gitignore` (git), `.pre-commit-config.yaml` (pre-commit), `.claude/settings.json`
  (Claude Code).
- The commit gate runs as a **host** `settings.json` hook, where
  `${CLAUDE_PLUGIN_ROOT}` may not resolve — so the setup script **copies** the gate
  scripts into `${CLAUDE_PROJECT_DIR}/.claude/vway-kit/scripts/` and references them by
  host path.

```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
PLUGIN="${CLAUDE_PLUGIN_ROOT}"
```
각 Bash 호출은 새 셸임 — 뒤의 블록마다 이 대입을 다시 열지 않으면 거기서 이 변수들이 빔.

## Execution

### Execution modes — first run vs re-run

`/vdev-init` is the single idempotent entry point. Branch on whether the host
config already exists (`${ROOT}/.claude/vway-kit/config/vdev-config.yaml`):

- **First run (config absent)** — run Step 0 → Step 4 in order, gathering
  everything (the full wizard below).
- **Re-run (config present)** — the goal is *update without clobbering*:
  1. **Codex 세션 (always, non-interactive):** 이 세션 자체가 Codex CLI 에서 돌고 config 의
     `harnesses` 목록에 `codex` 가 없으면 **Edit** 로 더함 — 목록이면 끝에 덧붙이고, 키가
     없거나 주석뿐이면 `harnesses: [claude, codex]` 를 씀 — 그리고 게이트가 Codex 에도
     심긴다고 사용자에게 알림. 아무것도 빼지 않음. 목록이 아닌 `harnesses` 값은 그대로 둠:
     재동기화가 그것을 보고하고, 게이트가 Codex 에 닿기 전에 고치라고 사용자에게 전함.
  2. **Re-sync (always, non-interactive):** run Step 2's
     `vdev_init_setup.py`. This re-copies the gate scripts/policy, repairs
     the `settings.json` gate path, registers every harness `harnesses` names,
     migrates any legacy layout, and prints
     the `[config 슬롯 점검]` + `[폐기 필드 점검]` + `[checks 타이밍 점검]` +
     `[ALM 계층 점검]` blocks. This must happen before any prompt, so a user who
     only wants fresh scripts is never blocked by questions.
  3. **Slot backfill (if any):** if the report lists missing slots, do Step
     2.5 (offer to insert them verbatim).
  4. **Legacy 폐기 필드 정리 (if flagged):** if Step 2's `[폐기 필드 점검]` block
     flags a lingering global `test.command`, run Step 2.6's **기존
     `test.command` 처리** — even on a re-run (migration is *by definition* a
     re-run, so this must not be gated behind first-run-only). Verify module
     coverage → migrate first if absent → then remove. If the same block flags a
     lingering **top-level `teamer:`**, migrate it into `alm.teamer` per
     [`references/recoble-spaces.md`](references/recoble-spaces.md) §4 — **before**
     accepting the `alm` slot backfill (Step 2.5), which would otherwise overwrite
     the host's numbers with the example's.
  5. **Legacy release 워크플로 마이그레이션 (if flagged):** if Step 2's
     `[릴리스 워크플로 마이그레이션]` block flags a legacy `release.yml` — it uses
     `secrets.GITHUB_TOKEN` with no `RELEASE_TOKEN`, it takes the bump level from a
     `workflow_dispatch` `level` input and never reads the `Release-Level:` trailer
     (`/release-commit` stops on such a host), **or** it lacks the 정식 릴리스 노트 스텝
     (`vway-release-notes`) that folds the user-approved CHANGELOG section into the GitHub
     Release body — guide the user:
     (1) re-render — the script does **not** overwrite an existing
     `.github/workflows/release.yml` (custom-preserving), so with the
     user's consent delete it and re-run so `render_versioning_workflows`
     writes the new template (merge any custom edits back); (2) on the token flag, the new
     workflow needs a repo secret **`RELEASE_TOKEN`** (fine-grained PAT,
     Contents: Read and write) — walk them through the report's
     create/inject steps (this is a GitHub-web action the script cannot
     do). See `docs/usage/promotion-and-release.md` "릴리스 CI 토큰 (RELEASE_TOKEN)".
  6. **Reconfigure (opt-in):** Ask the user (multi-select) — "재설정할 항목을 고르세요"
     (default: nothing). Options map to the existing steps,
     and you run **only the selected** ones against current values:
     - `vdev-config.yaml` 값 → Step 1's slot prompts (existing values shown as defaults)
     - Codex 게이트 → Step 1's `harnesses` slot
     - Recoble 스페이스 → Step 1's `alm` slot + Step 2.8
     - Teams webhook URL → Step 3's webhook prompts
     - CLAUDE.md teams 블록 → Step 3's managed-block step
     - Teamer 자격증명 → Step 4's guidance
     If the user selects nothing, stop after re-sync + backfill.
  7. **Re-render (6 이 렌더 플래그나 `harnesses` 를 건드렸을 때만):** `doc_style.enable`,
     `unit_test.enable`, `contract_test.enable`, `e2e.enable`, `deploy.enable` 이
     워크플로가 쓰이는지를, `harnesses` 가 게이트를 어느 에이전트 CLI 에 심을지를 정하는데,
     2 의 재동기화는 그 질문을 하기 **전에** 돎. 그중 하나에 새 값이 들어갔으면
     `vdev_init_setup.py` 를 한 번 더 돌릴 것 — 아니면 호스트가 워크플로 없는
     `enable: true` 를 이고 가고(`doc_style` 의 경우 사용자가 켰다고 믿는 규칙이 어느
     레이어에서도 강제되지 않음), `codex` 를 적고도 `.codex/hooks.json` 에 게이트가 없음.

  Re-run never re-gathers everything and never overwrites host-owned config
  without the user selecting that section.

### Step 0 — Dependencies: detect (script), then install-with-consent (you)

Detection is mechanical → a script. Choosing **how** to install for *this*
environment, and doing it, is judgment → you (the host AI). Never install without
consent; never mutate machine-wide state.

1. **Detect** — run the checker (detection only; it does not install):
   ```bash
   bash "${PLUGIN}/scripts/check-deps.sh"
   ```
   It reports each dep as present/absent: **python3 ≥ 3.8** (required),
   **PyYAML** (required), **pre-commit** (recommended), **superpowers** plugin
   (required for Dev+). Its printed install commands are a *baseline hint* —
   you may find a better method for the actual environment.

2. **Install what you can — only after consent.** For each missing **pip-installable**
   dep (PyYAML, pre-commit):
   - Inspect the environment to choose the method: is `python3 -m pip` available?
     is it externally-managed (PEP 668)? Look up the right approach if unsure. The
     package **must land in the bare `python3` the commit hook calls** — prefer
     `python3 -m pip install <pkg>` (or `--user` when externally-managed), **not**
     `uv add` / a project venv the hook can't see.
   - **Ask first** — ask the user (structured choice): show the exact command you intend to run;
     let the user **approve / pick an alternative / decline (install themselves)**.
   - On approval, run it, then re-run `check-deps.sh` to confirm. If it fails,
     diagnose and propose a better method (venv, pipx, OS package) — don't silently
     give up.

3. **Guide what you cannot install** (relay clearly; offer the command but let the
   user run it):
   - **python3 / version upgrade** — OS-level (Homebrew / apt / winget / choco),
     often needs admin. Offer the command for the detected OS.
   - **superpowers plugin** — installed via the host tool's *user-invoked* plugin
     command (`/plugin install superpowers@…`); you cannot run it. Guide the
     marketplace-add + install steps.

4. If a **required** dep (python3 ≥ 3.8, PyYAML) is still missing after this,
   **stop** and tell the user — the commit gate fails closed on every commit until
   it is present.

### Step 1 — Generate `vdev-config.yaml` (interactive — Claude)

1. **When this step runs:** on a first run (config absent), build the file from
   scratch via item 2's three steps below. On a re-run, this step runs **only if the user
   selected "vdev-config.yaml 값"** in the reconfigure menu (see Execution modes)
   — then edit only the specific values the user wants, showing current values as
   defaults; never a full re-entry, never a blind rewrite. (Missing-slot backfill
   is handled separately in Step 2.5.)

2. If the file is **absent** (first-time setup), build it:

   1. Read `${PLUGIN}/vdev-config.example.yaml` as the template (slots + format comments).
   2. Ask the user (structured choice) for each slot, showing the example value as default:
       - **branches**: `integration` / `staging` / `production` / `feature_prefix`
       - **teamer** (→ `alm.teamer`, see `alm` below — needed only when
         `alm.provider` includes `teamer` or the user explicitly wants Teamer,
         otherwise leave empty): `project_no` / `workitem_no` / `workflow_no`. Still
         no hardcoded fallback when in use — if the user cannot provide them, stop and
         explain they are mandatory for `/task-import` · `/task-sync`.
       - **alm** (ALM 연동): `provider`·`auto` 질문. `provider` 는 택일이 아니라
         `[recoble, teamer]` 처럼 **여럿 나열 = 동시 전송 가능**임을 함께 제시.
         `recoble` 이 들어가면 [`references/recoble-spaces.md`](references/recoble-spaces.md)
         §1 로 스페이스·`layers` 수집. Teamer 번호는 `alm.teamer` 에(최상위 `teamer:` 아님).
         `alm.recoble.propagate` 는 예시 그대로 `enable: false`, 켜는 시점은 팀이 항목 계층을
         실제로 쓰기 시작할 때.
       - **review_checklist**: keep the generic categories; let the team append.
       - **doc_sync**: `index` / `dirs` / `service_docs` (empty if no per-service docs).
       - **contract_test** (REST API 계약 테스트 — CI 전용): 먼저 ask the user (structured choice) 로
         "이 repo에 REST API가 있습니까?" 질문. **아니오** → `enable: false`로 쓰고
         이하 슬롯은 생략. **예** → `branches`(기본값으로 `vdev-config.branches`의
         integration/staging/production 값을 제안하되 독립 편집 가능), `schema`(OpenAPI
         스펙 URL/경로), `base_url`, `server.compose_file`/`health_url`/`health_timeout`
         수집.
         - **도구 pin (셋업 시 1회)**: `harness-researcher` 에이전트로 OpenAPI 계약 테스트
           도구 후보의 **최신 유지보수 상태**를 웹 확인 → 추천(기본 `schemathesis` +
           `schemathesis/action@v3`) 제시, 선택을 `tool`/`action_ref`에 **고정(pin)**.
           이후 CI는 이 고정값으로 결정적 실행(매 CI마다 웹 확인 없음).
       - **doc_style** (산문 규율 — `rules/doc-style.md`): ask the user (structured choice) 로
         "산문 규율을 강제합니까?" 질문. **"아니오"의 비용을 옵션 설명 안에 담을 것**:
         커밋 시점 단계는 경고만 하므로 `.github/workflows/doc-style.yml` 이 이 규칙이
         강제되는 유일한 자리임 — 거절은 더 가벼운 검사를 남기는 것이 아니라 검사를
         남기지 않음. **예** → `enable: true`, 이어서 `paths`·`exclude`(예시 파일의 두
         값을 그대로 기본값으로 제시 — 값의 SSOT 는 예시 파일의 주석. `**/*.py`·`**/*.sh`
         가 주석·독스트링을 덮는다는 것과 `exclude` 기본 항목이 어떤 편집으로도 통과 못
         하는 파일이라는 것을 함께 말함). **아니오** → `enable: false`,
         그러면 Step 2 가 워크플로를 렌더하지 않음. 이 플래그는 커밋 시점 단계도 몰므로
         한 번의 답이 두 레이어를 정하고, 나중에 되돌리면 이미 렌더된 워크플로가 삭제
         없이 조용해짐.
       - **modules** (모노레포 모듈 단위 사전검사 — 호스트 소유, config 아래 위치):
         첫 실행 시 값 수집 없음. Step 2.6 에서 harness SSOT 를 참고해 초안 작성 또는
         사용자 입력.
       - **harnesses** (커밋 게이트를 심을 에이전트 CLI — Claude Code 는 언제나 포함이라
         항목이 필요 없음): 이 세션 자체가 Codex CLI 에서 돌면 묻지 않고
         `harnesses: [claude, codex]` 를 쓰고, 게이트가 Codex 에도 심긴다고 사용자에게 알림.
         그 밖에는 호스트에 `.codex/` 디렉터리가 있거나 사용자가 Codex 를 언급했을
         때**만** ask the user (structured choice) 로 Codex 에도 게이트를 심을지 물음. **예** → example 의
         주석 슬롯을 `harnesses: [claude, codex]` 로 풀어 씀. **아니오**·조건 없음 → 슬롯을
         주석 그대로 둠(키 부재 = Claude 만). codex 를 적었으면 Step 2 리포트가 Codex trust 안내를
         싣는다는 것과, Codex 의 `/hooks` 에서 게이트 훅을 승인해야 돈다는 것(승인 전엔
         조용히 skip)을 함께 전할 것. 재실행은 Codex 세션 규칙을 다시 적용함
         (Execution modes, Re-run 1).
   3. Write the filled `${ROOT}/.claude/vway-kit/config/vdev-config.yaml` (create the
       `.claude/vway-kit/config/` directory if absent).

### Step 2 — Run the mechanical setup (idempotent script)

The deterministic wiring is done by a script so it is repeatable and tested — do
**not** hand-merge JSON/YAML:

```bash
python3 "${PLUGIN}/scripts/vdev_init_setup.py"
```

**Read its exit status before relaying.** Non-zero means no commit gate on this
host — the script re-read what the run left, so that outranks any `[+]` above it.
Relay its closing line verbatim, never as success, and name the `[!]` to fix.

It performs the steps listed in
[`references/setup-script-actions.md`](references/setup-script-actions.md) — copies,
hook/marketplace registration, `.gitignore`, host templates, and the CI workflow renders —
and prints a report. **Relay that report; it is the authority on what was written**, not
this skill's description of it.

Then remind the user to run `pre-commit install --hook-type commit-msg
--hook-type pre-push` (activates gitlint + the push notifier) and to swap the
language-specific `local` hooks for their stack.

### Step 2.5 — Backfill missing config slots (interactive — Claude, skippable)

The Step 2 script prints a `[config 슬롯 점검]` block listing slots present in
`${PLUGIN}/vdev-config.example.yaml` but absent from the host config (key-absence
only; handoff kinds appear as `handoff.<kind>`).

- If it lists missing slots, ask the user (multi-select) ("example 에 새 config 슬롯 N개
  (<목록>)가 있습니다. 호스트 config 에 추가할까요?", allow all or a subset, default all).
- For each accepted slot, read its block from `${PLUGIN}/vdev-config.example.yaml` and
  **insert it verbatim** (comments and example defaults intact) into the host config at
  the parent anchor (end of the parent section; top-level slots append a new section)
  using **Edit** — never a PyYAML round-trip (preserves comments/format).
- **`alm` is the one slot whose example values are actively harmful if kept.** When
  Step 2's `[폐기 필드 점검]` reports a lingering top-level `teamer:`, inserting `alm:`
  verbatim *kills* that host's Teamer integration (`load_alm_config` prefers `alm`) and
  points it at vway's own example numbers and placeholder MCP spaces. Migrate the
  host's values instead — [`references/recoble-spaces.md`](references/recoble-spaces.md) §4.
- Tell the user to adjust values for their environment; `enable`-style flags stay as in
  the example (handoff kinds stay `enable: false` until opted in).
- Skip entirely when the report lists no missing slots.

### Step 2.6 — 모듈 사전검사 초안 (harness 설치 시, skippable)

`vdev-config.modules[]`(모노레포 모듈 단위 사전검사 설정) 초안 작성.
harness 설치 여부를 먼저 판단, 결과에 따라 처리 분기.

**harness 감지**: `${CLAUDE_PROJECT_DIR}/docs/code-style/` 디렉터리 또는
`${CLAUDE_PROJECT_DIR}/services/*/CLAUDE.md` 파일이 하나라도 존재하면 harness 설치됨으로 판정.

**harness 가 설치된 경우** — SSOT 를 읽어 modules 초안 작성. 절차는
[`references/modules-draft.md`](references/modules-draft.md) §1(도구를 못 찾거나
모호하면 추측하지 말고 ask the user (structured choice) 로 확인).

**기존 `test.command`(구버전) 처리** — 첫 실행·재실행 모두 적용(Step 2 의
`[폐기 필드 점검]` 보고가 전역 `test.command` 를 표시하면 재실행에서도 **반드시** 수행 —
마이그레이션은 정의상 재실행이므로 이 단계를 첫 실행에만 묶으면 잔재가 영영 안 지워짐).
절차는 [`references/modules-draft.md`](references/modules-draft.md) §2.

**규율** — modules 삽입·`test:` 제거 모두 **PyYAML round-trip 금지**, Edit 로 해당 블록만
도려내고 다른 절·주석·포맷은 무접촉.

**harness 가 없는 경우** — ask the user (structured choice) 로 modules 슬롯을 직접 입력받거나, 지금은 비워 두고
나중에 수동으로 채울지 선택. 사용자가 스킵을 선택하면 `modules:` 를 빈 배열(`[]`)로 쓰고 진행.

### Step 2.6b — unit_test.jobs 초안 (modules 시드/변환, skippable)

`vdev-config.unit_test.jobs[]`(CI 유닛 테스트 매트릭스) 초안 작성.
`modules`(커밋 게이트 SSOT)와 `unit_test`(CI SSOT)는 **분리된 두 SSOT** — 시점·용도가 다름
(게이트=로컬 커밋 / CI=푸시).

> **런타임 파생 없음** — 렌더러(`render_unit_test_workflow`)는 `unit_test.jobs` 만
> 치환하며 `modules` 를 안 읽음. 아래는 **셋업 시점 1회 초안 작성**(config→config 변환).
>
> **코드베이스 스캔 금지** — 스택·컨벤션 감지는 `harness-init` 책임. 이 단계는 이미 채워진
> config 만 읽음.

1. `unit_test` 섹션이 없거나 `jobs` 가 빈 경우에만 수행(이미 채워져 있으면 skip — config 가
   최종 권한).
2. `modules[]` 가 채워져 있으면 **시드/변환**: 모듈마다 `name` ← 모듈명, `test` ← `checks.test`.
   `checks.test` 가 없는 모듈은 스킵(CI 에서 돌릴 것이 없음).
3. `language` / `version` / `setup` 은 `modules` 에 없는 정보. config 텍스트만으로 확정되지
   않으면 **ask the user (structured choice) 로 질문(추측 금지 — Step 2.6 과 같은 규율)**.
   - `language` 는 공식 setup action 택일 키: `python` · `node` · `java` · `go` · `rust`.
     그 외 언어(scala·c# 등)는 빈 문자열 `""` 로 두고 `setup` 셸이 런타임 전담.
     대소문자 무관(렌더러가 casefold 로 매칭해 소문자 정규화) — 그래도 초안은 소문자 권장(가독성).
   - `rust` 의 `version` 은 toolchain 이름(예: `stable`).
   - `language` 가 이 5개 중 하나면 `version` **필수** — 비워 두면 렌더 시 해당 job 이 matrix 에서
     제외되고 `[!]` 로 보고됨(빈 `version` 이 공식 action 에 그대로 전달되면 action 자체의
     default 가 무력화되어 실패).
4. `modules[]` 가 비면(harness 부재·사용자 스킵) ask the user (structured choice) 로 직접 입력받거나
   `jobs: []` 로 두고 진행. **폴백에도 코드 감지 없음.**
5. 작성한 초안은 `vdev-config.yaml` 의 `unit_test.jobs:` 에 **Edit 로 삽입**
   (PyYAML round-trip 금지 — 주석/포맷 보존). 리서치 결과는 기본값이며 사람이 수정.

### Step 2.7 — release.yml 수동 저작 (release_tool 미지원 도구, skippable)

Step 2 스크립트가 `[?] release_tool=... 은 준비된 템플릿이 없습니다` 를 보고하면(6개 known
템플릿 — `python-semantic-release`/`semantic-release`/`jreleaser`/`gitversion`/
`cargo-release`/`sbt-ci-release` — 어느 것도 아님, 예: Go/C++/기타), 스크립트는
그 도구를 추측해 만들지 않음(고정 템플릿 매핑은 언어가 늘 때마다 다시 깨지는 하드코딩이라 근본
해결 아님). 대신 **AI가 직접 작성**:

1. **스택 확인** — `vdev-config.modules[]`, `docs/code-style/<stack>.md`(harness SSOT),
   또는 harness 미설치면 이미 Step 1에서 받은 값으로 언어·릴리스 도구 확정.
   모호하면 ask the user (structured choice) 로 직접 질문(추측 금지).
2. **작성** — 확정된 릴리스 도구의 표준 CI 저작법(공식 문서·GitHub Actions 마켓플레이스
   기준)으로 `${ROOT}/.github/workflows/release.yml` 을 Write. Conventional Commits +
   SemVer 전제, `vdev-config.versioning.branches.stable`/`prerelease` 를 트리거 브랜치로
   사용 — 기존 6개 예시 템플릿(`github/release.python-semantic-release.workflow.example.yml`
   등)과 같은 뼈대(checkout → 툴체인 설치 → 릴리스 도구 실행 → 태그/체인지로그 반영)를 따름.
3. **덮어쓰기 금지** — `release.yml` 이 이미 있으면(스크립트가 만든 것이든 사람이 만든
   것이든) 무접촉(`_render_one` 이 아는 도구에 적용하는 것과 동일 불변식).
4. **스킵 가능** — `versioning.enable: false` 거나 사용자가 나중에 직접 만들겠다고 하면
   ask the user (structured choice) 로 확인 후 스킵.

### Step 2.8 — Recoble MCP 확인 (interactive — Claude, skippable)

Step 2 의 `[Recoble MCP]` 출력을 보여주고 [`references/recoble-spaces.md`](references/recoble-spaces.md)
§2 를 따름(등록은 사용자 터미널의 `claude mcp add` — **PAT 를 묻지 않음**). 계층이 `fields` 를
선언했으면 이어서 §5 — 그 필드가 보드에 실재하는지는 스크립트가 아니라 MCP 만 앎.

### Step 2.9 — srs-verify 워크플로 제안 (interactive — Claude, skippable)

`${ROOT}/docs/srs/` 가 체크아웃에 있을 때만 해당 — 없으면 워크플로가 가리킬 대상 없음.

Ask the user (structured choice) 로 `srs-verify.yml` 렌더 여부를 물음. **옵션 설명 자체가 거절 비용을
짐** — 위의 `wiki-verify`·`doc_style` 질문과 같은 규율: 커밋 게이트는 SRS 를 읽지 않으므로
이 워크플로가 죽은 앵커와 두 브랜치가 같이 뽑은 번호를 보는 유일한 곳. 거절은 가벼운 검사가
아니라 검사 없음.

**yes** 면 아래를 돌리고, 낸 줄을 그대로 전달. 기존 `srs-verify.yml` 은 보고만 하고 덮지
않음. 명령을 호스트 사본이 아니라 `${PLUGIN}` 으로 적는 것은 `vdev_init_setup.py` 가
`COPY_FILES` 에 없어 호스트에 사본이 없기 때문.

```bash
python3 "${PLUGIN}/scripts/vdev_init_setup.py" --render-srs-verify
```

**no** 면 SRS 앵커를 검사하는 것이 이제 아무것도 없음을 분명히 말하고, `/vdev-init` 재실행이
다시 제안한다는 것도 함께 말함.

### Step 3 — Teams webhook URLs + CLAUDE.md block (interactive — Claude, skippable)

1. Ask for the **personal** webhook URL (input-wait alerts). If provided:
   `python3 "${ROOT}/.claude/vway-kit/scripts/teams_alert.py" --set personal <URL>` →
   writes `${ROOT}/.claude/vway-kit/config/.teams-webhooks.local.json` (gitignored).
2. Ask for **team branch** channels (keys = branch names, e.g. integration /
   staging / production). For each provided: `--set <branch> <URL>` → the URL goes to the
   gitignored `.teams-webhooks.local.json`, and the branch name alone to the tracked
   `${ROOT}/.claude/vway-kit/config/teams-webhooks.json`, so every clone watches it and a
   clone holding the URL posts. Only when the user wants the URL itself committed for the
   team, add `--shared`: the URL's `sig=` token is the credential that posts to the channel,
   and a public or widely cloned repo hands it to everyone who reads it. Empty URLs are
   skipped at send time, so partial setup is fine.
3. **If any Teams channel was configured**, offer — ask the user (structured choice), default
   yes — to add a **managed Teams-usage block** to the host `CLAUDE.md` so this
   repo's Claude alerts **right before presenting a question to the user** — which the
   Notification hook does *not* cover (it only auto-fires on permission, idle and
   input-request waits). The alert directive must be **emphasized** (`IMPORTANT`/반드시) so
   the host model does it. Insert between the idempotent markers, **written in the same
   language as the existing host `CLAUDE.md`** (the Korean block below is the
   reference content — translate it to match the doc's language); if the markers
   already exist, **replace the block in place** (never duplicate). If
   `${ROOT}/CLAUDE.md` is absent, create it containing only this block. The script
   path is the host-installed copy `.claude/vway-kit/scripts/teams_alert.py` (not the
   plugin SOURCE). Skip entirely if no channel was set or the user declines:
   ````markdown
   <!-- vway-kit:teams BEGIN (managed by /vdev-init — edits inside are overwritten) -->
   ## Teams 알림 (vway-kit)

   **IMPORTANT — 사용자에게 질문(또는 사용자 입력 대기)을 띄우기 직전, 반드시 먼저
   personal 채널로 알린다:**

   ```bash
   python3 "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/.claude/vway-kit/scripts/teams_alert.py" \
     --channel personal --title "입력 대기" --text "<한 줄 작업 요약>"
   ```

   - **왜 수동인가** — 사용자 질문은 Notification 훅 트리거가 아니다. 옵션 제시
     시점을 알리는 길은 이 호출뿐(권한·idle·입력 요청 대기는 훅이 자동 처리). 카드에
     `project @ branch` 자동 부착.
   - **`CLAUDE_PROJECT_DIR` 폴백 권장** — 이 변수는 **훅 실행 시에만** 자동 주입됨.
     `teams_alert.py`는 미설정 시 git toplevel 로 폴백해 자가 치유하지만, 명시성을
     위해 수동 호출(사용자 질문 직전)에는 위처럼
     `:-$(git rev-parse --show-toplevel)` 폴백 부착(cwd 가 저장소 밖일 때의 안전망).
   - **웹훅 설정** — 웹훅 URL 은 `.claude/vway-kit/config/.teams-webhooks.local.json`
     (gitignored, 사용자별). `.claude/vway-kit/config/teams-webhooks.json`(git 추적)은 감시할
     브랜치(`dev`/`stage`/`main` 등) 이름을 쥐고, URL 은 `--shared` 로 등록했을 때만 담음.
   - **보안** — Power Automate URL 의 `sig=` 토큰이 채널에 글을 올리는 자격증명. `--shared` 로
     커밋한 URL 은 저장소를 읽는 누구나 채널 메시지를 주입하게 함(데이터 유출·권한 상승 없음) —
     그것을 받아들이기로 정한 뒤에만 시크릿 스캐너 예외로 둠.
   <!-- vway-kit:teams END -->
   ````

### Step 4 — Teamer credentials (interactive — Claude)

Guide the user to run `python "${CLAUDE_PLUGIN_ROOT}/scripts/teamer_api.py" setup` in
their terminal for `/task-import` · `/task-sync`. Credentials are stored in the OS
keyring (service `vway-kit-teamer`) — **not** a plaintext file. Setup migrates an
existing `teamer_account.md` into the keyring and deletes it, or prompts via getpass.
Do **not** collect the password yourself (never through a question to the user — that would put
it in model context). `keyring` 미설치 시 `python3 -m pip install keyring`.

## Completion report

Print a summary: the **Step 0** dependency status (python3 ≥3.8 / PyYAML required —
gate fails closed if missing; pre-commit / superpowers guidance), the **Step 2**
script report (copied / registered / pre-commit checked / **contract-test /
unit-test workflow rendered-or-skipped** / **deploy workflow rendered-or-skipped** /
**srs-verify workflow rendered-or-skipped** / **Recoble MCP render
(new/updated/skip)** / **release.yml wiring
added/updated/refused** / skipped, + any missing
pre-commit hooks to add manually, + the auto-update auth guidance if surfaced),
the **Step 2.6** modules 초안 결과(harness 감지 여부 / 작성된 modules 수 / 미확인
항목 목록 / 스킵 여부) **및 Step 2.6b unit_test.jobs 초안 결과(시드된 job 수 / 미확인
항목 목록 / 스킵 여부)** **및 폐기된 전역 `test.command` 처리 결과(추적→modules 이전→제거,
또는 잔존 안내)**, whether the
`CLAUDE.md` Teams block was added/updated/skipped, and the manual follow-ups
(`pre-commit install`, `Teamer keyring setup (teamer_api.py setup)`, swapping language-specific hooks). **If
the Teams block was inserted and the host `CLAUDE.md` already had a hand-written
Teams-alert rule (pre-vway-kit), advise removing it — the managed block supersedes it
(never delete the user's content automatically).** Then tell the user they can run
`/vdev`.

부재 둘은 리포트의 침묵에 맡기지 말고 이름을 부를 것 — 둘 다 레이어가 꺼져 있는데
나중에 그렇다고 말해 주는 것이 없음: `doc_style.enable: false` 는 산문 규칙이 적혀만
있고 아무 데서도 강제되지 않는다는 뜻이고, `wiki-verify.yml` 은 여기서 아예 렌더되지
않음 — wiki 가 생긴 뒤 [`/wiki-init`](../wiki-init/SKILL.md) 이 제안함.

## Critical rules

1. **Secrets discipline** — Teamer credentials stay in the OS keyring, and webhook URLs in
   the gitignored `.claude/vway-kit/config/.teams-webhooks.local.json`; the tracked
   `teams-webhooks.json` carries the watched branch names. A branch URL is committed only
   when the user asks for `--shared` (worst case channel-message injection by anyone who
   reads the repo).
2. **CLAUDE.md edits are a managed block only** — touch only the marked
   `vway-kit:teams` region; leave the user's own content as written.
