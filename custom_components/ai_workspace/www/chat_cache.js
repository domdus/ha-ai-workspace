// Last chat kept in this browser, so it paints at once before the server answers.
// Pure helpers (no DOM), tested in tests/test_chat_cache.mjs.

export const CHAT_CACHE_BASE = "ai_workspace_last_chat";
export const CHAT_CACHE_TAIL = 24;
export const CHAT_CACHE_MAX_BYTES = 200 * 1024;
const TEXT_CAP = 20000;
// Event fields that can be large (image data, excerpts) or are not needed to paint a bubble.
const HEAVY_FIELDS = new Set(["data", "text_full", "content", "base64", "image", "result"]);

// Waits and limits while a chat loads.
export const SKELETON_DELAY_MS = 150;
export const SLOW_HINT_MS = 8000;
export const LOAD_TIMEOUT_MS = 20000;

/** Per-user key: a shared tablet must not show one user's chat to the next. */
export function chatCacheKey(userId) {
  const id = String(userId || "").trim();
  return id ? `${CHAT_CACHE_BASE}:${id}` : "";
}

function trimEvent(event) {
  if (!event || typeof event !== "object") return null;
  if (event.type === "cross_chat") return { type: "cross_chat", chats: event.chats || [] };
  // Pictures are not kept (too big); the server's answer paints them.
  if (event.type === "image") return { type: "image", name: event.name || "", dropped: true };
  const out = {};
  for (const [key, value] of Object.entries(event)) {
    if (HEAVY_FIELDS.has(key)) continue;
    if (typeof value === "string" && value.length > 2000) out[key] = value.slice(0, 2000);
    else out[key] = value;
  }
  return out;
}

function trimMessage(message) {
  const content = String(message?.content || "");
  return {
    id: message?.id,
    role: message?.role,
    content: content.length > TEXT_CAP ? content.slice(0, TEXT_CAP) : content,
    events: (Array.isArray(message?.events) ? message.events : []).map(trimEvent).filter(Boolean),
    created_at: message?.created_at,
  };
}

/** What is kept: the chat's head fields and its newest messages, small enough for localStorage. */
export function trimChatForCache(session, { tail = CHAT_CACHE_TAIL, maxBytes = CHAT_CACHE_MAX_BYTES } = {}) {
  if (!session || !session.id) return null;
  let messages = (session.messages || []).slice(-tail).map(trimMessage);
  const head = {
    id: session.id,
    title: session.title || "",
    provider: session.provider || "",
    model: session.model || "",
    pinned: Boolean(session.pinned),
    has_activity: Boolean(session.has_activity),
    updated_at: session.updated_at || "",
    cached_at: Date.now(),
  };
  while (messages.length) {
    const body = JSON.stringify({ ...head, messages });
    if (body.length <= maxBytes) return { ...head, messages };
    messages = messages.slice(1);
  }
  return null;
}

/** A fingerprint of what the chat shows: same fingerprint, no repaint. */
export function chatSignature(session) {
  const messages = session?.messages || [];
  const last = messages[messages.length - 1];
  return JSON.stringify([
    session?.title || "",
    messages.length ? messages.slice(-CHAT_CACHE_TAIL).map((m) => m.id).join(",") : "",
    last ? String(last.content || "").length : 0,
    last ? String(last.content || "").slice(-80) : "",
  ]);
}

/**
 * Does the fresh chat end exactly like the cached one? Then only older messages may be missing
 * on screen (see olderCount), and nothing has to be painted again.
 */
export function sameChat(cached, fresh) {
  if (!cached || !fresh || cached.id !== fresh.id) return false;
  const dropped = (cached.messages || []).some((m) => (m.events || []).some((e) => e && e.dropped));
  if (dropped) return false;
  const shown = (cached.messages || []).length;
  const all = fresh.messages || [];
  if (all.length < shown || (!shown && all.length)) return false;
  const tail = { ...fresh, messages: all.slice(all.length - shown) };
  return chatSignature(cached) === chatSignature(tail);
}

/** How many older messages the fresh chat has before the cached tail. */
export function olderCount(cached, fresh) {
  return Math.max(0, (fresh?.messages || []).length - (cached?.messages || []).length);
}

export function readChatCache(storage, key, id) {
  if (!storage || !key || !id) return null;
  try {
    const row = JSON.parse(storage.getItem(key) || "null");
    return row && row.id === id && Array.isArray(row.messages) ? row : null;
  } catch (_err) {
    return null;
  }
}

/** Never throws: a full storage (QuotaExceededError) or private mode only means no cache. */
export function writeChatCache(storage, key, session) {
  if (!storage || !key) return false;
  const row = trimChatForCache(session);
  try {
    if (!row) {
      storage.removeItem(key);
      return false;
    }
    storage.setItem(key, JSON.stringify(row));
    return true;
  } catch (_err) {
    try {
      storage.removeItem(key);
    } catch (_ignored) {
      /* storage gone */
    }
    return false;
  }
}

/** Drop the cached chat (deleted chat), and caches of other users (user changed on this device). */
export function clearChatCache(storage, key, { id = "", keepKey = "" } = {}) {
  if (!storage) return;
  try {
    if (key && id) {
      const row = readChatCache(storage, key, id);
      if (row) storage.removeItem(key);
    } else if (key && !keepKey) {
      storage.removeItem(key);
    }
    if (keepKey) {
      const drop = [];
      for (let i = 0; i < storage.length; i += 1) {
        const name = storage.key(i);
        if (name && name.startsWith(`${CHAT_CACHE_BASE}:`) && name !== keepKey) drop.push(name);
      }
      for (const name of drop) storage.removeItem(name);
    }
  } catch (_err) {
    /* storage gone */
  }
}

/** 404 means the chat is gone; anything else that failed may work on a retry. */
export function loadOutcome(response, timedOut = false) {
  if (timedOut) return "error";
  if (!response) return "error";
  if (response.ok) return "ok";
  if (response.status === 404) return "gone";
  return "error";
}

/** Is any listed chat unread? The chat open and visible on this screen does not count. */
export function anyUnread(sessions, openId = "", visible = true) {
  return (sessions || []).some((session) => session && session.unread && !(visible && session.id === openId));
}

/** An AbortSignal that fires after ``ms`` or when ``outer`` fires. */
export function timeoutSignal(ms, outer) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("Timed out", "TimeoutError")), ms);
  if (outer) {
    if (outer.aborted) controller.abort(outer.reason);
    else outer.addEventListener("abort", () => controller.abort(outer.reason), { once: true });
  }
  return { signal: controller.signal, done: () => clearTimeout(timer) };
}
