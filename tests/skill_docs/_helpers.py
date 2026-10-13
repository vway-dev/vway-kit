"""스킬 문서 테스트가 공유하는 목록·추출기 — 스킬 집합, 링크 검사, 명령 추출."""

import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

# `scripts/` must not linger on sys.path after this import: scripts/teams_alert.py (and
# friends) resolve `_vway_paths` with `try: import _vway_paths / except ImportError:
# import scripts._vway_paths` (see that module's docstring) so tests can `import
# scripts.xxx` as a package. A `scripts/` dir left on sys.path for the rest of the
# session flips that try-branch for every test file collected afterward (alphabetically,
# that is most of them), loading `_vway_paths` a SECOND time under a different module
# identity — `scripts.teams_alert._host_root is scripts._vway_paths.host_root` then
# reads False even though both come from the same file.
sys.path.pop(0)

import scripts._vway_paths as vp

REPO = Path(__file__).resolve().parent.parent.parent
SKILLS = sorted(REPO.glob("skills/*/SKILL.md"))
SKILL_IDS = [p.parent.name for p in SKILLS]

# Every field the official SKILL.md frontmatter reference defines. Anything else is
# either a typo or a command-era leftover that silently does nothing.
SPEC_FIELDS = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
}

DESCRIPTION_CAP = 1024

# A real markdown link to a .md — not the bare substring ".md", which also fires on
# inline code like `docs/verification/performance.md` and over-skips.
_MD_LINK = re.compile(r"\]\([^)]+\.md[^)]*\)")


def frontmatter(path: Path) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", path.read_text(encoding="utf-8"), re.DOTALL)
    assert m, f"{path.relative_to(REPO)}: no frontmatter block — the skill will not load"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), f"{path.relative_to(REPO)}: frontmatter is not a mapping"
    return data


def body(path: Path) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def known_agents() -> set[str]:
    """`agent` 가 지목할 수 있는 이름 전부 — 공식 빌트인 셋 + 이 플러그인의 `agents/`.

    플러그인은 `agents/` 를 매니페스트 선언 없이 자동 발견시키고, plugins reference 대로 그
    이름은 `<plugin>:<agent>`("플러그인 `deploy-tools` 의 `reviewer` 는 `deploy-tools:reviewer`").
    접두 없는 파일명은 어떤 에이전트도 지목하지 않음."""
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    own = {f"{plugin['name']}:{p.stem}" for p in (REPO / "agents").glob("*.md")}
    return {"Explore", "Plan", "general-purpose"} | own


def fork_frontmatter_problem(data: dict) -> str | None:
    """fork 선언 네 필드가 서로 맞는가 — 어긋나는 방식이 전부 조용함.

    `agent`·`background` 는 `context: fork` 없이는 **아무 일도 안 하는** 스펙 필드라
    철자 검사를 통과한 채 걸린 것처럼 읽힘. `context` 에 `fork` 아닌 값을 적어도 같음.
    없는 `agent` 이름은 오류가 아니라 기본 agent 로 폴백하므로 스킬이 저자가 고르지 않은
    곳에서 돎. `background` 기본값은 true 이고 그쪽은 도구셋이 좁아 Read·Write 가 빠지며,
    마커는 부른 턴이 지난 뒤에 떨어져 게이트가 돌고도 커밋이 막힘."""
    if data.get("context") != "fork":
        # `context` 가 적혀 있으면 그 값이 범인 — 딸린 필드부터 보면 `context: Fork` 오타가
        # "background 가 불활성" 으로 보고돼 고칠 자리를 못 댐.
        if "context" in data:
            return f"context={data['context']!r} — 스펙이 정의하는 값은 fork 하나"
        dependent = sorted(f for f in ("agent", "background") if f in data)
        if dependent:
            return f"{dependent} 는 context: fork 없이는 불활성 — 걸리는 것처럼 읽히고 안 걸림"
        return None
    agent = data.get("agent", "general-purpose")
    if agent not in known_agents():
        return f"agent={agent!r} 가 실재하지 않음 — 오류 없이 기본 agent 로 폴백함"
    if data.get("background") is not False:
        return "background: false 미선언 — 기본값 background 는 도구셋이 좁아 Read·Write 가 빠짐"
    return None


