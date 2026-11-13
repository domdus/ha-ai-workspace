"""Usage of coding-worker jobs (agent_run / agent_job) recorded per engine, once per job."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.ai_workspace.api_provider import ApiProvider
from custom_components.ai_workspace.const import DOMAIN
from custom_components.ai_workspace.models import Settings
from custom_components.ai_workspace.sensor import worker_rows
from custom_components.ai_workspace.store import Store
from custom_components.ai_workspace.usage_cost import estimate_cost, parse_usage
from custom_components.ai_workspace.usage_record import finalize_worker_usage, record_worker_usage
from custom_components.ai_workspace.worker_usage import (
    bare_tool_name,
    job_payload_of,
    worker_usage_event,
    worker_usage_from_response,
)

_CLAUDE_USAGE = {
    "prompt_tokens": 1200,
    "completion_tokens": 300,
    "cache_read_tokens": 5000,
    "cache_write_tokens": 0,
    "total_tokens": 1500,
    "charged_cents": None,
    "cost_usd": 0.0421,
}
_CODEX_USAGE = {
    "prompt_tokens": 8000,
    "completion_tokens": 900,
    "cache_read_tokens": 2000,
    "cache_write_tokens": 0,
    "reasoning_tokens": 400,
    "total_tokens": 8900,
    "charged_cents": None,
    "cost_usd": None,
}
_CURSOR_USAGE = {
    "prompt_tokens": 400,
    "completion_tokens": 100,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "total_tokens": 500,
    "charged_cents": 7,
}


def _job(status="succeeded", engine="claude", usage=None, job_id="j1") -> dict:
    out = {"job_id": job_id, "status": status, "engine": engine, "workspace": "default"}
    if usage is not None:
        out["usage"] = usage
    return out


def _structured(job: dict, text: str | None = None) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(job) if text is None else text}],
        "structuredContent": job,
    }


def _text_only(job: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(job)}]}


# --- extraction ---


def test_reads_usage_from_structured_content() -> None:
    event = worker_usage_event("agent_job", {"job_id": "j1"}, _structured(_job(usage=_CLAUDE_USAGE), text="Done."))
    assert event is not None
    assert event["type"] == "usage"
    assert event["worker"] is True
    assert event["engine"] == "claude"
    assert event["job_id"] == "j1"
    assert event["run_id"] == "worker:j1"
    assert event["prompt_tokens"] == 1200
    assert event["cost_usd"] == 0.0421
    assert event["cost_source"] == "provider"


def test_structured_content_wrapped_in_result() -> None:
    result = {"content": [], "structuredContent": {"result": _job(usage=_CLAUDE_USAGE)}}
    assert job_payload_of(result)["job_id"] == "j1"


def test_falls_back_to_json_in_first_text_block() -> None:
    event = worker_usage_event("agent_run", {"task": "x"}, _text_only(_job(engine="codex", usage=_CODEX_USAGE)))
    assert event is not None
    assert event["engine"] == "codex"
    assert event["completion_tokens"] == 900
    assert event.get("cost_usd") is None


def test_json_string_and_jsonrpc_message() -> None:
    job = _job(usage=_CLAUDE_USAGE)
    assert worker_usage_event("agent_job", {}, json.dumps(job))["job_id"] == "j1"
    message = {"jsonrpc": "2.0", "id": 3, "result": _structured(job)}
    assert worker_usage_event("agent_job", {}, message)["job_id"] == "j1"


def test_other_tools_and_plain_text_give_nothing() -> None:
    assert worker_usage_event("ha_get_state", {}, _structured(_job(usage=_CLAUDE_USAGE))) is None
    assert worker_usage_event("agent_job", {}, {"content": [{"type": "text", "text": "not json"}]}) is None
    assert worker_usage_event("agent_job", {}, None) is None
    assert worker_usage_event("agent_job", {}, _structured(_job(usage={"prompt_tokens": 0}))) is None


def test_prefixed_and_legacy_tool_names() -> None:
    assert bare_tool_name("mcp__worker__agent_job") == "agent_job"
    assert bare_tool_name("worker.agent_run") == "agent_run"
    legacy = _job(engine="", usage=_CURSOR_USAGE)
    legacy.pop("engine")
    event = worker_usage_event("cursor_job", {}, _structured(legacy))
    assert event["engine"] == "cursor"
    assert event["charged_cents"] == 7
    assert worker_usage_event("worker__cursor_agent", {}, _structured(legacy))["engine"] == "cursor"


def test_agent_run_model_argument_is_used_when_usage_has_none() -> None:
    event = worker_usage_event("agent_run", {"model": "gpt-5"}, _structured(_job(engine="codex", usage=_CODEX_USAGE)))
    assert event["model"] == "gpt-5"
    # agent_job has no model argument; its job_id says nothing about the model.
    assert worker_usage_event("agent_job", {"model": "gpt-5"}, _structured(_job(engine="codex", usage=_CODEX_USAGE)))[
        "model"
    ] == ""


def test_sse_answer_from_the_proxy() -> None:
    message = {"jsonrpc": "2.0", "id": 1, "result": _structured(_job(usage=_CLAUDE_USAGE))}
    raw = f"event: message\ndata: {json.dumps(message)}\n\n".encode()
    event = worker_usage_from_response("agent_job", {}, raw)
    assert event["run_id"] == "worker:j1"
    assert worker_usage_from_response("ha_get_state", {}, raw) is None


# --- final-status gating ---


def test_only_final_jobs_report_usage() -> None:
    for status in ("running", "queued", "needs_approval", "unknown", "rejected"):
        assert worker_usage_event("agent_job", {}, _structured(_job(status=status, usage=_CLAUDE_USAGE))) is None, status
    for status in ("succeeded", "failed", "cancelled"):
        assert worker_usage_event("agent_job", {}, _structured(_job(status=status, usage=_CLAUDE_USAGE))), status


def test_finalize_refuses_events_that_are_not_final() -> None:
    event = worker_usage_event("agent_job", {}, _structured(_job(usage=_CLAUDE_USAGE)))
    assert finalize_worker_usage({**event, "status": "running"}) is None
    assert finalize_worker_usage(event) is not None


# --- cost_source ---


def test_provider_cost_without_cents_is_kept() -> None:
    usage = estimate_cost(parse_usage({"prompt_tokens": 1000, "completion_tokens": 10, "cost_usd": 0.5}, model="gpt-4o"))
    assert usage.cost_usd == 0.5
    assert usage.cost_source == "provider"


def test_own_estimate_read_back_stays_an_estimate() -> None:
    usage = parse_usage({"prompt_tokens": 10, "cost_usd": 0.01, "cost_source": "estimate"})
    assert (usage.cost_usd, usage.cost_source) == (0.01, "estimate")


def test_charged_cents_still_win() -> None:
    usage = estimate_cost(parse_usage({"prompt_tokens": 10, "cost_usd": 0.5, "charged_cents": 3}))
    assert (usage.cost_usd, usage.cost_source) == (0.03, "cursor_sdk")


def test_claude_worker_keeps_reported_cost() -> None:
    event = worker_usage_event("agent_job", {}, _structured(_job(usage=_CLAUDE_USAGE)))
    billed = finalize_worker_usage(event)
    assert billed.cost_usd == 0.0421
    assert billed.cost_source == "provider"


def test_codex_worker_with_known_model_is_estimated() -> None:
    event = worker_usage_event("agent_run", {"model": "gpt-5"}, _structured(_job(engine="codex", usage=_CODEX_USAGE)))
    billed = finalize_worker_usage(event)
    assert billed.cost_source == "estimate"
    assert billed.cost_usd and billed.cost_usd > 0


def test_codex_worker_without_model_keeps_tokens_cost_unknown() -> None:
    event = worker_usage_event("agent_job", {}, _structured(_job(engine="codex", usage=_CODEX_USAGE)))
    billed = finalize_worker_usage(event)
    assert billed.cost_usd is None
    assert billed.cost_source == "estimate"
    assert billed.prompt_tokens == 8000


# --- recording: per-engine identity and dedupe ---


def _hass(store: Store, track: bool = True):
    fired: list = []

    async def run(fn, *args):
        return fn(*args)

    hass = SimpleNamespace(
        data={DOMAIN: {"settings": SimpleNamespace(track_usage=track), "store": store}},
        async_add_executor_job=run,
        bus=SimpleNamespace(async_fire=lambda name, payload: fired.append(payload)),
        config=SimpleNamespace(time_zone="UTC"),
    )
    return hass, fired


def _record(hass, store, event, session="s1"):
    async def go():
        with patch("custom_components.ai_workspace.usage_record.async_dispatcher_send"):
            return await record_worker_usage(
                hass, store=store, user_id="u1", session_id=session, event=event, origin="chat"
            )

    return asyncio.run(go())


def test_repeated_agent_job_polls_store_one_row(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    hass, fired = _hass(store)
    running = _structured(_job(status="running"))
    done = _structured(_job(usage=_CLAUDE_USAGE))
    events = [worker_usage_event("agent_job", {}, result) for result in (running, done, done, done)]
    assert events[0] is None
    recorded = [_record(hass, store, event) for event in events[1:]]
    assert recorded[0] is not None and recorded[0]["agent_id"] == "worker:claude"
    assert recorded[1] is None and recorded[2] is None
    assert store.summarize_usage()["turns"] == 1
    assert len(fired) == 1
    assert store.has_usage_run("worker:j1")


def test_engines_are_grouped_apart_from_the_chat_agent(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    hass, _fired = _hass(store)
    store.add_usage(user_id="u1", session_id="s1", agent_id="openai", agent="OpenAI", model="gpt-4o", total_tokens=50)
    _record(hass, store, worker_usage_event("agent_job", {}, _structured(_job(usage=_CLAUDE_USAGE, job_id="a"))))
    _record(hass, store, worker_usage_event("agent_job", {}, _structured(_job(engine="codex", usage=_CODEX_USAGE, job_id="b"))))
    _record(hass, store, worker_usage_event("cursor_job", {}, _structured(_job(engine="cursor", usage=_CURSOR_USAGE, job_id="c"))))
    rows = {row["agent_id"]: row for row in store.usage_by_agent()}
    assert set(rows) == {"openai", "worker:claude", "worker:codex", "worker:cursor"}
    assert rows["worker:claude"]["agent"] == "Worker: Claude Code"
    assert rows["worker:claude"]["provider"] == "worker"
    assert rows["worker:claude"]["cost_usd"] == 0.0421
    assert rows["worker:cursor"]["cost_usd"] == 0.07
    assert rows["worker:codex"]["missing_cost"] is True
    # The chat agent's own total is not touched by the worker.
    assert store.summarize_usage(agent_id="openai")["total_tokens"] == 50
    models = {row["agent_id"] for row in store.usage_by_model()}
    assert {"worker:claude", "worker:codex", "worker:cursor"} <= models
    workers = worker_rows(store.usage_by_agent())
    assert set(workers) == {"worker:claude", "worker:codex", "worker:cursor"}
    assert workers["worker:codex"]["missing_cost"] is True


def test_track_usage_off_stores_nothing(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    hass, fired = _hass(store, track=False)
    _record(hass, store, worker_usage_event("agent_job", {}, _structured(_job(usage=_CLAUDE_USAGE))))
    assert store.summarize_usage()["turns"] == 0
    assert fired == []


def test_store_unique_run_skips_known_run(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    assert store.add_usage(user_id="u", run_id="worker:x", total_tokens=1, unique_run=True)
    assert store.add_usage(user_id="u", run_id="worker:x", total_tokens=1, unique_run=True) == 0
    # Without unique_run (normal chat turns) nothing changes.
    assert store.add_usage(user_id="u", run_id="worker:x", total_tokens=1)
    assert store.summarize_usage()["turns"] == 2


# --- API agents emit a separate worker usage event ---


def _settings(provider: str) -> Settings:
    return Settings(
        data_dir=Path("/tmp"),
        workspace_dir=Path("/tmp/workspace"),
        state_dir=Path("/tmp/state"),
        cursor_api_key="",
        model="gpt-4o",
        mcp_servers={},
        api_provider=provider,
        api_key="k",
    )


class _WorkerBundle:
    tools = [{"name": "agent_job", "description": "Job", "inputSchema": {"type": "object", "properties": {}}}]

    def original_name(self, name):
        return name

    async def call_tool(self, name, args):
        return _structured(_job(usage=_CLAUDE_USAGE))


def test_api_agent_yields_worker_usage_separately() -> None:
    for loop in ("openai", "anthropic"):
        provider = ApiProvider(None, _settings(loop), None)
        anthropic = loop == "anthropic"
        rounds: list = []

        async def fake_round(_http, _url, _headers, payload, anthropic=anthropic, rounds=rounds):
            rounds.append(payload)
            if len(rounds) == 1:
                yield "usage", parse_usage({"prompt_tokens": 100, "completion_tokens": 5})
                if anthropic:
                    yield "message", [{"type": "tool_use", "id": "t1", "name": "agent_job", "input": {"job_id": "j1"}}]
                else:
                    call = {"id": "c1", "type": "function", "function": {"name": "agent_job", "arguments": '{"job_id": "j1"}'}}
                    yield "message", {"role": "assistant", "content": None, "tool_calls": [call]}
                return
            yield "text", "Done."
            yield "message", [{"type": "text", "text": "Done."}] if anthropic else {"role": "assistant", "content": "Done."}

        async def collect(provider=provider, anthropic=anthropic, fake_round=fake_round):
            if anthropic:
                provider._anthropic_round = fake_round
                gen = provider._anthropic(None, [], "Fix it", _WorkerBundle(), "", [], "en", True, False)
            else:
                provider._openai_round = fake_round
                gen = provider._openai(None, [], "Fix it", _WorkerBundle(), "", [], "en", True, False)
            return [event async for event in gen]

        events = asyncio.run(collect())
        usage = [event for event in events if event.get("type") == "usage"]
        workers = [event for event in usage if event.get("worker")]
        own = [event for event in usage if not event.get("worker")]
        assert len(workers) == 1, loop
        assert workers[0]["engine"] == "claude"
        assert workers[0]["cost_usd"] == 0.0421
        assert len(own) == 1, loop
        # The chat model's own turn does not include the worker's tokens.
        assert own[0]["prompt_tokens"] == 100, loop


# --- Runtime (add-on) proxy keeps worker usage per chat ---


def test_runtime_proxy_queues_worker_usage_per_chat(tmp_path) -> None:
    from app.mcp_proxy import McpProxy
    from app.providers.cursor import _take_worker_usage
    from app.worker_usage import worker_usage_from_response as runtime_from_response

    proxy = McpProxy(tmp_path / "secret")
    message = {"jsonrpc": "2.0", "id": 1, "result": _structured(_job(usage=_CLAUDE_USAGE))}
    raw = json.dumps(message).encode()
    proxy.note_worker_usage("chat-1", runtime_from_response("agent_job", {}, raw))
    proxy.note_worker_usage("chat-1", runtime_from_response("agent_job", {}, raw))
    proxy.note_worker_usage("chat-1", None)
    proxy.note_worker_usage("", runtime_from_response("agent_job", {}, raw))
    runtime = SimpleNamespace(proxy=proxy)
    taken = _take_worker_usage(runtime, "chat-1")
    assert [event["run_id"] for event in taken] == ["worker:j1"]
    assert _take_worker_usage(runtime, "chat-1") == []
    assert _take_worker_usage(SimpleNamespace(proxy=object()), "chat-1") == []
