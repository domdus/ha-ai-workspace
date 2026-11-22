/**
 * Every chat and tasks-page string exists in every language AI Workspace ships, with the same
 * placeholders as English, and is not just an English copy.
 * Run: node tests/test_i18n_complete.mjs
 */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { I18N, stringsFor } from "../custom_components/ai_workspace/www/i18n.js";
import { TASK_I18N } from "../custom_components/ai_workspace/www/tasks_i18n.js";

const base = new URL("../custom_components/ai_workspace/", import.meta.url);
const SHIPPED = readdirSync(new URL("translations/", base))
  .filter((name) => name.endsWith(".json"))
  .map((name) => name.slice(0, -5))
  .sort();
const placeholders = (text) => (String(text).match(/\{[a-z_]+\}/g) || []).sort().join(",");
// Long English sentences that may stay English in another language (none so far).
const SAME_OK = new Set();

function checkTable(name, table) {
  assert.deepEqual(Object.keys(table).sort(), SHIPPED, `${name}: languages = translations/*.json`);
  const en = table.en;
  const keys = Object.keys(en);
  for (const [lang, strings] of Object.entries(table)) {
    const missing = keys.filter((key) => !(key in strings));
    const extra = Object.keys(strings).filter((key) => !(key in en));
    assert.deepEqual(missing, [], `${name}.${lang}: missing keys`);
    assert.deepEqual(extra, [], `${name}.${lang}: keys English does not have`);
    for (const key of keys) {
      assert.equal(typeof strings[key], "string", `${name}.${lang}.${key}: string`);
      if (en[key]) assert.ok(strings[key].trim(), `${name}.${lang}.${key}: empty`);
      assert.equal(placeholders(strings[key]), placeholders(en[key]), `${name}.${lang}.${key}: placeholders`);
    }
    if (lang === "en") continue;
    // A sentence of three or more words left in English is an untranslated copy.
    const copies = keys.filter(
      (key) => !SAME_OK.has(key) && strings[key] === en[key] && /[A-Za-z]{3,}\s+[A-Za-z]{3,}\s+[A-Za-z]{3,}/.test(en[key])
    );
    assert.deepEqual(copies, [], `${name}.${lang}: English copies`);
  }
}

checkTable("I18N", I18N);
checkTable("TASK_I18N", TASK_I18N);

// The approval card and plan limits read in German, not English.
const de = stringsFor("de");
assert.equal(de.approval_allow, "Erlauben");
assert.equal(stringsFor("fr").approval_title, "Autorisation requise");
assert.equal(stringsFor("zh-TW").approval_deny, "拒絕");
assert.notEqual(stringsFor("pl").usage_plan_heading, I18N.en.usage_plan_heading);

// Chat code takes its words from t()/strings, not from English literals in the DOM.
const www = new URL("www/", base);
const literal = /\.(textContent|placeholder|title|ariaLabel|label)\s*=\s*["'`][A-Za-z]/;
const setLabel = /setAttribute\("(aria-label|title|placeholder|label)",\s*["'`][A-Za-z]/;
const markup = /(aria-label|title|placeholder|label)="[A-Za-z]/;
for (const file of readdirSync(www).filter((name) => name.endsWith(".js") && !name.endsWith("i18n.js"))) {
  for (const [index, line] of readFileSync(new URL(file, www), "utf8").split("\n").entries()) {
    if (/^\s*(\/\/|\*)/.test(line)) continue;
    assert.ok(!literal.test(line) && !setLabel.test(line) && !markup.test(line), `${file}:${index + 1} hard-coded text: ${line.trim()}`);
  }
}

console.log("i18n complete:", SHIPPED.length, "languages,", Object.keys(I18N.en).length, "chat keys,", Object.keys(TASK_I18N.en).length, "task keys");
