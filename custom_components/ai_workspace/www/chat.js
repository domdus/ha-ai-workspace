const API = "/api/ai_workspace";

export function mountAiWorkspace(root, options = {}) {
  const compact = Boolean(options.compact);
  const getToken = options.getToken || (() => "");
  const navigate = options.navigate;
  const routed = Boolean(options.routed) && !compact;
  root.innerHTML = `
    <link rel="stylesheet" href="/ai_workspace/static/chat.css?v=20">
    <div class="wrap${compact ? " compact" : ""}">
      <aside>
        <div class="brand">AI Workspace</div>
        <ha-button class="new-chat" size="s" variant="brand" appearance="filled">
          <ha-svg-icon slot="start" path="M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z"></ha-svg-icon>
          New chat
        </ha-button>
        <div class="chats-label">Chats</div>
        <div class="sessions" role="list"></div>
      </aside>
      <section class="chat welcome">
        <header>
          <h1 class="title">New chat</h1>
          <p class="banner" hidden></p>
        </header>
        ${compact ? '<a class="workspace-link" href="/ai-workspace">Open full workspace</a>' : ""}
        <div class="stage">
          <div class="log"></div>
          <p class="status" hidden></p>
          <form class="composer">
            <div class="composer-box">
              <label class="sr" for="ai-message">Message</label>
              <textarea id="ai-message" class="message" rows="1" placeholder="Send a message to AI"></textarea>
              <ha-icon-button class="send" type="submit" label="Send">
                <ha-icon icon="mdi:arrow-up"></ha-icon>
              </ha-icon-button>
            </div>
          </form>
        </div>
      </section>
    </div>
  `;

  const chatEl = root.querySelector(".chat");
  const logEl = root.querySelector(".log");
  const sessionsEl = root.querySelector(".sessions");
  const titleEl = root.querySelector(".title");
  const statusEl = root.querySelector(".status");
  const bannerEl = root.querySelector(".banner");
  const form = root.querySelector(".composer");
  const messageEl = root.querySelector(".message");
  const sendBtn = root.querySelector(".send");
  const box = form.querySelector(".composer-box");
  const plusIcon = root.querySelector(".new-chat ha-svg-icon");
  if (plusIcon && !plusIcon.path) {
    plusIcon.path = "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z";
  }
  let sessionId = compact ? localStorage.getItem("ai_workspace_session") || "" : "";
  const workspaceLink = root.querySelector(".workspace-link");

  function sessionIdFromPath(pathname = location.pathname) {
    const match = pathname.match(/^\/ai-workspace(?:\/conversations)?\/([0-9a-fA-F-]{8,})\/?$/);
    return match ? match[1] : "";
  }

  function sessionPath(id) {
    return id ? `/ai-workspace/${id}` : "/ai-workspace";
  }

  function goToSession(id, replace = false) {
    const path = sessionPath(id);
    if (workspaceLink) workspaceLink.setAttribute("href", path);
    if (compact) {
      if (id) localStorage.setItem("ai_workspace_session", id);
      else localStorage.removeItem("ai_workspace_session");
      return;
    }
    if (!routed) return;
    if (location.pathname.replace(/\/$/, "") === path) return;
    if (typeof navigate === "function") navigate(path, { replace });
    else {
      history[replace ? "replaceState" : "pushState"](null, "", path);
      window.dispatchEvent(new CustomEvent("location-changed"));
    }
  }

  function applyRoute() {
    if (compact || !routed) return;
    const id = sessionIdFromPath();
    if (id === sessionId) return;
    if (id) openSession(id, true);
    else {
      sessionId = "";
      titleEl.textContent = "New chat";
      showEmpty();
      loadSessions();
    }
  }
  let streaming = false;
  let pinBottom = true;
  let followRaf = 0;
  let followLast = 0;
  let programmaticScroll = false;
  let motionTimer = 0;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function resizeComposer() {
    messageEl.style.height = "auto";
    messageEl.style.height = `${Math.min(Math.max(messageEl.scrollHeight, 36), 160)}px`;
    sendBtn.disabled = streaming || !messageEl.value.trim();
  }

  function clearMotion() {
    box.style.transition = "";
    box.style.transform = "";
    box.style.willChange = "";
    if (motionTimer) {
      clearTimeout(motionTimer);
      motionTimer = 0;
    }
  }

  function setWelcome(on, animate = true) {
    const want = Boolean(on);
    if (chatEl.classList.contains("welcome") === want) return;
    if (!want) logEl.querySelector(".empty")?.remove();
    const shouldAnimate = animate && !reduceMotion;
    if (shouldAnimate) {
      const from = box.getBoundingClientRect();
      chatEl.classList.toggle("welcome", want);
      const dy = from.top - box.getBoundingClientRect().top;
      if (Math.abs(dy) > 2) {
        if (motionTimer) clearTimeout(motionTimer);
        box.style.willChange = "transform";
        box.style.transition = "none";
        box.style.transform = `translateY(${dy}px)`;
        box.getBoundingClientRect();
        box.style.transition = "transform 560ms cubic-bezier(0.16, 1, 0.3, 1)";
        box.style.transform = "translateY(0)";
        box.addEventListener("transitionend", clearMotion, { once: true });
        motionTimer = setTimeout(clearMotion, 700);
        return;
      }
    }
    chatEl.classList.toggle("welcome", want);
    clearMotion();
  }

  function headers(extra = {}) {
    const token = getToken();
    return {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...extra,
    };
  }

  function prettyStatus(text) {
    const raw = String(text || "").trim();
    if (!raw || /^done\.?$/i.test(raw)) return "";
    if (/^running$/i.test(raw)) return "Working";
    if (/^thinking\.{0,3}$/i.test(raw)) return "Thinking";
    return raw;
  }

  function setActivity(bubble, text) {
    if (!bubble) return;
    const pretty = prettyStatus(text);
    let el = bubble.querySelector(".activity");
    if (!pretty) {
      el?.remove();
      return;
    }
    if (!el) {
      el = document.createElement("p");
      el.className = "activity shine";
      const anchor = bubble.querySelector(".text") || bubble.lastChild;
      bubble.insertBefore(el, anchor);
    }
    el.textContent = pretty;
  }

  function setStatus(text) {
    statusEl.hidden = true;
    statusEl.textContent = "";
    const bubble = logEl.querySelector(".bubble.assistant.streaming") || logEl.querySelector(".bubble.assistant:last-of-type");
    if (!bubble) return;
    const busyChip = bubble.querySelector(".tools span.busy");
    if (busyChip && /^running$/i.test(String(text || "").trim())) {
      setActivity(bubble, "");
      return;
    }
    setActivity(bubble, text);
  }

  function chipClass(event) {
    const phase = event?.phase || "";
    const text = String(event?.text || "");
    if (phase === "end" || /^finished/i.test(text) || /failed/i.test(text)) return "done";
    if (phase === "start" || /calling|\.\.\.$/i.test(text)) return "busy";
    return "done";
  }

  function chipLabel(text) {
    return String(text).replace(/\bmcp\b/gi, "MCP");
  }

  function settleChip(chip, text) {
    if (!chip) return;
    chip.className = "done";
    chip.style.animation = "none";
    if (text) chip.textContent = chipLabel(text);
  }

  function addChip(tools, event, animate) {
    if (!event?.text) return;
    const kind = animate ? chipClass(event) : "done";
    const name = String(event.name || "");
    const label = chipLabel(event.text);
    if (kind === "done" && name) {
      const pending = [...tools.children].find(
        (el) => el.dataset.tool === name && (el.classList.contains("busy") || /^calling\b/i.test(el.textContent || ""))
      );
      if (pending) {
        settleChip(pending, label);
        return;
      }
    }
    const chip = document.createElement("span");
    chip.className = kind;
    if (name) chip.dataset.tool = name;
    if (!animate || reduceMotion || kind !== "busy") chip.style.animation = "none";
    chip.textContent = label;
    tools.appendChild(chip);
  }

  function settleTools(root) {
    root?.querySelectorAll(".tools span.busy").forEach((chip) => {
      const text = chip.textContent || "";
      const finished = /^calling\b/i.test(text)
        ? text.replace(/^Calling\s+/i, "Finished ").replace(/\.\.\.\s*$/, "")
        : text;
      settleChip(chip, finished);
    });
  }

  function addBubble(role, content, events, opts = {}) {
    const empty = logEl.querySelector(".empty");
    if (empty) empty.remove();
    setWelcome(false, opts.animate !== false);
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    if (opts.animate === false || reduceMotion) bubble.classList.add("instant");
    if (events && events.length) {
      const tools = document.createElement("div");
      tools.className = "tools";
      for (const event of events) addChip(tools, event, opts.animate !== false);
      if (tools.childElementCount) bubble.appendChild(tools);
    }
    if (role === "assistant") {
      const md = document.createElement("ha-markdown");
      md.className = "text";
      md.breaks = true;
      md.content = content || "";
      md.hidden = !content;
      bubble.appendChild(md);
      if (content) bubble.classList.add("has-text");
    } else {
      const text = document.createElement("div");
      text.className = "text";
      text.textContent = content || "";
      bubble.appendChild(text);
    }
    logEl.appendChild(bubble);
    if (opts.follow !== false) scrollChatToBottom(opts.smooth !== false);
    return bubble;
  }

  function nearBottom() {
    return chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight < 96;
  }

  let streamNode = null;
  let streamBuf = "";
  let streamFull = "";
  let streamRaf = 0;

  function writeStreamBuf() {
    if (!streamNode) return;
    if (streamBuf) {
      streamFull += streamBuf;
      streamBuf = "";
    }
    streamNode.content = streamFull;
    streamNode.hidden = !streamFull;
    const bubble = streamNode.closest(".bubble");
    bubble?.classList.toggle("has-text", Boolean(streamFull));
    if (streamFull && bubble && !bubble.querySelector(".tools span.busy")) setActivity(bubble, "");
  }

  function flushAssistantText() {
    if (streamRaf) {
      cancelAnimationFrame(streamRaf);
      streamRaf = 0;
    }
    writeStreamBuf();
    streamNode = null;
  }

  function appendAssistantText(node, delta) {
    streamNode = node;
    streamBuf += delta;
    if (streamRaf) return;
    streamRaf = requestAnimationFrame(() => {
      streamRaf = 0;
      writeStreamBuf();
      scrollChatToBottom();
    });
  }

  function followBottom() {
    if (followRaf) return;
    followLast = performance.now();
    const tick = (now) => {
      const dt = Math.min(0.05, (now - followLast) / 1000);
      followLast = now;
      const max = Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
      const dist = max - chatEl.scrollTop;
      if (!pinBottom) {
        followRaf = 0;
        return;
      }
      if (dist <= 0.5) {
        programmaticScroll = true;
        chatEl.scrollTop = max;
        programmaticScroll = false;
        followRaf = 0;
        return;
      }
      const alpha = 1 - Math.exp(-dt * 14);
      programmaticScroll = true;
      chatEl.scrollTop += dist * alpha;
      programmaticScroll = false;
      followRaf = requestAnimationFrame(tick);
    };
    followRaf = requestAnimationFrame(tick);
  }

  function scrollChatToBottom(smooth = true) {
    pinBottom = true;
    if (!smooth || reduceMotion) {
      if (followRaf) {
        cancelAnimationFrame(followRaf);
        followRaf = 0;
      }
      programmaticScroll = true;
      chatEl.scrollTop = Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
      programmaticScroll = false;
      return;
    }
    followBottom();
  }

  function showEmpty() {
    setWelcome(true);
    logEl.replaceChildren();
    const note = document.createElement("p");
    note.className = "empty";
    note.textContent = "Ask about automations, entities, or what didn't run yesterday.";
    logEl.appendChild(note);
  }

  let defaultProvider = "api";

  async function loadProviders() {
    const response = await fetch(`${API}/providers`, { headers: headers() });
    if (!response.ok) return;
    const items = await response.json();
    const ready = items.find((item) => item.available) || items[0];
    if (ready?.id) defaultProvider = ready.id;
    if (ready && !ready.available) {
      bannerEl.hidden = false;
      bannerEl.textContent = ready.reason || "Configure an API provider or start the Runtime add-on.";
    } else {
      bannerEl.hidden = true;
    }
  }

  async function loadSessions() {
    if (compact || !sessionsEl) return;
    const response = await fetch(`${API}/sessions`, { headers: headers() });
    if (!response.ok) return;
    const sessions = await response.json();
    sessionsEl.replaceChildren();
    for (const session of sessions) {
      const item = document.createElement("ha-list-item-button");
      item.className = "session";
      item.setAttribute("interactive", "");
      item.setAttribute("ha-list-item", "");
      item.role = "listitem";
      const label = document.createElement("span");
      label.className = "item-text";
      label.slot = "headline";
      label.textContent = session.title;
      item.appendChild(label);
      if (session.id === sessionId) item.classList.add("selected");
      item.addEventListener("click", () => openSession(session.id));
      sessionsEl.appendChild(item);
    }
  }

  async function openSession(id, fromUrl = false) {
    if (!id) {
      sessionId = "";
      titleEl.textContent = "New chat";
      showEmpty();
      if (!fromUrl) goToSession("");
      await loadSessions();
      return;
    }
    if (fromUrl && id === sessionId) return;
    sessionId = id;
    if (compact) localStorage.setItem("ai_workspace_session", id);
    if (!fromUrl) goToSession(id);
    const response = await fetch(`${API}/sessions/${id}`, { headers: headers() });
    if (!response.ok) {
      sessionId = "";
      titleEl.textContent = "New chat";
      showEmpty();
      goToSession("", true);
      await loadSessions();
      return;
    }
    const session = await response.json();
    titleEl.textContent = session.title;
    logEl.replaceChildren();
    if (!session.messages.length) showEmpty();
    else setWelcome(false, false);
    for (const message of session.messages) {
      addBubble(message.role, message.content, message.events, { animate: false, follow: false });
    }
    scrollChatToBottom(false);
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
    resizeComposer();
    setWelcome(false);
    addBubble("user", text);
    const assistant = addBubble("assistant", "");
    assistant.classList.add("streaming");
    streamFull = "";
    streamBuf = "";
    const tools = document.createElement("div");
    tools.className = "tools";
    setActivity(assistant, "Thinking");
    try {
      if (!sessionId) {
        const created = await fetch(`${API}/sessions`, {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ provider: defaultProvider }),
        });
        if (!created.ok) throw new Error(await created.text());
        const session = await created.json();
        sessionId = session.id;
        goToSession(sessionId, true);
        if (compact) localStorage.setItem("ai_workspace_session", sessionId);
        titleEl.textContent = text.slice(0, 80);
      }
      setStatus("Thinking...");
      const response = await fetch(`${API}/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ message: text }),
      });
      if (!response.ok || !response.body) {
        const node = assistant.querySelector(".text");
        node.content = await response.text();
        node.hidden = !node.content;
        assistant.classList.add("error", "has-text");
        setActivity(assistant, "");
        return;
      }
      await readSSE(response, (name, data) => {
        if (name === "text") {
          appendAssistantText(assistant.querySelector(".text"), data.delta || "");
          return;
        }
        if (name === "tool" && data.text) {
          if (!tools.parentElement) assistant.insertBefore(tools, assistant.querySelector(".activity") || assistant.querySelector(".text"));
          addChip(tools, data, true);
          if (assistant.querySelector(".tools span.busy")) setActivity(assistant, "");
        } else if (name === "status") {
          setStatus(data.text);
        } else if (name === "error") {
          flushAssistantText();
          assistant.classList.add("error");
          const textNode = assistant.querySelector(".text");
          if (!streamFull) {
            textNode.content = data.message || "Error";
            textNode.hidden = !textNode.content;
            assistant.classList.add("has-text");
          }
          settleTools(assistant);
          setActivity(assistant, "");
        } else if (name === "done") {
          flushAssistantText();
          if (data.answer) {
            streamFull = data.answer;
            const textNode = assistant.querySelector(".text");
            textNode.content = streamFull;
            textNode.hidden = !streamFull;
            assistant.classList.toggle("has-text", Boolean(streamFull));
          }
          settleTools(assistant);
          setActivity(assistant, "");
        }
        scrollChatToBottom();
      });
      await loadSessions();
    } catch (error) {
      flushAssistantText();
      assistant.classList.add("error");
      const node = assistant.querySelector(".text");
      if (!streamFull) {
        node.content = String(error);
        node.hidden = !node.content;
        assistant.classList.add("has-text");
      }
      settleTools(assistant);
      setActivity(assistant, "");
    } finally {
      streaming = false;
      settleTools(assistant);
      assistant.classList.remove("streaming");
      resizeComposer();
      messageEl.focus();
    }
  });

  chatEl.addEventListener("scroll", () => {
    if (programmaticScroll) return;
    pinBottom = nearBottom();
  }, { passive: true });

  messageEl.addEventListener("input", resizeComposer);
  messageEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  sendBtn.addEventListener("click", (event) => {
    event.preventDefault();
    form.requestSubmit();
  });

  root.querySelector(".new-chat")?.addEventListener("click", () => {
    sessionId = "";
    if (compact) localStorage.removeItem("ai_workspace_session");
    goToSession("");
    titleEl.textContent = "New chat";
    showEmpty();
    loadSessions();
    messageEl.focus();
  });

  if (!compact && routed) {
    window.addEventListener("location-changed", applyRoute);
    window.addEventListener("popstate", applyRoute);
  }

  loadProviders();
  const startId = compact ? sessionId : sessionIdFromPath();
  if (startId) openSession(startId, true);
  else {
    showEmpty();
    loadSessions();
  }
  resizeComposer();
  return { openSession, applyRoute };
}
