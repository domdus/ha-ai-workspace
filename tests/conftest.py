import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai_workspace"))

import pytest


@pytest.fixture(autouse=True)
def _no_plan_usage_reads(monkeypatch):
    """Tests never call Anthropic's /api/oauth/usage (app.claude_usage); tests that need it opt back in."""
    monkeypatch.setenv("CLAUDE_PLAN_USAGE_READ", "off")
