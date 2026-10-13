# 일상 작업

## `/vdev`

```text
/vdev <자유 텍스트 요청 | ALM task-id(예: DEV-0952)>
```

1. **입력 해석** — 입력은 언제나 요청 텍스트입니다. `DEV-0952` 같은 토큰만으로 ALM 을 치지 않습니다.
   연동 여부는 `vdev-config.alm` 이 정합니다([ALM 연동](alm.md)).
2. **분류** — 실제 변경이 **코드냐 아니냐**로 Docs/Dev 를 나눕니다.
3. **등급 확인** — 결과를 묻고(오버라이드 가능) 작업 브랜치(`feature/*`·`fix/*`)로 옮깁니다.
   불확실하면 한 단계 위로 잡습니다.
4. **실행**
   - **Docs** — 직접 편집 → `doc-sync` → `commit`
   - **Dev** — `superpowers` 파이프라인(설계→계획→구현→검증) → `doc-sync` → 도메인 리뷰
     (`review_checklist` + 변경 심볼 호출자) → `commit`. 편집이 리뷰를 무효화하므로 리뷰가 마지막입니다.
     spec·plan 은 Docs 로 먼저, 코드는 Dev 로 커밋합니다.
5. **마무리** — ALM 이 연결됐다면 `task-sync` 로 결과를 올립니다.

- Dev 에는 `superpowers` 플러그인이 필요합니다. 없으면 `/vdev` 가 중단하고 설치를 안내합니다.
- `/vdev` 를 거치지 않은 커밋은 등급 마커가 없어 **미분류 커밋**으로 막힙니다.
- 승격(integration→staging→production) 요청은 `/vdev` 가 `/release-commit` 으로 넘깁니다
  ([승격과 릴리스](promotion-and-release.md)).

## `commit`

모든 커밋 단계가 거치는 스킬입니다. 영향 파일만 스테이징하고, Conventional Commits type 을 고르고,
50/72 규칙을 검사한 뒤 `git commit` 을 발행합니다. `commit_guide` 파일이 있으면 그 스택 사실(스코프
어휘·0.x 정책·bump 파생 여부)을 우선 적용하고, 메시지 형식은 [`commit-discipline`](../../rules/commit-discipline.md)이
소유합니다. 단독 호출도 되지만 **분류는 하지 않으므로** 그 커밋은 여전히 막힙니다.

## `doc-sync`

`/vdev` 가 자동으로 호출합니다. 계획만 보려면 `/doc-sync preview`.

- **코드 → 문서** — 바뀐 코드의 키워드(클래스·필드·route·함수)로 관련 문서를 찾아 갱신합니다.
- **문서 → 문서** — `vdev-config.doc_sync` 대상의 상호 참조·사실 일관성·인덱스를 맞춥니다.
  `service_docs` 에 맞는 모듈에 로컬 `CLAUDE.md` 가 없으면 만들고, 있으면 부족한 부분만 보완합니다.
- **wiki 동기화** — wiki 가 있으면 각 노드의 `sources` 마커(워킹트리 blob hash)와 `graph.yaml` 을 갱신합니다.
- **내용 보존 대조** — 편집 뒤 `doc_invariants.py --changed` 로 HEAD 와 비교해 링크·헤딩·코드펜스·
  front matter 키·코드 스팬이 줄지 않았는지 봅니다. 정당한 삭제도 걸리므로 게이트가 아니라 리포트입니다.
  ```bash
  python3 .claude/vway-kit/scripts/doc_invariants.py --changed            # 바뀐 .md 전체
  python3 .claude/vway-kit/scripts/doc_invariants.py --changed docs/a.md  # 범위 축소
  ```
- **문체** — 마커 전에 이 변경이 건드린 파일 전체를(직접 고친 파일만이 아니라) `prose-review` 로
  산문 규칙과 대조합니다. 인자 없는 `prose-review` 는 변경 파일을 `doc_style_check.py --scope` 로
  프로젝트 문체 범위에 좁힙니다 — 설정의 `paths`/`exclude`, 꺼졌거나 없으면 기본 범위 — 그래서
  프로젝트가 뺀 파일은 고치지 않습니다.

## 문체 규율

기준은 [`rules/doc-style.md`](../../rules/doc-style.md) — 개조식, 변경 이력 금지, 한 사실 한 곳.
기계가 판정하는 절반은 `doc_style_check.py` 가 봅니다:

```bash
python3 .claude/vway-kit/scripts/doc_style_check.py --lint docs/a.md   # 지목한 파일
python3 .claude/vway-kit/scripts/doc_style_check.py --lint-config      # 설정 범위 전체
```

잡는 것 — 변경 이력(`HIST`), 산문 속 커밋 sha(`SHA`), 계획 포인터·체크박스(`PLAN`), 군더더기
(`FILLER`), 한글 서술형 종결(`ENDING`), 줄 번호 앵커(`ANCHOR`), 변경 필드(`META`), 불완전한 함정
박스(`TRAP`). 경고만: 헤지된 크기(`CLAIM`)와 100자 초과(`LONG`).

범위는 `vdev-config.doc_style`([설정](configuration.md#예시))이고, 커밋 게이트와 CI 가 **같은 함수**로
읽습니다. 가상환경·벤더 트리(`node_modules`·`.venv`·`venv`·`site-packages`·`.tox`·`.nox`·`vendor`·
`third_party`·`.git`)는 `paths` 와 무관하게 **언제나** 빠집니다. GitHub 이슈·PR 템플릿
(`pull_request_template.md`·`issue_template.md`, `PULL_REQUEST_TEMPLATE/`·`ISSUE_TEMPLATE/` 아래
전부, 대소문자 무관)도 늘 빠집니다 — 체크리스트가 기여자가 채우는 양식이라 고칠 편집이 없습니다.
`build`·`dist`·`env`·`target` 은 손으로 쓴 소스일 수도 있어 자동으로 빠지지 않으니, 생성물이면
`exclude` 에 적으세요.