def _split_tools(text: str) -> list[str]:
    """공식 표기는 **공백 또는 쉼표** 구분 — 단 `Bash(git fetch origin)` 의 괄호 안 공백은
    구분자가 아님. 이 저장소가 두 표기를 다 출하하므로(`doc-sync`·`release-commit` 이
    공백 + 범위 인자) 쉼표만 쪼개면 그 파일들에서 판정이 통째로 빠짐."""
    out, buf, depth = [], [], 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (ch == "," or ch.isspace()):
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [t.strip() for t in out if t.strip()]


def _tool_list(value: object) -> set[str]:
    """`allowed-tools` 는 문자열로도 YAML 리스트로도 적힘 — 둘 다 같은 집합으로."""
    if isinstance(value, str):
        return set(_split_tools(value))
    if isinstance(value, list):
        return {t for item in value for t in _split_tools(str(item))}
    return set()


def tool_declaration_problem(data: dict) -> str | None:
    """같은 도구를 허용과 금지에 둘 다 적었는가.

    어느 쪽이 이기든 저자가 적은 선언 하나는 죽음 — 금지가 이기면 필요하다고 적은 도구가
    사라지고, 허용이 이기면 빼겠다고 적은 것이 남음. 어느 쪽인지 공식 문서가 스킬에 대해
    명시하지 않으므로 **모순 자체**를 결함으로 봄."""
    both = _tool_list(data.get("allowed-tools")) & _tool_list(data.get("disallowed-tools"))
    if both:
        return f"allowed-tools 와 disallowed-tools 에 함께 적힌 도구 {sorted(both)} — 제거됨"
    return None


_ASKS_USER = re.compile(r"(?i)\bask the user \((?:structured choice|multi-select)\)")


def fork_body_problem(data: dict, text: str) -> str | None:
    """fork 스킬 본문이 사람에게 묻는 절차를 적었는가.

    질문 도구(Claude Code `AskUserQuestion`)는 서브에이전트에서 제거됨. 본문에 적힌 질문은
    실행되지 않고, 그 자리에서 스킬이 무엇을 해야 하는지는 아무 데도 안 적혀 있음.
    출하 본문은 도구명 대신 행동 어휘(`rules/harness-tools/vocabulary.md`)로 물으므로 둘 다 봄."""
    if data.get("context") != "fork":
        return None
    if "AskUserQuestion" in text or _ASKS_USER.search(" ".join(text.split())):
        return "본문에 사용자 질문 — fork 에서 제거되는 도구라 죽은 절차"
    return None


def bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)


_CODE_FENCE = re.compile(r"^```.*?^```", re.M | re.S)
_CODE_SPAN = re.compile(r"`[^`\n]*`")


def _prose(text: str) -> str:
    """A link inside code is a sample of what the agent should WRITE, not somewhere it
    should go — `[FR-xxx](../srs/README.md)` names a path in the harness being
    generated. Only links the reader is meant to follow are checked."""
    return _CODE_SPAN.sub("", _CODE_FENCE.sub("", text))


def _dead_links(text: str, base: Path) -> list[str]:
    dead = []
    for link in re.findall(r"\]\(([^)]+)\)", _prose(text)):
        if link.startswith(("http://", "https://", "#")):
            continue
        if not (base / link.split("#")[0]).resolve().exists():
            dead.append(link)
    return dead


# A SKILL.md moves detail into references/ to stay under the line cap, so those files
# carry the procedure the agent follows — but the glob above stops at
# SKILL.md, leaving every link inside them unchecked. Same rule, so that moving a
# section between the two cannot change whether its links are verified.
REFERENCES = sorted(REPO.glob("skills/*/references/*.md"))
REFERENCE_IDS = [f"{p.parent.parent.name}/{p.name}" for p in REFERENCES]


SKILL_LINE_CAP = 500


