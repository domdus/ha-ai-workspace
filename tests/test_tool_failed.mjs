/**
 * Failed tool steps (MCP isError) and URL-mode elicitation links in the chat.
 * Run: node tests/test_tool_failed.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const chatSrc = readFileSync(new URL("chat.js", www), "utf8");
const cssSrc = readFileSync(new URL("chat.css", www), "utf8");

// markChipFailed: only a step whose end event says failed turns red, with the "Error" title.
const body = chatSrc.match(/function markChipFailed\(chip, event\) \{([\s\S]*?)\n  \}/);
assert.ok(body, "markChipFailed exists");
const markChipFailed = new Function("t", `return function (chip, event) {${body[1]}\n}`)((key) => `T:${key}`);
const chip = () => {
  const classes = new Set(["done"]);
  return { classList: { add: (name) => classes.add(name) }, classes, title: "" };
};
const bad = chip();
markChipFailed(bad, { phase: "end", failed: true });
assert.ok(bad.classes.has("failed"));
assert.equal(bad.title, "T:error");
const good = chip();
markChipFailed(good, { phase: "end" });
assert.ok(!good.classes.has("failed"));
markChipFailed(null, { failed: true });

// Both places that settle or draw a chip mark it.
assert.equal((chatSrc.match(/^\s+markChipFailed\((pending|chip), event\);$/gm) || []).length, 2);
assert.match(cssSrc, /\.tools-list span\.done\.failed/);

// URL mode: an http(s) link, opened in a new tab without opener, never javascript: or file:.
const link = chatSrc.match(/const link = !worker && (\/.+?\/i)\.test/);
assert.ok(link, "approval link guard exists");
const guard = new Function(`return ${link[1]};`)();
assert.ok(guard.test("https://example.com/a?b=1"));
assert.ok(!guard.test("javascript:alert(1)"));
assert.ok(!guard.test("file:///etc/passwd"));
assert.ok(!guard.test("https://a b"));
assert.match(chatSrc, /anchor\.rel = "noopener noreferrer"/);

console.log("tool failed + approval link: ok");
