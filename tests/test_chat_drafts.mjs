/**
 * Per-chat composer drafts and per-chat queued prompts (chat_drafts.js).
 * Run: node tests/test_chat_drafts.mjs
 */
import { readFileSync } from "node:fs";
import {
  DRAFT_TTL_MS,
  DRAFT_MAX_CHARS,
  DRAFT_MAX_CHATS,
  NEW_CHAT_DRAFT,
  draftStoreKey,
  draftSlot,
  readDrafts,
  readDraft,
  writeDraft,
  clearDraft,
  draftSlots,
  createChatQueues,
  drainQueue,
} from "../custom_components/ai_workspace/www/chat_drafts.js";

const chatSrc = readFileSync(new URL("../custom_components/ai_workspace/www/chat.js", import.meta.url), "utf8");

let failed = 0;
function ok(cond, label) {
  if (!cond) {
    console.error("FAIL:", label);
    failed += 1;
  }
}

function memoryStorage() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    get size() {
      return data.size;
    },
  };
}

// Keys and slots
ok(draftStoreKey("u1") === "ai_workspace_drafts:u1", "Drafts are kept per user");
ok(draftStoreKey("u1") !== draftStoreKey("u2"), "Two users never share drafts");
ok(draftStoreKey("") === "", "Without a known user nothing is stored");
ok(draftSlot("") === NEW_CHAT_DRAFT && draftSlot(null) === NEW_CHAT_DRAFT, "The new chat has its own slot");
ok(draftSlot("abc") === "abc", "A chat's slot is its id");

// Per-chat text
{
  const s = memoryStorage();
  const key = draftStoreKey("u1");
  const now = 1_000_000;
  writeDraft(s, key, "chatA", "Hallo A", now);
  writeDraft(s, key, NEW_CHAT_DRAFT, "neuer Chat", now);
  ok(readDraft(s, key, "chatA", now) === "Hallo A", "Chat A gets its own draft back");
  ok(readDraft(s, key, "chatB", now) === "", "Chat B without a draft starts empty (no leak from A)");
  ok(readDraft(s, key, NEW_CHAT_DRAFT, now) === "neuer Chat", "The new chat keeps its own draft");
  ok(readDraft(s, draftStoreKey("u2"), "chatA", now) === "", "Another user does not see it");
  writeDraft(s, key, "chatA", "   ", now);
  ok(readDraft(s, key, "chatA", now) === "", "Blank text removes the draft");
  clearDraft(s, key, NEW_CHAT_DRAFT);
  ok(s.size === 0, "The store key goes away when no draft is left");
}

// TTL, size and count caps
{
  const s = memoryStorage();
  const key = draftStoreKey("u1");
  writeDraft(s, key, "old", "alt", 0);
  ok(readDraft(s, key, "old", DRAFT_TTL_MS - 1) === "alt", "A draft lives up to the TTL");
  ok(readDraft(s, key, "old", DRAFT_TTL_MS + 1) === "", "An expired draft is gone");
  writeDraft(s, key, "new", "x".repeat(DRAFT_MAX_CHARS + 500), DRAFT_TTL_MS + 1);
  ok(!Object.keys(readDrafts(s, key, DRAFT_TTL_MS + 1)).includes("old"), "Writing prunes expired drafts");
  ok(readDraft(s, key, "new", DRAFT_TTL_MS + 1).length === DRAFT_MAX_CHARS, "Long drafts are trimmed");
}
{
  const s = memoryStorage();
  const key = draftStoreKey("u1");
  for (let i = 0; i < DRAFT_MAX_CHATS + 5; i += 1) writeDraft(s, key, `c${i}`, `t${i}`, 1000 + i);
  const slots = draftSlots(s, key, 2000);
  ok(slots.size === DRAFT_MAX_CHATS, "Only the newest drafts are kept");
  ok(slots.has(`c${DRAFT_MAX_CHATS + 4}`) && !slots.has("c0"), "The oldest drafts are dropped first");
}
{
  const s = memoryStorage();
  s.setItem(draftStoreKey("u1"), "{not json");
  ok(readDraft(s, draftStoreKey("u1"), "a") === "", "A broken store reads as empty");
  const throwing = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("full");
    },
    removeItem() {},
  };
  writeDraft(throwing, "k", "a", "text");
  ok(readDraft(throwing, "k", "a") === "", "Blocked storage does not throw");
}

// Per-chat queues
{
  const q = createChatQueues();
  q.of("A").push({ text: "a1" }, { text: "a2" });
  q.of("B").push({ text: "b1" });
  ok(q.of("A").length === 2 && q.of("B").length === 1, "Each chat has its own queue");
  ok(q.of("A") === q.of("A"), "The list is stable, so the open chat can hold it");
  ok(!q.has("C") && q.has("A"), "has() is per chat");
  q.of("").push({ text: "n1" });
  const list = q.of("");
  q.rename("", "N");
  ok(q.of("N") === list && q.of("N")[0].text === "n1" && !q.has(""), "A new chat's queue moves to its id");
  q.drop("B");
  ok(!q.has("B") && q.has("A"), "Dropping one chat's queue leaves the others");
  ok(q.ids().sort().join(",") === "A,N", "ids() lists chats with queued prompts");
}

