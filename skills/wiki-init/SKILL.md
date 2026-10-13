---
name: wiki-init
description: Set up an LLM Wiki in this repo — migrate existing docs into one-concept-per-file nodes with YAML front matter, then build the knowledge graph. Idempotent, incremental on re-run.
disable-model-invocation: true
---

# Wiki-Init — LLM Wiki 설치 마법사

기존 문서를 wiki 노드로 이전 + `graph.yaml` 생성. 임베딩 없음 — 관계는 front matter 에 손으로
쓰고, 그래프는 그것을 기계적으로 읽을 뿐.

**선행조건**: `.claude/vway-kit/config/vdev-config.yaml` 필요. 없으면
[`/vdev-init`](../vdev-init/SKILL.md) 을 먼저 돌리라 안내하고 **중단**.

재실행은 증분 — `wiki_id` 를 이미 가진 문서는 미변경.

**Interaction.** Wherever this skill asks the user something, use the host's blocking question
tool already in your tool list, matched by capability rather than by a host-specific name; if it
is listed but not loaded, load it first with the host's tool-discovery primitive; only when no
such tool is listed, or a question call errors, offer numbered options in chat and end your turn
to wait for the reply — never answer the question yourself or skip it.

## 1. wiki 루트 확인

Ask the user (structured choice) 로 확인. 기본값 `docs/` — `/harness-init` 산출물과 같은 트리에 둬야 문서
집합이 하나로 유지됨.

## 2. 스캔

루트 아래 `.md` 를 훑어 이전 후보 표 작성. 각 행: 파일 경로 · 줄 수 · H2 개수 · front matter 의
`wiki_id` 유무. 큰 줄 수 + 여러 H2 = 여러 개념이라는 **신호**이지 판정 아님 —
Installation/Usage/FAQ 페이지는 H2 가 여럿이어도 한 개념, 경계는 4단계에서 내용으로 판단.
`wiki_id` 있는 행은 이미 wiki 노드 — 맥락용으로 표에 남기되 이전 후보 아님.

**노드 표식은 `---` 블록도, `id` 도 아닌 `wiki_id`.** 문서 사이트 자체 메타데이터
(MkDocs · Docusaurus · Jekyll: `id`, `sidebar_position`, `slug`, `layout`, …)도 front matter 이고
그중 `id` 는 여럿에서 문서화된 1급 필드 — wiki 가 그것을 안 쓰는 이유. 그런 파일은 노드가
*아님*(검증이 무시). 평범한 이전 후보이니 블록을 새로 얹지 말고 기존 블록에 wiki 필드를 병합,
그쪽 `id` 는 유지.

## 3. 선택

후보 목록에는 **`wiki_id` 없는** 문서만 — 이미 있는 문서는 이미 노드이고 이번·이후 실행에도 재제안
안 됨(재실행이 증분인 이유). 남은 문서 중 이전 대상을 사용자가 선택. 후보가 많으면 배치로 질문.
미선택 문서는 그대로 — `wiki_id` 가 없으면 wiki 밖이라 검증 대상 아님.

## 4. 분할

2단계에서 센 H2 개수로 분기:

- **H2 0개** — 쪼갤 것 없음. 문서 자체가 노드 하나: front matter 만 부여, 새 파일 생성 없음.
- **H2 정확히 1개** — 쪼개면 새 파일 하나 + 껍데기 원본만 남아 이득 없음. H2 0개와 동일 취급.
- **H2 2개 이상** — **개념이 갈리는 H2 만** 분할. 구조적 섹션(사용법·FAQ·설치)은 자기 개념에
  붙어 있고, H2 전부가 한 개념의 여러 면인 문서는 미분할. 쪼개는 H2 는 새 파일로.
  **원본 삭제 금지** — 각 섹션 자리에 새 문서로 가는 링크를 남김(되돌리기 쉬운 변경이 목표).

  남은 원본도 노드. 링크만 든 껍데기가 아니라 자기 경로에서 파생한 `wiki_id`(5단계)와 쪼개 나간
  모든 문서를 가리키는 `related` 를 가진 front matter 부여. 아니면 링크는 들고 있으면서 자신은
  wiki 밖에 앉아 그래프의 어떤 경로로도 닿을 수 없음.

## 5. front matter 부여

