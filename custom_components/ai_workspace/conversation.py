"""Assist conversation agents. One entity per agent row."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.components import conversation
from homeassistant.components.conversation.chat_log import AssistantContent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .agents import Agent, agent_from_entry, entry_agents, is_agents, is_provider
from .const import DOMAIN
from .chat_scope import handoff_note, other_chat_note
from .http import _create_runtime_session, async_agent_events
from .small_talk import wants_house_tools
from .store import Store
from .titles import accept_generated_title, needs_title_summary, title_from_prompt

_LOGGER = logging.getLogger(__name__)


async def _login_token(hass: HomeAssistant, user_id: str) -> str | None:
    """Short-lived token for the person who opened Assist.

    The sidebar chat sends the browser login. Assist does not, so an empty
    MCP token would leave Home Assistant tools unauthorized.
    """
    if not user_id or user_id == "assist":
        return None
    try:
        user = await hass.auth.async_get_user(user_id)
    except Exception:
        return None
    if user is None:
        return None
    refresh = next(iter(getattr(user, "refresh_tokens", {}).values()), None)
    if refresh is None:
        return None
    try:
        return hass.auth.async_create_access_token(refresh)
    except Exception:
        _LOGGER.debug("Assist login token skipped", exc_info=True)
        return None


def _agent_device_active(hass: HomeAssistant, entry_id: str, subentry_id: str | None) -> bool:
    if not subentry_id:
        return True
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry_id):
        if device.config_subentry_id != subentry_id:
            continue
        return device.disabled_by is None
    return True


async def _drop_assist_pipeline(hass: HomeAssistant, unique_id: str) -> None:
    from homeassistant.helpers import entity_registry as er

    from .assist_pipelines import async_remove_assist_pipeline

    entity_id = er.async_get(hass).async_get_entity_id("conversation", DOMAIN, unique_id)
    if entity_id:
        await async_remove_assist_pipeline(hass, entity_id)


def _clear_integration_disabled_agent(hass: HomeAssistant, agent_id: str) -> None:
    """Undo the old form Enabled flag, which disabled the conversation entity."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("conversation", DOMAIN, agent_id)
    if not entity_id:
        return
    entry = registry.async_get(entity_id)
    if entry is None or entry.disabled_by is not er.RegistryEntryDisabler.INTEGRATION:
        return
    registry.async_update_entity(entity_id, disabled_by=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Expose each agent to Assist."""
    if is_agents(entry):
        agents = entry_agents(entry)
        wanted = []
        for agent in agents:
            if agent.assist and _agent_device_active(hass, entry.entry_id, agent.subentry_id):
                wanted.append(agent)
            else:
                await _drop_assist_pipeline(hass, agent.id)
        _LOGGER.info("Exposing %s Assist agent(s) for %s", len(wanted), entry.title)
        for agent in wanted:
            _clear_integration_disabled_agent(hass, agent.id)
        async_add_entities([AiWorkspaceConversationEntity(entry, agent) for agent in wanted])
        return
    if is_provider(entry):
        agent = agent_from_entry(entry)
        if agent.assist and _agent_device_active(hass, entry.entry_id, agent.subentry_id):
            async_add_entities([AiWorkspaceConversationEntity(entry, agent)])
        else:
            await _drop_assist_pipeline(hass, agent.id)


class AiWorkspaceConversationEntity(conversation.ConversationEntity):
    """Native Assist agent that uses the same model as the sidebar chat."""

    _attr_supports_streaming = True
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_icon = "mdi:robot"
    _attr_should_poll = False
    # Device linkage comes from _sync_subentry_devices (one device per agent row).
    # Do not set DeviceInfo here — it fights the subentry device and can strand setup.

    def __init__(self, entry: ConfigEntry, agent: Agent) -> None:
        self._agent_id = agent.id
        self._subentry_id = agent.subentry_id
        self._attr_unique_id = agent.id
        self._attr_name = agent.title or entry.title or "AI Workspace"
        if agent.subentry_id:
            self._attr_config_subentry_id = agent.subentry_id

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        _clear_integration_disabled_agent(self.hass, self._agent_id)
        self._link_agent_device()
        if self.registry_entry is not None and self.registry_entry.disabled_by:
            return
        from .assist_pipelines import async_ensure_assist_pipeline

        name = self.name if isinstance(self.name, str) else self._attr_name
        await async_ensure_assist_pipeline(self.hass, self.entity_id, str(name or "AI Workspace"))

    def _link_agent_device(self) -> None:
        """Put the conversation entity on the agent device so Disable device works."""
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        entry = registry.async_get(self.entity_id)
        if entry is None:
            return
        config_entry_id = entry.config_entry_id or (
            self.platform.config_entry.entry_id if self.platform and self.platform.config_entry else None
        )
        devices = dr.async_get(self.hass)
        device = None
        get_by_id = getattr(devices, "async_get_device_by_identifier", None)
        if callable(get_by_id) and config_entry_id:
            device = get_by_id((DOMAIN, f"agent:{self._agent_id}"), config_entry_id)
        else:
            device = devices.async_get_device(identifiers={(DOMAIN, f"agent:{self._agent_id}")})
        updates: dict[str, Any] = {}
        if device is not None and entry.device_id != device.id:
            updates["device_id"] = device.id
        if self._subentry_id and entry.config_subentry_id != self._subentry_id:
            updates["config_subentry_id"] = self._subentry_id
        if updates:
            try:
                registry.async_update_entity(self.entity_id, **updates)
            except TypeError:
                updates.pop("config_subentry_id", None)
                if updates:
                    registry.async_update_entity(self.entity_id, **updates)

    async def async_will_remove_from_hass(self) -> None:
        # Reloads unload the entity but the agent subentry stays — keep the pipeline.
        from .agents import entry_agents
        from .assist_pipelines import async_remove_assist_pipeline

        entry = None
        if self.registry_entry is not None:
            entry = self.hass.config_entries.async_get_entry(self.registry_entry.config_entry_id)
        if entry is None and self.platform is not None:
            entry = self.platform.config_entry
        still_configured = bool(
            entry is not None
            and any(
                agent.id == self._agent_id
                and agent.assist
                and _agent_device_active(self.hass, entry.entry_id, agent.subentry_id)
                for agent in entry_agents(entry)
            )
        )
        if not still_configured:
            await async_remove_assist_pipeline(self.hass, self.entity_id)
        await super().async_will_remove_from_hass()

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        text = str(user_input.text or "").strip()
        if not text:
            self._reply(chat_log, "Message is empty.")
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        data = self.hass.data.get(DOMAIN) or {}
        providers = data.get("providers") or {}
        provider = providers.get(self._agent_id)
        info = getattr(provider, "info", None)
        if getattr(provider, "kind", "") == "cursor" and not getattr(info, "available", False):
            from .discovery import async_bind_runtime

            await async_bind_runtime(self.hass, data)
            provider = providers.get(self._agent_id)
            info = getattr(provider, "info", None)
        if provider is None or not getattr(info, "available", False):
            reason = getattr(info, "reason", None) or "This agent is not available."
            self._reply(chat_log, str(reason))
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        store: Store = data["store"]
        user_id = str(user_input.context.user_id or "assist")
        conversation_id = str(chat_log.conversation_id or user_input.conversation_id or "")
        if not conversation_id:
            self._reply(chat_log, "Assist did not start a conversation.")
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        session = await self.hass.async_add_executor_job(store.get_session, user_id, conversation_id)
        if session is None:
            if getattr(provider, "kind", "") == "cursor":
                await _create_runtime_session(self.hass, user_id, conversation_id)
            session = await self.hass.async_add_executor_job(
                store.create_session, user_id, self._agent_id, conversation_id
            )
        elif session.provider != self._agent_id:
            await self.hass.async_add_executor_job(store.set_provider, user_id, session.id, self._agent_id)
            session.provider = self._agent_id

        locks: dict[str, asyncio.Lock] = data.setdefault("locks", {})
        lock = locks.setdefault(session.id, asyncio.Lock())
        if lock.locked():
            self._reply(chat_log, "This chat is already waiting on the agent.")
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        low_token = bool(getattr(getattr(provider, "settings", None), "low_token", False))
        extra = "" if low_token else str(user_input.extra_system_prompt or "").strip()
        outbound = f"{extra}\n\n{text}" if extra else text
        cross = bool(getattr(data.get("settings"), "cross_chat", False))
        note = (
            ""
            if low_token
            else await self.hass.async_add_executor_job(
                other_chat_note, store, user_id, session.id, text, cross
            )
        )
        if note:
            outbound = f"{outbound}\n\n{note}"
        origin = str(self.hass.config.external_url or self.hass.config.internal_url or "").rstrip("/")
        language = str(user_input.language or "")
        suggest = None
        error: str | None = None

        async with lock:
            await self.hass.async_add_executor_job(store.add_message, session.id, "user", text, "[]")
            await self.hass.async_add_executor_job(store.rename_if_default, session.id, title_from_prompt(text))
            count = await self.hass.async_add_executor_job(lambda: len(store.list_messages(session.id)))
            handoff = ""
            if getattr(provider, "kind", "") == "cursor":
                rows = await self.hass.async_add_executor_job(store.list_messages, session.id)
                handoff = handoff_note(rows, session.title)
            suggest = (
                None
                if low_token
                else getattr(provider, "suggest_title", None)
                if count <= 1 and needs_title_summary(text)
                else None
            )
            parts: list[str] = []
            tools: list[dict[str, Any]] = []
            final: str | None = None

            access_token = await _login_token(self.hass, user_id)

            async def deltas():
                nonlocal error, final
                started = False
                async for event in async_agent_events(
                    self.hass,
                    user_id,
                    session,
                    provider,
                    outbound,
                    language=language,
                    origin=origin,
                    access_token=access_token,
                    handoff=handoff,
                    question=text,
                    tools=wants_house_tools(text),
                ):
                    kind = event.get("type")
                    if kind == "text":
                        delta = str(event.get("delta") or "")
                        if not delta:
                            continue
                        parts.append(delta)
                        if not started:
                            started = True
                            yield {"role": "assistant", "content": delta}
                        else:
                            yield {"content": delta}
                    elif kind == "result":
                        final = str(event.get("text") or "")
                    elif kind == "tool":
                        tools.append(
                            {
                                "name": event.get("name"),
                                "phase": event.get("phase"),
                                "text": event.get("text"),
                                **({"id": event["id"]} if event.get("id") else {}),
                            }
                        )
                    elif kind == "error":
                        error = str(event.get("message") or "The agent failed.")
                if started:
                    return
                answer = (final or error or "").strip() or "The agent returned nothing."
                yield {"role": "assistant", "content": answer}

            async for _content in chat_log.async_add_delta_content_stream(self.entity_id, deltas()):
                pass

            answer = (final or "".join(parts)).strip()
            if error and not answer:
                answer = error
            stored = list(tools)
            if error:
                stored.append({"type": "error", "message": error})
            await self.hass.async_add_executor_job(
                store.add_message,
                session.id,
                "assistant",
                answer,
                json.dumps(stored, ensure_ascii=False),
            )

        if error is None and callable(suggest):
            try:
                title = accept_generated_title(text, await suggest(text, "") or "")
            except Exception:
                _LOGGER.debug("Assist title skipped", exc_info=True)
                title = ""
            if title:
                await self.hass.async_add_executor_job(
                    store.apply_generated_title, user_id, session.id, title_from_prompt(text), title
                )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    def _reply(self, chat_log: conversation.ChatLog, text: str) -> None:
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=self.entity_id, content=text)
        )
