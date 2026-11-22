/**
 * Mobile layout of the composer.
 * - The panel fits the visible viewport: HA sizes the page with html { height: 100vh }, which on
 *   mobile Chrome is the viewport with the address bar hidden, so the composer ended up below the screen.
 * - Attach, dictate and send have one size, also in the floating chat, whose app bar sizes every
 *   ha-icon-button 40px.
 * Run: node tests/test_composer_layout.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const read = (name) => readFileSync(new URL(name, www), "utf8");
const panelSrc = read("panel.js");
const overlaySrc = read("overlay.js");
const standardCss = read("chat.css");
const composerCss = read("chat-ha-composer.css");

// --- Bug: composer missing in the panel on mobile ---------------------------------------------

const cap = panelSrc.match(/const VIEWPORT_CAP = `([^`]*)`;/);
assert.ok(cap, "panel.js defines VIEWPORT_CAP");
const capCss = cap[1];
// dvh with a vh fallback before it (browsers without dvh keep the vh line).
const vhAt = capCss.search(/max-height: calc\(100vh\b/);
const dvhAt = capCss.search(/max-height: calc\(100dvh\b/);
assert.ok(vhAt >= 0, "vh fallback");
assert.ok(dvhAt > vhAt, "dvh after the vh fallback");
// The panel sits inside HA's safe-area padding.
for (const line of [capCss.slice(vhAt, dvhAt), capCss.slice(dvhAt)]) {
  assert.match(line, /var\(--safe-area-inset-top, 0px\)/);
  assert.match(line, /var\(--safe-area-inset-bottom, 0px\)/);
}
// Both host styles (before and after mount) carry the cap.
const hostBlocks = panelSrc.match(/:host \{[^}]*\}/g) || [];
assert.equal(hostBlocks.length, 2, "two :host blocks in panel.js");
for (const block of hostBlocks) {
  assert.match(block, /height: 100%;/);
  assert.match(block, /\$\{VIEWPORT_CAP\}/);
}
assert.doesNotMatch(panelSrc, /height: 100vh;/, "the panel never sizes itself by plain 100vh");

// The composer stays sticky at the bottom of the chat scroller.
const composerRule = standardCss.match(/\n\.composer \{[^}]*\}/)[0];
assert.match(composerRule, /position: sticky;/);
assert.match(composerRule, /bottom: 0;/);

// --- Bug: composer buttons in the floating chat ----------------------------------------------

// The floating chat's app bar rule reaches the composer (same shadow root): the composer rules
// must be more specific than it.
assert.match(overlaySrc, /\.bar ha-icon-button \{\s*--mdc-icon-button-size: 40px;\s*--ha-icon-button-size: 40px;/);

function ruleFor(css, selector) {
  const at = css.indexOf(selector);
  assert.ok(at >= 0, selector);
  return css.slice(at, css.indexOf("}", at) + 1);
}

const standardButtons = ruleFor(
  standardCss,
  ".composer .composer-actions > .attach,\n.composer .composer-actions > .mic,\n.composer .composer-actions > .send {",
);
const haButtons = ruleFor(
  composerCss,
  ".composer-ha .composer-field-actions > .attach,\n.composer-ha .composer-field-actions > .mic,\n.composer-ha .composer-field-actions > .send {",
);
for (const rule of [standardButtons, haButtons]) {
  for (const prop of ["width", "min-width", "height", "--ha-icon-button-size", "--mdc-icon-button-size", "--ha-button-height"]) {
    assert.match(rule, new RegExp(`\\n  ${prop}: var\\(--ai-composer-button\\);`), prop);
  }
  assert.match(rule, /flex: 0 0 var\(--ai-composer-button\);/);
  assert.match(rule, /align-items: center;/);
  assert.match(rule, /justify-content: center;/);
  assert.match(rule, /margin: 0;/);
}
assert.match(ruleFor(standardCss, "\n.composer {\n  --ai-composer-button"), /--ai-composer-button: 36px;/);
assert.match(ruleFor(composerCss, ".composer-ha .composer-field-actions {"), /--ai-composer-button: 40px;/);

// The Standard send button (ha-button) uses the same size.
assert.match(ruleFor(standardCss, "ha-button.send {"), /--ha-button-height: var\(--ai-composer-button, 36px\);/);
const sendBase = ruleFor(standardCss, "ha-button.send::part(base) {");
assert.match(sendBase, /width: var\(--ai-composer-button, 36px\);/);
assert.match(sendBase, /height: var\(--ai-composer-button, 36px\);/);

// Old per-button rules (mic and attach only, not the send button) are gone.
assert.doesNotMatch(standardCss, /:where\(\.wrap:not\(\.composer-ha\)\) \.(mic|attach)/);

// Same inset top, right and bottom around the buttons in the pill (and the HA fallback row).
const pill = ruleFor(standardCss, ".ui-theme-standard .composer-box {");
assert.match(pill, /padding: var\(--ai-composer-inset\) var\(--ai-composer-inset\) var\(--ai-composer-inset\) var\(--ha-space-4\);/);
assert.match(pill, /--ai-composer-inset: calc\(var\(--ha-space-1, 4px\) \* 1\.5\);/);
const fallback = ruleFor(composerCss, ".composer-ha .composer-fallback .composer-row {");
assert.match(fallback, /padding: var\(--ai-composer-inset\) var\(--ai-composer-inset\) var\(--ai-composer-inset\) var\(--ha-space-4\);/);

console.log("composer layout ok");
