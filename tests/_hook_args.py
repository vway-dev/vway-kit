"""두 훅이 오타로 다뤄야 하는 훅 엔트리 인자 — 목록 하나라 사례가 양쪽 테스트에 다 닿음."""

BAD_HARNESS_ARGS = [
    ("--harness", "Codex"),
    ("--harness", "cdx"),
    ("--harness",),
    ("--harness", "codex", "extra"),
]
