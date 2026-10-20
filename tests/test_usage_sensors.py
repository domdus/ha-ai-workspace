from pathlib import Path

from custom_components.ai_workspace.const import CONF_HA_USAGE_SENSORS, is_usage_sensor_unique_id
from custom_components.ai_workspace.models import Settings


def test_usage_sensor_unique_ids() -> None:
    assert is_usage_sensor_unique_id("abc_usage_cost_today")
    assert is_usage_sensor_unique_id("abc_claude_usage_tokens_total")
    assert not is_usage_sensor_unique_id("claude")
    assert not is_usage_sensor_unique_id("claude-stt")
    assert not is_usage_sensor_unique_id("claude-tts")
    assert not is_usage_sensor_unique_id(None)


def test_ha_usage_sensors_default_off() -> None:
    assert CONF_HA_USAGE_SENSORS == "ha_usage_sensors"
    settings = Settings(
        data_dir=Path("/tmp"),
        workspace_dir=Path("/tmp/workspace"),
        state_dir=Path("/tmp/state"),
        cursor_api_key="",
        model="",
        mcp_servers={},
    )
    assert settings.ha_usage_sensors is False
    assert settings.track_usage is True
