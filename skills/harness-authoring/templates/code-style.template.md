<!-- 이 문서의 wiki front matter. 아래 {{…}} 를 모두 채운 뒤 이 주석 줄을 지워, 뒤따르는
     "---" 가 생성 파일의 문자 그대로의 첫 줄이 되게 한다(wiki_graph.py 는 바이트 0에서
     시작하는 front matter 만 인식 — 이 주석을 남겨두면 파일은 평범한 마크다운처럼
     무해하게 wiki 밖에 머묾). -->
---
# wiki_id: 이 파일의 출력 경로를 wiki 루트 기준으로 삼아 wiki-init 5단계와 같은 방식으로
# 기계적으로 파생한다(예: docs/code-style/python.md -> code-style.python). 멀티스택
# 프로젝트는 이 템플릿을 스택마다 복제하므로, 여기서 <stack> 을 손으로 고르면 모든
# 복제본이 문자 그대로 같은 id 에 내려앉아 충돌할 위험.
wiki_id: {{ID}}
title: <stack> code style
tags: [code-style, <stack>]
# sources 는 선택 — 이 스타일 문서가 서술하는 실제 코드 경로를 주석 해제해 나열하고,
# 해당 없으면 아래 두 줄을 지울 것.
# sources:
#   src/path/to/code.py: null
---
# {{STACK_LABEL}} 코드 스타일

> {{LANGUAGE}} + {{FRAMEWORK_OR_PLATFORM}}. **코드 스니펫 없이** 규율을 산문으로 서술. 출처: {{SOURCES}}

## 네이밍 · 포맷 · 임포트
{{STYLE_RULES}}

## 베스트 프랙티스 (관점 렌즈별 — 적용 렌즈만, 9-2)
<!-- authoring: 적용 렌즈마다 아래 형식의 관리 블록을 9-1 순서로 둔다(scan-lenses 갭 대상만 emit).
  <stack> = 이 문서 파일명 stem({{STACK}}). 블록 안은 필요시 축별 `#### <axis>` 소섹션(예: #### error-handling)
  으로 세분화 — 축 앵커로 룰이 링크. 각 항목 1-2줄 + 출처. 블록 밖 사용자 자유 메모는 보존됨.
  경계(중복 금지): 성능 검증도구 → docs/verification/performance.md, 계층 횡단 구체 계약 → docs/sds 링크
  (블록 안 복제 금지). 순서(9-1): 정확성 · 운영 · 보안 · 성능 · UX/상호작용 · 접근성 · 국제화 ·
  유지보수성 · 계층 횡단. -->
<!-- code-style:lens:{{STACK}}:correctness BEGIN (managed by /harness-init — edits inside are overwritten) -->
### 정확성
{{LENS_CORRECTNESS}}  <!-- 에러 처리·입력 검증·엣지 케이스 등 축별 소섹션. 각 1-2줄+출처. -->
<!-- code-style:lens:{{STACK}}:correctness END -->

<!-- code-style:lens:{{STACK}}:performance BEGIN (managed by /harness-init — edits inside are overwritten) -->
### 성능
{{LENS_PERFORMANCE}}  <!-- N+1 회피·캐싱 등 코딩 패턴. 검증도구는 verification 링크. 각 1-2줄+출처. -->
<!-- code-style:lens:{{STACK}}:performance END -->

<!-- 나머지 렌즈(운영·보안·UX/상호작용·접근성·국제화·유지보수성·계층 횡단)도 위와 동일 형식 —
  스택에 실재하는 렌즈만(9-2) 9-1 순서 자리에 삽입. -->

## 안티패턴 (회피)
{{ANTI_PATTERNS}}
- **바퀴 재발명**: 무료·상용가능 기성 솔루션(공식 이미지·표준 라이브러리·OSS)이 있으면 직접 구현 대신 사용.

- **주석 속 일회성 플랜 인덱스**: 코드 주석에서 일회성 스펙/플랜 인덱스(`Step 3`, `Task 11`, `§2.1`) 참조 금지 — 주석은 의도를 설명하는 것이지, 시간이 지나면 낡아 대상을 잃는 계획 산출물이 아님.

## 툴체인 / 설정
{{TOOLCHAIN_CONFIG}}  <!-- 빌드·번들·타입체크·린트·테스트를 한 세트로. 감지된 버전의 공식 스캐폴더 출력 기준. 출처 표기. -->

## reuse 후보 (무료·상용가능)
{{REUSE_EXAMPLES}}
