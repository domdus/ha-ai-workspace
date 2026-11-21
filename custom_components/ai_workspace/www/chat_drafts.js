// Per-chat composer drafts and per-chat queued prompts.
// Pure helpers (no DOM), tested in tests/test_chat_drafts.mjs.

export const DRAFT_BASE = "ai_workspace_drafts";
// The "new chat" screen has its own draft.
export const NEW_CHAT_DRAFT = "_new";
export const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000;
export const DRAFT_MAX_CHARS = 8000;
export const DRAFT_MAX_CHATS = 30;

/** Per-user key: a shared tablet must not show one user's drafts to the next. */
export function draftStoreKey(userId) {
  const id = String(userId || "").trim();
  return id ? `${DRAFT_BASE}:${id}` : "";
}

/** Draft slot of a chat; "" (new chat) has its own slot. */
export function draftSlot(sessionId) {
  return String(sessionId || "").trim() || NEW_CHAT_DRAFT;
}

function parse(raw) {
  try {
    const data = JSON.parse(raw || "{}");
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch (_err) {
    return {};
  }
}

/** All drafts still within the TTL: { slot: { text, at } }. */
export function readDrafts(storage, key, now = Date.now()) {
  if (!storage || !key) return {};
  let raw;
  try {
    raw = storage.getItem(key);
  } catch (_err) {
    return {};
  }
  const out = {};
  for (const [slot, item] of Object.entries(parse(raw))) {
    const text = typeof item?.text === "string" ? item.text : "";
    const at = Number(item?.at) || 0;
    if (!text.trim() || now - at > DRAFT_TTL_MS || at > now + DRAFT_TTL_MS) continue;
    out[slot] = { text, at };
  }
  return out;
}

function store(storage, key, drafts) {
  try {
    if (!Object.keys(drafts).length) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(drafts));
  } catch (_err) {
    /* storage full or blocked: the draft stays in memory only */
  }
}

/** Text of one chat's draft, "" when none. */
export function readDraft(storage, key, slot, now = Date.now()) {
  return readDrafts(storage, key, now)[slot]?.text || "";
}

/** Keep (or with blank text, remove) one chat's draft. Old and surplus drafts are dropped. */
export function writeDraft(storage, key, slot, text, now = Date.now()) {
  if (!storage || !key || !slot) return;
  const drafts = readDrafts(storage, key, now);
  const clean = String(text || "").slice(0, DRAFT_MAX_CHARS);
  if (clean.trim()) drafts[slot] = { text: clean, at: now };
  else delete drafts[slot];
  const slots = Object.keys(drafts).sort((a, b) => drafts[b].at - drafts[a].at);
  for (const extra of slots.slice(DRAFT_MAX_CHATS)) delete drafts[extra];
  store(storage, key, drafts);
}

export function clearDraft(storage, key, slot) {
  writeDraft(storage, key, slot, "");
}

/** Slots that have a draft, for the marker in the chat list. */
export function draftSlots(storage, key, now = Date.now()) {
  return new Set(Object.keys(readDrafts(storage, key, now)));
}

/**
 * Queued prompts, one list per chat. A prompt stays with the chat it was written in;
 * the arrays are stable, so the open chat can hold a reference to its own list.
 */
export function createChatQueues() {
  const lists = new Map();
  return {
    of(id) {
      const slot = draftSlot(id);
      if (!lists.has(slot)) lists.set(slot, []);
      return lists.get(slot);
    },
    has(id) {
      return Boolean(lists.get(draftSlot(id))?.length);
    },
    /** A new chat got its id: its queue moves along (same array). */
    rename(from, to) {
      const a = draftSlot(from);
      const b = draftSlot(to);
      if (a === b || !lists.has(a)) return;
      const moving = lists.get(a);
      lists.delete(a);
      const existing = lists.get(b);
      if (existing?.length) existing.push(...moving.splice(0));
      else lists.set(b, moving);
    },
    drop(id) {
      const list = lists.get(draftSlot(id));
      if (list) list.length = 0;
    },
    ids() {
      return [...lists.keys()].filter((slot) => lists.get(slot).length && slot !== NEW_CHAT_DRAFT);
    },
  };
}

/**
 * Send a chat's queued prompts while another chat is open: wait for the running reply,
 * then send one after the other. Stops (and leaves the rest queued) as soon as the chat
 * is open again, so the open chat takes over, or when a send fails.
 *
 * deps: isActive(id) -> bool, status(id) -> "pending" | "idle" | "gone",
 * send(id, turn) -> "ok" | "busy" | "gone" | "error", wait(ms), onSent(id, turn).
 * Returns why it stopped: "empty" | "active" | "gone" | "error" | "timeout".
 */
export async function drainQueue(id, queues, deps, { pollMs = 2000, maxPolls = 1800 } = {}) {
  const { isActive, status, send, wait, onSent } = deps;
  let polls = 0;
  while (true) {
    if (!queues.has(id)) return "empty";
    if (isActive(id)) return "active";
    const state = await status(id);
    if (state === "gone") {
      queues.drop(id);
      return "gone";
    }
    if (isActive(id)) return "active";
    if (state !== "idle") {
      polls += 1;
      if (polls > maxPolls) return "timeout";
      await wait(pollMs);
      continue;
    }
    const list = queues.of(id);
    const turn = list.shift();
    if (!turn) return "empty";
    const result = await send(id, turn);
    if (result === "busy") {
      list.unshift(turn);
      polls += 1;
      if (polls > maxPolls) return "timeout";
      await wait(pollMs);
      continue;
    }
    if (result === "gone") {
      queues.drop(id);
      return "gone";
    }
    if (result !== "ok") {
      // Nothing is lost: the prompt goes back and waits until the chat is opened again.
      list.unshift(turn);
      return "error";
    }
    polls = 0;
    onSent?.(id, turn);
  }
}
