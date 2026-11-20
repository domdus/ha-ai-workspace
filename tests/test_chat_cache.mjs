/**
 * Chat loading in the browser: last-chat cache, skeleton, time limits, unread dot.
 * Run: node tests/test_chat_cache.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  CHAT_CACHE_MAX_BYTES,
  CHAT_CACHE_TAIL,
  LOAD_TIMEOUT_MS,
  SKELETON_DELAY_MS,
  SLOW_HINT_MS,
  anyUnread,
  chatCacheKey,
  clearChatCache,
  loadOutcome,
  olderCount,
  readChatCache,
  sameChat,
  timeoutSignal,
  trimChatForCache,
  writeChatCache,
} from "../custom_components/ai_workspace/www/chat_cache.js";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const read = (name) => readFileSync(new URL(name, www), "utf8");
const chatSrc = read("chat.js");
const panelSrc = read("panel.js");
const i18nSrc = read("i18n.js");

class MemoryStorage {
  constructor(limit = Infinity) {
    this.map = new Map();
    this.limit = limit;
  }
  get length() {
    return this.map.size;
  }
  key(i) {
    return [...this.map.keys()][i] ?? null;
  }
  getItem(k) {
    return this.map.has(k) ? this.map.get(k) : null;
  }
  setItem(k, v) {
    if (String(v).length > this.limit) {
      const err = new Error("full");
      err.name = "QuotaExceededError";
      throw err;
    }
    this.map.set(k, String(v));
  }
  removeItem(k) {
    this.map.delete(k);
  }
}

function chat(id, count, size = 100) {
  return {
    id,
    title: "Bewässerung",
    provider: "cursor",
    messages: Array.from({ length: count }, (_, n) => ({
      id: n + 1,
      role: n % 2 ? "assistant" : "user",
      content: `${n} ${"x".repeat(size)}`,
      events: [
        { type: "image", name: "a.png", data: "A".repeat(5000) },
        { type: "cross_chat", chats: [{ id: "w", title: "W" }], text: "secret excerpt" },
      ],
      created_at: "2026-11-19",
    })),
  };
}

// Keys are per user.
assert.equal(chatCacheKey(""), "");
assert.equal(chatCacheKey("u1"), "ai_workspace_last_chat:u1");

// Only the newest messages, without image data or excerpt text, under the size cap.
const trimmed = trimChatForCache(chat("c1", 60));
assert.equal(trimmed.messages.length, CHAT_CACHE_TAIL);
assert.equal(trimmed.messages[0].id, 60 - CHAT_CACHE_TAIL + 1);
assert.ok(!JSON.stringify(trimmed).includes("AAAA"));
assert.ok(!JSON.stringify(trimmed).includes("secret excerpt"));
assert.ok(JSON.stringify(trimChatForCache(chat("c2", 24, 15000))).length <= CHAT_CACHE_MAX_BYTES);

// A chat with pictures is painted again from the server: the cache keeps no image data.
assert.ok(!sameChat(trimChatForCache(chat("c1", 24)), chat("c1", 24)));
const plain = (c) => ({ ...c, messages: c.messages.map((m) => ({ ...m, events: [] })) });
// Same chat: no repaint. A new reply: repaint.
const fresh = plain(chat("c1", 24));
assert.ok(sameChat(trimChatForCache(fresh), fresh));
const newer = plain(chat("c1", 25));
assert.ok(!sameChat(trimChatForCache(fresh), newer));
assert.ok(!sameChat(trimChatForCache(fresh), plain(chat("c9", 24))));
// A long chat: the cache holds its tail; the same tail means only older messages are added.
const long = plain(chat("c3", 60));
assert.ok(sameChat(trimChatForCache(long), long));
assert.equal(olderCount(trimChatForCache(long), long), 60 - CHAT_CACHE_TAIL);
assert.ok(!sameChat(trimChatForCache(long), plain(chat("c3", 61))));

// Write, read back, and never throw on a full storage.
const storage = new MemoryStorage();
const key = chatCacheKey("u1");
assert.ok(writeChatCache(storage, key, fresh));
assert.equal(readChatCache(storage, key, "c1").id, "c1");
assert.equal(readChatCache(storage, key, "other"), null);
const full = new MemoryStorage(10);
full.setItem = MemoryStorage.prototype.setItem.bind(full);
assert.equal(writeChatCache(full, key, fresh), false);
assert.equal(full.getItem(key), null);

// Deleting the chat drops it; another user on the device drops other users' chats.
clearChatCache(storage, key, { id: "other" });
assert.ok(storage.getItem(key));
clearChatCache(storage, key, { id: "c1" });
assert.equal(storage.getItem(key), null);
writeChatCache(storage, chatCacheKey("u1"), fresh);
writeChatCache(storage, chatCacheKey("u2"), fresh);
clearChatCache(storage, "", { keepKey: chatCacheKey("u2") });
assert.equal(storage.getItem(chatCacheKey("u1")), null);
assert.ok(storage.getItem(chatCacheKey("u2")));

// Only 404 resets to a new chat.
assert.equal(loadOutcome({ ok: true, status: 200 }), "ok");
assert.equal(loadOutcome({ ok: false, status: 404 }), "gone");
assert.equal(loadOutcome({ ok: false, status: 500 }), "error");
assert.equal(loadOutcome({ ok: false, status: 503 }), "error");
assert.equal(loadOutcome(null), "error");
assert.equal(loadOutcome({ ok: true, status: 200 }, true), "error");

// Unread: the open, visible chat does not count.
assert.equal(anyUnread([{ id: "a", unread: true }], "a", true), false);
assert.equal(anyUnread([{ id: "a", unread: true }], "a", false), true);
assert.equal(anyUnread([{ id: "a", unread: false }, { id: "b", unread: true }], "a", true), true);

// Time limits.
assert.equal(SKELETON_DELAY_MS, 150);
assert.equal(SLOW_HINT_MS, 8000);
assert.equal(LOAD_TIMEOUT_MS, 20000);
const limited = timeoutSignal(10);
await new Promise((resolve) => setTimeout(resolve, 30));
assert.ok(limited.signal.aborted);
const outer = new AbortController();
const linked = timeoutSignal(10000, outer.signal);
outer.abort();
assert.ok(linked.signal.aborted);
linked.done();

// Skeleton: alternating bubbles, busy and announced, shown at once on open and late on a switch.
assert.match(chatSrc, /function messageSkeleton\(\)/);
assert.match(chatSrc, /bubble-skeleton \$\{role\}/);
assert.match(chatSrc, /role="status">\$\{htmlAttr\(t\("chat_loading"\)\)\}/);
assert.match(chatSrc, /logEl\.setAttribute\("aria-busy", "true"\)/);
assert.match(chatSrc, /\} else if \(initial\) \{\n\s+showMessageSkeleton\(\);/);
assert.match(chatSrc, /SKELETON_DELAY_MS\);/);
assert.match(chatSrc, /t\("chat_slow"\)/);
assert.match(chatSrc, /\{ raise: true, timeout: LOAD_TIMEOUT_MS \}/);
assert.match(chatSrc, /if \(outcome === "gone"\) \{/);
assert.match(chatSrc, /showLoadError\(id\)/);
assert.match(chatSrc, /t\("retry"\)/);
assert.match(chatSrc, /openSession\(id, true\);/);
for (const css of ["chat.css"]) {
  const text = read(css);
  assert.match(text, /\.message-skeleton \.bubble-skeleton \{[^}]*animation: session-skeleton/);
  assert.match(text, /prefers-reduced-motion: reduce\) \{\n  \.message-skeleton \.bubble-skeleton \{\n    animation: none;/);
  assert.match(text, /\.unread-dot \{/);
  assert.match(text, /\.chat-load-error \{/);
}

// Faster start: the chat is asked for right away, theme from the last visit, /ui once, the rest later.
assert.match(chatSrc, /export function prefetchSession\(/);
assert.match(chatSrc, /priority: "high"/);
assert.match(panelSrc, /prefetchSession\?\.\(routeSessionId\?\.\(\) \|\| "", token\);\n\s+await prefetchUiTheme\(token\);/);
assert.match(chatSrc, /localStorage\.getItem\(UI_THEME_KEY\)/);
assert.match(chatSrc, /if \(next !== activeUiTheme\) void remountForUiTheme\(next\);/);
assert.equal((chatSrc.match(/`\$\{API\}\/ui`/g) || []).length, 1);
assert.match(chatSrc, /sessionLoad\.then\(\(\) => whenIdle\(startDeferred\)\)/);
assert.ok(!/\n  loadProviders\(\);\n  loadDictate\(\);\n/.test(chatSrc));
assert.match(chatSrc, /readChatCache\(localStorage, chatCacheSlot\(\), id\)/);
assert.match(chatSrc, /if \(!cached \|\| !sameChat\(cached, session\)\) paintSession\(session, gen\);/);
assert.match(chatSrc, /prependOlder\(session\.messages, olderCount\(cached, session\)\)/);
assert.match(chatSrc, /clearChatCache\(localStorage, chatCacheSlot\(\), \{ id: session\.id \}\)/);

// Unread dot: on rows, on the chat list buttons, live from the list poll, read when opened and visible.
assert.match(chatSrc, /dot\.setAttribute\("aria-label", t\("unread_reply"\)\)/);
assert.match(chatSrc, /options\.onUnread\?\.\(unread\)/);
assert.match(chatSrc, /busy \? SESSIONS_POLL_BUSY_MS : SESSIONS_POLL_IDLE_MS/);
assert.match(chatSrc, /if \(sessionId === chatId\) markRead\(chatId\);/);
assert.match(chatSrc, /body: JSON\.stringify\(\{ read: /);
assert.match(panelSrc, /onUnread: \(unread\) => this\._setUnread\(unread, ui\)/);
assert.match(panelSrc, /\.chats-menu \.unread-dot \{/);

// Every language has the new texts.
for (const key of ["chat_loading", "chat_slow", "chat_load_failed", "retry", "unread_reply", "chats_unread"]) {
  assert.equal((i18nSrc.match(new RegExp(`^    ${key}: "`, "gm")) || []).length, 15, key);
}

console.log("test_chat_cache.mjs ok");
