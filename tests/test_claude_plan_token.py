from custom_components.ai_workspace.const import CLAUDE_PLAN_HELP_URL, MODE_CLAUDE, api_key_url, claude_plan_token_problem


def test_claude_plan_help_url_not_openrouter():
    assert "openrouter" not in api_key_url(MODE_CLAUDE).lower()
    assert api_key_url(MODE_CLAUDE) == CLAUDE_PLAN_HELP_URL


def test_claude_plan_token_validation():
    assert claude_plan_token_problem("") is None
    assert claude_plan_token_problem("sk-ant-oat-abc") is None
    assert claude_plan_token_problem("sk-ant-api-abc") == "claude_plan_not_api_key"
    assert claude_plan_token_problem("sk-or-v1-abc") == "claude_plan_not_openrouter"
    assert claude_plan_token_problem("not-a-token") == "claude_plan_invalid"
