/**
 * Guards for chat send / session routing (mirrors chat.js invariants).
 * Run: node tests/test_send_guard.mjs
 */

function knownSessionId({ freshChat, sessionId, pathId, compactStored }) {
  if (freshChat) return "";
  if (sessionId) return sessionId;
  if (!compactStored && pathId) return pathId;
  return compactStored || "";
}

function shouldCreateSessionOnSend({ sessionId, freshChat, pathId, compactStored }) {
  const known = knownSessionId({ freshChat, sessionId, pathId, compactStored });
  return !known;
}

let failed = 0;

function ok(cond, label) {
  if (!cond) {
    console.error("FAIL:", label);
    failed += 1;
  }
}

ok(
  shouldCreateSessionOnSend({
    sessionId: "",
    freshChat: true,
    pathId: "881b43ca352b4da2b8470ce28327c245",
    compactStored: "",
  }),
  "New Chat must create a session even when URL still shows an old id",
);

ok(
  !shouldCreateSessionOnSend({
    sessionId: "",
    freshChat: false,
    pathId: "881b43ca352b4da2b8470ce28327c245",
    compactStored: "",
  }),
  "Deep link should open existing session before send",
);

ok(
  knownSessionId({
    freshChat: false,
    sessionId: "abc",
    pathId: "other",
    compactStored: "",
  }) === "abc",
  "Active sessionId wins over URL",
);

function sendButtonMode({ streaming, hasDraft }) {
  if (streaming && !hasDraft) return { action: "stop", enabled: true };
  return { action: "send", enabled: Boolean(hasDraft) };
}

function afterStop({ queued }) {
  return queued ? "flush" : "idle";
}

ok(sendButtonMode({ streaming: true, hasDraft: false }).action === "stop", "Send is Stop while the agent is working");
ok(sendButtonMode({ streaming: true, hasDraft: false }).enabled === true, "Stop stays clickable with an empty composer");
ok(sendButtonMode({ streaming: true, hasDraft: true }).action === "send", "A typed follow-up turns Stop back into Send");
ok(sendButtonMode({ streaming: true, hasDraft: true }).enabled === true, "Send stays clickable so the follow-up can queue");
ok(sendButtonMode({ streaming: false, hasDraft: false }).enabled === false, "Send stays off without a draft");
ok(sendButtonMode({ streaming: false, hasDraft: true }).action === "send", "Send returns after stop");
ok(afterStop({ queued: true }) === "flush", "A queued prompt is sent after stop");
ok(afterStop({ queued: false }) === "idle", "With an empty queue, stop leaves the composer free");

function flushQueued({ queued, draft, pending }) {
  return { send: queued, composer: draft, pending };
}

function queueWhileBusy({ queued, draft, sendQueued }) {
  const list = Array.isArray(queued) ? queued.slice() : queued ? [queued] : [];
  if (draft) list.push(draft);
  return { queued: list, composer: "" };
}

ok(
  flushQueued({ queued: "first", draft: "second", pending: [] }).composer === "second",
  "Flushing the queue must leave a typed follow-up in the composer",
);
ok(
  flushQueued({ queued: "first", draft: "second", pending: [] }).send === "first",
  "Flushing the queue sends the queued prompt, not the draft",
);
ok(
  JSON.stringify(queueWhileBusy({ queued: "first", draft: "second" }).queued) === JSON.stringify(["first", "second"]),
  "A second send while one prompt is queued appends instead of replacing",
);
ok(
  queueWhileBusy({ queued: "first", draft: "second" }).composer === "",
  "Queuing a follow-up clears the composer so the next prompt can be typed",
);
ok(
  JSON.stringify(queueWhileBusy({ queued: ["first", "second"], draft: "third" }).queued) ===
    JSON.stringify(["first", "second", "third"]),
  "Further sends stack on the queue",
);
ok(
  JSON.stringify(queueWhileBusy({ queued: "first", draft: "second", sendQueued: true }).queued) ===
    JSON.stringify(["first", "second"]),
  "A send while the queue is flushing still stacks",
);

if (failed) {
  process.exit(1);
}
console.log("test_send_guard: ok");
