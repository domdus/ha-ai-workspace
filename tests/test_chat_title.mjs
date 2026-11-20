/**
 * Header title in the chat (full panel and floating chat): "New chat" / "Neuer Chat" is only a
 * placeholder, and the header switches to the real title once it arrives.
 * Run: node tests/test_chat_title.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  PLACEHOLDER_TITLES,
  isPlaceholderTitle,
  headerTitle,
  realTitle,
} from "../custom_components/ai_workspace/www/chat_title.js";

const LINK = "https://www.heise.de/tests/DGX-Spark-Nvidias-Desktop-KI-Computer-im-Test-1110266";

for (const label of ["New Chat", "New chat", "Neuer Chat", "", "  ", null, undefined]) {
  assert.equal(isPlaceholderTitle(label), true, `placeholder: ${label}`);
  assert.equal(headerTitle(label, "Neuer Chat"), "Neuer Chat");
  assert.equal(realTitle(label, "Neuer Chat"), undefined);
}
assert.deepEqual([...PLACEHOLDER_TITLES], ["New Chat", "New chat", "Neuer Chat"]);
// The UI's own placeholder in another language counts too.
assert.equal(isPlaceholderTitle("Nouvelle discussion", "Nouvelle discussion"), true);

// A URL is a real title, not a reason to keep "Neuer Chat".
assert.equal(isPlaceholderTitle(LINK, "Neuer Chat"), false);
assert.equal(headerTitle(LINK, "Neuer Chat"), LINK);
assert.equal(realTitle(LINK, "New chat"), LINK);

// Header state in the floating chat: default first, then the title event replaces it.
function floatingHeader(placeholder) {
  let header = placeholder;
  return {
    get text() {
      return header;
    },
    onTitle(title) {
      header = headerTitle(title, placeholder);
    },
    needsServerTitle() {
      return isPlaceholderTitle(header, placeholder);
    },
  };
}
for (const placeholder of ["Neuer Chat", "New chat"]) {
  const header = floatingHeader(placeholder);
  assert.equal(header.needsServerTitle(), true);
  header.onTitle("New Chat");
  assert.equal(header.text, placeholder);
  header.onTitle(LINK);
  assert.equal(header.text, LINK);
  assert.equal(header.needsServerTitle(), false);
  // An async generated title arriving after the reply still replaces the first one.
  header.onTitle("DGX Spark im Test");
  assert.equal(header.text, "DGX Spark im Test");
}

const chatSrc = readFileSync(new URL("../custom_components/ai_workspace/www/chat.js", import.meta.url), "utf8");
assert.match(chatSrc, /await import\(`\.\/chat_title\.js\$\{CACHE\}`\)/);
assert.match(chatSrc, /return headerTitle\(title, t\("new_chat"\)\);/);
assert.doesNotMatch(chatSrc, /\["New Chat", "New chat", "Neuer Chat"\]\.includes/);

console.log("test_chat_title: ok");
