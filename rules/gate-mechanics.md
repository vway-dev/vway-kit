# Gate Mechanics

> 게이트가 막았을 때, 또는 `vdev-config` 를 배선할 때 읽음. 세션 컨텍스트에 주입되지 않음 —
> 주입되는 것은 [`risk-tiers.md`](risk-tiers.md) 이고, 그 게이트 용어집이 여기를 지목함.

## `wiki`

`vdev-config.wiki` 가 켜져 있을 때 `graph.yaml` 이 문서 front matter 와 여전히 맞고 구조 규칙이
안 깨졌음을 **읽기 전용**으로 검증. 노드에 대한 변경이 `sources` sha 뿐인 커밋(본문 편집 없음)도
거부 — 그 도장은 [`doc-sync`](../skills/doc-sync/SKILL.md) Mode W 의 것. `docs` 포함 **모든
티어**에서 돎 — 문서 커밋이야말로 그래프가 어긋나는 순간. 어느 티어가 켜는지는
[`vdev-tiers.yaml`](../vdev-tiers.yaml).

훅의 게이트 스크립트가 **프로세스 내부 마지막 단계**로 실행함(`--wiki-check` 는 호환 alias).
미설정으로 세는 것은 셋 — 키 부재·`enable: false`·root 디렉터리 없음.

