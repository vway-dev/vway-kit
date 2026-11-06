"""docs/srs 와 Recoble requirement 계층의 왕복 — 판정을 쥔 쪽.

게이트 아님. 어긋남이 몇 건이든 exit 0 이고, `docs/srs` 부재는 무출력 성공(`srs_check`
와 같은 계약). 보드를 읽는 것은 이 스크립트가 아니라 `alm-docs` 스킬이 띄우는 에이전트이고,
여기 오는 것은 그 에이전트가 낸 JSON — 열거만 모델에 맡기고 판정은 결정적인 코드에 두는 분업.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from _md_anchors import _ANCHOR_ID_RE, _HTML_COMMENT_RE, mask_examples
except ImportError:
    from scripts._md_anchors import _ANCHOR_ID_RE, _HTML_COMMENT_RE, mask_examples

try:
    from _vway_paths import force_utf8_io, is_safe_template_rel, under_real_tree
except ImportError:
    from scripts._vway_paths import force_utf8_io, is_safe_template_rel, under_real_tree

# `docs/srs` 의 자리와 색인 파일 이름은 `srs_check` 가 쥠 — 요구 텍스트의 SSOT 가 그쪽이고,
# 두 곳에 적으면 한쪽만 옮겨도 이 스크립트가 빈 목록을 성공으로 보고함.
try:
    from srs_check import INDEX_STEM, SRS_REL
except ImportError:
    from scripts.srs_check import INDEX_STEM, SRS_REL

# 1차 범위. 다른 축(NFR·CON·ROLE)은 같은 앵커 문법을 쓰되 보드 쪽 대응이 없어 목록에서 빠짐.
KINDS = ("FR", "C")
# 수입한 줄에 서는 사람용 표식. 렌더된 본문에 남되 제목 비교에서는 빠짐 — 한쪽에만 있는
# 글자를 함께 비교하면 수입 직후의 상태가 곧 「제목 다름」이 되고, 이어지는 `--push` 가
# 그 표식을 보드 제목에 써 넣음.
REVIEW_MARK = "(확인 필요)"

_ALM_COMMENT_RE = re.compile(r"<!--\s*alm:\s*(.*?)\s*-->", re.DOTALL)
# 시작-자리 이차성 근거는 `_md_anchors._A_TAG_RE` 와 같음(그쪽 주석이 SSOT) — 입력이
# `_title()` 이 받는 한 줄이라 노출은 작되, 형제 패턴과 다르게 넓힐 이유는 없음.
_A_ANY_TAG_RE = re.compile(r"</?a\b[^<>]*>", re.IGNORECASE)
_BOLD_ID_RE = re.compile(r"\*\*[A-Za-z][A-Za-z0-9-]*\*\*")


def _read(path: Path) -> str:
    """줄끝을 번역하지 않고 읽음.

    개발 호스트의 워킹트리는 CRLF, CI 는 LF — 읽기가 줄끝을 접으면 되쓰기가 파일 전체의
    줄끝을 뒤집고, 한 줄짜리 편집이 파일 전체 diff 로 나감.
    """
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path: Path, text: str) -> None:
    """`_read` 의 짝 — 문자열이 지닌 줄끝을 그대로 내보냄."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _kind_and_number(anchor: str) -> tuple | None:
    """`fr-payment-001` 을 `("FR", "001")` 로. 번호로 끝나지 않으면 None."""
    head, _, num = anchor.rpartition("-")
    if not head or not num.isdigit():
        return None
    return head.split("-", 1)[0].upper(), num


def parse_alm(line: str) -> dict:
    """그 줄이 지닌 `<!-- alm: <스페이스>/<항목 id> -->` 전부.

    스페이스를 함께 적는 이유는 한 저장소가 여러 스페이스에 붙을 수 있고, 스페이스가
    다르면 같은 id 도 다른 항목인 것. 스페이스가 둘이면 주석도 둘.
    """
    out = {}
    for body in _ALM_COMMENT_RE.findall(line):
        space, sep, item = body.partition("/")
        space, item = space.strip(), item.strip()
        if sep and space and item:
            out[space] = item
    return out


