/**
 * Reply meta in the chat action row: reply time label and "copy last reply".
 * Run: node tests/test_reply_meta.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  haHour12,
  haTimeZone,
  lastReply,
  parseReplyTime,
  replyTimeFor,
  replyTimeLabel,
  replyTimeTitle,
} from "../custom_components/ai_workspace/www/reply_meta.js";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const read = (name) => readFileSync(new URL(name, www), "utf8");
const chatSrc = read("chat.js");
const i18nSrc = read("i18n.js");
const cssStandard = read("chat.css");
const cssLayout = read("chat-layout.css");
const cssHa = read("chat-ha-components.css");

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

// --- copy last reply ---
assert.equal(lastReply([]), null);
assert.equal(lastReply(null), null);
assert.equal(lastReply([{ role: "user", text: "Hallo" }]), null, "no assistant reply: nothing to copy");
assert.equal(
  lastReply([
    { role: "user", text: "a" },
    { role: "assistant", text: "  **first**  " },
    { role: "user", text: "b" },
    { role: "assistant", text: "## second\n\n- x" },
  ]).text,
  "## second\n\n- x",
  "newest reply, markdown kept",
);
assert.equal(
  lastReply([
    { role: "assistant", text: "done before" },
    { role: "user", text: "next" },
    { role: "assistant", text: "", createdAt: "x" },
  ]).text,
  "done before",
  "a reply with only tool chips (no text) is skipped",
);
assert.equal(
  lastReply([
    { role: "assistant", text: "old" },
    { role: "assistant", text: "half", streaming: true },
  ]).text,
  "old",
  "a reply still streaming is not copied",
);
assert.equal(lastReply([{ role: "assistant", text: "  first  " }]).text, "first", "trimmed");

// --- which time is shown ---
assert.equal(replyTimeFor([]), "");
assert.equal(replyTimeFor([{ role: "assistant", createdAt: "t1" }]), "t1");
assert.equal(replyTimeFor([{ role: "assistant", createdAt: "t1" }, { role: "user", createdAt: "t2" }]), "", "never user times");
assert.equal(replyTimeFor([{ role: "assistant", createdAt: "t1", streaming: true }]), "", "shown once finished");

// --- source wiring ---
assert.match(chatSrc, /await import\(\s*`\.\/reply_meta\.js\$\{CACHE\}`/);
assert.doesNotMatch(chatSrc, /transcriptText/, "whole-chat copy is gone");
assert.doesNotMatch(chatSrc, /copy_chat/);
assert.match(chatSrc, /btn\.label = t\("copy_last_reply"\)/);
assert.match(chatSrc, /copyBtn\.disabled = !hasReply/);
assert.match(chatSrc, /await copyText\(reply\.text\)/);
assert.match(chatSrc, /timeEl\.className = "reply-time"/);
assert.match(chatSrc, /timeEl\.title = replyTimeTitle\(/);
assert.match(chatSrc, /createdAt: bubble\.dataset\.createdAt/);
// Live replies get their time when they finish.
const stamps = chatSrc.match(/stampReply\((assistant|live)\)/g) || [];
assert.ok(stamps.length >= 4, `streamed replies are stamped (${stamps.length})`);
assert.match(
  chatSrc,
  /name === "done"\) \{[\s\S]{0,900}assistant\.classList\.remove\("streaming"\);\s*stampReply\(assistant\);/,
);

// Every language has both strings, German as asked.
const langs = (i18nSrc.match(/^ {2}(?:"[\w-]+"|\w+): \{$/gm) || []).length;
assert.ok(langs >= 10);
assert.equal((i18nSrc.match(/^ {4}copy_last_reply: "/gm) || []).length, langs);
assert.equal((i18nSrc.match(/^ {4}reply_yesterday: "[^"]*\{time\}[^"]*"/gm) || []).length, langs);
assert.match(i18nSrc, /copy_last_reply: "Letzte Antwort kopieren"/);
assert.match(i18nSrc, /reply_yesterday: "gestern, \{time\}"/);

// Both themes: right-aligned, muted, small, no wrap.
for (const css of [cssStandard, cssLayout]) {
  const rule = css.match(/\.chat-actions \.reply-time \{([^}]*)\}/)?.[1] || "";
  assert.match(rule, /margin-inline-start: auto/);
  assert.match(rule, /white-space: nowrap/);
  assert.match(rule, /text-overflow: ellipsis/);
  assert.match(rule, /color: var\(--secondary-text-color\)/);
  assert.match(rule, /font-size: var\(--ha-font-size-s/);
  assert.match(css, /\.chat-actions \.reply-time\[hidden\]/);
}
assert.match(cssHa, /\.ui-theme-ha-components \.chat-actions \{[^}]*align-self: stretch/);

console.log("reply meta ok");
