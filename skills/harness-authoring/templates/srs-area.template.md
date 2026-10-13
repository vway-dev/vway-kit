<!-- 이 문서의 wiki front matter. 아래 {{…}} 를 모두 채운 뒤 이 주석 줄을 지워, 뒤따르는
     "---" 가 생성 파일의 문자 그대로의 첫 줄이 되게 한다(wiki_graph.py 는 바이트 0에서
     시작하는 front matter 만 인식 — 이 주석을 남겨두면 파일은 평범한 마크다운처럼
     무해하게 wiki 밖에 머묾). -->
---
# wiki_id: 이 파일의 출력 경로를 wiki 루트 기준으로 삼아 wiki-init 5단계와 같은 방식으로
# 기계적으로 파생한다(예: docs/srs/payment.md -> srs.payment). 슬러그를 손으로 고르지
# 금지 — 이 템플릿은 요구사항 영역마다 한 번씩 복제되고, 손으로 고른 값이 복제본들
# 에서 반복되면 id 충돌.
wiki_id: {{ID}}
title: <requirement area>
tags: [srs]
# related 가 이 파일을 orphan 목록 밖으로 꺼냄 — wiki_graph.py 는 인덱스에서 노드로
# 걸어 들어가므로, 아무도 가리키지 않는 영역 파일은 아무리 완성돼 있어도 닿지 않음.
# 대상은 SRS 인덱스 자신의 기계적 id — 기본 wiki 루트에서 docs/srs/README.md -> srs.readme
# 이지만 루트가 다르면 철자도 달라지므로, 풀기 전에
# `wiki_graph.py --derive-id docs/srs/README.md` 로 이 호스트의 값을 확인할 것.
# 그 README 가 자기 front matter 를 갖게 된 뒤에 주석을 풀 것 — 노드가 아닌 문서로 가는
# 엣지는 dangling 이고, orphan 이 경고에 그치는 자리에서 dangling 은 커밋을 막음.
# related:
#   - srs.readme
# sources 는 선택 — 요구사항이 특정 코드 경로에 대응하는 일은 드묾. 정말 그럴 때만
# 주석을 풀고, 아니면 지운 채로 둘 것.
# sources:
#   src/path/to/code.py: null
---
# {{AREA_TITLE}} 기능 요구사항

> [SRS](README.md) 의 요구사항 영역 하나. 공통 절 — 목적·목표·용어집·사용자와 역할·고객 요구·
> 비기능 요구사항·제약 — 은 그쪽에 있음.

## 5. 기능 요구사항
<!-- 계층 분류(고정 스키마): 도메인(1차) > 사용자권한/하위영역(2차) > 개별 FR(3차).
     2차축이 **역할일 때만** role 앵커로 링크 — 하위영역은 평문. 억지 링크는 없는 역할을
     만듦. 각 FR 은 측정 가능한 수용 기준을 가짐.
     설명·수용 기준 둘 다 사용자나 비즈니스가 관찰하는 것 — 누른 버튼·보인 화면·청구된 금액 — 으로
     쓰고, 그 뒤의 구현은 쓰지 않음(구현은 SDS 몫). 모든 대상은 README 용어집의 용어로만 부름;
     용어집에 없는 용어는 먼저 거기에 추가. -->

### 5.1 {{DOMAIN_A}}
#### 5.1.1 {{ROLE_OR_SUBAREA_A}}
{{FR_LIST_A}}
<!-- 형식 —
     - <a id="fr-payment-001"></a>**FR-PAYMENT-001** [P0/P1/P2] (← [C-003](README.md#c-003))
       회원이 [간편결제](README.md#term-001)로 결제함. 수용 기준: 결제 버튼을 누른 뒤 3초 안에
       주문 완료 화면이 보임.
     영역 접두는 이 파일 stem 의 대문자이고, 번호는
     `srs_check.py --next-id <이 파일> --kind FR` 가 냄. 백참조가 파일을 넘는 것은 고객
     요구가 README 에 살기 때문 — 출처 고객 요구가 없으면 생략. 모호·미상이면 수용 기준에
     "확인 필요"를 적음. -->