def _strip_review_mark(title: str) -> str:
    """공백을 접고 **말미**의 `REVIEW_MARK` 를 남지 않을 때까지 뗀 비교용 값.

    비교의 양쪽이 같은 변환을 받는 것이 계약 — 한쪽만 벗기면 repo 쪽 표식이 붙은 문장이
    보드와 영영 안 맞아 「제목 다름」이 안 닫히고, `--push` 가 사람이 보드에 쓴 글자를 지움.
    자리를 묻는 이유는 문장 가운데의 같은 글자가 그 문장의 일부인 것 — 어디서나 지우면
    서로 다른 두 문장이 같아 보임.

    **반복**인 이유는 받는 횟수가 양쪽이 다른 것 — repo 쪽 제목은 `scan` 의 `_title` 과
    `diff` 의 `_norm` 으로 두 번, 보드 쪽은 `_norm` 으로 한 번임. 하나만 떼면 그 횟수 차이가
    글자 차이가 되어 표식이 둘 쌓인 거울상 입력에서 같은 문장이 「제목 다름」으로 나감.
    `REVIEW_MARK` 는 비지 않으므로 한 바퀴마다 값이 짧아져 루프가 끝남.
    """
    text = " ".join(str(title).split())
    while text.endswith(REVIEW_MARK):
        text = text[: -len(REVIEW_MARK)].rstrip()
    return text


def _title(line: str) -> str:
    """앵커 줄에서 태그·굵은 id 표기·HTML 주석을 걷어낸 나머지 한 줄.

    정의를 스크립트가 고정하는 이유는 「제목 다름」 판정이 이 한 줄에 걸리는 것 — 자르는
    자리가 사람마다 다르면 편집이 아니라 자르기 차이가 드리프트로 보고됨.

    `alm:` 주석 하나가 아니라 **주석 전부**를 벗기는 이유는 그것이 `mask_examples` 와 같은
    규약인 것 — 저자가 같은 줄에 단 다른 주석이 남으면 그 글자가 영구 「제목 다름」을 세우고,
    `--push` 가 주석 텍스트를 보드 항목 제목에 써 넣음. 매칭 키는 `parse_alm` 이 원문 줄에서
    따로 읽으므로 여기서 함께 지워도 안 바뀜.
    """
    text = _HTML_COMMENT_RE.sub("", line)
    text = _A_ANY_TAG_RE.sub("", text)
    text = _BOLD_ID_RE.sub("", text, count=1)
    return _strip_review_mark(text)


def _line_pairs(text: str) -> list:
    """(원문 줄, 마스킹된 같은 구간) 쌍 — 경계는 원문 하나가 정함.

    `raw`·`masked` 를 각자 `splitlines()` 하면 `\\x0c` 같은 구분자가 마스킹 안에서
    공백으로 덮여 한쪽만 줄이 갈리고, 그 뒤의 줄 번호가 통째로 밀림. `mask_examples`
    가 길이를 보존하므로 원문 하나의 오프셋으로 함께 자르면 어긋날 수 없음.
    """
    masked = mask_examples(text)
    out, start = [], 0
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        out.append((line, masked[start:end]))
        start = end
    return out


def scan(root: Path) -> dict | None:
    """repo 측 목록. `docs/srs` 부재는 빈 목록이 아니라 None — 호출자가 무출력으로 갈림."""
    srs = root / SRS_REL
    if not srs.is_dir():
        return None
    items = []
    for path in sorted(srs.glob("*.md")):
        text = _read(path)
        area = None if path.stem == INDEX_STEM else path.stem
        rel = path.relative_to(root).as_posix()
        for n, (raw_line, masked_line) in enumerate(_line_pairs(text), 1):
            for anchor in _ANCHOR_ID_RE.findall(masked_line):
                parsed = _kind_and_number(anchor.lower())
                if parsed is None or parsed[0] not in KINDS:
                    continue
                items.append(
                    {
                        "anchor": anchor.lower(),
                        "kind": parsed[0],
                        "area": area,
                        "file": rel,
                        "line": n,
                        "title": _title(raw_line),
                        "alm": parse_alm(raw_line),
                    }
                )
    return {"root": SRS_REL, "items": items}


