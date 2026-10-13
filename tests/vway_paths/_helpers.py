"""경로·스캐너 테스트가 공유하는 헬퍼 — 워크트리 저장소 세우기, 스캐너 호출."""

import subprocess
from pathlib import Path


def _run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def _repo_with_worktree(tmp_path: Path):
    """main repo + feature/x 체크아웃한 형제 worktree 를 만들어 (main, wt) 반환."""
    main = tmp_path / "main"
    main.mkdir()
    _run(["git", "init", "-b", "main"], main)
    _run(["git", "config", "user.email", "t@t"], main)
    _run(["git", "config", "user.name", "t"], main)
    (main / "f.txt").write_text("x", encoding="utf-8")
    _run(["git", "add", "."], main)
    _run(["git", "commit", "-m", "init"], main)
    wt = tmp_path / "main-feature"  # 형제 레벨 + 'main' 접두사(startswith 함정 케이스)
    _run(["git", "worktree", "add", str(wt), "-b", "feature/x"], main)
    return main, wt


# ── 셸이 **돌리는** 인용 텍스트 ────────────────────────────────────────────────
# 인용 span 이 데이터인 것은 무언가 그것을 실행하기 전까지. 아래는 정밀한 읽기(마스크)가
# 스스로 잡아야 하는 것들 — 그물이 아니라 스캐너의 일.
RUN_BY_THE_MASK = [
    # 겹따옴표 안의 치환은 셸이 진짜로 돌림(실측: git 셰임에 커밋이 남음). span 을
    # 통째로 덮으면 그 커밋이 사라지고 훅이 exit 0.
    'echo "$(git commit -m x)"',
    "X=`git commit -m x`",
    # 백틱은 **자기 자신이 닫는** 문자. 여는 것으로 세면 짝이 영영 안 맞아 스캔이 명령의
    # 나머지를 삼키고, 그 뒤의 진짜 커밋이 통째로 사라짐.
    'echo "`date`" && git commit -m x',
    'msg="`echo hi`"; git commit -m "$msg"',
    # 구분자를 인용하지 않은 heredoc 은 확장이 켜져 있음 — 본문의 치환은 셸이 돌리는 명령.
    "cat <<EOF\nhello $(git commit -m x)\nEOF",
    # 명령 자리의 인용 span 은 **프로그램 이름**.
    "'git' commit -m x",
]


NET_ELEMENTWISE = [
    # 그물은 원소 **하나**를 읽음. 문자열 전체로 읽으면 python 이나 bash 옆에서 도는
    # 읽기 전용 명령이 전부 차단됨(실측: 이 둘이 그렇게 차단됨).
    "python3 --version && grep 'git commit' f",
    "bash --version; rg 'git commit' .",
    "python3 -c 'print(1)' && echo 'git commit -m x'",
    # 복합 명령의 몸통도 원소로 갈림. 예약어가 인덱스 0 에 서는 원소에서 프로그램 스캔이
    # 되감기에 걸리면 `grep` 이 안 보이고 원소가 면제를 못 받아 전부 차단됨(상류의 결함).
    "if grep -q 'git commit' f; then echo yes; fi",
    "for f in a b; do grep 'git commit' $f; done",
    # 파이프는 경계가 **아님**. 단계가 전부 리더이므로 여기서도 면제됨 — 단계 하나라도
    # 리더가 아니면 그때는 차단되고, 그 corpus 는 REVIEW_REGRESSIONS 가 붙듦.
    "cat f | grep 'git commit' | head -5",
    "rg 'git commit' . | sort | uniq",
]