# Trigger signals a model-invocable description may use to say WHEN to load the skill.
# English imperative, Korean "…할 때 …" clause / quoted example requests, or a
# sub-step invocation signal (the skill is invoked by another skill, not user intent).
_TRIGGER = re.compile(
    r"Use (when|for)\b"  # English imperative
    r"|할 때 (사용|호출|부르)"  # Korean "when …ing, use/invoke/call"
    r"|필요할 때"  # Korean "when needed"
    r"|요청에 사용|같은 요청"  # Korean "for requests like"
    r"|invokes\b|가 (부르는|호출)|직접 호출하지"  # sub-step invocation signal
)


def _spawns_the_gate(command: str) -> bool:
    """러너의 **거친 사전 필터**가 이 명령에 게이트를 띄우는가 — 셸에서 읽어 온 그대로.

    이 필터가 정하는 것은 그것 하나뿐. 무엇인지는 `--classify` 가 정함(파이썬 문법).
    적어 두지 않고 **읽는** 이유는 예전과 같음: 여기 베껴 두면 셸이 바뀐 뒤에도 계속 통과함.
    필터는 두 조각이고 둘 다 통과해야 spawn — `git` 낱말을 담은 `case` 갈래와 `_word_re`.
    """
    source = (REPO / "scripts/precommit-runner.sh").read_text(encoding="utf-8")
    assert re.search(r"^\s*\*git\*\)", source, re.M), (
        "precommit-runner.sh 의 `*git*` 갈래가 사라졌다 — 이 가드가 읽는 것이 없다"
    )
    m = re.search(r"^\s*_word_re='(.+)'$", source, re.M)
    assert m, "precommit-runner.sh 가 _word_re 를 더는 정의하지 않는다 — 이 가드는 아무것도 안 잰다"
    ere = m.group(1).replace("[:space:]", r"\s").replace("[:alnum:]", "a-zA-Z0-9")
    bare = _runner_bare(command, source)
    return "git" in command + bare and (
        re.search(ere, command) is not None or re.search(ere, bare) is not None
    )


# 사전 필터가 함께 보는 인용 지운 사본의 단계 — 스크립트 순서대로, 스크립트가 적은 치환과 그
# 치환이 지우는 것. 스크립트에서 **읽어서** 한 단계가 빠지면 흉내가 아니라 여기서 실패함.
_BARE_STEPS = (
    (r"${_filter_src//\\$'\r\n'/}", r"\\\r\n"),
    (r"${_filter_bare//\\$'\n'/}", r"\\\n"),
    ('${_filter_bare//\\"/}', '"'),
    ("${_filter_bare//\\'/}", "'"),
    ("${_filter_bare//\\$/}", r"\$"),
    ("${_filter_bare//\\\\/}", r"\\"),
)


def _runner_bare(command: str, source: str) -> str:
    """러너가 함께 보는 인용 지운 사본. 단계가 하나라도 스크립트에서 사라지면 단언이 실패함."""
    for spelled, _deleted in _BARE_STEPS:
        assert spelled in source, f"precommit-runner.sh 가 {spelled} 단계를 더는 안 함"
    for bypass in _ANSI_C_BYPASS:
        assert bypass in source, f"precommit-runner.sh 가 `$'…'` 우회 {bypass} 를 더는 안 둠"
    bare = command
    for _spelled, deleted in _BARE_STEPS[:2]:  # 우회 판정은 줄이음을 지운 뒤
        bare = re.sub(deleted, "", bare)
    if "$'" in bare:
        tail = " git commit"
    elif "$" in bare and "\\" in bare:
        tail = " git pull"
    else:
        tail = ""
    for _spelled, deleted in _BARE_STEPS[2:]:
        bare = re.sub(deleted, "", bare)
    return bare + tail


# 러너의 `$'…'` 우회 — 스크립트가 적은 그대로. 스크립트가 그것을 지우는 날 흉내도 우회를 멈춤.
_ANSI_C_BYPASS = (
    r"""*"\$'"*) _ansi_c=commit ;;""",
    r"*\$*\\* | *\\*\$*) _ansi_c=pull ;;",
    '[ -z "$_ansi_c" ] || _filter_bare="$_filter_bare git $_ansi_c"',
)


