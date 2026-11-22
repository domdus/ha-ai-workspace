// The Tasks page ("Aufgaben"): agent prompts that run as Home Assistant automations.
//
// Saving and deleting go through Home Assistant's automation config API
// (config/automation/config/<id>), the automation editor's own path. AI Workspace only builds the
// config (/api/ai_workspace/tasks/build), lists the automations with its label, and adds the label.
const CACHE = new URL(import.meta.url).search;
const { taskStrings } = await import(`./tasks_i18n.js${CACHE}`);

const API = "/api/ai_workspace/tasks";
const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

function weekdayNames(lang) {
  // 2024-01-01 was a Monday.
  const format = new Intl.DateTimeFormat(lang || undefined, { weekday: "short" });
  return Object.fromEntries(WEEKDAYS.map((day, i) => [day, format.format(new Date(Date.UTC(2024, 0, 1 + i, 12)))]));
}

export function scheduleText(schedule, s, days) {
  const kind = schedule?.kind || "custom";
  if (kind === "daily") return s.daily_at.replace("{time}", schedule.time || "");
  if (kind === "weekly") {
    const names = (schedule.weekdays || []).map((day) => days[day] || day).join(", ");
    return s.days_at.replace("{days}", names).replace("{time}", schedule.time || "");
  }
  if (kind === "interval") return (schedule.unit === "minutes" ? s.every_min : s.every_h).replace("{n}", String(schedule.every || ""));
  return s.sched_custom;
}

/** Heading of the task form: editing an existing task or creating a new one. */
export function formHeading(row, s) {
  return row ? s.task_edit_title : s.tasks_new;
}

/** Index of the task with this automation id in the list, or -1. */
export function taskIndexById(tasks, id) {
  if (!id) return -1;
  return (tasks || []).findIndex((row) => row?.id === id);
}

/**
 * Where the one task form goes: "top" for a new task, "card" inside the edited task's card,
 * or "closed" when the edited task is gone (deleted elsewhere, or no longer editable here).
 */
export function formPlace(editing, tasks) {
  if (editing === undefined || editing === false) return "closed";
  if (!editing) return "top";
  const row = (tasks || [])[taskIndexById(tasks, editing.id)];
  return row?.editable ? "card" : "closed";
}

/**
 * mountTasksPage(el, { hass, lang, apiFetch, openPath, openChat })
 * Returns { load, el }.
 */