def _norm(title: str) -> str:
    """보드 제목의 비교용 값 — repo 쪽 `_title` 과 같은 변환."""
    return _strip_review_mark(title)


def _board_index(boards: list) -> tuple:
    """(스페이스 → {제목 표, 잘림 여부}, 버린 것의 사유별 건수). 같은 스페이스가 둘이면 **합침**.

    뒤엣것으로 덮으면 앞 파일이 본 항목이 통째로 「보드에만 있음」에서 빠지고, 그것을
    가리키는 앵커는 「끊긴 매핑」으로 나감 — 정보를 잃지 않는 읽기가 합치는 쪽 하나뿐임.

    버린 것을 세는 이유는 그것이 0건과 구별되지 않는 것 — `space` 키 없는 열거 하나만
    넘기면 다섯 갈래가 전부 0건으로 서고, 미푸시 요구가 몇 개든 「어긋남 없음」으로 읽힘.
    """
    out = {}
    ignored = {"no_space": 0, "no_id": 0}
    for board in boards:
        space = str((board or {}).get("space") or "")
        if not space:
            ignored["no_space"] += 1
            continue
        slot = out.setdefault(space, {"titles": {}, "truncated": False})
        for item in board.get("items") or []:
            item_id = str((item or {}).get("id") or "")
            if not item_id:
                ignored["no_id"] += 1
                continue
            slot["titles"][item_id] = _norm((item or {}).get("title") or "")
        slot["truncated"] = slot["truncated"] or bool((board.get("meta") or {}).get("truncated"))
    return out, ignored


def diff(repo: dict, boards: list) -> dict:
    """다섯 갈래 판정.

    잘린 열거는 그 스페이스를 「보드에만 있음」과 「끊긴 매핑」 **양쪽**에서 뺌 — 못 본
    항목이 전자에서는 누락으로, 후자에서는 가짜 결함으로 나옴. 두 판정 다 완전한 보드를
    전제하고, 잘렸다는 사실은 `truncated` 에 실려 표에 뜸.
    """
    index, ignored = _board_index(boards)
    items = repo.get("items") or []
    drift = {
        "never_pushed": [],
        "broken_mapping": [],
        "board_only": [],
        "title_differs": [],
        "duplicate_mapping": [],
    }
    for space in sorted(index):
        titles = index[space]["titles"]
        truncated = index[space]["truncated"]
        seen = {}
        for item in items:
            where = {
                "anchor": item["anchor"],
                "file": item["file"],
                "line": item["line"],
                "space": space,
            }
            mapped = (item.get("alm") or {}).get(space)
            if not mapped:
                drift["never_pushed"].append(dict(where, title=item["title"]))
                continue
            seen.setdefault(mapped, []).append(item["anchor"])
            if mapped not in titles:
                if not truncated:
                    drift["broken_mapping"].append(dict(where, item=mapped))
                continue
            if _norm(item["title"]) != titles[mapped]:
                drift["title_differs"].append(
                    dict(
                        where,
                        item=mapped,
                        repo_title=_norm(item["title"]),
                        board_title=titles[mapped],
                    )
                )
        for item_id, anchors in sorted(seen.items()):
            if len(anchors) > 1:
                drift["duplicate_mapping"].append(
                    {"space": space, "item": item_id, "anchors": sorted(anchors)}
                )
        if not truncated:
            for item_id in sorted(titles):
                if item_id not in seen:
                    drift["board_only"].append(
                        {"space": space, "item": item_id, "title": titles[item_id]}
                    )
    return {
        "spaces": sorted(index),
        "truncated": sorted(s for s in index if index[s]["truncated"]),
        "ignored": ignored,
        "drift": drift,
        "counts": {key: len(rows) for key, rows in drift.items()},
    }


