# Agent tasks

An agent task is a prompt that an AI Workspace agent runs on its own, for example every morning. Tasks are ordinary Home Assistant automations: a trigger (usually a time) and the action **AI Workspace: Run agent task** (`ai_workspace.run_task`). AI Workspace has no scheduler of its own; Home Assistant runs the automation.

## The Tasks page

Open AI Workspace in the sidebar and choose the calendar icon (**Tasks**) at the top of the chat list, next to Activity and Usage. On a phone, open the chat list first. The page is for administrators only.

- **New task** asks for a name, the prompt, a schedule (daily, weekly, or every N minutes/hours), the agent, where the result goes (task chat, push message, or both), and **Allow changes**.
- **Save** creates or updates a real automation through Home Assistant's automation config API, the same one the automation editor uses, and gives it the **AI Workspace** label. The page lists exactly the automations with that label.
- An agent in chat builds an automation that sends a prompt to an AI Workspace agent as a task, with `ai_workspace.run_task`. Any new automation whose actions run `ai_workspace.run_task` gets the **AI Workspace** label automatically, for example one an agent writes in chat or one you save in the automation editor. If you remove the label from an existing task later, it stays off.
- **Advanced (automation editor)** saves the task and opens it in the automation editor, where you can add any trigger or condition.
- Each task shows whether it is on or paused (the automation's on/off switch), the last run and its result, and buttons for **Run now** (triggers the automation), **Open task chat**, **Open in automation editor**, and **Delete** (removes the automation after you confirm).

You can keep editing a task in the automation editor. The page shows what it understands (name, prompt, simple schedules) and keeps your extra triggers, conditions and steps when you save there again. A schedule it cannot show reads "Advanced (automation editor)"; edit that one in the editor.

## The action

```yaml
action: ai_workspace.run_task
data:
  task_name: Morning briefing   # task chat title, logs, last run
  prompt: >-
    Give me a short morning briefing ...
  agent: ""                     # agent id, title or conversation entity; empty = default agent (see below)
  chat: task                    # none (default) or task: one continuing chat per task
  notify: notify.mobile_app_my_phone   # optional: the result as a push message (plain text, task_name as title)
  allow_changes: false          # default: read-only
  timeout: 600                  # seconds, 10 to 7200
response_variable: result       # optional
```

With `response_variable` the automation waits and gets:

```yaml
status: ok            # ok, error, timeout or busy
response: "…"         # the agent's final answer in Markdown (or the error)
agent: OpenAI
chat_id: 3f2c…        # the task chat, or null
duration: 12.4        # seconds
usage: {prompt_tokens: 5400, completion_tokens: 310, total_tokens: 5710, cost_usd: 0.0123}
```

Without it the task runs in the background and the automation goes on at once.

**The result is only the final answer.** Status lines an agent writes before or between its tool calls ("Reading the weather data.") are left out of `response`, the push message and the task chat. The push message is plain text: phones do not render Markdown, so `**bold**`, `_italic_`, code marks, `#` headings and link syntax are removed, list items start with "• ", and a long answer is cut at a line or word boundary after about 1000 characters ("…"). The task chat and `response` keep the Markdown.

**Which agent runs it.** With **Fallback** off (the default, and also while the Fallback section was never saved) a task runs with exactly one agent and never switches: the named `agent`, else the **Default agent** (Settings → AI Workspace → Configure → Chat). If the Default agent is "Last used" (an automation has no browser that last picked one), the task takes the first signed-in Runtime agent in this order: Claude, Cursor, Codex; without one, the first agent that can take tasks. If that agent fails, the run ends with `status: error`. With Fallback on, the saved Fallback list decides: from the top, agents that are waiting out a limit or a backoff last; a named `agent` goes first and the rest of the list follows. When an agent fails on the provider side (plan or rate limit, expired sign-in, timeout, connection error, overloaded server), the next one takes over in the same run with the task and a journal of the tool calls already made, so device actions are not repeated; the failed agent waits like it does for chats. A failing tool, a refusal or a bad request never switches the agent. Tasks do not pause: if no agent is left, the run ends with `status: error`. The Home Assistant log shows the choice at the start of each run: `task <name>: agent <agent> (fallback on|off)`.

**Every run starts fresh.** The agent remembers nothing from earlier runs and cannot ask you anything, so the prompt has to say everything: what to check, how long the answer should be, and what counts as a problem. Only with `chat: task` does the agent see that task's earlier runs in its chat. Templates work in the prompt like in any action, for example `{{ now().strftime('%A') }}`.

### What a task may do

- **Allow changes off (default): read-only.** The agent only gets tools that read Home Assistant (states, history, logbook, the house map). Service calls, device control and every config write are refused. Unknown tools count as writes.
- **Allow changes on:** the agent may control devices and call services like in the chat.
- **Always, either way (loop protection):** a task can never start `ai_workspace.run_task`, trigger an automation, or create, edit or delete automations or scripts. Runtime agents (Claude, Cursor, Codex) also get no shell or file tools during a task. The same task never runs twice at once, and at most three tasks run at the same time.

Cloud agents apply these rules in their tool loop. Runtime agents apply them in the Runtime's MCP proxy, so the Runtime App must be 1.6.1b6 or newer; an older Runtime cannot take tasks (with Fallback on the list moves on to the next agent).

Task runs show on the **Usage** page like chat turns and are tagged as tasks. A reload of AI Workspace waits for running tasks the same way it waits for chat replies.

## Examples

### Morning briefing (weather, calendar, open windows)

```yaml
alias: Morning briefing
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: ai_workspace.run_task
    data:
      task_name: Morning briefing
      chat: task
      notify: notify.mobile_app_my_phone
      prompt: >-
        Write my morning briefing for today, {{ now().strftime('%A, %d %B') }}, in at most 6 short lines:
        1. Weather today from weather.home (high/low, rain).
        2. Today's events from calendar.family, with times.
        3. Any window or door that is open right now (binary_sensor with device class window or door).
        If something needs attention, put it first.
```

### Weekly report: failed automations and low batteries

```yaml
alias: Weekly house report
triggers:
  - trigger: time
    at: "18:00:00"
    weekday: sun
actions:
  - action: ai_workspace.run_task
    data:
      task_name: Weekly house report
      chat: task
      prompt: >-
        Weekly report for the last 7 days. Read only.
        1. Automations that ended with an error or did not run when they should have (check their traces/logbook).
           Name each one and the error.
        2. Every battery sensor below 20 %, lowest first.
        3. Entities that have been unavailable for more than a day.
        Compare with last week's report in this chat and say what is new or fixed. Keep it under 15 lines.
```

### Evening check: everything closed and off? (read-only)

```yaml
alias: Evening check
triggers:
  - trigger: time
    at: "22:30:00"
actions:
  - action: ai_workspace.run_task
    data:
      task_name: Evening check
      allow_changes: false
      prompt: >-
        It is late evening. Check, without changing anything: are all windows, doors and garage doors closed,
        all exterior doors locked, the oven, stove and iron off, and all lights outside the bedrooms off?
        Answer "All good" if everything is fine. Otherwise list only what is still open or on, one line each.
    response_variable: check
  - if: "{{ check.status == 'ok' and 'All good' not in check.response }}"
    then:
      - action: notify.mobile_app_my_phone
        data:
          title: Evening check
          message: "{{ check.response }}"
```
