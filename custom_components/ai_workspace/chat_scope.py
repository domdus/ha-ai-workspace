from __future__ import annotations

import logging
import math
import re
import unicodedata
from difflib import SequenceMatcher

from .const import (
    CROSS_CHAT_BUDGET,
    CROSS_CHAT_MESSAGE_CAP,
    CROSS_CHAT_MIN_SCORE,
    CROSS_CHAT_REPLY_CAP,
    CROSS_CHAT_SUMMARY_CHARS,
    TOKEN_MODE_OFF,
)
from .context import DIGEST_LEAD, Turn, _events, _failed_reply, as_transcript, digest, history_for

logger = logging.getLogger(__name__)

# Words that say the user means another chat. Compounds ending in one of the suffixes count too
# ("Bewässerungschat", "Bewässerungs-Chat", "Börsenverlauf").
_CUE_WORDS = frozenset(
    {
        "chat",
        "chats",
        "conversation",
        "conversations",
        "unterhaltung",
        "unterhaltungen",
        "gespraech",
        "gespraeche",
        "frueher",
        "vorher",
        "verlauf",
        "thread",
        "threads",
        "talk",
    }
)
_CUE_SUFFIXES = ("chats", "chat", "verlauf", "thread", "unterhaltung", "gespraech")
_WEAK_CUES = frozenset({"verlauf"})
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "æ": "ae", "ø": "oe", "œ": "oe"})
_STOP = frozenset(
    {
        "about",
        "aber",
        "alle",
        "alles",
        "also",
        "another",
        "auch",
        "auf",
        "aus",
        "bitte",
        "chat",
        "chats",
        "conversation",
        "conversations",
        "damit",
        "dann",
        "dar",
        "daraus",
        "darin",
        "darueber",
        "dass",
        "davon",
        "dazu",
        "dem",
        "den",
        "der",
        "des",
        "die",
        "dies",
        "diese",
        "diesem",
        "diesen",
        "dieser",
        "dort",
        "eine",
        "einem",
        "einen",
        "einer",
        "eines",
        "erstell",
        "erstelle",
        "from",
        "fuer",
        "gemacht",
        "gesagt",
        "gespraech",
        "gespraeche",
        "geht",
        "gib",
        "gibt",
        "haben",
        "hast",
        "hatten",
        "have",
        "hier",
        "just",
        "kann",
        "kannst",
        "know",
        "last",
        "letzte",
        "letzten",
        "letzter",
        "like",
        "list",
        "liste",
        "mach",
        "mache",
        "machen",
        "make",
        "mal",
        "mehr",
        "mein",
        "meine",
        "meinem",
        "mit",
        "nach",
        "neue",
        "neuen",
        "neuer",
        "neues",
        "new",
        "nicht",
        "noch",
        "nochmal",
        "other",
        "please",
        "schau",
        "schaue",
        "schreib",
        "sein",
        "show",
        "sind",
        "table",
        "tabelle",
        "tabellen",
        "that",
        "the",
        "them",
        "there",
        "this",
        "ueber",
        "und",
        "uns",
        "unser",
        "unsere",
        "unserem",
        "unseren",
        "unterhaltung",
        "verlauf",
        "vom",
        "von",
        "vorher",
        "frueher",
        "war",
        "waren",
        "was",
        "what",
        "when",
        "where",
        "wie",
        "wir",
        "wissen",
        "with",
        "wurde",
        "your",
        "zeig",
        "zeige",
        "zum",
        "zur",
        "thread",
        "talk",
    }
)
# Little words allowed between a title word and "chat" ("im Chat über Bewässerung").
_FILLER = frozenset({"im", "in", "dem", "der", "den", "zum", "zur", "zu", "ueber", "about", "on", "the", "our", "my", "unserem", "meinem"})
_NEIGHBOR = re.compile(
    r"\b(?:anderen|andere|vorigen|vorherigen|letzten|alten|previous|last|other|earlier)\s+"
    r"(?:chat|unterhaltung|gespraech|conversation|thread)\b"
)
_PLACEHOLDERS = frozenset({"", "new chat", "neuer chat"})
_FUZZY = 0.85
_COMPOUND_MIN = 5
CROSS_MARK = "=== Read-only excerpt from another chat ==="
CROSS_EVENT = "cross_chat"
_HANDOFF_BUDGET = 100000
HANDOFF_LEAD = (
    "This is the same Home Assistant chat. AI Workspace already shows these turns; "
    "the transcript below is the source of truth. Continue from it. "
    "Do not greet as if this is a new chat, do not say the chat was empty, "
    "and do not ask the user to paste earlier messages. "
    "If they ask what you talked about, summarize this transcript. "
    "If the user says to go ahead, do the last thing you offered."
)
_HANDOFF_LEAD = HANDOFF_LEAD


