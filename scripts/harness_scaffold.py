"""harness-init 스캐폴드 생성 엔진 — /harness-init 이 호출.
detect·scan-lenses·validate·migrate·apply·doctor 로 CLAUDE.md·rules·agents·기술문서 골격을
프로젝트 프레임워크에 맞춰 생성/검증/마이그레이션. 프로젝트 비종속.
커밋 게이트가 아니므로 강제 차단과 무관 — 예외는 `apply` 의 경로 봉쇄뿐(진단이 아니라
쓰기라, root 밖·증거 디렉터리로 나가는 엔트리는 거부).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

try:
    import yaml  # PyYAML (repo 의존성)
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# 인코딩 방어는 공용 SSOT(_vway_paths)에서 가져온다(중복 정의 금지). harness_scaffold 는
# 플러그인 위치에서 실행되므로 형제 import 가 기본이고, 패키지(테스트)에서는 scripts._vway_paths.
try:
    from _vway_paths import force_utf8_io
except ImportError:
    from scripts._vway_paths import force_utf8_io

try:
    from wiki_graph import DEFECT_PREFIX, _wiki_root_hint, derive_wiki_id
except ImportError:
    from scripts.wiki_graph import DEFECT_PREFIX, _wiki_root_hint, derive_wiki_id

# _HEADING_RE·_SETEXT_RE·_slugify 는 이 모듈 본문에서 안 쓰임 — `harness_scaffold.<이름>` 이
# 유효한 속성 경로로 남게 재노출.
try:
    from _md_anchors import (
        _HEADING_RE,  # noqa: F401
        _SETEXT_RE,  # noqa: F401
        _has_anchor,
        _slugify,  # noqa: F401
        _strip_code,
        _strip_frontmatter,
    )
except ImportError:
    from scripts._md_anchors import (
        _HEADING_RE,  # noqa: F401
        _SETEXT_RE,  # noqa: F401
        _has_anchor,
        _slugify,  # noqa: F401
        _strip_code,
        _strip_frontmatter,
    )

VENDOR_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
    "vendor",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
}
SOURCE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".swift",
    ".scala",
    ".vue",
    ".svelte",
}
# 의존성 키 → 프레임워크 라벨
FRAMEWORK_SIGNATURES = {
    "next": "next.js",
    "react": "react",
    "vue": "vue",
    "nuxt": "nuxt",
    "svelte": "svelte",
    "@angular/core": "angular",
    "express": "express",
    "nestjs": "nestjs",
    "@nestjs/core": "nestjs",
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
}


def _walk_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in VENDOR_DIRS]
        for fn in filenames:
            yield Path(dirpath) / fn


def detect_state(root: Path) -> str:
    for f in _walk_files(root):
        if f.suffix in SOURCE_EXTS:
            return "brownfield"
    return "greenfield"


def _norm_version(spec: str) -> str:
    # "==0.118.0", "^15.0.1", ">=2,<3" → 첫 숫자 버전만 추출(없으면 원문)
    m = re.search(r"\d+(?:\.\d+)*", spec or "")
    return m.group(0) if m else (spec or "").strip()


def detect_frameworks(root: Path) -> list[dict]:
    out: list[dict] = []

    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {}
            deps.update(data.get("dependencies", {}) or {})
            deps.update(data.get("devDependencies", {}) or {})
            for dep, ver in deps.items():
                label = FRAMEWORK_SIGNATURES.get(dep)
                if label:
                    out.append(
                        {
                            "name": label,
                            "version": _norm_version(str(ver)),
                            "manifest": "package.json",
                        }
                    )
        except Exception:
            pass

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
            for dep, label in FRAMEWORK_SIGNATURES.items():
                esc = re.escape(dep)
                # PEP 621: dependencies = ["fastapi==0.118.0"]  (이름이 따옴표 안)
                m = re.search(rf"['\"]{esc}\s*([=<>!~^]*\s*[\d.]+)?['\"]", text)
                if not m:
                    # Poetry: [tool.poetry.dependencies] 의 `fastapi = "^0.118.0"` (이름이 키)
                    m = re.search(rf"(?m)^\s*{esc}\s*=\s*['\"]([^'\"]*)['\"]", text)
                if m:
                    out.append(
                        {
                            "name": label,
                            "version": _norm_version(m.group(1) or ""),
                            "manifest": "pyproject.toml",
                        }
                    )
        except Exception:
            pass

    reqs = root / "requirements.txt"
    if reqs.is_file():
        try:
            text = reqs.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                name_m = re.match(r"([A-Za-z0-9_.\-]+)", stripped)
                if not name_m:
                    continue
                label = FRAMEWORK_SIGNATURES.get(name_m.group(1).lower())
                if label:
                    ver_m = re.search(r"==\s*([\d.]+)", stripped)
                    out.append(
                        {
                            "name": label,
                            "version": ver_m.group(1) if ver_m else "",
                            "manifest": "requirements.txt",
                        }
                    )
        except Exception:
            pass

    gomod = root / "go.mod"
    if gomod.is_file():
        out.append({"name": "go", "version": "", "manifest": "go.mod"})

    # 나머지 SOURCE_EXTS 언어(딥 프레임워크 서명 대신 매니페스트 존재만 신호 —
    # 세부 프레임워크는 harness-init Step 1 인터뷰가 항상 확인/보완).
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        out.append({"name": "rust", "version": "", "manifest": "Cargo.toml"})

    if (root / "pom.xml").is_file():
        out.append({"name": "java", "version": "", "manifest": "pom.xml"})
    else:
        gradle = next(
            (root / n for n in ("build.gradle.kts", "build.gradle") if (root / n).is_file()), None
        )
        if gradle is not None:
            label = "kotlin" if gradle.suffix == ".kts" else "java"
            out.append({"name": label, "version": "", "manifest": gradle.name})

    if (root / "Gemfile").is_file():
        out.append({"name": "ruby", "version": "", "manifest": "Gemfile"})

    if (root / "composer.json").is_file():
        out.append({"name": "php", "version": "", "manifest": "composer.json"})

    if (root / "Package.swift").is_file():
        out.append({"name": "swift", "version": "", "manifest": "Package.swift"})

    dotnet_manifest = next(iter(sorted(root.glob("*.sln")) + sorted(root.glob("*.csproj"))), None)
    if dotnet_manifest is not None:
        out.append({"name": "dotnet", "version": "", "manifest": dotnet_manifest.name})

    cpp_names = ("CMakeLists.txt", "vcpkg.json", "conanfile.txt")
    cpp_manifest = next((root / n for n in cpp_names if (root / n).is_file()), None)
    if cpp_manifest is not None:
        out.append({"name": "cpp", "version": "", "manifest": cpp_manifest.name})

    # 같은 프레임워크를 가리키는 의존성이 둘 이상이면 name 기준 dedup(첫 등장 유지)
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in out:
        if item["name"] not in seen:
            seen.add(item["name"])
            deduped.append(item)
    return deduped


def _parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    if yaml is not None:
        try:
            data = yaml.safe_load(block) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    # 폴백(yaml 부재): name/description 라인 파싱 + 블록 스칼라(>, |) 멀티라인 수집
    out: dict = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        mm = re.match(r"\s*(name|description)\s*:\s*(.*?)\s*$", lines[i])
        if not mm:
            i += 1
            continue
        key, val = mm.group(1), mm.group(2).strip()
        if val in (">", "|", ">-", "|-", ">+", "|+"):
            collected: list[str] = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                collected.append(lines[i].strip())
                i += 1
            out[key] = " ".join(c for c in collected if c)
            continue
        out[key] = val.strip("'\"")
        i += 1
    return out


def _read_frontmatter(md_path: Path) -> dict:
    try:
        return _parse_frontmatter(md_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _component_entry(md_path: Path) -> dict:
    fm = _read_frontmatter(md_path)
    return {
        "name": fm.get("name", ""),
        "description": fm.get("description", ""),
        "path": str(md_path),
    }


def scan_components(claude_dir: Path) -> dict:
    result: dict = {"skills": [], "commands": [], "agents": []}
    cmd_dir = claude_dir / "commands"
    if cmd_dir.is_dir():
        result["commands"] = [_component_entry(p) for p in sorted(cmd_dir.glob("*.md"))]
    agt_dir = claude_dir / "agents"
    if agt_dir.is_dir():
        result["agents"] = [_component_entry(p) for p in sorted(agt_dir.glob("*.md"))]
    skl_dir = claude_dir / "skills"
    if skl_dir.is_dir():
        result["skills"] = [_component_entry(p) for p in sorted(skl_dir.glob("*/SKILL.md"))]
    return result


def _marker_begin(marker_id: str) -> str:
    return f"<!-- {marker_id} BEGIN (managed by /harness-init — edits inside are overwritten) -->"


def _marker_end(marker_id: str) -> str:
    return f"<!-- {marker_id} END -->"


def upsert_marker_block(path: Path, marker_id: str, body: str) -> str:
    begin, end = _marker_begin(marker_id), _marker_end(marker_id)
    block = f"{begin}\n{body.rstrip()}\n{end}\n"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(block, encoding="utf-8")
        return "created"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
    if pattern.search(text):
        new_text = pattern.sub(block, text, count=1)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
        return "replaced"
    if begin in text:
        raise ValueError(
            f"corrupt managed block: '{marker_id}' has BEGIN without matching END in {path}"
        )
    sep = "" if text.endswith("\n") else "\n"
    path.write_text(text + sep + "\n" + block, encoding="utf-8")
    return "inserted"


# ── 품질 렌즈(harness-rules 9-1). marker_id·insert 순서의 SSOT. ──
LENS_KEYS = (
    "correctness",
    "operational",
    "security",
    "performance",
    "ux",
    "a11y",
    "i18n",
    "maintainability",
    "cross-cutting",
)
_LENS_BEGIN_RE = re.compile(r"code-style:lens:(?P<stack>[^\s:]+):(?P<lens>[^\s:]+)\s+BEGIN")
_LENS_END_RE = re.compile(r"code-style:lens:(?P<stack>[^\s:]+):(?P<lens>[^\s:]+)\s+END")
# 베스트 프랙티스 섹션 헤딩(접두 매칭 — 한글/영문). 행 전체.
_BP_HEADING_RE = re.compile(r"^##[ \t]+(?:베스트 프랙티스|Best Practices).*$", re.MULTILINE)


def _lens_marker_id(stack: str, lens: str) -> str:
    return f"code-style:lens:{stack}:{lens}"


def classify_code_style_doc(text: str, stack: str) -> dict:
    """기존 code-style 문서를 3분류하고 present 렌즈를 마커로 집계.

    - "lensed": 이 스택의 `code-style:lens:<stack>:*` BEGIN 마커가 하나 이상.
    - "flat": 베스트 프랙티스 헤딩은 있으나 이 스택 렌즈 마커 없음(마이그레이션 대상).
    - "nonstandard": 베스트 프랙티스 헤딩 자체가 없음(스킵+경고). 파일 부재는 호출자가 처리.
    present 는 LENS_KEYS 순서로 정규화(결정성).
    """
    seen = {
        m.group("lens")
        for m in _LENS_BEGIN_RE.finditer(text)
        if m.group("stack") == stack and m.group("lens") in LENS_KEYS
    }
    present = [k for k in LENS_KEYS if k in seen]
    if present:
        return {"state": "lensed", "present": present}
    if _BP_HEADING_RE.search(text):
        return {"state": "flat", "present": []}
    return {"state": "nonstandard", "present": []}


def upsert_lens_block(text: str, stack: str, lens: str, body: str) -> str:
    """렌즈 블록 하나를 9-1(LENS_KEYS) 순서 자리에 upsert.

    마커 있으면 그 블록 교체, 없으면 순서 위치에 insert(파일 끝 append 아님).
    BEGIN 만 있고 END 없음 → ValueError. 베스트 프랙티스 헤딩 없음 → ValueError.
    """
    mid = _lens_marker_id(stack, lens)
    block = f"{_marker_begin(mid)}\n{body.rstrip()}\n{_marker_end(mid)}\n"
    # 검색은 마커 id + BEGIN/END 만으로(주석 문구 드리프트에 관용적) — 신규 쓰기만 정본 문구 사용.
    begin_re = re.compile(r"<!--\s*" + re.escape(mid) + r"\s+BEGIN[^\n]*-->")
    end_re = re.compile(r"<!--\s*" + re.escape(mid) + r"\s+END[^\n]*-->")
    pattern = re.compile(begin_re.pattern + r".*?" + end_re.pattern + r"\n?", re.DOTALL)
    if pattern.search(text):
        return pattern.sub(block, text, count=1)
    if begin_re.search(text):
        raise ValueError(f"corrupt lens block: '{mid}' BEGIN without matching END")
    lens_idx = LENS_KEYS.index(lens)
    lines = text.splitlines(keepends=True)
    before_line = None  # 순서상 뒤 형제 BEGIN(그 앞에 삽입)
    after_line = None  # 마지막 형제 END 다음(그 뒤에 삽입)
    for i, line in enumerate(lines):
        bm = _LENS_BEGIN_RE.search(line)
        if bm and bm.group("stack") == stack and bm.group("lens") in LENS_KEYS:
            if LENS_KEYS.index(bm.group("lens")) > lens_idx and before_line is None:
                before_line = i
        em = _LENS_END_RE.search(line)
        if em and em.group("stack") == stack and em.group("lens") in LENS_KEYS:
            after_line = i + 1
    if before_line is not None:
        lines.insert(before_line, block)
    elif after_line is not None:
        lines.insert(after_line, block)
    else:
        hm = _BP_HEADING_RE.search(text)
        if not hm:
            raise ValueError("no Best Practices heading for lens insert")
        heading_line_idx = text.count("\n", 0, hm.start())
        lines.insert(heading_line_idx + 1, block)
    return "".join(lines)


def replace_bp_section(text: str, blocks: str) -> str:
    """flat 레거시: `## 베스트 프랙티스` 헤딩부터 다음 `## ` 직전(또는 EOF)까지를
    렌즈 블록 구조로 대체(기존 헤딩 라인 보존). 헤딩 없으면 ValueError."""
    hm = _BP_HEADING_RE.search(text)
    if not hm:
        raise ValueError("no Best Practices heading")
    heading = text[hm.start() : hm.end()].rstrip()
    m2 = re.compile(r"^##[ \t]", re.MULTILINE).search(text, hm.end())
    end = m2.start() if m2 else len(text)
    replacement = f"{heading}\n{blocks.rstrip()}\n"
    if m2:
        replacement += "\n"
    return text[: hm.start()] + replacement + text[end:]


def scan_code_style(root: Path) -> list[dict]:
    """docs/code-style/*.md(README 제외) 를 스캔해 스택별 상태·present 렌즈 보고.

    stack = 파일명 stem(예: typescript-react.md → typescript-react). 리더가 이 출력으로
    갭(적용 렌즈 − present)을 계산해 스코핑 질문을 만듦.
    """
    out: list[dict] = []
    cs_dir = root / "docs" / "code-style"
    if not cs_dir.is_dir():
        return out
    for md in sorted(cs_dir.glob("*.md")):
        if md.name == "README.md":
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        info = classify_code_style_doc(text, md.stem)
        out.append({"stack": md.stem, "path": str(md.relative_to(root)).replace("\\", "/"), **info})
    return out


REQUIRED_RULES = ("karpathy", "dry-constants", "version-pinning", "security", "reuse-first")
BASELINE_MARKER = "harness:baseline"
# 하위 디렉터리 컴포넌트도 인식한다(.+ — 단일 세그먼트 가정 금지).
_SKILL_PATH_RE = re.compile(r"(?:^|/)\.claude/skills/.+/SKILL\.md$")
_AGENT_PATH_RE = re.compile(r"(?:^|/)\.claude/agents/.+\.md$")
# 인라인 마크다운 링크만(이미지 ![..](..) 제외 — '[' 직전 '!' 차단, 타이틀·공백 패딩 허용).
_MD_LINK_RE = re.compile(
    r"(?<!!)\[[^\]]*\]\(\s*([^)\s#]+\.md)(?:#([^)\s]*))?(?:\s+[\"'][^\")]*[\"'])?\s*\)"
)
# 앵커가 아니라 GitHub 줄 참조. `.md` 대상도 그것을 달고 옴(이 저장소 스펙이 `SKILL.md#L153`
# 을 인용).
_LINE_FRAGMENT_RE = re.compile(r"^L\d+(-L\d+)?$")
# 드라이브 접두는 구분자가 없어도 root 밖 — 경로 판정과 링크 판정이 함께 씀.
# `PureWindowsPath('D:/p') / 'C:x'` 는 `C:x`, 드라이브-상대 `C:../x.md` 도 root 를 벗어남.
_DRIVE_PREFIX_RE = re.compile(r"[a-zA-Z]:")
# gitignored 증거 디렉터리의 이름. 경로 판정은 이 **세그먼트**로 하고(대소문자 무시 —
# Windows·macOS 기본 FS 에서 `.HARNESS` 는 같은 디렉터리), 링크 판정은 아래 정규식으로.
_HARNESS_DIR_NAME = ".harness"
# 링크가 증거 경로를 가리키는지 — 어느 깊이의 상대 접두(`../../`)든 잡음.
_HARNESS_LINK_RE = re.compile(r"(?:^|/)\.harness/", re.IGNORECASE)
# Windows 8.3 단축명(`HARNES~1`) — 긴 이름의 별칭이라 이름 접기로는 정체를 알 수 없음.
_SHORT_NAME_RE = re.compile(r"~\d")
# 경로가 비었을 때 리포트에 싣는 자리표. apply 의 `rejected` 와 doctor 의 `plan_bad_paths` 가
# **같은 상수**를 써야 두 표를 대조할 수 있음(한쪽만 빈 문자열이면 같은 엔트리가 갈림).
EMPTY_PATH = "<빈 경로>"
OPS_ANCHOR_RE = re.compile(r"<!--\s*ops-conventions\s*-->")
OPS_MAX_LINES = 3
# dict.get(key, _NO_WIKI_ID) 용 sentinel: "키 없음"(wiki 노드 아님)과 "있는데 falsy"를 구분
# (dict.get(key) 만 쓰면 키 부재와 명시적 `wiki_id: null` 이 둘 다 None 이라 구별 불가).
_NO_WIKI_ID = object()


def _ops_directive_blocks(body: str) -> list[list[str]]:
    """`<!-- ops-conventions -->` 앵커 뒤의 최상위 리스트 항목(`- ...`)을 블록으로 나눔.

    각 블록 = `- ` 줄 + 빈 줄/다음 `- `/헤딩/다음 앵커 전까지의 연속 줄. 헤딩이나 다음
    앵커를 만나면 절이 끝난 것으로 봄(운영 directive 라인 수 가드의 입력).
    """
    m = OPS_ANCHOR_RE.search(body)
    if not m:
        return []
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for line in body[m.end() :].splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or OPS_ANCHOR_RE.search(line):
            break
        if line.startswith("- "):
            if cur is not None:
                blocks.append(cur)
            cur = [line]
        elif cur is not None:
            if stripped == "":
                blocks.append(cur)
                cur = None
            else:
                cur.append(line)
    if cur is not None:
        blocks.append(cur)
    return blocks


def _norm_rel(path: str) -> str:
    """plan 경로를 POSIX 정규형으로 통일(백슬래시·중복 구분자·'./' 제거).

    한쪽만 정규화하면 경로 비교가 어긋나 dead-link 오탐·커맨드 가드 우회가 생김.
    """
    if not path:
        return ""
    return os.path.normpath(path.replace("\\", "/")).replace("\\", "/")


def _rel_posix(p: Path, root: Path) -> str:
    """root 상대 POSIX 경로. root 밖이면 원문 그대로(진단이 예외로 죽지 않게)."""
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _fold_segment(seg: str) -> str:
    """경로 세그먼트를 파일시스템이 보는 형태로 접음 — 이름 비교의 유일한 자리.

    Windows 는 대소문자를 무시하고 후행 점·공백을 잘라낸 뒤 해석하므로 `.HARNESS`·
    `.harness.`·`.harness ` 가 전부 `.harness` 와 같은 디렉터리. 접기를 한 군데 모아
    `_path_problem` 과 doctor 의 stray 검사가 서로 다른 답을 못 내게 함.
    """
    return seg.lower().rstrip(" .")


def _path_problem(rel: str) -> str | None:
    """플랜 경로의 **철자**가 쓰기에 안전한가 — 안전하면 None, 아니면 사유.

    셋 다 결과가 root 밖이거나 증거 자리. 절대경로는 `root / rel` 이 pathlib 의미상
    root 를 통째로 버리고, `..` 는 걸어 나가며, `.harness` 는 gitignored 증거 디렉터리라
    산출물이 떨어지면 cleanup 이 지우거나 링크가 끊어짐. 입력은 `_norm_rel` 을 거친 값.

    철자만 봄 — 심링크로 나가는 경로는 `_escapes_root` 가 실제 위치로 따로 판정.
    """
    if not rel:
        return "빈 경로"
    # POSIX 절대(`/x`)·UNC(`\\x`)·드라이브(`C:/x`·구분자 없는 `C:x`) 전부. Path.is_absolute()
    # 는 플랫폼마다 답이 달라(윈도에서 `/x` 는 False) 혼자 두면 반대 플랫폼에서 구멍이 생김.
    if rel.startswith(("/", "\\")) or _DRIVE_PREFIX_RE.match(rel) or Path(rel).is_absolute():
        return f"절대경로 금지: {rel}"
    if rel == ".." or rel.startswith("../"):
        return f"root 밖으로 나가는 경로 금지: {rel}"
    if "\x00" in rel:
        return "널 문자 포함 경로 금지"
    # 8.3 단축명(`HARNES~1`)은 Windows 가 같은 디렉터리로 푸는 또 하나의 별칭 — 접기로는
    # 못 잡음(철자가 아예 다름). 하네스 산출물 경로에 `~N` 이 설 이유가 없으므로 통째로 막음.
    if _SHORT_NAME_RE.search(rel):
        return f"8.3 단축명 금지(다른 디렉터리의 별칭일 수 있음): {rel}"
    # 세그먼트로 봄 — 접두 문자열로 보면 끝에 선 `docs/x/.harness` 를 놓침. 비교 전에
    # **Windows 가 경로에 적용하는 정규화를 똑같이** 적용함: 대소문자 접기 + 후행 점·공백 제거.
    # 셋 중 하나라도 빠뜨리면 `.HARNESS`·`.harness.`·`.harness ` 가 같은 디렉터리를 가리키면서
    # 검사만 비껴감.
    if any(_fold_segment(seg) == _HARNESS_DIR_NAME for seg in rel.split("/")):
        return f"증거 디렉터리(.harness)에 산출물 금지: {rel}"
    return None


def _escapes_root(root: Path, target: Path) -> str | None:
    """심링크까지 편 **실제** 위치가 root 밖인가 — 철자 검사가 못 보는 한 겹.

    `docs/research` 가 root 밖을 가리키는 심링크면 경로 문자열만으로는 안전해 보임.
    없는 조상은 realpath 가 그대로 이어 붙이므로 아직 안 만든 파일도 판정됨.

    드라이브는 relpath 의 ValueError 가 아니라 **먼저 직접** 비교 — Windows 디바이스명
    (`nul`·`con`)도 그 예외를 던져, 예외만 보면 사유가 "다른 드라이브"로 거짓이 됨.
    """
    try:
        real_root = os.path.realpath(str(root))
        real_target = os.path.realpath(str(target))
    except OSError:
        return None  # 판정 불가는 철자 검사 결과에 맡김(FAIL-OPEN)
    if os.path.splitdrive(real_root)[0].lower() != os.path.splitdrive(real_target)[0].lower():
        return f"root 와 다른 드라이브·디바이스로 해석됨: {target}"
    try:
        rp = os.path.relpath(real_target, real_root)
    except ValueError:  # 드라이브 비교를 통과했는데도 계산 불가 — 정체 불명이므로 막음
        return f"실제 위치를 root 기준으로 계산 불가: {target}"
    if rp == os.pardir or rp.startswith(os.pardir + os.sep):
        return f"root 밖으로 나가는 실제 경로(심링크): {target}"
    return None


def _is_component_path(rel: str) -> bool:
    return bool(_SKILL_PATH_RE.search(rel) or _AGENT_PATH_RE.search(rel))


def _has_rule_anchor(body: str, key: str) -> bool:
    """룰 앵커 검출 — HTML 주석 공백 변형(<!--rule:x-->, <!-- rule:x  -->)에 관대."""
    return re.search(rf"<!--\s*rule:{re.escape(key)}\s*-->", body) is not None


def validate_plan(root: Path, plan: dict) -> dict:
    """생성 plan 의 결정적 구조 검증. 게이트가 아니라 진단(FAIL-OPEN)."""
    issues: list[dict] = []
    files = plan.get("files", [])
    # 경로는 비교 전 항상 정규화 — 한쪽만 정규화하면 매칭이 어긋남.
    plan_paths = {_norm_rel(e.get("path", "")) for e in files}
    disk_texts: dict[str, str | None] = {}  # 앵커 조회 읽기 캐시, None = 못 읽음
    # 아래 앵커 조회용 — **파일 전체를 쓰는** 엔트리만. 부정이 아니라 허용목록: 부분 액션의
    # `.get("content", "")` 는 빈 문자열이라 무엇을 물어도 "앵커 없음" 이라 답함. 없는
    # `action` 은 `apply_plan` 과 같이 `create` 로 봄.
    plan_contents = {
        _norm_rel(e.get("path", "")): e["content"]
        for e in files
        if e.get("action", "create") == "create" and "content" in e
    }
    wiki_root = _wiki_root_hint(root)

    existing = scan_components(root / ".claude")
    existing_by_name: dict = {}  # name → 기존 파일의 root-상대 정규경로
    for grp in existing.values():
        for c in grp:
            nm2 = c.get("name")
            if not nm2:
                continue
            try:
                rp = _norm_rel(os.path.relpath(c["path"], root))
            except Exception:
                rp = ""
            existing_by_name.setdefault(nm2, rp)
    new_names: dict = {}  # name → plan 내 정규경로

    for e in files:
        rel = _norm_rel(e.get("path", ""))
        content = e.get("content", "")

        problem = _path_problem(rel)
        if problem:
            issues.append({"severity": "high", "kind": "path", "path": rel, "detail": problem})

        if rel.startswith(".claude/commands/") or "/.claude/commands/" in rel:
            issues.append(
                {
                    "severity": "high",
                    "kind": "command",
                    "path": rel,
                    "detail": "harness는 커맨드를 생성하지 않는다",
                }
            )

        if _is_component_path(rel):
            fm = _parse_frontmatter(content)
            name_val = fm.get("name")
            if not name_val or not isinstance(name_val, str):
                issues.append(
                    {
                        "severity": "high",
                        "kind": "frontmatter",
                        "path": rel,
                        "detail": "name 누락/빈값",
                    }
                )
            desc_val = fm.get("description")
            if not desc_val or not isinstance(desc_val, str):
                issues.append(
                    {
                        "severity": "high",
                        "kind": "frontmatter",
                        "path": rel,
                        "detail": "description 누락/빈값",
                    }
                )
            # name 은 비교·해싱 전 문자열로 보장(YAML 리스트/딕트면 위에서 이미 누락 처리).
            nm = name_val if isinstance(name_val, str) else ""
            if nm:
                # 같은 name 이 다른 경로면 진짜 중복. 같은 경로면 기존 파일 갱신이므로 허용.
                if nm in existing_by_name and existing_by_name[nm] != rel:
                    issues.append(
                        {
                            "severity": "high",
                            "kind": "dedup",
                            "path": rel,
                            "detail": f"기존 컴포넌트와 name 충돌: {nm}",
                        }
                    )
                if nm in new_names and new_names[nm] != rel:
                    issues.append(
                        {
                            "severity": "high",
                            "kind": "dedup",
                            "path": rel,
                            "detail": f"plan 내 name 중복: {nm}",
                        }
                    )
                new_names.setdefault(nm, rel)

        # wiki 노드 id parity: 손으로 판 wiki_id 가 기계 파생과 어긋나면 나중에 duplicate/format
        # 으로 --verify 가 모든 커밋을 막음 — plan 시점에 잡음. wiki root 아래 `.md` 중
        # front matter 가 바이트 0에서 시작하고 wiki_id 를 든 것만 노드(wiki_graph 와 같은
        # 마커 의미론 — 아니면 _parse_frontmatter 가 이미 {} 를 줌). 다만 정확히 같지는
        # 않음: `_parse_frontmatter` 는 닫는 `---` 뒤 개행을 요구하고 PyYAML 부재 시
        # name/description 만 뽑으므로, 두 경우 이 검사는 조용히 통과 — 게이트가 아니라
        # 진단이라 놓친 쪽이 fail-open. root 가 "." 또는 ""
        # (저장소 루트를 wiki 루트로 설정)이면 plan 의 모든 `.md` 가 대상 — rel 은 정규화
        # 후 선행 "./" 가 없어 `rel.startswith(f"{wiki_root}/")` 가 영영 매칭되지 않음.
        if rel.endswith(".md") and (wiki_root in ("", ".") or rel.startswith(f"{wiki_root}/")):
            wid = _parse_frontmatter(content).get("wiki_id", _NO_WIKI_ID)
            if wid is _NO_WIKI_ID or wid is None:
                pass  # wiki_id 자체가 없음 — 평범한 문서, 노드 아님
            elif not isinstance(wid, str):
                # YAML 1.1 은 따옴표 없는 스칼라를 문자열 아닌 타입으로 읽음: `wiki_id: no` 는
                # bool False, `wiki_id: 0123456` 은 8진수 int. 안 잡으면 falsy 라 아래 parity
                # 검사에서 조용히 빠져나가는데, 그게 바로 이 검사가 한 게이트 앞에서 잡으려는
                # 조건 — wiki_graph 는 --verify 에서 같은 조건을 보고(_wrong_type/
                # _text_type_problems) 어휘를 하나로 두려고 문구를 맞춤.
                issues.append(
                    {
                        "severity": "high",
                        "kind": "wiki-id",
                        "path": rel,
                        "detail": (
                            f"wiki_id 가 문자열이 아닙니다 — YAML 이 {type(wid).__name__} 로 "
                            f"읽었습니다 (값 {wid!r}). 따옴표로 감싸세요"
                        ),
                    }
                )
            elif wid.startswith(DEFECT_PREFIX):
                # defect 노드는 defect-template 의 `defect.<slug>` 관례를 따름(경로 파생이
                # 아님 — wiki-init Step 5) — 여기서 패리티를 보면 오탐.
                pass
            elif wid:
                try:
                    expected = derive_wiki_id(rel, wiki_root)
                    if wid != expected:
                        issues.append(
                            {
                                "severity": "high",
                                "kind": "wiki-id",
                                "path": rel,
                                "detail": (
                                    f"wiki_id '{wid}' ≠ 경로 파생값 '{expected}' — "
                                    "--derive-id 로 얻으세요"
                                ),
                            }
                        )
                except ValueError as exc:
                    issues.append(
                        {"severity": "high", "kind": "wiki-id", "path": rel, "detail": str(exc)}
                    )

        # 링크 스캔은 본문만(frontmatter·코드·이미지 제외, root 밖 경로는 검증 범위 밖).
        for link, frag in _MD_LINK_RE.findall(_strip_code(_strip_frontmatter(content))):
            if link.startswith(("http://", "https://", "/", "\\")) or _DRIVE_PREFIX_RE.match(link):
                continue
            # 증거 경로 참조는 dead-link 가 아니라 규칙 위반(harness-rules 4-1) — 편입 위치
            # `docs/research/` 를 가리켜야 함. cleanup 이 이 링크를 보면 정리를 보류하므로
            # 증거 사본이 그대로 남음. dead-link 로 이중 보고하지 않음.
            if _HARNESS_LINK_RE.search(link):
                issues.append(
                    {
                        "severity": "high",
                        "kind": "harness-ref",
                        "path": rel,
                        "detail": f"증거 경로 참조 금지 — docs/research/ 로 링크: {link}",
                    }
                )
                continue
            target = _norm_rel(str(Path(rel).parent / link))
            # `..` 뿐 아니라 `/` 도: `\Users\x.md` 로 쓴 링크는 Windows 에서 드라이브
            # 루트에 걸려 `Path(rel).parent / link` 가 왼쪽을 버리고 `_norm_rel` 이
            # `/Users/x.md` 를 냄 — root 밖인데 `..` 로 시작하지 않음. 아래 읽기가
            # 그것을 열어 버림.
            if target.startswith(("..", "/")) or _DRIVE_PREFIX_RE.match(target):
                continue
            if target not in plan_paths and not (root / target).exists():
                # detail 은 **원문 링크만**(근거는 harness-rules 4-2) — 해석된 경로를 실으면 안 됨.
                issues.append(
                    {
                        "severity": "warn",
                        "kind": "dead-link",
                        "path": rel,
                        "detail": f"링크 대상 없음: {link}",
                    }
                )
                continue
            if not frag or _LINE_FRAGMENT_RE.match(frag):
                continue
            # 디스크 우선: `apply_plan` 의 `create` 는 이미 있는 파일을 덮지 않고(conflict 로
            # 적음), 그래서 플랜 content 는 아직 없는 경로만 기술함.
            disk = root / target
            if disk.exists():
                # 메모이제이션: 한 대상을 가리키는 링크 N 개가 N 번이 아니라 한 번 읽음.
                if target not in disk_texts:
                    try:
                        # utf-8-sig: BOM 은 첫 `#` 에 붙어 있고 `\s` 가 아님(Invariant 2).
                        disk_texts[target] = disk.read_text(encoding="utf-8-sig", errors="replace")
                    except Exception:
                        disk_texts[target] = None  # 못 읽음 — 답을 내지 않음(FAIL-OPEN)
                target_text = disk_texts[target]
                if target_text is None:
                    continue
            else:
                target_text = plan_contents.get(target)
                if target_text is None:
                    continue
            if not _has_anchor(target_text, frag):
                issues.append(
                    {
                        "severity": "warn",
                        "kind": "dead-anchor",
                        "path": rel,
                        "detail": f"앵커 대상 없음: {link}#{frag}",
                    }
                )

        for blk in _ops_directive_blocks(content):
            non_empty = [ln for ln in blk if ln.strip()]
            if len(non_empty) > OPS_MAX_LINES:
                issues.append(
                    {
                        "severity": "high",
                        "kind": "ops-line-limit",
                        "path": rel,
                        "detail": (
                            f"운영 directive 가 {len(non_empty)}줄 — "
                            f"항목당 ≤{OPS_MAX_LINES}줄 (살은 docs/code-style 로)"
                        ),
                    }
                )

        if e.get("action") == "marker_upsert":
            mid = e.get("marker_id", "")
            # plan content 에 마커 라인이 박혀 있으면(템플릿 통째 복사) apply 가 재래핑해 중첩됨.
            if mid and (_marker_begin(mid) in content or _marker_end(mid) in content):
                issues.append(
                    {
                        "severity": "high",
                        "kind": "marker",
                        "path": rel,
                        "detail": "content 에 마커 BEGIN/END 포함 — body 만 넣어야 함(중첩 방지)",
                    }
                )
            target_file = root / rel
            if target_file.exists():
                try:
                    # cp949 호스트의 기존 파일도 마커(ASCII)는 읽혀야 함 → errors='replace'.
                    txt = target_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    txt = ""
                if mid and _marker_begin(mid) in txt and _marker_end(mid) not in txt:
                    issues.append(
                        {
                            "severity": "high",
                            "kind": "marker",
                            "path": rel,
                            "detail": "BEGIN without END (corrupt)",
                        }
                    )

    baseline = next(
        (
            e
            for e in files
            if e.get("action") == "marker_upsert" and e.get("marker_id") == BASELINE_MARKER
        ),
        None,
    )
    if baseline is None:
        issues.append(
            {
                "severity": "high",
                "kind": "rule-load",
                "path": "CLAUDE.md",
                "detail": f"{BASELINE_MARKER} 마커블록 없음",
            }
        )
    else:
        body = baseline.get("content", "")
        for key in REQUIRED_RULES:
            if not _has_rule_anchor(body, key):
                issues.append(
                    {
                        "severity": "high",
                        "kind": "rule-load",
                        "path": baseline.get("path", "CLAUDE.md"),
                        "detail": f"필수 룰 anchor 누락: {key}",
                    }
                )

    return {"ok": not any(i["severity"] == "high" for i in issues), "issues": issues}


def apply_plan(root: Path, plan: dict) -> dict:
    """플랜을 파일로 떨어뜨림. 쓰기 시점의 경로 봉쇄가 여기 있음.

    validate 는 FAIL-OPEN 진단이라 건너뛰거나 무시될 수 있지만 apply 는 **쓰기** —
    철자로 나가는 경로(`_path_problem`)와 심링크로 나가는 경로(`_escapes_root`) 둘 다
    거부하고 `rejected` 에 사유와 함께 남김. 거부는 그 엔트리 하나뿐, 나머지는 계속
    적용(기존 `conflicts` 와 같은 결).
    의도된 잔여: 이미 존재하는 파일을 가리키는 하드링크는 판정 대상이 아님.

    **어떤 엔트리도 실행을 죽이지 않음.** 예외로 올리면 앞 엔트리만 적용된 반쯤 쓰인
    트리가 남아, doctor 가 덮으려는 그 상태를 apply 스스로 만듦. 그래서 OS 가 거절한
    경로는 `rejected` 로, 엔트리 자체가 잘못 쓰인 경우(키 누락·타입 불일치·마커 구조 오류)는
    `lens_upsert` 가 이미 쓰는 결대로 `skipped` + `warnings` 로 내려감 — 후자는 조작된
    입력이 아니라 모델이 쓴 plan 의 평범한 오류라 경로 문제보다 흔함.

    보고 경로는 `path`(정규화 — validate·doctor 와 같은 문자열이라 표를 대조할 수 있음)와,
    다를 때만 함께 실리는 `raw`(플랜에 적힌 원문 — 사람이 고칠 자리).
    """
    report = {"created": [], "skipped": [], "updated": [], "conflicts": [], "rejected": []}
    for entry in plan.get("files", []):
        raw = entry.get("path", "")
        rel = _norm_rel(raw)
        problem = _path_problem(rel) or _escapes_root(root, root / rel)
        if problem:
            _reject(report, rel, raw, problem)
            continue
        try:
            _apply_entry(root, rel, entry, report)
        except OSError as e:
            _reject(report, rel, raw, f"OS 가 경로를 거절함: {e}")
        except (KeyError, TypeError, ValueError) as e:
            report["skipped"].append(rel)
            report.setdefault("warnings", []).append(
                f"{rel}: 엔트리 오류 — {type(e).__name__}: {e}"
            )
    return report


def _reject(report: dict, rel: str, raw: str, reason: str) -> None:
    entry = {"path": rel or EMPTY_PATH, "reason": reason}
    if raw != rel:
        entry["raw"] = raw
    report["rejected"].append(entry)


def _lf(text: str) -> str:
    # 텍스트 모드는 "\n" 마다 플랫폼 줄끝을 씀 — 플랜 JSON 에 남은 "\r\n" 은 Windows 에서
    # "\r\r\n" 이 됨. 홀로 선 "\r" 도 다시 읽으면 줄바꿈이라 함께 접음.
    if not isinstance(text, str):  # AttributeError 는 _apply_entry 호출자가 못 받음
        raise TypeError(f"문자열이 아님: {type(text).__name__}")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _apply_entry(root: Path, rel: str, entry: dict, report: dict) -> None:
    """엔트리 하나를 적용하고 결과를 report 에 기록. 경로 봉쇄는 호출자가 이미 마침."""
    target = root / rel
    action = entry.get("action", "create")
    if action == "marker_upsert":
        upsert_marker_block(target, entry["marker_id"], _lf(entry.get("content", "")))
        report["updated"].append(rel)
    elif action == "create":
        if target.exists():
            report["conflicts"].append(rel)  # 덮어쓰기 금지
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_lf(entry.get("content", "")), encoding="utf-8")
        report["created"].append(rel)
    elif action == "lens_upsert":
        stack = entry["stack"]
        mode = entry.get("mode", "additive")
        lenses = entry.get("lenses", [])
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        original = text
        try:
            if mode == "replace_section":
                blocks = "".join(
                    _marker_begin(_lens_marker_id(stack, lens["key"]))
                    + "\n"
                    + _lf(lens["body"]).rstrip()
                    + "\n"
                    + _marker_end(_lens_marker_id(stack, lens["key"]))
                    + "\n"
                    for lens in lenses
                )
                text = replace_bp_section(text, blocks)
            else:  # additive
                for lens in lenses:
                    text = upsert_lens_block(text, stack, lens["key"], _lf(lens["body"]))
        except ValueError as e:
            report["skipped"].append(rel)
            report.setdefault("warnings", []).append(f"{rel}: {e}")
        else:
            if text != original:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            report["updated"].append(rel)
    else:
        report["skipped"].append(rel)


# 구버전 하네스가 만든 문서의 경로 이전 테이블 (old_rel, new_rel). 플러그인 갱신으로 산출물
# 위치가 바뀌면 여기 한 줄씩 추가 — harness-init 재실행이 옛 위치의 사용자 편집 문서를
# 새 위치로 옮겨 고아 사본·중복 SSOT 를 막음.
DOC_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("docs/performance.md", "docs/verification/performance.md"),
    ("docs/integration.md", "docs/verification/integration.md"),
)


def migrate_docs(root: Path, migrations: tuple[tuple[str, str], ...] = DOC_MIGRATIONS) -> dict:
    """구버전 경로의 문서를 새 위치로 이동한다(멱등·FAIL-OPEN·덮어쓰기 금지).

    - 옛 파일 부재: 이동할 게 없음(이미 이전됐거나 애초에 없음) → 조용히 건너뜀(멱등).
    - 새 위치에 이미 파일 존재: 사용자 편집 보존을 위해 clobber 하지 않고 `conflicts` 로
      보고(둘 다 남기고 사람이 조정) — apply 의 "덮어쓰기 금지" 불변식과 동일 규율.
    - 그 외: 부모 폴더 생성 후 rename. 오류는 FAIL-OPEN(`errors` 로 보고하고 흐름을 막지 않음).
    """
    report: dict = {"moved": [], "conflicts": [], "errors": []}
    for old_rel, new_rel in migrations:
        old = root / old_rel
        new = root / new_rel
        if not old.is_file():
            continue
        if new.exists():
            report["conflicts"].append({"from": old_rel, "to": new_rel})
            continue
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            report["moved"].append({"from": old_rel, "to": new_rel})
        except OSError as e:  # 크로스-디바이스 등 — FAIL-OPEN
            report["errors"].append({"path": old_rel, "detail": str(e)})
    return report


# 편입 완료된 중간 사본을 정리할 때 절대 지우지 않는 감사용 증거(호스트로 복사되지 않음).
CLEANUP_PRESERVE = ("plan.json", "manifest.json", "critic-report.json", "rationale.md")


def cleanup_harness(harness_dir: Path, root: Path | None = None) -> dict:
    """apply 후 docs로 편입된 중간 사본(research/)을 제거.

    링크 가드(FAIL-SAFE): root가 주어지면 docs/ 의 .md 를 스캔해 ".harness/research" 를
    참조하는 링크가 있으면 제거를 보류하고 link_warnings 에 기록(편입 누락으로 링크가
    깨질 상황 방지). 감사/재실행용 증거(CLEANUP_PRESERVE)는 항상 보존하고, research/ 와 보존
    목록 외의 파일은 보수적으로 건드리지 않음.
    """
    report: dict = {"removed": [], "preserved": [], "link_warnings": []}
    research_dir = harness_dir / "research"

    if root is not None:
        docs_dir = root / "docs"
        if docs_dir.is_dir():
            for md in sorted(docs_dir.rglob("*.md")):
                try:
                    text = md.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if ".harness/research" in text:
                    report["link_warnings"].append(str(md.relative_to(root)).replace("\\", "/"))

    if research_dir.is_dir() and not report["link_warnings"]:
        for f in sorted(research_dir.rglob("*"), reverse=True):
            try:
                if f.is_file():
                    f.unlink()
                    report["removed"].append(str(f.relative_to(harness_dir)).replace("\\", "/"))
                elif f.is_dir():
                    f.rmdir()
            except OSError:
                pass  # FAIL-OPEN: 정리는 부가작업, 실패해도 흐름을 막지 않음
        try:
            research_dir.rmdir()
        except OSError:
            pass

    report["preserved"] = [n for n in CLEANUP_PRESERVE if (harness_dir / n).exists()]
    return report


# docs 밑에 있으면 언제나 사고인 디렉터리 이름(소문자 — 비교는 대소문자 무시) — 하네스
# 택소노미(harness-rules 8)에 `.claude`·`.harness` 는 없음. 편입이 경로를 잘못 이은 서명.
_STRAY_DIR_NAMES = (".claude", ".harness")
_DOCTOR_LISTS = ("stray_trees", "research_residue", "plan_unapplied", "plan_bad_paths")


def _plan_entries(plan_path: Path) -> tuple[list, bool]:
    """plan.json 의 files 리스트와 **읽어냈는가**. 파일이 아예 없으면 `([], True)`.

    doctor 가 존재하는 이유가 **중단된 실행이 남긴 반쯤 쓰인 plan.json** 이므로, 파싱
    실패만 잡고 모양을 안 보면 바로 그 입력에 죽음(`{"files": "not a list"}` → 크래시).
    실패를 빈 리스트로 삼키기만 해도 안 됨 — 그러면 깨진 plan 이 "계획 없음"과 같아져
    doctor 가 `clean` 을 보고함. 그래서 못 읽었다는 사실을 함께 돌려줌.
    """
    if not plan_path.is_file():
        return [], True
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return [], False
    if not isinstance(plan, dict):
        return [], False
    # `files` 키 부재는 "빈 계획" — apply·validate 가 `plan.get("files", [])` 로 그렇게 읽으므로
    # 여기만 "깨짐"이라 하면 같은 입력에 세 함수가 다른 답을 냄.
    files = plan.get("files", [])
    if not isinstance(files, list):
        return [], False
    entries = [e for e in files if isinstance(e, dict)]
    return entries, len(entries) == len(files)


def doctor(root: Path) -> dict:
    """중단된 실행의 잔해를 진단(읽기 전용·FAIL-OPEN·게이트 아님·항상 exit 0).

    `cleanup` 은 apply 성공 후에만 돌아 중단 사고를 못 봄. 재실행은 반쯤 쓰인 파일을
    `exists()` 로 보고 `conflicts` 에 넣고 넘어가므로 스스로 낫지도 않음. 그래서
    "재실행 전에 무엇이 어긋났는지" 를 이름 대는 진입점이 따로 필요. 아무것도 고치지
    않음 — 판단과 수습은 사람 몫.

    보고 넷 + 플래그 하나: `stray_trees`(docs 밑 `.claude`/`.harness` 트리) ·
    `research_residue`(편입이 끝났는데 남은 증거 사본) · `plan_unapplied`(계획됐는데 파일이
    없음) · `plan_bad_paths`(apply 가 거부할 경로 — 이게 없으면 산출물이 전부 거부된 실행이
    `clean` 으로 보임) · `plan_unreadable`(plan.json 이 깨져 위 셋을 판정 못 함).
    """
    harness_dir = root / ".claude" / "vway-kit" / ".harness"
    report: dict = {k: [] for k in _DOCTOR_LISTS}
    report["plan_unreadable"] = False
    report["verdict"] = "clean"

    docs_dir = root / "docs"
    if docs_dir.is_dir():
        stray: list[str] = []
        for dirpath, dirnames, _ in os.walk(docs_dir):
            for name in [d for d in dirnames if _fold_segment(d) in _STRAY_DIR_NAMES]:
                stray.append(_rel_posix(Path(dirpath) / name, root))
                dirnames.remove(name)  # 트리당 한 번 — 안쪽 파일마다 되풀이하지 않음
        report["stray_trees"] = sorted(stray)

    entries, readable = _plan_entries(harness_dir / "plan.json")
    report["plan_unreadable"] = not readable
    unapplied: list[str] = []
    bad: list[str] = []
    for e in entries:
        rel = _norm_rel(str(e.get("path") or ""))
        # apply 와 **같은 판정**을 씀 — 여기서 철자만 보면 심링크로 나가는 엔트리가
        # "계획됐는데 아직 안 됨"(다시 apply 하면 됨)으로 보고돼 사람을 헛돌게 함.
        # 빈 경로도 apply 가 거부하는 대상이므로 버리지 않음(버리면 전부 null-path 인
        # plan 이 clean 으로 읽힘).
        if _path_problem(rel) or _escapes_root(root, root / rel):
            bad.append(rel or EMPTY_PATH)
        elif not (root / rel).exists():
            unapplied.append(rel)
    report["plan_unapplied"] = sorted(unapplied)
    report["plan_bad_paths"] = sorted(bad)

    # 편입이 끝났는가 — 그 전의 research 는 잔해가 아니라 입력. manifest 는 Step 8,
    # 즉 cleanup(7.5) **뒤**라 7.5 재확인 시점엔 없음. 계획된 산출물이 전부 자리에 있으면
    # 그 시점에도 apply 는 끝난 것이므로, 늦은 표식과 그 조건 중 **먼저 참인 쪽**을 씀.
    # 잔여 오탐: `exists()` 는 "apply 가 만들었다"와 "원래 있었다"를 구분하지 못함.
    applied = (harness_dir / "manifest.json").exists() or (
        bool(entries) and not unapplied and not bad
    )
    research_dir = harness_dir / "research"
    if applied and research_dir.is_dir():
        report["research_residue"] = sorted(
            _rel_posix(f, root) for f in research_dir.rglob("*") if f.is_file()
        )

    if report["plan_unreadable"] or any(report[k] for k in _DOCTOR_LISTS):
        report["verdict"] = "dirty"
    return report


def _detect_payload(root: Path) -> dict:
    return {
        "state": detect_state(root),
        "frameworks": detect_frameworks(root),
        "existing": scan_components(root / ".claude"),
    }


def main(argv: list[str]) -> int:
    force_utf8_io()
    parser = argparse.ArgumentParser(prog="harness_scaffold")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--root", default=".")
    a = sub.add_parser("apply")
    a.add_argument("--root", default=".")
    a.add_argument("--plan", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--root", default=".")
    v.add_argument("--plan", required=True)
    c = sub.add_parser("cleanup")
    c.add_argument("--root", default=".")
    mg = sub.add_parser("migrate")
    mg.add_argument("--root", default=".")
    sc = sub.add_parser("scan-lenses")
    sc.add_argument("--root", default=".")
    dr = sub.add_parser("doctor")
    dr.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.cmd == "detect":
        print(json.dumps(_detect_payload(root), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "apply":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        print(json.dumps(apply_plan(root, plan), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "validate":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        print(json.dumps(validate_plan(root, plan), ensure_ascii=False, indent=2))
        return 0  # FAIL-OPEN: 진단이지 게이트가 아님
    if args.cmd == "cleanup":
        harness_dir = root / ".claude" / "vway-kit" / ".harness"
        print(json.dumps(cleanup_harness(harness_dir, root), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "migrate":
        print(json.dumps(migrate_docs(root), ensure_ascii=False, indent=2))
        return 0  # FAIL-OPEN: 재배치 실패는 흐름을 막지 않음
    if args.cmd == "scan-lenses":
        print(json.dumps(scan_code_style(root), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "doctor":
        print(json.dumps(doctor(root), ensure_ascii=False, indent=2))
        return 0  # FAIL-OPEN: 진단이지 게이트가 아님
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
