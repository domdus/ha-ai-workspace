"""MCP elicitation forms: what a server asks for, and checking the user's answer against it.

An MCP server asks the user a question with ``elicitation/create`` (MCP 2025-06-18). Its
``requestedSchema`` is a flat JSON Schema object with string, number, integer, boolean and
enum fields. The chat shows those as a small form; an approval (no fields, or one required
yes/no field) is just the two buttons.

Pure Python: the integration and the Runtime ship separate copies of this file.
"""

from __future__ import annotations

import math
import re
from typing import Any

ACTIONS = ("accept", "decline", "cancel")
# Longest message and field texts kept for the card; a server cannot fill the chat.
MESSAGE_CHARS = 4000
TEXT_CHARS = 300
VALUE_CHARS = 4000
MAX_FIELDS = 20
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _text(value: Any, limit: int = TEXT_CHARS) -> str:
    text = str(value if value is not None else "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _enum_choices(spec: dict[str, Any]) -> tuple[list[str], list[str]] | None:
    """(values, labels) of an enum field: ``enum`` (+ legacy ``enumNames``) or ``oneOf`` const/title."""
    values = spec.get("enum")
    if isinstance(values, list) and values:
        names = spec.get("enumNames")
        labels = names if isinstance(names, list) and len(names) == len(values) else values
        return [str(item) for item in values], [_text(item) for item in labels]
    options = spec.get("oneOf") or spec.get("anyOf")
    if isinstance(options, list) and options:
        found = [item for item in options if isinstance(item, dict) and "const" in item]
        if found and len(found) == len(options):
            return [str(item["const"]) for item in found], [_text(item.get("title") or item["const"]) for item in found]
    return None


def form_fields(schema: Any) -> list[dict[str, Any]]:
    """The fields of a requestedSchema, in order, as the chat card draws them.

    Each field: name, kind (string, number, integer, boolean, enum or unsupported), title,
    description, required, default and, where it applies, choices/labels, min/max, format.
    """
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    fields: list[dict[str, Any]] = []
    for name, spec in list(props.items())[:MAX_FIELDS]:
        if not isinstance(spec, dict):
            spec = {}
        kind = str(spec.get("type") or "").strip().lower()
        field: dict[str, Any] = {
            "name": str(name),
            "title": _text(spec.get("title") or name),
            "description": _text(spec.get("description") or ""),
            "required": name in required,
        }
        choices = _enum_choices(spec)
        if choices is not None and kind in {"", "string"}:
            field["kind"] = "enum"
            field["choices"], field["labels"] = choices
        elif kind in {"string", "number", "integer", "boolean"}:
            field["kind"] = kind
        else:
            field["kind"] = "unsupported"
        if field["kind"] == "string":
            for key in ("minLength", "maxLength"):
                if isinstance(spec.get(key), int) and not isinstance(spec.get(key), bool):
                    field[key] = int(spec[key])
            if spec.get("format") in {"email", "uri", "date", "date-time"}:
                field["format"] = spec["format"]
        if field["kind"] in {"number", "integer"}:
            for key in ("minimum", "maximum"):
                if _number(spec.get(key)) is not None:
                    field[key] = _number(spec[key])
        if "default" in spec and spec["default"] is not None:
            field["default"] = spec["default"]
        fields.append(field)
    return fields


def approval_field(fields: list[dict[str, Any]]) -> str:
    """The yes/no field the Allow button answers, when the form is an approval; else "".

    That is a form whose only boolean field is required (agent-worker asks approve: bool plus an
    optional note). Allow sends it as true; the field itself is not drawn.
    """
    flags = [field for field in fields if field.get("kind") == "boolean"]
    if len(flags) == 1 and flags[0].get("required"):
        return str(flags[0]["name"])
    return ""


def is_confirmation(fields: list[dict[str, Any]]) -> bool:
    """True when the card is an approval (Allow / Deny): no fields, or a required yes/no field.

    Other fields of an approval (agent-worker's optional note) are drawn as optional inputs.
    """
    return not fields or bool(approval_field(fields))


def _check(field: dict[str, Any], value: Any) -> tuple[Any, str]:
    """(cleaned value, "" ) or (None, error code)."""
    kind = field.get("kind")
    if kind == "boolean":
        if isinstance(value, bool):
            return value, ""
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true", ""
        return None, "type"
    if kind in {"number", "integer"}:
        number = _number(value.strip() if isinstance(value, str) else value)
        if number is None:
            return None, "type"
        if kind == "integer":
            if number != int(number):
                return None, "type"
            number = int(number)
        if "minimum" in field and number < field["minimum"]:
            return None, "range"
        if "maximum" in field and number > field["maximum"]:
            return None, "range"
        return number, ""
    if kind == "enum":
        text = str(value)
        return (text, "") if text in field.get("choices", []) else (None, "choice")
    if kind == "string":
        if not isinstance(value, str):
            return None, "type"
        text = value.strip()[:VALUE_CHARS]
        if "minLength" in field and len(text) < field["minLength"]:
            return None, "length"
        if "maxLength" in field and len(text) > field["maxLength"]:
            return None, "length"
        if field.get("format") == "email" and text and not _EMAIL.match(text):
            return None, "format"
        return text, ""
    return None, "unsupported"


def check_answer(schema: Any, action: Any, content: Any) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """The elicitation result to send for a user's answer, or (None, {field: error}).

    decline and cancel never carry content. accept keeps only fields of the schema, with the
    right types; a required field that is missing or wrong refuses the answer.
    """
    action = str(action or "").strip().lower()
    if action not in ACTIONS:
        return None, {"": "action"}
    if action != "accept":
        return {"action": action}, {}
    fields = form_fields(schema)
    given = content if isinstance(content, dict) else {}
    flag = approval_field(fields)
    cleaned: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for field in fields:
        name = field["name"]
        value = given.get(name)
        if name == flag and value is None:
            value = True
        if value is None or (isinstance(value, str) and not value.strip() and field.get("kind") != "string"):
            if field.get("required"):
                errors[name] = "required"
            continue
        if isinstance(value, str) and not value.strip() and field.get("kind") == "string":
            if field.get("required"):
                errors[name] = "required"
            continue
        ok, error = _check(field, value)
        if error:
            errors[name] = error
            continue
        cleaned[name] = ok
    if errors:
        return None, errors
    return {"action": "accept", "content": cleaned}, {}


def card_of(params: Any) -> dict[str, Any]:
    """What the chat card shows for elicitation/create params: message, fields, confirmation."""
    params = params if isinstance(params, dict) else {}
    schema = params.get("requestedSchema") if isinstance(params.get("requestedSchema"), dict) else {}
    fields = form_fields(schema)
    return {
        "message": _text(params.get("message") or "", MESSAGE_CHARS),
        "schema": schema,
        "fields": fields,
        "approval_field": approval_field(fields),
        "confirmation": is_confirmation(fields),
    }