def _is_invocation(word: str, command: str) -> bool:
    """게이트의 **유일한** 호출 문법이 이 명령에서 `git … <word>` 를 읽는가.

    정규식만 보면 안 됨. `\\bgit` 는 `/usr/bin/git` 안에서도 매치되므로, 그 형태가 실제로
    호출로 **세어지는지**는 명령 자리 판정까지 통과해야 정해짐 — `--classify` 가 세는 것과
    같은 두 단계를 여기서도 그대로 밟음.
    """
    return vp.is_invocation(command, word)


CONTINUED = re.compile(r"\\\n\s*")


def _runnable(chunk: str) -> str:
    """`chunk` with its comments blanked, so a comment is never read as a command.

    Both halves bite in this repo: whole-line Korean commentary sits inside the bash blocks,
    and a `# …` tail explains half the commands there. Either can carry the word `commit`
    beside the word `git` and would otherwise be measured as a command that misses the gate.

    The gate's own authority decides what a comment is, rather than a `" #"` split here. That
    split cut inside quotes — `git commit -m "fix #123"` became `git commit -m "fix`, which
    :func:`_has_open_quote` then reads as a command continuing onto the next line, gluing the
    rest of the block into one. Blanked, not dropped, so line numbers and quoting survive.
    """
    out = list(chunk)
    for a, b, kind in vp._shell_regions(chunk):
        if kind == "comment":
            out[a:b] = " " * (b - a)
    return "".join(out)


def _has_open_quote(text: str) -> bool:
    """`text` 가 닫히지 않은 따옴표로 끝나는가 — 즉 명령이 다음 줄로 이어지는가."""
    import shlex

    try:
        shlex.split(text)
    except ValueError:  # "No closing quotation"
        return True
    return False


def _commands_in(chunk: str) -> list[str]:
    """한 조각을 명령 단위로 쪼갬 — 주석은 지우고, 줄이음과 열린 따옴표는 이어 붙임.

    경계 판정을 프로그램마다 따로 두지 않는 이유 — 둘이면 한쪽만 고쳐진 채 다른 쪽이 조용히
    좁아지고, 좁아진 추출기는 아무것도 못 재면서 초록임.
    """
    commands: list[str] = []
    pending = ""
    for line in _runnable(chunk).splitlines():
        pending += line
        # 줄이음이 아니어도, 따옴표가 안 닫혔으면 명령은 다음 줄로 이어짐. `commit`
        # 스킬이 출하하는 `printf '%s\n'` 은 그 개행을 **홑따옴표 안의 리터럴 개행**으로
        # 적으므로, 물리적 줄로 자르면 `' "$msg" | git commit -F -` 라는 따옴표 한가운데서
        # 시작하는 조각이 나옴. 훅은 그런 조각을 절대 받지 않음 — 한 번의 Bash 호출
        # 전체를 받음 — 그래서 조각을 재는 것은 문서가 아니라 추출기를 재는 것임.
        if line.rstrip().endswith("\\") or _has_open_quote(pending):
            pending += "\n"
            continue
        commands.append(pending)
        pending = ""
    if pending:
        commands.append(pending)
    return commands


# 출력에 경로 **이름**이 실리는 git — 목록형만이 아니라 전체 diff 도. `diff --git a/… b/…`
# 헤더가 곧 파일 이름이라, 인용되면 읽는 쪽이 그 hunk 가 어느 파일 것인지 못 댐.
NAMES_A_PATH = re.compile(
    r"--name-only|--name-status|--porcelain"
    r"|(?<![\w-])(ls-files|ls-tree|diff-tree|diff-index|diff|show|log|status)(?![\w-])"
)
# 인라인 span 에서 실행 지시와 산문을 가르는 선. 산문은 서브커맨드 이름만 부르고(`git diff` 가
# 두 끝점을 읽는다는 설명), 실행 지시는 목록 플래그까지 적음. 이 구분이 없으면 결함을 경고하는
# 문장 자체가 가드에 걸려 그 경고를 지우게 됨 — `_issued_git_commands` 의 `-C` 규칙과 같은 논거.
LISTS_EXPLICITLY = re.compile(
    r"--name-only|--name-status|--porcelain"
    r"|(?<![\w-])ls-files(?![\w-])|(?<![\w-])status\s+--short(?![\w-])"
)
# 출력을 안 내는 꼴 — 종료 코드만 봄. 인용 여부가 아무것도 안 바꿈.
PRINTS_NOTHING = re.compile(r"(?<![\w-])(--quiet|-q)(?![\w-])")


