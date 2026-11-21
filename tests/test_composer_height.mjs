/**
 * The prompt is one line unless its text needs more (wrap, newline, paste, Shift+Enter).
 * After send/clear it goes back to one line, Standard textarea and HA ha-textarea alike.
 * Run: node tests/test_composer_height.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const read = (name) => readFileSync(new URL(name, www), "utf8");
const chatSrc = read("chat.js");
const standardCss = read("chat.css");
const composerCss = read("chat-ha-composer.css");

const body = (name) => {
  const start = chatSrc.indexOf(`  function ${name}(`);
  assert.ok(start > 0, name);
  return chatSrc.slice(start, chatSrc.indexOf("\n  }\n", start));
};

// Both fields start as one row.
assert.match(chatSrc, /<textarea id="ai-message" class="message" rows="1"/);
assert.match(chatSrc, /<ha-textarea id="message-input" class="message" rows="1"/);

// Code never writes the prompt directly: setComposerText also updates ha-textarea's inner field,
// which otherwise still holds the sent text when the size is measured.
const writes = chatSrc.match(/messageEl\.value\s*\+?=(?!=)/g) || [];
assert.equal(writes.length, 1, "only setComposerText writes messageEl.value");
const setText = body("setComposerText");
assert.match(setText, /messageEl\.value = value;/);
assert.match(setText, /inner\.value = value/);

const resize = body("resizeComposer");
// Placeholder is set before measuring (it changes while a reply streams).
assert.ok(resize.indexOf('t("placeholder_next")') < resize.indexOf("syncFieldLines()"));
assert.ok(resize.indexOf('t("placeholder_next")') < resize.indexOf("scrollHeight"));
// Empty: one line, never scrollHeight (a wrapping placeholder would count).
assert.match(resize, /const scrollH = empty \? minH : messageEl\.scrollHeight;/);
assert.match(resize, /inner\.style\.height = `\$\{empty \? oneLineHeight\(inner\) : inner\.scrollHeight\}px`;/);

// An empty prompt drops the two-row layout before any measuring.
const lines = body("syncFieldLines");
assert.match(lines, /if \(!value\) \{\n\s+field\.classList\.remove\("multi"\);\n\s+return;/);
assert.match(lines, /value\.includes\("\\n"\)/);

// Clearing after send and queueing resizes.
for (const name of ["queueTurn", "restoreQueued", "switchComposer"]) {
  assert.match(body(name), /resizeComposer\(\);/, name);
}

// Long placeholders stay on one line.
assert.match(standardCss, /textarea\.message::placeholder \{\n\s+white-space: nowrap;/);
assert.match(composerCss, /ha-textarea::part\(wa-textarea\)::placeholder \{\n\s+white-space: nowrap;/);

// oneLineHeight: line + padding (+ borders for border-box).
const oneLine = new Function(`${body("oneLineHeight")}\n  }\nreturn oneLineHeight;`);
const style = { lineHeight: "24px", fontSize: "16px", paddingTop: "8px", paddingBottom: "4px",
  boxSizing: "content-box", borderTopWidth: "1px", borderBottomWidth: "1px" };
globalThis.getComputedStyle = () => style;
assert.equal(oneLine()({}), 36);
style.boxSizing = "border-box";
assert.equal(oneLine()({}), 38);
style.lineHeight = "normal";
assert.equal(oneLine()({}), Math.ceil(16 * 1.2 + 14));

// Bottom gap under the picker row stays small; ha-top-app-bar-fixed already adds the safe area.
const rule = (css, sel) => {
  const start = css.indexOf(`${sel} {`);
  assert.ok(start >= 0, sel);
  return css.slice(start, css.indexOf("}", start));
};
assert.match(rule(standardCss, "\n.composer"), /padding: var\(--ha-space-4\) var\(--ai-inline-pad\) var\(--ha-space-2\);/);
assert.match(rule(standardCss, "\n.agent-picker"), /margin: var\(--ha-space-1\) 0 0 var\(--ha-space-3\);/);
assert.match(rule(standardCss, "button.agent-trigger::before"), /inset: -4px 0;/);
assert.match(rule(composerCss, ".composer-ha .composer"), /padding: 0;/);
assert.match(rule(composerCss, ".composer-ha .agent-picker"), /margin: var\(--ha-space-1\) 0 var\(--ha-space-2\);/);
assert.doesNotMatch(standardCss + composerCss, /safe-area-inset-bottom/);

console.log("composer height ok");
