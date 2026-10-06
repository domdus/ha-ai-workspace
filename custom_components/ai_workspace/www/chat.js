const CACHE = new URL(import.meta.url).search;
const { stringsFor } = await import(`./i18n.js${CACHE}`);

const API = "/api/ai_workspace";
const HELPER_DOMAINS = new Set([
  "input_boolean",
  "input_button",
  "input_datetime",
  "input_number",
  "input_select",
  "input_text",
  "counter",
  "timer",
  "schedule",
]);

function hassObj() {
  return document.querySelector("home-assistant")?.hass;
}

function hassLanguage() {
  const hass = hassObj();
  return hass?.locale?.language || hass?.language || navigator.language || "en";
}

function looksLikeEntityId(id) {
  return /^[a-z][a-z0-9_]*\.[a-zA-Z0-9_]+$/.test(String(id || ""));
}

function harvestEntityConfig(config, out) {
  if (!config || out.size >= 40) return;
  if (typeof config === "string") {
    if (looksLikeEntityId(config)) out.add(config);
    return;
  }
  if (Array.isArray(config)) {
    for (const item of config) harvestEntityConfig(item, out);
    return;
  }
  if (typeof config !== "object") return;
  for (const key of ["entity", "camera", "media_player", "climate", "light", "switch"]) {
    harvestEntityConfig(config[key], out);
  }
  for (const key of ["entities", "cards", "sections", "badges", "chips", "features", "views"]) {
    harvestEntityConfig(config[key], out);
  }
}

function walkVisibleEntities(node, out, depth) {
  if (!node || depth > 24 || out.size >= 40) return;
  if (node.id === "ha-ai-workspace-overlay") return;
  const attr = node.getAttribute?.("entity-id") || node.getAttribute?.("data-entity-id") || node.getAttribute?.("data-entity");
  if (looksLikeEntityId(attr)) out.add(attr);
  if (looksLikeEntityId(node.entityId)) out.add(node.entityId);
  if (looksLikeEntityId(node.entity_id)) out.add(node.entity_id);
  if (node.config) harvestEntityConfig(node.config, out);
  const next = node.shadowRoot ? [...node.shadowRoot.children, ...node.children] : [...(node.children || [])];
  for (const child of next) walkVisibleEntities(child, out, depth + 1);
}

function haPanelRoot() {
  const main = document.querySelector("home-assistant")?.shadowRoot?.querySelector("home-assistant-main");
  const tree = main?.shadowRoot;
  const drawer = tree?.querySelector("ha-drawer");
  const from = drawer?.shadowRoot || tree;
  return from?.querySelector("partial-panel-resolver") || from?.querySelector("ha-panel-lovelace") || main;
}