# ── 인터프리터 그물 ───────────────────────────────────────────────────────────
# 텍스트를 셸로 나르는 **통로**는 끝이 없고(`-c` 인자·here-string·heredoc·파이프라인·치환),
# 그 텍스트를 **실행하는 프로그램**은 목록. 그래서 그물은 명령이 그 프로그램 중 하나로
# **시작하는지**를 묻고, 그럴 때만 같은 문법을 인용 지운 판 위에서 한 번 더 읽음.
NET_INVOCATIONS = [
    ("printf 'git commit -m x' | bash", "commit"),
    ("bash -c 'git commit -m x'", "commit"),
    ('eval "git commit -m x"', "commit"),
    # 명령 자리의 치환은 자기가 **출력하는** 것을 돌림. 안에 적힌 리더의 이름을 그 원소가
    # 돌리는 프로그램으로 읽으면 면제가 적용돼 게이트가 통째로 꺼짐(실측: bash 가 이
    # 커밋을 진짜로 돌림).
    ("$(echo 'git commit -m x')", "commit"),
    # 자기 인자에 적힌 명령을 돌리는 프로그램들. 실행 목록을 방아쇠로 쓰던 판에서는
    # 이름이 없어 그물이 아예 안 봤고, bash 는 커밋을 돌렸다(실측).
    ("""awk 'BEGIN{system("git commit -m x")}'""", "commit"),
    ('echo "git commit -m x" | sh', "commit"),
    ('bash -c -- "git commit -m x"', "commit"),
    ("eval $'git commit -m x'", "commit"),
    ("bash <<< 'git commit -m x'", "commit"),
    ("bash -s <<< 'git commit -m x'", "commit"),
    ("""perl -e 'system("git commit -m x")'""", "commit"),
    ("bash <<'EOF'\ngit commit -m x\nEOF", "commit"),
    ("printf 'git merge --no-ff dev' | bash", "merge"),
    ("bash <<< 'git merge --squash feature/x'", "merge"),
    ("source /dev/stdin <<< 'git commit -m x'", "commit"),
    ("node -e \"require('child_process').execSync('git commit -m x')\"", "commit"),
    # 백슬래시로 이스케이프한 따옴표도 인용 — 그물은 그것이 이스케이프하는 따옴표와
    # 함께 지워야 함. 여기서 실제로 도는 스크립트는 `git "commit" -m x`.
    ('bash -c "git \\"commit\\" -m x"', "commit"),
    ("{ bash <<< 'git commit -m x'; }", "commit"),
    # 리다이렉션이 이름에 **붙는** 철자. 뒤 경계를 공백류로 좁히면 통째로 빠져나감.
    ('bash<<<"git commit -m x"', "commit"),
    ("sh<<EOF\ngit commit -m x\nEOF", "commit"),
    # 명령 앞에 서는 것들 — 대입 접두와 복합 명령의 몸통. `at_command_start` 가 이미 앎.
    ('VAR=1 bash -c "git commit -m x"', "commit"),
    ('for f in a; do bash -c "git commit -m x"; done', "commit"),
    ('if true; then bash -c "git commit -m x"; fi', "commit"),
    ("/usr/bin/bash -c 'git commit -m x'", "commit"),
    ("C:/Git/bin/bash.exe -c 'git commit -m x'", "commit"),
    # 실행 플래그가 붙은 판독기는 면제를 잃음 — 이름만으로 면제를 주면 그 플래그가
    # 돌리는 명령을 게이트가 통째로 못 봄(실측: bash 가 커밋을 진짜로 만듦).
    ("printf -v 'a[$(git commit -m x)]' 1", "commit"),
    ("printf -v c 'git commit -m x'; $c", "commit"),
    ("rg --pre git x commit", "commit"),
    ("printf 'git commit -m x\\n' | sort --compress-program=bash", "commit"),
    ("printf 'git commit -m x\\n' | sort --compress-program bash", "commit"),
    # 판독기가 아닌 원소의 heredoc 본문은 늘 스크립트. 인터프리터 이름 목록을 방아쇠로
    # 쓰면 목록에 없는 실행기 하나가 게이트를 끔.
    ('awk -f - <<EOF\nBEGIN{system("git commit -m x")}\nEOF', "commit"),
    (". /dev/stdin <<EOF\ngit commit -m x\nEOF", "commit"),
    # 프로세스 치환은 원소 하나 — 안의 `;` 로 자르면 잘린 꼬리가 `echo` 만의 원소가 돼
    # 면제를 얻음.
    ('bash <(echo; echo "git commit -m x")', "commit"),
    # xargs·parallel 은 하위 명령을 표준 입력에서 받아 인자 순서가 뒤집힘.
    ("echo commit -m x | xargs git", "commit"),
    ("echo commit -m x | parallel git", "commit"),
    ("echo merge --no-ff dev | xargs git", "merge"),
]


