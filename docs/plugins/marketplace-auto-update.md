# 플러그인 마켓플레이스 자동 업데이트 조건

비공개 마켓(vway-kit 등) 플러그인이 **시작 시 자동 갱신**되려면 아래 조건이 모두
충족돼야 함. 하나라도 빠지면 백그라운드 갱신이 조용히 스킵됨(에러 없이 미전파).

## 1. autoUpdate 켜짐

- 호스트 `settings.json` 의 `extraKnownMarketplaces.<name>.autoUpdate = true`.
- 서드파티 마켓은 기본 **OFF**, 배포자가 `marketplace.json` 으로 강제할 수 없다(공급망
  경계). 호스트가 명시적으로 켜야 하고, 등록 주체는 `/vdev-init` 의 `register_marketplace`.

## 2. 변경 감지 (버전 / SHA)

- 버전 해석 순서: `plugin.json` version → 마켓 엔트리 version → git commit SHA.
- version 을 **생략하면 각 커밋이 새 버전**(SHA 기반). vway-kit 은 `marketplace.json`
  의 `source.sha` 로 특정 커밋에 핀하므로, **이 sha 문자열이 바뀔 때만** 재설치가 트리거됨.
- sha 갱신은 `release.yml` 의 핀 스텝이 **main 릴리스가 났을 때만** 자동 수행.

## 3. 백그라운드 인증 (비공개 repo 의 핵심)

백그라운드 갱신은 결국 **git clone/fetch** 로 동작하고, 시작 시 대화형 프롬프트를 막으므로
**비대화형 인증**만 가능. SSH 는 백그라운드에 agent 가 없어 불가, HTTPS 필수.

### 3-1. GITHUB_TOKEN 환경변수

- fine-grained PAT(해당 repo **Contents: Read-only**)를 발급해 `GITHUB_TOKEN`(또는
  `GH_TOKEN`)으로 설정. (GitLab: `GITLAB_TOKEN`/`GL_TOKEN`, Bitbucket: `BITBUCKET_TOKEN`.)
- 공개 repo 는 토큰 불필요.

### 3-2. github.com 자격증명 헬퍼 — 놓치기 쉬운 핵심

- **git 은 `GITHUB_TOKEN` 환경변수를 직접 읽지 않음.** 그래서 토큰만 설정하면
  백그라운드 git fetch 가 `unable to get password` 로 실패. env 토큰을 git 에
  넘기는 자격증명 헬퍼가 있어야 함:

  ```bash
  git config --global credential.https://github.com.helper ""
  git config --global --add credential.https://github.com.helper \
    '!f() { test "$1" = get && echo username=x-access-token && echo "password=$GITHUB_TOKEN"; }; f'
  ```

  - 1줄: 이 호스트에 대해 기존 헬퍼(GCM 등)를 **비움** — GCM 은 다중 GitHub 계정에서
    무인 선택을 못 해 "계정 선택" 팝업을 띄우거나 비대화형에서 실패.
  - 2줄: `get` 시 env 의 `$GITHUB_TOKEN` 을 반환하는 인라인 헬퍼(비대화형).
  - 다른 github repo 는 4번 전역 insteadOf 로 SSH 라 이 헬퍼는 마켓 HTTPS 에만 실효.

### 3-3. 마켓 source 는 `github` + repo

- `extraKnownMarketplaces` 등록은 `{"source": {"source": "github", "repo": "<owner>/<repo>"}}` 로.
  `source: git` + url 은 자동갱신 신뢰성이 낮음 — `github` 가 권장/표준 형식이고 `plugin.json`
  의 plugin source 와도 일치. `/vdev-init` 의 `register_marketplace` 가 이 형식으로 등록.

## 4. insteadOf 충돌 해소 (HTTPS 토큰 ↔ SSH 치환)

- 전역 `url."git@github.com:".insteadOf "https://github.com/"` 가 있으면 마켓의 HTTPS
  fetch 가 SSH 로 치환돼 **토큰(HTTPS)이 무력화**되고, 백그라운드엔 SSH-agent 가 없어 실패.
