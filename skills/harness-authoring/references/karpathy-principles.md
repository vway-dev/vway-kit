# Karpathy CLAUDE.md 원칙 (주입 블록)

> 구현 시 실제 원전을 fetch해 최신 문구로 갱신할 것(추측 금지). 원전: Forrest Chang의
> `andrej-karpathy-skills`(Karpathy의 LLM 코딩 관찰 distill). 아래는 검증된 4원칙 요지.

1. **Think Before Coding** — 가정을 명시, 모호하면 추측 말고 질문.
   복수 해석이 가능하면 임의 선택 말고 제시. 더 단순한 길이 있으면 반박.
2. **Simplicity First** — 요청한 것만, 최소 코드로. 요청 안 한 추상화·기능·설정·
   과방어 코드 금지. 50줄로 될 일을 200줄로 쓰기 금지.
3. **Surgical Changes** — 변경된 모든 줄이 요청에 직결. 건드릴 것만
   건드리고, 내가 만든 것만 정리.
4. **Goal-Driven Execution** — 명령을 검증 가능한 성공기준으로 바꿈. 다단계 작업은
   검증 체크포인트가 있는 짧은 계획을 먼저 세움.