# 갈래 → (표에 쓰는 이름, 자동 처리). 끊긴 매핑·중복 매핑에 자동이 없는 근거는 의도의
# 문제인 것 — 지워진 항목을 되살릴지 주석을 지울지 한쪽을 고르면 조용히 틀림.
_LABELS = (
    ("never_pushed", "한 번도 안 올림", "--push"),
    ("broken_mapping", "끊긴 매핑", "사람"),
    ("board_only", "보드에만 있음", "--pull"),
    ("title_differs", "제목 다름", "방향별"),
    ("duplicate_mapping", "중복 매핑", "사람"),
)

_IGNORED_LABELS = (
    ("no_space", "`space` 키 없는 보드 열거"),
    ("no_id", "`id` 없는 보드 항목"),
)


def _row(key: str, row: dict) -> str:
    """표 한 줄. 앵커를 지목하는 셋은 `-> ` 뒤에 **대상 스페이스**를 실음.

    싣지 않으면 스페이스 둘인 호스트에서 같은 앵커가 둘 다 미푸시일 때 바이트 동일한 줄이
    두 번 나가, 건수가 앵커 수인지 스페이스 수인지 읽는 쪽이 못 가름. 항목이 정해진 둘은
    「보드에만 있음」과 같은 `{space}/{item}` 꼴.
    """
    if key == "board_only":
        return "{space}/{item}  {title}".format(**row)
    if key == "duplicate_mapping":
        return "{space}/{item}  <- ".format(**row) + ", ".join(row["anchors"])
    where = "{file}:{line}  {anchor}  -> ".format(**row)
    if key == "never_pushed":
        return where + "{space}  {title}".format(**row)
    if key == "broken_mapping":
        return where + "{space}/{item} (보드에 없음)".format(**row)
    both = f"repo={row['repo_title']!r} board={row['board_title']!r}"
    return where + "{space}/{item}  ".format(**row) + both


def render(result: dict) -> str:
    """사람이 읽는 표. 0건인 갈래도 줄을 지님 — 빠진 갈래와 0건은 다른 답."""
    lines = ["스페이스: " + (", ".join(result["spaces"]) or "(없음)")]
    if result["truncated"]:
        lines.append(
            "잘린 열거: "
            + ", ".join(result["truncated"])
            + " — 이 스페이스의 「보드에만 있음」·「끊긴 매핑」은 세지 않음"
        )
    ignored = result.get("ignored") or {}
    dropped = [f"{label} {ignored[key]}건" for key, label in _IGNORED_LABELS if ignored.get(key)]
    if dropped:
        lines.append("버린 입력: " + ", ".join(dropped) + " — 아래 건수의 분모 밖")
    for key, label, action in _LABELS:
        rows = result["drift"][key]
        lines.append(f"[{label}] {len(rows)}건 (자동 처리: {action})")
        for row in rows:
            lines.append("  " + _row(key, row))
    return "\n".join(lines)


_NEWLINE_RE = re.compile(r"\r\n|\r|\n")


def _newline(text: str) -> str:
    """그 파일이 쓰는 줄끝. 못 찾으면 LF."""
    m = _NEWLINE_RE.search(text)
    return m.group(0) if m else "\n"


def _split_end(line: str) -> tuple:
    """줄 본문과 줄끝을 가름 — 줄끝을 통째로 보존해 파일의 관례가 안 바뀜.

    가르는 자리를 `splitlines()` 에 되묻는 이유는 줄을 나눈 것이 `_line_pairs` 의 같은
    호출인 것 — 줄끝을 CR·LF·CRLF 셋으로만 다시 읽으면 폼피드·NEL 류 구분자로 끝난 줄이
    줄끝 없는 줄로 보이고, 되쓰기의 `rstrip()` 이 그 구분자를 지워 다음 줄과 합쳐짐.
    """
    parts = line.splitlines()
    body = parts[0] if parts else ""
    return body, line[len(body) :]


