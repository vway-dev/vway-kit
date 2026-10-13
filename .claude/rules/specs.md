---
paths:
  - "vdev-tiers.yaml"
  - "vdev-config.example.yaml"
  - "hooks/*.sh"
  - "agents/*.md"
  - "skills/vdev/**/*"
  - "skills/vdev-init/**/*"
  - "skills/commit/**/*"
  - "skills/release-commit/**/*"
  - "skills/harness-init/**/*"
  - "skills/harness-authoring/**/*"
  - "skills/wiki-init/**/*"
  - "skills/doc-sync/**/*"
  - "skills/alm-docs/**/*"
  - "skills/prose-review/**/*"
  - "scripts/vdev_gate_check.py"
  - "scripts/_vway_paths.py"
  - "scripts/precommit-runner.sh"
  - "scripts/wiki_graph.py"
  - "scripts/doc_style_check.py"
  - "scripts/doc_invariants.py"
  - "scripts/harness_scaffold.py"
  - "scripts/vdev_init_setup.py"
  - "scripts/srs_check.py"
  - "scripts/alm_*.py"
  - "scripts/handoff_resolve.py"
  - ".github/workflows/doc-style.yml"
  - ".github/workflows/release.yml"
  - "github/release.*.yml"
---

# 지금 편집하는 파일 뒤에 선 스펙

이 파일을 끌어온 파일을 고치기 전에 그 행의 스펙을 읽을 것 — 그 파일이 **구현하는 명세**임.
일곱 중 둘(risk-tiers 전문·doc-style 요약)은 훅이 매 세션 주입하므로 이미 컨텍스트에 있고, 그
행이 하는 일은 **어느 룰이 이 파일의 스펙인지 지목**하는 것뿐임. 나머지 다섯은 세션에
없으므로 링크를 따라가야 함. 여기서 `@` 로 임포트하지 않는 이유도 같음 — 트리거와 무관하게
세션 시작에 그 바이트가 실림.

| 편집하는 파일 | 그 스펙 |
|---|---|
| `vdev-tiers.yaml` · `skills/vdev` · `hooks/inject-risk-tiers.sh` · `scripts/vdev_gate_check.py` | [`risk-tiers.md`](../../rules/risk-tiers.md) |
| `scripts/precommit-runner.sh` · `scripts/wiki_graph.py` · `scripts/doc_style_check.py` · `scripts/_vway_paths.py` · `hooks/invalidate-gate-markers.sh` · `vdev-config.example.yaml` · `skills/vdev-init` · `scripts/vdev_init_setup.py` · `skills/wiki-init` · `skills/doc-sync` · `skills/alm-docs` | [`gate-mechanics.md`](../../rules/gate-mechanics.md) |
| `scripts/vdev_gate_check.py` 의 merge 경로 · `scripts/_vway_paths.py` · `vdev-tiers.yaml` 의 `merge_strategy` | [`merge-strategy.md`](../../rules/merge-strategy.md) |
| `skills/commit` · `skills/release-commit` | [`commit-discipline.md`](../../rules/commit-discipline.md) |
| `skills/release-commit` · `.github/workflows/release.yml` · 릴리스 워크플로 템플릿 | [`promotion.md`](../../rules/promotion.md) |
| `skills/harness-init` · `skills/harness-authoring` · `agents/` · `scripts/harness_scaffold.py` · `scripts/srs_check.py` | [`harness-rules.md`](../../rules/harness-rules.md) |
| `scripts/doc_style_check.py` · `scripts/doc_invariants.py` · `skills/prose-review` · `hooks/inject-risk-tiers.sh` 의 doc-style 블록 · `.github/workflows/doc-style.yml` | [`doc-style.md`](../../rules/doc-style.md) |

ALM 쪽은 `rules/` 가 아니라 스킬 문서가 스펙임 — `scripts/alm_*.py` 와
`scripts/handoff_resolve.py` 를 고치기 전에 [CLAUDE.md](../CLAUDE.md) Architecture 의 ALM
절이 지목하는 references 를 읽을 것(상태 전이·전파·계층·서버 해석이 각각 다른 파일에 있음).

이 중 무엇도 **이 세션의 워크플로를 정하지 않음**: 그것은 설치된 vway-kit 이 SessionStart 에
주입하는 것임. 둘이 어긋나면 편집 대상 파일은 `rules/` 를 따름.
