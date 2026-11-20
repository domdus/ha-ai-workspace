"""Agent fallback chain: classifier, list walking, capabilities, pause/resume, promotion, handoff."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.ai_workspace.fallback import (
    BACKOFF_SECONDS,
    CAP_CHAT,
    CAP_WORKSPACE,
    KIND_AUTH,
    KIND_CONNECTION,
    KIND_LIMIT,
    KIND_OVERLOADED,
    KIND_TIMEOUT,
    PROMOTION_LOCK_SECONDS,
    RETURN_AFTER_RESET,
    RETURN_NEW_MESSAGE,
    RETURN_OFF,
    ChatFallback,
    Failure,
    FallbackBook,
    TurnJournal,
    agent_caps,
    classify_exception,
    classify_failure,
    clean_chain,
    first_ready,
    handoff_prompt,
    has_side_effect,
    next_agent,
    promotion_target,
    wait_for_agent,
)


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _err(message: str = "", **extra) -> dict:
    return {"type": "error", "message": message, **extra}


# --- Classifier -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "kind"),
    [
        (_err("", code="claude_plan_rejected", engine="claude", reset_at=1_700_000_000), KIND_LIMIT),
        (_err("", code="codex_plan_rejected"), KIND_LIMIT),
        (_err("Too many requests", status=429), KIND_LIMIT),
        (_err("This Claude credential hit its usage or rate limit. Try again later."), KIND_LIMIT),
        (_err("This Codex credential hit a rate limit. Try again later."), KIND_LIMIT),
        (_err("You exceeded your current quota, please check your plan and billing details."), KIND_LIMIT),
        (_err("Anthropic refused the request for billing reasons."), KIND_LIMIT),
        (_err("", code="claude_auth_failed"), KIND_AUTH),
        (_err("", code="codex_auth_failed"), KIND_AUTH),
        (_err("Incorrect API key provided", status=401), KIND_AUTH),
        (_err("Cursor API key is invalid: 401 Unauthorized"), KIND_AUTH),
        (_err("OAuth token has expired. Please run /login"), KIND_AUTH),
        (_err("The provider did not answer in time. Try again, or pick a faster model.", timeout=True), KIND_TIMEOUT),
        (_err("Request timed out after 600s"), KIND_TIMEOUT),
        (_err("gateway", status=504), KIND_TIMEOUT),
        (_err("AI Workspace runtime is unreachable at http://x: boom", connection=True), KIND_CONNECTION),
        (_err("Connection reset by peer (ECONNRESET)"), KIND_CONNECTION),
        (_err("API Error: 529 Overloaded"), KIND_OVERLOADED),
        (_err("OpenAI is overloaded right now. Try again later."), KIND_OVERLOADED),
        (_err("upstream", status=503), KIND_OVERLOADED),
        (_err("Internal server error", status=500), KIND_OVERLOADED),
    ],
)
def test_provider_failures_are_classified(event, kind) -> None:
    found = classify_failure(event)
    assert found is not None and found.kind == kind


@pytest.mark.parametrize(
    "event",
    [
        {"type": "text", "delta": "rate limit"},
        _err("Stopped by the user."),
        _err("anything", cancelled=True),
        _err("MCP server returned 401 Unauthorized"),
        _err("Home Assistant tools did not connect: connection refused"),
        _err("Tool failed"),
        _err("boom", tool_error=True),
        _err("I can't help with that request; it violates the content policy."),
        _err("The model refused to answer."),
        _err("This model's maximum context length is 128000 tokens."),
        _err("Invalid request: messages.0.content is empty", status=400),
        _err("rate limit words but a bad request", status=400),
        _err("Not found", status=404),
        _err("Unprocessable", status=422),
        _err("Codex does not offer the model gpt-x for this account."),
        _err("The model kept calling tools without finishing."),
        _err("The model finished without a reply. Try sending again."),
        _err(""),
    ],
)
def test_never_fall_back_on_user_tool_refusal_or_input_errors(event) -> None:
    assert classify_failure(event) is None


def test_limit_keeps_its_reset_time() -> None:
    found = classify_failure(_err("", code="claude_plan_rejected", reset_at="1700000000", window="week"))
    assert found == Failure(KIND_LIMIT, 1_700_000_000, "claude", "week")


def test_exceptions_are_classified() -> None:
    class ApiError(RuntimeError):
        def __init__(self, status):
            super().__init__("x")
            self.status = status

    assert classify_exception(TimeoutError()).kind == KIND_TIMEOUT
    assert classify_exception(ConnectionRefusedError()).kind == KIND_CONNECTION
    assert classify_exception(ApiError(429)).kind == KIND_LIMIT
    assert classify_exception(ApiError(400)) is None
    assert classify_exception(asyncio.CancelledError()) is None
    assert classify_exception(ValueError("bad json")) is None


# --- Capabilities and list walking ------------------------------------------------------------

KINDS = {"claude": "claude", "cursor": "cursor", "openai": "api", "gemini": "api"}


def caps(agent: str):
    return agent_caps(KINDS.get(agent, ""))


def test_runtime_agents_have_a_workspace_cloud_agents_only_chat() -> None:
    assert agent_caps("claude") == {CAP_CHAT, CAP_WORKSPACE}
    assert agent_caps("codex") == {CAP_CHAT, CAP_WORKSPACE}
    assert agent_caps("api") == {CAP_CHAT}


def test_clean_chain_drops_unknown_and_duplicates() -> None:
    assert clean_chain(["a", "x", "b", "a", ""], {"a", "b"}) == ["a", "b"]


def test_walks_down_the_list_skipping_tried_waiting_and_unavailable() -> None:
    book = FallbackBook(Clock())
    chain = ["claude", "openai", "cursor", "gemini"]
    pick = lambda tried, **kw: next_agent(chain, tried=tried, needs={CAP_CHAT}, caps_of=caps, book=book, **kw)  # noqa: E731
    assert pick(["claude"]) == "openai"
    book.mark_failed("openai", Failure(KIND_CONNECTION))
    assert pick(["claude"]) == "cursor"
    assert pick(["claude"], available=lambda agent: agent != "cursor") == "gemini"
    assert pick(["claude", "cursor", "gemini"]) is None


def test_workspace_jobs_skip_chat_only_agents() -> None:
    book = FallbackBook(Clock())
    chain = ["claude", "openai", "gemini", "cursor"]
    found = next_agent(chain, tried=["claude"], needs={CAP_CHAT, CAP_WORKSPACE}, caps_of=caps, book=book)
    assert found == "cursor"
    assert next_agent(chain, tried=["claude", "cursor"], needs={CAP_CHAT, CAP_WORKSPACE}, caps_of=caps, book=book) is None


def test_new_chats_start_with_the_first_agent_that_is_not_waiting() -> None:
    clock = Clock()
    book = FallbackBook(clock)
    assert first_ready(["claude", "cursor"], book) == "claude"
    book.mark_failed("claude", Failure(KIND_LIMIT, int(clock.now) + 600))
    assert first_ready(["claude", "cursor"], book) == "cursor"
    clock.now += 601
    assert first_ready(["claude", "cursor"], book) == "claude"


# --- Backoff ----------------------------------------------------------------------------------


def test_backoff_is_5_15_60_minutes_and_a_known_reset_wins() -> None:
    clock = Clock()
    book = FallbackBook(clock)
    waits = []
    for _ in range(4):
        waits.append(book.mark_failed("a", Failure(KIND_CONNECTION)).until - clock.now)
    assert waits == [BACKOFF_SECONDS[0], BACKOFF_SECONDS[1], BACKOFF_SECONDS[2], BACKOFF_SECONDS[2]]
    assert BACKOFF_SECONDS == (300, 900, 3600)
    item = book.mark_failed("b", Failure(KIND_LIMIT, int(clock.now) + 5000))
    assert item.reset_known and item.until == clock.now + 5000
    book.mark_ok("a")
    assert not book.blocked("a")


def test_limits_are_not_probed_before_their_reset() -> None:
    clock = Clock()
    book = FallbackBook(clock)
    book.mark_failed("claude", Failure(KIND_LIMIT, int(clock.now) + 3600))
    assert not book.may_probe("claude", RETURN_NEW_MESSAGE)
    assert not book.may_probe("claude", RETURN_AFTER_RESET)
    clock.now += 3600
    assert book.may_probe("claude", RETURN_AFTER_RESET)


def test_new_message_checks_once_then_backs_off_after_reset_waits() -> None:
    clock = Clock()
    book = FallbackBook(clock)
    book.mark_failed("cursor", Failure(KIND_CONNECTION))
    assert book.may_probe("cursor", RETURN_NEW_MESSAGE)
    assert not book.may_probe("cursor", RETURN_AFTER_RESET)
    book.mark_failed("cursor", Failure(KIND_CONNECTION), probe=True)
    assert not book.may_probe("cursor", RETURN_NEW_MESSAGE)
    clock.now += BACKOFF_SECONDS[1]
    assert book.may_probe("cursor", RETURN_NEW_MESSAGE)


def test_state_survives_a_restart() -> None:
    clock = Clock()
    book = FallbackBook(clock)
    book.mark_failed("claude", Failure(KIND_LIMIT, int(clock.now) + 100))
    book.mark_failed("old", Failure(KIND_CONNECTION))
    book.set_chat("s1", ChatFallback(active="cursor", preferred="claude", fell_back=True, reason=KIND_LIMIT))
    saved = book.dump()
    clock.now += 400  # "old" waited 5 minutes: gone after the restart
    again = FallbackBook(clock)
    again.load(saved)
    assert "old" not in again.health
    assert "claude" not in again.health  # its reset passed too
    assert again.chat("s1").active == "cursor"


# --- Promotion --------------------------------------------------------------------------------


def _promote(chain, state, book, probe, mode=RETURN_NEW_MESSAGE, needs=None):
    return asyncio.run(
        promotion_target(chain, state, mode=mode, needs=needs or {CAP_CHAT}, caps_of=caps, book=book, probe=probe)
    )


def test_promotion_tries_from_the_top_with_a_cheap_probe() -> None:
    clock = Clock()
    book = FallbackBook(clock)
    asked: list[str] = []

    async def probe(agent):
        asked.append(agent)
        return Failure(KIND_CONNECTION) if agent == "claude" else None

    state = ChatFallback(active="gemini", preferred="claude", fell_back=True)
    assert _promote(["claude", "openai", "gemini"], state, book, probe) == "openai"
    assert asked == ["claude", "openai"]
    # The failed check counts: the next one waits for the backoff.
    assert book.blocked("claude") and book.health["claude"].probes == 1


def test_no_promotion_when_off_by_hand_locked_or_waiting() -> None:
    clock = Clock()
    book = FallbackBook(clock)

    async def probe(agent):
        raise AssertionError("must not probe")

    chain = ["claude", "cursor"]
    fell = ChatFallback(active="cursor", preferred="claude", fell_back=True)
    assert _promote(chain, fell, book, probe, mode=RETURN_OFF) is None
    assert _promote(chain, None, book, probe) is None
    assert _promote(chain, ChatFallback(active="cursor", fell_back=False), book, probe) is None
    locked = ChatFallback(active="cursor", fell_back=True, promoted_at=clock.now - PROMOTION_LOCK_SECONDS + 5)
    assert _promote(chain, locked, book, probe) is None
    book.mark_failed("claude", Failure(KIND_LIMIT, int(clock.now) + 900))
    assert _promote(chain, fell, book, probe) is None


def test_after_reset_promotes_once_the_reset_passed() -> None:
    clock = Clock()
    book = FallbackBook(clock)

    async def probe(agent):
        return None

    book.mark_failed("claude", Failure(KIND_LIMIT, int(clock.now) + 900))
    fell = ChatFallback(active="cursor", preferred="claude", fell_back=True)
    assert _promote(["claude", "cursor"], fell, book, probe, mode=RETURN_AFTER_RESET) is None
    clock.now += 900
    assert _promote(["claude", "cursor"], fell, book, probe, mode=RETURN_AFTER_RESET) == "claude"
    assert "claude" not in book.health


def test_promotion_skips_agents_that_cannot_do_the_task() -> None:
    book = FallbackBook(Clock())

    async def probe(agent):
        return None

    fell = ChatFallback(active="cursor", preferred="openai", fell_back=True)
    chain = ["openai", "claude", "cursor"]
    assert _promote(chain, fell, book, probe, needs={CAP_CHAT, CAP_WORKSPACE}) == "claude"


# --- Pause and resume -------------------------------------------------------------------------


def test_pause_waits_for_the_first_agent_that_comes_back() -> None:
    clock = Clock()
    book = FallbackBook(clock)
    book.mark_failed("claude", Failure(KIND_LIMIT, int(clock.now) + 3600))
    book.mark_failed("cursor", Failure(KIND_CONNECTION))
    naps: list[float] = []
    asked: list[str] = []

    async def sleep(seconds):
        naps.append(seconds)
        clock.now += seconds

    async def probe(agent):
        asked.append(agent)
        # Cursor is still down at its first check, fine at the second one.
        return Failure(KIND_CONNECTION) if asked.count("cursor") == 1 else None

    found = asyncio.run(
        wait_for_agent(
            ["claude", "cursor", "openai"],
            needs={CAP_CHAT, CAP_WORKSPACE},
            caps_of=caps,
            book=book,
            probe=probe,
            sleep=sleep,
        )
    )
    assert found == "cursor"
    # Never probed before its wait was over; openai cannot do a workspace job and is never asked.
    assert asked == ["cursor", "cursor"]
    assert naps[0] == 300 and "cursor" not in book.health


def test_pause_without_any_capable_agent_or_after_a_day_gives_none() -> None:
    clock = Clock()
    book = FallbackBook(clock)

    async def sleep(seconds):
        clock.now += seconds

    async def probe(agent):
        return Failure(KIND_OVERLOADED)

    none = asyncio.run(
        wait_for_agent(["openai"], needs={CAP_CHAT, CAP_WORKSPACE}, caps_of=caps, book=book, probe=probe, sleep=sleep)
    )
    assert none is None
    gave_up = asyncio.run(
        wait_for_agent(["claude"], needs={CAP_CHAT}, caps_of=caps, book=book, probe=probe, sleep=sleep, give_up=7200)
    )
    assert gave_up is None and clock.now >= 1_000_000 + 7200


# --- Journal and handoff ----------------------------------------------------------------------


def test_journal_and_handoff_prompt() -> None:
    journal = TurnJournal()
    journal.note({"type": "tool", "name": "HassTurnOn", "phase": "start", "text": "Calling HassTurnOn...", "id": "1",
                  "detail": {"name": "Kitchen light"}}, "Claude")
    journal.note({"type": "tool", "name": "tool", "phase": "end", "text": "Finished", "id": "1", "detail": "ok"}, "Claude")
    journal.note({"type": "tool", "name": "Bash", "phase": "start", "text": "Calling Bash...", "id": "2",
                  "detail": {"command": "git push"}}, "Claude")
    journal.note({"type": "tool", "name": "GetLiveContext", "phase": "end", "text": "Finished GetLiveContext",
                  "note": "3 lights on"}, "Claude")
    assert journal.needs_workspace()
    prompt = handoff_prompt(
        "Turn on the kitchen light and push the config",
        journal,
        failed_agent="Claude",
        reason=KIND_LIMIT,
        partial="I turned on the light.",
    )
    assert "Original task from the user:\n<<<\nTurn on the kitchen light and push the config\n>>>" in prompt
    assert "Claude hit its plan or rate limit" in prompt
    assert "1. [Claude] HassTurnOn [changes something] — done" in prompt
    assert 'call: {"name": "Kitchen light"}' in prompt and "result: ok" in prompt
    assert "2. [Claude] Bash [changes something] — STARTED, RESULT UNKNOWN" in prompt
    assert "3. [Claude] GetLiveContext — done" in prompt and "3 lights on" in prompt
    assert "Do NOT repeat side-effecting steps" in prompt
    assert "git commits, pushes" in prompt
    assert "I turned on the light." in prompt


def test_empty_journal_says_so() -> None:
    prompt = handoff_prompt("Hi", TurnJournal(), failed_agent="Cursor", reason=KIND_CONNECTION)
    assert "(no tool calls yet)" in prompt and "could not be reached" in prompt
    assert not TurnJournal().needs_workspace()


def test_side_effect_guess() -> None:
    assert has_side_effect("HassTurnOn") and has_side_effect("Write") and has_side_effect("ha_call_service")
    assert not has_side_effect("Read") and not has_side_effect("GetLiveContext") and not has_side_effect("ha_get_state")


# --- Settings form ----------------------------------------------------------------------------


def test_fallback_section_and_last_used_choice() -> None:
    config_flow = pytest.importorskip("custom_components.ai_workspace.config_flow")
    from custom_components.ai_workspace.agents import agent_from_mapping
    from custom_components.ai_workspace.const import (
        CONF_DEFAULT_AGENT,
        CONF_FALLBACK_AGENTS,
        CONF_FALLBACK_ENABLED,
        CONF_FALLBACK_RETURN,
    )

    agents = [
        agent_from_mapping("a1", "Claude", {"api_provider": "claude"}),
        agent_from_mapping("a2", "Cursor", {"api_provider": "cursor"}),
        agent_from_mapping("a3", "OpenAI", {"api_provider": "openai"}),
    ]
    # Defaults: off, the Default agent first, then the others.
    schema = config_flow._fallback_schema({CONF_DEFAULT_AGENT: "a2"}, agents)
    values = schema({})
    assert values == {CONF_FALLBACK_ENABLED: False, CONF_FALLBACK_AGENTS: ["a2", "a1", "a3"], CONF_FALLBACK_RETURN: "new_message"}
    keys = {getattr(key, "schema", key): key for key in schema.schema}
    agents_selector = schema.schema[keys[CONF_FALLBACK_AGENTS]]
    assert agents_selector.config["multiple"] is True
    # Home Assistant serializes the form: the selector must be one it accepts.
    assert agents_selector.serialize()["selector"]["select"]["multiple"] is True
    # A saved order wins; agents that are gone drop out.
    saved = config_flow._fallback_schema({CONF_FALLBACK_AGENTS: ["a3", "gone", "a1"], CONF_FALLBACK_ENABLED: True}, agents)
    assert saved({})[CONF_FALLBACK_AGENTS] == ["a3", "a1"]

    # "Last used" is a translated choice in the form and still stored as "".
    field = config_flow._default_agent_field({}, agents)
    selector = next(iter(field.values()))
    assert selector.config["translation_key"] == "default_agent"
    assert selector.config["options"][0]["value"] == config_flow.LAST_USED
    flat = config_flow._normalize(
        config_flow._flatten(
            {"chat": {CONF_DEFAULT_AGENT: "last_used"}, "fallback": {CONF_FALLBACK_ENABLED: True, CONF_FALLBACK_AGENTS: ["a2", "a2", "a1"]}}
        )
    )
    assert flat[CONF_DEFAULT_AGENT] == "" and flat[CONF_FALLBACK_AGENTS] == ["a2", "a1"] and flat[CONF_FALLBACK_ENABLED]
    assert {CONF_FALLBACK_ENABLED, CONF_FALLBACK_AGENTS, CONF_FALLBACK_RETURN} <= set(config_flow._SHARED_KEYS)


def test_translations_name_the_fallback_section_in_every_language() -> None:
    import json
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "translations"
    de = json.loads((base / "de.json").read_text(encoding="utf-8"))
    section = de["options"]["step"]["init"]["sections"]["fallback"]
    assert section["data"]["fallback_enabled"] == "Fallback aktivieren"
    assert section["data"]["fallback_return"] == "Zurück zum bevorzugten Agent"
    assert de["selector"]["default_agent"]["options"]["last_used"] == "Zuletzt verwendet"
    for path in base.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert set(doc["selector"]["fallback_return"]["options"]) == {"off", "new_message", "after_reset"}
