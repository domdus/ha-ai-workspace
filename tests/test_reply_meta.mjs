/**
 * Reply meta: reply time label and the action row under each finished reply
 * (copy, read aloud, time).
 * Run: node tests/test_reply_meta.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  haHour12,
  haTimeZone,
  parseReplyTime,
  replyActionText,
  replyRows,
  replyTimeLabel,
  replyTimeTitle,
} from "../custom_components/ai_workspace/www/reply_meta.js";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const read = (name) => readFileSync(new URL(name, www), "utf8");
const chatSrc = read("chat.js");
const i18nSrc = read("i18n.js");
const cssStandard = read("chat.css");

const de = { locale: "de-DE", timeZone: "Europe/Berlin", hour12: false, yesterday: "gestern, {time}" };
const now = new Date("2026-11-19T10:00:00Z"); // 11:00 in Berlin

// --- time label ---
assert.equal(replyTimeLabel("2026-11-19T08:30:00+00:00", { ...de, now }), "09:30", "today: time only");
assert.equal(replyTimeLabel("2026-11-18T20:04:00Z", { ...de, now }), "gestern, 21:04", "yesterday");
assert.equal(replyTimeLabel("2026-11-17T20:04:00Z", { ...de, now }), "17.11., 21:04", "older, same year");
assert.equal(replyTimeLabel("2025-11-17T20:04:00Z", { ...de, now }), "17.11.2025, 21:04", "other year");

// Day borders follow the chosen time zone, not UTC: 23:30 UTC on the 18th is the 19th in Berlin.
assert.equal(replyTimeLabel("2026-11-18T23:30:00Z", { ...de, now }), "00:30");
// ...and the 18th in New York, where "now" is still the 19th (05:00).
assert.equal(
  replyTimeLabel("2026-11-18T23:30:00Z", { ...de, timeZone: "America/New_York", now }),
  "gestern, 18:30",
);
// Yesterday across a month and a year border.
assert.equal(
  replyTimeLabel("2026-12-31T12:00:00Z", { ...de, now: new Date("2027-01-01T12:00:00Z") }),
  "gestern, 13:00",
);
assert.equal(
  replyTimeLabel("2026-12-30T12:00:00Z", { ...de, now: new Date("2027-01-01T12:00:00Z") }),
  "30.12.2026, 13:00",
);

// English and the 12-hour clock come from Intl.
const en = replyTimeLabel("2026-11-18T20:04:00Z", {
  locale: "en-US",
  timeZone: "Europe/Berlin",
  hour12: true,
  yesterday: "yesterday, {time}",
  now,
});
assert.match(en, /^yesterday, 09:04\sPM$/);

// Bad input stays empty; an unknown time zone falls back instead of throwing.
assert.equal(replyTimeLabel("", { ...de, now }), "");
assert.equal(replyTimeLabel(undefined, { ...de, now }), "");
assert.equal(replyTimeLabel("not a date", { ...de, now }), "");
assert.ok(replyTimeLabel("2026-11-19T08:30:00Z", { ...de, timeZone: "Mars/Olympus", now }));
assert.equal(parseReplyTime(null), null);
assert.equal(parseReplyTime(0)?.toISOString(), "1970-01-01T00:00:00.000Z");

// Tooltip carries the full date and time.
const title = replyTimeTitle("2026-11-17T20:04:00Z", de);
assert.match(title, /Dienstag/);
assert.match(title, /17\. November 2026/);
assert.match(title, /21:04/);
assert.equal(replyTimeTitle("", de), "");

// HA profile settings.
assert.equal(haHour12("12"), true);
assert.equal(haHour12("24"), false);
assert.equal(haHour12("language"), undefined);
assert.equal(haHour12(undefined), undefined);
assert.equal(haTimeZone({ config: { time_zone: "Europe/Berlin" }, locale: { time_zone: "server" } }), "Europe/Berlin");
assert.equal(haTimeZone({ config: { time_zone: "Europe/Berlin" }, locale: { time_zone: "local" } }), undefined);
assert.equal(haTimeZone(null), undefined);

// --- which replies get their own action row ---
assert.deepEqual(replyRows([]), []);
assert.deepEqual(replyRows(null), []);
assert.deepEqual(replyRows([{ role: "user", text: "Hallo" }]), [], "user messages get no row");
assert.equal(replyActionText({ role: "assistant", text: "  **first**  " }), "**first**", "markdown kept, trimmed");
assert.equal(replyActionText({ role: "assistant", text: "half", streaming: true }), "", "streaming: no row yet");
assert.equal(replyActionText({ role: "assistant", text: "", createdAt: "x" }), "", "only tool steps: no row");
assert.equal(replyActionText({ role: "assistant", text: "  \n " }), "", "blank text: no row");
assert.equal(replyActionText({ role: "assistant", text: "Fehler", error: true }), "", "errors: no row");
assert.equal(replyActionText(null), "");
const chat = [
  { role: "user", text: "a" },
  { role: "assistant", text: "  **first**  " },
  { role: "user", text: "b" },
  { role: "assistant", text: "" },
  { role: "assistant", text: "## second\n\n- x" },
  { role: "user", text: "c" },
  { role: "assistant", text: "third, still going", streaming: true },
];
assert.deepEqual(replyRows(chat), [
  { index: 1, text: "**first**", last: false, held: false },
  { index: 4, text: "## second\n\n- x", last: false, held: true },
], "every finished reply; streaming holds the newest row");
const idleChat = [
  { role: "user", text: "a" },
  { role: "assistant", text: "  **first**  " },
  { role: "user", text: "b" },
  { role: "assistant", text: "## second\n\n- x" },
];
assert.deepEqual(replyRows(idleChat), [
  { index: 1, text: "**first**", last: false, held: false },
  { index: 3, text: "## second\n\n- x", last: true, held: false },
], "idle: newest finished reply is last");
assert.deepEqual(replyRows(chat, { busy: true }), [
  { index: 1, text: "**first**", last: false, held: false },
  { index: 4, text: "## second\n\n- x", last: false, held: true },
], "busy: newest row held while the turn runs");
assert.deepEqual(
  replyRows([{ role: "assistant", text: "only" }]).map((row) => row.last),
  [true],
);

// --- source wiring ---
assert.match(chatSrc, /await import\(\s*`\.\/reply_meta\.js\$\{CACHE\}`/);
assert.doesNotMatch(chatSrc, /transcriptText/, "whole-chat copy is gone");
assert.doesNotMatch(chatSrc, /copy_chat/);
assert.doesNotMatch(chatSrc, /copy_last_reply|copy-chat/, "the bottom row no longer copies: each reply has its own button");
assert.match(chatSrc, /const rows = replyRows\(entries, \{ busy: streaming \|\| liveStream \}\)/);
assert.match(chatSrc, /row\.classList\.toggle\("is-held", info\.held\)/);
assert.match(chatSrc, /bubble\._replyFresh/);
assert.match(chatSrc, /replyActionButton\("copy", "mdi:content-copy", t\("copy_reply"\)\)/);
assert.match(chatSrc, /replyActionButton\("speak", "mdi:volume-high", t\("speak_reply"\)\)/);
assert.match(chatSrc, /btn\.setAttribute\("aria-label", label\)/, "buttons carry an aria-label");
assert.match(chatSrc, /row\.setAttribute\("role", "group"\)/);
assert.match(chatSrc, /row\.setAttribute\("aria-label", t\("reply_actions"\)\)/);
assert.match(chatSrc, /if \(speakBtn\) speakBtn\.hidden = !voice\.tts;/, "speaker hidden without TTS");
assert.match(chatSrc, /row\.classList\.toggle\("is-last", info\.last\)/);
// One delegated listener for all rows, none per message.
assert.match(chatSrc, /logEl\.addEventListener\("click", onReplyAction\)/);
const rowFn = chatSrc.match(/function syncReplyRows\(entries\) \{([\s\S]*?)\n  \}\n/)?.[1] || "";
assert.ok(rowFn, "syncReplyRows found");
assert.doesNotMatch(rowFn, /addEventListener/, "no listener per reply row");
const onAction = chatSrc.match(/async function onReplyAction\(event\) \{([\s\S]*?)\n  \}\n/)?.[1] || "";
assert.match(onAction, /await copyText\(text\)/);
assert.match(onAction, /if \(speakTarget === bubble\) \{\s*const state = speechState\(\);/, "same reply: its state decides");
assert.match(onAction, /state === "paused"\) \{\s*await resumeSpeech\(\);/, "same reply paused by the user: play");
assert.match(onAction, /state === "playing"\) \{\s*haltSpeech\(\);/, "same reply playing: stop");
assert.match(onAction, /await speakReply\(text, true, bubble\)/, "other reply: read that one");
// The copied/read text is the reply markdown only (no tool chips, status, "reply cut" note).
assert.match(chatSrc, /function replyTextOf\(bubble\) \{\s*const md = bubble\?\.querySelector\("ha-markdown\.text"\);/);
// Read-aloud: one reply at a time, the button shows stop while its reply plays.
assert.match(chatSrc, /function speakReply\(text, fromUser = false, target = null\) \{[\s\S]{0,200}haltSpeech\(\);\s*\/\/[^\n]*\n\s*speakTarget = target \|\| lastAssistantBubble\(\);\s*speakAuto = false;/);
assert.match(chatSrc, /const gen = speakGen;\s*if \(fromUser\) await unlockOutput\(\);\s*\/\/[^\n]*\n\s*if \(gen !== speakGen\) return;/, "a newer click wins");
assert.match(chatSrc, /if \(target\) syncCopyChat\(\);/, "stop state shows at once");
assert.match(chatSrc, /function haltSpeech\(\) \{\s*speakGen \+= 1;\s*speakTarget = null;\s*speakAuto = false;\s*speakUserPaused = false;/);
assert.match(chatSrc, /next === "playing" \? "mdi:stop" : next === "paused" \? "mdi:play" : "mdi:volume-high"/);
assert.match(chatSrc, /t\(next === "playing" \? "stop_reading" : "speak_reply"\)/);
assert.match(chatSrc, /btn\.setAttribute\("aria-pressed", mine \? "true" : "false"\)/);
assert.match(chatSrc, /if \(!voice\.speak \|\| !delta \|\| \(speakTarget && !speakAuto\)\) return;/, "auto read-aloud does not cut in");
// One control: no chat-level speaker any more; auto read-aloud targets the live reply's row.
assert.doesNotMatch(chatSrc, /speak-chat/, "no stray chat-level speaker");
assert.doesNotMatch(cssStandard, /speak-chat/);
assert.doesNotMatch(chatSrc, /const showSpeak\b/);
assert.match(chatSrc, /if \(taken\.pieces\.length && \(!speakTarget \|\| speakAuto\)\) \{[\s\S]{0,200}speakTarget = live;\s*speakAuto = true;/);
assert.match(chatSrc, /!speakAuto && !keep\.has\(replyRowOf\(speakTarget\)\)/, "auto target survives while streaming");
// The state resets when nothing plays: error, blocked play(), browser pause, page left.
assert.match(chatSrc, /addEventListener\("error", \(\) => \{[\s\S]{0,160}if \(ownClip\(\)\) haltSpeech\(\);/);
assert.match(chatSrc, /replyAudio\.play\(\)\.catch\(\(err\) => \{[\s\S]{0,500}done\(\);\s*haltSpeech\(\);/);
assert.match(chatSrc, /if \(document\.hidden\) \{\s*\/\/[^\n]*\n\s*haltSpeech\(\);/, "pause while hidden is the browser's");
assert.match(chatSrc, /listen\(document, "visibilitychange", onSpeakVisibility\);/);
assert.match(chatSrc, /listen\(window, "pagehide", \(\) => \{\s*if \(speechLive\(\)\) haltSpeech\(\);/);
assert.match(chatSrc, /addEventListener\("emptied"/);
assert.match(chatSrc, /userPaused: speakUserPaused,\s*\}\);/, "watchdog: browser pause is a stall");
assert.match(chatSrc, /timeEl\.className = "reply-time"/);
assert.match(chatSrc, /timeEl\.title = replyTimeTitle\(/);
assert.match(chatSrc, /createdAt: bubble\.dataset\.createdAt/);
// Live replies get their time (and row) when they finish; older parts of the chat too.
const stamps = chatSrc.match(/stampReply\((assistant|live)\)/g) || [];
assert.ok(stamps.length >= 4, `streamed replies are stamped (${stamps.length})`);
assert.match(
  chatSrc,
  /name === "done"\) \{[\s\S]{0,900}assistant\.classList\.remove\("streaming"\);\s*stampReply\(assistant\);/,
);
assert.match(chatSrc, /function stampReply\(bubble\) \{[\s\S]{0,400}requestAnimationFrame\(\(\) => \{\s*replyRowsQueued = false;\s*syncCopyChat\(\);/);
assert.ok((chatSrc.match(/settleTools\(logEl\);\s*(?:\/\/[^\n]*\n\s*)?syncCopyChat\(\);/g) || []).length >= 3, "rows after every paint");
// The status line stays above the reply row.
assert.match(chatSrc, /if \(el\.nextElementSibling !== row\) bubble\.insertBefore\(el, row\);/);

// Every language has the strings, German as asked.
const langs = (i18nSrc.match(/^ {2}(?:"[\w-]+"|\w+): \{$/gm) || []).length;
assert.ok(langs >= 10);
for (const key of ["copy_reply", "stop_reading", "reply_actions", "speak_reply", "copied"]) {
  assert.equal((i18nSrc.match(new RegExp(`^ {4}${key}: "[^"]+"`, "gm")) || []).length, langs, key);
}
assert.equal((i18nSrc.match(/^ {4}copy_last_reply: "/gm) || []).length, 0, "old key gone");
assert.equal((i18nSrc.match(/^ {4}reply_yesterday: "[^"]*\{time\}[^"]*"/gm) || []).length, langs);
assert.match(i18nSrc, /copy_reply: "Antwort kopieren"/);
assert.match(i18nSrc, /stop_reading: "Vorlesen stoppen"/);
assert.match(i18nSrc, /reply_yesterday: "gestern, \{time\}"/);

// One message template (HA components only swap the composer): subtle row, full on
// hover/focus, always on touch; time right-aligned, muted, small, no wrap; older replies
// show it on hover/focus.
for (const css of [cssStandard]) {
  const row = css.match(/\n\.reply-actions \{([^}]*)\}/)?.[1] || "";
  assert.match(row, /display: flex/);
  assert.match(row, /opacity: 0\.6/);
  assert.match(css, /\.reply-actions:focus-within \{\s*opacity: 1;/);
  assert.match(css, /@media \(hover: none\) \{\s*\.reply-actions \{\s*opacity: 1;/);
  assert.match(css, /\.reply-actions \[hidden\] \{\s*display: none !important;/);
  const rule = css.match(/\.reply-actions \.reply-time \{([^}]*)\}/)?.[1] || "";
  assert.match(rule, /margin-inline-start: auto/);
  assert.match(rule, /white-space: nowrap/);
  assert.match(rule, /text-overflow: ellipsis/);
  assert.match(rule, /color: var\(--secondary-text-color\)/);
  assert.match(rule, /font-size: var\(--ha-font-size-s/);
  assert.match(css, /\.reply-actions:not\(\.is-last\) \.reply-time \{\s*opacity: 0;/);
  assert.match(css, /\.reply-actions:focus-within \.reply-time \{\s*opacity: 1;/);
  assert.match(css, /\.reply-actions\.is-held \{/);
  assert.match(css, /\.reply-actions\.is-fresh \{/);
  assert.match(css, /@keyframes reply-actions-in/);
  assert.doesNotMatch(css, /copy-chat|\.chat-actions \.reply-time/);
}
// The row always lives inside the reply bubble: no second (HA) host for it.
assert.match(chatSrc, /return bubble \? bubble\.querySelector\(":scope > \.reply-actions"\) : null;/);
assert.doesNotMatch(chatSrc, /message-container|replyRowHost/);

console.log("reply meta ok");