def fold(text: str) -> str:
    """Lowercase, umlauts as ae/oe/ue/ss, other accents dropped."""
    lowered = str(text or "").casefold().translate(_FOLD)
    return "".join(ch for ch in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(ch))


def stem(word: str) -> str:
    """Strip a German plural or joint ending (-en, -s, -e, -n) while a usable word is left."""
    for ending in ("en", "s", "e", "n"):
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


_STOP_STEMS = frozenset(stem(word) for word in _STOP)


def _split_cue(token: str) -> tuple[str, str]:
    """'bewaesserungschat' -> ('bewaesserungs', 'chat'). The cue is 'chat', 'verlauf' (weak) or ''."""
    if token in _CUE_WORDS:
        return "", _cue_kind(token)
    for suffix in _CUE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)], _cue_kind(suffix)
    return token, ""


def _cue_kind(word: str) -> str:
    # "Verlauf" is also an entity's history in Home Assistant, so alone it is only a weak hint.
    return "verlauf" if word in _WEAK_CUES else "chat"


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Folded words in order, each with a flag that it is (or ends in) a chat cue.

    A compound like "bewaesserungschat" gives the word part and then a cue.
    """
    found: list[tuple[str, bool]] = []
    for raw in _TOKEN.findall(fold(text)):
        word, cue = _split_cue(raw)
        if word:
            found.append((word, False))
        if cue:
            found.append((cue, True))
    return found


def mentions_chat(message: str) -> bool:
    return any(cue for _, cue in _tokens(message))


def _names_chat(message: str) -> bool:
    """A real chat word ("chat", "Unterhaltung", "thread"), not only "Verlauf"."""
    return any(cue and word == "chat" for word, cue in _tokens(message))


def _content_words(text: str) -> list[str]:
    kept = []
    for word, cue in _tokens(text):
        if cue or len(word) < 4 or word.isdigit() or word in _STOP:
            continue
        stemmed = stem(word)
        if stemmed not in _STOP_STEMS:
            kept.append(stemmed)
    return kept


def _same(asked: str, title_word: str) -> float:
    """1.0 for the same word, a bit less for a typo or a compound, 0 for no match."""
    if asked == title_word:
        return 1.0
    if len(asked) >= _COMPOUND_MIN and len(title_word) >= _COMPOUND_MIN:
        if SequenceMatcher(None, asked, title_word).ratio() >= _FUZZY:
            return 0.95
    if len(title_word) >= _COMPOUND_MIN and len(asked) > len(title_word):
        # Compounds: "gartenbewaesserung", "bewaesserungsplan".
        if asked.startswith(title_word) or asked.endswith(title_word):
            return 0.9
    return 0.0


def _best(asked: list[str], title_word: str) -> float:
    return max((_same(word, title_word) for word in asked), default=0.0)


def _title_words(title: str) -> list[str]:
    words = _content_words(title)
    if words:
        return words
    # A title of only common words ("Neue Tabelle") still matches by those words.
    return [stem(word) for word, cue in _tokens(title) if not cue and len(word) >= 3]


def _weights(chats: list[dict]) -> dict[str, float]:
    """Rarer title words weigh more: a word in every title says little about which chat is meant."""
    counts: dict[str, int] = {}
    for chat in chats:
        for word in set(_title_words(str(chat.get("title") or ""))):
            counts[word] = counts.get(word, 0) + 1
    total = max(1, len(chats))
    return {word: 1.0 + math.log(total / count) for word, count in counts.items()}


def _near_cue(tokens: list[tuple[str, bool]]) -> list[str]:
    """Stemmed words right before or after a chat cue, skipping little words like "im" or "über"."""
    near: list[str] = []
    for index, (_, cue) in enumerate(tokens):
        if not cue:
            continue
        for step in (-1, 1):
            pos = index + step
            skipped = 0
            while 0 <= pos < len(tokens) and tokens[pos][0] in _FILLER and skipped < 2:
                pos += step
                skipped += 1
            if 0 <= pos < len(tokens) and not tokens[pos][1]:
                near.append(stem(tokens[pos][0]))
    return near


def score_title(message: str, title: str, weights: dict[str, float] | None = None) -> float:
    """How surely the message means the chat with this title. 0 when it does not.

    Whole title in the message (100+) > a title word right next to "chat" (60-80) >
    weighted share of shared words (up to 50).
    """
    words = _title_words(title)
    if not words:
        return 0.0
    tokens = _tokens(message)
    asked = [stem(word) for word, cue in tokens if not cue and len(word) >= 3]
    if not asked:
        return 0.0
    hits = [_best(asked, word) for word in words]
    if all(hits):
        # Whole title, in any spelling. Exact spellings and longer titles first.
        return 100.0 + min(len(words), 5) + 2 * (sum(hits) / len(hits) - 1)
    weights = weights or {}
    total = sum(weights.get(word, 1.0) for word in words)
    shared = sum(weights.get(word, 1.0) * hit for word, hit in zip(words, hits))
    share = shared / total if total else 0.0
    near = _near_cue(tokens)
    if near and any(_best(near, word) for word in words):
        return 60.0 + 20.0 * share
    return 50.0 * share


def matching_chats(message: str, chats: list[dict], current_id: str, cross: bool = False) -> list[dict]:
    """The other chat this message means: the best title, a second only when it is nearly as good.

    Without Cross chat, the message also has to mention a chat. Pinned and recent chats win
    only a tie (``chats`` comes pinned first, then newest first).
    """
    if not cross and not mentions_chat(message):
        return []
    # Only "Verlauf": the whole title has to be in the message.
    least = CROSS_CHAT_MIN_SCORE if cross or _names_chat(message) else 100.0
    candidates = []
    for chat in chats:
        if str(chat.get("id") or "") == current_id:
            continue
        title = str(chat.get("title") or "").strip()
        if title.casefold() in _PLACEHOLDERS:
            continue
        candidates.append(chat)
    if not candidates:
        return []
    weights = _weights(candidates)
    scored = []
    for order, chat in enumerate(candidates):
        value = score_title(message, str(chat.get("title") or ""), weights)
        if value >= least:
            scored.append((value, order, chat))
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], item[1]))
    best = scored[0]
    picked = [best[2]]
    if len(scored) > 1 and scored[1][0] >= best[0] - 2:
        picked.append(scored[1][2])
    return picked


def neighbor_chat(message: str, chats: list[dict], current_id: str) -> dict | None:
    """'im anderen/vorigen/letzten Chat' without a title: the most recently updated other chat."""
    if not _NEIGHBOR.search(fold(message)):
        return None
    others = [
        chat
        for chat in chats
        if str(chat.get("id") or "") != current_id
        and str(chat.get("title") or "").strip().casefold() not in _PLACEHOLDERS
    ]
    if not others:
        return None
    return max(others, key=lambda chat: str(chat.get("updated_at") or ""))


def split_cross_note(text: str) -> tuple[str, str]:
    """The message and the excerpt after it, so clipping a long message never cuts the excerpt."""
    raw = str(text or "")
    at = raw.find(f"\n\n{CROSS_MARK}")
    if at < 0:
        return raw, ""
    return raw[:at], raw[at + 2 :]


def clip_keeping_excerpt(text: str, limit: int, clip=None) -> str:
    body, note = split_cross_note(text)
    if clip is None:
        body = body[:limit]
    else:
        body = clip(body, limit)
    return f"{body}\n\n{note}" if note else body


def _lines_upto(text: str, limit: int) -> tuple[str, bool]:
    """The start of a text up to ``limit`` characters, cut only at a line end."""
    if len(text) <= limit:
        return text, False
    cut = text.rfind("\n", 0, limit + 1)
    if cut < limit // 3:
        # One long line: cut at a word instead.
        cut = text.rfind(" ", 0, limit + 1)
    if cut <= 0:
        cut = limit
    return text[:cut].rstrip(), True


def _chat_turns(rows) -> list[Turn]:
    turns = []
    for row in rows or []:
        if isinstance(row, (tuple, list)):
            role, content = str(row[0] or ""), str(row[1] or "")
            events: list = []
        else:
            role = str(getattr(row, "role", "") or "")
            content = str(getattr(row, "content", "") or "")
            events = _events(row)
        content = content.strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if _failed_reply(role, content, events):
            continue
        turns.append(Turn(role, content, "", None))
    return turns


def chat_excerpt(
    title: str,
    rows,
    *,
    budget: int = CROSS_CHAT_BUDGET,
    reply_cap: int = CROSS_CHAT_REPLY_CAP,
    message_cap: int = CROSS_CHAT_MESSAGE_CAP,
    last_n: int = 0,
    chat_id: str = "",
    updated_at: str = "",
) -> str:
    """Newest messages first into the budget, shown oldest to newest, plus a summary of the rest.

    Line breaks stay, so tables and code arrive intact; long messages are cut at a line end.
    """
    turns = _chat_turns(rows)
    if not turns:
        return ""
    name = " ".join(str(title or "").split())[:80] or "Untitled"
    head = f'{CROSS_MARK}\nRead-only excerpt from the chat "{name}"'
    facts = [f"{len(turns)} message(s)"]
    if updated_at:
        facts.append(f"last updated {str(updated_at)[:16].replace('T', ' ')} UTC")
    if chat_id:
        facts.append(f"id {chat_id}")
    head = (
        f"{head} ({', '.join(facts)}). Use it only to answer this question. Do not change that chat. "
        "Use read_chat for more of it."
    )
    room = max(400, int(budget) - len(head) - 2)
    summary_room = min(CROSS_CHAT_SUMMARY_CHARS, room // 6)
    room -= summary_room
    kept: list[str] = []
    newest_reply = True
    used = 0
    pool = turns[-last_n:] if last_n and last_n > 0 else turns
    taken = 0
    for turn in reversed(pool):
        label = "User" if turn.role == "user" else "Assistant"
        cap = message_cap
        if turn.role == "assistant" and newest_reply:
            cap = reply_cap
            newest_reply = False
        left = room - used - len(label) - 4
        if left < 200 and kept:
            break
        body, cut = _lines_upto(turn.text, max(200, min(cap, left)))
        if cut:
            body = f"{body}\n[gekürzt]"
        block = f"{label}: {body}"
        kept.append(block)
        used += len(block) + 2
        taken += 1
        if cut and len(turn.text) > left:
            break
    kept.reverse()
    older = turns[: len(turns) - taken]
    parts = [head]
    if older:
        summary = digest(older, summary_room) if summary_room > 80 else ""
        if summary:
            parts.append(summary.replace(DIGEST_LEAD, "Summary of the older messages in that chat:", 1))
        parts.append(f"[… {len(older)} ältere Nachrichten ausgelassen]")
    parts.extend(kept)
    return "\n\n".join(parts)


def excerpt_for(chats: list[dict], budget: int = CROSS_CHAT_BUDGET) -> str:
    """Excerpts of the picked chats, sharing one budget."""
    chats = [chat for chat in chats or [] if chat]
    if not chats:
        return ""
    share = max(1000, int(budget) // len(chats))
    blocks = []
    for chat in chats:
        text = chat_excerpt(
            str(chat.get("title") or ""),
            chat.get("messages") or [],
            budget=share,
            chat_id=str(chat.get("id") or ""),
            updated_at=str(chat.get("updated_at") or ""),
        )
        if text:
            blocks.append(text)
    return "\n\n".join(blocks)


_CACHE: dict[tuple, str] = {}
_CACHE_SIZE = 32


def _cached_excerpt(store, chat: dict, budget: int) -> str:
    key = (str(chat["id"]), str(chat.get("updated_at") or ""), int(budget))
    if key in _CACHE:
        return _CACHE[key]
    rows = store.list_messages(chat["id"])
    text = excerpt_for([{**chat, "messages": rows}], budget)
    if len(_CACHE) >= _CACHE_SIZE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = text
    return text


def _catalog(store, user_id: str) -> list[dict]:
    return [
        {
            "id": item.id,
            "title": item.title,
            "updated_at": item.updated_at,
            "pinned": bool(getattr(item, "pinned", False)),
        }
        for item in store.list_sessions(user_id)
    ]


def pick_other_chats(store, user_id: str, session_id: str, message: str, cross: bool = False) -> list[dict]:
    if not cross and not mentions_chat(message):
        # Most messages name no chat: no database read for them.
        return []
    catalog = _catalog(store, user_id)
    picked = matching_chats(message, catalog, session_id, cross=bool(cross))
    if picked:
        return picked
    near = neighbor_chat(message, catalog, session_id)
    return [near] if near else []


def other_chat_context(
    store, user_id: str, session_id: str, message: str, cross: bool = False, budget: int = CROSS_CHAT_BUDGET
) -> tuple[str, list[dict]]:
    """The excerpt for this message and the chats it came from ([] when none)."""
    picked = pick_other_chats(store, user_id, session_id, message, cross)
    if not picked:
        return "", []
    share = max(1000, int(budget) // len(picked))
    blocks = []
    used = []
    for chat in picked:
        text = _cached_excerpt(store, chat, share)
        if text:
            blocks.append(text)
            used.append({"id": chat["id"], "title": chat["title"]})
    note = "\n\n".join(blocks)
    if note:
        logger.info(
            "cross-chat excerpt session=%s chats=%s chars=%s",
            session_id,
            ", ".join(f"{item['title']!r}" for item in used),
            len(note),
        )
    return note, used


def other_chat_note(
    store, user_id: str, session_id: str, message: str, cross: bool = False, budget: int = CROSS_CHAT_BUDGET
) -> str:
    return other_chat_context(store, user_id, session_id, message, cross, budget)[0]


def cross_chat_event(note: str, chats: list[dict]) -> dict:
    """Kept with the user message, so a resumed or switched agent gets the same excerpt again."""
    return {"type": CROSS_EVENT, "chats": chats, "chars": len(note), "text": note}


def public_events(events: list) -> list:
    """Events for the browser: the excerpt text stays on the server."""
    shown = []
    for item in events or []:
        if isinstance(item, dict) and item.get("type") == CROSS_EVENT:
            shown.append({k: v for k, v in item.items() if k != "text"})
        else:
            shown.append(item)
    return shown


PRIOR_EXCERPT_LEAD = (
    "Earlier in this chat the user asked about another of their chats. "
    "This read-only excerpt was sent with that message:"
)


def prior_excerpt(rows) -> str:
    """The excerpt of an earlier turn, when the message being answered now brought none."""
    rows = list(rows or [])
    if rows and str(getattr(rows[-1], "role", "") or "") == "user":
        if last_excerpt(rows[-1:]):
            return ""
        rows = rows[:-1]
    return last_excerpt(rows)


def with_prior_excerpt(messages: list[dict], rows, message: str = "") -> list[dict]:
    """History for a cloud agent: the excerpt from an earlier turn goes with the first turn shown."""
    if CROSS_MARK in str(message or ""):
        return messages
    prior = prior_excerpt(rows)
    if not prior:
        return messages
    note = f"{PRIOR_EXCERPT_LEAD}\n{prior}"
    shown = list(messages)
    if shown and shown[0].get("role") == "user":
        shown[0] = {**shown[0], "content": f"{note}\n\n{shown[0]['content']}"}
    else:
        shown.insert(0, {"role": "user", "content": note})
    return shown


def last_excerpt(rows) -> str:
    """The excerpt sent with the latest earlier user message that had one."""
    for row in reversed(list(rows or [])):
        if str(getattr(row, "role", "") or "") != "user":
            continue
        for item in _events(row):
            if isinstance(item, dict) and item.get("type") == CROSS_EVENT and item.get("text"):
                return str(item["text"])
    return ""


def handoff_note(
    rows,
    title: str = "",
    *,
    mode: str = TOKEN_MODE_OFF,
    model: str = "",
    manual_window: int = 0,
    zone=None,
) -> str:
    """Prior turns from this HA chat, used only when Cursor may have lost the thread.

    Same budget and digest as cloud agents (context.py). Line breaks stay, so YAML and code survive.
    """
    history = history_for(rows, mode=mode, model=model, manual_window=manual_window, zone=zone)
    if not history:
        return ""
    name = " ".join(str(title or "").split())
    turns = (len(history.turns) + 1) // 2 + history.dropped // 2
    if name and name.casefold() not in _PLACEHOLDERS:
        lead = (
            f'This is the same Home Assistant chat titled "{name[:80]}". '
            f"AI Workspace already shows this conversation ({turns} prior turn(s)); "
            "the transcript below is the source of truth, including replies from other agents. "
            "Continue from it. Do not greet as if this is a new chat, do not say the chat was empty, "
            "and do not ask the user to paste earlier messages. "
            "If they ask what you talked about, summarize this transcript. "
            "If the user says to go ahead, do the last thing you offered."
        )
    else:
        lead = _HANDOFF_LEAD
    transcript = as_transcript(history)
    prior = prior_excerpt(rows)
    if prior:
        transcript = f"{transcript}\n\n{PRIOR_EXCERPT_LEAD}\n{prior}"
    return _fit_handoff(lead, transcript)


def _fit_handoff(lead: str, transcript: str) -> str:
    note = f"{lead}\n\n{transcript}"
    if len(note) <= _HANDOFF_BUDGET:
        return note
    room = max(0, _HANDOFF_BUDGET - len(lead) - 2)
    # Cut at a line start, so the first kept table row or code line stays whole.
    tail = transcript[-room:]
    newline = tail.find("\n")
    if 0 <= newline < 2000:
        tail = tail[newline + 1 :]
    return f"{lead}\n\n{tail}"


def attach_handoff(message: str, rows, needed: bool = True, title: str = "") -> str:
    if not needed:
        return message
    note = handoff_note(rows, title)
    if not note:
        return message
    return f"{note}\n\n{message}"


def text_after_tools(earlier: list[str], delta: str) -> str:
    """First text after a tool call: Cursor's answer otherwise runs straight on from its opening sentence."""
    said = "".join(earlier)
    if not said.strip():
        return delta
    have = len(said) - len(said.rstrip("\n")) + len(delta) - len(delta.lstrip("\n"))
    return "\n" * max(0, 2 - have) + delta