NET_MUST_NOT_FIRE = [
    # 이어 붙인 낱말도 프로그램이 git 이 아니거나 서브커맨드 자리가 아니면 인자일 뿐.
    "grep -rn \"git com''mit\" .",
    "git log --grep=com''mit",
    "git log --oneline -- 'com'mit.txt",
    'echo bash and then "git commit -m x"',
    "git log $'commit'",
    "# git $'commit' -m x",
    "git log -1 --format=%s <<'EOF'\ngit $'commit' -m x\nEOF",
    # 텍스트를 실행하는 프로그램이 없으니 그물은 아예 보지 않음 — 낱말은 데이터로 남음.
    'grep -rn "git commit" scripts/',
    "git log -1 --format=%s <<'EOF'\ngit -C /wt commit -m x\nEOF",
    'git -C "/c/wt" log --oneline -5 && echo "now commit"',
    "git -c commit.gpgsign=false log --oneline",
    # 인자로 **이름만** 등장한 인터프리터는 이 명령이 실행하는 것이 아님. 개발자가 온종일
    # 쓰는 모양이고, `sh` 는 옵션 값에도 흔히 나오는 두 글자.
    'rg "git commit" --type sh',
    'rg -t sh "git commit"',
    'ls /bin/sh && echo "git commit -m x"',
    'which bash; echo "git commit -m x"',
    'echo bash and then "git commit -m x"',
    'shellcheck -s bash scripts/*.sh && grep -rn "git commit" .',
    # 주석은 무엇이 옆에서 돌든 코드가 아님.
    "bash x.sh  # remember to git commit -m x",
    # 아무것도 인용하지 않는 백슬래시는 경로 구분자. 지우는 순간 셸에 없던 토큰 경계가
    # 생겨, bash 가 **파일 이름**으로 받는 인자가 호출로 읽힘(실측: 모든 이스케이프를
    # 지우면 아래 둘째 줄이 발화함).
    "bash C:\\git\\commit\\run.sh",
    "bash 'git\\x commit'",
    # 명령 목록처럼 **보이는** 인용 문자열도 여전히 데이터. 프로그램은 마스크에서 찾아야
    # 함 — 두 번째 판에서 찾으면 이 전부가 발화함.
    "echo \"; bash -c 'git commit -m x'\"",
    'echo "| bash" && grep -rn "git commit" .',
    "cat <<'EOF'\n; bash -c 'git commit -m x'\nEOF",
    # 인터프리터는 있는데 호출이 없는 경우.
    "bash -c 'echo hello'",
    "python3 -c 'import sys; print(sys.version)'",
    # 대입의 **값**에 든 이름은 이 명령이 시작하는 프로그램이 아님 — 시작하는 것은 `make`.
    # 토큰 안의 `=` 를 안 보면 `at_command_start` 가 `PYTHON=/usr/bin/` 을 디렉터리
    # 접두로 받아 읽기 전용 명령을 차단함(실측).
    'PYTHON=/usr/bin/python3 make test && rg "git commit" .',
    'SHELL=/bin/bash make -n && rg "git commit" .',
    # 실행 플래그의 **값**이 프로그램 이름이 될 수 없으면 아무것도 안 돎 — 공백을 담은
    # 값은 존재할 수 없는 이름임. 이걸 안 가르면 흔한 검색이 미분류 세션에서 차단됨.
    "rg --pre 'git commit' pattern .",
    "sort --compress-program='git commit -m x' f",
    # 플래그는 그 원소의 프로그램 것 — `rg -v` 의 `-v` 는 `printf` 의 것이 아님.
    'printf x | rg -v y && rg "git commit" .',
    "printf x | rg -v 'git commit'",
    # `--pre-glob` 은 `--pre` 가 아님 — 접두만 보면 흔한 검색이 막힘.
    "rg --pre-glob '*.md' 'git commit' .",
    # `<(…)` 의 출력은 명령이 아니라 파일 이름 — 요소를 자르지 않되 발화도 안 함.
    'cat <(echo "git commit")',
    'cat <(echo; echo "git commit -m x")',
    # `commit.gpgsign`·`committing` 은 따로 선 `commit` 낱말이 아님 — xargs 그물의 낱말
    # 판정이 토큰 경계를 안 보면 이 둘이 통째로 오차단됨.
    "echo x | xargs git config commit.gpgsign false",
    "git log | xargs -I{} echo committing {}",
    # 맨몸 백슬래시는 Windows 경로 구분자이지 토큰 경계가 아님 — 경계로 읽으면 인용된
    # 경로 안의 `\git`·`\commit` 이 따로 선 낱말이 되어 오차단됨.
    'printf -v x "C:\\git\\commit\\y"',
    'rg --pre cat "C:\\git\\commit\\log.txt"',
    "find . -name '*.log' | xargs grep 'C:\\git\\commit\\path'",
]


