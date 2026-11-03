/**
 * cleanErrorText in chat.js matches error_text.py for stored chats and request failures.
 * Run: node tests/test_error_text.mjs
 */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../custom_components/ai_workspace/www/chat.js", import.meta.url), "utf8");
const grab = (name) => {
  const start = src.indexOf(name);
  let depth = 0;
  for (let i = src.indexOf("{", start); i < src.length; i++) {
    if (src[i] === "{") depth++;
    if (src[i] === "}" && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error(`missing ${name}`);
};
const clean = new Function(`${grab("function errorBodyMessage(")}\n${grab("function cleanErrorText(")}\nreturn cleanErrorText;`)();
const busy = "This model is currently experiencing high demand.";
let failed = 0;
const ok = (cond, label) => {
  if (!cond) failed++;
  console.log(`${cond ? "ok" : "FAIL"} ${label}`);
};
ok(clean(JSON.stringify([{ error: { code: 503, message: busy, status: "UNAVAILABLE" } }], null, 2)) === busy, "Gemini list body");
ok(clean(`Gemini API error 503: {"error": {"message": "${busy}"}}`) === busy, "prefixed body");
ok(clean("Timeout on reading data from socket").startsWith("The provider did not answer in time."), "socket timeout");
ok(clean("<html><h1>502 Bad Gateway</h1></html>") === "502 Bad Gateway", "HTML page");
ok(clean("Use [x](y) to fix it.") === "Use [x](y) to fix it.", "plain text with brackets stays");
ok(clean("") === "", "empty stays empty");
if (failed) {
  console.error(`${failed} failed`);
  process.exit(1);
}
