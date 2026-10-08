const logEl = document.querySelector("#log");
const sessionsEl = document.querySelector("#sessions");
const titleEl = document.querySelector("#title");
const statusEl = document.querySelector("#status");
const bannerEl = document.querySelector("#banner");
const form = document.querySelector("#composer");
const messageEl = document.querySelector("#message");
const sendBtn = document.querySelector("#send");

let sessionId = location.hash.replace("#", "");
let streaming = false;

function api(path) {
  return new URL(path, window.location.href).toString();
}

function setStatus(text) {
  if (!text) {
    statusEl.hidden = true;
    statusEl.textContent = "";
    return;
  }
  statusEl.hidden = false;
  statusEl.textContent = text;
}

function addBubble(role, content, events) {
  const empty = logEl.querySelector(".empty");
  if (empty) empty.remove();
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  const text = document.createElement("div");
  text.className = "text";
  text.textContent = content || "";
  bubble.appendChild(text);
  if (events && events.length) {
    const tools = document.createElement("div");
    tools.className = "tools";
    for (const event of events) {
      if (!event.text) continue;
      const chip = document.createElement("span");
      chip.textContent = event.text;
      tools.appendChild(chip);
    }
    if (tools.childElementCount) bubble.appendChild(tools);
  }
  logEl.appendChild(bubble);
  logEl.scrollTop = logEl.scrollHeight;
  return bubble;
}

function showEmpty() {
  logEl.replaceChildren();
  const note = document.createElement("p");
  note.className = "empty";
  note.textContent = "Stelle Fragen, debugge oder baue eine Automatisierung.";
  logEl.appendChild(note);
}

async function loadProviders() {
  const response = await fetch(api("api/providers"));
  const items = await response.json();
  const cursor = items.find((item) => item.id === "cursor");
  if (cursor && !cursor.available) {
    bannerEl.hidden = false;
    bannerEl.textContent = cursor.reason;
  } else {
    bannerEl.hidden = true;
  }
}

function applySessionTitle(id, title) {
  if (!id || !title) return;
  if (sessionId === id) titleEl.textContent = title;
  const button = sessionsEl.querySelector(`li[data-session-id="${id}"] button`);
  if (button) button.textContent = title;
}

async function loadSessions() {
  const response = await fetch(api("api/sessions"));
  const sessions = await response.json();
  sessionsEl.replaceChildren();
  for (const session of sessions) {
    const item = document.createElement("li");
    item.dataset.sessionId = session.id;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = session.title;
    button.className = session.id === sessionId ? "active" : "";
    button.addEventListener("click", () => openSession(session.id));
    item.appendChild(button);
    sessionsEl.appendChild(item);
    if (session.id === sessionId) titleEl.textContent = session.title;
  }
}

async function openSession(id) {
  sessionId = id;
  location.hash = id;
  const response = await fetch(api(`api/sessions/${id}`));
  if (!response.ok) {
    sessionId = "";
    location.hash = "";
    titleEl.textContent = "Neuer Chat";
    showEmpty();
    return;
  }
  const session = await response.json();
  titleEl.textContent = session.title;
  logEl.replaceChildren();
  if (!session.messages.length) showEmpty();
  for (const message of session.messages) {
    const bubble = addBubble(message.role, message.content, message.events);
    if (message.role === "assistant" && message.content.startsWith("Cursor API key")) {
      bubble.classList.add("error");
    }
  }
  await loadSessions();
}

async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let splitAt;
    while ((splitAt = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, splitAt);
      buffer = buffer.slice(splitAt + 2);
      let event = "message";
      const dataLines = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      onEvent(event, JSON.parse(dataLines.join("\n")));
    }
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = messageEl.value.trim();
  if (!text || streaming) return;
  streaming = true;
  sendBtn.disabled = true;
  messageEl.value = "";
  try {
    if (!sessionId) {
      const created = await fetch(api("api/sessions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: "cursor" }),
      });
      if (!created.ok) throw new Error(await created.text());
      const session = await created.json();
      sessionId = session.id;
      location.hash = sessionId;
      titleEl.textContent = text.slice(0, 80);
    }
    addBubble("user", text);
    const assistant = addBubble("assistant", "");
    const tools = document.createElement("div");
    tools.className = "tools";
    setStatus("Thinking...");
    const response = await fetch(api(`api/sessions/${sessionId}/chat`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    if (!response.ok || !response.body) {
      assistant.textContent = await response.text();
      assistant.classList.add("error");
      return;
    }
    await readSSE(response, (name, data) => {
      if (name === "text") {
        assistant.querySelector(".text").textContent += data.delta || "";
      } else if (name === "tool" && data.text) {
        if (!tools.parentElement) assistant.appendChild(tools);
        const chip = document.createElement("span");
        chip.textContent = data.text;
        tools.appendChild(chip);
      } else if (name === "status") {
        setStatus(data.text);
      } else if (name === "error") {
        assistant.classList.add("error");
        const textNode = assistant.querySelector(".text");
        if (!textNode.textContent) textNode.textContent = data.message || "Fehler";
        setStatus("");
      } else if (name === "done") {
        if (data.answer) assistant.querySelector(".text").textContent = data.answer;
        setStatus("Done.");
        streaming = false;
        sendBtn.disabled = false;
      } else if (name === "title" && data.title) {
        applySessionTitle(sessionId, data.title);
      }
      logEl.scrollTop = logEl.scrollHeight;
    });
    await loadSessions();
  } catch (error) {
    addBubble("assistant", String(error), []).classList.add("error");
    setStatus("");
  } finally {
    streaming = false;
    sendBtn.disabled = false;
    messageEl.focus();
  }
});

messageEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelector("#new-chat").addEventListener("click", () => {
  sessionId = "";
  location.hash = "";
  titleEl.textContent = "Neuer Chat";
  showEmpty();
  loadSessions();
  messageEl.focus();
});

window.addEventListener("hashchange", () => {
  const next = location.hash.replace("#", "");
  if (next !== sessionId) openSession(next);
});

loadProviders();
if (sessionId) openSession(sessionId);
else {
  showEmpty();
  loadSessions();
}