# 면제가 목록이므로, 목록에 없는 프로그램에 인용된 커밋을 건네는 명령은 게이팅됨. 그
# 방향이 이 게이트가 틀려도 되는 쪽이고, 사용자는 deny 를 보고 우회 가능. 여기 적는
# 것은 그 값을 세어 두기 위해서 — 오차단이 늘면 이 목록도 늘어남.
DELIBERATE_OVER_GATES = [
    # 로컬 셸은 아무 커밋도 안 돌림(실측: git 셰임에 호출이 안 남음). 그래도 `ssh` 는
    # 자기 인자를 원격 셸에 넘기므로 읽기 전용이 아니고, 면제를 얻지 못함.
    'ssh host "git commit -m x"',
    # `-exec` 는 프로그램과 그 인자를 받음. 이 철자에서는 `;` 가 인용되지 않아 find 가
    # 불완전한 채로 죽지만, 게이트는 그것까지 알지 못함.
    "find . -name x -exec git commit -m x ;",
    # 표준 입력이 비어 있어 아무것도 안 돌지만, `xargs` 는 자기 인자를 프로그램으로 돌림.
    "xargs -I{} git commit -m x",
    # `LESSOPEN` 이 안 선 셸에서는 아무것도 안 돈다(실측). 그래도 그 변수는 명령이 아니라
    # 환경에 있어 명령만 봐서는 알 수 없고, 그것을 아는 유일한 방법이 `less` 를 리더로
    # 안 세는 것.
    "grep 'git commit -m x' f | less",
    # `more` 는 여러 호스트에서 `less` 와 같은 프로그램(이 호스트에는 아예 없음, 실측).
    "more 'git commit -m x'",
    # 판독기가 아닌 원소의 heredoc 본문은 목록이 그 이름을 알든 모르든 스크립트로 읽힘.
    # 그 비용이 이것 — 본문이 커밋을 **언급만** 해도 게이팅됨. 목록을 방아쇠로 쓰던 판은
    # 반대로 틀렸음: 목록에 없는 이름 하나가 아무 말 없이 게이트를 껐음.
    "nodemon <<EOF\ngit commit -m x\nEOF",
    "bashful <<EOF\ngit commit -m x\nEOF",
    "rebash <<EOF\ngit commit -m x\nEOF",
    # 같은 값을 치르는 일상 명령들 — 본문을 **저장·전송**만 하는데도 면제 목록에 없어
    # 게이팅됨. 면제로 풀 수 있는 오차단이고(이름을 목록에 더하면 됨), 반대 방향은
    # 풀 수 없음: 실행 통로를 세던 판은 빠뜨린 통로마다 게이트가 조용히 꺼졌음.
    "tee docs/notes.md <<EOF\ngit commit -m x 로 커밋한다\nEOF",
    "gh pr create --body-file - <<EOF\n- git commit -m x\nEOF",
    "curl -d @- https://example.test <<EOF\ngit commit -m x\nEOF",
    "mail -s note me <<EOF\ngit commit -m x\nEOF",
]


# 독립 리뷰가 실측으로 찾아낸, 이 변경이 **새로 만든** 구멍들. 전부 HEAD 는 차단하던
# 명령이고(러너 exit 2 → 0), 실제 bash 가 커밋을 돌림.
REVIEW_REGRESSIONS = [
    # 확장이 켜진 heredoc 본문이 **치환으로 시작하면** `_expanding` 이 그 앞에 리터럴 구간을
    # 만들지 않아 본문이 어디서 시작하는지 기록이 사라졌고, 본문을 여는 개행이 원소 경계로
    # 읽혀 인터프리터와 스크립트가 서로 다른 원소로 찢어짐.
    ("bash <<EOF\n$(pwd)/setup.sh\ngit commit -m x\nEOF", "commit"),
    ("bash <<EOF\n`pwd`\ngit commit -m x\nEOF", "commit"),
    ("bash <<EOF\n$(pwd)\ngit merge --no-ff stage\nEOF", "merge"),
    # 파이프는 원소 경계가 아니므로 한 원소에 여러 명령이 옴. 이름을 원소 전체에서 한 번에
    # 모으면, 이름을 못 뽑은 단계가 뒤 단계의 리더 이름 뒤에 숨어 면제를 받음.
    ("bash -c 'git commit -m x' | cat", "commit"),
    ("eval 'git commit -m x' | cat", "commit"),
    ("bash <<< 'git commit -m x' | cat", "commit"),
    ("printf 'git commit -m x' | bash | cat", "commit"),
    # 이름을 남기지 않는 선두들 — 리다이렉션·부정·명령 자리의 치환.
    (">out git commit -m x | cat", "commit"),
    ("<f git commit -m x | cat", "commit"),
    ("! bash -c 'git commit -m x' | cat", "commit"),
    ("! $(echo 'git commit -m x') | cat", "commit"),
    ("$(echo 'git commit -m x') | cat", "commit"),
    ("time 'git' commit -m x | cat", "commit"),
    ("if true; then 'git' commit -m x | cat; fi", "commit"),
]


