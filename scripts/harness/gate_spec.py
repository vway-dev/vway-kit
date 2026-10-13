"""커밋 게이트를 한 번만 적어 두는 곳 — 하네스 패키지마다 이것에서 자기 훅 엔트리를 렌더함.

- 값이 바뀌면 그 하네스를 쓰는 모든 호스트의 훅이 `/vdev-init` 재실행 때 "보정" 으로 다시
  쓰이므로, 렌더 결과는 `tests/harnesses/` 가 리터럴로 고정함.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from _vway_paths import SCRIPTS_DIR
except ImportError:
    from scripts._vway_paths import SCRIPTS_DIR


@dataclass(frozen=True)
class GateSpec:
    runner_rel: str
    timeout: int
    status: str


GATE = GateSpec(
    runner_rel=f"{SCRIPTS_DIR}/precommit-runner.sh",
    timeout=600,
    status="vway-kit: vdev 게이트 + 테스트 검사 중…",
)