export function mountTasksPage(el, options) {
  const s = taskStrings(options.lang);
  const days = weekdayNames(options.lang);
  const hass = () => options.hass();
  let state = { tasks: [], agents: [], notify: [] };
  // undefined: no form open; null: the "new task" form at the top; a row: that task's card is the form.
  let editing = undefined;
  let highlightTimer = 0;

  el.innerHTML = `
    <div class="tasks-bar"><h1>${esc(s.tasks)}</h1></div>
    <div class="tasks-body">
      <p class="tasks-intro">${esc(s.tasks_intro)}</p>
      <div class="tasks-actions"><button type="button" class="tasks-btn primary tasks-new">${esc(s.tasks_new)}</button></div>
      <p class="tasks-note" role="status" hidden></p>
      <div class="tasks-form-slot"></div>
      <div class="tasks-list" role="list"></div>
    </div>`;
  const listEl = el.querySelector(".tasks-list");
  const slotEl = el.querySelector(".tasks-form-slot");
  const newBtn = el.querySelector(".tasks-new");
  const actionsEl = el.querySelector(".tasks-actions");
  const noteEl = el.querySelector(".tasks-note");
  // One form for the whole page; it moves to the top (new task) or into the edited task's card.
  const formEl = document.createElement("form");
  formEl.className = "tasks-form";
  formEl.hidden = true;
  formEl.setAttribute("aria-labelledby", "ai-task-form-title");
  const reducedMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  const isOpen = () => editing !== undefined;
  const cardById = (id) => {
    const i = taskIndexById(state.tasks, id);
    return i < 0 ? null : listEl.querySelector(`.task-card[data-i="${i}"]`);
  };

  function note(text, bad = false) {
    noteEl.hidden = !text;
    noteEl.textContent = text || "";
    noteEl.classList.toggle("bad", Boolean(bad));
  }

  async function load() {
    const response = await options.apiFetch(API, { headers: { Accept: "application/json" } });
    if (!response?.ok) {
      note(s.load_failed, true);
      return;
    }
    state = await response.json();
    renderList();
  }

  function statusText(row) {
    if (!row.last_status) return s.never_run;
    const label = s[`status_${row.last_status}`] || row.last_status;
    const when = row.last_run ? new Date(row.last_run * 1000).toLocaleString(options.lang || undefined, { dateStyle: "short", timeStyle: "short" }) : "";
    return `${label}${when ? ` · ${when}` : ""}`;
  }

  function renderList() {
    // Re-rendering replaces the cards; the form node survives and goes back where it was.
    if (formEl.parentNode && formEl.parentNode !== slotEl) formEl.remove();
    if (!state.tasks.length) {
      listEl.innerHTML = `<p class="tasks-empty">${esc(s.tasks_empty)}</p>`;
    } else {
      listEl.innerHTML = renderCards();
    }
    placeForm();
  }

  function renderCards() {
    return state.tasks
      .map((row, i) => {
        const bad = row.last_status && row.last_status !== "ok" && row.last_status !== "running";
        return `
        <div class="task-card" role="listitem" data-i="${i}">
          <div class="task-view">
          <div class="task-head">
            <label class="task-toggle" title="${esc(row.enabled ? s.enabled : s.paused)}">
              <input type="checkbox" class="task-enabled" ${row.enabled ? "checked" : ""} ${row.available ? "" : "disabled"}>
              <span>${esc(row.enabled ? s.enabled : s.paused)}</span>
            </label>
            <strong class="task-name">${esc(row.name)}</strong>
          </div>
          <div class="task-meta">
            <span>${esc(scheduleText(row.schedule, s, days))}</span>
            <span class="task-status ${bad ? "bad" : ""}" title="${esc(row.last_error || "")}">${esc(s.last_run)}: ${esc(statusText(row))}</span>
          </div>
          ${row.editable ? "" : `<p class="task-hint">${esc(s.not_parsable)}</p>`}
          ${row.last_error && bad ? `<p class="task-hint bad">${esc(row.last_error)}</p>` : ""}
          <div class="task-buttons">
            <button type="button" class="tasks-btn task-run" ${row.has_task ? "" : "disabled"}>${esc(s.run_now)}</button>
            ${row.chat_id ? `<button type="button" class="tasks-btn task-chat">${esc(s.open_chat)}</button>` : ""}
            ${row.editable ? `<button type="button" class="tasks-btn task-edit">${esc(s.edit)}</button>` : ""}
            <button type="button" class="tasks-btn task-editor">${esc(s.open_editor)}</button>
            <button type="button" class="tasks-btn danger task-delete">${esc(s.delete)}</button>
          </div>
          </div>
        </div>`;
      })
      .join("");
  }

  // Puts the form where `editing` says: top slot, inside the edited card (its view hidden), or closed.
  function placeForm() {
    const place = formPlace(editing, state.tasks);
    listEl.querySelectorAll(".task-card.editing").forEach((card) => {
      card.classList.remove("editing");
      card.querySelector(".task-view").hidden = false;
    });
    if (place === "closed") {
      editing = undefined;
      formEl.hidden = true;
      formEl.remove();
    } else if (place === "top") {
      slotEl.append(formEl);
      formEl.hidden = false;
    } else {
      editing = state.tasks[taskIndexById(state.tasks, editing.id)];
      const card = cardById(editing.id);
      card.classList.add("editing");
      card.querySelector(".task-view").hidden = true;
      card.append(formEl);
      formEl.hidden = false;
    }
    actionsEl.hidden = isOpen();
  }

  function option(value, label, current) {
    return `<option value="${esc(value)}" ${String(current ?? "") === String(value) ? "selected" : ""}>${esc(label)}</option>`;
  }

  function openForm(row = null) {
    // Only one form: opening another edit (or a new task) drops the one that is open.
    note("");
    editing = row;
    const sched = row?.schedule?.kind ? row.schedule : { kind: "daily", time: "07:00" };
    const target = row?.target || "chat";
    const kind = sched.kind;
    formEl.innerHTML = `
      <h2 class="tasks-form-title" id="ai-task-form-title">${esc(formHeading(row, s))}</h2>
      <p class="tasks-form-note bad" role="alert" hidden></p>
      <label>${esc(s.task_name)}<input name="name" required maxlength="120" value="${esc(row?.task_name || row?.name || "")}"></label>
      <label>${esc(s.task_prompt)}<textarea name="prompt" rows="6" required>${esc(row?.prompt || "")}</textarea>
        <small>${esc(s.task_prompt_hint)}</small></label>
      <fieldset class="task-schedule"><legend>${esc(s.task_schedule)}</legend>
        <select name="kind">
          ${option("daily", s.sched_daily, kind)}${option("weekly", s.sched_weekly, kind)}${option("interval", s.sched_interval, kind)}${option("custom", s.sched_custom, kind)}
        </select>
        <label class="sched-time">${esc(s.task_time)}<input type="time" name="time" value="${esc(sched.time || "07:00")}"></label>
        <div class="sched-days">${WEEKDAYS.map((day) => `<label><input type="checkbox" name="day" value="${day}" ${(sched.weekdays || []).includes(day) ? "checked" : ""}>${esc(days[day])}</label>`).join("")}</div>
        <label class="sched-every">${esc(s.task_every)}<input type="number" name="every" min="1" max="59" value="${esc(sched.every || 1)}">
          <select name="unit">${option("minutes", s.unit_minutes, sched.unit)}${option("hours", s.unit_hours, sched.unit || "hours")}</select></label>
      </fieldset>
      <label>${esc(s.task_agent)}<select name="agent">${option("", s.task_agent_default, row?.agent || "")}${state.agents.map((agent) => option(agent.id, agent.label, row?.agent || "")).join("")}</select></label>
      <label>${esc(s.task_target)}<select name="target">${option("chat", s.target_chat, target)}${option("push", s.target_push, target)}${option("both", s.target_both, target)}</select></label>
      <label class="task-notify">${esc(s.task_notify)}<input name="notify" list="ai-task-notify" value="${esc(row?.notify || "")}">
        <datalist id="ai-task-notify">${state.notify.map((item) => `<option value="${esc(item.id)}">${esc(item.label)}</option>`).join("")}</datalist></label>
      <label class="task-check"><input type="checkbox" name="allow_changes" ${row?.allow_changes ? "checked" : ""}>${esc(s.task_allow_changes)}</label>
      <small>${esc(s.task_allow_changes_hint)}</small>
      <div class="task-buttons">
        <button type="submit" class="tasks-btn primary task-save">${esc(s.save)}</button>
        <button type="button" class="tasks-btn task-save-editor">${esc(s.save_open_editor)}</button>
        <button type="button" class="tasks-btn task-cancel">${esc(s.cancel)}</button>
      </div>`;
    placeForm();
    syncForm();
    formEl.scrollIntoView?.({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    formEl.querySelector("input[name=name]")?.focus({ preventScroll: true });
  }

  // Closes the form and restores the card. With refocus, focus goes back to where the form came from.
  function closeForm(refocus = false) {
    const id = editing?.id;
    editing = undefined;
    placeForm();
    if (!refocus) return;
    const target = id ? cardById(id)?.querySelector(".task-edit") : newBtn;
    target?.focus();
  }

  function formError(text) {
    const box = formEl.querySelector(".tasks-form-note");
    if (!box) return note(text, true);
    box.hidden = !text;
    box.textContent = text || "";
  }

  function highlight(id) {
    const card = cardById(id);
    if (!card) return;
    card.scrollIntoView?.({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    listEl.querySelectorAll(".task-card.task-saved").forEach((other) => other.classList.remove("task-saved"));
    card.classList.add("task-saved");
    window.clearTimeout(highlightTimer);
    highlightTimer = window.setTimeout(() => card.classList.remove("task-saved"), 2000);
    card.querySelector(".task-edit, .task-run")?.focus({ preventScroll: true });
  }

  function syncForm() {
    const kind = formEl.querySelector("select[name=kind]")?.value;
    formEl.querySelector(".sched-time").hidden = !(kind === "daily" || kind === "weekly");
    formEl.querySelector(".sched-days").hidden = kind !== "weekly";
    formEl.querySelector(".sched-every").hidden = kind !== "interval";
    formEl.querySelector(".task-notify").hidden = formEl.querySelector("select[name=target]")?.value === "chat";
  }

  function readForm() {
    const value = (name) => formEl.querySelector(`[name=${name}]`)?.value ?? "";
    const kind = value("kind");
    const schedule = { kind };
    if (kind === "daily" || kind === "weekly") schedule.time = value("time");
    if (kind === "weekly") schedule.weekdays = [...formEl.querySelectorAll("input[name=day]:checked")].map((box) => box.value);
    if (kind === "interval") Object.assign(schedule, { every: Number(value("every")), unit: value("unit") });
    if (kind === "custom" && !editing) Object.assign(schedule, { kind: "daily", time: value("time") || "07:00" });
    return {
      name: value("name").trim(),
      prompt: value("prompt").trim(),
      schedule,
      agent: value("agent"),
      target: value("target"),
      notify: value("notify").trim(),
      allow_changes: Boolean(formEl.querySelector("input[name=allow_changes]")?.checked),
    };
  }

  let saving = false;

  async function save(openEditor = false) {
    if (saving) return;
    saving = true;
    formEl.querySelectorAll(".task-buttons button").forEach((btn) => (btn.disabled = true));
    try {
      await saveNow(openEditor);
    } finally {
      saving = false;
      formEl.querySelectorAll(".task-buttons button").forEach((btn) => (btn.disabled = false));
    }
  }

  async function saveNow(openEditor) {
    note("");
    formError("");
    const form = readForm();
    // "Advanced": save what the page can, then the automation editor takes over.
    const wantsEditor = openEditor || formEl.querySelector("select[name=kind]")?.value === "custom";
    if (form.schedule.kind === "custom" && editing) form.schedule = { kind: "custom" };
    const built = await options.apiFetch(`${API}/build`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: editing?.id || "", form }),
    });
    const body = built ? await built.json().catch(() => ({})) : {};
    if (!built?.ok) {
      formError(body.error || s.load_failed);
      return;
    }
    try {
      // The automation editor's own save: validates, writes automations.yaml, reloads this automation.
      await hass().callApi("POST", `config/automation/config/${encodeURIComponent(body.id)}`, body.config);
    } catch (err) {
      formError(err?.body?.message || err?.message || String(err));
      return;
    }
    await options.apiFetch(`${API}/${encodeURIComponent(body.id)}/label`, { method: "POST" });
    closeForm();
    note(s.saved);
    if (wantsEditor) {
      options.openPath(`/config/automation/edit/${encodeURIComponent(body.id)}`);
      return;
    }
    await load();
    highlight(body.id);
  }

  formEl.addEventListener("change", syncForm);
  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    save(false);
  });
  formEl.addEventListener("click", (event) => {
    if (event.target.closest(".task-cancel")) {
      closeForm(true);
    } else if (event.target.closest(".task-save-editor")) {
      if (formEl.reportValidity()) save(true);
    }
  });
  formEl.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !event.defaultPrevented) {
      event.preventDefault();
      closeForm(true);
    }
  });
  newBtn.addEventListener("click", () => openForm(null));

  listEl.addEventListener("change", async (event) => {
    if (event.target.closest(".tasks-form")) return;
    const box = event.target.closest(".task-enabled");
    if (!box) return;
    const row = state.tasks[Number(box.closest(".task-card")?.dataset.i)];
    if (!row) return;
    await hass().callService("automation", box.checked ? "turn_on" : "turn_off", { entity_id: row.entity_id });
    window.setTimeout(load, 400);
  });

  listEl.addEventListener("click", async (event) => {
    if (event.target.closest(".tasks-form")) return;
    const card = event.target.closest(".task-card");
    const row = card ? state.tasks[Number(card.dataset.i)] : null;
    if (!row) return;
    if (event.target.closest(".task-run")) {
      // Runs the automation's actions now; the agent task runs in the background.
      await hass().callService("automation", "trigger", { entity_id: row.entity_id, skip_condition: true });
      note(s.run_started);
      window.setTimeout(load, 1500);
    } else if (event.target.closest(".task-chat")) {
      options.openChat(row.chat_id);
    } else if (event.target.closest(".task-edit")) {
      openForm(row);
    } else if (event.target.closest(".task-editor")) {
      options.openPath(`/config/automation/edit/${encodeURIComponent(row.id)}`);
    } else if (event.target.closest(".task-delete")) {
      if (!window.confirm(s.delete_confirm.replace("{name}", row.name))) return;
      try {
        await hass().callApi("DELETE", `config/automation/config/${encodeURIComponent(row.id)}`);
      } catch (err) {
        note(err?.body?.message || err?.message || String(err), true);
        return;
      }
      await load();
    }
  });

  return { load, el };
}
