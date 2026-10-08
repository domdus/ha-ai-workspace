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
from .http import _create_runtime_session, async_agent_events
from .store import Store

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Expose each agent to Assist."""
    if is_provider(entry):
        async_add_entities([AiWorkspaceConversationEntity(entry, agent_from_entry(entry))])
        return
    if is_agents(entry):
        return
    async_add_entities([AiWorkspaceConversationEntity(entry, agent) for agent in entry_agents(entry)])


class AiWorkspaceConversationEntity(conversation.ConversationEntity):
    """Native Assist agent that uses the same model as the sidebar chat."""

    _attr_supports_streaming = True
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_icon = "mdi:robot"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, agent: Agent) -> None:
        self._agent_id = agent.id
        self._attr_unique_id = agent.id
        self._attr_name = agent.title or entry.title or "AI Workspace"
        if agent.subentry_id:
            self._attr_config_subentry_id = agent.subentry_id

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from .assist_pipelines import async_ensure_assist_pipeline

        name = self.name if isinstance(self.name, str) else self._attr_name
        await async_ensure_assist_pipeline(self.hass, self.entity_id, str(name or "AI Workspace"))

    async def async_will_remove_from_hass(self) -> None:
        from .assist_pipelines import async_remove_assist_pipeline

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

        extra = str(user_input.extra_system_prompt or "").strip()
        outbound = f"{extra}\n\n{text}" if extra else text
        origin = str(self.hass.config.external_url or self.hass.config.internal_url or "").rstrip("/")
        language = str(user_input.language or "")

        async with lock:
            await self.hass.async_add_executor_job(store.add_message, session.id, "user", text, "[]")
            await self.hass.async_add_executor_job(store.rename_if_default, session.id, text.replace("\n", " ").strip())
            count = await self.hass.async_add_executor_job(lambda: len(store.list_messages(session.id)))
            suggest = getattr(provider, "suggest_title", None) if count <= 1 else None
            parts: list[str] = []
            tools: list[dict[str, Any]] = []
            error: str | None = None
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
                title = await suggest(text, answer)
            except Exception:
                _LOGGER.debug("Assist title skipped", exc_info=True)
                title = None
            if title:
                await self.hass.async_add_executor_job(
                    store.apply_generated_title, user_id, session.id, text, title
                )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    def _reply(self, chat_log: conversation.ChatLog, text: str) -> None:
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=self.entity_id, content=text)
        )
