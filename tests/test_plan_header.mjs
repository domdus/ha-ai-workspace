/**
 * Chat header: plan % replaces $ only for an agent whose resolved billing is "plan" and only with a
 * snapshot of its own engine from exactly its own credential.
 * Run: node tests/test_plan_header.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../custom_components/ai_workspace/www/chat.js", import.meta.url), "utf8");
const grab = (name) => {
  const start = src.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, `${name} in chat.js`);
  const end = src.indexOf("\n  }\n", start);
  return src.slice(start, end + 4);
};
const planSnapForAgent = new Function(`${grab("planHasPercent")}\n${grab("planSnapForAgent")}\nreturn planSnapForAgent;`)();

const quota = {
  claude: { session_percent: 12, week_percent: 16, credential: "cRUNTIME" },
  codex: { session_percent: 40, week_percent: 5, credential: "cCODEX" },
};

// Runtime agent whose Runtime reports a Claude subscription: its snapshot.
const runtimePlan = { provider: "claude", billing: "plan", billing_source: "runtime", plan_credential: "cRUNTIME" };
assert.equal(planSnapForAgent(runtimePlan, quota), quota.claude);

// Runtime agent on an API key (env), or the Runtime unreachable: $ (no snapshot).
assert.equal(planSnapForAgent({ provider: "claude", billing: "api_key", plan_credential: "" }, quota), null);
assert.equal(planSnapForAgent({ provider: "claude", billing: "unknown", plan_credential: "" }, quota), null);
// Older backends sent "runtime" unresolved: never plan % on that.
assert.equal(planSnapForAgent({ provider: "claude", billing: "runtime" }, quota), null);

// An agent with its own Plan token never shows the Runtime sign-in's numbers, and the other way round.
assert.equal(planSnapForAgent({ provider: "claude", billing: "plan", plan_credential: "cOWN" }, quota), null);
// Another engine's plan data is never used.
assert.equal(planSnapForAgent({ provider: "claude", billing: "plan", plan_credential: "cCODEX" }, quota), null);
assert.equal(planSnapForAgent({ provider: "cursor", billing: "plan", plan_credential: "cRUNTIME" }, quota), null);
// Snapshots stored before 1.6.1b16 carry no credential: not attributed to anyone.
assert.equal(
  planSnapForAgent(runtimePlan, { claude: { session_percent: 3, week_percent: 4 } }),
  null,
);
// A matching snapshot without percentages: nothing to show.
assert.equal(planSnapForAgent(runtimePlan, { claude: { status: "allowed", credential: "cRUNTIME" } }), null);

console.log("test_plan_header: ok");
