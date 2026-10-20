"""Usage and cost sensors for Lovelace dashboards."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .agents import Agent, entry_agents
from .const import DOMAIN, SUBENTRY_USAGE, usage_device_ident
from .store import Store
from .usage_cost import SIGNAL_USAGE_UPDATE, empty_summary
from .usage_record import day_bounds, provider_label

SCAN = timedelta(minutes=15)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    if not bool(getattr(settings, "ha_usage_sensors", False)):
        return
    store: Store = hass.data[DOMAIN]["store"]
    agents = entry_agents(entry)
    hub = UsageHub(hass, store, [agent.id for agent in agents])
    usage_sub = next((sub.subentry_id for sub in entry.subentries.values() if sub.subentry_type == SUBENTRY_USAGE), None)
    async_add_entities(
        [
            WorkspaceUsageSensor(hass, entry, hub, "cost_today", "Cost today", "cost", "today"),
            WorkspaceUsageSensor(hass, entry, hub, "cost_month", "Cost this month", "cost", "month"),
            WorkspaceUsageSensor(hass, entry, hub, "cost_total", "Cost total", "cost", "all", increasing=True),
            WorkspaceUsageSensor(hass, entry, hub, "tokens_today", "Tokens today", "tokens", "today"),
            WorkspaceUsageSensor(hass, entry, hub, "tokens_month", "Tokens this month", "tokens", "month"),
            WorkspaceUsageSensor(hass, entry, hub, "tokens_total", "Tokens total", "tokens", "all", increasing=True),
            WorkspaceUsageSensor(hass, entry, hub, "turns_today", "Turns today", "turns", "today"),
            WorkspaceUsageSensor(hass, entry, hub, "turns_month", "Turns this month", "turns", "month"),
            WorkspaceUsageSensor(hass, entry, hub, "turns_total", "Turns total", "turns", "all", increasing=True),
            WorkspaceLastSensor(hass, entry, hub, "last_cost", "Last turn cost", "cost"),
            WorkspaceLastSensor(hass, entry, hub, "last_tokens", "Last turn tokens", "tokens"),
            WorkspaceLastSensor(hass, entry, hub, "last_model", "Last model", "model"),
            WorkspaceLastSensor(hass, entry, hub, "last_agent", "Last agent", "agent"),
            WorkspaceUsageSensor(hass, entry, hub, "cost_tts_today", "Speech cost today", "cost", "today", source="tts"),
            WorkspaceUsageSensor(
                hass, entry, hub, "cost_tts_total", "Speech cost total", "cost", "all", increasing=True, source="tts"
            ),
        ],
        config_subentry_id=usage_sub,
    )
    for agent in agents:
        async_add_entities(
            [
                AgentUsageSensor(hass, entry, hub, agent, "cost_today", "Cost today", "cost", "today"),
                AgentUsageSensor(hass, entry, hub, agent, "cost_month", "Cost this month", "cost", "month"),
                AgentUsageSensor(
                    hass, entry, hub, agent, "cost_total", "Cost total", "cost", "all", increasing=True
                ),
                AgentUsageSensor(hass, entry, hub, agent, "tokens_today", "Tokens today", "tokens", "today"),
                AgentUsageSensor(hass, entry, hub, agent, "tokens_month", "Tokens this month", "tokens", "month"),
                AgentUsageSensor(
                    hass, entry, hub, agent, "tokens_total", "Tokens total", "tokens", "all", increasing=True
                ),
                AgentUsageSensor(hass, entry, hub, agent, "turns_today", "Turns today", "turns", "today"),
                AgentUsageSensor(
                    hass, entry, hub, agent, "turns_total", "Turns total", "turns", "all", increasing=True
                ),
                AgentLastSensor(hass, entry, hub, agent, "last_cost", "Last turn cost", "cost"),
                AgentLastSensor(hass, entry, hub, agent, "last_tokens", "Last turn tokens", "tokens"),
                AgentLastSensor(hass, entry, hub, agent, "last_model", "Last model", "model"),
                AgentUsageSensor(
                    hass, entry, hub, agent, "cost_tts_today", "Speech cost today", "cost", "today", source="tts"
                ),
                AgentUsageSensor(
                    hass,
                    entry,
                    hub,
                    agent,
                    "cost_tts_total",
                    "Speech cost total",
                    "cost",
                    "all",
                    increasing=True,
                    source="tts",
                ),
            ],
            config_subentry_id=agent.subentry_id or None,
        )


class UsageHub:
    """One SQLite pass for every usage sensor."""

    def __init__(self, hass: HomeAssistant, store: Store, agent_ids: list[str]) -> None:
        self.hass = hass
        self.store = store
        self.agent_ids = agent_ids
        self.windows: dict[str, dict] = {
            "today": empty_summary(),
            "month": empty_summary(),
            "all": empty_summary(),
        }
        self.tts_windows: dict[str, dict] = {
            "today": empty_summary(),
            "month": empty_summary(),
            "all": empty_summary(),
        }
        self.last: dict | None = None
        self.agent_windows: dict[str, dict[str, dict]] = {}
        self.agent_tts_windows: dict[str, dict[str, dict]] = {}
        self.agent_last: dict[str, dict | None] = {}
        self._unsub: list[Callable[[], None]] = []
        self._entities: list[_UsageBase] = []
        self._busy = False
        self._again = False

    def attach(self, entity: "_UsageBase") -> None:
        self._entities.append(entity)

    async def async_setup(self) -> None:
        if self._unsub:
            return
        self._unsub.append(async_dispatcher_connect(self.hass, SIGNAL_USAGE_UPDATE, self._on_update))
        self._unsub.append(async_track_time_interval(self.hass, self._on_interval, SCAN))
        await self.refresh()

    def detach(self, entity: "_UsageBase") -> None:
        if entity in self._entities:
            self._entities.remove(entity)
        if self._entities:
            return
        while self._unsub:
            self._unsub.pop()()

    @callback
    def _on_update(self) -> None:
        self.hass.async_create_task(self.refresh())

    async def _on_interval(self, _now: datetime) -> None:
        await self.refresh()

    async def refresh(self) -> None:
        if self._busy:
            self._again = True
            return
        self._busy = True
        try:
            while True:
                self._again = False
                today, tomorrow, month = day_bounds(self.hass)
                agent_ids = list(self.agent_ids)

                def load() -> dict:
                    payload: dict = {
                        "today": self.store.summarize_usage(since=today, until=tomorrow),
                        "month": self.store.summarize_usage(since=month),
                        "all": self.store.summarize_usage(),
                        "last": self.store.last_usage(),
                        "tts_today": self.store.summarize_usage(since=today, until=tomorrow, origin="tts"),
                        "tts_month": self.store.summarize_usage(since=month, origin="tts"),
                        "tts_all": self.store.summarize_usage(origin="tts"),
                        "agent_windows": {},
                        "agent_tts_windows": {},
                        "agent_last": {},
                    }
                    for agent_id in agent_ids:
                        payload["agent_windows"][agent_id] = {
                            "today": self.store.summarize_usage(since=today, until=tomorrow, agent_id=agent_id),
                            "month": self.store.summarize_usage(since=month, agent_id=agent_id),
                            "all": self.store.summarize_usage(agent_id=agent_id),
                        }
                        payload["agent_tts_windows"][agent_id] = {
                            "today": self.store.summarize_usage(
                                since=today, until=tomorrow, agent_id=agent_id, origin="tts"
                            ),
                            "all": self.store.summarize_usage(agent_id=agent_id, origin="tts"),
                        }
                        payload["agent_last"][agent_id] = self.store.last_usage(agent_id=agent_id)
                    return payload

                data = await self.hass.async_add_executor_job(load)
                self.windows = {key: data[key] for key in ("today", "month", "all")}
                self.tts_windows = {
                    "today": data["tts_today"],
                    "month": data["tts_month"],
                    "all": data["tts_all"],
                }
                self.last = data["last"]
                self.agent_windows = data["agent_windows"]
                self.agent_tts_windows = data["agent_tts_windows"]
                self.agent_last = data["agent_last"]
                for entity in list(self._entities):
                    entity.apply_hub()
                if not self._again:
                    break
        finally:
            self._busy = False


class _UsageBase(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_attribution = "AI Workspace"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: UsageHub) -> None:
        self.hass = hass
        self._entry = entry
        self._hub = hub

    async def async_added_to_hass(self) -> None:
        self._hub.attach(self)
        await self._hub.async_setup()
        self.apply_hub()

    async def async_will_remove_from_hass(self) -> None:
        self._hub.detach(self)

    def apply_hub(self) -> None:
        raise NotImplementedError


def _style_cost(entity: SensorEntity, *, increasing: bool = False, total: bool = False) -> None:
    entity._attr_native_unit_of_measurement = "USD"
    entity._attr_suggested_display_precision = 4
    entity._attr_icon = "mdi:currency-usd"
    if increasing:
        entity._attr_state_class = SensorStateClass.TOTAL_INCREASING
    elif total:
        entity._attr_state_class = SensorStateClass.TOTAL


def _style_tokens(entity: SensorEntity, *, increasing: bool = False, total: bool = False) -> None:
    entity._attr_native_unit_of_measurement = "tokens"
    entity._attr_icon = "mdi:counter"
    if increasing:
        entity._attr_state_class = SensorStateClass.TOTAL_INCREASING
    elif total:
        entity._attr_state_class = SensorStateClass.TOTAL


def _style_turns(entity: SensorEntity, *, increasing: bool = False, total: bool = False) -> None:
    entity._attr_icon = "mdi:chat-processing-outline"
    entity._attr_entity_category = EntityCategory.DIAGNOSTIC
    if increasing:
        entity._attr_state_class = SensorStateClass.TOTAL_INCREASING
    elif total:
        entity._attr_state_class = SensorStateClass.TOTAL


def _from_summary(kind: str, summary: dict | None):
    row = summary or empty_summary()
    if kind == "cost":
        return round(float(row.get("cost_usd") or 0), 6)
    if kind == "tokens":
        return int(row.get("total_tokens") or 0)
    return int(row.get("turns") or 0)


def _summary_attrs(summary: dict | None, extra: dict | None = None) -> dict:
    row = summary or empty_summary()
    attrs = {
        "prompt_tokens": row.get("prompt_tokens") or 0,
        "completion_tokens": row.get("completion_tokens") or 0,
        "cache_read_tokens": row.get("cache_read_tokens") or 0,
        "cache_write_tokens": row.get("cache_write_tokens") or 0,
        "turns": row.get("turns") or 0,
        "missing_cost": bool(row.get("missing_cost")),
        "cost_usd": row.get("cost_usd") or 0,
        "total_tokens": row.get("total_tokens") or 0,
        "characters": row.get("characters") or 0,
    }
    if extra:
        attrs.update(extra)
    return attrs


class WorkspaceUsageSensor(_UsageBase):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        hub: UsageHub,
        unique: str,
        name: str,
        kind: str,
        window: str,
        *,
        increasing: bool = False,
        source: str = "",
    ) -> None:
        super().__init__(hass, entry, hub)
        self._kind = kind
        self._window = window
        self._source = source
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_usage_{unique}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, usage_device_ident(entry.entry_id))},
            name="AI Workspace",
            manufacturer="AI Workspace",
            model="Usage",
            entry_type=DeviceEntryType.SERVICE,
        )
        resettable = window != "all"
        if kind == "cost":
            _style_cost(self, increasing=increasing, total=resettable)
        elif kind == "tokens":
            _style_tokens(self, increasing=increasing, total=resettable)
        else:
            _style_turns(self, increasing=increasing, total=resettable)
        if source == "tts":
            self._attr_icon = "mdi:account-voice"
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def apply_hub(self) -> None:
        pool = self._hub.tts_windows if self._source == "tts" else self._hub.windows
        summary = pool.get(self._window) or empty_summary()
        self._attr_native_value = _from_summary(self._kind, summary)
        self._attr_extra_state_attributes = _summary_attrs(summary, {"origin": "tts"} if self._source == "tts" else None)
        self.async_write_ha_state()


class WorkspaceLastSensor(_UsageBase):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        hub: UsageHub,
        unique: str,
        name: str,
        kind: str,
    ) -> None:
        super().__init__(hass, entry, hub)
        self._kind = kind
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_usage_{unique}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, usage_device_ident(entry.entry_id))},
            name="AI Workspace",
            manufacturer="AI Workspace",
            model="Usage",
            entry_type=DeviceEntryType.SERVICE,
        )
        if kind == "cost":
            _style_cost(self)
            self._attr_suggested_display_precision = 6
        elif kind == "tokens":
            _style_tokens(self)
        else:
            self._attr_icon = "mdi:robot-outline" if kind == "agent" else "mdi:chip"

    def apply_hub(self) -> None:
        last = self._hub.last
        if not last:
            self._attr_native_value = None if self._kind in {"cost", "tokens"} else ""
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return
        if self._kind == "cost":
            self._attr_native_value = last.get("cost_usd")
        elif self._kind == "tokens":
            self._attr_native_value = last.get("total_tokens") or 0
        elif self._kind == "agent":
            self._attr_native_value = last.get("agent") or last.get("agent_id") or ""
        else:
            self._attr_native_value = last.get("model") or ""
        self._attr_extra_state_attributes = last
        self.async_write_ha_state()


class AgentUsageSensor(_UsageBase):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        hub: UsageHub,
        agent: Agent,
        unique: str,
        name: str,
        kind: str,
        window: str,
        *,
        increasing: bool = False,
        source: str = "",
    ) -> None:
        super().__init__(hass, entry, hub)
        self._agent = agent
        self._kind = kind
        self._window = window
        self._source = source
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{agent.id}_usage_{unique}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"agent:{agent.id}")},
            name=agent.title or provider_label(agent),
            manufacturer="AI Workspace",
            model="Agent",
            entry_type=DeviceEntryType.SERVICE,
        )
        resettable = window != "all"
        if kind == "cost":
            _style_cost(self, increasing=increasing, total=resettable)
        elif kind == "tokens":
            _style_tokens(self, increasing=increasing, total=resettable)
        else:
            _style_turns(self, increasing=increasing, total=resettable)
        if window == "today" or source == "tts":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if source == "tts":
            self._attr_icon = "mdi:account-voice"

    def apply_hub(self) -> None:
        pool = self._hub.agent_tts_windows if self._source == "tts" else self._hub.agent_windows
        summary = (pool.get(self._agent.id) or {}).get(self._window)
        extra = {"agent_id": self._agent.id}
        if self._source == "tts":
            extra["origin"] = "tts"
        self._attr_native_value = _from_summary(self._kind, summary)
        self._attr_extra_state_attributes = _summary_attrs(summary, extra)
        self.async_write_ha_state()


class AgentLastSensor(_UsageBase):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        hub: UsageHub,
        agent: Agent,
        unique: str,
        name: str,
        kind: str,
    ) -> None:
        super().__init__(hass, entry, hub)
        self._agent = agent
        self._kind = kind
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{agent.id}_usage_{unique}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"agent:{agent.id}")},
            name=agent.title or provider_label(agent),
            manufacturer="AI Workspace",
            model="Agent",
            entry_type=DeviceEntryType.SERVICE,
        )
        if kind == "cost":
            _style_cost(self)
            self._attr_suggested_display_precision = 6
        elif kind == "tokens":
            _style_tokens(self)
        else:
            self._attr_icon = "mdi:chip"

    def apply_hub(self) -> None:
        last = self._hub.agent_last.get(self._agent.id)
        if not last:
            self._attr_native_value = None if self._kind in {"cost", "tokens"} else ""
            self._attr_extra_state_attributes = {"agent_id": self._agent.id}
            self.async_write_ha_state()
            return
        if self._kind == "cost":
            self._attr_native_value = last.get("cost_usd")
        elif self._kind == "tokens":
            self._attr_native_value = last.get("total_tokens") or 0
        else:
            self._attr_native_value = last.get("model") or ""
        self._attr_extra_state_attributes = last
        self.async_write_ha_state()