function haPageContext() {
  const path = `${location.pathname}${location.search}`;
  if (!path.startsWith("/") || path.startsWith("/ai-workspace")) return null;
  const hass = hassObj();
  const parts = location.pathname.split("/").filter(Boolean);
  const dashboardPath = parts[0] || "";
  const viewPath = parts.slice(1).join("/");
  const panel = hass?.panels?.[dashboardPath];
  const areas = hass?.areas || {};
  const areaMatch = /(?:^|\/)areas-([^/?#]+)/.exec(location.pathname);
  let areaId = "";
  let areaName = "";
  if (areaMatch) {
    const slug = areaMatch[1];
    for (const [id, area] of Object.entries(areas)) {
      if (id === slug || id.replace(/_/g, "-") === slug || String(area?.name || "").toLowerCase().replace(/\s+/g, "-") === slug) {
        areaId = id;
        areaName = area?.name || "";
        break;
      }
    }
    if (!areaName) {
      areaId = slug.replace(/-/g, "_");
      areaName = areas[areaId]?.name || slug.replace(/-/g, " ");
    }
  }
  let viewTitle = "";
  let dashboardTitle = panel?.title || "";
  try {
    const lovelace = document.querySelector("home-assistant")
      ?.shadowRoot?.querySelector("home-assistant-main")
      ?.shadowRoot?.querySelector("ha-panel-lovelace")?.lovelace;
    if (!dashboardTitle && lovelace?.config?.title) dashboardTitle = lovelace.config.title;
    const views = lovelace?.config?.views || [];
    const view = views.find((item) => item.path === parts[1] || item.path === viewPath)
      || (parts.length < 2 ? views[0] : null);
    viewTitle = view?.title || "";
  } catch {
    viewTitle = "";
  }
  const entities = new Set();
  const root = haPanelRoot();
  if (root) walkVisibleEntities(root, entities, 0);
  const title = String(document.title || "")
    .replace(/\s*[–—-]\s*Home Assistant\s*$/i, "")
    .trim();
  return {
    path,
    title,
    dashboard: dashboardTitle || dashboardPath,
    view: viewTitle || viewPath,
    area: areaName,
    area_id: areaId,
    entities: [...entities],
  };
}

function lookupEntity(id) {
  const hass = hassObj();
  if (!hass || !id) return null;
  if (hass.states?.[id] || hass.entities?.[id]) {
    return { entityId: id, state: hass.states?.[id], entry: hass.entities?.[id] };
  }
  if (!String(id).includes(".")) {
    for (const domain of ["automation", "script", "scene"]) {
      const entityId = `${domain}.${id}`;
      if (hass.states?.[entityId] || hass.entities?.[entityId]) {
        return { entityId, state: hass.states?.[entityId], entry: hass.entities?.[entityId] };
      }
    }
  }
  return { entityId: id, state: hass.states?.[id], entry: hass.entities?.[id] };
}

function configId(info) {
  const attr = info?.state?.attributes?.id;
  if (attr != null && String(attr) !== "") return String(attr);
  const unique = info?.entry?.unique_id;
  return unique ? String(unique) : "";
}

function pathForEntity(entityId, info) {
  const domain = String(entityId || "").split(".")[0];
  if (HELPER_DOMAINS.has(domain)) return "/config/helpers";
  if (domain === "automation") {
    const id = configId(info);
    if (id && !looksLikeEntityId(id)) return `/config/automation/edit/${id}`;
  }
  if (domain === "script") {
    const id = configId(info) || String(entityId).replace(/^script\./, "");
    if (id) return `/config/script/edit/${id}`;
  }
  if (domain === "scene") {
    const id = configId(info) || String(entityId).replace(/^scene\./, "");
    if (id) return `/config/scene/edit/${id}`;
  }
  const deviceId = info?.entry?.device_id;
  if (deviceId) return `/config/devices/device/${deviceId}`;
  return `/config/entities/entity/${entityId}`;
}

function rewriteHaPath(pathname) {
  const path = String(pathname || "");
  const edit = path.match(/^\/config\/(automation|script|scene)\/edit\/(.+)$/);
  if (edit) {
    const kind = edit[1];
    let raw = edit[2];
    try {
      raw = decodeURIComponent(raw);
    } catch (_err) {
      /* keep */
    }
    const entityId = looksLikeEntityId(raw) ? raw : `${kind}.${raw}`;
    const info = lookupEntity(entityId);
    const domain = entityId.split(".")[0];
    if (HELPER_DOMAINS.has(domain)) return "/config/helpers";
    if (looksLikeEntityId(raw) || info?.state || info?.entry) {
      if (domain === "automation" || kind === "automation") {
        const id = configId(info);
        if (id && !looksLikeEntityId(id)) return `/config/automation/edit/${id}`;
      }
      if (domain === "script" || kind === "script") {
        const id = configId(info) || entityId.replace(/^script\./, "");
        if (id) return `/config/script/edit/${id}`;
      }
      if (domain === "scene" || kind === "scene") {
        const id = configId(info) || entityId.replace(/^scene\./, "");
        if (id) return `/config/scene/edit/${id}`;
      }
      if (looksLikeEntityId(raw) && domain !== kind) return pathForEntity(entityId, info);
    }
  }
  const device = path.match(/^\/config\/devices\/device\/(.+)$/);
  if (device) {
    let raw = device[1];
    try {
      raw = decodeURIComponent(raw);
    } catch (_err) {
      /* keep */
    }
    if (looksLikeEntityId(raw)) return pathForEntity(raw, lookupEntity(raw));
  }
  const entity = path.match(/^\/config\/entities(?:\/entity)?\/(.+)$/);
  if (entity) {
    let raw = entity[1];
    try {
      raw = decodeURIComponent(raw);
    } catch (_err) {
      /* keep */
    }
    if (looksLikeEntityId(raw)) return pathForEntity(raw, lookupEntity(raw));
  }
  return path;
}

function rewriteHaHref(raw) {
  const trimmed = String(raw || "").trim();
  if (!trimmed || trimmed.startsWith("#") || trimmed.startsWith("mailto:")) return trimmed;
  let url;
  try {
    url = new URL(trimmed, window.location.origin);
  } catch (_err) {
    return trimmed;
  }
  const path = rewriteHaPath(url.pathname);
  const suffix = `${path}${url.search}${url.hash}`;
  if (
    trimmed.startsWith("/") ||
    url.origin === window.location.origin ||
    haAppPath(path)
  ) {
    return suffix.startsWith("/") ? suffix : `/${suffix}`;
  }
  return `${url.origin}${suffix}`;
}

function haAppPath(path) {
  const value = String(path || "");
  return (
    value.startsWith("/config/") ||
    value.startsWith("/lovelace") ||
    value.startsWith("/dashboard") ||
    value.startsWith("/history") ||
    value.startsWith("/logbook") ||
    value.startsWith("/developer-tools") ||
    value.startsWith("/profile") ||
    value.startsWith("/media-browser") ||
    value.startsWith("/energy") ||
    value.startsWith("/map") ||
    value.startsWith("/todo") ||
    value.startsWith("/ai-workspace") ||
    value.startsWith("/hassio") ||
    value.startsWith("/supervisor")
  );
}

export function mountAiWorkspace(root, options = {}) {
  const compact = Boolean(options.compact);
  const strings = stringsFor(hassLanguage());
  const t = (key, vars = {}) => {
    let text = strings[key] || key;
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, value);
    }
    return text;
  };
  const getToken = options.getToken || (() => "");
  const navigate = options.navigate;
  const routed = Boolean(options.routed) && !compact;
  const NAV_KEY = "ai_workspace_nav_collapsed";
  const mqNarrow = window.matchMedia("(max-width: 870px)");
  const overlayStart = Boolean(options.narrow) || mqNarrow.matches;
  const collapsedStart = !compact && !overlayStart && localStorage.getItem(NAV_KEY) === "1";
  const wrapClass = [
    "wrap",
    compact ? "compact" : "",
    options.chrome === "panel" ? "has-app-bar" : "",
    overlayStart ? "narrow" : "",
    collapsedStart ? "nav-collapsed" : "",
  ]
    .filter(Boolean)
    .join(" ");
  root.innerHTML = `
    <link rel="stylesheet" href="/ai_workspace/static/chat.css${CACHE}">
    <div class="${wrapClass}">
      <button type="button" class="nav-scrim" hidden aria-label="${t("close")}"></button>
      <aside>
        <div class="nav-toolbar">
          <ha-icon-button class="nav-toggle" label="${t("hide_chats")}">
            <ha-icon icon="mdi:dock-left"></ha-icon>
          </ha-icon-button>
        </div>
        <div class="brand">${t("title")}</div>
        <ha-icon-button class="new-chat-icon" label="${t("new_chat")}">
          <ha-icon icon="mdi:plus"></ha-icon>
        </ha-icon-button>
        <ha-button class="new-chat" size="s" variant="brand" appearance="filled">
          <ha-svg-icon slot="start" path="M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z"></ha-svg-icon>
          ${t("new_chat")}
        </ha-button>
        <div class="sessions" role="list"></div>
      </aside>
      <section class="chat welcome">
        <header>
          <div class="header-row">
            <ha-icon-button class="nav-toggle chat-nav-toggle" label="${t("show_chats")}">
              <ha-icon icon="mdi:forum-outline"></ha-icon>
            </ha-icon-button>
            <h1 class="title">${t("new_chat")}</h1>
          </div>
          <p class="banner" hidden></p>
        </header>
        ${compact ? `<a class="workspace-link" href="/ai-workspace">${t("open_workspace")}</a>` : ""}
        <div class="stage">
          <div class="log"></div>
          <p class="status" hidden></p>
          <form class="composer">
            <div class="composer-box">
              <div class="attach-row" hidden></div>
              <div class="composer-row">
              <label class="sr" for="ai-message">${t("message")}</label>
              <textarea id="ai-message" class="message" rows="1" placeholder="${t("placeholder")}"></textarea>
              <input class="file-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif,.yaml,.yml,.json,.txt,.md,.csv,.xml,.toml,.html,.css,.js,.ts,.py,.log,.cfg,.ini,.conf" multiple hidden>
              <ha-icon-button class="attach" type="button" label="${t("attach")}">
                <ha-icon icon="mdi:paperclip"></ha-icon>
              </ha-icon-button>
              <ha-icon-button class="mic" type="button" label="${t("dictate")}" hidden>
                <ha-icon icon="mdi:microphone"></ha-icon>
              </ha-icon-button>
              <ha-icon-button class="send" type="submit" label="${t("send")}">
                <ha-icon icon="mdi:arrow-up"></ha-icon>
              </ha-icon-button>
              </div>
            </div>
          </form>
        </div>
      </section>
    </div>
  `;

  const wrap = root.querySelector(".wrap");
  const scrim = root.querySelector(".nav-scrim");
  const chatEl = root.querySelector(".chat");
  const logEl = root.querySelector(".log");
  const sessionsEl = root.querySelector(".sessions");
  const titleEl = root.querySelector(".title");
  const statusEl = root.querySelector(".status");
  const bannerEl = root.querySelector(".banner");
  const form = root.querySelector(".composer");
  const messageEl = root.querySelector(".message");
  const sendBtn = root.querySelector(".send");
  const micBtn = root.querySelector(".mic");
  const micIcon = micBtn?.querySelector("ha-icon");
  const attachBtn = root.querySelector(".attach");
  const fileInput = root.querySelector(".file-input");
  const attachRow = root.querySelector(".attach-row");
  const box = form.querySelector(".composer-box");
  const plusIcon = root.querySelector(".new-chat ha-svg-icon");
  if (plusIcon && !plusIcon.path) {
    plusIcon.path = "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z";
  }
  let sessionId = "";
  let routeGen = 0;
  const workspaceLink = root.querySelector(".workspace-link");

  function isNarrow() {
    return Boolean(options.narrow) || mqNarrow.matches;
  }

  function syncToggleLabels() {
    const collapsed = wrap.classList.contains("nav-collapsed");
    const open = wrap.classList.contains("nav-open");
    const label = wrap.classList.contains("narrow")
      ? (open ? t("hide_chats") : t("show_chats"))
      : (collapsed ? t("show_chats") : t("hide_chats"));
    root.querySelectorAll(".nav-toggle").forEach((btn) => {
      btn.label = label;
    });
  }

  function setNavOpen(open) {
    wrap.classList.toggle("nav-open", Boolean(open));
    if (scrim) scrim.hidden = !open;
    syncToggleLabels();
  }

  function closeNavIfOverlay() {
    if (isNarrow() || mqNarrow.matches) setNavOpen(false);
  }

  function setNarrow(narrow) {
    if (compact) return;
    options.narrow = Boolean(narrow);
    const overlay = isNarrow();
    wrap.classList.toggle("narrow", overlay);
    if (overlay) {
      wrap.classList.remove("nav-collapsed");
      setNavOpen(false);
    } else {
      wrap.classList.toggle("nav-collapsed", localStorage.getItem(NAV_KEY) === "1");
      setNavOpen(false);
    }
    syncToggleLabels();
  }

  function toggleNav() {
    if (compact) return;
    if (isNarrow() || mqNarrow.matches) {
      wrap.classList.add("narrow");
      wrap.classList.remove("nav-collapsed");
      setNavOpen(!wrap.classList.contains("nav-open"));
      return;
    }
    const collapsed = !wrap.classList.contains("nav-collapsed");
    wrap.classList.toggle("nav-collapsed", collapsed);
    localStorage.setItem(NAV_KEY, collapsed ? "1" : "0");
    syncToggleLabels();
  }

  setNarrow(options.narrow);

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
      titleEl.textContent = t("new_chat");
      showEmpty();
      loadSessions();
    }
  }
  let streaming = false;
  const MAX_ATTACH = 4;
  const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
  const MAX_FILE_BYTES = 256 * 1024;
  const IMAGE_EDGE = 1280;
  const TEXT_EXT = /\.(ya?ml|json|toml|ini|cfg|conf|env|txt|md|markdown|csv|tsv|xml|html?|css|js|mjs|cjs|tsx?|jsx|py|sh|bash|sql|log)$/i;
  let pending = [];
  let attachNoticeTimer = 0;
  let pinBottom = true;
  let followRaf = 0;
  let followLast = 0;
  let programmaticScroll = false;
  let motionTimer = 0;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function resizeComposer() {
    messageEl.style.height = "auto";
    messageEl.style.height = `${Math.min(Math.max(messageEl.scrollHeight, 36), 160)}px`;
    sendBtn.disabled = streaming || (!messageEl.value.trim() && !pending.length);
    if (attachBtn) attachBtn.disabled = streaming || pending.length >= MAX_ATTACH;
  }

  function keepComposerFocus() {
    return window.matchMedia("(pointer: fine)").matches && !mqNarrow.matches;
  }

  function hideKeyboard() {
    messageEl.blur();
    sendBtn.blur();
    const active = document.activeElement;
    if (active && active !== document.body && typeof active.blur === "function") active.blur();
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
    if (/^no mcp servers configured\.?$/i.test(raw)) return "";
    if (/^mcp:\s/i.test(raw)) return "";
    if (/^running$/i.test(raw)) return t("working");
    if (/^thinking\.{0,3}$/i.test(raw)) return t("thinking");
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
      const label = document.createElement("span");
      label.className = "label";
      el.appendChild(label);
      const anchor = bubble.querySelector(".text") || bubble.lastChild;
      bubble.insertBefore(el, anchor);
    }
    let label = el.querySelector(".label");
    if (!label) {
      label = document.createElement("span");
      label.className = "label";
      el.replaceChildren(label);
    }
    label.textContent = pretty;
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

  function rewriteAssistantLinks(content) {
    let text = String(content || "");
    const here = window.location.origin;
    if (!/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?$/i.test(here)) {
      text = text.replace(/https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?/gi, here);
    }
    text = text.replace(/\]\(([^)]+)\)/g, (_m, url) => `](${rewriteHaHref(url)})`);
    text = text.replace(/https?:\/\/[^\s)<]+/g, (url) => rewriteHaHref(url));
    return text;
  }

  function chipClass(event) {
    const phase = event?.phase || "";
    const text = String(event?.text || "");
    if (phase === "end" || /^finished/i.test(text) || /failed/i.test(text)) return "done";
    if (phase === "start" || /calling|\.\.\.$/i.test(text)) return "busy";
    return "done";
  }

  function chipName(name) {
    return String(name || "").replace(/\bmcp\b/gi, "MCP").replace(/\s*\.\.\.\s*$/, "");
  }

  function chipLabel(text) {
    const raw = String(text || "").trim();
    const calling = raw.match(/^Calling\s+(.+?)\s*$/i);
    if (calling) return t("calling_tool", { name: chipName(calling[1]) });
    const finished = raw.match(/^Finished\s+(.+?)\s*$/i);
    if (finished) return t("finished_tool", { name: chipName(finished[1]) });
    return chipName(raw);
  }

  function settleChip(chip, text) {
    if (!chip) return;
    chip.className = "done";
    chip.style.animation = "none";
    if (text) chip.textContent = chipLabel(text);
  }

  function ensureToolsChrome(tools) {
    let list = tools.querySelector(".tools-list");
    if (list) return list;
    const summary = document.createElement("button");
    summary.type = "button";
    summary.className = "tools-summary";
    summary.hidden = true;
    summary.setAttribute("aria-expanded", "false");
    const chevron = document.createElement("ha-icon");
    chevron.className = "tools-chevron";
    chevron.setAttribute("icon", "mdi:chevron-right");
    const label = document.createElement("span");
    label.className = "tools-summary-label";
    summary.append(chevron, label);
    summary.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      tools.classList.toggle("expanded");
      tools.dataset.userToggle = "1";
      syncToolsSummary(tools);
    });
    list = document.createElement("div");
    list.className = "tools-list";
    tools.append(summary, list);
    return list;
  }

  function toolsSummaryLabel(chips, busy) {
    const n = chips.length;
    const noun = n === 1 ? t("tool_one") : t("tool_many");
    return t(busy ? "calling_n" : "called_n", { n: String(n), noun });
  }

  function syncToolsSummary(tools) {
    const list = tools.querySelector(".tools-list");
    const summary = tools.querySelector(".tools-summary");
    if (!list || !summary) return;
    const chips = [...list.querySelectorAll(":scope > span")];
    const n = chips.length;
    const busy = chips.some((chip) => chip.classList.contains("busy"));
    tools.classList.toggle("busy", busy);
    summary.hidden = n === 0;
    if (!n) return;
    summary.querySelector(".tools-summary-label").textContent = toolsSummaryLabel(chips, busy);
    if (!tools.dataset.userToggle) {
      tools.classList.remove("expanded");
    }
    const open = tools.classList.contains("expanded");
    summary.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function isPendingChip(el) {
    return el.classList.contains("busy") || /^calling\b/i.test(el.textContent || "");
  }

  function addChip(tools, event, animate) {
    if (!event?.text || event.type === "image" || event.type === "file") return;
    const list = ensureToolsChrome(tools);
    const kind = animate ? chipClass(event) : "done";
    const name = String(event.name || "");
    const callId = String(event.id || event.call_id || "");
    const label = chipLabel(event.text);
    if (kind === "done") {
      const chips = [...list.children];
      const pending =
        (callId && chips.find((el) => el.dataset.callId === callId && isPendingChip(el))) ||
        chips.find((el) => name && el.dataset.tool === name && isPendingChip(el)) ||
        chips.find((el) => name && name.toLowerCase() !== "mcp" && el.dataset.tool === "mcp" && isPendingChip(el));
      if (pending) {
        if (name) pending.dataset.tool = name;
        if (callId) pending.dataset.callId = callId;
        settleChip(pending, label);
        syncToolsSummary(tools);
        return;
      }
    }
    const chip = document.createElement("span");
    chip.className = kind;
    if (name) chip.dataset.tool = name;
    if (callId) chip.dataset.callId = callId;
    if (!animate || reduceMotion || kind !== "busy") chip.style.animation = "none";
    chip.textContent = label;
    list.appendChild(chip);
    syncToolsSummary(tools);
  }

  function settleTools(root) {
    root?.querySelectorAll(".tools span.busy").forEach((chip) => {
      const name = chip.dataset.tool || chip.textContent || "";
      settleChip(chip, t("finished_tool", { name: chipName(name) }));
    });
    root?.querySelectorAll(".tools").forEach(syncToolsSummary);
  }

  function isDefaultImageCaption(text) {
    const value = String(text || "").trim();
    return (
      value === "Look at this image." ||
      /^Look at these \d+ images\.$/.test(value) ||
      value === "Look at this file." ||
      /^Look at these \d+ files\.$/.test(value) ||
      value === "Look at these attachments."
    );
  }

  function addBubbleImages(bubble, events) {
    const pics = (events || []).filter((event) => event && event.type === "image" && event.src);
    if (!pics.length) return pics;
    const row = document.createElement("div");
    row.className = "bubble-images";
    for (const pic of pics) {
      const img = document.createElement("img");
      img.src = pic.src;
      img.alt = pic.name || "Image";
      row.appendChild(img);
    }
    bubble.appendChild(row);
    return pics;
  }

  function addBubbleFiles(bubble, events) {
    const files = (events || []).filter((event) => event && event.type === "file" && event.name);
    if (!files.length) return files;
    const row = document.createElement("div");
    row.className = "bubble-files";
    for (const file of files) {
      const chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = file.name;
      row.appendChild(chip);
    }
    bubble.appendChild(row);
    return files;
  }

  function addBubble(role, content, events, opts = {}) {
    const empty = logEl.querySelector(".empty");
    if (empty) empty.remove();
    setWelcome(false, opts.animate !== false);
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    if (opts.animate === false || reduceMotion) bubble.classList.add("instant");
    const pics = addBubbleImages(bubble, events);
    const files = addBubbleFiles(bubble, events);
    const chips = (events || []).filter((event) => event && event.type !== "image" && event.type !== "file");
    if (chips.length) {
      const tools = document.createElement("div");
      tools.className = "tools";
      for (const event of chips) addChip(tools, event, opts.animate !== false);
      if (tools.childElementCount) bubble.appendChild(tools);
    }
    if (role === "assistant") {
      const md = document.createElement("ha-markdown");
      md.className = "text";
      md.breaks = true;
      md.content = rewriteAssistantLinks(content || "");
      md.hidden = !content;
      bubble.appendChild(md);
      if (content) bubble.classList.add("has-text");
    } else if (content && !((pics.length || files.length) && isDefaultImageCaption(content))) {
      const text = document.createElement("div");
      text.className = "text";
      text.textContent = content;
      bubble.appendChild(text);
      bubble.classList.add("has-text");
    }
    logEl.appendChild(bubble);
    retargetHaLinks(bubble);
    syncCopyChat();
    if (opts.follow !== false) scrollChatToBottom(opts.smooth !== false);
    return bubble;
  }

  function transcriptText() {
    const parts = [];
    for (const bubble of logEl.querySelectorAll(".bubble")) {
      const role = bubble.classList.contains("user") ? t("you") : t("assistant");
      const md = bubble.querySelector("ha-markdown.text");
      const textEl = bubble.querySelector("div.text");
      const body = md
        ? String(md.content || "").trim()
        : String(textEl?.textContent || "").trim();
      const attachments = [
        ...[...bubble.querySelectorAll(".bubble-images img")].map((img) => img.alt || "image"),
        ...[...bubble.querySelectorAll(".bubble-files .file-chip")].map((el) => el.textContent.trim()),
      ].filter(Boolean);
      if (!body && !attachments.length) continue;
      const lines = [];
      if (attachments.length) lines.push(attachments.map((name) => `[${name}]`).join(" "));
      if (body) lines.push(body);
      parts.push(`${role}:\n${lines.join("\n")}`);
    }
    return parts.join("\n\n");
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      throw new Error("clipboard");
    } catch (_err) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
  }

  function syncCopyChat() {
    let row = logEl.querySelector(".chat-actions");
    const hasChat = Boolean(logEl.querySelector(".bubble.has-text, .bubble .bubble-files, .bubble .bubble-images"));
    const busy = streaming || Boolean(logEl.querySelector(".bubble.streaming"));
    if (!hasChat || busy) {
      if (row) row.hidden = true;
      return;
    }
    if (!row) {
      row = document.createElement("div");
      row.className = "chat-actions";
      const btn = document.createElement("ha-icon-button");
      btn.className = "copy-chat";
      btn.type = "button";
      btn.label = t("copy_chat");
      const icon = document.createElement("ha-icon");
      icon.setAttribute("icon", "mdi:content-copy");
      btn.appendChild(icon);
      btn.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const text = transcriptText();
        if (!text) return;
        await copyText(text);
        icon.setAttribute("icon", "mdi:check");
        btn.label = t("copied");
        window.setTimeout(() => {
          icon.setAttribute("icon", "mdi:content-copy");
          btn.label = t("copy_chat");
        }, 1600);
      });
      row.appendChild(btn);
    }
    row.hidden = false;
    logEl.appendChild(row);
  }

  function haLinkPath(href) {
    const next = rewriteHaHref(href);
    try {
      const url = new URL(next, window.location.origin);
      if (url.origin === window.location.origin || haAppPath(url.pathname)) {
        return `${url.pathname}${url.search}${url.hash}`;
      }
    } catch (_err) {
      /* keep */
    }
    return String(next).startsWith("/") ? next : "";
  }

  function retargetLink(anchor) {
    if (!anchor || anchor.tagName !== "A") return;
    const href = anchor.getAttribute("href") || "";
    if (!href || href.startsWith("#") || href.startsWith("mailto:")) return;
    const path = haLinkPath(href);
    if (!path) return;
    anchor.setAttribute("href", path);
    anchor.removeAttribute("target");
  }

  function retargetHaLinks(scope) {
    const root = scope || logEl;
    root.querySelectorAll?.("a[href]")?.forEach(retargetLink);
    root.querySelectorAll?.("ha-markdown")?.forEach((md) => {
      md.querySelectorAll("a[href]").forEach(retargetLink);
      md.shadowRoot?.querySelectorAll("a[href]").forEach(retargetLink);
    });
  }

  function openHaPath(path) {
    if (typeof navigate === "function") {
      navigate(path);
      return;
    }
    const hass = hassObj();
    if (typeof hass?.navigate === "function") {
      hass.navigate(path);
      return;
    }
    const state = history.state && typeof history.state === "object" ? history.state : { root: true };
    history.pushState(state, "", path);
    const event = new Event("location-changed", { bubbles: true, composed: true });
    event.detail = { replace: false };
    window.dispatchEvent(event);
  }

  function nearBottom() {
    return chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight < 96;
  }

  let streamNode = null;
  let streamBuf = "";
  let streamFull = "";
  let streamDrainRaf = 0;
  let streamDrainLast = 0;
  let streamWaiters = [];

  function writeStreamVisible() {
    if (!streamNode) return;
    streamNode.content = rewriteAssistantLinks(streamFull);
    streamNode.hidden = !streamFull;
    const bubble = streamNode.closest(".bubble");
    bubble?.classList.toggle("has-text", Boolean(streamFull));
    if (streamFull && bubble && !bubble.querySelector(".tools span.busy")) setActivity(bubble, "");
    if (bubble) retargetHaLinks(bubble);
  }

  function takeStreamChunk(dt) {
    const backlog = streamBuf.length;
    const cps = Math.min(200, 28 + backlog * 0.18);
    let n = Math.max(1, Math.round(cps * dt));
    n = Math.min(n, backlog);
    if (n < backlog) {
      const space = streamBuf.slice(n, n + 10).search(/\s/);
      if (space >= 0 && space < 8) n += space + 1;
    }
    const chunk = streamBuf.slice(0, n);
    streamBuf = streamBuf.slice(n);
    return chunk;
  }

  function finishStreamWaiters() {
    const waiters = streamWaiters;
    streamWaiters = [];
    waiters.forEach((fn) => fn());
  }

  function pumpStream(now) {
    streamDrainRaf = 0;
    const dt = Math.min(0.05, (now - streamDrainLast) / 1000);
    streamDrainLast = now;
    if (reduceMotion) {
      streamFull += streamBuf;
      streamBuf = "";
    } else if (streamBuf) {
      streamFull += takeStreamChunk(dt);
    }
    writeStreamVisible();
    if (pinBottom) followBottom();
    if (streamBuf) {
      streamDrainRaf = requestAnimationFrame(pumpStream);
      return;
    }
    finishStreamWaiters();
  }

  function startStreamPump() {
    if (streamDrainRaf) return;
    streamDrainLast = performance.now();
    streamDrainRaf = requestAnimationFrame(pumpStream);
  }

  function revealAllNow() {
    if (streamDrainRaf) {
      cancelAnimationFrame(streamDrainRaf);
      streamDrainRaf = 0;
    }
    streamFull += streamBuf;
    streamBuf = "";
    writeStreamVisible();
    finishStreamWaiters();
  }

  function waitForStream() {
    if (!streamBuf && !streamDrainRaf) return Promise.resolve();
    return new Promise((resolve) => {
      streamWaiters.push(resolve);
      startStreamPump();
    });
  }

  function queueStreamAnswer(answer) {
    const text = String(answer || "");
    if (!text) return;
    if (!streamFull) streamBuf = text;
    else if (text.startsWith(streamFull)) streamBuf = text.slice(streamFull.length);
    startStreamPump();
  }

  function appendAssistantText(node, delta) {
    streamNode = node;
    streamBuf += delta;
    startStreamPump();
  }

  function followBottom() {
    if (followRaf) return;
    followLast = performance.now();
    const tick = (now) => {
      const dt = Math.min(0.032, (now - followLast) / 1000);
      followLast = now;
      const max = Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
      const dist = max - chatEl.scrollTop;
      const keep = pinBottom && (streaming || Boolean(streamBuf) || dist > 0.5);
      if (!keep) {
        followRaf = 0;
        return;
      }
      programmaticScroll = true;
      if (dist <= 0.5) {
        chatEl.scrollTop = max;
      } else {
        const k = streaming || streamBuf ? 2.6 : 10;
        const alpha = 1 - Math.exp(-dt * k);
        let step = dist * alpha;
        if (streaming || streamBuf) step = Math.min(step, Math.max(6, dist * 0.16));
        chatEl.scrollTop += step;
      }
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
    note.textContent = t("empty");
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
      bannerEl.textContent = ready.reason || t("configure_provider");
    } else {
      bannerEl.hidden = true;
    }
  }

  let sessionMenu = null;

  function closeSessionMenu() {
    if (!sessionMenu) return;
    sessionMenu.remove();
    sessionMenu = null;
    root.querySelectorAll(".session-more[aria-expanded='true']").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });
  }

  function sessionAction(label, className, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = className;
    btn.setAttribute("role", "menuitem");
    btn.textContent = label;
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeSessionMenu();
      onClick();
    });
    return btn;
  }

  function openSessionMenu(anchor, session) {
    const already = sessionMenu && sessionMenu.dataset.sessionId === session.id;
    closeSessionMenu();
    if (already) return;
    sessionMenu = document.createElement("div");
    sessionMenu.className = "session-menu";
    sessionMenu.dataset.sessionId = session.id;
    sessionMenu.setAttribute("role", "menu");
    sessionMenu.append(
      sessionAction(session.pinned ? t("unpin") : t("pin"), "", () => pinSession(session)),
      sessionAction(t("rename"), "", () => renameSession(session)),
      sessionAction(t("delete"), "danger", () => deleteSession(session)),
    );
    wrap.appendChild(sessionMenu);
    const rect = anchor.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    const menuRect = sessionMenu.getBoundingClientRect();
    let top = rect.bottom - wrapRect.top + 4;
    let left = rect.right - wrapRect.left - menuRect.width;
    if (left < 8) left = 8;
    if (top + menuRect.height > wrapRect.height - 8) {
      top = rect.top - wrapRect.top - menuRect.height - 4;
    }
    sessionMenu.style.top = `${Math.max(8, top)}px`;
    sessionMenu.style.left = `${left}px`;
    anchor.setAttribute("aria-expanded", "true");
  }

  async function pinSession(session) {
    const pinned = !session.pinned;
    const response = await fetch(`${API}/sessions/${session.id}`, {
      method: "PATCH",
      headers: headers(),
      body: JSON.stringify({ pinned }),
    });
    if (!response.ok) {
      setBanner(await response.text());
      return;
    }
    loadSessions();
  }

  async function renameSession(session) {
    const next = window.prompt(t("rename_prompt"), session.title);
    if (next == null) return;
    const title = next.trim().replace(/\s+/g, " ").slice(0, 80);
    if (!title || title === session.title) return;
    const response = await fetch(`${API}/sessions/${session.id}`, {
      method: "PATCH",
      headers: headers(),
      body: JSON.stringify({ title }),
    });
    if (!response.ok) return;
    if (session.id === sessionId) titleEl.textContent = title;
    await loadSessions();
  }

  async function deleteSession(session) {
    if (!window.confirm(t("delete_confirm", { title: session.title }))) return;
    const response = await fetch(`${API}/sessions/${session.id}`, {
      method: "DELETE",
      headers: headers(),
    });
    if (!response.ok && response.status !== 204) return;
    if (session.id === sessionId) startNewChat();
    else await loadSessions();
  }

  function displayTitle(title) {
    if (!title || ["New Chat", "New chat", "Neuer Chat"].includes(title)) return t("new_chat");
    return title;
  }

  function applySessionTitle(id, title) {
    if (!id || !title) return;
    const labelText = displayTitle(title);
    if (sessionId === id) titleEl.textContent = labelText;
    const row = sessionsEl?.querySelector(`.session-row[data-session-id="${id}"]`);
    const label = row?.querySelector(".item-text");
    if (label) label.textContent = labelText;
  }

  function sessionLabel(text) {
    const label = document.createElement("div");
    label.className = "chats-label";
    label.textContent = text;
    return label;
  }

  function sessionRow(session) {
    const row = document.createElement("div");
    row.className = "session-row";
    row.dataset.sessionId = session.id;
    row.role = "listitem";
    if (session.id === sessionId) titleEl.textContent = displayTitle(session.title);
    const item = document.createElement("ha-list-item-button");
    item.className = "session";
    item.setAttribute("interactive", "");
    item.setAttribute("ha-list-item", "");
    const label = document.createElement("span");
    label.className = "item-text";
    label.slot = "headline";
    label.textContent = displayTitle(session.title);
    item.appendChild(label);
    if (session.id === sessionId) {
      item.classList.add("selected");
      row.classList.add("selected");
    }
    item.addEventListener("click", () => {
      closeSessionMenu();
      closeNavIfOverlay();
      openSession(session.id);
    });
    const more = document.createElement("button");
    more.type = "button";
    more.className = "session-more";
    more.setAttribute("aria-label", "Chat actions");
    more.setAttribute("aria-haspopup", "menu");
    more.setAttribute("aria-expanded", "false");
    const dots = document.createElement("ha-icon");
    dots.setAttribute("icon", "mdi:dots-horizontal");
    more.appendChild(dots);
    more.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openSessionMenu(more, session);
    });
    row.append(item, more);
    return row;
  }

  async function loadSessions() {
    if (compact || !sessionsEl) return;
    closeSessionMenu();
    const response = await fetch(`${API}/sessions`, { headers: headers() });
    if (!response.ok) return;
    const sessions = await response.json();
    const pinned = sessions.filter((session) => session.pinned);
    const rest = sessions.filter((session) => !session.pinned);
    sessionsEl.replaceChildren();
    if (pinned.length) {
      sessionsEl.appendChild(sessionLabel(t("pinned")));
      for (const session of pinned) sessionsEl.appendChild(sessionRow(session));
    }
    sessionsEl.appendChild(sessionLabel(t("chats")));
    for (const session of rest) sessionsEl.appendChild(sessionRow(session));
  }

  async function createSession() {
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
    return session;
  }

  async function openSession(id, fromUrl = false) {
    if (!id) {
      routeGen += 1;
      sessionId = "";
      titleEl.textContent = t("new_chat");
      showEmpty();
      if (!fromUrl) goToSession("");
      await loadSessions();
      return;
    }
    if (fromUrl && id === sessionId) return;
    const gen = ++routeGen;
    const response = await fetch(`${API}/sessions/${id}`, { headers: headers() });
    if (gen !== routeGen) return;
    if (!response.ok) {
      sessionId = "";
      titleEl.textContent = t("new_chat");
      showEmpty();
      goToSession("", true);
      await loadSessions();
      return;
    }
    sessionId = id;
    if (compact) localStorage.setItem("ai_workspace_session", id);
    if (!fromUrl) goToSession(id);
    const session = await response.json();
    titleEl.textContent = displayTitle(session.title);
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

  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let listening = false;
  let speechBase = "";

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || "").split(",")[1] || "");
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function loadBitmap(file) {
    if (typeof createImageBitmap === "function") {
      return createImageBitmap(file);
    }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = reject;
        image.src = url;
      });
      return image;
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function fileToImage(file) {
    if (!file || !isImageFile(file)) return null;
    const bitmap = await loadBitmap(file);
    const scale = Math.min(1, IMAGE_EDGE / Math.max(bitmap.width || 1, bitmap.height || 1));
    const width = Math.max(1, Math.round((bitmap.width || 1) * scale));
    const height = Math.max(1, Math.round((bitmap.height || 1) * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(bitmap, 0, 0, width, height);
    bitmap.close?.();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (!blob || blob.size > MAX_IMAGE_BYTES) return null;
    const data = await blobToBase64(blob);
    if (!data) return null;
    const base = String(file.name || "image").replace(/\.[^.]+$/, "") || "image";
    return { kind: "image", name: `${base}.jpg`, mime: "image/jpeg", data, src: `data:image/jpeg;base64,${data}` };
  }

  function isImageFile(file) {
    const type = String(file?.type || "").toLowerCase();
    if (type.startsWith("image/")) return true;
    return /\.(jpe?g|png|webp|gif)$/i.test(file?.name || "");
  }

  function isTextFile(file) {
    const type = String(file?.type || "").toLowerCase();
    if (TEXT_EXT.test(file?.name || "")) return true;
    if (type.startsWith("text/")) return true;
    return [
      "application/json",
      "application/yaml",
      "application/x-yaml",
      "application/xml",
      "application/toml",
      "application/javascript",
    ].includes(type);
  }

  async function fileToText(file) {
    if (!file || !isTextFile(file)) return null;
    if (file.size > MAX_FILE_BYTES) return { error: "attach_too_large" };
    const text = await file.text();
    if (!text || text.includes("\0") || !text.trim()) return null;
    return {
      kind: "file",
      name: String(file.name || "file.txt").split(/[/\\]/).pop(),
      mime: String(file.type || "text/plain").split(";")[0] || "text/plain",
      text,
    };
  }

  function showAttachNotice(key) {
    if (!bannerEl) return;
    bannerEl.hidden = false;
    bannerEl.textContent = t(key);
    if (attachNoticeTimer) clearTimeout(attachNoticeTimer);
    attachNoticeTimer = window.setTimeout(() => {
      if (bannerEl.textContent === t(key)) {
        bannerEl.hidden = true;
        bannerEl.textContent = "";
      }
    }, 4000);
  }

  function renderThumbs() {
    if (!attachRow) return;
    attachRow.hidden = pending.length === 0;
    attachRow.replaceChildren();
    pending.forEach((item, index) => {
      if (item.kind === "file") {
        const chip = document.createElement("div");
        chip.className = "file-chip pending";
        const name = document.createElement("span");
        name.className = "name";
        name.textContent = item.name;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "thumb-remove";
        remove.setAttribute("aria-label", t("remove_file"));
        remove.textContent = "×";
        remove.addEventListener("click", () => {
          pending.splice(index, 1);
          renderThumbs();
          resizeComposer();
        });
        chip.append(name, remove);
        attachRow.appendChild(chip);
        return;
      }
      const thumb = document.createElement("div");
      thumb.className = "thumb";
      const picture = document.createElement("img");
      picture.src = item.src;
      picture.alt = item.name || "Image";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "thumb-remove";
      remove.setAttribute("aria-label", "Remove image");
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        pending.splice(index, 1);
        renderThumbs();
        resizeComposer();
      });
      thumb.append(picture, remove);
      attachRow.appendChild(thumb);
    });
  }

  async function addFiles(files) {
    let notice = "";
    for (const file of files) {
      if (pending.length >= MAX_ATTACH) break;
      try {
        if (isImageFile(file)) {
          const image = await fileToImage(file);
          if (image) pending.push(image);
          else notice = "attach_unsupported";
        } else if (isTextFile(file)) {
          const item = await fileToText(file);
          if (item?.error) notice = item.error;
          else if (item) pending.push(item);
          else notice = "attach_unsupported";
        } else {
          notice = "attach_unsupported";
        }
      } catch (_err) {
        notice = "attach_unsupported";
      }
    }
    if (notice) showAttachNotice(notice);
    renderThumbs();
    resizeComposer();
  }

  function imageFilesFromClipboard(event) {
    return [...(event.clipboardData?.items || [])]
      .filter((item) => item.kind === "file" && String(item.type || "").startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
  }

  attachBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (streaming || pending.length >= MAX_ATTACH) return;
    fileInput?.click();
  });
  fileInput?.addEventListener("change", async () => {
    await addFiles([...fileInput.files]);
    fileInput.value = "";
  });
  ["dragenter", "dragover"].forEach((name) => {
    box.addEventListener(name, (event) => {
      if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
      event.preventDefault();
      box.classList.add("drop-target");
    });
  });
  box.addEventListener("dragleave", (event) => {
    if (!box.contains(event.relatedTarget)) box.classList.remove("drop-target");
  });
  box.addEventListener("drop", async (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    box.classList.remove("drop-target");
    const files = [...(event.dataTransfer?.files || [])];
    if (files.length) await addFiles(files);
  });
  messageEl.addEventListener("paste", async (event) => {
    const files = imageFilesFromClipboard(event);
    if (!files.length) return;
    event.preventDefault();
    await addFiles(files);
  });

  function speechLanguage() {
    const hass = document.querySelector("home-assistant")?.hass;
    return hass?.locale?.language || hass?.language || navigator.language || "en";
  }

  function stopSpeech() {
    listening = false;
    micBtn?.classList.remove("listening");
    if (micBtn) micBtn.label = t("dictate");
    if (micIcon) micIcon.setAttribute("icon", "mdi:microphone");
    try {
      recognition?.stop();
    } catch (_err) {
      /* already stopped */
    }
  }

  function showMicHelp() {
    if (!bannerEl) return;
    bannerEl.hidden = false;
    bannerEl.textContent = window.isSecureContext ? t("mic_blocked") : t("mic_needs_https");
  }

  function startSpeech() {
    if (!SpeechRecognitionAPI || streaming) return;
    if (!window.isSecureContext) {
      showMicHelp();
      return;
    }
    if (!recognition) {
      recognition = new SpeechRecognitionAPI();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onresult = (event) => {
        let finals = "";
        let interim = "";
        for (let i = 0; i < event.results.length; i += 1) {
          const chunk = event.results[i][0]?.transcript || "";
          if (event.results[i].isFinal) finals += chunk;
          else interim += chunk;
        }
        const parts = [speechBase, finals, interim].filter((part) => String(part).trim());
        messageEl.value = parts.join(" ").replace(/\s+/g, " ").trim();
        if (interim) messageEl.value += " ";
        resizeComposer();
      };
      recognition.onerror = (event) => {
        if (event.error === "not-allowed") {
          if (micBtn) micBtn.label = t("mic_blocked");
          showMicHelp();
        }
        if (event.error !== "no-speech") stopSpeech();
      };
      recognition.onend = () => {
        if (!listening) return;
        try {
          recognition.start();
        } catch (_err) {
          stopSpeech();
        }
      };
    }
    recognition.lang = speechLanguage();
    speechBase = messageEl.value.trim();
    listening = true;
    micBtn.classList.add("listening");
    micBtn.label = t("stop_dictate");
    try {
      recognition.start();
    } catch (_err) {
      stopSpeech();
      showMicHelp();
    }
  }

  if (micBtn && SpeechRecognitionAPI) {
    micBtn.hidden = false;
    micBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (listening) stopSpeech();
      else startSpeech();
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = messageEl.value.trim();
    const attachments = pending.slice();
    const images = attachments.filter((item) => item.kind === "image");
    const files = attachments.filter((item) => item.kind === "file");
    if ((!text && !attachments.length) || streaming) return;
    stopSpeech();
    if (keepComposerFocus()) messageEl.focus();
    else hideKeyboard();
    streaming = true;
    sendBtn.disabled = true;
    routeGen += 1;
    pending = [];
    renderThumbs();
    messageEl.value = "";
    resizeComposer();
    setWelcome(false);
    addBubble("user", text, [
      ...images.map((img) => ({ type: "image", name: img.name, src: img.src })),
      ...files.map((file) => ({ type: "file", name: file.name })),
    ]);
    const assistant = addBubble("assistant", "");
    assistant.classList.add("streaming");
    streamFull = "";
    streamBuf = "";
    const tools = document.createElement("div");
    tools.className = "tools";
    setActivity(assistant, t("thinking"));
    try {
      if (!sessionId) {
        await createSession();
        titleEl.textContent = (text || attachments[0]?.name || "File").slice(0, 80);
      }
      setStatus(t("thinking"));
      const payload = JSON.stringify({
          message: text,
          origin: window.location.origin,
          page: haPageContext(),
          images: images.map((img) => ({ name: img.name, mime: img.mime, data: img.data })),
          files: files.map((file) => ({ name: file.name, mime: file.mime, text: file.text })),
        });
      let response = await fetch(`${API}/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: headers(),
        body: payload,
      });
      if (response.status === 404) {
        await createSession();
        titleEl.textContent = (text || attachments[0]?.name || "File").slice(0, 80);
        response = await fetch(`${API}/sessions/${sessionId}/chat`, {
          method: "POST",
          headers: headers(),
          body: payload,
        });
      }
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
          revealAllNow();
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
          if (data.answer) queueStreamAnswer(data.answer);
          settleTools(assistant);
          setActivity(assistant, "");
          streaming = false;
          resizeComposer();
        } else if (name === "title" && data.title) {
          applySessionTitle(sessionId, data.title);
        }
        scrollChatToBottom();
      });
      await waitForStream();
      streamNode = null;
      await loadSessions();
    } catch (error) {
      revealAllNow();
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
      syncCopyChat();
      resizeComposer();
      if (keepComposerFocus()) messageEl.focus();
      else hideKeyboard();
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

  function startNewChat() {
    routeGen += 1;
    sessionId = "";
    pending = [];
    renderThumbs();
    if (compact) localStorage.removeItem("ai_workspace_session");
    closeNavIfOverlay();
    goToSession("");
    titleEl.textContent = t("new_chat");
    showEmpty();
    loadSessions();
    messageEl.focus();
  }

  root.querySelectorAll(".nav-toggle").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      toggleNav();
    });
  });
  scrim?.addEventListener("click", () => {
    closeSessionMenu();
    setNavOpen(false);
  });
  wrap.addEventListener("click", (event) => {
    if (!sessionMenu) return;
    const path = event.composedPath();
    if (path.includes(sessionMenu) || path.some((node) => node.classList?.contains("session-more"))) return;
    closeSessionMenu();
  });
  sessionsEl?.addEventListener("scroll", closeSessionMenu, { passive: true });
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (sessionMenu) {
      closeSessionMenu();
      return;
    }
    if (wrap.classList.contains("nav-open")) setNavOpen(false);
  });
  mqNarrow.addEventListener("change", () => setNarrow(options.narrow));

  logEl.addEventListener("click", (event) => {
    const link = event.composedPath().find((node) => node && node.tagName === "A");
    if (!link) return;
    const href = link.getAttribute("href") || "";
    if (!href || href.startsWith("#") || href.startsWith("mailto:")) return;
    const path = haLinkPath(href);
    if (!path) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    retargetLink(link);
    openHaPath(path);
  }, true);

  root.querySelector(".new-chat")?.addEventListener("click", startNewChat);
  root.querySelector(".new-chat-icon")?.addEventListener("click", startNewChat);

  if (!compact && routed) {
    window.addEventListener("location-changed", applyRoute);
    window.addEventListener("popstate", applyRoute);
  }

  loadProviders();
  const startId = compact ? localStorage.getItem("ai_workspace_session") || "" : sessionIdFromPath();
  if (startId) openSession(startId, true);
  else {
    showEmpty();
    loadSessions();
  }
  resizeComposer();
  const linkWatch = new MutationObserver(() => retargetHaLinks(logEl));
  linkWatch.observe(logEl, { subtree: true, childList: true, attributes: true, attributeFilter: ["href", "target"] });
  return { openSession, applyRoute, setNarrow, toggleNav, startNewChat };
}