_SENTENCE_END = (".", "!", "?", ":", "…", "。", "！", "？")


def text_after_pause(earlier: list[str], delta: str) -> str:
    """First text after a thinking step: a new message from the agent, not the rest of a word.

    Cursor sends its status sentence and the answer as two messages. Without a break they run
    together ("hängt.Die"). Only when the earlier text ended a sentence and the new one does
    not start with a space, so a word split around the pause stays whole.
    """
    said = "".join(earlier).rstrip(" ")
    if not said.strip() or not delta or delta[0].isspace() or not said.endswith(_SENTENCE_END):
        return delta
    return text_after_tools(earlier, delta)


def merge_reply_text(streamed: str, final: str | None) -> str:
    """Keep a spoken intro that arrived before tools when the result is only the later answer."""
    streamed = str(streamed or "").strip()
    final = str(final or "").strip()
    if not final:
        return streamed
    if not streamed:
        return final
    if streamed == final or streamed in final:
        return final
    # The chat puts a blank line between text from before and after tools.
    if "".join(streamed.split()) == "".join(final.split()):
        return streamed
    if final in streamed:
        return streamed
    overlap = 0
    for n in range(min(len(streamed), len(final)), 0, -1):
        if streamed.endswith(final[:n]):
            overlap = n
            break
    intro = streamed[: len(streamed) - overlap].strip() if overlap else streamed
    if intro and intro not in final:
        return f"{intro}\n\n{final}".strip()
    return final