def _marks(alm: dict) -> str:
    return "".join(f" <!-- alm: {s}/{alm[s]} -->" for s in sorted(alm))


def anchor_line(anchor: str, item_id: str, title: str, alm: dict) -> str:
    """수입한 요구 한 줄.

    `REVIEW_MARK` 가 주석이 아니라 본문에 서는 이유는 보드 한 줄이 측정 가능한 FR 이라는
    보장이 없는 것 — 렌더된 문서에서 보여야 사람이 다듬을 자리로 읽힘. 지우는 것이 사람의 일.
    """
    return f'<a id="{anchor}"></a>**{item_id}** {title} {REVIEW_MARK}{_marks(alm or {})}'


def _defined_anchors(text: str) -> set:
    """그 문서가 정의하는 앵커 — 예시는 뺌."""
    return {a.lower() for a in _ANCHOR_ID_RE.findall(mask_examples(text))}


def _key_gap(top: str, n: int, row: object, needed: tuple) -> str | None:
    """필수 키를 다 지니면 None, 아니면 자리와 빠진 이름을 대는 `[!]` 한 줄.

    원소 하나의 `KeyError` 가 실행을 죽이면 종료 코드가 판정에 실리지 않는다는 계약이 그
    경로에서만 깨지고, 같은 계획의 성한 줄까지 함께 떨어짐.
    """
    missing = [k for k in needed if k not in row] if isinstance(row, dict) else list(needed)
    if not missing:
        return None
    return f"[!] '{top}' {n}번째 원소에 키 없음, 건너뜀: " + ", ".join(missing)


def _escape_gap(top: str, n: int, root: Path, rel: object) -> str | None:
    """`file` 이 `--root` 안에 머물면 None, 아니면 자리와 값을 대는 `[!]` 한 줄.

    계획의 `file` 은 보드 텍스트를 읽은 모델이 저작하므로 **원격 비신뢰 입력**임. 쓰기
    두 자리의 `is_file()` 는 새 파일 생성만 막고 기존 파일 덧쓰기는 막지 않아 봉쇄가
    아님 — `../` 하나가 저장소 밖 파일에 한 줄을 얹음.

    술어 **둘**을 `_vway_paths` 에서 그대로 씀. 렉시컬 판정 하나로는 부족함 — `..` 가
    없어도 루트 안의 정션·심볼릭 링크를 지나면 링크 너머 남의 디렉터리에 씀. 짝으로
    거는 것이 `vdev_init_setup` 의 이동 경로와 같은 규율이고, 사본을 두면 한쪽만
    고쳐졌을 때 어느 쪽이 참인지 말할 자리가 없음.

    값을 `repr` 로 내는 이유는 빈 문자열·비문자열도 자리를 말해야 하기 때문 — 콜론
    뒤가 비면 운영자가 어느 원소가 걸렸는지 못 가림. 두 갈래의 사유를 가르는 것도
    같은 이유 — 링크는 루트 안을 가리킬 수도 있어 "루트 밖" 이 거짓이 됨.
    """
    at = f"[!] '{top}' {n}번째 원소의 file 이"
    if not is_safe_template_rel(rel):
        return f"{at} 루트 밖, 건너뜀: {rel!r}"
    if not under_real_tree(root / str(rel), root):
        return f"{at} 링크 너머라 건너뜀: {rel!r}"
    return None


