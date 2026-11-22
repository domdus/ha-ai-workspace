/**
 * Tasks page: one form at a time, edited in the task's own card, with its own heading.
 * Run: node tests/test_tasks_page.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { formHeading, formPlace, scheduleText, taskIndexById } from "../custom_components/ai_workspace/www/tasks_page.js";
import { TASK_I18N, TASK_KEYS, TASK_VALUE_COUNTS, taskStrings } from "../custom_components/ai_workspace/www/tasks_i18n.js";

const www = new URL("../custom_components/ai_workspace/www/", import.meta.url);
const read = (name) => readFileSync(new URL(name, www), "utf8");

// --- strings: every language has every key, the edit heading included ---
for (const [lang, count] of Object.entries(TASK_VALUE_COUNTS)) {
  assert.equal(count, TASK_KEYS.length, `${lang}: value count`);
  assert.ok(TASK_I18N[lang].task_edit_title, `${lang}: task_edit_title`);
  assert.notEqual(TASK_I18N[lang].task_edit_title, TASK_I18N[lang].tasks_new, `${lang}: edit heading differs from new`);
}
const de = taskStrings("de");
assert.equal(de.task_edit_title, "Aufgabe bearbeiten");
assert.equal(de.tasks_new, "Neue Aufgabe");

// --- heading ---
assert.equal(formHeading(null, de), "Neue Aufgabe");
assert.equal(formHeading({ id: "a" }, de), "Aufgabe bearbeiten");

// --- lookup by automation id ---
const tasks = [
  { id: "a", editable: true },
  { id: "b", editable: false },
  { id: "c", editable: true },
];
assert.equal(taskIndexById(tasks, "c"), 2);
assert.equal(taskIndexById(tasks, "x"), -1);
assert.equal(taskIndexById(tasks, ""), -1);
assert.equal(taskIndexById(undefined, "a"), -1);

// --- where the one form goes ---
assert.equal(formPlace(undefined, tasks), "closed", "no form open");
assert.equal(formPlace(null, tasks), "top", "new task: top of the page");
assert.equal(formPlace({ id: "a" }, tasks), "card", "edit: inside the card");
assert.equal(formPlace({ id: "b" }, tasks), "closed", "not parsable any more: no form");
assert.equal(formPlace({ id: "gone" }, tasks), "closed", "deleted meanwhile: no form");
assert.equal(formPlace({ id: "a" }, []), "closed");

// --- schedule text unchanged ---
assert.equal(scheduleText({ kind: "daily", time: "07:00" }, de, {}), "Täglich um 07:00");
assert.equal(scheduleText({ kind: "custom" }, de, {}), de.sched_custom);

// --- page wiring (source checks; the page needs a DOM) ---
const page = read("tasks_page.js");
assert.match(page, /tasks-form-title/, "form has a heading");
assert.match(page, /aria-labelledby/, "form is labelled by its heading");
assert.match(page, /actionsEl\.hidden = isOpen\(\)/, "New task button hidden while a form is open");
assert.match(page, /\.task-edit"\) : newBtn/, "cancel returns focus to the card's Edit button");
assert.match(page, /prefers-reduced-motion: reduce/, "scrolling respects reduced motion");
assert.match(page, /row\.editable \? `<button type="button" class="tasks-btn task-edit">/, "no Edit button on rows the page cannot parse");
assert.match(page, /task-save-editor/, "save and open in automation editor stays");
const css = read("tasks.css");
assert.match(css, /\.task-card > \.tasks-form/, "form inside a card has no second card surface");
assert.match(css, /prefers-reduced-motion: no-preference[\s\S]*task-saved/, "saved highlight animates only without reduced motion");

console.log("tasks page: ok");
