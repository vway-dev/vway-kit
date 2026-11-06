---
name: prose-review
description: "Use when comments, docstrings or documents need checking against the prose rules — before writing them, or to clean up what is already there. The doc-sync gate calls it."
argument-hint: "[경로… | 비우면 변경된 파일]"
---

# prose-review

산문 규칙의 절반은 패턴이고 절반은 판단임.
[`doc-style.md`](../../rules/doc-style.md) 가 규칙이고, 이 스킬은 지목한 파일에 그 양쪽을
다 돌림.

위반은 **사용자가 쓰고 있는 언어로** 보고하고, 박스 키 뒤에 오는 것도 같은 언어로 씀. 키 셋
— `CRITICAL TRAP:` · `Trigger:` · `Symptom:` — 만은 프로젝트를 가리지 않고 리터럴로 둠:
검사기가 그것을 파싱함.

## 1. 기계가 판정하는 절반

`$ARGUMENTS` 가 경로를 공백으로 나열함. 비어 있으면 호출자가 주지 않은 것 — 변경된 파일을
가져와 프로젝트 문체 범위(설정의 `paths`·`exclude`, `doc_style` 이 꺼졌거나 없으면 기본 범위)로
좁힘 — 프로젝트가 뺀 파일은 고치지 않음. 경로는 NUL 로 끊어 넘김 — 공백 든 경로가 낱말로
쪼개지면 진짜 파일은 빠지고 없는 경로가 찍힘. 저장소 루트에서 돌림(루트 상대 경로를 찍음):

```bash
{ git -c core.quotePath=false diff -z --name-only HEAD
  git -c core.quotePath=false ls-files -z --others --exclude-standard
} | xargs -0 python3 .claude/vway-kit/scripts/doc_style_check.py --scope
```

`unrecognized arguments` 오류(xargs 를 거쳐 비0 종료)면 호스트 사본이 `--scope` 이전 판이고, 스크립트가 없는
저장소는 돌릴 것이 없음: 그렇다고 말하고 `/vdev-init` 재실행을 안내한 뒤 두 `git` 목록을
좁히지 않고 씀. 실패가 남긴 빈 목록으로 계속하지 말 것.

**그 목록을 쥐고 있을 것** — 4단계가 그것을 다시 씀.

```bash
python3 .claude/vway-kit/scripts/doc_style_check.py --lint <경로들>
```

`ANCHOR` · `META` · `TRAP` · `HIST` · `SHA` · `PLAN` · `FILLER` · `ENDING` · `CLAIM` 이
여기서 판정됨. 스크립트가 없는 저장소는 이 단계를 건너뛰고 판단 절반만 함.

## 2. 사람이 판정하는 절반

어떤 패턴도 이것들엔 답을 못 냄. 경로가 담은 주석·독스트링·문단을 하나씩 읽음:

- **어떻게를 적고 있는가?** 아래 코드를 풀어 쓴 것은 무슨 값을 치르든 삭제.
- **코드가 대신 터질 수 있는가?** `assert`·검증된 경계·타입이 질 수 있는 제약을 산문으로
  적은 것은 있으면 안 되는 주석임. 더 나은 문장이 아니라 **그 검사**를 제안할 것.
- **자명한가?** 자기 식별자를 되풀이하는 주석은 잡음.
- **숫자가 측정인가 계약인가?** 둘 다 아니면 수치를 쓴 추측임 — 방향을 대신 적음.
- **더 짧아질 수 있는가?** 명사형 종결, 잇는 말 없음.

## 3. 고침

위반마다 대체안을 파일별로 묶어 보임. 사용자가 받아들인 것만 적용.

## 4. 사라진 것이 없음을 확인

1단계가 해석한 **그 목록의 `.md` 만** 돌림 — 새로 구한 변경 파일 목록이 아님. 고침 자체가
파일을 만들거나 이름을 바꿀 수 있어, 여기서 다시 구하면 이미 고친 것과 **다른 집합**을
확인하게 됨. `.md` 로 거르는 이유는 이 대조기가 마크다운 전용이기 때문 — `.py`·`.sh` 를
건네면 "저장소의 .md 가 아님" 이라는 **틀린 진단**과 함께 exit 2 로 끝남. 주석만 고친 실행은
`.md` 가 하나도 안 남는 것이 정상이고, 그때는 **이 단계를 건너뜀**: 인자 없이 부르면 변경된
`.md` 전부로 조용히 넓어져, 바로 위에서 금지한 "새로 구한 목록" 을 그대로 확인하게 됨.

```bash
python3 .claude/vway-kit/scripts/doc_invariants.py --changed <경로들 중 .md>
```

헤딩·펜스·URL·인라인 코드 스팬을 떨어뜨린 재작성은 사실을 떨어뜨린 재작성임. 되살리거나,
그 삭제가 목적이었다는 것을 리포트에 적을 것.