def apply_pull(root: Path, plan: dict) -> list:
    """확정된 수입 계획대로 `plan["writes"][*]` 의 앵커 줄을 덧붙임.

    한 원소는 `{file, anchor, id, title, alm}` — `id` 는 SRS 채번(`FR-PAYMENT-002`)이고
    `alm` 만 없어도 됨.

    파일을 **만들지 않음** — 새 영역 파일은 wiki front matter 와 파생 id 가 필요하고 그것은
    부르는 쪽의 일임. 없는 파일은 그 줄만 건너뛰고 보고하므로, 앞 단계의 누락이 조용한
    0건이 아니라 이름으로 드러남.

    최상위 키도 원소의 필수 키도 그 이름을 대는 한 줄 — 무출력 exit 0 은 성공으로 읽힘.
    """
    rows = plan.get("writes") or []
    if not rows:
        return ["[!] 계획에 'writes' 항목이 없음"]
    report = []
    for n, row in enumerate(rows, 1):
        gap = _key_gap("writes", n, row, ("file", "anchor", "id", "title"))
        if gap:
            report.append(gap)
            continue
        rel = row["file"]
        escape = _escape_gap("writes", n, root, rel)
        if escape:
            report.append(escape)
            continue
        path = root / rel
        if not path.is_file():
            report.append("[!] 파일 없음, 건너뜀: " + rel)
            continue
        text = _read(path)
        anchor = str(row["anchor"]).lower()
        if anchor in _defined_anchors(text):
            report.append(f"[=] 이미 있음: {rel}  {anchor}")
            continue
        end = _newline(text)
        if text and not text.endswith(("\n", "\r")):
            text += end
        body = anchor_line(anchor, row["id"], row["title"], row.get("alm") or {})
        _write(path, text + body + end)
        report.append(f"[+] 추가: {rel}  {anchor}")
    return report


def record(root: Path, mapping: dict) -> list:
    """`mapping["records"][*]` 의 항목 id 를 앵커 줄 끝의 주석에 되씀.

    한 원소는 `{file, anchor, space, item}` — `item` 은 Recoble 항목 id(`REQ-118`)임.
    `apply_pull` 쪽 `id`(SRS 채번)와 이름을 가르는 이유는 한 실행이 두 파일을 연달아 쓰는
    것 — 같은 이름이면 교차시켜도 오류가 안 나고 엉뚱한 값이 주석에 실림.

    같은 스페이스의 옛 id 는 교체하고 다른 스페이스의 주석은 그대로 둠 — 한 앵커가 여러
    스페이스를 가리킬 수 있음. 일부만 성공한 실행은 성공한 것만 남김.

    최상위 키도 원소의 필수 키도 그 이름을 대는 한 줄 — 무출력 exit 0 은 성공으로 읽힘.
    """
    rows = mapping.get("records") or []
    if not rows:
        return ["[!] 매핑에 'records' 항목이 없음"]
    report = []
    by_file = {}
    for n, row in enumerate(rows, 1):
        gap = _key_gap("records", n, row, ("file", "anchor", "space", "item"))
        if gap:
            report.append(gap)
            continue
        escape = _escape_gap("records", n, root, row["file"])
        if escape:
            report.append(escape)
            continue
        by_file.setdefault(row["file"], []).append(row)
    for rel in sorted(by_file):
        path = root / rel
        if not path.is_file():
            report.append("[!] 파일 없음, 건너뜀: " + rel)
            continue
        text = _read(path)
        pairs = _line_pairs(text)
        lines = [raw for raw, _ in pairs]
        index = {}
        for n, (_, masked_line) in enumerate(pairs):
            for anchor in _ANCHOR_ID_RE.findall(masked_line):
                index.setdefault(anchor.lower(), n)
        changed = False
        for row in by_file[rel]:
            anchor = str(row["anchor"]).lower()
            n = index.get(anchor)
            if n is None:
                report.append(f"[!] 앵커 없음, 건너뜀: {rel}  {anchor}")
                continue
            body, end = _split_end(lines[n])
            alm = parse_alm(body)
            if alm.get(row["space"]) == row["item"]:
                report.append(f"[=] 이미 있음: {rel}  {anchor}  {row['space']}/{row['item']}")
                continue
            alm[row["space"]] = row["item"]
            lines[n] = _ALM_COMMENT_RE.sub("", body).rstrip() + _marks(alm) + end
            changed = True
            report.append(f"[+] 기록: {rel}  {anchor}  {row['space']}/{row['item']}")
        if changed:
            _write(path, "".join(lines))
    return report


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: str) -> tuple:
    """(읽힌 객체, 경고 한 줄). 부재·파싱 실패·객체 아님은 `(None, 사유)`.

    입력이 없다는 것은 앞 단계가 안 돌았다는 뜻이지 이 스크립트가 낼 판정이 아님 — 게이트가
    아니라는 계약대로 경로를 이름으로 대는 경고 한 줄이고 종료 0. 펼쳐지지 않은 glob 이
    그대로 넘어오는 자리가 이것이 닫는 실제 경로(`--board .../board-*.json`).
    """
    p = Path(path)
    if not p.is_file():
        return None, f"[!] 입력 파일 없음, 건너뜀: {path}"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"[!] JSON 으로 못 읽음, 건너뜀: {path} ({exc})"
    if not isinstance(data, dict):
        return None, f"[!] 최상위가 객체가 아님, 건너뜀: {path}"
    return data, None


