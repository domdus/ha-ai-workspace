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

if (failed) {
  process.exit(1);
}
console.log("test_send_guard: ok");