그래프를 **생성**하는 주체는 `/doc-sync`·`/wiki-init`, 그리고 단계가 `--build` 를 직접
지시하는 자리 — [`/vdev`](../skills/vdev/SKILL.md) Dev 2 와
[`/alm-docs`](../skills/alm-docs/SKILL.md)(둘 다 새 SRS 영역 파일),
[`/release-commit`](../skills/release-commit/SKILL.md)(막힌 승격 커밋). 훅도 CI 도
생성하지 않음.
생성 대상 노드 집합은 **git 인덱스**에서 옴 — `git add` 가 문서를 wiki 에 편입시키므로 새
문서는 스테이징 후 빌드. 진짜 검증 실패만 차단하고 내부 오류는 통과함(Invariant #1) — git 이
자기 인덱스를 못 읽는 경우도 포함이며, 그때 노드 집합이 파일시스템으로 떨어지면 git 이 숨기고
있는 바로 그 파일들까지 세어버림.

비차단 품질 경고(orphan, max_lines 초과, 디스크에 없는 `sources` 경로, `sources` 키가 없거나
값이 아예 없는 `sds` 문서, defect→rule 승격, `wiki_id:` 줄 없이 파싱에 실패한 front matter,
`wiki_id` 없이 wiki 전용 필드(`related`/`depends_on`/`affects`/`sources`)만 있는 문서)는
통과하는 커밋에서 `systemMessage` 로 돌아오며 종류별로 3건 + 건수로 캡. 차단 사유 쪽 구조 위반
목록은 10건 + 건수로 캡. defect 노드의 `regression_test`·`promoted_to_rule` 경로만은 `sources`
와 달리 **부재 시 차단**함: 그 둘은 추적되는 저장소 산출물의 존재를 주장하는 필드이고 고치는
법도 빠져나갈 구멍도 문서 한 줄 수정인 반면, `sources` 항목은 생성물이나 gitignore 된 파일을
정당하게 가리킬 수 있어 어떤 수정으로도 존재시킬 수 없음.

못 보는 것이 둘. 훅은 `git commit` 이 스테이징하기 **전**에 발화하므로 **워킹트리**를 읽음 —
`graph.yaml` 을 그것을 만들어낸 문서들과 함께 스테이징하지 않으면 커밋에는 새 front matter
옆에 옛 그래프가 기록되고 다음 세션 커밋까지 아무도 못 잡음. 그리고 **승격**(Staging/Release)
에서는 어떤 게이트도 그래프를 재생성하지 않음(`doc-sync` 가 승격 게이트가 아니므로) —
터미널 커밋으로 들어온 drift 가 거기서 막힌 승격으로 드러남. 그 복구 절차는
[`/release-commit`](../skills/release-commit/SKILL.md) 이 가짐.

## `doc-style`

이 커밋이 바꾼, 범위 안 파일을 [`doc-style.md`](doc-style.md) 에 대고 검사해 `systemMessage` 로
보고. **절대 차단 안 함** — 판정은 트리 전체를 보는 CI 의 `doc-style.yml` 몫이라, 규칙을 조인
순간 예측 못 한 커밋이 거부되지 않음. 플래그 하나가 두 팔을 몲: `/vdev-init` 이 그 워크플로를
`enable: true` 일 때만 렌더하므로 `false` 는 가볍게가 아니라 어디서도 강제하지 않는 것.

`paths`/`exclude` glob 의 기본은 산문을 읽어낼 수 있는 확장자 전부 — 주석·독스트링도 산문임.
그 범위를 CI 의 `--lint-config` 와 **같은 함수**가 읽으므로 `exclude` 가 두 팔 모두에 걸림.
`doc_style` 블록 부재·`enable: false`·어떤 내부 오류든 → 아무것도 안 돎(Invariant #1).
`vdev-config.yaml` 이 YAML 로 안 읽히면 CI 는 원문에 `doc_style:` 키(따옴표 철자 포함)가 있을
때만 붉어짐 — 켠 적 없는 저장소가 doc-style 소유도 아닌 곳의 오타로 붉은 빌드를 받지 않음.
키가 있으면 `enable: false` 여도 붉음: 설정이 깨진 동안 커밋 게이트는 미분류 커밋도 통과시키고,
그것을 드러내는 신호가 이 잡뿐임. 메시지가 문체가 아니라 설정이 원인임을 밝힘.

## 타이밍 버킷과 호스트 커스텀 검사

`precommit`·`security-scan` 이 무엇을 언제 도는지는 용어집이 정의함. 여기는 호스트가 그 버킷에
자기 검사를 붙이는 법과, 버킷 자체를 끄는 법.

호스트는 `vdev-config.modules[].checks` 에 임의 키를 더해 커스텀 검사를 붙임 — 명령 문자열
(타이밍은 키 이름이 정함: `security` 는 promotion, 나머지는 every-commit)이거나 `{run, when}`
확장 형식으로 타이밍을 명시(`on` 이 아니라 `when` — YAML 이 맨 `on` 키를 불리언으로 읽음).
**단 타이밍은 해당 티어의 `gates` 에 그 버킷 게이트가 있어야 발동** — `docs` 티어는 두 버킷이
모두 없어 커스텀 검사가 문서 커밋에서 아예 안 걸림(모듈 사전검사가 거기서 조기 종료).
`wiki`·`doc-style` 은 문서 커밋에서도 돎 — 모듈 검사가 아니라 그 경로를 안 탐.

둘 다 각 티어 `vdev-tiers.yaml` `gates` 목록의 평범한 항목이라 **거기서 빼면 그 티어의 그 버킷이
통째로 꺼짐**(예: `release` 에서 `security-scan` 을 빼면 릴리스 승격의 전체 모듈 보안 스캔이
멈춤) — 하드코딩된 티어 분기가 아니라 그 목록이 유일한 on/off 스위치. 레이어2 검사가 다 그렇듯
**에이전트 세션(Claude Code·Codex) 커밋에서만** 돎 — 터미널·CI 커밋은 게이팅 안 됨(강제가 필요하면 CI 안전망을 둘 것).

## 강제 속성

- **Fail-open on errors** — missing/unparseable policy or config, or
  any internal error → the action is allowed (a broken gate never bricks
  commits or deploys). The test is "the gate works reliably", not "a
  file exists". **Exception — an unclassified commit is fail-CLOSED**:
  when the policy parses and config is intact but no `tier` marker
  exists, the commit is **blocked** so skipping `/vdev` cannot silently
  disable the gate. Promotion gates are likewise fail-*closed* on
  missing evidence, but still fail-open on internal errors.
- **Branch-bound** — the `tier` marker carries the branch it was written
  on, so stale state on one branch cannot classify work on another.
  `<gate>.done` 마커는 브랜치를 안 실음 — 자기를 쓴 커밋보다 오래 살고,
  편집마다 PostToolUse 훅이 `review`·`doc-sync` 를 지우며(그 둘만),
  나머지는 `/vdev` 의 마지막 단계가 증거 디렉터리를 통째로 지울 때 사라짐.
  그 무효화의 스위치와 대가는 아래 "증거 무효화 스위치".
- Judgment gates (review quality, human integration test) can only be
  *recorded*, not verified — a marker is an audit trail + forcing
  function, not proof.
- **Air-gapped limit** — an offline production machine runs on a
  separate host a local hook cannot reach; the staging → production
  commit is the local release-authorization gate.

Clear state with `rm -rf .claude/vway-kit/.vdev` (also done by `/vdev`
after a successful commit/merge).

## merge 전략 판정의 fail-open

[merge-strategy](merge-strategy.md) 의 ✅ 행을 판정 없이 통과시키는 경우는 다섯뿐임.

- **의존성 없는 호스트의 pull** — python3 3.8+ 나 PyYAML 이 없으면 `commit`·`merge` 만 그 부재로
  막고 pull 은 통과.
- **브랜치를 못 읽는 switch 뒤의 머지** — `switch -c`·pathspec·원격이나 전체 ref·`main~0` 같은
  리비전 접미.
- **다른 디렉터리를 대는 머지** — `git -C <wt> merge …`·선행 `cd <wt> && …`. 머지마다 판정하므로
  이 root 에서 도는 형제 머지는 여전히 검사함. 앞의 `cd` 는 전부 따라가고 `-C` 는 그 끝에서 읽음.
  이 저장소의 하위 디렉터리는 다른 디렉터리가 아님. 이름 못 대는 `cd`(첫 `cd -`, 32단을 넘는
  연쇄)는 다른 디렉터리로 셈.
- **같은 명령이 만드는 디렉터리 안의 머지** — `mkdir d && cd d && …` 는 훅 시점에 없으므로 다른
  디렉터리로 읽힘.
- **게이트가 못 읽는 철자로 인터프리터 텍스트에 든 머지** — 확장으로 짓거나(`eval "$cmd"`·
  `bash -c "$c"`) 그 텍스트 안의 따옴표로 쪼갠 머지는 플래그를 못 읽음.

## 증거 무효화 스위치

`vdev-config.gate_evidence.invalidate_on_edit: false` 면 편집이 `review`·`doc-sync` 마커를
안 지움 — 통과 뒤의 작은 수정이 재실행을 물지 않는 옛 순서. 이 훅은 플러그인이 등록하므로
버전만 올라가도 켜지고 `/vdev-init` 에 동의할 단계가 없음 — 재실행 비용을 치르는 호스트가
답하는 자리가 이 스위치.

- **대가는 커버리지** — 통과 뒤의 편집은 리뷰가 요구한 수정까지 그 리뷰가 본 적 없는 채로
  커밋됨. `/vdev` 는 커밋·병합 뒤 증거 디렉터리를 여전히 지우지만, `<gate>.done` 은 브랜치에
  안 묶이므로 그 단계 없이 끝난 작업의 마커는 다음 작업에 브랜치와 무관하게 남음.
- **켜짐이 기본** — 훅은 최상위 `gate_evidence:` 블록 밑의 `false` 만 읽음. `no`·`off`·`False`
  같은 다른 YAML 거짓, 다른 블록 밑에 적은 키, 중첩 매핑·블록 스칼라 안의 줄은 전부 켜진 채.
  YAML 처럼 중복 키·중복 블록은 마지막 것이 답.
- **줄 단위로 읽음** — YAML 이 못 읽는 파일도 그 한 줄로 끔. 이 리더가 알아보지 못하는 줄은
  켜진 채로 둠.
- **트리마다 물음** — 편집이 낡게 만든 트리 각자의 설정이 답함. 끈 프로젝트의 세션이 다른
  repo 를 고치면 그 repo 의 마커는 그 repo 의 설정대로 지워짐.

---

*Pilot: Docs & Dev enforced at commit; Staging at integration →
staging, Release at staging → production / offline deploy. Full
one-shot `/vdev` automation of the Dev/Staging/Release pipelines
is a follow-up.*
