"""ALM 계층 테스트가 공유하는 것 — 픽스처 config 와 그 쓰기."""

from pathlib import Path

from scripts.alm_layers import resolve_layers


def write_config(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "vdev-config.yaml"
    p.write_text(body, encoding="utf-8")
    return p


CONFIG = """
alm:
  recoble:
    default: dev3
    spaces:
      dev3:
        workboard: "RAS 작업"
        layers:
          requirement:
            workboard: "요구사항"
          design:
            workboard: "설계"
            derives_from: requirement
"""


def resolve(tmp_path: Path, layers_yaml: str) -> dict:
    body = (
        "alm:\n  recoble:\n    default: dev3\n    spaces:\n      dev3:\n"
        "        workboard: board\n        layers:\n" + layers_yaml
    )
    return resolve_layers(write_config(tmp_path, body), None, tmp_path, tmp_path)
