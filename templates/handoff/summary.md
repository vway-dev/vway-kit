<!--
  handoff: summary 템플릿. /task-sync 의 AI 요약이 쓰는 **유일한** 구조 —
  Teamer 필드(item_content·colXX)도 Recoble 댓글·본문·customFields 도 이 한 파일을
  씀. handoff_resolve.py 가 template_path 로 지목함. 호스트가
  .claude/vway-kit/templates/handoff/ 아래 같은 이름을 두면 그것이 이 파일을 대신함
  (/vdev-init 이 선언된 종류의 이 사본을 거기 시드하므로 고칠 파일이 이미 놓여 있음).

  AI 는 task 문서를 읽고 아래 3섹션 구조로 요약 Markdown 을 생성함.

  규칙:
  - 독자: Implementation 은 개발자, Verification·Notes 는 비개발자. 규칙 SSOT 는
    skills/task-import/references/item-body.md.
  - Verification·Notes 에는 코드 식별자·파일 경로·커밋 sha·명령어·테스트 파일 이름을 쓰지 않음.
    method 이름도 "자동 테스트"·"화면 확인" 처럼 사람이 아는 말로, 결과는 관찰한 동작으로.
  - 저장소 문서·경로를 근거로 링크하지 않음 — 필요한 내용을 항목에 풀어 씀.
  - 최상위 번호 목록. 섹션 고정 순서: Implementation, Verification, Notes.
  - 섹션 라벨은 항상 영어. 본문은 task 문서 언어를 따른다(한글 task → 한글 본문).
  - Implementation: area 를 번호 항목, 구체 변경을 그 아래 불릿.
  - Verification: method 를 번호 항목, 결과를 그 아래 번호 항목(번호 증거).
  - Notes: caveat 의 평평한 번호 목록. 없으면 섹션 통째로 생략.
  - Worklog: task-sync 0단계 Worklog 의 `enabled: true` 일 때만. 값은 worklog.py 출력 그대로,
    번호는 Notes 다음(Notes 가 없으면 3). `active` 가 없으면 `AI Agent 활동` 줄 생략.
  - atomic 항목: 한 항목 = 한 사실. ':' '→' '/' ',' ';' '+' 로 여러 사실을 묶지 말 것.
  - self-contained 항목: 앞 항목 없이도 읽히게. '이/그/이를/따라서' 로 시작 금지.
  - area/method/Notes 라인은 이름만. 설명·수치·before/after 는 별도 항목으로.
  - 개발 과정(TDD 반복·디버깅 이력·dev-server 왕복) 서술 금지 — 최종 형태만.
  - 최상위 task 제목 포함 금지(ALM 항목 화면이 제목을 별도 렌더).
  - Summarize, do not enumerate: Implementation area 당 대표 bullet 2–4개. 모든 커밋
    변경 1:1 매핑 금지. 한 결정의 명백한 부분 단계는 merge. 한 변경이 다른 변경의 자동
    결과면 상위 요약만 유지. 요약이지 code-review 체크리스트 아님.
  - Multi-fact rule: baseline 수치와 신규 수치는 두 사실 → 두 항목. 증상과 fix 는 두
    사실 → 두 항목.
  - HTML 태그를 쓰지 말 것 — 대상이 무엇이든 본문은 Markdown 임. 작성자 표기가
    필요하면 맨 끝에 `_Author: {author} ({YYYY-MM-DD})_` 한 줄, author 가 비면 그
    줄도 생략.
-->
1. Implementation
   1. [Area name — bare noun phrase, no colon, no detail]
      - [One atomic change]
      - [Another atomic change]
   2. [Another area name]
      - [One atomic change]
      - [Another atomic change]
2. Verification
   1. [Verification method name]
      1. [One atomic observed result]
      2. [Another atomic observed result]
   2. [Another verification method]
      1. [One atomic observed result]
3. Notes
   1. [One atomic caveat]
   2. [Another atomic caveat]
4. Worklog
   1. 착수 [started]
   2. 완료 [completed]
   3. AI Agent 활동 [active]
