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

/**
 * mountTasksPage(el, { hass, lang, apiFetch, openPath, openChat })
 * Returns { load, el }.
 */
export function mountTasksPage(el, options) {
  const s = taskStrings(options.lang);
  const days = weekdayNames(options.lang);
  const hass = () => options.hass();
  let state = { tasks: [], agents: [], notify: [] };
  let editing = null;

  el.innerHTML = `
    <div class="tasks-bar"><h1>${esc(s.tasks)}</h1></div>
    <div class="tasks-body">
      <p class="tasks-intro">${esc(s.tasks_intro)}</p>
      <div class="tasks-actions"><button type="button" class="tasks-btn primary tasks-new">${esc(s.tasks_new)}</button></div>
      <p class="tasks-note" role="status" hidden></p>
      <form class="tasks-form" hidden></form>
      <div class="tasks-list" role="list"></div>
    </div>`;
  const listEl = el.querySelector(".tasks-list");
  const formEl = el.querySelector(".tasks-form");
  const noteEl = el.querySelector(".tasks-note");

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
    if (!state.tasks.length) {
      listEl.innerHTML = `<p class="tasks-empty">${esc(s.tasks_empty)}</p>`;
      return;
    }
    listEl.innerHTML = state.tasks
      .map((row, i) => {
        const bad = row.last_status && row.last_status !== "ok" && row.last_status !== "running";
        return `
        <div class="task-card" role="listitem" data-i="${i}">
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
        </div>`;
      })
      .join("");
  }

  function option(value, label, current) {
    return `<option value="${esc(value)}" ${String(current ?? "") === String(value) ? "selected" : ""}>${esc(label)}</option>`;
  }

  function openForm(row = null) {
    editing = row;
    const sched = row?.schedule?.kind ? row.schedule : { kind: "daily", time: "07:00" };
    const target = row?.target || "chat";
    const kind = sched.kind;
    formEl.innerHTML = `
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
        <button type="submit" class="tasks-btn primary">${esc(s.save)}</button>
        <button type="button" class="tasks-btn task-save-editor">${esc(s.save_open_editor)}</button>
        <button type="button" class="tasks-btn task-cancel">${esc(s.cancel)}</button>
      </div>`;
    formEl.hidden = false;
    syncForm();
    formEl.querySelector("input[name=name]")?.focus();
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

  async function save(openEditor = false) {
    note("");
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
      note(body.error || s.load_failed, true);
      return;
    }
    try {
      // The automation editor's own save: validates, writes automations.yaml, reloads this automation.
      await hass().callApi("POST", `config/automation/config/${encodeURIComponent(body.id)}`, body.config);
    } catch (err) {
      note(err?.body?.message || err?.message || String(err), true);
      return;
    }
    await options.apiFetch(`${API}/${encodeURIComponent(body.id)}/label`, { method: "POST" });
    formEl.hidden = true;
    editing = null;
    note(s.saved);
    if (wantsEditor) {
      options.openPath(`/config/automation/edit/${encodeURIComponent(body.id)}`);
      return;
    }
    await load();
  }

  formEl.addEventListener("change", syncForm);
  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    save(false);
  });
  formEl.addEventListener("click", (event) => {
    if (event.target.closest(".task-cancel")) {
      formEl.hidden = true;
      editing = null;
    } else if (event.target.closest(".task-save-editor")) {
      if (formEl.reportValidity()) save(true);
    }
  });
  el.querySelector(".tasks-new").addEventListener("click", () => openForm(null));

  listEl.addEventListener("change", async (event) => {
    const box = event.target.closest(".task-enabled");
    if (!box) return;
    const row = state.tasks[Number(box.closest(".task-card")?.dataset.i)];
    if (!row) return;
    await hass().callService("automation", box.checked ? "turn_on" : "turn_off", { entity_id: row.entity_id });
    window.setTimeout(load, 400);
  });

  listEl.addEventListener("click", async (event) => {
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
