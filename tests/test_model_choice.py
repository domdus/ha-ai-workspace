"""Model lists for agent forms and the chat model switcher, and the per-chat agent/model choice."""

from pathlib import Path

from custom_components.ai_workspace.agents import CursorAgent, agent_from_mapping
from custom_components.ai_workspace.api_provider import ApiProvider
from custom_components.ai_workspace.config_flow import _chat_schema
from custom_components.ai_workspace.const import (
    CONF_DEFAULT_AGENT,
    CONF_MODEL_SWITCHER,
    api_model_choices,
    api_model_picks,
    model_catalog,
)
from custom_components.ai_workspace.http import _with_model
from custom_components.ai_workspace.model_list import _ids, merge_models
from custom_components.ai_workspace.models import Settings
from custom_components.ai_workspace.store import Store


def _settings(provider: str, **overrides) -> Settings:
    values = {
        "data_dir": Path("/tmp"),
        "workspace_dir": Path("/tmp/workspace"),
        "state_dir": Path("/tmp/state"),
        "cursor_api_key": "",
        "model": "gemini-3.8-flash",
        "mcp_servers": {},
        "api_provider": provider,
        "api_key": "k",
        "agent_id": "agent-1",
        "agent_title": "Gemini",
    }
    values.update(overrides)
    return Settings(**values)


def test_dropdowns_list_catalog_models_after_the_picks() -> None:
    choices = api_model_choices("anthropic")
    assert choices[: len(api_model_picks("anthropic"))] == api_model_picks("anthropic")
    assert "claude-haiku-4-5" in choices
    assert len(choices) == len(set(choices))
    assert "composer-2" in api_model_choices("cursor")
    assert model_catalog("azure") == []


def test_live_list_drops_non_chat_and_dated_ids() -> None:
    rows = [
        {"id": "gpt-5"},
        {"id": "o4-mini-2025-04-16"},
        {"id": "text-embedding-3-large"},
        {"id": "sora-2"},
        {"id": "models/gemini-3.8-flash"},
        {"id": "gemini-3.8-live"},
        {"id": "gpt-5"},
    ]
    assert _ids(rows) == ["gpt-5", "gemini-3.8-flash"]


def test_merge_keeps_configured_model_first_and_picks_only_when_live() -> None:
    live = ["gpt-6.1-sol", "gpt-5", "o3"]
    merged = merge_models("openai", "my-finetune", live)
    assert merged[0] == "my-finetune"
    assert merged[1] == "gpt-5"
    assert "gpt-4.1" not in merged
    assert merge_models("openai", "", []) == api_model_choices("openai")


def test_provider_rows_carry_title_and_model() -> None:
    api = ApiProvider(None, _settings("gemini"), None)
    row = api.info.as_dict()
    assert (row["title"], row["model"], row["provider"]) == ("Gemini", "gemini-3.8-flash", "gemini")
    cursor = CursorAgent(agent_from_mapping("c1", "Cursor", {"api_provider": "cursor"}), True, None)
    assert cursor.info.as_dict()["model"] == "composer-2.5"
    assert cursor.info.as_dict()["title"] == "Cursor"


def test_chat_model_override_leaves_the_shared_agent_alone() -> None:
    api = ApiProvider(None, _settings("gemini"), None)
    other = _with_model(api, "gemini-3.7-flash")
    assert other is not api
    assert other._model() == "gemini-3.7-flash"
    assert api._model() == "gemini-3.8-flash"
    assert _with_model(api, "gemini-3.7-flash") is other
    assert _with_model(api, "") is api
    assert _with_model(api, "gemini-3.8-flash") is api
    cursor = CursorAgent(agent_from_mapping("c1", "Cursor", {"api_provider": "cursor", "model": "composer-2.5"}), True, None)
    assert _with_model(cursor, "composer-2").model == "composer-2"
    assert cursor.model == "composer-2.5"


def test_configure_form_offers_default_agent_and_switcher() -> None:
    agents = [agent_from_mapping("a1", "Cursor", {"api_provider": "cursor"})]
    fields = {getattr(key, "schema", key) for key in _chat_schema({}, agents).schema}
    assert {CONF_DEFAULT_AGENT, CONF_MODEL_SWITCHER} <= fields
    fields = {getattr(key, "schema", key) for key in _chat_schema({}).schema}
    assert CONF_DEFAULT_AGENT not in fields


def test_chat_remembers_agent_and_model_without_moving_up(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session("user-1", "cursor")
    assert session.model == ""
    changed = store.set_choice("user-1", session.id, "gemini", "gemini-3.7-flash")
    assert (changed.provider, changed.model) == ("gemini", "gemini-3.7-flash")
    assert changed.updated_at == session.updated_at
    assert store.set_choice("user-2", session.id, "cursor", "") is None
    store.close()
