from __future__ import annotations

import re


EXPERT_ID_PATTERN = r"^[0-9a-f]{16}$"
_SUPPORTED_RUNTIMES = {"codex", "opencode"}


def expert_runtime_name(runtime_type: str, expert_id: str) -> str:
    if runtime_type not in _SUPPORTED_RUNTIMES:
        raise ValueError(f"Unsupported Expert runtime: {runtime_type}")
    if re.fullmatch(EXPERT_ID_PATTERN, expert_id) is None:
        raise ValueError("Expert id must be 16 lowercase hexadecimal characters")
    return f"expert-{runtime_type}-{expert_id}"