# 2라운드 리뷰가 실측으로 찾아낸, 1라운드 **수정이** 새로 만든 구멍들. 전부 이식 전
# (`c311153`)에는 차단되던 명령이고, 실제 bash 가 커밋을 돌림.
ROUND2_REGRESSIONS = [
    # 도입부와 본문 **사이**의 구분자를 원소 경계로 읽으면 본문이 다음 원소로 넘어가고,
    # 거기 리더가 하나 있으면 그 원소가 면제를 받아 본문의 진짜 커밋이 아무에게도 안 읽힘.
    ("bash <<EOF && echo ok\ngit commit -m x\nEOF", "commit"),
    ("bash <<EOF; echo ok\ngit commit -m x\nEOF", "commit"),
    ("bash <<EOF || echo fail\ngit commit -m x\nEOF", "commit"),
    ("bash -s <<EOF && echo ok\ngit commit -m x\nEOF", "commit"),
    ("bash <<'EOF' && echo ok\ngit commit -m x\nEOF", "commit"),
    ("bash <<EOF && cat f\ngit commit -m x\nEOF", "commit"),
    ("bash <<EOF && wc -l f\ngit commit -m x\nEOF", "commit"),
    ("sh <<EOF ; echo done\ngit commit -m x\nEOF", "commit"),
    ("bash <<E1 && cat <<E2\ngit commit -m x\nE1\nnote\nE2", "commit"),
    ("printf x | bash <<EOF && echo ok\ngit commit -m x\nEOF", "commit"),
    ("bash <<EOF && echo ok\ngit merge --no-ff stage\nEOF", "merge"),
]


# 3라운드. **전부 실제 bash 가 커밋을 돌리는 것으로 실측**(샌드박스 repo 의 커밋 수가
# 늘어남). `less` 두 줄은 `LESSOPEN` 이 설정된 셸에서 측정.
ROUND3_REGRESSIONS = [
    # 명령이 프로그램 앞에 지닐 수 있는 것(`!`·리다이렉션·대입)은 이름이 아님. 거기서
    # 멈추면 그 자리의 프로그램이 면제 판정에서 빠지고, 앞 명령의 `cat` 하나가 원소 전체를
    # 리더로 만듦. `&` 는 원소 경계가 아니라 같은 원소의 다음 명령.
    ("cat f & > /dev/null 'git' commit -m x", "commit"),
    ("cat f & 2>&1 'git' commit -m x", "commit"),
    ("cat f & ! 'git' commit -m x", "commit"),
    ("cat f & > /dev/null 'git' merge --no-ff stage", "merge"),
    # 리다이렉션의 피연산자가 떨어져 서면 `at_command_start` 가 그 자리를 명령 자리로 보지
    # 않음. 그러니 조건부 `git` 면제를 여기 주면 두 읽기가 **함께** 놓침 — 이식이 걸음을
    # 접두 너머로 보내면서 실제로 한 번 그렇게 됨(HEAD 에서는 차단되던 명령).
    ("> /dev/null git commit -m x", "commit"),
    ("2>&1 git commit -m x", "commit"),
    ("< f git commit -m x", "commit"),
    ("> f git merge --no-ff feature", "merge"),
    ("cat f | > /dev/null git commit -m x", "commit"),
    # 치환이 **어디에 있든** 그 원소가 돌리는 것은 거기 적힌 이름이 아님. 자리를 물으면
    # 명령이 지닐 수 있는 접두를 전부 알아야 하는데, 하나만 빠져도 면제가 되돌아옴.
    ("cat `'git' commit -m x`", "commit"),
    # 치환 **안**의 구분자는 원소 경계가 아님. 거기서 자르면 꼬리가 리더만 든 원소가 되어
    # 면제를 받고, 치환이 출력하는 진짜 커밋을 아무도 안 읽음.
    ("$(cat /dev/null; echo git commit -m x)", "commit"),
    ("cat f; $(true; echo git commit -m x)", "commit"),
    # `less` 가 돌리는 명령은 자기 **환경**이 지목한다(`LESSOPEN`). 대부분 배포판이 login
    # profile 에서 설정하므로 명령 텍스트에는 아무 흔적도 없음. 둘 다 `LESSOPEN` 이 선
    # 셸에서 실제로 커밋을 돌렸다(실측).
    ("less 'git commit -m x'", "commit"),
    ("LESSOPEN='|git commit -m x %s' less -f f", "commit"),
]