- 해결: **마켓 repo 만 HTTPS 로 예외 처리**(identity-override). git 은 최장 prefix 매치라
  더 구체적인 규칙이 전역 규칙을 국소적으로 무력화하고, 다른 repo 의 SSH 치환은 유지됨.

  ```bash
  git config --global url."https://github.com/<owner>/<repo>".insteadOf "https://github.com/<owner>/<repo>"
  ```

## 5. 환경변수 전파 (완전 재시작)

- 토큰은 **프로세스 시작 시점**에 읽힘. 설정 후 호스트(VS Code 등)를 완전 재시작해야
  반영됨. VS Code 는 여러 창이 메인 프로세스를 공유하므로, **모든 창을 종료**한 뒤
  재실행해야 한다(창 하나만 reload 하면 옛 환경이 그대로 상속됨).

## 수동 vs 백그라운드

| | 인증 경로 |
|---|---|
| **수동** `/plugin marketplace update <name>` | credential-helper + SSH-agent (대화형 — SSH 키/계정 선택 가능) |
| **백그라운드** (시작 시 자동) | 비대화형 git — github.com 자격증명 헬퍼(3-2)로 env 토큰 사용 |

> 수동 갱신은 되는데 자동 갱신이 안 된다면 거의 항상 3-2(자격증명 헬퍼 부재) 또는
> 4번(insteadOf 충돌) — 수동은 SSH-agent/대화형으로 우회되지만 백그라운드는 안 되기 때문.

## 검증

전역 규칙 확인 — 광범위 규칙만 있고 마켓 repo 예외가 없으면 4번 충돌:

```bash
git config --global --get-regexp '^url\.'
```

백그라운드 그대로(프롬프트·SSH 차단 + **전역 설정만**) 재현 fetch — `exit=0` 이면
3-2 자격증명 헬퍼·4번 예외가 모두 제대로 동작하는 것:

```bash
GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND=false git ls-remote https://github.com/<owner>/<repo>.git HEAD
```

> `exit≠0` 이면: 헬퍼가 없거나(3-2), insteadOf 가 SSH 로 치환(4번)했거나, 토큰이
> 비었음(3-1). `-c` 로 헬퍼를 직접 끼워 넣어 어느 조각이 빠졌는지 좁힐 수 있음.

## 릴리스 — sha 자동 핀 (배포자)

`marketplace.json` 의 `source.sha` 가 effective pin 이고, 소비자 자동 업데이트는 이 sha 가
바뀔 때만 재설치를 트리거한다(§2). [`release.yml`](../../.github/workflows/release.yml) 의
`Publish the plugin branch` 스텝이 **main 에서 릴리스가 실제로 났을 때만** 릴리스 커밋에서
출하 파일만 고른 `plugin` 브랜치 커밋을 만들고, `Pin both marketplaces to the plugin branch`
스텝이 ([`plugin_dist.py pin`](../../.github/scripts/plugin_dist.py)으로) Claude·Codex 두
마켓플레이스의 sha 를 그 커밋으로 갱신·커밋 — 그 커밋이 `plugin.json` version 을 이미 들고
있으므로 핀과 버전이 한 커밋으로 수렴함.

- **전제**: 저장소 Settings → Actions → Workflow permissions = **Read and write**.
- 핀 push 와 `uv.lock` 동기화 push 는 태그 push 뒤라 재실행으로 복구 못 함 — 거부되면
  `git pull --rebase` 후 3회까지 유계 재시도(회차마다 대기 5초씩 늘림), 3회째도 거부면 스텝 실패.
- 릴리스 직후 CI 가 sha-핀 커밋을 붙이므로 **다음 작업 전 `git fetch`**(로컬 포인터가 뒤처짐).
- Action 이 꺼졌거나 수동 갱신 시: 코드 커밋·push → `git rev-parse HEAD` 로 sha 확인 →
  `marketplace.json` 의 `source.sha` 를 그 값으로 갱신·커밋·push. self-hosted(마켓==플러그인)라
  sha 는 항상 직전 코드 커밋을 가리키고, 핀 커밋이 한 발 앞서는 1커밋 지연은 정상·무해.
- `sha` 만 쓰고 `commit` 필드는 넣지 않는다(미문서화·내부용). `ref`(브랜치/태그)와 병기할 수
  있으나 `sha` 가 있으면 그것이 effective pin.