def main(argv: list | None = None) -> int:
    force_utf8_io()
    parser = argparse.ArgumentParser(description="SRS 와 Recoble requirement 계층의 대조")
    parser.add_argument("--root", default=".", help="저장소 루트 (기본: cwd)")
    parser.add_argument("--scan", action="store_true", help="repo 측 목록을 JSON 으로")
    parser.add_argument("--out", metavar="PATH", help="--scan 의 출력 경로")
    parser.add_argument("--diff", action="store_true", help="repo 목록과 보드 열거를 대조")
    parser.add_argument("--repo", metavar="PATH", help="--scan 이 낸 JSON")
    parser.add_argument(
        "--board", nargs="+", metavar="PATH", help="보드 열거 JSON (스페이스당 하나 이상)"
    )
    parser.add_argument("--json", metavar="PATH", dest="json_out", help="--diff 결과의 기계용 사본")
    parser.add_argument(
        "--apply-pull", action="store_true", dest="apply_pull", help="수입 계획 적용"
    )
    parser.add_argument(
        "--plan",
        metavar="PATH",
        help='--apply-pull 이 읽는 확정 계획: {"writes": [{file, anchor, id, title, alm}]}',
    )
    parser.add_argument("--record", action="store_true", help="생성된 항목 id 를 주석에 되씀")
    parser.add_argument(
        "--map",
        metavar="PATH",
        dest="map_path",
        help='--record 가 읽는 매핑: {"records": [{file, anchor, space, item}]}',
    )
    args = parser.parse_args(argv)
    if args.scan:
        if not args.out:
            parser.error("--scan 은 --out 이 필요함")
        result = scan(Path(args.root))
        if result is None:
            return 0
        _dump(Path(args.out), result)
        print(f"{len(result['items'])}건 → {args.out}")
    if args.diff:
        if not args.repo or not args.board:
            parser.error("--diff 는 --repo 와 --board 가 필요함")
        repo, warn = _load_json(args.repo)
        if warn:
            print(warn)
        boards = []
        for board_path in args.board:
            board, board_warn = _load_json(board_path)
            if board_warn:
                print(board_warn)
            else:
                boards.append(board)
        if repo is not None and boards:
            result = diff(repo, boards)
            print(render(result))
            if args.json_out:
                _dump(Path(args.json_out), result)
        elif repo is not None:
            print("[!] 읽힌 보드 열거가 없음 — 대조를 건너뜀")
    if args.apply_pull:
        if not args.plan:
            parser.error("--apply-pull 은 --plan 이 필요함")
        plan, warn = _load_json(args.plan)
        if warn:
            print(warn)
        else:
            for line in apply_pull(Path(args.root), plan):
                print(line)
    if args.record:
        if not args.map_path:
            parser.error("--record 는 --map 이 필요함")
        mapping, warn = _load_json(args.map_path)
        if warn:
            print(warn)
        else:
            for line in record(Path(args.root), mapping):
                print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
