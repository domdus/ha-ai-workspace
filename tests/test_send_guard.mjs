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
  if (streaming) return { action: "stop", enabled: true };
  return { action: "send", enabled: Boolean(hasDraft) };
}

function afterStop({ queued }) {
  return queued ? "flush" : "idle";
}

ok(sendButtonMode({ streaming: true, hasDraft: false }).action === "stop", "Send is Stop while the agent is working");
ok(sendButtonMode({ streaming: true, hasDraft: false }).enabled === true, "Stop stays clickable with an empty composer");
ok(sendButtonMode({ streaming: false, hasDraft: false }).enabled === false, "Send stays off without a draft");
ok(sendButtonMode({ streaming: false, hasDraft: true }).action === "send", "Send returns after stop");
ok(afterStop({ queued: true }) === "flush", "A queued prompt is sent after stop");
ok(afterStop({ queued: false }) === "idle", "With an empty queue, stop leaves the composer free");

if (failed) {
  process.exit(1);
}
console.log("test_send_guard: ok");
