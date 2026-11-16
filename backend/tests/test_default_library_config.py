from copy import deepcopy

from app.core.config import Settings
from scripts.configure_default_library import configure_service


def test_default_library_config_preserves_skills_and_other_runtime_settings():
    original = {
        "id": "default-codex", "agent_type": "codex", "cwd": "/existing/workspace",
        "env": {"HOME": "/existing/home", "CODEX_HOME": "/existing/codex", "OTHER": "kept"},
        "codex": {"mode": "adapter", "adapter_command": "codex-acp",
                  "adapter_args": ["-c", 'model="existing-model"', "-c", 'mcp_servers.other.url="http://other"']},
        "permission_mode": "auto_approve",
    }
    before = deepcopy(original)
    settings = Settings(mcp_model_compat_base_url="http://127.0.0.1:8766/v1")
    result = configure_service(original, settings, "agw")
    assert original == before
    assert result["cwd"] == original["cwd"]
    assert result["env"].items() >= original["env"].items()
    assert result["codex"]["adapter_args"][:4] == original["codex"]["adapter_args"]
    assert "/library/default" in str(result["codex"]["adapter_args"])
    assert "EXPERT_LIBRARY_AUTHORIZATION" in result["env"]
    assert configure_service(result, settings, "agw") == result
