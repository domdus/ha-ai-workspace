from __future__ import annotations

import importlib.util
from pathlib import Path


def _const():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "const.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_const", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_agent_choices_include_claude_sdk() -> None:
    const = _const()
    # Mirrors agent_flow._agent_choices without importing Home Assistant.
    choices = {const.MODE_CURSOR: "Cursor", const.MODE_CLAUDE: "Claude SDK", **const.API_PROVIDERS}
    assert const.MODE_CLAUDE in choices
    assert choices[const.MODE_CLAUDE] == "Claude SDK"


def test_runtime_session_payload_uses_agent_kind() -> None:
    """HA must pass the agent kind when creating a runtime session (not always cursor)."""
    runtime_kinds = frozenset({"cursor", "claude"})

    def payload(provider: str) -> dict[str, str]:
        return {"provider": provider if provider in runtime_kinds else "cursor"}

    assert payload("claude")["provider"] == "claude"
    assert payload("cursor")["provider"] == "cursor"
