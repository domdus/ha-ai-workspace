"""Chat titles: a short label from the first message, later maybe a model-written one.

The first title is set right away from the user's first message (no model call). It is never
the message cut at 80 characters: links become the page's name (a pasted article keeps its
topic, "Heise: DGX Spark Nvidias Desktop KI Computer"), and long text is cut to its first
sentence and a few words. When the message needed shortening and the turn allows extras, an
agent may write a real title afterwards; it replaces only this first, automatic title.

This file exists twice (add-on and integration) and both copies stay identical.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

_PROMPT = """Write a short sidebar title for this chat from the user's first message only.

Rules:
- 2 to 6 words
- Same language as the user's own words (not the language of a linked page)
- Summarize the topic; do not copy or truncate the message
- Never return a URL; for a link, name the site and the topic (for example: Heise Artikel über Nvidia DGX Spark)
- If the message is already a short label, return that label cleaned
- Do not use the words Home Assistant, MCP, assistance, assistant, chat, or help
- Plain text only: no quotes, markdown, asterisks, or trailing punctuation

User:
{user}
"""

_GENERIC = re.compile(
    r"\b(home assistant|mcp|assistance|assistent|assistant|new chat|chat title|hilfe beim)\b",
    re.I,
)
_PLACEHOLDERS = {"", "New Chat", "New chat", "Neuer Chat"}

# The first title: at most this many words and characters, cut at a word.
TITLE_WORDS = 6
TITLE_CHARS = 48

_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'()\[\]]+", re.I)
_SENTENCE_END = re.compile(r"(?<=[^\s.?!])[.?!]+(?=\s|$)")
# Path parts that name no topic.
_PATH_NOISE = re.compile(
    r"^(?:index|default|home|start|amp|seite|page|p|s|de|en|www|html?|php|aspx?|"
    r"tests?|news|artikel|article|articles|blog|post|posts|watch|wiki|meldung|ct|"
    r"\d+|[0-9a-f]{8,}|[a-z]?\d[\w]*\d)$",
    re.I,
)
_TLD_NOISE = {"www", "m", "amp", "mobile", "de", "com", "org", "net", "io", "co", "uk", "at", "ch", "eu"}
_SITE_NAMES = {"youtube": "YouTube", "youtu": "YouTube", "github": "GitHub", "reddit": "Reddit"}
# A title does not end on these.
_TAIL = {
    "a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to", "with", "about", "from", "is",
    "am", "an", "auf", "aus", "bei", "beim", "das", "dem", "den", "der", "des", "die", "ein", "eine",
    "einen", "einer", "für", "im", "in", "ist", "mit", "oder", "und", "vom", "von", "zu", "zum", "zur",
    "über", "etc", "usw", "ob", "wie", "was", "dass", "alle", "haben", "hat",
}


def title_prompt(user: str, assistant: str = "") -> str:
    del assistant
    return _PROMPT.format(user=(user or "").strip()[:800])


def clean_title(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    text = re.sub(r"^(title|chat title|titel)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"[*_`#]+", "", text)
    text = text.strip(" \t\"'`“”‘’„")
    text = re.sub(r"\s+", " ", text).strip(" .-")
    text = text.rstrip("?!.,;:")
    return text[:80]


def _flat(user: str) -> str:
    return re.sub(r"\s+", " ", (user or "").replace("\n", " ")).strip()


def _site(host: str) -> str:
    parts = [p for p in host.lower().split(".") if p]
    while len(parts) > 1 and parts[0] in _TLD_NOISE:
        parts.pop(0)
    while len(parts) > 1 and parts[-1] in _TLD_NOISE:
        parts.pop()
    name = parts[-1] if parts else ""
    if not name:
        return ""
    if name in _SITE_NAMES:
        return _SITE_NAMES[name]
    return " ".join(w[:1].upper() + w[1:] for w in name.split("-") if w)


def link_topic(url: str, min_words: int = 2) -> str:
    """A link as "Site: words from its path", or just the site when the path names nothing."""
    raw = url if "://" in url else f"https://{url}"
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    site = _site(parts.hostname or "")
    best: list[str] = []
    for segment in unquote(parts.path or "").split("/"):
        segment = re.sub(r"\.(?:s?html?|php|aspx?|jsp)$", "", segment, flags=re.I)
        words = [w for w in re.split(r"[-_+.,\s]+", segment) if w and not _PATH_NOISE.match(w)]
        # The most telling part of the path is the slug with the most words.
        if len(words) >= len(best):
            best = words
    if len(best) < max(1, min_words):
        return site
    topic = " ".join(best)
    return f"{site}: {topic}" if site else topic


def _first_sentence(text: str) -> str:
    match = _SENTENCE_END.search(text)
    return text[: match.start()] if match else text


def shorten_title(text: str, words: int = TITLE_WORDS, chars: int = TITLE_CHARS) -> str:
    """At most ``words`` words and ``chars`` characters, cut at a word, no dangling little word."""
    tokens = clean_title(text).split(" ")
    out: list[str] = []
    for token in tokens:
        if not token:
            continue
        if len(out) >= words or len(" ".join([*out, token])) > chars:
            break
        out.append(token)
    if not out and tokens and tokens[0]:
        out = [tokens[0][:chars]]
    while len(out) > 1 and out[-1].strip(",;:-").casefold() in _TAIL:
        out.pop()
    return " ".join(out).strip(" ,;:-")


def title_from_prompt(user: str) -> str:
    """The first title, set right away: short, never a URL."""
    flat = _flat(user)
    if not flat:
        return ""
    links = _URL.findall(flat)
    rest = _flat(_URL.sub(" ", flat))
    rest = clean_title(_first_sentence(rest)) if rest else ""
    links = [link.rstrip(".,;:!?") for link in links]
    for link in links:
        topic = link_topic(link)
        if ":" in topic:
            return shorten_title(topic, words=TITLE_WORDS + 1)
    if rest:
        return shorten_title(rest)
    if links:
        return shorten_title(link_topic(links[0], min_words=1) or "Link", words=TITLE_WORDS + 1)
    return shorten_title(flat)


def needs_title_summary(user: str) -> bool:
    """True when the first title had to shorten the message, so a written title would help."""
    flat = _flat(user)
    if not flat:
        return False
    if _URL.search(flat):
        return True
    return title_from_prompt(user) != clean_title(flat)


def accept_generated_title(user: str, title: str) -> str:
    label = clean_title(title)
    if not label or _GENERIC.search(label) or _URL.search(label) or "://" in label:
        return ""
    source = clean_title(_flat(user))
    if source.startswith(label) and len(source) > len(label) + 6:
        return ""
    return label


def is_placeholder_title(title: str, first_user: str = "") -> bool:
    """Still the automatic title: "New chat", the first title, or the message cut short (older chats)."""
    current = (title or "").strip()
    if current in _PLACEHOLDERS:
        return True
    flat = _flat(first_user)
    if not flat or not current:
        return False
    if current == title_from_prompt(first_user):
        return True
    cleaned = clean_title(current)
    source = clean_title(flat)
    # Older versions stored the message itself, cut at 80 characters.
    return current == flat[:80] or bool(cleaned) and (source.startswith(cleaned) or flat.startswith(current))
