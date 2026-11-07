/**
 * Guards for chat send / session routing and the queue/attach helpers in send_guard.js.
 * Run: node tests/test_send_guard.mjs
 */
import { readFileSync } from "node:fs";
import {
  MAX_ATTACH,
  MAX_QUEUE,
  filesToRead,
  takeInputFiles,
  pullQueuedDraft,
  keepQueueOnHalt,
} from "../custom_components/ai_workspace/www/send_guard.js";

const chatSrc = readFileSync(new URL("../custom_components/ai_workspace/www/chat.js", import.meta.url), "utf8");

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

ok(sendButtonMode({ streaming: true, hasDraft: false }).action === "stop", "Send is Stop while the agent is working");
ok(sendButtonMode({ streaming: true, hasDraft: false }).enabled === true, "Stop stays clickable with an empty composer");
ok(sendButtonMode({ streaming: true, hasDraft: true }).action === "send", "A typed follow-up turns Stop back into Send");
ok(sendButtonMode({ streaming: true, hasDraft: true }).enabled === true, "Send stays clickable so the follow-up can queue");
ok(sendButtonMode({ streaming: false, hasDraft: false }).enabled === false, "Send stays off without a draft");
ok(sendButtonMode({ streaming: false, hasDraft: true }).action === "send", "Send returns after stop");

ok(keepQueueOnHalt("stop") === true, "Stop keeps the queued stack");
ok(keepQueueOnHalt("send") === true, "Sending the next turn keeps remaining queued prompts");
ok(keepQueueOnHalt("switch") === true, "Switching chats keeps the queued stack");
ok(keepQueueOnHalt("destroy") === false, "Destroying the panel drops the queue");

const stacked = [{ text: "first" }, { text: "second" }, { text: "third" }];
const fromEmpty = pullQueuedDraft(stacked, { draftText: "", pending: [] });
ok(fromEmpty.pulled && fromEmpty.text === "first", "Empty composer takes the first queued prompt");
ok(stacked.length === 2 && stacked[0].text === "second", "The rest of the stack stays queued");

const withDraft = [{ text: "kept" }, { text: "also" }];
const skipped = pullQueuedDraft(withDraft, { draftText: "I am typing", pending: [] });
ok(!skipped.pulled, "A typed draft is not replaced by the queue");
ok(withDraft.length === 2, "Queue stays intact when the composer already has text");

ok(MAX_ATTACH === 4 && MAX_QUEUE === 10, "Attach and queue caps");
ok(filesToRead(["a", "b", "c", "d", "e"], 4).join(",") === "a,b,c,d", "Only four files are read");
ok(filesToRead(["a", "b", "c"], 1).join(",") === "a", "Remaining slots cap the read");
ok(filesToRead(["a", "b"], 0).length === 0, "No slots means no files are read");

{
  let clearedBeforeRead = false;
  const input = { files: ["one", "two"], value: "x" };
  const freeze = async (files, slots) => {
    if (input.value === "") clearedBeforeRead = true;
    return filesToRead(files, slots);
  };
  const frozen = await takeInputFiles(input, freeze, 4);
  ok(!clearedBeforeRead, "Picker is still set while bytes are copied");
  ok(input.value === "", "Picker is cleared after the copy");
  ok(frozen.join(",") === "one,two", "Copied files are returned");
}

{
  const input = { files: ["a", "b", "c", "d", "e"], value: "x" };
  const freeze = async (files, slots) => filesToRead(files, slots);
  const frozen = await takeInputFiles(input, freeze, 2);
  ok(frozen.join(",") === "a,b", "Limit applies before reading");
}

{
  const input = { files: [], value: "x" };
  const freeze = async () => {
    throw new Error("should not read an empty picker");
  };
  const frozen = await takeInputFiles(input, freeze, 4);
  ok(frozen.length === 0 && input.value === "", "Empty picker clears without reading");
}

ok(chatSrc.includes("takeInputFiles("), "chat.js copies picker files before clearing");
ok(chatSrc.includes("keepQueueOnHalt("), "chat.js keeps the queue on send/stop");
ok(chatSrc.includes("pullQueuedDraft("), "chat.js restores queued prompts via pullQueuedDraft");
ok(chatSrc.includes("takePendingClip("), "chat.js bundles TTS clips from speech.js");
ok(!/function takePendingClip\(/.test(chatSrc), "chat.js does not reimplement takePendingClip");

if (failed) {
  process.exit(1);
}
console.log("test_send_guard: ok");
