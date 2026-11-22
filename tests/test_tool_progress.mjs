/**
 * MCP tool progress (notifications/progress) on the running tool step.
 * Run: node tests/test_tool_progress.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { progressChip, toolProgressText } from "../custom_components/ai_workspace/www/tool_progress.js";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const chatSrc = readFileSync(new URL("chat.js", www), "utf8");

// Text: the server's message first, else a percentage.
assert.equal(toolProgressText({ text: "Cloning  the repo\n" }), "Cloning the repo");
assert.equal(toolProgressText({ progress: 3, total: 4 }), "75%");
assert.equal(toolProgressText({ progress: 9, total: 4 }), "100%");
assert.equal(toolProgressText({ progress: 3 }), "");
assert.equal(toolProgressText({}), "");
assert.equal(toolProgressText({ text: "x".repeat(500) }).length, 160);

// Chip: by call id, then by tool name (also with an engine's server prefix), then the newest running one.
const chip = (tool, callId = "") => ({ dataset: { tool, callId } });
const a = chip("mcp__agent-worker__agent_run", "c1");
const b = chip("ha_get_state", "c2");
const c = chip("mcp");
assert.equal(progressChip([a, b], { id: "c2", name: "agent_run" }), b);
assert.equal(progressChip([a, b], { name: "agent_run" }), a);
assert.equal(progressChip([chip("worker.agent_run"), b], { name: "agent_run" }).dataset.tool, "worker.agent_run");
assert.equal(progressChip([a, c], { name: "something_else" }), c);
assert.equal(progressChip([], { name: "agent_run" }), null);

// The chat handles the event in both streams (send and follow) and clears it when the step ends.
assert.equal(chatSrc.match(/name === "tool_progress"/g)?.length, 2);
assert.match(chatSrc, /function settleChip[\s\S]*?\.chip-progress"\)\?\.remove\(\)/);
assert.match(chatSrc, /tool_progress\.js\$\{CACHE\}/);

console.log("tool progress ok");
