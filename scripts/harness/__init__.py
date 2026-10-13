"""커밋 게이트를 심는 에이전트 하네스의 레지스트리 — 하네스별 설치 패키지를 찾는 입구.

- `KNOWN` 은 이름으로 알아보는 하네스, `SUPPORTED` 는 그중 설치 코드가 있는 것.
  알지만 지원하지 않는 이름(antigravity)은 오타와 구분해 `NotImplementedError` 로 답함.
- 설치 모듈은 `harness.<이름>.install` 을 먼저 찾음 — `vdev_init_setup.py` 를 스크립트로
  돌리면 `scripts/` 가 `sys.path` 에 있어 형제 import 가 기본이고, 패키지(테스트)에서는
  `scripts.harness.<이름>.install` 로 떨어짐.
"""

from __future__ import annotations

import importlib

KNOWN = ("claude", "codex", "antigravity")
SUPPORTED = ("claude", "codex")


def installer(name: str):
    if name not in KNOWN:
        raise ValueError(f"unknown harness: {name}")
    if name not in SUPPORTED:
        raise NotImplementedError(f"harness not supported yet: {name}")
    try:
        return importlib.import_module(f"harness.{name}.install")
    except ImportError:
        return importlib.import_module(f"scripts.harness.{name}.install")
