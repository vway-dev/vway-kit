"""하네스 스캐폴드 테스트가 공유하는 헬퍼 — 컴포넌트·플랜·설정 쓰기."""

from pathlib import Path


def _write_component(path: Path, name: str, desc: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\nbody\n", encoding="utf-8")


def _baseline_entry(extra_body=""):
    anchors = "".join(
        f"<!-- rule:{k} -->\n"
        for k in ("karpathy", "dry-constants", "version-pinning", "security", "reuse-first")
    )
    return {
        "path": "CLAUDE.md",
        "action": "marker_upsert",
        "marker_id": "harness:baseline",
        "content": anchors + extra_body,
    }


def _conv_entry(content):
    return {"path": ".claude/rules/x-conventions.md", "action": "create", "content": content}


def _lensed(*pairs):  # (lens, body) → BP 섹션 텍스트
    s = "## 베스트 프랙티스\n"
    for lens, body in pairs:
        b = f"code-style:lens:react:{lens}"
        s += f"<!-- {b} BEGIN (managed) -->\n{body}\n<!-- {b} END -->\n"
    return s


# ---------------------------------------------------------------- wiki-id parity


def _wiki_plan(path: str, content: str) -> dict:
    return {"files": [{"path": path, "action": "create", "content": content}]}


def _write_wiki_config(root: Path, body: str) -> None:
    cfg = root / ".claude" / "vway-kit" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "vdev-config.yaml").write_text(body, encoding="utf-8")
