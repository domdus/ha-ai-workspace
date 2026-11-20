"""Endpoints of the Tasks page (admin only).

The page saves and deletes the automation itself through Home Assistant's automation config API
(``/api/config/automation/config/<id>``, the automation editor's own path). These endpoints only
list the labelled automations, build the config for a task form, and put the label on.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .const import DOMAIN
from .tasks import (
    TASK_LABEL,
    TASK_LABEL_ICON,
    STATUS_RUNNING,
    build_automation,
    new_automation_id,
    parse_automation,
    task_key,
    task_state,
)

_LOGGER = logging.getLogger(__name__)
_LABEL_WAIT = 15.0


def task_label_id(hass: HomeAssistant, create: bool = False) -> str:
    registry = lr.async_get(hass)
    found = registry.async_get_label_by_name(TASK_LABEL)
    if found is None and create:
        found = registry.async_create(TASK_LABEL, icon=TASK_LABEL_ICON, color="primary")
    return found.label_id if found is not None else ""


def labelled_automations(hass: HomeAssistant, label_id: str) -> list[er.RegistryEntry]:
    """Exactly the automations with the AI Workspace label."""
    if not label_id:
        return []
    return [
        row
        for row in er.async_entries_for_label(er.async_get(hass), label_id)
        if row.domain == "automation"
    ]


def _raw_config(hass: HomeAssistant, entity_id: str) -> dict[str, Any] | None:
    try:
        from homeassistant.components.automation import DATA_COMPONENT
    except ImportError:  # older Home Assistant
        DATA_COMPONENT = "automation"
    component = hass.data.get(DATA_COMPONENT)
    entity = component.get_entity(entity_id) if component is not None else None
    raw = getattr(entity, "raw_config", None)
    return dict(raw) if isinstance(raw, dict) else None


def task_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    state = task_state(hass)
    rows: list[dict[str, Any]] = []
    for entry in labelled_automations(hass, task_label_id(hass)):
        config = _raw_config(hass, entry.entity_id)
        parsed = parse_automation(config)
        live = hass.states.get(entry.entity_id)
        key = task_key(parsed.get("task_name") or parsed.get("name") or "") if parsed.get("has_task") else ""
        last = state.get(key) if key else {}
        rows.append(
            {
                "id": str((config or {}).get("id") or entry.unique_id or ""),
                "entity_id": entry.entity_id,
                "name": parsed.get("name") or (live.name if live else entry.entity_id),
                "enabled": bool(live and live.state == "on"),
                "available": live is not None and live.state != "unavailable",
                "last_triggered": str((live.attributes.get("last_triggered") if live else "") or ""),
                "last_run": last.get("last_run"),
                "last_status": STATUS_RUNNING if key and key in state.running else last.get("last_status"),
                "last_error": last.get("last_error") or "",
                "last_duration": last.get("last_duration"),
                "last_agent": last.get("last_agent") or "",
                "chat_id": last.get("chat_id") or "",
                **{name: value for name, value in parsed.items() if name != "name"},
            }
        )
    rows.sort(key=lambda row: str(row.get("name") or "").casefold())
    return rows


def _agents(hass: HomeAssistant) -> list[dict[str, str]]:
    data = hass.data.get(DOMAIN) or {}
    found = []
    for provider in (data.get("providers") or {}).values():
        info = getattr(provider, "info", None)
        if info is None:
            continue
        found.append({"id": str(info.id), "label": str(info.title or info.label or info.id)})
    return found


def _notify_targets(hass: HomeAssistant) -> list[dict[str, str]]:
    found = [
        {"id": f"notify.{name}", "label": f"notify.{name}"}
        for name in sorted(hass.services.async_services_for_domain("notify"))
        if name not in {"send_message", "notify", "persistent_notification"}
    ]
    for state in hass.states.async_all("notify"):
        found.append({"id": state.entity_id, "label": str(state.name or state.entity_id)})
    found.append({"id": "notify.persistent_notification", "label": "Home Assistant (persistent notification)"})
    return found


def _admin(request: web.Request) -> HomeAssistant:
    from .http import _hass

    user = request.get("hass_user")
    if user is None or not user.is_admin:
        raise web.HTTPUnauthorized()
    return _hass(request)


class TasksView(HomeAssistantView):
    url = "/api/ai_workspace/tasks"
    name = "api:ai_workspace:tasks"

    async def get(self, request: web.Request) -> web.Response:
        hass = _admin(request)
        await task_state(hass).load()
        return self.json(
            {
                "tasks": task_rows(hass),
                "agents": _agents(hass),
                "notify": _notify_targets(hass),
                "label": TASK_LABEL,
            }
        )


class TaskBuildView(HomeAssistantView):
    """The automation config for a task form. The page then saves it through the editor's API."""

    url = "/api/ai_workspace/tasks/build"
    name = "api:ai_workspace:tasks:build"

    async def post(self, request: web.Request) -> web.Response:
        hass = _admin(request)
        try:
            body = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid JSON.") from None
        form = body.get("form") if isinstance(body, dict) else None
        if not isinstance(form, dict):
            raise web.HTTPBadRequest(text="Missing form.")
        automation_id = str(body.get("id") or "").strip()
        existing = None
        if automation_id:
            entity_id = er.async_get(hass).async_get_entity_id("automation", "automation", automation_id)
            existing = _raw_config(hass, entity_id) if entity_id else None
        try:
            config = build_automation(form, existing)
        except ValueError as exc:
            return self.json({"error": str(exc)}, status_code=400)
        return self.json({"id": automation_id or new_automation_id(), "config": config})


class TaskLabelView(HomeAssistantView):
    """Put the AI Workspace label on a task's automation once Home Assistant loaded it."""

    url = "/api/ai_workspace/tasks/{automation_id}/label"
    name = "api:ai_workspace:tasks:label"

    async def post(self, request: web.Request, automation_id: str) -> web.Response:
        hass = _admin(request)
        registry = er.async_get(hass)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _LABEL_WAIT
        entity_id = registry.async_get_entity_id("automation", "automation", automation_id)
        while entity_id is None and loop.time() < deadline:
            await asyncio.sleep(0.25)
            entity_id = registry.async_get_entity_id("automation", "automation", automation_id)
        if entity_id is None:
            return self.json({"error": "The automation did not load. Check it in the automation editor."}, status_code=404)
        label_id = task_label_id(hass, create=True)
        row = registry.async_get(entity_id)
        if row is not None and label_id not in row.labels:
            registry.async_update_entity(entity_id, labels={*row.labels, label_id})
        return self.json({"entity_id": entity_id, "label_id": label_id})


def register_task_views(hass: HomeAssistant) -> None:
    for view in (TasksView, TaskBuildView, TaskLabelView):
        hass.http.register_view(view())