STORED_HEREDOCS = [
    # 본문이 데이터로 남는 것은 그 원소가 **면제를 받을 때**뿐. 판을 가르는 것은 더는
    # 인터프리터 이름이 아님 — 이름이 방아쇠였을 때는 목록에 없는 실행기 하나가 아무 말
    # 없이 게이트를 껐고, 목록을 늘려도 다음 이름이 또 나왔음. 지금 판을 가르는 것은
    # 면제이고, 면제는 목록이라 그 목록의 구멍은 오차단으로만 나타남.
    "cat <<EOF\ngit commit -m x 로 커밋한다\nEOF",
    "head -20 <<EOF\n- git commit -m x\nEOF",
    "grep -n x <<EOF\ngit merge --no-ff stage\nEOF",
    # 조건부 `git` 면제도 같음 — `git log` 는 자기 본문을 명령으로 안 돌림.
    "git log -1 --format=%s <<EOF\ngit -C /wt commit -m x\nEOF",
]


READ_ONLY_GIT = [
    # 이 저장소에서 매일 쓰는 모양들. 전부 미분류 커밋으로 차단됐었다(실측 43개 중 9개).
    "git grep 'git commit'",
    "git log --grep='git commit'",
    "git log -S 'git commit -m' --oneline",
    "git log --oneline | grep 'git commit'",
    "git show HEAD | grep 'git commit'",
    "git blame scripts/_vway_paths.py | grep 'git commit'",
    "git log --format='%s' | rg 'git commit'",
    "git grep -n 'git merge'",
    "git diff c311153 a257765 | grep 'git merge'",
    # 면제를 취소하는 철자는 그 **단계**에서 물어야 함. 원소 전체에서 물으면 뒤 단계의
    # `grep -c` 가 앞 단계의 git 면제를 취소해, 평범한 명령이 미분류 커밋으로 막힘.
    "git log --oneline | grep -c 'git commit'",
    # `run`·`foreach` 는 자기 서브커맨드에 묶어서만 봄. 낱말만 보면 경로가 그 이름인
    # 읽기 전용 명령이 우회로 없이 막힌다(실측 4건).
    "git grep 'git commit' -- run",
    "git log -S 'git commit' -- run",
    "git log --grep='git commit' -- run",
    "git grep 'git commit' -- foreach",
    # 인자 자리의 맨몸 `git` 도 호출이 아님. 낱말 단위 읽기를 **선두 고정**으로 걸지 않으면
    # 여기서 매치돼 우회로 없이 막힘 — 인용이 없어 공백 치환도 그것을 못 막음.
    "git grep git commit",
    "git log --oneline -- git commit",
]


GIT_RUNS_A_COMMAND = [
    # `--exec`/`-x` 는 alias 도 config 도 아닌 평범한 플래그. 실제 git 으로 재 보면
    # 커밋 수가 늘어남 — 면제를 조건 없이 주면 우회로가 이 한 줄.
    "git rebase --exec 'git commit --allow-empty -m pwn' --root",
    "git rebase -x 'git commit --allow-empty -m pwn' --root",
    'git rebase --exec "git commit --allow-empty -m pwn" --root',
    "git -c alias.x='!git commit --allow-empty -m pwn' x",
    "git -c core.pager='git commit -m pwn' log",
    "git fetch --upload-pack='git commit -m pwn' file:///srv/r",
]


