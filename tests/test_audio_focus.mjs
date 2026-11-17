// Sending a prompt must not touch audio unless auto read-aloud is on (Android ducks
// other apps as soon as a page plays even a silent clip).
import { readFileSync } from "node:fs";
import { unlockOnSend, releaseAudio } from "../custom_components/ai_workspace/www/speech.js";

let failed = 0;
function ok(cond, label) {
  if (!cond) {
    console.error("FAIL:", label);
    failed += 1;
  }
}

ok(unlockOnSend({ speak: true, tts: true }) === true, "auto read-aloud on: unlock");
ok(unlockOnSend({ speak: false, tts: true }) === false, "auto read-aloud off: no unlock");
ok(unlockOnSend({ speak: true, tts: false }) === false, "no TTS engine: no unlock");
ok(unlockOnSend({ speak: false, tts: false }) === false, "all off: no unlock");
ok(unlockOnSend(null) === false, "no voice settings yet: no unlock");

function fakeAudio({ paused = false, src = "blob:x" } = {}) {
  const calls = [];
  const attrs = new Map(src ? [["src", src]] : []);
  return {
    calls,
    paused,
    get src() {
      return attrs.get("src") || "";
    },
    pause() {
      calls.push("pause");
      this.paused = true;
    },
    hasAttribute: (name) => attrs.has(name),
    removeAttribute(name) {
      calls.push(`remove:${name}`);
      attrs.delete(name);
    },
    load() {
      calls.push("load");
    },
  };
}

{
  const audio = fakeAudio();
  releaseAudio(audio);
  ok(audio.paused, "playing audio is paused");
  ok(audio.src === "", "source unloaded");
  ok(audio.calls.join(",") === "pause,remove:src,load", `release order: ${audio.calls}`);
}
{
  const audio = fakeAudio({ paused: true, src: "" });
  releaseAudio(audio);
  ok(audio.calls.length === 0, "nothing loaded: nothing to do");
}
releaseAudio(null);

// The send path in chat.js only unlocks audio through the read-aloud gate.
const chat = readFileSync(new URL("../custom_components/ai_workspace/www/chat.js", import.meta.url), "utf8");
const calls = [...chat.matchAll(/^\s*(.*)\bunlockOutput\(\)/gm)].map((m) => m[0].trim());
for (const line of calls) {
  if (line.startsWith("async function unlockOutput")) continue;
  ok(
    /unlockOnSend\(voice\)/.test(line) || /if \(fromUser\) await unlockOutput\(\)/.test(line),
    `ungated unlockOutput(): ${line}`,
  );
}
ok(calls.length >= 2, "unlockOutput call sites found");
ok(!/speechSynthesis/.test(chat), "no Web Speech synthesis (would grab audio focus)");

if (failed) {
  console.error(`${failed} audio focus check(s) failed`);
  process.exit(1);
}
console.log("audio focus ok");