`wiki_id` 는 wiki 루트 **기준 상대경로**에서 기계적으로 파생 — 손으로 고르지도, 손으로 파생하지도
않음: [`wiki_graph.py`](../../scripts/wiki_graph.py) `--derive-id` 를 고른 문서 전부에 대해 **한 번**
호출하고 실제 경로 전달(예: `python3 .claude/vway-kit/scripts/wiki_graph.py --derive-id
docs/code-style/python.md docs/api_spec.md --root docs/`). stdout 한 줄 = `경로<TAB>id`.

**`--root` 에는 1단계에서 확정한 루트를 반드시 전달.** 생략 시 `vdev-config` 의 wiki.root 를 읽는데,
그 값을 쓰는 것은 7단계이므로 지금은 아직 출하 기본값(`docs/`) — 사용자가 `documentation/` 을
골랐다면 모든 노드가 `documentation.` 접두를 달고 태어나고, `--verify` 는 경로↔id 대응을 안 보므로
통과. 7단계 이후 doc-sync 가 추가하는 문서는 접두 없이 파생돼 한 그래프에 id 체계가 둘. id 를 만들
수 없는 경로 — 정규화 후 `[a-z0-9]` 가 안 남는 세그먼트, 예: 한글만인 파일명 — 는 사유와 함께
stderr 에 지목되고 호출은 비영 종료, 단 성공한 경로는 그대로 자기 줄을 냄: 지목된 파일만 개명해
재실행. 규칙의 주인은 `derive_wiki_id`, 아래 표는 그것과 대조 테스트됨
(`tests/wiki/test_parity.py`) — 행 추가 = 테스트 케이스 추가:

| 경로 (루트 `docs/`) | wiki_id |
|---|---|
| `docs/code-style/python.md` | `code-style.python` |
| `docs/a.b.md` | `a-b` |
| `docs/a/b.md` | `a.b` |
| `docs/api_spec.md` | `api-spec` |
| `docs/sds/README.md` | `sds.readme` |
| `docs/onboarding/README.md` | `onboarding.readme` |

규칙 안의 **순서**가 `docs/a.b.md`(→ `a-b`)와 `docs/a/b.md`(→ `a.b`)를 구별 — 세그먼트를 `.` 로 잇기
**전에** 각각 정규화하기 때문. 단 형제 간 충돌까지 없지는 **않음**: 한 디렉터리의 `a.b.md`·`a-b.md`·
`a_b.md` 는 전부 `a-b` 로 파생. 어느 쪽이든 `--verify` 가 중복으로 보고하고(순서를 뒤집어 손으로 판
id 도 같은 검사에 걸림), 해소는 파일 하나 개명 후 재파생.

`wiki_id` 는 한 번 부여되면 **불변** — 파일 이동·개명에도 재파생 금지(개명을 가로질러 링크를
안정시키는 근거가 그 id). 파생은 최초 부여용.

`related` · `depends_on`: 기존 문서를 읽고 값을 **제안**한 뒤 사용자와 확정.
`used_by` · `defects` 는 **절대 금지** — 생성 필드라 손으로 쓰면 검증이 막힘.

설계 문서는 `tags: [sds]` 도 함께 부여. 설계 문서라는 표식이 그 태그 하나 —
`--verify` 의 `sources` 부재 경고도 `--unmapped` 도 그것을 읽으므로, 없으면 `sources` 가
아무리 비어도 어느 쪽도 그 문서를 부르지 않음.

`sources` 는 문서가 서술하는 코드 경로를 맵으로 기록. **파일** 경로 우선: staleness 판정이 파일
내용의 해시(`git hash-object`)라 디렉터리 키는 `--nodes-for` 조회에는 걸리되 `--stale` 에는 영영
안 나오고 마커도 미갱신 — 문서가 정말 그 디렉터리 전체에 관한 것이고 그 비대칭을 받아들일 때만
사용, 안의 파일들을 줄여 쓰는 용도 금지. sha 는 `null` 로 두면 [`doc-sync`](../doc-sync/SKILL.md) 가
채움. 모르는 sha 에 빈 문자열 금지: `""` 는 무엇과도 같다고 비교돼 그 노드는 영원히 최신으로 보고됨.
`sds` 문서는 이 키를 빼면 안 됨 — 매핑할 코드가 아직 없으면 `sources: {}` 로 적고,
키가 값을 가질 때까지(빈 맵도 값) `--verify` 가 경고. 빈 맵도 노드를 `--stale`·`--nodes-for`
밖에 두는 것은 같으므로 그것은 안식처가 아니라 "아직" 이라는 진술 —
[`doc-sync`](../doc-sync/SKILL.md) 가 `--unmapped` 로 빈 것들을 열거해 코드가 생기면 채움.

