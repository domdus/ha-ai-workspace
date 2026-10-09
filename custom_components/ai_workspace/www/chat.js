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
  if (HELPER_DOMAINS.has(domain)) return `/config/entities/entity/${entityId}`;
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
    if (HELPER_DOMAINS.has(domain)) return `/config/entities/entity/${entityId}`;
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

function escapeRe(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function rememberUniqueName(map, name, path) {
  const text = String(name || "").trim();
  if (text.length < 3) return;
  const key = text.toLowerCase();
  const prev = map.get(key);
  if (prev && prev.path !== path) map.set(key, null);
  else if (!prev) map.set(key, { name: text, path });
}

function haLinkCatalog() {
  const names = [];
  const ids = [];
  const hass = hassObj();
  if (!hass) return { names, ids };
  const nameToPath = new Map();
  for (const [entityId, state] of Object.entries(hass.states || {})) {
    const info = { entityId, state, entry: hass.entities?.[entityId] };
    const path = pathForEntity(entityId, info);
    ids.push({ match: entityId, path });
    rememberUniqueName(nameToPath, state?.attributes?.friendly_name, path);
  }
  for (const device of Object.values(hass.devices || {})) {
    const id = device?.id;
    if (!id) continue;
    const path = `/config/devices/device/${id}`;
    rememberUniqueName(nameToPath, device.name_by_user || device.name, path);
  }
  for (const row of nameToPath.values()) {
    if (row) names.push(row);
  }
  names.sort((a, b) => b.name.length - a.name.length);
  ids.sort((a, b) => b.match.length - a.match.length);
  return { names, ids };
}

function linkifyHaPaths(text) {
  // Bare HA UI paths the model sometimes writes without Markdown, e.g. /lovelace/media
  return String(text || "").replace(
    /(?<![\w./#\u0000[])(\/(?:config|lovelace|dashboard|history|logbook|developer-tools|profile|media-browser|energy|map|todo|ai-workspace|hassio|supervisor)[^\s)\]<>"'`]*)/g,
    (raw) => {
      let path = raw;
      while (/[.,;:!?]$/.test(path)) path = path.slice(0, -1);
      const base = path.split(/[?#]/)[0];
      if (!haAppPath(base)) return raw;
      return `[${path}](${path})${raw.slice(path.length)}`;
    },
  );
}

function linkifyHaMentions(content) {
  let text = String(content || "");
  if (!text) return text;
  const held = [];
  const hold = (chunk) => {
    const token = `\u0000HA${held.length}\u0000`;
    held.push(chunk);
    return token;
  };
  text = text.replace(/```[\s\S]*?```/g, hold);
  text = text.replace(/`[^`\n]+`/g, hold);
  text = text.replace(/\[[^\]]+\]\([^)\s]+\)/g, hold);
  text = linkifyHaPaths(text);
  text = text.replace(/\[[^\]]+\]\([^)\s]+\)/g, hold);
  const { names, ids } = haLinkCatalog();
  for (const item of names) {
    const re = new RegExp(`(?<![\\w./#\\u0000])${escapeRe(item.name)}(?![\\w./\\u0000])`, "gi");
    text = text.replace(re, (matched) => hold(`[${matched}](${item.path})`));
  }
  for (const item of ids) {
    const re = new RegExp(`(?<![\\w./#\\u0000])${escapeRe(item.match)}(?![\\w./\\u0000])`, "g");
    text = text.replace(re, (matched) => hold(`[${matched}](${item.path})`));
  }
  return text.replace(/\u0000HA(\d+)\u0000/g, (_m, index) => held[Number(index)] || "");
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
        <ha-button class="new-chat" size="s">
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
            <button type="button" class="scroll-bottom" tabindex="-1" aria-label="${t("scroll_to_bottom")}">
              <ha-icon icon="mdi:arrow-down"></ha-icon>
            </button>
            <div class="composer-box">
              <div class="next-row" hidden>
                <p class="next-copy"></p>
                <button type="button" class="next-remove"></button>
              </div>
              <div class="attach-row" hidden></div>
              <div class="composer-row">
              <label class="sr" for="ai-message">${t("message")}</label>
              <textarea id="ai-message" class="message" rows="1" placeholder="${t("placeholder")}"></textarea>
              <div class="composer-actions">
              <input class="file-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif,.yaml,.yml,.json,.txt,.md,.csv,.xml,.toml,.html,.css,.js,.ts,.py,.log,.cfg,.ini,.conf" multiple hidden>
              <ha-icon-button class="attach" type="button" label="${t("attach")}">
                <ha-icon icon="mdi:paperclip"></ha-icon>
              </ha-icon-button>
              <ha-icon-button class="mic" type="button" label="${t("dictate")}" hidden>
                <ha-icon icon="mdi:microphone"></ha-icon>
              </ha-icon-button>
              <ha-button class="send" size="s" appearance="accent" aria-label="${t("send")}">
                <ha-icon icon="mdi:arrow-up"></ha-icon>
              </ha-button>
              </div>
              </div>
            </div>
            <div class="agent-picker" hidden>
              <button type="button" class="agent-trigger" aria-haspopup="listbox" aria-expanded="false" aria-label="${t("agent")}">
                <span class="agent-trigger-label"></span>
                <ha-icon icon="mdi:chevron-down"></ha-icon>
              </button>
              <div class="agent-menu" role="listbox" hidden></div>
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
  const scrollBottomBtn = root.querySelector(".scroll-bottom");
  const messageEl = root.querySelector(".message");
  const sendBtn = root.querySelector(".send");
  const agentPicker = root.querySelector(".agent-picker");
  const agentTrigger = root.querySelector(".agent-trigger");
  const agentLabel = root.querySelector(".agent-trigger-label");
  const agentMenu = root.querySelector(".agent-menu");
  const micBtn = root.querySelector(".mic");
  const micIcon = micBtn?.querySelector("ha-icon");
  const attachBtn = root.querySelector(".attach");
  const fileInput = root.querySelector(".file-input");
  const attachRow = root.querySelector(".attach-row");
  const nextRow = root.querySelector(".next-row");
  const nextCopy = root.querySelector(".next-copy");
  const nextRemove = root.querySelector(".next-remove");
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
      abandonStream();
      sessionId = "";
      titleEl.textContent = t("new_chat");
      showEmpty();
      loadSessions();
    }
  }
  let streaming = false;
  let nextTurn = null;
  const MAX_ATTACH = 4;
  const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
  const MAX_FILE_BYTES = 256 * 1024;
  const IMAGE_EDGE = 1280;
  const TEXT_EXT = /\.(ya?ml|json|toml|ini|cfg|conf|env|txt|md|markdown|csv|tsv|xml|html?|css|js|mjs|cjs|tsx?|jsx|py|sh|bash|sql|log)$/i;
  let pending = [];
  let attachNoticeTimer = 0;
  let micNoticeTimer = 0;
  let pinBottom = true;
  let jumping = false;
  let jumpTimer = 0;
  let lastScrollTop = 0;
  let followRaf = 0;
  let followLast = 0;
  let motionTimer = 0;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function resizeComposer() {
    const holdTop = !pinBottom ? chatEl.scrollTop : null;
    messageEl.style.height = "auto";
    messageEl.style.height = `${Math.min(Math.max(messageEl.scrollHeight, 36), 160)}px`;
    const hasDraft = Boolean(messageEl.value.trim() || pending.length);
    sendBtn.disabled = !hasDraft;
    if (attachBtn) attachBtn.disabled = pending.length >= MAX_ATTACH;
    messageEl.placeholder = streaming ? t("placeholder_next") : t("placeholder");
    if (holdTop != null) chatEl.scrollTop = holdTop;
    else if (pinBottom) stickToBottom();
  }

  function keepComposerFocus() {
    return window.matchMedia("(pointer: fine)").matches && !mqNarrow.matches;
  }

  function hideKeyboard() {
    messageEl.blur();
    sendBtn.blur();
    const active = document.activeElement;
    if (active && active !== document.body && typeof active.blur === "function") active.blur();
    clearKeyboardLock();
  }

  function composerFocused() {
    return root.activeElement === messageEl || messageEl.matches(":focus");
  }

  let pinningScroll = false;

  function resetOuterScroll() {
    if (pinningScroll) return;
    pinningScroll = true;
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    let node = root.host || null;
    while (node) {
      if (node.scrollTop) node.scrollTop = 0;
      const next = node.parentElement || node.getRootNode?.()?.host || null;
      node = next === node ? null : next;
    }
    pinningScroll = false;
  }

  function clearKeyboardLock() {
    wrap.classList.remove("keyboard-open");
    wrap.style.height = "";
  }

  function syncKeyboardInset() {
    if (keepComposerFocus()) return;
    const vv = window.visualViewport;
    const inset = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
    const open = composerFocused() && inset > 80;
    if (!open) {
      clearKeyboardLock();
      return;
    }
    resetOuterScroll();
    const top = wrap.getBoundingClientRect().top;
    const visibleBottom = (vv?.offsetTop || 0) + (vv?.height || window.innerHeight);
    const available = Math.max(180, visibleBottom - Math.max(0, top));
    wrap.classList.add("keyboard-open");
    wrap.style.height = `${Math.round(available)}px`;
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
    if (chatEl.classList.contains("welcome") === want) {
      syncScrollBottomBtn();
      return;
    }
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
        syncScrollBottomBtn();
        return;
      }
    }
    chatEl.classList.toggle("welcome", want);
    clearMotion();
    syncScrollBottomBtn();
  }

  function overlayOpen() {
    if (!compact) return true;
    return Boolean(root.parentElement?.classList.contains("open"));
  }

  function chatVisible() {
    return overlayOpen() && document.visibilityState !== "hidden";
  }

  async function apiFetch(url, options = {}) {
    const hass = hassObj();
    const auth = hass?.auth;
    if (typeof hass?.fetchWithAuth === "function") {
      try {
        return await hass.fetchWithAuth(url, options);
      } catch (_err) {
        return null;
      }
    }
    try {
      if (auth?.expired && typeof auth.refreshAccessToken === "function") {
        await auth.refreshAccessToken();
      }
    } catch (_err) {
      return null;
    }
    if (auth?.expired) return null;
    const token = auth?.data?.access_token || auth?.accessToken || getToken();
    if (!token) return null;
    return fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(options.headers || {}),
      },
    });
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

  function ensureActivitySlot(bubble) {
    let el = bubble.querySelector(".activity");
    if (!el) {
      el = document.createElement("p");
      el.className = "activity idle";
      el.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = "\u00a0";
      el.appendChild(label);
      bubble.appendChild(el);
    }
    // Keep the status chip under tools and text so it never shifts the answer.
    if (el.parentElement !== bubble || bubble.lastElementChild !== el) {
      bubble.appendChild(el);
    }
    return el;
  }

  function setActivity(bubble, text) {
    if (!bubble) return;
    const pretty = prettyStatus(text);
    const el = ensureActivitySlot(bubble);
    let label = el.querySelector(".label");
    if (!label) {
      label = document.createElement("span");
      label.className = "label";
      el.replaceChildren(label);
    }
    if (!pretty) {
      // Keep the line height while streaming so show/hide does not jump the scroll.
      el.className = "activity idle";
      el.setAttribute("aria-hidden", "true");
      label.textContent = "\u00a0";
      if (!bubble.classList.contains("streaming")) el.remove();
      return;
    }
    el.className = "activity shine";
    el.removeAttribute("aria-hidden");
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
    return linkifyHaMentions(text);
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
    const chips = (events || []).filter(
      (event) => event && event.type !== "image" && event.type !== "file" && event.type !== "error",
    );
    if ((events || []).some((event) => event && event.type === "error")) bubble.classList.add("error");
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

  function distanceFromBottom() {
    return chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight;
  }

  function nearBottom() {
    return distanceFromBottom() < 32;
  }

  let scrollLock = 0;

  function writeScrollTop(value) {
    scrollLock += 1;
    chatEl.scrollTop = value;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        scrollLock = Math.max(0, scrollLock - 1);
      });
    });
  }

  function releaseFollow() {
    pinBottom = false;
    jumping = false;
    if (jumpTimer) {
      window.clearTimeout(jumpTimer);
      jumpTimer = 0;
    }
    if (followRaf) {
      cancelAnimationFrame(followRaf);
      followRaf = 0;
    }
    chatEl.scrollTop = chatEl.scrollTop;
    syncScrollBottomBtn();
  }

  function syncScrollBottomBtn() {
    if (!scrollBottomBtn) return;
    const overflow = chatEl.scrollHeight - chatEl.clientHeight;
    const far = overflow > 48 && distanceFromBottom() > 72;
    if (!far || !pinBottom) jumping = false;
    const show = !chatEl.classList.contains("welcome") && far && !jumping;
    scrollBottomBtn.classList.toggle("is-visible", show);
    scrollBottomBtn.setAttribute("aria-hidden", show ? "false" : "true");
  }

  function stickToBottom() {
    if (!pinBottom) {
      syncScrollBottomBtn();
      return;
    }
    writeScrollTop(Math.max(0, chatEl.scrollHeight - chatEl.clientHeight));
    lastScrollTop = chatEl.scrollTop;
    syncScrollBottomBtn();
  }

  function jumpToBottom() {
    pinBottom = true;
    jumping = true;
    syncScrollBottomBtn();
    if (followRaf) {
      cancelAnimationFrame(followRaf);
      followRaf = 0;
    }
    const max = Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
    if (reduceMotion) {
      writeScrollTop(max);
      lastScrollTop = chatEl.scrollTop;
      jumping = false;
      syncScrollBottomBtn();
      return;
    }
    const finish = () => {
      if (jumpTimer) {
        window.clearTimeout(jumpTimer);
        jumpTimer = 0;
      }
      chatEl.removeEventListener("scrollend", finish);
      jumping = false;
      lastScrollTop = chatEl.scrollTop;
      if (pinBottom) writeScrollTop(Math.max(0, chatEl.scrollHeight - chatEl.clientHeight));
      syncScrollBottomBtn();
    };
    chatEl.addEventListener("scrollend", finish, { once: true });
    if (jumpTimer) window.clearTimeout(jumpTimer);
    jumpTimer = window.setTimeout(finish, 900);
    chatEl.scrollTo({ top: max, behavior: "smooth" });
  }

  let streamNode = null;
  let streamBuf = "";
  let streamFull = "";
  let streamDrainRaf = 0;
  let streamDrainLast = 0;
  let streamWaiters = [];
  let streamToken = 0;
  let streamAbort = null;

  function renderNext() {
    if (!nextRow || !nextCopy) return;
    if (!nextTurn) {
      nextRow.hidden = true;
      nextCopy.replaceChildren();
      return;
    }
    const names = nextTurn.attachments.map((item) => item.name).filter(Boolean);
    const label = [nextTurn.text, names.join(", ")].filter(Boolean).join(" · ");
    const text = document.createElement("span");
    text.className = "next-text";
    text.textContent = label;
    const hint = document.createElement("span");
    hint.className = "next-hint";
    hint.textContent = t("queued_hint");
    nextCopy.replaceChildren(text, hint);
    if (nextRemove) {
      nextRemove.textContent = t("queued_remove");
      nextRemove.setAttribute("aria-label", t("queued_remove"));
    }
    nextRow.hidden = false;
  }

  function queueTurn(text, attachments) {
    nextTurn = { text, attachments: attachments.slice() };
    pending = [];
    messageEl.value = "";
    stopSpeech();
    renderThumbs();
    renderNext();
    resizeComposer();
    if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
  }

  function flushNext() {
    if (!nextTurn || streaming) return;
    const turn = nextTurn;
    nextTurn = null;
    renderNext();
    messageEl.value = turn.text;
    pending = turn.attachments.slice();
    renderThumbs();
    form.requestSubmit();
  }

  function abandonStream() {
    streamToken += 1;
    if (streamAbort) {
      streamAbort.abort();
      streamAbort = null;
    }
    if (streamDrainRaf) {
      cancelAnimationFrame(streamDrainRaf);
      streamDrainRaf = 0;
    }
    streamBuf = "";
    streamFull = "";
    streamNode = null;
    const waiters = streamWaiters;
    streamWaiters = [];
    waiters.forEach((fn) => fn());
    streaming = false;
    liveStream = false;
    nextTurn = null;
    renderNext();
    resizeComposer();
  }

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
        jumping = false;
        syncScrollBottomBtn();
        return;
      }
      if (dist <= 0.5) {
        writeScrollTop(max);
      } else {
        const k = streaming || streamBuf ? 2.6 : 10;
        const alpha = 1 - Math.exp(-dt * k);
        let step = dist * alpha;
        if (streaming || streamBuf) step = Math.min(step, Math.max(6, dist * 0.16));
        writeScrollTop(chatEl.scrollTop + step);
      }
      followRaf = requestAnimationFrame(tick);
    };
    followRaf = requestAnimationFrame(tick);
  }

  function scrollChatToBottom(smooth = true) {
    if (!pinBottom) {
      syncScrollBottomBtn();
      return;
    }
    if (!smooth || reduceMotion) {
      if (followRaf) {
        cancelAnimationFrame(followRaf);
        followRaf = 0;
      }
      writeScrollTop(Math.max(0, chatEl.scrollHeight - chatEl.clientHeight));
      syncScrollBottomBtn();
      return;
    }
    followBottom();
    syncScrollBottomBtn();
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
  let agentId = "";
  let voice = { dictate: true, stt: "browser", speak: false };

  function selectedAgent() {
    return agentId || defaultProvider;
  }

  function closeAgentMenu() {
    if (!agentMenu || !agentTrigger) return;
    agentMenu.hidden = true;
    agentTrigger.setAttribute("aria-expanded", "false");
  }

  function agentChoices(items) {
    return items.filter((item) => item.available);
  }

  async function loadProviders() {
    const response = await apiFetch(`${API}/providers`);
    if (!response?.ok) return;
    const items = await response.json();
    const ready = agentChoices(items);
    const previous = agentId || localStorage.getItem("ai_workspace_agent") || "";
    const pick = ready.find((item) => item.id === previous) || ready[0];
    agentId = pick?.id || "";
    if (agentPicker && agentMenu && agentLabel) {
      agentPicker.hidden = ready.length < 2;
      agentLabel.textContent = pick?.label || "";
      agentMenu.replaceChildren();
      for (const item of items) {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "agent-option";
        option.setAttribute("role", "option");
        option.dataset.id = item.id;
        option.disabled = !item.available;
        option.setAttribute("aria-selected", item.id === agentId ? "true" : "false");
        const name = document.createElement("span");
        name.className = "agent-option-name";
        name.textContent = item.label;
        option.appendChild(name);
        if (item.id === agentId) {
          const mark = document.createElement("ha-icon");
          mark.setAttribute("icon", "mdi:check");
          option.appendChild(mark);
        }
        option.addEventListener("click", () => {
          if (!item.available) return;
          agentId = item.id;
          localStorage.setItem("ai_workspace_agent", agentId);
          defaultProvider = agentId;
          agentLabel.textContent = item.label;
          for (const other of agentMenu.querySelectorAll(".agent-option")) {
            const on = other.dataset.id === agentId;
            other.setAttribute("aria-selected", on ? "true" : "false");
            const mark = other.querySelector("ha-icon");
            if (on && !mark) {
              const icon = document.createElement("ha-icon");
              icon.setAttribute("icon", "mdi:check");
              other.appendChild(icon);
            } else if (!on && mark) {
              mark.remove();
            }
          }
          closeAgentMenu();
        });
        agentMenu.appendChild(option);
      }
    }
    const chosen = items.find((item) => item.id === selectedAgent()) || ready[0] || items[0];
    if (chosen?.id) defaultProvider = chosen.id;
    if (chosen && !chosen.available) {
      clearMicHelp();
      bannerEl.hidden = false;
      bannerEl.textContent = chosen.reason || t("configure_provider");
    } else if (bannerEl && !bannerEl.classList.contains("hold") && !bannerEl.classList.contains("mic-help")) {
      bannerEl.hidden = true;
      bannerEl.textContent = "";
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
    const response = await apiFetch(`${API}/sessions/${session.id}`, {
      method: "PATCH",
      body: JSON.stringify({ pinned }),
    });
    if (!response?.ok) {
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
    const response = await apiFetch(`${API}/sessions/${session.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    if (!response?.ok) return;
    if (session.id === sessionId) titleEl.textContent = title;
    await loadSessions();
  }

  async function deleteSession(session) {
    if (!window.confirm(t("delete_confirm", { title: session.title }))) return;
    const response = await apiFetch(`${API}/sessions/${session.id}`, { method: "DELETE" });
    if (!response || (!response.ok && response.status !== 204)) return;
    if (session.id === sessionId) startNewChat();
    else await loadSessions();
  }

  function displayTitle(title) {
    if (!title || ["New Chat", "New chat", "Neuer Chat"].includes(title)) return t("new_chat");
    return title;
  }

  function promptTitle(text) {
    const clean = String(text || "")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/[*_`#]+/g, "")
      .replace(/[?!.]+$/g, "");
    if (!clean) return "";
    const words = clean.split(" ");
    if (clean.length > 50 || words.length > 8) return "";
    return clean;
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
    dots.setAttribute("icon", "mdi:dots-vertical");
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
    const response = await apiFetch(`${API}/sessions`);
    if (!response?.ok) return;
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
    const mark = streamToken;
    const created = await apiFetch(`${API}/sessions`, {
      method: "POST",
      body: JSON.stringify({ provider: selectedAgent() }),
    });
    if (!created?.ok) throw new Error(created ? await created.text() : "Not signed in");
    const session = await created.json();
    if (mark !== streamToken) return null;
    sessionId = session.id;
    goToSession(sessionId, true);
    if (compact) localStorage.setItem("ai_workspace_session", sessionId);
    return session;
  }

  async function openSession(id, fromUrl = false) {
    if (id !== sessionId) abandonStream();
    watchGen += 1;
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
    const response = await apiFetch(`${API}/sessions/${id}`);
    if (gen !== routeGen) return;
    if (!response?.ok) {
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
    paintSession(session);
    await loadSessions();
    if (session.pending) watchPending(id);
  }

  function paintSession(session) {
    clearMicHelp();
    titleEl.textContent = displayTitle(session.title);
    logEl.replaceChildren();
    const messages = session.messages || [];
    if (!messages.length) showEmpty();
    else setWelcome(false, false);
    for (const message of messages) {
      addBubble(message.role, message.content, message.events, { animate: false, follow: false });
    }
    pinBottom = true;
    stickToBottom();
    requestAnimationFrame(() => requestAnimationFrame(stickToBottom));
    window.setTimeout(stickToBottom, 50);
    window.setTimeout(stickToBottom, 250);
    window.setTimeout(stickToBottom, 700);
  }

  function needsPaint(session) {
    const messages = session.messages || [];
    const bubbles = [...logEl.querySelectorAll(".bubble")];
    if (bubbles.length !== messages.length) return true;
    if (!messages.length) return false;
    const lastBubble = bubbles[bubbles.length - 1];
    if (lastBubble.classList.contains("streaming") || lastBubble.classList.contains("error")) return true;
    const node = lastBubble.querySelector(".text");
    const shown = String(node?.content || node?.textContent || "").trim();
    const stored = String(messages[messages.length - 1].content || "").trim();
    if (!stored) return Boolean(shown);
    return shown.length + 8 < stored.length;
  }

  function ensureThinkingBubble() {
    let bubble = logEl.querySelector(".bubble.assistant.streaming");
    if (!bubble) {
      bubble = addBubble("assistant", "", [], { animate: false, follow: false });
      bubble.classList.add("streaming");
    }
    bubble.classList.remove("error");
    ensureActivitySlot(bubble);
    if (!bubble.querySelector(".text")?.content) setActivity(bubble, t("thinking"));
    streaming = true;
    resizeComposer();
  }

  function isDisconnect(error) {
    const name = String(error?.name || "");
    const message = String(error?.message || error || "");
    return name === "AbortError" || /failed to fetch|load failed|network|abort|cancel|disconnected|reset/i.test(message);
  }

  let watchGen = 0;
  let liveStream = false;

  async function watchPending(id) {
    if (!id || liveStream || !chatVisible()) return false;
    const gen = ++watchGen;
    for (let attempt = 0; attempt < 240; attempt += 1) {
      if (gen !== watchGen || sessionId !== id || liveStream || !chatVisible()) return false;
      let session;
      try {
        const pendingResponse = await apiFetch(`${API}/sessions/${id}`);
        if (gen !== watchGen || sessionId !== id || liveStream) return false;
        if (!pendingResponse?.ok) return false;
        session = await pendingResponse.json();
      } catch (error) {
        if (!isDisconnect(error) && attempt > 2) return false;
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        continue;
      }
      if (session.pending) {
        ensureThinkingBubble();
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        continue;
      }
      if (needsPaint(session)) paintSession(session);
      else {
        const live = logEl.querySelector(".bubble.assistant.streaming");
        if (live) {
          live.classList.remove("streaming");
          setActivity(live, "");
        }
      }
      streaming = false;
      resizeComposer();
      syncCopyChat();
      await loadSessions();
      return true;
    }
    return false;
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
    if (pending.length >= MAX_ATTACH) return;
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

  function clearMicHelp() {
    if (micNoticeTimer) {
      clearTimeout(micNoticeTimer);
      micNoticeTimer = 0;
    }
    if (!bannerEl?.classList.contains("mic-help")) return;
    bannerEl.classList.remove("mic-help");
    bannerEl.hidden = true;
    bannerEl.textContent = "";
  }

  function showMicHelp() {
    if (!bannerEl) return;
    bannerEl.classList.add("mic-help");
    bannerEl.hidden = false;
    bannerEl.textContent = window.isSecureContext ? t("mic_blocked") : t("mic_needs_https");
    if (micNoticeTimer) clearTimeout(micNoticeTimer);
    micNoticeTimer = window.setTimeout(() => {
      clearMicHelp();
    }, 6000);
  }

  function startSpeech() {
    if (!SpeechRecognitionAPI || micBtn?.hidden) return;
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

  agentTrigger?.addEventListener("click", () => {
    if (!agentMenu) return;
    const open = agentMenu.hidden;
    agentMenu.hidden = !open;
    agentTrigger.setAttribute("aria-expanded", open ? "true" : "false");
  });
  root.addEventListener("click", (event) => {
    if (!agentPicker || agentPicker.hidden || agentMenu?.hidden) return;
    if (event.composedPath().includes(agentPicker)) return;
    closeAgentMenu();
  });
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAgentMenu();
  });

  let capture = null;
  let replyAudio = null;

  function encodeWav(chunks, sampleRate) {
    const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const buffer = new ArrayBuffer(44 + length * 2);
    const view = new DataView(buffer);
    const write = (offset, text) => {
      for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
    };
    write(0, "RIFF");
    view.setUint32(4, 36 + length * 2, true);
    write(8, "WAVE");
    write(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    write(36, "data");
    view.setUint32(40, length * 2, true);
    let offset = 44;
    for (const chunk of chunks) {
      for (let i = 0; i < chunk.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, chunk[i]));
        view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
        offset += 2;
      }
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  async function startEngineSpeech() {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      showMicHelp();
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const gain = ctx.createGain();
    gain.gain.value = 0;
    const chunks = [];
    proc.onaudioprocess = (event) => {
      chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    };
    source.connect(proc);
    proc.connect(gain);
    gain.connect(ctx.destination);
    listening = true;
    micBtn.classList.add("listening");
    micBtn.label = t("stop_dictate");
    capture = {
      async stop() {
        proc.disconnect();
        source.disconnect();
        stream.getTracks().forEach((track) => track.stop());
        await ctx.close();
        return encodeWav(chunks, ctx.sampleRate || 16000);
      },
    };
  }

  async function finishEngineSpeech() {
    const active = capture;
    capture = null;
    stopSpeech();
    if (!active) return;
    let wav;
    try {
      wav = await active.stop();
    } catch (_err) {
      showMicHelp();
      return;
    }
    const response = await apiFetch(`${API}/stt`, {
      method: "POST",
      headers: { "Content-Type": "audio/wav", "X-Speech-Language": speechLanguage() },
      body: wav,
    });
    if (!response?.ok) {
      showMicHelp();
      return;
    }
    const body = await response.json();
    const said = String(body.text || "").trim();
    if (!said) return;
    const base = messageEl.value.trim();
    messageEl.value = [base, said].filter(Boolean).join(" ");
    resizeComposer();
  }

  async function speakReply(text) {
    if (!voice.speak || !String(text || "").trim()) return;
    try {
      const response = await apiFetch(`${API}/tts`, {
        method: "POST",
        body: JSON.stringify({ text, language: speechLanguage() }),
      });
      if (!response?.ok) return;
      const body = await response.json();
      if (!body.url) return;
      replyAudio?.pause();
      replyAudio = new Audio(body.url);
      await replyAudio.play();
    } catch (_err) {
      /* playback can be blocked until the next tap */
    }
  }

  if (micBtn) {
    micBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const engine = voice.stt && voice.stt !== "browser";
      if (listening) {
        if (engine) finishEngineSpeech();
        else stopSpeech();
        return;
      }
      if (engine) {
        startEngineSpeech().catch(() => showMicHelp());
        return;
      }
      startSpeech();
    });
  }

  function setMicShown(show) {
    if (!micBtn) return;
    const browserOnly = !voice.stt || voice.stt === "browser";
    const visible = Boolean(show) && !(browserOnly && !SpeechRecognitionAPI);
    micBtn.classList.toggle("is-hidden", !visible);
    if (visible) micBtn.removeAttribute("hidden");
    else micBtn.setAttribute("hidden", "");
    micBtn.hidden = !visible;
    if (!visible) stopSpeech();
  }

  async function loadDictate() {
    if (!micBtn) return;
    // Stay hidden until /ui explicitly allows the mic (also covers the overlay drawer).
    let show = false;
    try {
      const response = await apiFetch(`${API}/ui`);
      if (response?.ok) {
        const body = await response.json();
        show = body.dictate === true;
        voice = {
          dictate: show,
          stt: body.stt || "browser",
          speak: body.speak === true,
        };
      }
    } catch (_err) {
      show = false;
    }
    setMicShown(show);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    let text = messageEl.value.trim();
    let attachments = pending.slice();
    if (streaming) {
      if (!text && !attachments.length) return;
      queueTurn(text, attachments);
      return;
    }
    if (!text && !attachments.length) {
      if (!nextTurn) return;
      text = nextTurn.text;
      attachments = nextTurn.attachments.slice();
      nextTurn = null;
      renderNext();
      messageEl.value = text;
      pending = attachments.slice();
    }
    const images = attachments.filter((item) => item.kind === "image");
    const files = attachments.filter((item) => item.kind === "file");
    if (!text && !attachments.length) return;
    abandonStream();
    const token = streamToken;
    const abort = new AbortController();
    streamAbort = abort;
    stopSpeech();
    if (keepComposerFocus()) messageEl.focus();
    else hideKeyboard();
    streaming = true;
    watchGen += 1;
    clearKeyboardLock();
    resetOuterScroll();
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
    ensureActivitySlot(assistant);
    setActivity(assistant, t("thinking"));
    let recover = false;
    let sawDone = false;
    let chatId = "";
    liveStream = true;
    try {
      if (!sessionId) {
        const created = await createSession();
        if (token !== streamToken || !created) return;
        titleEl.textContent = promptTitle(text) || attachments[0]?.name || t("new_chat");
      }
      if (token !== streamToken) return;
      chatId = sessionId;
      setStatus(t("thinking"));
      const payload = JSON.stringify({
          message: text,
          origin: window.location.origin,
          language: speechLanguage(),
          page: haPageContext(),
          images: images.map((img) => ({ name: img.name, mime: img.mime, data: img.data })),
          files: files.map((file) => ({ name: file.name, mime: file.mime, text: file.text })),
          agent: selectedAgent(),
        });
      let response = await apiFetch(`${API}/sessions/${chatId}/chat`, {
        method: "POST",
        body: payload,
        signal: abort.signal,
      });
      if (!response || token !== streamToken) return;
      if (response.status === 404) {
        const created = await createSession();
        if (token !== streamToken || !created) return;
        titleEl.textContent = promptTitle(text) || attachments[0]?.name || t("new_chat");
        response = await apiFetch(`${API}/sessions/${sessionId}/chat`, {
          method: "POST",
          body: payload,
          signal: abort.signal,
        });
        if (!response) return;
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
        if (token !== streamToken) return;
        if (name === "text") {
          appendAssistantText(assistant.querySelector(".text"), data.delta || "");
          return;
        }
        if (name === "tool" && data.text) {
          if (!tools.parentElement) {
            const textNode = assistant.querySelector(".text");
            if (textNode) assistant.insertBefore(tools, textNode);
            else assistant.appendChild(tools);
          }
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
          sawDone = true;
          if (data.answer) queueStreamAnswer(data.answer);
          settleTools(assistant);
          setActivity(assistant, "");
        } else if (name === "title" && data.title) {
          applySessionTitle(chatId, data.title);
        }
        scrollChatToBottom();
      });
      await waitForStream();
      streamNode = null;
      if (!sawDone) recover = true;
      else {
        await loadSessions();
        await speakReply(streamFull);
      }
    } catch (error) {
      if (token !== streamToken) return;
      if (chatId && (isDisconnect(error) || document.visibilityState === "hidden") && sessionId === chatId) {
        recover = true;
        assistant.classList.remove("error");
        setActivity(assistant, t("thinking"));
      } else {
        revealAllNow();
        assistant.classList.add("error");
        const node = assistant.querySelector(".text");
        if (!streamFull) {
          node.content = String(error?.message || error);
          node.hidden = !node.content;
          assistant.classList.add("has-text");
        }
        settleTools(assistant);
        setActivity(assistant, "");
      }
    } finally {
      if (token !== streamToken) return;
      liveStream = false;
      let followUp = true;
      if (recover && sessionId === chatId) {
        assistant.classList.remove("error");
        const found = await watchPending(chatId);
        followUp = found;
        if (!found) {
          streaming = false;
          assistant.classList.remove("streaming");
          setActivity(assistant, "");
          if (!streamFull) {
            assistant.classList.add("error");
            const node = assistant.querySelector(".text");
            if (node && !node.content) {
              node.content = t("thinking");
              node.hidden = false;
            }
          }
        }
      } else {
        streaming = false;
        settleTools(assistant);
        assistant.classList.remove("streaming");
        setActivity(assistant, "");
      }
      syncCopyChat();
      resizeComposer();
      if (followUp && sessionId === chatId && nextTurn) {
        flushNext();
        return;
      }
      if (keepComposerFocus()) messageEl.focus();
      else hideKeyboard();
    }
  });

  chatEl.addEventListener("scroll", () => {
    const top = chatEl.scrollTop;
    const movedUp = top < lastScrollTop - 2;
    lastScrollTop = top;
    syncScrollBottomBtn();
    if (scrollLock) return;
    if (movedUp) {
      releaseFollow();
      return;
    }
    if (!nearBottom()) return;
    const resume = !pinBottom && (streaming || streamBuf);
    pinBottom = true;
    syncScrollBottomBtn();
    if (resume) followBottom();
  }, { passive: true });

  let lastTouchY = 0;
  chatEl.addEventListener("touchstart", (event) => {
    lastTouchY = event.touches[0]?.clientY || 0;
  }, { passive: true });
  chatEl.addEventListener("touchmove", (event) => {
    const y = event.touches[0]?.clientY || 0;
    if (y > lastTouchY + 6) releaseFollow();
    lastTouchY = y;
  }, { passive: true });
  chatEl.addEventListener("wheel", (event) => {
    if (event.deltaY < 0) releaseFollow();
  }, { passive: true });

  messageEl.addEventListener("focus", () => {
    if (keepComposerFocus()) return;
    syncKeyboardInset();
    requestAnimationFrame(syncKeyboardInset);
    window.setTimeout(syncKeyboardInset, 80);
    window.setTimeout(syncKeyboardInset, 320);
  });
  messageEl.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (!composerFocused()) clearKeyboardLock();
    }, 60);
  });
  window.visualViewport?.addEventListener("resize", syncKeyboardInset);
  window.visualViewport?.addEventListener("scroll", () => {
    if (wrap.classList.contains("keyboard-open")) syncKeyboardInset();
  });
  messageEl.addEventListener("input", () => {
    const top = chatEl.scrollTop;
    const hold = !pinBottom;
    resizeComposer();
    if (!hold) return;
    chatEl.scrollTop = top;
    requestAnimationFrame(() => {
      if (!pinBottom) chatEl.scrollTop = top;
    });
  });
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
  scrollBottomBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    jumpToBottom();
  });
  const scrollBtnWatch = new ResizeObserver(() => {
    if (pinBottom) stickToBottom();
    else syncScrollBottomBtn();
  });
  scrollBtnWatch.observe(logEl);
  nextRemove?.addEventListener("click", (event) => {
    event.preventDefault();
    nextTurn = null;
    renderNext();
    resizeComposer();
    if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
  });

  function startNewChat() {
    abandonStream();
    clearMicHelp();
    routeGen += 1;
    watchGen += 1;
    sessionId = "";
    pending = [];
    renderThumbs();
    if (compact) localStorage.removeItem("ai_workspace_session");
    closeNavIfOverlay();
    goToSession("");
    titleEl.textContent = t("new_chat");
    showEmpty();
    loadSessions();
    if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
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
  document.addEventListener("visibilitychange", () => {
    if (sessionId && chatVisible()) watchPending(sessionId);
  });
  window.addEventListener("pageshow", () => {
    if (sessionId && chatVisible()) watchPending(sessionId);
  });

  loadProviders();
  loadDictate();
  const startId = compact ? localStorage.getItem("ai_workspace_session") || "" : sessionIdFromPath();
  if (startId) openSession(startId, true);
  else {
    showEmpty();
    loadSessions();
  }
  resizeComposer();
  const linkWatch = new MutationObserver(() => retargetHaLinks(logEl));
  linkWatch.observe(logEl, { subtree: true, childList: true, attributes: true, attributeFilter: ["href", "target"] });
  function resume() {
    loadDictate();
    if (sessionId) watchPending(sessionId);
  }

  return { openSession, applyRoute, setNarrow, toggleNav, startNewChat, loadDictate, resume };
}
