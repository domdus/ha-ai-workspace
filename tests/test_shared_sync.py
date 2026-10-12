from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "ai_workspace"
RUNTIME = ROOT / "ai_workspace" / "app"

# The integration and the runtime ship separately, so these files are copied, not imported.
SHARED = [
    "tool_result.py",
    "titles.py",
    "files.py",
    "small_talk.py",
    "redact.py",
    "workspace_seed/AGENTS.md",
]


@pytest.mark.parametrize("name", SHARED)
def test_shared_copies_match(name: str) -> None:
    assert (INTEGRATION / name).read_text() == (RUNTIME / name).read_text(), (
        f"{name} differs between custom_components/ai_workspace and ai_workspace/app; edit both"
    )