**sha 는 전부 따옴표, 키워드로 읽힐 수 있는 `title` 도 따옴표.** front matter 는 YAML 1.1 — 따옴표
없는 `0123456` 은 8진수라 숫자 42798, `title: no` 는 `false`. 검증이 타입으로 걸러내지만 따옴표를
쓰면 그 왕복이 없음.

defect 문서는 [`defect-template.md`](references/defect-template.md) 의 다섯 절 본문 구조를 따름 —
그 `wiki_id` 는 이 절의 경로 파생이 아니라 템플릿의 `defect.<슬러그>` 관례.

## 6. index 생성

`<root>/index.md` 자체가 wiki 노드 — 사람용 랜딩 페이지가 아님. 도달 가능성은 front matter
edge(`related` · `depends_on` · `used_by`, 방향 무시)로**만** 계산하고 본문의 마크다운 링크는 절대
안 읽음(설계 §3). 따라서 자기 `wiki_id`(관례상 `index`)와 **최상위 진입 노드**들 — 읽는 사람도
그래프 순회도 거기서 출발하는 개념들 — 의 `related:` 목록을 front matter 로 부여. 거기에 **모든**
노드 id 열거 **금지**: 전부 실은 index 는 그래프를 star 로 퇴화시키고, orphan 검사를 실제 연결성
측정이 아니라 "index 갱신 깜빡함 검사"로 만듦.

나머지 노드는 실제 edge 로 index 에서 도달돼야 함: 자기가 정말 속한 노드들에
(`related`/`depends_on`) 연결. 그래서 orphan 경고 = "이 노드가 의미 있는 무엇과도 안 이어져 있음",
해소는 관련 개념들에 연결 — 정말 최상위 진입점일 때만 index 에 추가. front matter 없이 본문 링크
목록만 있거나 `related:` 가 비면 orphan 검사가 통째로 무력화(모든 노드가 도달 불가로 보고되거나,
`_index_id` 가 노드를 못 찾아 검사 스킵).

본문의 사람용 링크 목록은 파일을 직접 여는 사람용 — 쓸모 있게 유지하되 그래프가 아니고 `related:`
와 1:1 동기화 불요.

## 7. vdev-config 갱신

`vdev-config.example.yaml` 이 이미 `enable: false` 인 `wiki:` 키를 배포 → `/vdev-init` 을 거친
호스트에서는 보통 **그 키의 기존 값을 제자리에서 수정**(`enable: true` 부터)이지 정해지지 않은
위치에 새 블록을 끼워 넣는 일이 아님. 어쩌다 키가 없으면 최상위 절로 삽입. 어느 쪽이든 `wiki` 키만
건드리고 나머지 설정은 보존.

```yaml
wiki:
  enable: true
  root: docs/
  index: docs/index.md
  max_lines: 400
  context_lines: 2000
  defect_rule_threshold: 3
```

## 8. 그래프 빌드·검증

만들거나 쪼개 낸 문서를 먼저 전부 `git add`. 그래프는 파일시스템이 아니라 git 인덱스에서 만들어짐 —
git 이 모르는 파일은 노드가 아님(그것을 담은 그래프는 클론한 사람에게 재현되지 않음).

```bash
python3 .claude/vway-kit/scripts/wiki_graph.py --build
python3 .claude/vway-kit/scripts/wiki_graph.py --verify
```

`--verify` 실패 시 보고된 사유를 고치고 재실행. 통과할 때까지 종료 금지. 실패는 두 부류이고 고치는
곳이 다름 — 출력이 어느 쪽인지 알려줌:

- **구조 위반**(`wiki_id` 형식·중복 · `title` 누락 · 아무것도 안 가리키는 `depends_on` · 순환 ·
  숫자/불리언으로 읽힌 스칼라 · `wiki_id` 를 달고 있으면서 파싱 실패한 front matter) — **문서의
  front matter** 수정. `--build` 는 무용(front matter 가 말하는 대로 그래프를 맞출 뿐). 이 목록은
  출력 시 10건 + 건수로 캡 → 고치고 재실행해 나머지 확인.