// Background sending: waits for the running reply, sends in order to its own chat.
{
  const q = createChatQueues();
  q.of("A").push({ text: "a1" }, { text: "a2" });
  q.of("B").push({ text: "b1" });
  const sent = [];
  let busy = 2;
  const reason = await drainQueue("A", q, {
    isActive: () => false,
    status: async () => (busy-- > 0 ? "pending" : "idle"),
    send: async (id, turn) => {
      sent.push(`${id}:${turn.text}`);
      return "ok";
    },
    wait: async () => {},
    onSent: () => {},
  });
  ok(reason === "empty", "Background run ends when the queue is empty");
  ok(sent.join(",") === "A:a1,A:a2", "Queued prompts go out in order, in their own chat");
  ok(q.of("B").length === 1, "Another chat's queue is not touched");
}
{
  const q = createChatQueues();
  q.of("A").push({ text: "a1" }, { text: "a2" });
  let active = false;
  const sent = [];
  const reason = await drainQueue("A", q, {
    isActive: () => active,
    status: async () => "idle",
    send: async (_id, turn) => {
      sent.push(turn.text);
      active = true; // the user opens chat A again
      return "ok";
    },
    wait: async () => {},
  });
  ok(reason === "active" && sent.length === 1, "The open chat takes over once the user is back");
  ok(q.of("A").length === 1 && q.of("A")[0].text === "a2", "What is left stays queued for that chat");
}
{
  const q = createChatQueues();
  q.of("A").push({ text: "a1" });
  let tries = 0;
  const reason = await drainQueue("A", q, {
    isActive: () => false,
    status: async () => "idle",
    send: async () => (++tries < 3 ? "busy" : "ok"),
    wait: async () => {},
  });
  ok(reason === "empty" && tries === 3, "A busy chat (409) is retried, the prompt is not lost");
}
{
  const q = createChatQueues();
  q.of("A").push({ text: "a1" });
  const reason = await drainQueue("A", q, {
    isActive: () => false,
    status: async () => "idle",
    send: async () => "error",
    wait: async () => {},
  });
  ok(reason === "error" && q.of("A")[0]?.text === "a1", "A failed send keeps the prompt for when the chat is opened");
}
{
  const q = createChatQueues();
  q.of("A").push({ text: "a1" });
  const reason = await drainQueue("A", q, {
    isActive: () => false,
    status: async () => "gone",
    send: async () => "ok",
    wait: async () => {},
  });
  ok(reason === "gone" && !q.has("A"), "A deleted chat drops its queue");
}
{
  const q = createChatQueues();
  q.of("A").push({ text: "a1" });
  let sent = 0;
  const reason = await drainQueue(
    "A",
    q,
    { isActive: () => false, status: async () => "pending", send: async () => (sent += 1), wait: async () => {} },
    { maxPolls: 3 },
  );
  ok(reason === "timeout" && sent === 0 && q.has("A"), "A reply that never ends does not lose the queue");
}

// Wiring in chat.js
ok(chatSrc.includes("./chat_drafts.js"), "chat.js loads chat_drafts.js");
ok(/form\.addEventListener\("input"[\s\S]{0,200}saveDraftSoon\(\)/.test(chatSrc), "Typing saves the draft");
{
  const del = chatSrc.slice(chatSrc.indexOf("async function deleteSession"), chatSrc.indexOf("function displayTitle"));
  ok(del.includes("dropDraft(session.id)") && del.includes("chatQueues.drop(session.id)"), "Deleting a chat clears its draft and queue");
  const sw = chatSrc.slice(chatSrc.indexOf("function switchComposer"), chatSrc.indexOf("function adoptNewChat"));
  ok(sw.includes("saveDraft()") && sw.includes("readDraft("), "Switching saves the old draft and restores the new one");
  ok(sw.includes("nextTurns = chatQueues.of(id)"), "Switching shows only the target chat's queue");
  ok(sw.includes("setSelectionRange") && sw.includes("resizeComposer()"), "Cursor at the end, composer resized");
  const send = chatSrc.slice(chatSrc.indexOf('form.addEventListener("submit"'), chatSrc.indexOf('chatEl.addEventListener("scroll"'));
  ok(send.includes("dropDraft(sessionId)"), "Sending clears the draft");
  ok(send.includes("sessionId !== queuedFrom"), "A queued prompt never goes out after a chat switch");
  ok(send.includes("status === 409"), "A busy chat queues the prompt instead of failing");
  const bg = chatSrc.slice(chatSrc.indexOf("function sendQueueInBackground"), chatSrc.indexOf("function resumeQueue"));
  ok(bg.includes("refreshSessions()"), "A reply finished in the background brings its unread dot");
  const bgSend = chatSrc.slice(chatSrc.indexOf("async function backgroundSend"), chatSrc.indexOf("function sendQueueInBackground"));
  ok(!bgSend.includes("selectedAgent()"), "Background sends keep the chat's own agent");
}

if (failed) process.exit(1);
console.log("test_chat_drafts: ok");
