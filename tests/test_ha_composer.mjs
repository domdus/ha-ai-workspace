/**
 * "Use HA Components" only swaps the composer (HA message field, agent and model pickers).
 * Messages, thinking line, reply row, notices and tool steps always use the Standard template.
 * Run: node tests/test_ha_composer.mjs
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const read = (name) => readFileSync(new URL(name, www), "utf8");
const chatSrc = read("chat.js");
const overlaySrc = read("overlay.js");
const standardCss = read("chat.css");
const composerCss = read("chat-ha-composer.css");

// The HA message template and its sheets are gone.
assert.equal(existsSync(new URL("chat-layout.css", www)), false);
assert.equal(existsSync(new URL("chat-ha-components.css", www)), false);
assert.doesNotMatch(chatSrc, /chat-layout\.css|chat-ha-components\.css|ui-theme-ha-components/);
assert.doesNotMatch(chatSrc, /message-container|replyRowHost|log messages|ha-scrollbar/);

// Off by default; the stored key and its values stay as they were.
assert.match(chatSrc, /let uiTheme = "standard";/);
assert.match(chatSrc, /export function haComponentsUi\(\) \{\n\s+return uiTheme === "ha_components";/);

// chat.css always loads; HA mode only adds the composer sheet on top.
assert.match(
  chatSrc,
  /const themeCss = `<link rel="stylesheet" href="\/ai_workspace\/static\/chat\.css\$\{CACHE\}">\$\{\n\s+haUi \? `<link rel="stylesheet" href="\/ai_workspace\/static\/chat-ha-composer\.css\$\{CACHE\}">` : ""\n\s+\}`;/,
);
// The wrap is always Standard; HA mode only marks the composer variant.
assert.match(chatSrc, /"wrap",\n\s+"ui-theme-standard",\n\s+haUi \? "composer-ha" : "",/);

// Mount markup outside the composer has no HA variant.
const mount = chatSrc.slice(chatSrc.indexOf("export async function mountAiWorkspace"), chatSrc.indexOf("const wrap = root.querySelector"));
const composerStart = mount.indexOf('<form class="composer">');
const composerEnd = mount.indexOf("</form>");
assert.ok(composerStart > 0 && composerEnd > composerStart);
const outsideComposer = mount.slice(mount.indexOf("root.innerHTML"), composerStart) + mount.slice(composerEnd);
assert.doesNotMatch(outsideComposer, /haUi/, "only the composer markup depends on the HA option");
assert.match(mount, /const bannerMarkup = `<p class="banner" hidden><\/p>`;/);
assert.match(mount, /<div class="log"><p class="empty">/);
// HA composer: HA text field labelled "Message", pickers inside the composer column.
assert.match(mount, /<ha-textarea id="message-input" class="message" rows="1" resize="auto" label="\$\{htmlAttr\(t\("message"\)\)\}"/);
const haComposer = mount.slice(mount.indexOf("${haUi ? `<${composerTag} class=\"composer-box\">"), mount.indexOf("` : `<${composerTag} class=\"composer-box\">"));
assert.match(haComposer, /\$\{haComposerInputMarkup\}[\s\S]*<div class="agent-picker" hidden>[\s\S]*agent-menu[\s\S]*model-menu/);
// Standard composer unchanged: Standard row, pickers under the box.
assert.match(mount, /` : `<\$\{composerTag\} class="composer-box">\n\s+<div class="next-row" hidden><\/div>\n\s+<div class="attach-row" hidden><\/div>\n\s+\$\{standardComposerRowMarkup\}\n\s+<\/\$\{composerTag\}>\n\s+<div class="agent-picker" hidden>/);

// Message renderers have one implementation, independent of the option.
const body = (name) => {
  const start = chatSrc.indexOf(`  function ${name}(`);
  assert.ok(start > 0, name);
  const end = chatSrc.indexOf("\n  }\n", start);
  return chatSrc.slice(start, end);
};
for (const name of [
  "addBubble",
  "addBubbleFiles",
  "ensureToolsChrome",
  "syncToolsSummary",
  "addChip",
  "settleChip",
  "activityGlyph",
  "fillActivitySlot",
  "syncActivityGlyph",
  "setActivity",
  "replyRowOf",
  "syncReplyRows",
  "markNotSent",
  "setBanner",
  "askText",
]) {
  assert.doesNotMatch(body(name), /haUi|haComponentsUi|composerCreate|ha-alert|ha-card|ha-assist-chip|ha-chip-set/, name);
}
// The thinking line always gets its glyph.
assert.match(body("fillActivitySlot"), /el\.replaceChildren\(activityGlyph\(\), label\);/);
// HA widgets are only built for composer parts (queued prompts, file chips).
const composerCreates = [...chatSrc.matchAll(/composerCreate\("([^"]+)"/g)].map((m) => m[1]).sort();
assert.deepEqual(composerCreates, ["ha-chip-set", "ha-input-chip", "ha-input-chip"]);
for (const name of ["renderNext", "renderThumbs"]) assert.match(body(name), /composerCreate\(/);

// The composer sheet only styles the composer, always under .composer-ha.
const rules = composerCss.replace(/\/\*[\s\S]*?\*\//g, "").replace(/@media[^{]+\{/g, "");
const selectors = [...rules.matchAll(/([^{}]+)\{[^{}]*\}/g)]
  .flatMap((m) => m[1].split(","))
  .map((s) => s.trim())
  .filter(Boolean);
assert.ok(selectors.length > 20);
for (const sel of selectors) {
  assert.match(sel, /^\.composer-ha /, sel);
  assert.doesNotMatch(sel, /\.bubble|\.log\b|\.reply-|\.activity|\.tools|header|\.title|\.banner|\.sessions|aside|\.empty/, sel);
}
// HA field look kept as before.
assert.match(composerCss, /\.composer-ha \.composer-field \{[^}]*box-shadow: inset 0 -1px 0/);
assert.match(composerCss, /\.composer-ha \.composer-field:focus-within \{\s*box-shadow: inset 0 -2px 0 var\(--primary-color\);/);
assert.match(composerCss, /\.composer-ha ha-button\.agent-trigger \{/);

// Standard composer chrome does not leak onto the HA pickers and buttons.
assert.match(standardCss, /\nbutton\.agent-trigger \{/);
assert.doesNotMatch(standardCss, /\n\.agent-trigger \{|\n\.agent-trigger:hover/);
assert.match(standardCss, /\nha-button\.send::part\(base\) \{/);
// Standard button sizes apply to the Standard row only; the HA field has its own (test_composer_layout.mjs).
assert.match(standardCss, /\n\.composer \.composer-actions > \.mic,/);
assert.match(composerCss, /\n\.composer-ha \.composer-field-actions > \.mic,/);
// Standard messages keep following the HA theme variables.
assert.match(standardCss, /\.ui-theme-standard \.bubble\.user \{/);
assert.match(standardCss, /var\(--primary-text-color\)/);

// The floating button no longer depends on the option.
assert.doesNotMatch(overlaySrc, /haComponentsUi|haUi|ha-button class="fab"/);

console.log("ha composer ok");
