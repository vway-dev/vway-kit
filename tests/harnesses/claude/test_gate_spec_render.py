"""gate IR 에서 렌더한 Claude 엔트리가 기존 호스트가 이미 가진 엔트리와 같은지 잼.

값이 한 글자라도 바뀌면 모든 호스트의 settings.json 이 `/vdev-init` 재실행 때 "보정" 으로
다시 쓰임 — 그래서 기대값은 IR 에서 끌어오지 않고 리터럴로 고정함."""

import scripts.vdev_init_setup as vis
from scripts.harness.claude import install
from scripts.harness.gate_spec import GATE

EXISTING_ENTRY = {
    "matcher": "Bash",
    "hooks": [
        {
            "type": "command",
            "shell": "bash",
            "command": 'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/vway-kit/scripts/precommit-runner.sh"',  # noqa: E501
            "timeout": 600,
            "statusMessage": "vway-kit: vdev 게이트 + 테스트 검사 중…",
        }
    ],
}


def test_rendered_claude_entry_is_byte_identical_to_the_shipped_one():
    assert install.GATE_ENTRY == EXISTING_ENTRY


def test_vdev_init_setup_reexports_the_same_objects():
    assert vis.GATE_ENTRY is install.GATE_ENTRY
    assert vis.register_gate is install.register
    assert vis._is_gate_hook is install.is_gate_hook
    assert vis.MARKETPLACE_URL is install.MARKETPLACE_URL


def test_ir_holds_the_values_both_harnesses_render_from():
    assert GATE.runner_rel == ".claude/vway-kit/scripts/precommit-runner.sh"
    assert GATE.timeout == 600
    assert GATE.status == "vway-kit: vdev 게이트 + 테스트 검사 중…"


def test_marketplace_values_are_the_vway_ones():
    assert install.GATE_MARKER == ("vway-kit", "precommit-runner.sh")
    assert install.MARKETPLACE_NAME == "vway"
    assert install.MARKETPLACE_REPO == "vway-dev/vway-kit"
    assert install.MARKETPLACE_URL == "https://github.com/vway-dev/vway-kit"
