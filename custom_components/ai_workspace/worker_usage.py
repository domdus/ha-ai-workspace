"""Usage of a coding worker (agent-worker / cursor-worker) read from its MCP tool results.

A chat agent can hand a task to a worker over MCP (agent_run, then agent_job to poll).
The worker reports what its own engine used once the job is done. That usage is not part
of the chat model's bill, so it becomes a separate usage event marked worker=True.

Only final jobs count (succeeded, failed, cancelled): a running job has no usage yet, and
each poll of a finished job repeats the same numbers, so run_id ("worker:<job_id>") lets
the store keep one row per job.

Pure Python: the integration and the Runtime ship separate copies of this file.
"""

from __future__ import annotations

import json
from typing import Any

# Tools that return a job payload. cursor_* are the older cursor-worker names.
JOB_TOOLS = frozenset(
    {"agent_run", "agent_job", "agent_cancel", "agent_approve", "cursor_agent", "cursor_job", "cursor_cancel"}
)
# Tools that take a model argument for the job they start.
_STARTS = frozenset({"agent_run", "cursor_agent"})
FINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "completed"})
WORKER_PREFIX = "worker:"
ENGINE_LABELS = {"cursor": "Cursor", "claude": "Claude Code", "codex": "OpenAI Codex"}

_COUNTS = (
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def bare_tool_name(name: object) -> str:
    """agent_job from agent_job, worker__agent_job, mcp__worker__agent_job or worker.agent_job."""
    text = str(name or "").strip()
    for sep in ("__", "/", "."):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text.lower()


def is_job_tool(name: object) -> bool:
    return bare_tool_name(name) in JOB_TOOLS


def worker_agent_id(engine: str) -> str:
    return WORKER_PREFIX + (str(engine or "").strip().lower() or "unknown")


def worker_agent_label(engine: str) -> str:
    key = str(engine or "").strip().lower()
    return f"Worker: {ENGINE_LABELS.get(key, key or 'unknown')}"


def _loads(text: object) -> Any:
    if not isinstance(text, str):
        return None
    body = text.strip()
    if not body or body[0] not in "{[":
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None


def _job_like(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict) and ("status" in value or "usage" in value or "job_id" in value):
        return value
    return None


def job_payload_of(result: Any) -> dict[str, Any] | None:
    """The worker's job payload from an MCP tool result.

    structuredContent first (FastMCP puts the returned dict there, sometimes under "result"),
    then the JSON in the first text block. Accepts a JSON-RPC message or a JSON string too.
    """
    if isinstance(result, (str, bytes)):
        text = result.decode("utf-8", "replace") if isinstance(result, bytes) else result
        parsed = _loads(text)
        if parsed is None:
            return None
        result = parsed
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("result"), dict) and ("jsonrpc" in result or "id" in result):
        result = result["result"]
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        found = _job_like(structured) or _job_like(structured.get("result"))
        if found is not None:
            return found
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                found = _job_like(_loads(block.get("text")))
                if found is not None:
                    return found
                break
    if "content" not in result and "structuredContent" not in result:
        return _job_like(result)
    return None


def _has_usage(usage: dict[str, Any]) -> bool:
    for key in _COUNTS:
        try:
            if float(usage.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    for key in ("cost_usd", "charged_cents", "total_cents"):
        if usage.get(key) not in (None, "", 0, 0.0):
            return True
    return False


def worker_usage_event(name: object, args: Any, result: Any) -> dict[str, Any] | None:
    """A usage event for a finished worker job, or None.

    None for other tools, jobs that are still running, queued or waiting for approval,
    and jobs that report no usage.
    """
    tool = bare_tool_name(name)
    if tool not in JOB_TOOLS:
        return None
    job = job_payload_of(result)
    if job is None:
        return None
    status = str(job.get("status") or "").strip().lower()
    if status not in FINAL_STATUSES:
        legacy = str(job.get("legacy_status") or "").strip().lower()
        if legacy in FINAL_STATUSES:
            status = legacy
        else:
            return None
    usage = job.get("usage")
    if not isinstance(usage, dict) or not _has_usage(usage):
        return None
    engine = str(job.get("engine") or "").strip().lower()
    if not engine:
        engine = "cursor" if tool.startswith("cursor_") else "unknown"
    job_id = str(job.get("job_id") or job.get("id") or "").strip()
    model = str(usage.get("model") or job.get("model") or "").strip()
    if not model and tool in _STARTS and isinstance(args, dict):
        model = str(args.get("model") or "").strip()
    event: dict[str, Any] = {key: usage[key] for key in _COUNTS if key in usage}
    for key in ("cost_usd", "charged_cents", "total_cents", "cost_source"):
        if usage.get(key) is not None:
            event[key] = usage[key]
    if event.get("cost_usd") is not None and event.get("charged_cents") is None and not event.get("cost_source"):
        # The engine reported this price itself (Claude Code); keep it over a list-price estimate.
        event["cost_source"] = "provider"
    event.update(
        {
            "type": "usage",
            "worker": True,
            "engine": engine,
            "job_id": job_id,
            "status": status,
            "model": model,
            "run_id": f"{WORKER_PREFIX}{job_id}" if job_id else "",
        }
    )
    return event


def _json_messages(text: str):
    body = text.strip()
    if body.startswith("{") or body.startswith("["):
        yield body
        return
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line.startswith("{") or line.startswith("["):
            yield line


def worker_usage_from_response(name: object, args: Any, raw: bytes | str) -> dict[str, Any] | None:
    """worker_usage_event for a raw MCP HTTP answer (JSON or server-sent events)."""
    if not is_job_tool(name):
        return None
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    for chunk in _json_messages(text):
        try:
            payload = json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue
        messages = payload if isinstance(payload, list) else [payload]
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("result"), dict):
                continue
            event = worker_usage_event(name, args, message["result"])
            if event is not None:
                return event
    return None
