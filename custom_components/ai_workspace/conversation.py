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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .agents import Agent, entry_agents
from .const import DOMAIN, provider_token_mode, token_mode_allows_extras
from .chat_scope import handoff_note, merge_reply_text, other_chat_note
from .http import _create_runtime_session, async_agent_events
from .small_talk import wants_house_tools
from .store import Store
from .titles import accept_generated_title, needs_title_summary, title_from_prompt
from .usage_record import finalize_usage, record_usage_turn

_LOGGER = logging.getLogger(__name__)


async def _login_token(hass: HomeAssistant, user_id: str) -> str | None:
    """Short-lived token for the person who opened Assist.

    The sidebar chat sends the browser login. Assist does not, so an empty
    MCP token would leave Home Assistant tools unauthorized. Only a normal
    login is used, never a long-lived access token.
    """
    from homeassistant.auth.models import TOKEN_TYPE_NORMAL

    if not user_id or user_id == "assist":
        return None
    try:
        user = await hass.auth.async_get_user(user_id)
    except Exception:
        return None
    if user is None:
        return None
    logins = [
        token
        for token in getattr(user, "refresh_tokens", {}).values()
        if getattr(token, "token_type", None) == TOKEN_TYPE_NORMAL
    ]
    if not logins:
        _LOGGER.info("Assist user %s has no browser or app login; Home Assistant MCP tools are skipped", user.name)
        return None
    refresh = max(logins, key=lambda token: token.last_used_at or token.created_at)
    try:
        return hass.auth.async_create_access_token(refresh)
    except Exception:
        _LOGGER.debug("Assist login token skipped", exc_info=True)
        return None


async def _is_admin(hass: HomeAssistant, user_id: str) -> bool:
    """Voice satellites run without a user and get the tools the administrator set up."""
    if not user_id or user_id == "assist":
        return True
    try:
        user = await hass.auth.async_get_user(user_id)
    except Exception:
        return False
    return user is None or bool(user.is_admin)


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Expose each agent that has Assist on."""
    from .assist_pipelines import async_prune_voice_entities

    keep: set[str] = set()
    wanted = 0
    for agent in entry_agents(entry):
        if agent.assist:
            keep.add(agent.id)
        if agent.assist and _agent_device_active(hass, entry.entry_id, agent.subentry_id):
            async_add_entities(
                [AiWorkspaceConversationEntity(entry, agent)],
                config_subentry_id=agent.subentry_id or None,
            )
            wanted += 1
        else:
            await _drop_assist_pipeline(hass, agent.id)
    await async_prune_voice_entities(hass, entry.entry_id, "conversation", keep)
    _LOGGER.info("Exposing %s Assist agent(s)", wanted)


class AiWorkspaceConversationEntity(conversation.ConversationEntity):
    """Native Assist agent that uses the same model as the sidebar chat."""

    _attr_supports_streaming = True
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_icon = "mdi:robot"
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry, agent: Agent) -> None:
        self._agent_id = agent.id
        self._title = agent.title or entry.title or "AI Workspace"
        self._attr_unique_id = agent.id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"agent:{agent.id}")},
            name=self._title,
            manufacturer="AI Workspace",
            model="Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.registry_entry is not None and self.registry_entry.disabled_by:
            return
        from .assist_pipelines import async_ensure_assist_pipeline

        await async_ensure_assist_pipeline(self.hass, self.entity_id, str(self._title))

    async def async_will_remove_from_hass(self) -> None:
        # Reloads unload the entity but the agent subentry stays — keep the pipeline.
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

        extras = token_mode_allows_extras(provider_token_mode(provider))
        extra = "" if not extras else str(user_input.extra_system_prompt or "").strip()
        outbound = f"{extra}\n\n{text}" if extra else text
        cross = bool(getattr(data.get("settings"), "cross_chat", False))
        note = (
            ""
            if not extras
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

        locks: dict[str, asyncio.Lock] = data.setdefault("locks", {})
        lock = locks.setdefault(session.id, asyncio.Lock())
        if lock.locked():
            self._reply(chat_log, "This chat is already waiting on the agent.")
            return conversation.async_get_result_from_chat_log(user_input, chat_log)
        async with lock:
            await self.hass.async_add_executor_job(store.add_message, session.id, "user", text, "[]")
            await self.hass.async_add_executor_job(store.rename_if_default, session.id, title_from_prompt(text))
            count = await self.hass.async_add_executor_job(lambda: len(store.list_messages(session.id)))
            handoff = ""
            if getattr(provider, "kind", "") == "cursor":
                rows = await self.hass.async_add_executor_job(store.list_messages, session.id)
                handoff = handoff_note(rows, session.title)
            suggest = (
                getattr(provider, "suggest_title", None)
                if extras and count <= 1 and needs_title_summary(text)
                else None
            )
            parts: list[str] = []
            tools: list[dict[str, Any]] = []
            final: str | None = None

            access_token = await _login_token(self.hass, user_id)
            admin = await _is_admin(self.hass, user_id)

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
                    admin=admin,
                    force_tools=wants_house_tools(text),
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
                    elif kind == "usage":
                        billed = finalize_usage(
                            event,
                            model=str(event.get("model") or getattr(provider, "model", "") or ""),
                            run_id=str(event.get("run_id") or ""),
                        )
                        if billed is not None:
                            await record_usage_turn(
                                self.hass,
                                store=store,
                                user_id=user_id,
                                session_id=session.id,
                                provider=provider,
                                usage=billed,
                                origin="assist",
                            )
                if started:
                    return
                answer = (final or error or "").strip() or "The agent returned nothing."
                yield {"role": "assistant", "content": answer}

            async for _content in chat_log.async_add_delta_content_stream(self.entity_id, deltas()):
                pass

            answer = merge_reply_text("".join(parts), final)
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

        if locks.get(session.id) is lock and not lock.locked():
            locks.pop(session.id, None)
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