- **그래프 불일치** — `--build` 재실행.

그 밖의 출력은 전부 경고이고 비차단: orphan, max_lines 초과, 디스크에 없는 `sources` 경로,
`sources` 키가 없거나 값이 아예 없는 `sds` 문서, rule
승격 후보, `wiki_id:` 줄 없이 파싱 실패한 front matter, `wiki_id` 없이 wiki 전용 필드
(`related`/`depends_on`/`affects`/`sources`)만 있는 문서. 각각 3건 + 건수로 캡.

이번 세션에서 `--verify` 를 통과 못 시키겠으면 종료 전 7단계의 `enable` 을 `false` 로 되돌리고 남긴
위반을 보고. `--build` 가 `enable: true` 를 요구하므로 7단계 이후 게이트는 필연적으로 켜져 있고,
켠 채 그래프가 무효인 상태로 끝내면 누군가 손으로 고칠 때까지 저장소의 모든 커밋이 막힘.

`--verify` 는 **워킹트리**를 읽으므로 커밋이 그것을 안 담아도 디스크의 새 `graph.yaml` 만으로 만족.
`docs/graph/graph.yaml` 을 그것을 만들어낸 문서들과 **함께** 스테이징해야 함 — 아니면 커밋에는 새
front matter 옆에 옛 그래프가 기록되고, 다음 사람의 세션 커밋 전까지 아무도 그 drift 를 못 잡음.

**`graph.yaml` 의 머지 충돌은 절대 손으로 풀지 않음** — 생성 파일이라 손으로 합친 결과는 깨진
YAML 이거나 `--verify` 가 drift 로 거부하는 그래프. 아무 쪽이나 취하고
(`git checkout --ours -- <root>/graph/graph.yaml` 또는 `--theirs`) `--build` 재실행 후, 재빌드본을
문서들과 함께 스테이징. (merge driver 미설치는 의도 — 자동 `ours` 는 틀린 그래프를 조용히 다음
`--verify` 차단으로 미루지만, 충돌은 지금 재빌드를 강제.)

## 9. CI 검증 워크플로 제안

8단계의 `--verify` 가 통과한 뒤에만. 7단계의 `enable` 을 `false` 로 되돌려야 했으면 이 단계
통째 스킵 — 검증되지 않는 그래프를 검증하는 워크플로는 모든 push 를 붉게 만들고, 그것의
수정은 CI 가 아니라 front matter 임.

Ask the user (structured choice) 로 `.github/workflows/wiki-verify.yml` 렌더 여부를 물음. **옵션 설명이
거절의 비용을 담아야 함** — 그 공백이 에이전트 세션 안에서는 안 보이기 때문임: 커밋 시점 wiki
게이트는 **에이전트 세션(Claude Code 또는 Codex) 커밋만** 봄. 터미널 커밋도, CI 커밋도,
GitHub 웹UI 에서 한 머지도 그것을 지나지 않고 브랜치에 닿음. 그렇게 들어온 그래프 drift 는 누군가의 다음 세션 커밋이나
승격에서야 — 그것을 만든 커밋이 담기지 않은 diff 를 앞에 두고 — 드러남. 매 push 마다 그래프를
읽는 것이 이 워크플로 하나임.

**예**:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vdev_init_setup.py" --render-wiki-verify
```

스크립트가 플러그인의 템플릿을 읽어 호스트에 씀 — 8단계의 호스트 경로 호출과 달리 이것만
플러그인 루트로 철자하는 이유가 그것임(`.claude/vway-kit/scripts/` 에는 이 사본이 없음).

출력 줄을 relay. 이미 있는 `wiki-verify.yml` 은 보고만 되고 절대 덮이지 않으므로, 그
파일을 가진 호스트는 손대지 않은 채로 둠. 렌더된 파일은 8단계의 스테이징과 함께
`git add`.

**아니오**: 세션 밖에서 들어오는 그래프 drift 를 이제 아무것도 검사하지 않는다는 것과,
`/wiki-init` 재실행이 이것을 다시 제안한다는 것을 그대로 말할 것.

## 10. 리포트

무엇을 쪼갰고 어떤 `id` 를 부여했는지 + 남은 orphan·초과 크기 문서, 그리고 CI 워크플로
렌더 여부 보고.

**커밋 금지** — 커밋은 [`/vdev`](../vdev/SKILL.md) 의 일.