PAIRED_HEREDOCS = [
    # **앞** heredoc 의 본문이 확장되면(치환이 들었으면) 본문 영역이 조각으로 쪼개져 시작이
    # 여러 개가 됨. 정렬 후 zip 하면 뒤 heredoc 의 도입부가 앞 본문의 조각과 짝지어지고,
    # 그 구간은 끝이 시작보다 앞섬 — 뒤 도입부 줄의 구분자가 경계가 되어 본문이 인터프리터
    # 에서 떨어져 나가고, 리더만 남은 원소가 면제를 받아 게이트가 꺼진다(실측 True → False).
    ("cat <<A\nhello $(echo z) world\nA\nbash <<B && echo ok\ngit commit -m x\nB", "commit"),
    ("cat <<A\nhello $(echo z) world\nA\nbash <<B && wc -l f\ngit commit -m x\nB", "commit"),
    ("cat <<A\n$(echo z)\nA\nsh <<B ; cat f\ngit commit -m x\nB", "commit"),
    ("cat <<A\n$(date)\nA\nbash <<B && echo ok\ngit merge --no-ff stage\nB", "merge"),
    ("cat <<A && bash <<B\nhello $(echo z) world\nA\ngit commit -m x\nB", "commit"),
]


SPELLED_WITH_QUOTES = [
    # 셸은 **모든 낱말**에 인용 제거를 함. 다섯 철자 전부 실제 git 으로 커밋을 만들었고
    # (커밋 수 1 → 6), 마스크만 보면 전부 "커밋 아님" — `--classify` 가 `ok=1` 만 내
    # 러너가 게이트 단계 전에 exit 0 했다(실측).
    ("git 'commit' --allow-empty -m p", "commit"),
    ('git "commit" --allow-empty -m p', "commit"),
    ("git c'ommit' --allow-empty -m p", "commit"),
    ("git com''mit --allow-empty -m p", "commit"),
    ("git \\commit --allow-empty -m p", "commit"),
    ("git --no-pager 'commit' --allow-empty -m p", "commit"),
    ("git -C /wt 'commit' -m x", "commit"),
    ("/usr/bin/git 'commit' -m x", "commit"),
    ("git.exe 'commit' -m x", "commit"),
    ("echo a && git 'commit' -m x", "commit"),
    ("git 'merge' stage", "merge"),
    ('git "merge" --no-ff stage', "merge"),
    # 인용이 **프로그램 낱말** 안에 들어도 같음 — 마스크에는 `git` 이 아예 없음.
    ("gi't' commit -m x", "commit"),
    ('gi"t" commit -m x', "commit"),
    ("gi''t commit -m x", "commit"),
    ("g\\it commit -m x", "commit"),
    ("gi't' merge --no-ff fix/x", "merge"),
    ("env gi't' commit -m x", "commit"),
]