def _path_listing_commands(text: str) -> list[str]:
    """출하 문서가 발행하는 git 중 **경로 이름을 출력에 싣는** 것.

    펜스 안은 전부 실행 지시라 넓게 보고, 인라인 span 은 목록 플래그를 적은 것만 — 두 자리의
    성격이 다름. 줄이음은 편 뒤 판정.
    """
    out = []
    fenced = [c for chunk in bash_blocks(text) for c in _commands_in(chunk)]
    inline = re.findall(r"`([^`\n]*\bgit\b[^`\n]*)`", text)
    for command, gate in [(c, NAMES_A_PATH) for c in fenced] + [
        (c, LISTS_EXPLICITLY) for c in inline
    ]:
        flat = CONTINUED.sub(" ", command).strip()
        if not re.search(r"\bgit\b", flat):
            continue
        if gate.search(flat) and not PRINTS_NOTHING.search(flat):
            out.append(flat)
    return out


def _issued_git_commands(text: str) -> list[str]:
    """Every `git …` command a shipped document tells the agent to run, comments removed and
    each continued command kept whole — with its backslashes, because that is the text the
    hook is handed.

    Inline spans count only when they carry `-C`: the prose deliberately quotes the broken
    form as a counter-example, and a guard that failed on the warning against the bug would
    force the warning to be deleted. The `-C` forms are the ones a document tells the
    agent to run — `commit`'s worktree variant has to be inline because `$msg` cannot cross
    into a second block.
    """
    inline = [s for s in re.findall(r"`([^`\n]*\bgit\b[^`\n]*)`", text) if "-C" in s]
    commands = [c for chunk in bash_blocks(text) + inline for c in _commands_in(chunk)]
    return [c for c in commands if re.search(r"\bgit\b", c)]


# `gh` 는 온전한 낱말로만 — `gh-pages` 안에서 매치되면 안 됨.
GH_PROGRAM = re.compile(r"(?<![\w-])gh(?![\w-])")
GH_WORKFLOW_RUN = re.compile(r"(?<![\w-])workflow\s+run(?![\w-])")


def _issued_gh_commands(text: str) -> list[str]:
    """출하 문서가 실행하라고 적은 `gh …` — 커맨드 블록에 선 것만.

    `git` 쪽의 인라인 예외는 없음. 그 예외는 `commit` 의 worktree 형태가 `$msg` 때문에
    블록에 못 들어가서 생긴 것이라 여기 대응물이 없고, 산문에 인용된 반례를 재면 그 반례를
    지우는 압력이 됨.
    """
    commands = [c for chunk in bash_blocks(text) for c in _commands_in(chunk)]
    return [c for c in commands if GH_PROGRAM.search(c)]


def _mentions_subcommand(word: str, command: str) -> bool:
    """`command` carries `word` as a whole word — `commit-graph` and `merge-base` stay out, the
    same exclusion the gate's own terminator makes.

    Deliberately loose rather than anchored on the subcommand position: the malformed forms this
    guard exists to catch have no parseable position to anchor on (`git ${WT:+-C "$WT"} commit`
    has no flag run and no subcommand token), so anchoring would blind it to exactly those. The
    price is that a runnable line merely naming the word elsewhere — `git config --get
    commit.template` — is measured too and fails here; move such a line out of the block.
    """
    return bool(re.search(rf"(?<![\w-]){word}(?![\w-])", command))


# Every instruction document this plugin ships, not only the skills: the commit forms live in
# `skills/commit`, and the merge forms live in `rules/merge-strategy.md` beside the skills
# that issue them, so a skills-only corpus would read only half the merge subject. The skills
# glob recurses because `references/` and `templates/` are shipped instructions too.
GIT_DOCS = sorted(
    set(REPO.glob("skills/**/*.md")) | set(REPO.glob("rules/*.md")) | set(REPO.glob("agents/*.md"))
)
GIT_DOC_IDS = [p.relative_to(REPO).as_posix() for p in GIT_DOCS]