QUOTE_JOINED = [
    # 인용 제거는 한 낱말의 조각을 이음 — 따옴표나 보통 문자 앞 백슬래시로 쪼개진 낱말도 그
    # 낱말임(bash 와 스텁 `git` 으로 확인). `$'…'`·낱말 한가운데의 줄이음은 낱말 단위 읽기도
    # 놓쳤음(실측: 러너 exit 0).
    ("git com''mit -m x", "commit"),
    ('git com""mit -m x', "commit"),
    ("git c\\ommit -m x", "commit"),
    ("g''it commit -m x", "commit"),
    ("git $'commit' -m x", "commit"),
    ('git $"commit" -m x', "commit"),
    ("git -C /tmp/wt com''mit -m x", "commit"),
    ("cd /tmp/wt && git c\\ommit -m x", "commit"),
    # `-C` 는 무엇으로 시작하든 다음 낱말을 받음: `-` 는 `-` 라는 이름의 디렉터리
    ("git -C - commit -m x", "commit"),
    ("git -C -x -C - merge --no-ff dev", "merge"),
    # 아무 낱말이나 값으로 받는 옵션은 `-C` 도 값으로 받으므로 `commit` 이 그대로 서브커맨드
    ("git --namespace -C commit -m x", "commit"),
    ("git --work-tree -C commit -m x", "commit"),
    ("git mer''ge --no-ff dev", "merge"),
    ("git com$'mit' -m x", "commit"),
    ('git com$"mit" -m x', "commit"),
    ("g$''it commit -m x", "commit"),
    # 줄이음은 낱말을 가르기 전에 지워짐 — 낱말 한가운데여도. CRLF 판은 bash 에선 줄이음이
    # 아니지만 Windows 훅 페이로드의 줄끝이라 함께 이음(과다 게이팅 쪽).
    ("git co\\\nmmit -m x", "commit"),
    ("gi\\\nt commit -m x", "commit"),
    ("git co\\\r\nmmit -m x", "commit"),
    # 원소 선두가 아닌 명령 자리 — 판독기 `git` 자신의 서브커맨드도 거기서 이어 붙여야 함
    # (실측: 선두 고정 판에서 러너 exit 0, bash 스텁 argv 는 `commit`).
    ("echo a | git $'commit' -m x", "commit"),
    ("( git $'commit' -m x )", "commit"),
    ("{ git $'commit' -m x; }", "commit"),
    ("! git $'commit' -m x", "commit"),
    ("time git $'commit' -m x", "commit"),
    ("case a in a) git $'commit' -m x;; esac", "commit"),
    ("for i in 1; do git $'commit' -m x; done", "commit"),
    ("git log -1 | git $'commit' -m x", "commit"),
    ("if true; then git co\\\nmmit -m x; fi", "commit"),
    ("echo a | git co\\\nmmit -m x", "commit"),
    ("/usr/bin/git $'commit' -m x", "commit"),
    ('/tmp/stub/git $"commit" -m x', "commit"),
    ("/tmp/stub/git co\\\nmmit -m x", "commit"),
    ("( git $'merge' --no-ff dev )", "merge"),
    ("echo | git $'merge' --ff-only dev", "merge"),
    # 큰따옴표 안의 줄이음도 bash 는 지움 — 인용 안 공백을 낱말 글자로 바꿀 때 개행은 빼야 함
    # (실측: 개행까지 바꾼 판에서 러너 exit 0).
    ('git "co\\\nmmit" -m x', "commit"),
    ('( git "co\\\nmmit" -m x )', "commit"),
    ('git -C /tmp "co\\\nmmit" -m x', "commit"),
    ('cd /tmp && /usr/bin/git "co\\\nmmit" -m x', "commit"),
    # `$'…'` 은 이스케이프를 풂 — 16진·8진·유니코드로 철자한 서브커맨드.
    ("git $'\\x63ommit' -m x", "commit"),
    ("git $'co\\155mit' -m x", "commit"),
    ("git $'\\u0063ommit' -m x", "commit"),
]


OPENS_A_COMMAND = [
    # 셸이 명령을 여는 자리인데 `at_command_start` 가 부정하던 낱말들. 정밀한 읽기가 명령
    # 자리를 부정하고 그물은 `git` 면제로 건너뛰어, 두 fail-CLOSED 게이트가 함께 꺼짐
    # (실측: 러너 exit 0, 실제 bash 는 커밋을 만듦).
    ("if git commit -m x; then :; fi", "commit"),
    ("while git commit -m x; do break; done", "commit"),
    ("until git commit -m x; do :; done", "commit"),
    ("if git merge --no-ff fix/x; then :; fi", "merge"),
    ("case x in x) git merge --no-ff fix/x;; esac", "merge"),
    ("if ! git commit -m x; then :; fi", "commit"),
]


CONTINUED_LINES = [
    # 훅이 받는 명령은 Windows 에서 온다(Invariant #2). `\`+CR 이 이스케이프로 안 읽히면
    # `_SEPARATOR_RE` 의 `\r` 이 피연산자 영역을 즉시 끊어 게이트가 꺼짐 — 실제 bash 는
    # argv 로 `commit` 을 넘긴다(실측).
    ("git \\\n commit -m x", "commit"),
    ("git \\\r\n commit -m x", "commit"),
    ("git merge \\\r\n --no-ff fix/x", "merge"),
    ("git \\\r\n merge \\\r\n --squash feature/x", "merge"),
]


GIT_RUNS_A_SUBCOMMAND = [
    # 플래그만이 아니라 서브커맨드도 인자를 돌림. 실제 git 으로 확인: `submodule foreach`
    # 는 서브모듈 커밋 수를 늘리고, `bisect run` 은 인자를 실행함.
    ("git submodule foreach 'git commit -am x'", "commit"),
    ("git submodule foreach --recursive 'git commit -am x'", "commit"),
    ("git bisect run git commit -am x", "commit"),
    ("git filter-branch --tree-filter 'git commit -am x' HEAD", "commit"),
    ("git filter-branch --index-filter 'git commit -am x' HEAD", "commit"),
    ("git submodule foreach 'git merge --no-ff fix/x'", "merge"),
]
