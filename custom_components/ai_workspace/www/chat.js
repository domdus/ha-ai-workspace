const CACHE = new URL(import.meta.url).search;
const { stringsFor } = await import(`./i18n.js${CACHE}`);
const { taskStrings } = await import(`./tasks_i18n.js${CACHE}`);
const { takeSpeech, speechPlain, takePendingClip, speechTail, splitSpeechClip, MAX_CHARS, clipWatch, unlockOnSend, releaseAudio } = await import(
  `./speech.js${CACHE}`
);
const { stripRemoteMedia, watchRenderedMedia } = await import(`./media_guard.js${CACHE}`);
const {
  MAX_ATTACH,
  MAX_QUEUE,
  filesToRead,
  takeInputFiles,
  pullQueuedDraft,
  keepQueueOnHalt,
  filesLeftOut,
  sessionCacheKey,
} = await import(
  `./send_guard.js${CACHE}`
);

const {
  chatCacheKey,
  readChatCache,
  writeChatCache,
  clearChatCache,
  sameChat,
  olderCount,
  loadOutcome,
  anyUnread,
  timeoutSignal,
  SKELETON_DELAY_MS,
  SLOW_HINT_MS,
  LOAD_TIMEOUT_MS,
} = await import(`./chat_cache.js${CACHE}`);
const {
  draftStoreKey,
  draftSlot,
  readDraft,
  writeDraft,
  clearDraft,
  draftSlots,
  createChatQueues,
  drainQueue,
  NEW_CHAT_DRAFT,
} = await import(`./chat_drafts.js${CACHE}`);
const { replyTimeLabel, replyTimeTitle, haHour12, haTimeZone, replyRows } = await import(
  `./reply_meta.js${CACHE}`
);
const { isPlaceholderTitle, headerTitle, realTitle } = await import(`./chat_title.js${CACHE}`);
const { toolProgressText, progressChip } = await import(`./tool_progress.js${CACHE}`);

const API = "/api/ai_workspace";
const UI_THEME_KEY = "ai_workspace_ui_theme";
const SESSION_CACHE_KEY = "ai_workspace_sessions";
const PAINT_TAIL = 24;

function sessionCacheSlot() {
  return sessionCacheKey(SESSION_CACHE_KEY, document.querySelector("home-assistant")?.hass?.user?.id);
}

function readSessionCache() {
  const key = sessionCacheSlot();
  if (!key) return [];
  try {
    const rows = JSON.parse(sessionStorage.getItem(key) || "[]");
    return Array.isArray(rows) ? rows.filter((row) => row && row.id) : [];
  } catch (_err) {
    return [];
  }
}

function writeSessionCache(sessions) {
  const key = sessionCacheSlot();
  if (!key) return;
  try {
    // Drop the old shared key from 1.5.0b18-b27.
    sessionStorage.removeItem(SESSION_CACHE_KEY);
    sessionStorage.setItem(
      key,
      JSON.stringify(
        (sessions || []).map((session) => ({
          id: session.id,
          title: session.title || "",
          pinned: Boolean(session.pinned),
          unread: Boolean(session.unread),
        })),
      ),
    );
  } catch (_err) {
    /* private mode */
  }
}

function userId() {
  return document.querySelector("home-assistant")?.hass?.user?.id || "";
}

function chatCacheSlot() {
  return chatCacheKey(userId());
}

/** The chat id in /ai-workspace/<id>, also before the page is mounted. */
export function routeSessionId(pathname = location.pathname) {
  const match = String(pathname || "").match(/^\/ai-workspace(?:\/conversations)?\/([0-9a-fA-F-]{8,})\/?$/);
  return match ? match[1] : "";
}

// Signed-in fetch for code that runs before mountAiWorkspace (panel open), with a time limit.
async function authFetch(url, init = {}, getToken = null, timeoutMs = 0) {
  const hass = hassObj();
  const limit = timeoutMs ? timeoutSignal(timeoutMs, init.signal) : null;
  const options = limit ? { ...init, signal: limit.signal } : init;
  try {
    if (typeof hass?.fetchWithAuth === "function") return await hass.fetchWithAuth(url, options);
    const token = (typeof getToken === "function" ? getToken() : "") || hass?.auth?.data?.access_token || "";
    if (!token) return null;
    return await fetch(url, { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } });
  } finally {
    limit?.done();
  }
}

// The open chat's messages, asked for the moment the panel opens, in parallel with everything else.
let sessionPrefetch = null;
const PREFETCH_FRESH_MS = 10000;

export function prefetchSession(id = routeSessionId(), getToken = null) {
  if (!id) return null;
  if (sessionPrefetch && sessionPrefetch.id === id && Date.now() - sessionPrefetch.at < PREFETCH_FRESH_MS) {
    return sessionPrefetch.promise;
  }
  const promise = authFetch(
    `${API}/sessions/${id}`,
    { headers: { Accept: "application/json" }, priority: "high" },
    getToken,
    LOAD_TIMEOUT_MS,
  ).then(
    async (response) => ({ response, body: response?.ok ? await response.json() : null }),
    (error) => ({ response: null, body: null, timedOut: error?.name === "TimeoutError" || error?.name === "AbortError", error }),
  );
  sessionPrefetch = { id, at: Date.now(), promise };
  return promise;
}

function takeSessionPrefetch(id) {
  const hit = sessionPrefetch;
  if (!hit || hit.id !== id || Date.now() - hit.at >= PREFETCH_FRESH_MS) return null;
  sessionPrefetch = null;
  return hit.promise;
}

export { takeSpeech };

function hassObj() {
  return document.querySelector("home-assistant")?.hass;
}

let shellScrollPin = false;

/** Reset window/body and HA panel scroll containers (e.g. after sidebar navigation). */
export function resetHaShellScroll(startEl) {
  if (shellScrollPin) return;
  shellScrollPin = true;
  window.scrollTo(0, 0);
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
  const seen = new Set();
  let node = startEl || null;
  while (node && !seen.has(node)) {
    seen.add(node);
    if (node.scrollTop) node.scrollTop = 0;
    const root = node.getRootNode?.();
    node = node.parentElement || (root instanceof ShadowRoot ? root.host : null);
  }
  shellScrollPin = false;
}

function haAtLeast(year, month) {
  const [major, minor] = String(hassObj()?.config?.version || "").split(".").map(Number);
  if (!major) return true;
  return major > year || (major === year && minor >= month);
}

function haHas(name) {
  return Boolean(customElements.get(name));
}

function haCreate(...names) {
  const tag = names.find((name) => name && name.includes("-"));
  if (tag) return document.createElement(tag);
  return document.createElement(names[names.length - 1] || "div");
}

function setMarkdown(el, body) {
  const text = stripRemoteMedia(String(body || ""));
  el.content = text;
  watchRenderedMedia(el);
  return text;
}

function fillHaMarkdown(el, body) {
  const text = setMarkdown(el, body);
  styleMarkdownTables(el);
  if (!text || haHas("ha-markdown")) return;
  el.textContent = text;
  customElements.whenDefined("ha-markdown").then(() => {
    if (el.isConnected) el.textContent = "";
    styleMarkdownTables(el);
  });
}

function isPipeTableLine(line) {
  return String(line || "").trim().startsWith("|");
}

function isPipeTableSep(line) {
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(String(line || ""));
}

function streamFenceOpen(text) {
  const marks = String(text || "").match(/^```/gm);
  return Boolean(marks && marks.length % 2);
}

/** Hold incomplete markdown tables so columns do not dance while a row is still arriving. */
function stableStreamMarkdown(text, done) {
  if (done || !text || streamFenceOpen(text)) return text;
  const lines = text.split("\n");
  if (!text.endsWith("\n") && lines.length) {
    const last = lines[lines.length - 1];
    if (isPipeTableLine(last) || isPipeTableSep(last)) lines.pop();
  }
  let end = lines.length - 1;
  while (end >= 0 && !lines[end].trim()) end -= 1;
  if (end < 0 || !(isPipeTableLine(lines[end]) || isPipeTableSep(lines[end]))) {
    return lines.join("\n");
  }
  let start = end;
  while (start >= 0 && (isPipeTableLine(lines[start]) || isPipeTableSep(lines[start]) || !lines[start].trim())) {
    start -= 1;
  }
  start += 1;
  const block = [];
  for (let i = start; i <= end; i += 1) {
    if (lines[i].trim()) block.push(lines[i]);
  }
  const sepAt = block.findIndex(isPipeTableSep);
  if (sepAt < 1) lines.splice(start);
  return lines.join("\n");
}

let markdownTableSheet;

function markdownTableStyleSheet() {
  if (markdownTableSheet !== undefined) return markdownTableSheet;
  markdownTableSheet = null;
  if (typeof CSSStyleSheet !== "function") return null;
  try {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(
      "table{table-layout:fixed;width:100%;max-width:100%}"
      + "th,td{overflow-wrap:anywhere;word-break:break-word;vertical-align:top}",
    );
    markdownTableSheet = sheet;
  } catch (_err) {
    markdownTableSheet = null;
  }
  return markdownTableSheet;
}

function styleMarkdownTables(md) {
  if (!md) return;
  const apply = () => {
    const sheet = markdownTableStyleSheet();
    if (!sheet) return;
    const roots = [];
    if (md.shadowRoot) roots.push(md.shadowRoot);
    const inner = md.querySelector?.("ha-markdown-element");
    if (inner?.shadowRoot) roots.push(inner.shadowRoot);
    for (const root of roots) {
      if (!root.adoptedStyleSheets || root.adoptedStyleSheets.includes(sheet)) continue;
      root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
    }
  };
  apply();
  if (!md.shadowRoot) requestAnimationFrame(apply);
}

async function loadHaPanel(componentName, urlPath) {
  await customElements.whenDefined("partial-panel-resolver");
  const resolver = document.createElement("partial-panel-resolver");
  const panels = { [urlPath]: { url_path: urlPath, component_name: componentName } };
  let routerOptions;
  if (typeof resolver._getRoutes === "function") {
    routerOptions = resolver._getRoutes(panels);
  } else if (typeof resolver._updateRoutes === "function") {
    resolver.hass = { panels };
    resolver._updateRoutes();
    routerOptions = resolver.routerOptions;
  }
  const load = routerOptions?.routes?.[urlPath]?.load;
  if (typeof load === "function") await load.call(routerOptions.routes[urlPath]);
}

/** Config/automation chunk preload runs at most once per full HA page load. */
let haComponentsLoaderTriggered = false;
let haDatePickerLoaderTriggered = false;

async function ensureHaComponents(names) {
  const missing = names.filter((name) => name && name.includes("-") && !haHas(name));
  if (!missing.length) return;
  const ready = Promise.all(missing.map((name) => customElements.whenDefined(name)));
  try {
    if (
      !haComponentsLoaderTriggered &&
      missing.some((name) => !haHas(name))
    ) {
      haComponentsLoaderTriggered = true;
      await loadHaPanel("config", "tmp");
      if (haHas("ha-panel-config")) {
        const panel = document.createElement("ha-panel-config");
        const load = panel.routerOptions?.routes?.automation?.load;
        if (typeof load === "function") await load.call(panel.routerOptions.routes.automation);
      }
    }
    if (missing.includes("ha-textarea") && !haHas("ha-textarea") && haHas("ha-selector")) {
      // HA ships ha-textarea in a lazy chunk; a multi-line text selector imports it.
      const selector = document.createElement("ha-selector");
      selector.hass = hassObj();
      selector.selector = { text: { multiline: true } };
      selector.hidden = true;
      document.body.append(selector);
      customElements.whenDefined("ha-textarea").then(() => selector.remove());
    }
    const wantDate = missing.some((name) => String(name).startsWith("ha-date-range"));
    if (wantDate && !haDatePickerLoaderTriggered) {
      haDatePickerLoaderTriggered = true;
      if (!haHas("ha-date-range-nav") && !haHas("ha-date-range-picker")) {
        await loadHaPanel("logbook", "logbook");
      }
      if (!haHas("ha-date-range-nav") && !haHas("ha-date-range-picker")) {
        await loadHaPanel("history", "history");
      }
    }
  } catch (_err) {
    /* Current page may already expose the tags. */
  }
  await Promise.race([ready, new Promise((resolve) => setTimeout(resolve, 8000))]);
}

let uiRemountInFlight = false;

// What the HA composer is built from: text field, queued-prompt and file chips, pickers.
const HA_COMPOSER_PRELOAD = [
  "ha-textarea",
  "ha-chip-set",
  "ha-input-chip",
  "ha-button",
  "ha-icon-button",
  "ha-dropdown",
  "ha-dropdown-item",
];

let uiTheme = "standard";
let uiThemeLoaded = false;

export function haComponentsUi() {
  return uiTheme === "ha_components";
}

/** Composer parts (queued prompts, file chips): HA widgets with HA components on, plain elements otherwise. */
function composerCreate(...names) {
  if (!haComponentsUi()) {
    return document.createElement(names[names.length - 1] || "div");
  }
  return haCreate(...names);
}

// One /ui answer serves the panel, the theme check and the mic/usage settings: they ask within moments.
let uiBodyCache = null;
const UI_BODY_FRESH_MS = 5000;

function storedUiTheme() {
  try {
    const saved = localStorage.getItem(UI_THEME_KEY);
    return saved === "ha_components" || saved === "standard" ? saved : "";
  } catch (_err) {
    return "";
  }
}

function fetchUiBody(getToken, { fresh = false } = {}) {
  if (!fresh && uiBodyCache && Date.now() - uiBodyCache.at < UI_BODY_FRESH_MS) return uiBodyCache.promise;
  const promise = (async () => {
    try {
      const response = await authFetch(`${API}/ui`, { headers: { Accept: "application/json" } }, getToken, LOAD_TIMEOUT_MS);
      if (!response?.ok) return null;
      const body = await response.json();
      try {
        localStorage.setItem(UI_THEME_KEY, body.ui_theme === "ha_components" ? "ha_components" : "standard");
      } catch (_err) {
        /* private mode */
      }
      return body;
    } catch (_err) {
      return null;
    }
  })();
  uiBodyCache = { at: Date.now(), promise };
  return promise;
}

async function fetchUiTheme(getToken) {
  const body = await fetchUiBody(getToken);
  if (body) {
    uiTheme = body.ui_theme === "ha_components" ? "ha_components" : "standard";
    uiThemeLoaded = true;
  }
  return uiTheme;
}

export function invalidateUiThemeCache() {
  uiThemeLoaded = false;
}

/** The theme to mount with. The last one seen in this browser goes at once; /ui is checked in the background. */
export async function prefetchUiTheme(getToken, { force = false } = {}) {
  if (force) invalidateUiThemeCache();
  if (uiThemeLoaded && !force) {
    void fetchUiTheme(getToken);
    return uiTheme;
  }
  const saved = force ? "" : storedUiTheme();
  if (saved) {
    uiTheme = saved;
    uiThemeLoaded = true;
    void fetchUiBody(getToken);
    return uiTheme;
  }
  return fetchUiTheme(getToken);
}

function haChipLabel(chip, text) {
  if (!chip) return "";
  if (text !== undefined) {
    if ("label" in chip) chip.label = text;
    else chip.textContent = text;
    return text;
  }
  return String(chip.label || chip.textContent || "");
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
  if (domain === "automation") {
    const id = configId(info);
    if (id && !looksLikeEntityId(id)) return `/config/automation/edit/${encodeURIComponent(id)}`;
  }
  if (domain === "script") {
    const id = configId(info) || String(entityId).replace(/^script\./, "");
    if (id) return `/config/script/edit/${encodeURIComponent(id)}`;
  }
  if (domain === "scene") {
    const id = configId(info) || String(entityId).replace(/^scene\./, "");
    if (id) return `/config/scene/edit/${encodeURIComponent(id)}`;
  }
  return `/config/entities/entity/${encodeURIComponent(entityId)}`;
}

function entityIdFromHaPath(path) {
  try {
    const url = new URL(String(path || ""), window.location.origin);
    const match = url.pathname.match(/^\/config\/entities(?:\/entity)?\/([^/]+)$/);
    if (!match) return "";
    const raw = decodeURIComponent(match[1]);
    return looksLikeEntityId(raw) ? raw : "";
  } catch (_err) {
    return "";
  }
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
    if (looksLikeEntityId(raw) || info?.state || info?.entry) {
      if (domain === "automation" || kind === "automation") {
        const id = configId(info);
        if (id && !looksLikeEntityId(id)) return `/config/automation/edit/${encodeURIComponent(id)}`;
      }
      if (domain === "script" || kind === "script") {
        const id = configId(info) || entityId.replace(/^script\./, "");
        if (id) return `/config/script/edit/${encodeURIComponent(id)}`;
      }
      if (domain === "scene" || kind === "scene") {
        const id = configId(info) || entityId.replace(/^scene\./, "");
        if (id) return `/config/scene/edit/${encodeURIComponent(id)}`;
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
  if (!trimmed || trimmed.startsWith("#")) return trimmed;
  let url;
  try {
    url = new URL(trimmed, window.location.origin);
  } catch (_err) {
    return trimmed;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return trimmed;
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

// One-word names ("Home", "Wohnzimmer") are ordinary words in a reply, so only longer names link.
const UNLINKED_NAMES = new Set(["home assistant"]);

function rememberUniqueName(map, name, path) {
  const text = String(name || "").trim();
  if (text.length < 3 || !/\s/.test(text) || UNLINKED_NAMES.has(text.toLowerCase())) return;
  const key = text.toLowerCase();
  const prev = map.get(key);
  if (prev && prev.path !== path) map.set(key, null);
  else if (!prev) map.set(key, { name: text, path });
}

let linkCatalog = null;

function mentionPattern(words) {
  if (!words.length) return null;
  return new RegExp(`(^|[^\\w./#\\u0000])(${words.map(escapeRe).join("|")})(?![\\w./\\u0000])`, "g");
}

function haLinkCatalog() {
  const hass = hassObj();
  if (!hass) return { names: null, ids: null, paths: new Map() };
  const states = hass.states || {};
  const count = Object.keys(states).length;
  const cached = linkCatalog;
  if (
    cached &&
    cached.entities === hass.entities &&
    cached.devices === hass.devices &&
    cached.count === count &&
    Date.now() - cached.at < 60000
  ) {
    return cached;
  }
  const nameToPath = new Map();
  const paths = new Map();
  for (const [entityId, state] of Object.entries(states)) {
    const info = { entityId, state, entry: hass.entities?.[entityId] };
    const path = pathForEntity(entityId, info);
    paths.set(entityId, path);
    rememberUniqueName(nameToPath, state?.attributes?.friendly_name, path);
  }
  for (const device of Object.values(hass.devices || {})) {
    const id = device?.id;
    if (!id) continue;
    rememberUniqueName(nameToPath, device.name_by_user || device.name, `/config/devices/device/${encodeURIComponent(id)}`);
  }
  const names = [];
  for (const row of nameToPath.values()) {
    if (row && !paths.has(row.name)) {
      paths.set(row.name, row.path);
      names.push(row.name);
    }
  }
  const byLength = (a, b) => b.length - a.length;
  linkCatalog = {
    entities: hass.entities,
    devices: hass.devices,
    count,
    at: Date.now(),
    names: mentionPattern(names.sort(byLength)),
    ids: mentionPattern(Object.keys(states).sort(byLength)),
    paths,
  };
  return linkCatalog;
}

function linkifyHaPaths(text) {
  // Bare HA UI paths the model sometimes writes without Markdown, e.g. /lovelace/media
  return String(text || "").replace(
    /(^|[^\w./#\u0000[])(\/(?:config|lovelace|dashboard|history|logbook|developer-tools|profile|media-browser|energy|map|todo|ai-workspace|hassio|supervisor)[^\s)\]<>"'`]*)/g,
    (whole, lead, raw, offset, source) => {
      if (lead === "(" && source[offset - 1] === "]") return whole;
      let path = raw;
      while (/[.,;:!?]$/.test(path)) path = path.slice(0, -1);
      const base = path.split(/[?#]/)[0];
      if (!haAppPath(base)) return whole;
      return `${lead}[${path}](${path})${raw.slice(path.length)}`;
    },
  );
}

const QUOTED = /„[^“”\n]{1,120}[“”]|“[^”\n]{1,120}”|"[^"\n]{1,120}"|«[^»\n]{1,120}»|»[^«\n]{1,120}«/g;

function linkifyHaMentions(content, mentions = true) {
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
  // A quoted name is a title the user or agent is talking about (a section, a card), not a link target.
  text = text.replace(QUOTED, hold);
  const { names, ids, paths } = mentions ? haLinkCatalog() : {};
  const linked = new Set();
  for (const re of [names, ids]) {
    if (!re) continue;
    re.lastIndex = 0;
    text = text.replace(re, (whole, lead, matched) => {
      const path = paths.get(matched);
      if (linked.has(path)) return whole;
      linked.add(path);
      return `${lead}${hold(`[${matched}](${path})`)}`;
    });
  }
  return text.replace(/\u0000HA(\d+)\u0000/g, (_m, index) => held[Number(index)] || "");
}

function errorBodyMessage(data) {
  if (Array.isArray(data)) {
    for (const item of data) {
      const found = errorBodyMessage(item);
      if (found) return found;
    }
    return "";
  }
  if (!data || typeof data !== "object") return "";
  const err = data.error;
  if (err && typeof err === "object") return errorBodyMessage(err) || String(err.status || err.code || "");
  if (typeof err === "string" && err.trim()) return err.trim();
  for (const key of ["message", "detail", "error_description", "msg"]) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (value && typeof value === "object") {
      const found = errorBodyMessage(value);
      if (found) return found;
    }
  }
  return "";
}

// Same rules as error_text.py, for chats stored before the server cleaned errors and for request failures.
function cleanErrorText(value) {
  let text = String(value || "").trim();
  if (!text) return text;
  const start = text.search(/[[\u007b]/);
  if (start >= 0) {
    try {
      const found = errorBodyMessage(JSON.parse(text.slice(start)));
      text = found || text.slice(0, start).replace(/[\s:-]+$/, "") || text;
    } catch (_err) {
      /* not a JSON body */
    }
  }
  if (text.startsWith("<")) text = text.replace(/<[^>]*>/g, " ");
  if (text.length < 120 && /timeout on reading data from socket|read timed out/i.test(text)) {
    return "The provider did not answer in time. Try again, or pick a faster model.";
  }
  text = text.replace(/\s+/g, " ").trim();
  return text.length <= 400 ? text : `${text.slice(0, 399).trimEnd()}…`;
}

// A closed sidebar would otherwise slide away on open when its sheet arrives after the first paint.
function releaseMountHold(root) {
  const hold = root.querySelector(".mount-hold");
  const sheets = [...root.querySelectorAll("link[rel='stylesheet']")];
  const loaded = sheets.map(
    (link) =>
      new Promise((done) => {
        if (link.sheet) done();
        link.addEventListener("load", done, { once: true });
        link.addEventListener("error", done, { once: true });
      })
  );
  // The new styles are computed on the frame after load, so the hold must outlast that frame.
  const settled = Promise.all(loaded).then(
    () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))
  );
  const limit = new Promise((done) => setTimeout(done, 1500));
  void Promise.race([settled, limit]).then(() => hold?.remove());
}

export async function mountAiWorkspace(root, options = {}) {
  // Read at mount, not at import: the user is known by then, and it may have changed.
  let cachedSessions = readSessionCache();
  // The open chat's messages are asked for first, in parallel with the theme and everything else.
  const earlyId =
    options.restoreSessionId ||
    (options.compact ? localStorage.getItem("ai_workspace_session") || "" : options.routed ? routeSessionId() : "");
  if (earlyId) prefetchSession(earlyId, options.getToken);
  // A different user on this device must not see the last user's cached chat.
  const ownChatCache = chatCacheSlot();
  if (ownChatCache) clearChatCache(localStorage, "", { keepKey: ownChatCache });
  await prefetchUiTheme(options.getToken, { force: Boolean(options.forceUiTheme) });
  // HA components only swap the composer (HA text field, agent and model pickers); messages stay Standard.
  const haUi = haComponentsUi();
  let activeUiTheme = haUi ? "ha_components" : "standard";
  const compact = Boolean(options.compact);
  const strings = stringsFor(hassLanguage());
  const t = (key, vars = {}) => {
    let text = strings[key] || key;
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, value);
    }
    return text;
  };
  // Server errors arrive in English; show the known ones in the user's language.
  const KNOWN_ERRORS = {
    "The provider did not answer in time. Try again, or pick a faster model.": "provider_timeout",
  };
  const shownError = (value) => {
    const text = cleanErrorText(value);
    const key = KNOWN_ERRORS[text];
    return key ? t(key) : text;
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
    "ui-theme-standard",
    haUi ? "composer-ha" : "",
    compact ? "compact" : "",
    options.chrome === "panel" ? "has-app-bar" : "",
    overlayStart ? "narrow" : "",
    collapsedStart ? "nav-collapsed" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const themeCss = `<link rel="stylesheet" href="/ai_workspace/static/chat.css${CACHE}">${
    haUi ? `<link rel="stylesheet" href="/ai_workspace/static/chat-ha-composer.css${CACHE}">` : ""
  }`;
  const tasksCss = `<link rel="stylesheet" href="/ai_workspace/static/tasks.css${CACHE}">`;
  // The Tasks page (agent tasks as automations) is for administrators on the full page only.
  const tasksAllowed = routed && Boolean(hassObj()?.user?.is_admin);
  // The Tasks entry lives in the chat list toolbar only, next to Activity and Usage.
  const tasksButton = () =>
    tasksAllowed
      ? `<ha-icon-button class="tasks-open" label="${taskStrings(hassLanguage()).tasks}">
                <ha-icon icon="mdi:calendar-clock"></ha-icon>
              </ha-icon-button>`
      : "";
  const bannerMarkup = `<p class="banner" hidden></p>`;
  const workspaceLinkMarkup =
    compact && hassObj()?.user?.is_admin ? `<a class="workspace-link" href="/ai-workspace">${t("open_workspace")}</a>` : "";
  const scrollBottomMarkup = `<button type="button" class="scroll-bottom" tabindex="-1" aria-label="${t("scroll_to_bottom")}"><ha-icon icon="mdi:arrow-down"></ha-icon></button>`;
  const htmlAttr = (value) =>
    String(value)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  const composerTag = "div";
  const fileInputMarkup =
    `<input class="file-input" type="file" accept="image/*,.yaml,.yml,.json,.txt,.md,.csv,.xml,.toml,.html,.css,.js,.ts,.py,.log,.cfg,.ini,.conf" multiple hidden>`;
  const attachBtnMarkup = `<ha-icon-button class="attach" type="button" label="${htmlAttr(t("attach"))}"><ha-icon icon="mdi:paperclip"></ha-icon></ha-icon-button>`;
  const micBtnMarkup = `<ha-icon-button class="mic" type="button" label="${htmlAttr(t("dictate"))}" hidden><ha-icon icon="mdi:microphone"></ha-icon></ha-icon-button>`;
  const messageMarkup = `<label class="sr" for="ai-message">${t("message")}</label><textarea id="ai-message" class="message" rows="1" enterkeyhint="enter" placeholder="${htmlAttr(t("placeholder"))}"></textarea>`;
  const sendMarkup = haUi
    ? `<ha-icon-button class="send" type="button" label="${htmlAttr(t("send"))}"><ha-icon icon="mdi:send"></ha-icon></ha-icon-button>`
    : `<ha-button class="send" size="s" appearance="accent" aria-label="${htmlAttr(t("send"))}"><ha-icon icon="mdi:arrow-up"></ha-icon></ha-button>`;
  const standardComposerRowMarkup = `
              <div class="composer-row">
              ${messageMarkup}
              <div class="composer-actions">
              ${fileInputMarkup}
              ${attachBtnMarkup}
              ${micBtnMarkup}
              ${sendMarkup}
              </div>
              </div>`;
  const haComposerInputMarkup = `
              <div class="input">
                ${fileInputMarkup}
                <div class="composer-fallback">${standardComposerRowMarkup}</div>
                <div class="composer-field">
                  <ha-textarea id="message-input" class="message" rows="1" resize="auto" label="${htmlAttr(t("message"))}" placeholder="${htmlAttr(t("placeholder"))}"></ha-textarea>
                  <div class="composer-field-actions">
                    ${attachBtnMarkup}
                    ${micBtnMarkup}
                    ${sendMarkup}
                  </div>
                </div>
              </div>`;
  const agentTriggerMarkup = haUi
    ? `<ha-button type="button" class="agent-trigger" slot="trigger" appearance="plain" size="s" aria-haspopup="menu" aria-expanded="false" aria-label="${t("agent")}"><span class="agent-trigger-label"></span><ha-icon slot="end" icon="mdi:chevron-down"></ha-icon></ha-button>`
    : `<button type="button" class="agent-trigger" slot="trigger" aria-haspopup="menu" aria-expanded="false" aria-label="${t("agent")}"><span class="agent-trigger-label"></span><ha-icon icon="mdi:chevron-down"></ha-icon></button>`;
  const modelTriggerMarkup = haUi
    ? `<ha-button type="button" class="agent-trigger model-trigger" slot="trigger" appearance="plain" size="s" aria-haspopup="menu" aria-expanded="false" aria-label="${t("model")}"><span class="agent-trigger-label model-trigger-label"></span><ha-icon slot="end" icon="mdi:chevron-down"></ha-icon></ha-button>`
    : `<button type="button" class="agent-trigger model-trigger" slot="trigger" aria-haspopup="menu" aria-expanded="false" aria-label="${t("model")}"><span class="agent-trigger-label model-trigger-label"></span><ha-icon icon="mdi:chevron-down"></ha-icon></button>`;
  // Inline, so it applies before the theme sheets that define the transitions.
  root.innerHTML = `
    <style class="mount-hold">.wrap, .wrap * { transition: none !important; }</style>
    ${themeCss}${tasksCss}
    <div class="${wrapClass}">
      <button type="button" class="nav-scrim" hidden aria-label="${t("close")}"></button>
      <div class="notice-pop" role="dialog" aria-label="${t("notice")}" hidden></div>
      <aside>
        <div class="nav-head">
          <div class="nav-toolbar">
            <div class="nav-tools">
              <ha-icon-button class="notice-open" label="${t("notice")}" aria-expanded="false" hidden>
                <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
              </ha-icon-button>
              <ha-icon-button class="search-open" label="${t("search_chats")}" aria-pressed="false" hidden>
                <ha-icon icon="mdi:magnify"></ha-icon>
              </ha-icon-button>
              <ha-icon-button class="history-open" label="${t("activity")}">
                <ha-icon icon="mdi:history"></ha-icon>
              </ha-icon-button>
              <ha-icon-button class="usage-open" label="${t("usage")}">
                <ha-icon icon="mdi:chart-bar"></ha-icon>
              </ha-icon-button>
              ${tasksButton()}
            </div>
            <ha-icon-button class="nav-toggle" label="${t("hide_chats")}">
              <ha-icon icon="${collapsedStart ? "mdi:dock-left" : "mdi:chevron-double-left"}"></ha-icon>
            </ha-icon-button>
          </div>
          <div class="brand">${t("title")}</div>
          <ha-icon-button class="new-chat-icon" label="${t("new_chat")}">
            <ha-icon icon="mdi:plus"></ha-icon>
          </ha-icon-button>
          <div class="nav-action">
            <div class="nav-search" hidden>
              <input type="search" class="nav-search-input" placeholder="${t("search_chats")}" aria-label="${t("search_chats")}" autocomplete="off" enterkeyhint="search">
            </div>
            <ha-button class="new-chat" size="s" variant="brand" appearance="accent">
              <ha-svg-icon slot="start" path="M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z"></ha-svg-icon>
              ${t("new_chat")}
            </ha-button>
          </div>
        </div>
        <div class="sessions" role="list" aria-busy="true">${sessionSkeleton()}</div>
      </aside>
      <section class="chat welcome">
        <header>
          <div class="header-row">
            <ha-icon-button class="nav-toggle chat-nav-toggle" label="${t("show_chats")}">
              <ha-icon icon="mdi:forum-outline"></ha-icon>
            </ha-icon-button>
            ${compact ? "" : `<ha-icon-button class="notice-open header-notice" label="${t("notice")}" aria-expanded="false" hidden>
                <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
              </ha-icon-button>
            <ha-icon-button class="history-open header-history" label="${t("activity")}">
              <ha-icon icon="mdi:history"></ha-icon>
            </ha-icon-button>
            <ha-icon-button class="usage-open header-usage" label="${t("usage")}">
              <ha-icon icon="mdi:chart-bar"></ha-icon>
            </ha-icon-button>`}
            <h1 class="title">${t("new_chat")}</h1>
          </div>
          <p class="chat-usage" hidden></p>
          ${bannerMarkup}
        </header>
        ${workspaceLinkMarkup}
        <div class="stage">
          <div class="log"><p class="empty">${t("empty")}</p></div>
          <form class="composer">
            ${scrollBottomMarkup}
            <div class="approvals" hidden aria-live="polite"></div>
            ${haUi ? `<${composerTag} class="composer-box">
              <div class="next-row" hidden></div>
              <div class="attach-row" hidden></div>
              ${haComposerInputMarkup}
              <div class="agent-picker" hidden>
                <ha-dropdown class="agent-menu" placement="top-start">
                  ${agentTriggerMarkup}
                </ha-dropdown>
                <ha-dropdown class="model-menu" placement="top-start" hidden>
                  ${modelTriggerMarkup}
                </ha-dropdown>
              </div>
            </${composerTag}>` : `<${composerTag} class="composer-box">
              <div class="next-row" hidden></div>
              <div class="attach-row" hidden></div>
              ${standardComposerRowMarkup}
            </${composerTag}>
            <div class="agent-picker" hidden>
              <ha-dropdown class="agent-menu" placement="top-start">
                ${agentTriggerMarkup}
              </ha-dropdown>
              <ha-dropdown class="model-menu" placement="top-start" hidden>
                ${modelTriggerMarkup}
              </ha-dropdown>
            </div>`}
          </form>
        </div>
      </section>
      <div class="history" hidden aria-hidden="true">
        <div class="history-bar">
          <span>${t("activity")}</span>
          <ha-icon-button class="history-close" label="${t("close")}">
            <ha-icon icon="mdi:close"></ha-icon>
          </ha-icon-button>
        </div>
        <div class="history-list"></div>
      </div>
      <div class="usage" hidden aria-hidden="true">
        <div class="usage-bar">
          <h1>${t("usage")}</h1>
        </div>
        <div class="usage-toolbar">
          <div class="usage-range"></div>
          <div class="usage-filters"></div>
        </div>
        <div class="usage-list"></div>
      </div>
      ${tasksAllowed ? `<div class="tasks-page" hidden aria-hidden="true"></div>` : ""}
    </div>
  `;

  const wrap = root.querySelector(".wrap");
  releaseMountHold(root);
  const scrim = root.querySelector(".nav-scrim");
  const chatEl = root.querySelector(".chat");
  const headerEl = chatEl?.querySelector("header");
  const stageEl = root.querySelector(".stage");
  const logEl = root.querySelector(".log");
  const approvalsEl = root.querySelector(".approvals");
  const sessionsEl = root.querySelector(".sessions");
  const searchOpen = root.querySelector(".search-open");
  const searchBox = root.querySelector(".nav-search");
  const searchInput = root.querySelector(".nav-search-input");
  const titleEl = root.querySelector(".title");
  const bannerEl = root.querySelector(".banner");
  const form = root.querySelector(".composer");
  const scrollBottomBtn = root.querySelector(".scroll-bottom");
  let messageEl = root.querySelector("#ai-message") || root.querySelector("#message-input");
  function syncComposerField() {
    const haField = root.querySelector("#message-input");
    if (haUi && haField?.localName === "ha-textarea" && haHas("ha-textarea")) messageEl = haField;
    else messageEl = root.querySelector("#ai-message") || haField;
  }
  syncComposerField();
  function composerControls(selector) {
    return form ? [...form.querySelectorAll(selector)] : [];
  }
  function setComposerDisabled(selector, disabled) {
    for (const el of composerControls(selector)) el.disabled = disabled;
  }
  function primaryMicButton() {
    return composerControls(".mic").find((btn) => !btn.hidden && !btn.classList.contains("is-hidden"));
  }
  function setMicListening(active) {
    for (const btn of composerControls(".mic")) {
      btn.classList.toggle("listening", active);
      btn.label = active ? t("stop_dictate") : t("dictate");
    }
  }
  const agentPicker = root.querySelector(".agent-picker");
  const agentTrigger = root.querySelector(".agent-menu .agent-trigger");
  const agentLabel = root.querySelector(".agent-menu .agent-trigger-label");
  const agentMenu = root.querySelector(".agent-menu");
  const modelMenu = root.querySelector(".model-menu");
  const modelTrigger = root.querySelector(".model-trigger");
  const modelLabel = root.querySelector(".model-trigger-label");
  const attachRow = root.querySelector(".attach-row");
  const nextRow = root.querySelector(".next-row");
  const box = form.querySelector(".composer-box");
  const plusIcon = root.querySelector(".new-chat ha-svg-icon");
  if (plusIcon && !plusIcon.path) {
    plusIcon.path = "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z";
  }
  function bindHaTree(node) {
    if (!haUi || !node) return;
    const hass = hassObj();
    if (!hass) return;
    const visit = (el) => {
      if (el.localName?.includes("-") && "hass" in el) el.hass = hass;
    };
    visit(node);
    node.querySelectorAll?.("*")?.forEach(visit);
  }
  bindHaTree(form);
  if (haUi) {
    customElements.whenDefined("ha-textarea").then(() => {
      syncComposerField();
      bindHaTree(form);
      resizeComposer();
    });
  }
  let sessionId = "";
  let sessionLoad = Promise.resolve();
  let freshChat = false;
  let routeGen = 0;
  const workspaceLink = root.querySelector(".workspace-link");
  const teardown = [];
  teardown.push(() => {
    if (approvalPoll) window.clearInterval(approvalPoll);
  });

  function listen(target, type, handler, opts) {
    if (!target) return;
    target.addEventListener(type, handler, opts);
    teardown.push(() => target.removeEventListener(type, handler, opts));
  }

  function isNarrow() {
    return Boolean(options.narrow) || mqNarrow.matches;
  }

  function syncToggleLabels() {
    const collapsed = wrap.classList.contains("nav-collapsed");
    const open = wrap.classList.contains("nav-open");
    const overlay = wrap.classList.contains("narrow");
    const label = overlay
      ? (open ? t("hide_chats") : t("show_chats"))
      : (collapsed ? t("show_chats") : t("hide_chats"));
    root.querySelectorAll(".nav-toggle").forEach((btn) => {
      btn.label = overlay && !btn.classList.contains("chat-nav-toggle") ? t("close") : label;
    });
    const rail = root.querySelector(".nav-toolbar .nav-toggle ha-icon");
    if (rail) rail.setAttribute("icon", overlay ? "mdi:close" : collapsed ? "mdi:dock-left" : "mdi:chevron-double-left");
  }

  function setNavOpen(open) {
    wrap.classList.toggle("nav-open", Boolean(open));
    if (scrim) scrim.hidden = !open;
    syncToggleLabels();
    options.onNavOpen?.(Boolean(open));
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

  function workspaceRoute(pathname = location.pathname) {
    const clean = String(pathname || "").replace(/\/$/, "") || "/";
    if (clean === "/ai-workspace/usage") return { view: "usage", sessionId: "" };
    if (clean === "/ai-workspace/tasks") return { view: "tasks", sessionId: "" };
    const match = String(pathname || "").match(/^\/ai-workspace(?:\/conversations)?\/([0-9a-fA-F-]{8,})\/?$/);
    return { view: "chat", sessionId: match ? match[1] : "" };
  }

  function sessionIdFromPath(pathname = location.pathname) {
    return workspaceRoute(pathname).sessionId;
  }

  function usagePath() {
    return "/ai-workspace/usage";
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
    if (!location.pathname.startsWith("/ai-workspace")) {
      haltSpeech();
      return;
    }
    const route = workspaceRoute();
    if (route.view === "usage") {
      haltSpeech();
      closeTasksPage();
      openUsagePage();
      return;
    }
    if (route.view === "tasks" && tasksAllowed) {
      haltSpeech();
      closeUsagePage();
      openTasksPage();
      return;
    }
    const leavingUsage = wrap.classList.contains("page-usage") || wrap.classList.contains("page-tasks");
    closeUsagePage();
    closeTasksPage();
    const id = route.sessionId;
    if (id === sessionId && !leavingUsage) return;
    if (id) openSession(id, true);
    else {
      leaveChat();
      sessionId = "";
      switchComposer("");
      freshChat = true;
      titleEl.textContent = t("new_chat");
      showEmpty();
    }
  }
  let streaming = false;
  let liveStream = false;
  let watchGen = 0;
  let turnStopping = false;
  let turnStopDone = null;
  // Queued prompts belong to their chat; nextTurns is the open chat's own list.
  const chatQueues = createChatQueues();
  let nextTurns = chatQueues.of("");
  let sendQueued = null;
  // Chat ids whose queued prompts are being sent while another chat is open.
  const backgroundRuns = new Map();
  let destroyed = false;
  // The chat the composer text belongs to (NEW_CHAT_DRAFT for the new chat screen).
  let draftOwner = null;
  // Picked files and images of a draft stay in memory only (too big for localStorage).
  const draftFiles = new Map();
  const draftMemory = new Map();
  let draftSaveTimer = 0;
  const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
  const MAX_FILE_BYTES = 256 * 1024;
  const IMAGE_EDGE = 1280;
  const TEXT_EXT = /\.(ya?ml|json|toml|ini|cfg|conf|env|txt|md|markdown|csv|tsv|xml|html?|css|js|mjs|cjs|tsx?|jsx|py|sh|bash|sql|log)$/i;
  let pending = [];
  let attachNoticeTimer = 0;
  let micNoticeTimer = 0;
  let pinBottom = true;
  let holdFollow = false;
  let jumping = false;
  let jumpTimer = 0;
  let lastScrollTop = 0;
  // Last chat position we accepted, and when the user last typed in the prompt (see typingGuard).
  let acceptedTop = 0;
  let typingAt = 0;
  let followRaf = 0;
  let followLast = 0;
  let motionTimer = 0;
  let userScrollAt = 0;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // The text field inside ha-textarea (the element itself for the Standard textarea).
  function composerInner() {
    if (messageEl?.localName !== "ha-textarea") return messageEl;
    return messageEl.shadowRoot?.querySelector("wa-textarea")?.shadowRoot?.querySelector("textarea") || null;
  }

  // Height of one text line in `el`, padding and (for border-box) borders included.
  function oneLineHeight(el) {
    const style = getComputedStyle(el);
    const px = (v) => parseFloat(v) || 0;
    let line = px(style.lineHeight);
    if (!line) line = px(style.fontSize) * 1.2;
    let h = line + px(style.paddingTop) + px(style.paddingBottom);
    if (style.boxSizing === "border-box") h += px(style.borderTopWidth) + px(style.borderBottomWidth);
    return Math.ceil(h);
  }

  // The prompt text was set by code (sent, cleared, restored, dictated). ha-textarea passes
  // a new value to its inner textarea only on its next render; the size is measured from
  // the inner one, so it gets the text now.
  function setComposerText(text) {
    const value = String(text ?? "");
    messageEl.value = value;
    const inner = composerInner();
    if (inner && inner !== messageEl && inner.value !== value) inner.value = value;
  }

  function resizeComposer() {
    syncComposerField();
    if (!messageEl) return;
    const holdTop = chatEl.scrollTop;
    const inner = composerInner();
    // Placeholder first: an empty field is measured with it.
    const prompt = streaming ? t("placeholder_next") : t("placeholder");
    if ("placeholder" in messageEl) messageEl.placeholder = prompt;
    if (messageEl.localName !== "ha-textarea") messageEl.setAttribute("placeholder", prompt);
    syncFieldLines();
    const empty = !String(inner?.value ?? messageEl.value ?? "");
    if (messageEl.localName === "textarea") {
      const minH = 36;
      const maxH = 160;
      messageEl.style.height = "auto";
      // Empty: one line, whatever the placeholder (a wrapping placeholder counts in scrollHeight).
      const scrollH = empty ? minH : messageEl.scrollHeight;
      const h = Math.min(Math.max(scrollH, minH), maxH);
      messageEl.style.height = `${h}px`;
      // Avoid a stray in-field scrollbar until content actually exceeds the cap.
      const overflows = scrollH > maxH;
      messageEl.style.overflowY = overflows ? "auto" : "hidden";
      messageEl.classList.toggle("message-overflows", overflows);
    } else if (inner && messageEl.localName === "ha-textarea") {
      // ha-textarea only grows on its own input; a cleared or restored text keeps the old height.
      inner.style.height = "auto";
      inner.style.height = `${empty ? oneLineHeight(inner) : inner.scrollHeight}px`;
    }
    syncSendButton();
    setComposerDisabled(".attach", pending.length >= MAX_ATTACH);
    chatEl.scrollTop = holdTop;
  }

  // The prompt is one row (text, then the buttons) while the text fits beside the buttons;
  // once it needs more lines the text gets the full width and the buttons sit below it, on
  // the right. Measured from the text itself, not the current layout, so the box does not
  // flip back and forth at the edge.
  let measureCanvas = null;
  function syncFieldLines() {
    const ha = messageEl.localName === "ha-textarea";
    const field = messageEl.closest?.(ha ? ".composer-field" : ".composer-row");
    const actions = field?.querySelector(ha ? ".composer-field-actions" : ".composer-actions");
    const inner = composerInner();
    if (!field) return;
    // setComposerText keeps the inner textarea current; an empty prompt is one row.
    const value = String(inner?.value ?? messageEl.value ?? "");
    if (!value) {
      field.classList.remove("multi");
      return;
    }
    if (!actions || !inner || !field.clientWidth) return;
    let multi = value.includes("\n");
    if (!multi && value) {
      const style = getComputedStyle(inner);
      measureCanvas ||= document.createElement("canvas");
      const ctx = measureCanvas.getContext("2d");
      ctx.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const textWidth = ctx.measureText(value).width;
      const edges = (s, a, b) => parseFloat(s[a]) + parseFloat(s[b]);
      const padX = edges(style, "paddingLeft", "paddingRight") + edges(style, "borderLeftWidth", "borderRightWidth");
      // Everything around the text inside the field (padding, borders, ha-textarea's own margins).
      const chrome = messageEl.getBoundingClientRect().width - (inner.getBoundingClientRect().width - padX);
      const box = getComputedStyle(field);
      const gap = parseFloat(box.columnGap) || 0;
      const content = field.clientWidth - edges(box, "paddingLeft", "paddingRight");
      const room = content - actions.getBoundingClientRect().width - gap - chrome;
      multi = textWidth + 8 > room;
    }
    field.classList.toggle("multi", multi);
  }

  function holdChatScroll(fn) {
    const holdTop = chatEl.scrollTop;
    fn();
    chatEl.scrollTop = holdTop;
    requestAnimationFrame(() => {
      chatEl.scrollTop = holdTop;
    });
  }

  function keepComposerFocus() {
    return window.matchMedia("(pointer: fine)").matches && !mqNarrow.matches;
  }

  function hideKeyboard() {
    messageEl.blur();
    composerControls(".send").forEach((btn) => btn.blur());
    const active = document.activeElement;
    if (active && active !== document.body && typeof active.blur === "function") active.blur();
    clearKeyboardLock();
  }

  function composerFocused() {
    return messageEl.matches(":focus-within") || messageEl.matches(":focus") || root.activeElement === messageEl;
  }

  let keyboardRaf = 0;
  let keyboardInset = 0;
  let keyboardOpen = false;
  let keyboardWroteAt = 0;

  function resetOuterScroll() {
    const start =
      root.getRootNode?.()?.host ||
      root.parentElement ||
      root.host ||
      null;
    resetHaShellScroll(start);
  }

  function clearKeyboardLock() {
    keyboardOpen = false;
    keyboardInset = 0;
    keyboardWroteAt = 0;
    wrap.classList.remove("keyboard-open");
    wrap.style.height = "";
    form.style.removeProperty("--ai-keyboard-inset");
    wrap.style.removeProperty("--ai-keyboard-inset");
    syncWelcomeInset();
  }

  // Only in the welcome state: the stage holds the whole log, and a long chat must not restyle per keyboard frame.
  function syncWelcomeInset() {
    if (keyboardOpen && chatEl.classList.contains("welcome")) {
      stageEl.style.setProperty("--ai-keyboard-inset", `${keyboardInset}px`);
    } else {
      stageEl.style.removeProperty("--ai-keyboard-inset");
    }
  }

  function keyboardGap() {
    const vv = window.visualViewport;
    // Overlay keyboards shrink visualViewport.height. Ignore offsetTop so IME
    // pan does not chase the composer (that loop is the rubber-band).
    // Measured from the chat's own bottom: the shell can reserve space below it (Android gesture bar).
    return vv ? Math.max(0, Math.round(chatEl.getBoundingClientRect().bottom - vv.height)) : 0;
  }

  function syncKeyboardInset() {
    if (keepComposerFocus()) return;
    if (keyboardRaf) return;
    keyboardRaf = requestAnimationFrame(applyKeyboardInset);
  }

  function applyKeyboardInset() {
    keyboardRaf = 0;
    if (keepComposerFocus()) return;
    const next = keyboardGap();
    const open = composerFocused() && next > 80;
    if (!open) {
      if (keyboardOpen) clearKeyboardLock();
      return;
    }
    const opened = !keyboardOpen;
    const delta = Math.abs(next - keyboardInset);
    if (!opened && delta < 8) return;
    const now = performance.now();
    if (!opened && delta < 48 && now - keyboardWroteAt < 120) return;
    keyboardOpen = true;
    keyboardInset = next;
    keyboardWroteAt = now;
    form.style.setProperty("--ai-keyboard-inset", `${next}px`);
    syncWelcomeInset();
    if (opened) {
      if (followRaf) {
        cancelAnimationFrame(followRaf);
        followRaf = 0;
      }
      wrap.classList.add("keyboard-open");
    }
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
      syncWelcomeInset();
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
    syncWelcomeInset();
    clearMotion();
    syncScrollBottomBtn();
  }

  function overlayDrawer() {
    if (!compact) return null;
    return root.closest?.(".drawer") || root.getRootNode?.()?.querySelector?.(".drawer") || null;
  }

  function overlayOpen() {
    if (!compact) return true;
    return Boolean(overlayDrawer()?.classList.contains("open"));
  }

  function chatVisible() {
    return overlayOpen() && document.visibilityState !== "hidden";
  }

  // Resolves to null when nobody is signed in. Network errors reject only with { raise: true }.
  // With { timeout }, the request is aborted after that many ms (a TimeoutError with raise).
  async function apiFetch(url, options = {}, { raise = false, timeout = 0 } = {}) {
    const limit = timeout ? timeoutSignal(timeout, options.signal) : null;
    if (limit) options = { ...options, signal: limit.signal };
    try {
      return await apiFetchNow(url, options, raise);
    } finally {
      limit?.done();
    }
  }

  async function apiFetchNow(url, options, raise) {
    const hass = hassObj();
    const auth = hass?.auth;
    try {
      if (typeof hass?.fetchWithAuth === "function") {
        return await hass.fetchWithAuth(url, options);
      }
      if (auth?.expired && typeof auth.refreshAccessToken === "function") {
        await auth.refreshAccessToken();
      }
      if (auth?.expired) return null;
      const token = auth?.data?.access_token || auth?.accessToken || getToken();
      if (!token) return null;
      return await fetch(url, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...(options.headers || {}),
        },
      });
    } catch (err) {
      if (raise) throw err;
      console.debug("AI Workspace request failed", url, err);
      return null;
    }
  }

  // Status labels always start with a capital letter, also texts that come from Cursor or the runtime.
  function capitalized(text) {
    const value = String(text || "");
    if (!value) return value;
    const first = value.codePointAt(0);
    const head = String.fromCodePoint(first);
    return head.toLocaleUpperCase(hassLanguage()) + value.slice(head.length);
  }

  function prettyStatus(text) {
    const raw = String(text || "").trim();
    if (!raw || /^done\.?$/i.test(raw)) return "";
    if (/^no mcp servers configured\.?$/i.test(raw)) return "";
    if (/^mcp:\s/i.test(raw)) return "";
    if (/^running$/i.test(raw)) return t("working");
    if (/^working\.{0,3}$/i.test(raw)) return t("working");
    if (/^thinking\.{0,3}$/i.test(raw)) return t("thinking");
    return capitalized(raw);
  }

  function toolsBusy(root) {
    return Boolean(root?.querySelector(".tools .busy"));
  }

  // While text is appearing, the answer itself shows progress. Once it pauses for this long
  // (the agent went back to tools or is thinking), "Working" comes back instead of nothing.
  const TEXT_QUIET_MS = 1200;
  let textPaintedAt = 0;
  let quietTimer = 0;

  function textIsMoving() {
    // The typing pump paints every frame while text is left, so this stays fresh until it is all shown.
    return performance.now() - textPaintedAt < TEXT_QUIET_MS;
  }

  function noteTextPainted(bubble) {
    textPaintedAt = performance.now();
    clearTimeout(quietTimer);
    quietTimer = setTimeout(function recheck() {
      if (!bubble.isConnected || !bubble.classList.contains("streaming")) return;
      if (textIsMoving()) {
        quietTimer = setTimeout(recheck, TEXT_QUIET_MS);
        return;
      }
      // Only fill an empty slot; a status the agent sent stays as it is.
      if (bubble.querySelector(".activity.idle")) setActivity(bubble, "");
    }, TEXT_QUIET_MS + 50);
  }

  function pendingStatus(bubble, text) {
    const pretty = prettyStatus(text);
    if (pretty) return pretty;
    if (!bubble?.classList.contains("streaming") || bubble.classList.contains("error")) return "";
    if (bubble.classList.contains("has-text") && !toolsBusy(bubble) && textIsMoving()) return "";
    return t("working");
  }

  // A small plain glyph in front of the status, one per kind of moment:
  // : : working, : : thinking (four turning dots), + reading the house,
  // = changing the house (lines run down), - waiting (a turning dash).
  const PLUS_GLYPH =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" aria-hidden="true"><path d="M12 4v16M4 12h16"/></svg>';
  const DOTS_GLYPH =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true"><circle class="dot" cx="7" cy="7" r="2.5" fill="currentColor"/><circle class="dot" cx="17" cy="7" r="2.5" fill="currentColor"/><circle class="dot" cx="7" cy="17" r="2.5" fill="currentColor"/><circle class="dot" cx="17" cy="17" r="2.5" fill="currentColor"/></svg>';
  const ACTIVITY_GLYPHS = {
    work: DOTS_GLYPH,
    think: DOTS_GLYPH,
    read: PLUS_GLYPH,
    write:
      '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" aria-hidden="true"><g class="lines"><path d="M5 -1.5h14M5 7.5h14M5 16.5h14M5 25.5h14"/></g></svg>',
    wait: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" aria-hidden="true"><path d="M5 12h14"/></svg>',
  };
  const TOOL_GLYPHS = new Set(["read", "write"]);
  const WRITE_TOOL =
    /(?:^|[_\-.\s])(set|create|delete|remove|update|rename|call|bulk|add|install|uninstall|restart|reload|enable|disable|assign|move|toggle|turn|write|edit|str_replace|apply|restore)(?:[_\-.\s]|$)/i;
  const WAIT_STATUS = /\b(wait|waiting|queued|queue)\b/i;

  function toolGlyphKind(name) {
    const text = String(name || "").trim();
    if (!text) return "work";
    return WRITE_TOOL.test(text) ? "write" : "read";
  }

  function activityGlyphKind(bubble) {
    const busy = [...(bubble?.querySelectorAll(".tools .busy") || [])];
    const last = busy[busy.length - 1];
    if (last) {
      return toolGlyphKind(last.dataset.tool && last.dataset.tool.toLowerCase() !== "mcp" ? last.dataset.tool : last.textContent);
    }
    const label = String(bubble?.querySelector(".activity .label")?.textContent || "").trim();
    if (label && label === t("thinking")) return "think";
    if (WAIT_STATUS.test(label)) return "wait";
    return "work";
  }

  function activityGlyph(kind = "work") {
    const glyph = document.createElement("span");
    glyph.className = "glyph";
    glyph.dataset.kind = kind;
    glyph.innerHTML = ACTIVITY_GLYPHS[kind];
    return glyph;
  }

  function fillActivitySlot(el, label) {
    el.replaceChildren(activityGlyph(), label);
  }

  // A tool icon stays at least this long, so quick tool calls in a row do not flicker.
  const GLYPH_HOLD_MS = 700;

  function syncActivityGlyph(bubble) {
    const glyph = bubble?.querySelector(".activity .glyph");
    if (!glyph) return;
    const kind = activityGlyphKind(bubble);
    if (glyph.dataset.kind === kind) {
      return;
    }
    const shown = performance.now() - Number(glyph.dataset.since || 0);
    if (!TOOL_GLYPHS.has(kind) && TOOL_GLYPHS.has(glyph.dataset.kind) && shown < GLYPH_HOLD_MS) {
      clearTimeout(glyph._hold);
      glyph._hold = setTimeout(() => syncActivityGlyph(bubble), GLYPH_HOLD_MS - shown + 20);
      return;
    }
    clearTimeout(glyph._hold);
    glyph.dataset.kind = kind;
    glyph.dataset.since = String(performance.now());
    glyph.innerHTML = ACTIVITY_GLYPHS[kind];
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
      fillActivitySlot(el, label);
      bubble.appendChild(el);
    }
    // Keep the status chip under tools and text so it never shifts the answer
    // (but above the reply's own action row, which stays last).
    const row = bubble.querySelector(":scope > .reply-actions");
    if (row) {
      if (el.nextElementSibling !== row) bubble.insertBefore(el, row);
    } else if (el.parentElement !== bubble || bubble.lastElementChild !== el) {
      bubble.appendChild(el);
    }
    return el;
  }

  function setActivity(bubble, text) {
    if (!bubble) return;
    const pretty = pendingStatus(bubble, text);
    const el = ensureActivitySlot(bubble);
    let label = el.querySelector(".label");
    if (!label) {
      label = document.createElement("span");
      label.className = "label";
      fillActivitySlot(el, label);
    } else if (!el.querySelector(".glyph")) {
      el.prepend(activityGlyph());
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
    syncActivityGlyph(bubble);
  }

  function lastAssistantBubble() {
    const live = logEl.querySelector(".bubble.assistant.streaming");
    if (live) return live;
    const bubbles = logEl.querySelectorAll(".bubble.assistant");
    return bubbles[bubbles.length - 1] || null;
  }

  function setStatus(text) {
    const bubble = lastAssistantBubble();
    if (!bubble) return;
    setActivity(bubble, text);
  }

  function planResetLabel(epoch) {
    const ts = Number(epoch);
    if (!Number.isFinite(ts) || ts <= 0) return "?";
    const tz = hassObj()?.config?.time_zone;
    try {
      return new Date(ts * 1000).toLocaleString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: tz || undefined,
      });
    } catch (_err) {
      return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    }
  }

  function planResetDayLabel(epoch) {
    const ts = Number(epoch);
    if (!Number.isFinite(ts) || ts <= 0) return "?";
    const tz = hassObj()?.config?.time_zone;
    const opts = { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" };
    try {
      return new Date(ts * 1000).toLocaleString(undefined, { ...opts, timeZone: tz || undefined });
    } catch (_err) {
      return new Date(ts * 1000).toLocaleString(undefined, opts);
    }
  }

  // Session reset: only the time when it is today (in HA's time zone), else weekday, date and time.
  function planResetSmartLabel(epoch) {
    const ts = Number(epoch);
    if (!Number.isFinite(ts) || ts <= 0) return "?";
    const tz = hassObj()?.config?.time_zone;
    const day = (when) => {
      try {
        return new Date(when).toLocaleDateString("en-CA", { timeZone: tz || undefined });
      } catch (_err) {
        return new Date(when).toLocaleDateString("en-CA");
      }
    };
    return day(ts * 1000) === day(Date.now()) ? planResetLabel(ts) : planResetDayLabel(ts);
  }

  function planHasData(snap) {
    if (!snap) return false;
    return ["status", "session_percent", "week_percent", "session_reset_at", "week_reset_at"].some(
      (key) => snap[key] != null && snap[key] !== "",
    );
  }

  function planHasPercent(snap) {
    return Boolean(snap) && (snap.session_percent != null || snap.week_percent != null);
  }

  // One window of a snapshot: percent (0 once the window has rolled over), reset, rolled over.
  function planWindow(snap, name) {
    const raw = snap?.[`${name}_percent`];
    const reset = snap?.[`${name}_reset_at`];
    const gone = reset != null && Number(reset) > 0 && Number(reset) <= Date.now() / 1000;
    let percent = raw == null || raw === "" ? null : Math.max(0, Math.min(100, Math.round(Number(raw))));
    if (!Number.isFinite(percent)) percent = null;
    if (gone && percent != null) percent = 0;
    return { percent, reset: reset == null || gone ? null : reset, gone };
  }

  // Same thresholds for the Usage cards and the chat header: yellow from 60 %, red from 85 %.
  function planLevel(percent) {
    const n = Number(percent);
    if (percent == null || !Number.isFinite(n)) return "ok";
    if (n >= 85) return "high";
    if (n >= 60) return "mid";
    return "ok";
  }

  // Plan data for an agent that bills a subscription. The backend resolves "billing" ("plan": its own
  // Plan token, or the Runtime's own credential when the Runtime reports a subscription for that
  // engine; "api_key" / "unknown" / "api": $) and names the credential in "plan_credential". Only a
  // snapshot of that engine from exactly that credential counts: never another agent's sign-in.
  function planSnapForAgent(item, quota) {
    if (!item || String(item.billing || "") !== "plan") return null;
    const credential = String(item.plan_credential || "");
    if (!credential) return null;
    const snap = quota?.[String(item.provider || "")];
    if (!snap || String(snap.credential || "") !== credential) return null;
    return planHasPercent(snap) ? snap : null;
  }

  let lastPlanQuota = {};

  function planAgentIds(quota) {
    return new Set(providerItems.filter((item) => planSnapForAgent(item, quota)).map((item) => item.id));
  }

  // Header text where the chat's $ used to be: "5h 12% · W 16%", colored by the higher window.
  function planChip(snap, costText) {
    const session = planWindow(snap, "session");
    const week = planWindow(snap, "week");
    const fmt = (value) => (value.percent == null ? t("usage_plan_unknown") : `${value.percent}%`);
    const chip = document.createElement("span");
    chip.className = "chat-plan";
    chip.dataset.level = planLevel(Math.max(session.percent ?? -1, week.percent ?? -1));
    chip.textContent = t("chat_plan_short", { session: fmt(session), week: fmt(week) });
    const resetText = (value, label) =>
      value.gone ? t("usage_plan_rolled_over") : value.reset != null ? `${t("usage_plan_reset")} ${label(value.reset)}` : "";
    const line = (name, value, label) => {
      const reset = resetText(value, label);
      const pct = value.percent == null ? t("usage_plan_unknown") : `${value.percent}%`;
      return `${name}: ${pct}${reset ? ` (${reset})` : ""}`;
    };
    const lines = [
      line(t("usage_plan_session"), session, planResetSmartLabel),
      line(t("usage_plan_week"), week, planResetDayLabel),
    ];
    if (snap.overage) lines.push(t("usage_plan_overage"));
    if (costText) lines.push(t("chat_plan_cost", { cost: costText }));
    chip.title = lines.join("\n");
    chip.setAttribute("aria-label", lines.join(". "));
    return chip;
  }

  // The chat's usage line; for a plan agent the $ part becomes the plan chip (same place, no new row).
  let chatUsageShown = null;

  function setChatUsageLine(prefix, bits, costText, snap) {
    if (!chatUsageEl) return;
    chatUsageShown = { prefix, bits, costText };
    const nodes = [];
    const text = (value) => document.createTextNode(value);
    if (prefix) nodes.push(text(`${prefix}: `));
    const before = bits.before.join(" · ");
    const after = bits.after.join(" · ");
    if (snap) {
      if (before) nodes.push(text(`${before} · `));
      nodes.push(planChip(snap, costText));
      if (after) nodes.push(text(` · ${after}`));
    } else {
      nodes.push(text([...bits.before, ...(costText ? [costText] : []), ...bits.after].join(" · ")));
    }
    chatUsageEl.replaceChildren(...nodes);
    chatUsageEl.hidden = false;
  }

  function chatPlanSnap() {
    return planSnapForAgent(providerItems.find((item) => item.id === selectedAgent()), lastPlanQuota);
  }

  // The agent list arrived or the chat's agent changed: $ or plan for the line already shown.
  function rerenderChatUsage() {
    if (!chatUsageShown || !chatUsageEl || chatUsageEl.hidden) return;
    const { prefix, bits, costText } = chatUsageShown;
    setChatUsageLine(prefix, bits, costText, chatPlanSnap());
  }

  function planBar(label, value, resetLabel) {
    const row = document.createElement("div");
    row.className = "usage-plan-row";
    row.dataset.level = planLevel(value.percent);
    const head = document.createElement("div");
    head.className = "usage-plan-row-head";
    const name = document.createElement("span");
    name.className = "usage-plan-label";
    name.textContent = label;
    const pct = document.createElement("span");
    pct.className = "usage-plan-pct";
    pct.textContent = value.percent == null ? t("usage_plan_unknown") : `${value.percent}%`;
    head.append(name, pct);
    const bar = document.createElement("div");
    bar.className = "usage-plan-bar";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-label", label);
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    if (value.percent != null) bar.setAttribute("aria-valuenow", String(value.percent));
    const fill = document.createElement("span");
    fill.className = "usage-plan-fill";
    fill.style.width = `${value.percent ?? 0}%`;
    bar.appendChild(fill);
    row.append(head, bar);
    const resetText = value.gone
      ? t("usage_plan_rolled_over")
      : value.reset != null
        ? `${t("usage_plan_reset")} ${resetLabel(value.reset)}`
        : "";
    if (resetText) {
      const reset = document.createElement("p");
      reset.className = "usage-plan-reset";
      reset.textContent = resetText;
      row.appendChild(reset);
    }
    return row;
  }

  // One plan as a usage card: two bars (session, week) with their resets, warnings, as-of and link.
  function planCard(engine, snap, link) {
    const card = document.createElement("article");
    card.className = "usage-card usage-plan";
    const title = document.createElement("p");
    title.className = "usage-card-title";
    title.textContent = t(`usage_plan_${engine}`);
    card.appendChild(title);
    if (planHasPercent(snap)) {
      card.append(
        planBar(t("usage_plan_session"), planWindow(snap, "session"), planResetSmartLabel),
        planBar(t("usage_plan_week"), planWindow(snap, "week"), planResetDayLabel),
      );
    } else {
      const line = document.createElement("p");
      line.className = "usage-card-meta";
      line.textContent = planUsageLine(snap);
      card.appendChild(line);
    }
    const warnings = [];
    if (planHasPercent(snap)) {
      if (snap.status === "rejected") warnings.push(t("usage_plan_status_rejected"));
      else if (snap.status === "allowed_warning") warnings.push(t("usage_plan_status_warning"));
    }
    if (snap.overage) warnings.push(t("usage_plan_overage"));
    for (const text of warnings) {
      const warn = document.createElement("p");
      warn.className = "usage-plan-warn";
      warn.setAttribute("role", "status");
      warn.textContent = text;
      card.appendChild(warn);
    }
    const when = Date.parse(snap.updated_at || "");
    if (Number.isFinite(when) || link) {
      const foot = document.createElement("div");
      foot.className = "usage-plan-foot";
      if (Number.isFinite(when)) {
        const asOf = document.createElement("span");
        asOf.className = "usage-plan-asof";
        asOf.textContent = t("usage_plan_updated", { when: planResetDayLabel(Math.floor(when / 1000)) });
        foot.appendChild(asOf);
      }
      if (link) {
        const a = document.createElement("a");
        a.className = "usage-plan-link";
        a.href = link;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = t("usage_plan_official");
        foot.appendChild(a);
      }
      card.appendChild(foot);
    }
    return card;
  }

  // One line per plan: session % (reset), week % (reset). Status only (the SDK sent no percent): say so.
  function planUsageLine(snap) {
    const nowSec = Date.now() / 1000;
    const hasPercent = snap.session_percent != null || snap.week_percent != null;
    if (!hasPercent) {
      if (snap.status === "rejected") return t("usage_plan_status_rejected");
      if (snap.status === "allowed_warning") return t("usage_plan_status_warning");
      return t("usage_plan_below_warning");
    }
    const parts = [];
    const sessionGone = snap.session_reset_at != null && Number(snap.session_reset_at) <= nowSec;
    const weekGone = snap.week_reset_at != null && Number(snap.week_reset_at) <= nowSec;
    let session = snap.session_percent == null ? t("usage_plan_unknown") : `${snap.session_percent}%`;
    if (sessionGone) session = t("usage_plan_rolled_over");
    else if (snap.session_reset_at != null) session += ` (${t("usage_plan_reset")} ${planResetLabel(snap.session_reset_at)})`;
    parts.push(`${t("usage_plan_session")}: ${session}`);
    let week = snap.week_percent == null ? t("usage_plan_unknown") : `${snap.week_percent}%`;
    if (weekGone) week = t("usage_plan_rolled_over");
    else if (snap.week_reset_at != null) week += ` (${t("usage_plan_reset")} ${planResetDayLabel(snap.week_reset_at)})`;
    parts.push(`${t("usage_plan_week")}: ${week}`);
    return parts.join(" · ");
  }

  function planEngineTitle(engine) {
    const key = `usage_plan_${String(engine || "claude")}`;
    return t(key);
  }

  function planNoticeText(data) {
    const engine = planEngineTitle(data?.engine || "claude");
    const session = data?.session_percent;
    const week = data?.week_percent;
  const reset = planResetLabel(data?.session_reset_at);
    if (session != null && week != null) {
      return t("plan_notice_both", { engine, session, week, reset });
    }
    if (session != null) return t("plan_notice_session", { engine, percent: session, reset });
    if (week != null) return t("plan_notice_week", { engine, percent: week });
    return "";
  }

  // The agent fallback: who stopped and who goes on, paused or back. The chat now runs on data.to.
  function applyFallback(data) {
    const text = String(data?.message || "").trim();
    if (text && logEl) {
      const note = document.createElement("p");
      note.className = "plan-notice fallback-notice";
      note.dataset.phase = String(data.phase || "");
      note.textContent = text;
      logEl.appendChild(note);
      if (nearBottom()) followBottom();
    }
    if (data?.to && knownAgent(data.to)) setChatChoice(data.to, "");
  }

  function appendPlanNotice(data) {
    const text = planNoticeText(data);
    if (!text || !logEl) return;
    const note = document.createElement("p");
    note.className = "plan-notice";
    note.textContent = text;
    logEl.appendChild(note);
    if (nearBottom()) followBottom();
  }

  // Questions from MCP tools (elicitation) and worker jobs waiting for an approval. Only a click
  // here answers them; the agent never sees them and chat text does not count.
  const approvalCards = new Map();
  let approvalPoll = 0;

  function approvalTarget(worker) {
    const host = worker.user ? `${worker.user}@${worker.host}` : worker.host || "";
    return worker.hostname && worker.hostname !== worker.host ? `${host} (${worker.hostname})` : host;
  }

  function approvalLeft(data) {
    const at = Number(data.expires_at || 0) * 1000;
    if (at) return Math.max(0, Math.round((at - Date.now()) / 1000));
    return Math.max(0, Number(data.expires_in || 0) - Math.round((performance.now() - (data._seen || 0)) / 1000));
  }

  function syncApprovalTimer(entry) {
    const left = approvalLeft(entry.data);
    if (left <= 0) {
      closeApprovalCard(entry.data.id, "timeout");
      return;
    }
    entry.timerEl.textContent =
      left < 60 ? t("approval_expires_soon") : t("approval_expires", { minutes: Math.ceil(left / 60) });
  }

  function approvalField(field) {
    const row = document.createElement("label");
    row.className = "approval-field";
    const name = document.createElement("span");
    name.className = "approval-field-name";
    name.textContent = field.title || field.name;
    if (field.required) name.textContent += " *";
    let input;
    if (field.kind === "boolean") {
      row.classList.add("approval-check");
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = field.default === true;
      row.append(input, name);
    } else if (field.kind === "enum") {
      input = document.createElement("select");
      if (!field.required) input.append(new Option("", ""));
      (field.choices || []).forEach((value, index) => {
        input.append(new Option((field.labels || [])[index] || value, value));
      });
      if (field.default != null) input.value = String(field.default);
      row.append(name, input);
    } else if (field.kind === "number" || field.kind === "integer") {
      input = document.createElement("input");
      input.type = "number";
      input.step = field.kind === "integer" ? "1" : "any";
      if (field.minimum != null) input.min = String(field.minimum);
      if (field.maximum != null) input.max = String(field.maximum);
      if (field.default != null) input.value = String(field.default);
      row.append(name, input);
    } else if (field.kind === "string") {
      input = document.createElement("input");
      input.type = { email: "email", uri: "url", date: "date", "date-time": "datetime-local" }[field.format] || "text";
      if (field.maxLength) input.maxLength = field.maxLength;
      if (field.default != null) input.value = String(field.default);
      row.append(name, input);
    } else {
      const note = document.createElement("span");
      note.className = "approval-hint";
      note.textContent = t("approval_unsupported");
      row.append(name, note);
      return { row, read: () => undefined, field };
    }
    input.className = "approval-input";
    input.name = field.name;
    if (field.description) {
      const hint = document.createElement("span");
      hint.className = "approval-hint";
      hint.textContent = field.description;
      row.append(hint);
    }
    const error = document.createElement("span");
    error.className = "approval-error";
    error.hidden = true;
    row.append(error);
    const read = () => {
      if (field.kind === "boolean") return input.checked;
      const value = String(input.value ?? "");
      if (!value.trim()) return undefined;
      if (field.kind === "number" || field.kind === "integer") return Number(value);
      return value;
    };
    return { row, read, field, error };
  }

  function approvalCard(data) {
    const card = document.createElement("div");
    card.className = "approval-card";
    card.dataset.approvalId = data.id;
    card.setAttribute("role", "group");
    const head = document.createElement("div");
    head.className = "approval-head";
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", "mdi:shield-key-outline");
    const title = document.createElement("strong");
    title.textContent = data.confirmation === false ? t("approval_question") : t("approval_title");
    const close = document.createElement("button");
    close.type = "button";
    close.className = "approval-dismiss";
    close.setAttribute("aria-label", t("approval_dismiss"));
    close.title = t("approval_dismiss");
    close.textContent = "×";
    head.append(icon, title, close);
    card.setAttribute("aria-label", title.textContent);
    const from = document.createElement("div");
    from.className = "approval-from";
    from.textContent = t("approval_from", { server: data.server || "MCP" });
    card.append(head, from);
    const worker = data.kind === "worker" ? data.worker || {} : null;
    if (worker) {
      const what = document.createElement("div");
      what.className = "approval-what";
      what.textContent = `${worker.tool || "ssh"} · ${t("approval_target")} ${approvalTarget(worker)}`;
      const cmdLabel = document.createElement("div");
      cmdLabel.className = "approval-label";
      cmdLabel.textContent = t("approval_command");
      const cmd = document.createElement("pre");
      cmd.className = "approval-command";
      cmd.textContent = worker.command || t("approval_interactive");
      card.append(what, cmdLabel, cmd);
      if (worker.job_id) {
        const job = document.createElement("div");
        job.className = "approval-hint";
        job.textContent = t("approval_job", { job: worker.job_id });
        card.append(job);
      }
    } else if (data.message) {
      const message = document.createElement("div");
      message.className = "approval-message";
      message.textContent = data.message;
      card.append(message);
    }
    // MCP URL mode: the full link, opened only by the user's own click.
    const link = !worker && /^https?:\/\/\S+$/i.test(String(data.url || "")) ? String(data.url) : "";
    if (link) {
      const anchor = document.createElement("a");
      anchor.className = "approval-link";
      anchor.href = link;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = link;
      card.append(anchor);
    }
    const flag = data.approval_field || "";
    const inputs = (data.fields || []).filter((field) => field.name !== flag).map(approvalField);
    if (inputs.length) {
      const form = document.createElement("div");
      form.className = "approval-form";
      inputs.forEach((item) => form.append(item.row));
      card.append(form);
    }
    const status = document.createElement("div");
    status.className = "approval-status";
    status.hidden = true;
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const timerEl = document.createElement("span");
    timerEl.className = "approval-timer";
    const deny = document.createElement("ha-button");
    deny.setAttribute("type", "button");
    deny.setAttribute("appearance", "plain");
    deny.setAttribute("variant", "danger");
    deny.className = "approval-deny";
    deny.textContent = t("approval_deny");
    const allow = document.createElement("ha-button");
    allow.setAttribute("type", "button");
    allow.setAttribute("variant", "brand");
    allow.className = "approval-allow";
    allow.textContent = data.confirmation === false ? t("approval_submit") : t("approval_allow");
    actions.append(timerEl, deny, allow);
    card.append(status, actions);
    const entry = { data, card, inputs, status, timerEl, buttons: [allow, deny, close], busy: false };
    // The cards sit in the composer form: no click or Enter here may send the chat message.
    const click = (action) => (event) => {
      event.preventDefault();
      event.stopPropagation();
      answerApproval(entry, action);
    };
    allow.addEventListener("click", click("accept"));
    deny.addEventListener("click", click("decline"));
    close.addEventListener("click", click("cancel"));
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.target?.localName !== "input") return;
      event.preventDefault();
      event.stopPropagation();
    });
    return entry;
  }

  function syncApprovalsShown() {
    if (!approvalsEl) return;
    approvalsEl.hidden = !approvalsEl.childElementCount;
    const open = [...approvalCards.values()].some((entry) => !entry.closed);
    if (open && !approvalPoll) {
      approvalPoll = window.setInterval(() => {
        approvalCards.forEach((entry) => {
          if (!entry.closed) syncApprovalTimer(entry);
        });
        if (sessionId && chatVisible() && !document.hidden) refreshApprovals(sessionId);
      }, 15000);
    } else if (!open && approvalPoll) {
      window.clearInterval(approvalPoll);
      approvalPoll = 0;
    }
  }

  function clearApprovals() {
    approvalCards.clear();
    approvalsEl?.replaceChildren();
    syncApprovalsShown();
  }

  function showApproval(data) {
    if (!data?.id || !approvalsEl) return;
    if (data.session_id && sessionId && data.session_id !== sessionId) return;
    if (data.status && data.status !== "pending") {
      closeApprovalCard(data.id, data.status);
      return;
    }
    const known = approvalCards.get(data.id);
    if (known) {
      if (!known.closed) {
        known.data = { ...known.data, ...data };
        syncApprovalTimer(known);
      }
      return;
    }
    const entry = approvalCard({ ...data, _seen: performance.now() });
    approvalCards.set(data.id, entry);
    approvalsEl.append(entry.card);
    syncApprovalTimer(entry);
    syncApprovalsShown();
    if (nearBottom()) followBottom();
  }

  function closeApprovalCard(id, status) {
    const entry = approvalCards.get(id);
    if (!entry || entry.closed) return;
    entry.closed = true;
    entry.buttons.forEach((button) => {
      button.disabled = true;
    });
    entry.card.classList.add("closed", `approval-${status}`);
    entry.card.querySelector(".approval-form")?.remove();
    entry.card.querySelector(".approval-actions")?.remove();
    entry.status.hidden = false;
    const key = `approval_done_${status}`;
    entry.status.textContent = t(key) === key ? t("approval_done_gone") : t(key);
    // Answered cards go away after a moment; a timeout stays until dismissed, so it is seen.
    const remove = () => {
      if (approvalCards.get(id) !== entry) return;
      approvalCards.delete(id);
      entry.card.remove();
      syncApprovalsShown();
    };
    if (status === "timeout" || status === "ended") {
      const ok = document.createElement("button");
      ok.type = "button";
      ok.className = "approval-dismiss";
      ok.setAttribute("aria-label", t("approval_dismiss"));
      ok.textContent = "×";
      ok.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        remove();
      });
      entry.card.querySelector(".approval-head .approval-dismiss")?.replaceWith(ok);
    } else {
      window.setTimeout(remove, 6000);
    }
    syncApprovalsShown();
  }

  function syncApprovals(list, id = sessionId) {
    if (id !== sessionId) return;
    const open = new Set((list || []).map((item) => item.id));
    approvalCards.forEach((entry, key) => {
      // Answered on another device or timed out there: this page catches up.
      if (!entry.closed && !entry.busy && !open.has(key)) closeApprovalCard(key, "gone");
    });
    (list || []).forEach(showApproval);
    syncApprovalsShown();
  }

  async function refreshApprovals(id) {
    if (!id) return;
    const response = await apiFetch(`${API}/sessions/${id}/approvals`);
    if (!response?.ok || id !== sessionId) return;
    try {
      syncApprovals(await response.json(), id);
    } catch (_error) {
      // A broken answer leaves the cards as they are.
    }
  }

  async function answerApproval(entry, action) {
    if (entry.busy || entry.closed) return;
    const content = {};
    let bad = false;
    if (action === "accept") {
      entry.inputs.forEach((item) => {
        if (item.error) item.error.hidden = true;
        const value = item.read();
        if (value === undefined || Number.isNaN(value)) {
          if (item.field.required && item.error) {
            item.error.textContent = t("approval_required");
            item.error.hidden = false;
            bad = true;
          }
          return;
        }
        content[item.field.name] = value;
      });
      if (entry.data.approval_field) content[entry.data.approval_field] = true;
    }
    if (bad) return;
    entry.busy = true;
    entry.buttons.forEach((button) => {
      button.disabled = true;
    });
    entry.status.hidden = true;
    let body = null;
    let response = null;
    try {
      response = await apiFetch(`${API}/approvals/${encodeURIComponent(entry.data.id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action === "accept" ? { action, content } : { action }),
      });
      body = response ? await response.json().catch(() => null) : null;
    } catch (_error) {
      body = null;
    }
    entry.busy = false;
    const result = body?.status;
    if (result === "invalid") {
      const errors = body.errors || {};
      entry.inputs.forEach((item) => {
        if (!item.error || !errors[item.field.name]) return;
        item.error.textContent = t(errors[item.field.name] === "required" ? "approval_required" : "approval_invalid");
        item.error.hidden = false;
      });
    }
    if (result === "answered" || result === "expired" || result === "gone" || result === "closed") {
      const status =
        result === "answered" ? action : body?.approval?.status && body.approval.status !== "pending" ? body.approval.status : result === "expired" ? "timeout" : "gone";
      closeApprovalCard(entry.data.id, status);
      return;
    }
    entry.buttons.forEach((button) => {
      button.disabled = false;
    });
    if (result !== "invalid") {
      entry.status.textContent = t("approval_failed");
      entry.status.hidden = false;
    }
  }

  function rewriteAssistantLinks(content, mentions = true) {
    let text = stripRemoteMedia(content);
    const here = window.location.origin;
    if (!/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?$/i.test(here)) {
      text = text.replace(/https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?/gi, here);
    }
    text = text.replace(/\]\(([^)]+)\)/g, (_m, url) => `](${rewriteHaHref(url)})`);
    text = text.replace(/(^|[^(])(https?:\/\/[^\s)<]+)/g, (_m, lead, url) => `${lead}${rewriteHaHref(url)}`);
    return linkifyHaMentions(text, mentions);
  }

  async function errorText(response) {
    if (!response) return t("not_signed_in");
    let raw = "";
    try {
      raw = await response.text();
    } catch (_err) {
      raw = "";
    }
    try {
      const body = JSON.parse(raw);
      const detail = body?.message || body?.detail || body?.error;
      if (typeof detail === "string" && detail.trim()) return detail.trim();
    } catch (_err) {
      /* not JSON */
    }
    const plain = raw.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    if (plain && plain.length <= 300 && !/^\d{3}\b/.test(plain)) return plain;
    return `${t("error")} (${response.status})`;
  }

  let noticeTimer = 0;

  function setBanner(text) {
    if (!bannerEl) return;
    const msg = String(text || "");
    bannerEl.textContent = msg;
    bannerEl.hidden = !msg;
  }

  // Hints that do not mean something is broken (an outdated runtime) sit behind a
  // toolbar icon instead of the error banner. The compact overlay has no toolbar.
  const noticePop = root.querySelector(".notice-pop");
  const noticeButtons = () => [...root.querySelectorAll(".notice-open")];
  let hintText = "";

  function closeHint() {
    if (!noticePop || noticePop.hidden) return;
    noticePop.hidden = true;
    noticeButtons().forEach((btn) => btn.setAttribute("aria-expanded", "false"));
  }

  function setHint(text) {
    hintText = String(text || "");
    if (noticePop) noticePop.textContent = hintText;
    noticeButtons().forEach((btn) => {
      btn.hidden = !hintText;
    });
    if (!hintText) closeHint();
  }

  function openHint(btn) {
    if (!noticePop || !hintText) return;
    if (!noticePop.hidden) {
      closeHint();
      return;
    }
    const box = btn.getBoundingClientRect();
    // Hidden elements have no offsetParent; the pop is positioned against .wrap.
    const host = (noticePop.parentElement || root.host || document.body).getBoundingClientRect();
    const width = Math.min(320, host.width - 16);
    const left = Math.max(8, Math.min(box.left - host.left, host.width - width - 8));
    noticePop.style.width = `${width}px`;
    noticePop.style.left = `${left}px`;
    noticePop.style.top = `${box.bottom - host.top + 4}px`;
    noticePop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
  }

  noticeButtons().forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      openHint(btn);
    });
  });
  root.addEventListener("click", (event) => {
    if (noticePop && !noticePop.hidden && !event.composedPath().includes(noticePop)) closeHint();
  });
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeHint();
  });

  function showNotice(text) {
    if (!text) return;
    clearMicHelp();
    setBanner(text);
    if (noticeTimer) clearTimeout(noticeTimer);
    noticeTimer = window.setTimeout(() => {
      if (bannerEl && bannerEl.textContent === text) setBanner("");
    }, 6000);
  }

  // Errors about the connection to the Runtime, not about one answer: they stay in the
  // header until a turn gets through, and the message itself only gets a short note.
  function showConnectionError(text) {
    if (!bannerEl || !text) return;
    clearMicHelp();
    if (noticeTimer) clearTimeout(noticeTimer);
    setBanner(text);
    bannerEl.classList.add("hold", "connection");
  }

  function clearConnectionError() {
    if (!bannerEl?.classList.contains("connection")) return;
    bannerEl.classList.remove("hold", "connection");
    setBanner("");
  }

  function markNotSent(userBubble, restore) {
    const anchor = userBubble;
    if (!anchor?.parentElement) return;
    const restored = Boolean(restore?.text || restore?.pending?.length) && !String(messageEl.value || "").trim() && !pending.length;
    if (restored) {
      setComposerText(restore.text || "");
      pending = restore.pending || [];
      renderThumbs();
    }
    const note = document.createElement("p");
    note.className = "not-sent";
    note.textContent = t(restored ? "not_sent_restored" : "not_sent");
    anchor.classList.add("unsent");
    anchor.after(note);
  }

  // An unsent message is not in the chat's history; the next send replaces it.
  function dropUnsent() {
    logEl.querySelectorAll(".unsent, .not-sent").forEach((node) => node.remove());
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

  function chipToolName(text, name) {
    const fromEvent = chipName(name);
    if (fromEvent) return fromEvent;
    const raw = String(text || "").trim();
    const calling = raw.match(/^Calling\s+(.+?)\s*$/i);
    if (calling) return chipName(calling[1]);
    const finished = raw.match(/^Finished\s+(.+?)\s*$/i);
    if (finished) return chipName(finished[1]);
    return chipName(raw);
  }

  function settleChip(chip) {
    if (!chip) return;
    chip.className = "done";
    chip.style.animation = "none";
    chip.querySelector(".chip-progress")?.remove();
    delete chip.dataset.progress;
  }

  // MCP progress of a running tool: on its chip and as the reply's status line.
  function showToolProgress(bubble, tools, event) {
    const text = toolProgressText(event);
    if (!text || !bubble) return;
    const list = tools?.querySelector?.(".tools-list");
    const chip = list ? progressChip([...list.children].filter(isPendingChip), event) : null;
    if (chip) {
      let note = chip.querySelector(".chip-progress");
      if (!note) {
        note = document.createElement("small");
        note.className = "chip-progress";
        chip.appendChild(note);
      }
      note.textContent = text;
      chip.dataset.progress = text;
    }
    setActivity(bubble, text);
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
    const chips = [...list.children];
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
    return el.classList.contains("busy") || /^calling\b/i.test(el.textContent);
  }

  function addChip(tools, event, animate) {
    if (!event?.text || event.type === "image" || event.type === "file") return;
    const list = ensureToolsChrome(tools);
    const kind = chipClass(event);
    const name = String(event.name || "");
    const callId = String(event.id || event.call_id || "");
    const label = chipToolName(event.text, name);
    if (kind === "done") {
      const chips = [...list.children];
      const pending =
        (callId && chips.find((el) => el.dataset.callId === callId && isPendingChip(el))) ||
        chips.find((el) => name && el.dataset.tool === name && isPendingChip(el)) ||
        chips.find((el) => name && name.toLowerCase() !== "mcp" && el.dataset.tool === "mcp" && isPendingChip(el));
      if (pending) {
        if (name) pending.dataset.tool = name;
        if (callId) pending.dataset.callId = callId;
        if (label) pending.textContent = label;
        settleChip(pending);
        markChipFailed(pending, event);
        syncToolsSummary(tools);
        syncActivityGlyph(tools.closest?.(".bubble"));
        return;
      }
    }
    const chip = document.createElement("span");
    chip.className = kind;
    if (name) chip.dataset.tool = name;
    if (callId) chip.dataset.callId = callId;
    if (!animate || reduceMotion || kind !== "busy") chip.style.animation = "none";
    chip.textContent = label;
    markChipFailed(chip, event);
    list.appendChild(chip);
    syncToolsSummary(tools);
    syncActivityGlyph(tools.closest?.(".bubble"));
  }

  // A tool step that ended with an error (MCP isError, refused, not reachable).
  function markChipFailed(chip, event) {
    if (!chip || !event?.failed) return;
    chip.classList.add("failed");
    chip.title = t("error");
  }

  function settleTools(root) {
    root?.querySelectorAll(".tools .busy").forEach((chip) => settleChip(chip));
    root?.querySelectorAll(".tools").forEach(syncToolsSummary);
    if (root?.classList?.contains("bubble")) syncActivityGlyph(root);
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
      img.alt = pic.name || t("image");
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

  // A reply that stopped in the middle (Home Assistant restarted or the integration reloaded).
  function markReplyCut(bubble) {
    if (!bubble || bubble.querySelector(":scope > .reply-cut")) return;
    const note = document.createElement("div");
    note.className = "reply-cut";
    note.textContent = t("reply_cut");
    bubble.appendChild(note);
  }

  function addBubble(role, content, events, opts = {}) {
    const empty = logEl.querySelector(".empty");
    if (empty) empty.remove();
    setWelcome(false, opts.animate !== false);
    const isError = (events || []).some((event) => event && event.type === "error");
    if (isError && role === "assistant") content = shownError(content);
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    if (isError) bubble.classList.add("error");
    if (opts.createdAt) bubble.dataset.createdAt = String(opts.createdAt);
    if (opts.animate === false || reduceMotion) bubble.classList.add("instant");
    const pics = addBubbleImages(bubble, events);
    const files = addBubbleFiles(bubble, events);
    const chips = (events || []).filter(
      (event) =>
        event && event.type !== "image" && event.type !== "file" && event.type !== "error" && event.type !== "interrupted",
    );
    if (chips.length) {
      const tools = document.createElement("div");
      tools.className = "tools";
      for (const event of chips) addChip(tools, event, opts.animate !== false);
      if (tools.childElementCount) bubble.appendChild(tools);
    }
    if (role === "assistant") {
      const md = document.createElement("ha-markdown");
      md.className = "text";
      md.setAttribute("breaks", "");
      md.setAttribute("cache", "");
      md.breaks = true;
      md.cache = true;
      fillHaMarkdown(md, rewriteAssistantLinks(content || ""));
      md.hidden = !content;
      bubble.appendChild(md);
      if (content) bubble.classList.add("has-text");
      if ((events || []).some((event) => event && event.type === "interrupted")) markReplyCut(bubble);
    } else if (content && !((pics.length || files.length) && isDefaultImageCaption(content))) {
      const text = document.createElement("div");
      text.className = "text";
      text.textContent = content;
      bubble.appendChild(text);
      bubble.classList.add("has-text");
    }
    const parent = opts.parent || logEl;
    parent.appendChild(bubble);
    retargetHaLinks(bubble);
    if (!opts.parent) {
      syncCopyChat();
      if (opts.follow !== false) scrollChatToBottom(opts.smooth !== false);
    }
    return bubble;
  }

  function replyEntries() {
    return [...logEl.querySelectorAll(".bubble")].map((bubble) => {
      const md = bubble.querySelector("ha-markdown.text");
      return {
        bubble,
        role: bubble.classList.contains("assistant") ? "assistant" : "user",
        // The reply markdown only: tool chips, status and "reply cut" notes live outside it.
        text: String(md?.content || md?.textContent || ""),
        streaming: bubble.classList.contains("streaming"),
        error: bubble.classList.contains("error"),
        createdAt: bubble.dataset.createdAt || "",
      };
    });
  }

  // The row sits inside the reply bubble, after its text.
  function replyRowOf(bubble) {
    return bubble ? bubble.querySelector(":scope > .reply-actions") : null;
  }

  function replyActionButton(action, icon, label) {
    const btn = document.createElement("ha-icon-button");
    btn.className = `reply-action reply-${action}`;
    btn.type = "button";
    btn.dataset.action = action;
    btn.label = label;
    btn.setAttribute("aria-label", label);
    const glyph = document.createElement("ha-icon");
    glyph.setAttribute("icon", icon);
    btn.appendChild(glyph);
    return btn;
  }

  function setActionLabel(btn, label) {
    btn.label = label;
    btn.setAttribute("aria-label", label);
  }

  // One row per finished reply: copy, read aloud, time. Clicks go through one listener on
  // the log (see onReplyAction), so long chats add no listener per message.
  function syncReplyRows(entries) {
    // A turn runs from send (incl. a waiting or queued reply) until its text has drained.
    const rows = replyRows(entries, { busy: streaming || liveStream });
    const keep = new Set();
    const opts = replyTimeOptions();
    const today = new Date().toDateString();
    for (const info of rows) {
      const bubble = entries[info.index].bubble;
      let row = replyRowOf(bubble);
      if (!row) {
        row = document.createElement("div");
        row.className = "reply-actions";
        row.setAttribute("role", "group");
        row.setAttribute("aria-label", t("reply_actions"));
        row.appendChild(replyActionButton("copy", "mdi:content-copy", t("copy_reply")));
        row.appendChild(replyActionButton("speak", "mdi:volume-high", t("speak_reply")));
        const timeEl = document.createElement("time");
        timeEl.className = "reply-time";
        row.appendChild(timeEl);
      }
      if (bubble.lastElementChild !== row) bubble.appendChild(row);
      keep.add(row);
      row.classList.toggle("is-last", info.last);
      row.classList.toggle("is-held", info.held);
      // Fade in only for a reply that just finished in this view, never on open or re-render.
      if (info.last && bubble._replyFresh) {
        bubble._replyFresh = false;
        row.classList.remove("is-fresh");
        void row.offsetWidth;
        row.classList.add("is-fresh");
      }
      const speakBtn = row.querySelector(".reply-speak");
      if (speakBtn) speakBtn.hidden = !voice.tts;
      // Time labels are cached per day: "today"/"yesterday" only change at midnight.
      const at = bubble.dataset.createdAt || "";
      const timeEl = row.querySelector(".reply-time");
      if (timeEl && (timeEl.dataset.at !== at || timeEl.dataset.day !== today)) {
        timeEl.dataset.at = at;
        timeEl.dataset.day = today;
        const label = at ? replyTimeLabel(at, opts) : "";
        timeEl.textContent = label;
        timeEl.hidden = !label;
        if (label) {
          timeEl.dateTime = String(at);
          timeEl.title = replyTimeTitle(at, opts);
        } else {
          timeEl.removeAttribute("datetime");
          timeEl.removeAttribute("title");
        }
      }
    }
    for (const row of logEl.querySelectorAll(".reply-actions")) {
      if (!keep.has(row)) row.remove();
    }
    if (speakTarget && !keep.has(replyRowOf(speakTarget))) speakTarget = null;
    syncReplySpeakUi();
  }

  function syncReplySpeakUi() {
    const live = speechLive();
    for (const btn of logEl.querySelectorAll(".reply-actions .reply-speak")) {
      const row = btn.closest(".reply-actions");
      const mine = Boolean(speakTarget && live && replyRowOf(speakTarget) === row);
      if (btn.classList.contains("speaking") === mine && btn.dataset.ready) continue;
      btn.dataset.ready = "1";
      btn.classList.toggle("speaking", mine);
      btn.setAttribute("aria-pressed", mine ? "true" : "false");
      btn.querySelector("ha-icon")?.setAttribute("icon", mine ? "mdi:stop" : "mdi:volume-high");
      setActionLabel(btn, t(mine ? "stop_reading" : "speak_reply"));
    }
  }

  function replyBubbleOfRow(row) {
    const host = row?.parentElement;
    if (!host) return null;
    return host.classList.contains("bubble") ? host : host.querySelector(":scope > .bubble");
  }

  function replyTextOf(bubble) {
    const md = bubble?.querySelector("ha-markdown.text");
    return String(md?.content || md?.textContent || "").trim();
  }

  async function onReplyAction(event) {
    const btn = event.target?.closest?.(".reply-actions .reply-action");
    if (!btn || !logEl.contains(btn) || btn.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    const bubble = replyBubbleOfRow(btn.closest(".reply-actions"));
    const text = replyTextOf(bubble);
    if (!bubble || !text) return;
    if (btn.dataset.action === "copy") {
      await copyText(text);
      const icon = btn.querySelector("ha-icon");
      icon?.setAttribute("icon", "mdi:check");
      setActionLabel(btn, t("copied"));
      window.clearTimeout(btn._copiedTimer);
      btn._copiedTimer = window.setTimeout(() => {
        icon?.setAttribute("icon", "mdi:content-copy");
        setActionLabel(btn, t("copy_reply"));
      }, 1600);
      return;
    }
    if (btn.dataset.action === "speak") {
      // Same reply playing: stop. Another reply: stop that one and read this one.
      if (speakTarget === bubble && speechLive()) {
        haltSpeech();
        return;
      }
      await speakReply(text, true, bubble);
    }
  }

  let replyRowsQueued = false;

  function stampReply(bubble) {
    if (bubble && !bubble.dataset.createdAt) bubble.dataset.createdAt = new Date().toISOString();
    // Finished live in this view: its row fades in once the turn is over (see syncReplyRows).
    if (bubble) bubble._replyFresh = true;
    // The reply is finished: its own action row appears (once per frame, however many finish).
    if (replyRowsQueued) return;
    replyRowsQueued = true;
    requestAnimationFrame(() => {
      replyRowsQueued = false;
      syncCopyChat();
    });
  }

  function replyTimeOptions() {
    const hass = hassObj();
    return {
      locale: hassLanguage(),
      timeZone: haTimeZone(hass),
      hour12: haHour12(hass?.locale?.time_format),
      yesterday: t("reply_yesterday"),
    };
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

  function speechLive() {
    return Boolean(
      speakStarted ||
        speakBusy ||
        speakPending.length > 0 ||
        speakInflight.length > 0 ||
        (replyObjectUrl && replyAudio && !replyAudio.ended),
    );
  }

  // Rollback/history button for the latest turn. It sits in the newest reply's own action
  // row (copy, read aloud, history ... time), as it did before replies got their own rows;
  // only without such a row (e.g. the turn ended without reply text) it falls back to the
  // chat-level row at the end of the log.
  let historyBtn = null;

  function historyButton() {
    if (historyBtn) return historyBtn;
    historyBtn = document.createElement("ha-icon-button");
    historyBtn.className = "history-chat";
    historyBtn.type = "button";
    historyBtn.label = t("activity");
    historyBtn.setAttribute("aria-label", t("activity"));
    const historyIcon = document.createElement("ha-icon");
    historyIcon.setAttribute("icon", "mdi:history");
    historyBtn.appendChild(historyIcon);
    historyBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await openHistory();
    });
    return historyBtn;
  }

  function syncCopyChat() {
    let row = logEl.querySelector(".chat-actions");
    syncReplyRows(replyEntries());
    // Copy, read aloud and the time live in each reply's own row. The bottom row keeps the
    // chat-level actions, plus a speaker while a reply is read on its own (auto read-aloud),
    // so that reading can still be paused or stopped.
    const showSpeak = Boolean(voice.tts && speechLive() && !speakTarget);
    const showHistory = Boolean(turnHasHistory);
    const lastRow = logEl.querySelector(".reply-actions.is-last");
    if (showHistory) {
      const btn = historyButton();
      btn.hidden = false;
      if (lastRow) {
        const timeEl = lastRow.querySelector(":scope > .reply-time");
        if (btn.parentElement !== lastRow || btn.nextElementSibling !== timeEl) {
          lastRow.insertBefore(btn, timeEl);
        }
      }
    } else if (historyBtn) {
      historyBtn.hidden = true;
    }
    const historyInRow = Boolean(showHistory && lastRow);
    if (!showSpeak && !(showHistory && !historyInRow)) {
      if (row) row.hidden = true;
      return;
    }
    if (!row) {
      row = document.createElement("div");
      row.className = "chat-actions";
    }
    let speakBtn = row.querySelector(".speak-chat");
    if (voice.tts) {
      if (!speakBtn) {
        speakBtn = document.createElement("ha-icon-button");
        speakBtn.className = "speak-chat";
        speakBtn.type = "button";
        speakBtn.label = t("speak_reply");
        const speakIcon = document.createElement("ha-icon");
        speakIcon.setAttribute("icon", "mdi:volume-high");
        speakBtn.appendChild(speakIcon);
        speakBtn.addEventListener("click", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          await toggleSpeak();
        });
        row.prepend(speakBtn);
      }
      speakBtn.hidden = !showSpeak;
    } else if (speakBtn) {
      speakBtn.hidden = true;
    }
    if (showHistory && !historyInRow && historyBtn.parentElement !== row) row.appendChild(historyBtn);
    row.hidden = false;
    if (logEl.lastElementChild !== row) logEl.appendChild(row);
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

  function fireMoreInfo(entityId) {
    const hassEl = document.querySelector("home-assistant");
    if (!hassEl) return false;
    hassEl.dispatchEvent(
      new CustomEvent("hass-more-info", {
        bubbles: true,
        composed: true,
        detail: { entityId },
      }),
    );
    return true;
  }

  function closeOverlayChat() {
    haltSpeech();
    overlayDrawer()?.classList.remove("open");
  }

  function openHaPath(path) {
    const entityId = entityIdFromHaPath(path);
    if (entityId && fireMoreInfo(entityId)) {
      if (compact) closeOverlayChat();
      return;
    }
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
    return distanceFromBottom() < 72;
  }

  function syncHeaderShadow() {
    headerEl?.classList.toggle("scrolled", chatEl.scrollTop > 0);
  }

  function clipToBottom() {
    holdFollow = false;
    pinBottom = true;
  }

  let scrollLock = 0;

  function followMax() {
    return Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
  }

  function writeScrollTop(value) {
    if (holdFollow || !pinBottom) return;
    const next = Math.max(0, Math.min(followMax(), value));
    if (Math.abs(chatEl.scrollTop - next) < 0.5) return;
    scrollLock += 1;
    chatEl.scrollTop = next;
    lastScrollTop = chatEl.scrollTop;
    requestAnimationFrame(() => {
      scrollLock = Math.max(0, scrollLock - 1);
    });
  }

  // Phones scroll the chat to reveal the caret on every key. The prompt is sticky inside the
  // chat, so the caret never moves and the chat creeps toward the bottom key by key.
  function typingGuard() {
    return !keepComposerFocus() && composerFocused() && performance.now() - typingAt < 600 && !isUserScroll();
  }

  function restoreTypingScroll() {
    scrollLock += 1;
    chatEl.scrollTop = acceptedTop;
    lastScrollTop = chatEl.scrollTop;
    requestAnimationFrame(() => {
      scrollLock = Math.max(0, scrollLock - 1);
    });
  }

  function markUserScroll() {
    userScrollAt = performance.now();
  }

  function isUserScroll() {
    return performance.now() - userScrollAt < 500;
  }

  function releaseFollow() {
    holdFollow = true;
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
    if (holdFollow || !pinBottom) {
      syncScrollBottomBtn();
      return;
    }
    writeScrollTop(followMax());
    lastScrollTop = chatEl.scrollTop;
    syncScrollBottomBtn();
  }

  function jumpToBottom() {
    typingAt = 0;
    clipToBottom();
    jumping = true;
    syncScrollBottomBtn();
    const max = followMax();
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
  let streamPainted = "";
  let streamDrainRaf = 0;
  let streamDrainLast = 0;
  let streamWaiters = [];
  let streamToken = 0;
  let streamAbort = null;
  let streamFinal = false;

  function turnLabel(turn) {
    const names = (turn.attachments || []).map((item) => item.name).filter(Boolean);
    return [turn.text, names.join(", ")].filter(Boolean).join(" · ");
  }

  function dropQueued(index) {
    nextTurns.splice(index, 1);
    renderNext();
    resizeComposer();
    if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
  }

  function renderNext() {
    if (!nextRow) return;
    if (!nextTurns.length) {
      nextRow.hidden = true;
      nextRow.replaceChildren();
      return;
    }
    if (haUi) {
      const set = composerCreate("ha-chip-set", "div");
      set.className = "next-chips";
      nextTurns.forEach((turn, index) => {
        const chip = composerCreate("ha-input-chip", "div");
        chip.className = "next-chip";
        const label = turnLabel(turn);
        const hint = index === 0 ? t("queued_hint") : t("queued_later");
        chip.title = hint;
        chip.setAttribute("title", hint);
        if (chip.localName === "ha-input-chip") {
          haChipLabel(chip, label);
          chip.removable = true;
          chip.addEventListener("remove", (event) => {
            event.preventDefault();
            event.stopPropagation();
            dropQueued(index);
          });
        } else {
          chip.append(queuedChipCopy(label, hint), queuedChipRemove(index));
        }
        set.append(chip);
      });
      nextRow.replaceChildren(set);
      bindHaTree(nextRow);
      nextRow.hidden = false;
      return;
    }
    nextRow.replaceChildren(
      ...nextTurns.map((turn, index) => {
        const chip = document.createElement("div");
        chip.className = "next-chip";
        const label = turnLabel(turn);
        const hint = index === 0 ? t("queued_hint") : t("queued_later");
        chip.append(queuedChipCopy(label, hint), queuedChipRemove(index));
        return chip;
      }),
    );
    nextRow.hidden = false;
  }

  function queuedChipCopy(label, hint) {
    const copy = document.createElement("p");
    copy.className = "next-copy";
    const text = document.createElement("span");
    text.className = "next-text";
    text.textContent = label;
    const hintEl = document.createElement("span");
    hintEl.className = "next-hint";
    hintEl.textContent = hint;
    copy.append(text, hintEl);
    return copy;
  }

  function queuedChipRemove(index) {
    const remove = document.createElement("ha-icon-button");
    remove.className = "next-remove";
    remove.type = "button";
    remove.label = t("queued_remove");
    remove.setAttribute("label", t("queued_remove"));
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", "mdi:close");
    remove.append(icon);
    remove.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropQueued(index);
    });
    return remove;
  }

  function queueTurn(text, attachments) {
    if (nextTurns.length >= MAX_QUEUE) {
      showNotice(t("queue_full"));
      return;
    }
    nextTurns.push({ text, attachments: attachments.slice() });
    pending = [];
    setComposerText("");
    dropDraft(sessionId);
    // Microphone only — TTS of the current reply keeps going.
    stopSpeech();
    renderThumbs();
    renderNext();
    resizeComposer();
    if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
  }

  function flushNext() {
    if (!nextTurns.length || streaming || sendQueued) return;
    sendQueued = nextTurns.shift();
    renderNext();
    form.requestSubmit();
  }

  function restoreQueued() {
    const pulled = pullQueuedDraft(nextTurns, { draftText: messageEl.value, pending });
    if (pulled.pulled) {
      setComposerText(pulled.text);
      pending = pulled.attachments;
    }
    renderThumbs();
    renderNext();
    resizeComposer();
  }

  // --- Drafts: what was typed (and attached) but not sent stays with its chat. ---

  function draftKey() {
    return draftStoreKey(userId());
  }

  function saveDraft() {
    window.clearTimeout(draftSaveTimer);
    draftSaveTimer = 0;
    if (draftOwner == null || !messageEl) return;
    const key = draftKey();
    // Without a known user nothing is stored; the draft still lives while the page is open.
    if (key) writeDraft(localStorage, key, draftOwner, messageEl.value);
    else if (messageEl.value.trim()) draftMemory.set(draftOwner, messageEl.value);
    else draftMemory.delete(draftOwner);
    if (pending.length) draftFiles.set(draftOwner, pending.slice());
    else draftFiles.delete(draftOwner);
  }

  function saveDraftSoon() {
    window.clearTimeout(draftSaveTimer);
    draftSaveTimer = window.setTimeout(saveDraft, 400);
  }

  function dropDraft(id) {
    const slot = draftSlot(id);
    clearDraft(localStorage, draftKey(), slot);
    draftMemory.delete(slot);
    draftFiles.delete(slot);
    paintRowDraft(id, false);
  }

  /** The composer now shows chat `id` (or the new chat): keep the old text, bring back the new one's. */
  function switchComposer(id) {
    const from = draftOwner;
    saveDraft();
    if (from && from !== NEW_CHAT_DRAFT) paintRowDraft(from, Boolean(messageEl?.value.trim() || draftFiles.has(from)));
    draftOwner = draftSlot(id);
    nextTurns = chatQueues.of(id);
    sendQueued = null;
    if (!messageEl) return;
    const key = draftKey();
    setComposerText(key ? readDraft(localStorage, key, draftOwner) : draftMemory.get(draftOwner) || "");
    pending = (draftFiles.get(draftOwner) || []).slice();
    paintRowDraft(id, false);
    renderThumbs();
    renderNext();
    resizeComposer();
    syncSendButton();
    const end = String(messageEl.value || "").length;
    try {
      messageEl.setSelectionRange?.(end, end);
    } catch (_err) {
      /* ha-textarea before it is upgraded */
    }
  }

  /** The new chat just got its id: its draft slot and queue move along. */
  function adoptNewChat(id) {
    chatQueues.rename("", id);
    nextTurns = chatQueues.of(id);
    if (draftOwner === NEW_CHAT_DRAFT) {
      clearDraft(localStorage, draftKey(), NEW_CHAT_DRAFT);
      draftMemory.delete(NEW_CHAT_DRAFT);
      const files = draftFiles.get(NEW_CHAT_DRAFT);
      draftFiles.delete(NEW_CHAT_DRAFT);
      if (files) draftFiles.set(id, files);
      draftOwner = draftSlot(id);
      if (messageEl?.value.trim()) saveDraft();
    }
  }

  // Read once per list paint, not once per row.
  let draftCache = null;
  function rowDrafts() {
    if (!draftCache) {
      draftCache = draftSlots(localStorage, draftKey());
      for (const slot of [...draftFiles.keys(), ...draftMemory.keys()]) draftCache.add(slot);
      queueMicrotask(() => {
        draftCache = null;
      });
    }
    return draftCache;
  }

  function paintRowDraft(id, on) {
    if (!id || id === NEW_CHAT_DRAFT) return;
    const row = sessionsEl?.querySelector(`.session-row[data-session-id="${id}"]`);
    const label = row?.querySelector(".item-text");
    if (!label) return;
    let mark = row.querySelector(".draft-mark");
    if (!on) {
      mark?.remove();
      return;
    }
    if (mark) return;
    mark = document.createElement("span");
    mark.className = "draft-mark";
    mark.textContent = t("draft");
    label.after(mark);
  }

  // --- Queued prompts of a chat that is not open: they still go out in their own chat. ---

  async function backgroundStatus(id) {
    const response = await apiFetch(`${API}/sessions`, {}, { timeout: LOAD_TIMEOUT_MS });
    if (!response?.ok) return "pending";
    const rows = await response.json().catch(() => null);
    if (!Array.isArray(rows)) return "pending";
    const row = rows.find((item) => item?.id === id);
    if (!row) return "gone";
    return row.pending ? "pending" : "idle";
  }

  async function backgroundSend(id, turn) {
    const attachments = turn.attachments || [];
    const images = attachments.filter((item) => item.kind === "image");
    const files = attachments.filter((item) => item.kind === "file");
    let response;
    try {
      // No agent or model: the chat keeps its own (the picker shows the open chat's).
      response = await apiFetch(
        `${API}/sessions/${id}/chat`,
        {
          method: "POST",
          body: JSON.stringify({
            message: turn.text,
            origin: window.location.origin,
            language: speechLanguage(),
            images: images.map((img) => ({ name: img.name, mime: img.mime, data: img.data })),
            files: files.map((file) => ({ name: file.name, mime: file.mime, text: file.text })),
          }),
        },
        { raise: true },
      );
    } catch (_err) {
      return "error";
    }
    if (response?.status === 409) return "busy";
    if (response?.status === 404) return "gone";
    if (!response?.ok || !response.body) return "error";
    try {
      // The reply runs on the server either way; reading it to the end tells us when it is done.
      await readSSE(response, (name, data) => {
        if (destroyed) return;
        if (name === "title" && data.title) applySessionTitle(id, data.title);
      });
    } catch (_err) {
      /* connection dropped: the server finishes the reply, the next send waits for it */
    }
    return "ok";
  }

  /** Leaving chat `id` with prompts still queued: send them there once its reply is done. */
  function sendQueueInBackground(id) {
    if (!id || !chatQueues.has(id) || backgroundRuns.has(id)) return;
    const run = drainQueue(id, chatQueues, {
      isActive: (chat) => !destroyed && chat === sessionId,
      status: backgroundStatus,
      send: backgroundSend,
      wait: (ms) => new Promise((resolve) => window.setTimeout(resolve, ms)),
      onSent: (chat) => {
        if (!destroyed) bumpSession(chat);
      },
    })
      .catch(() => "error")
      .then((reason) => {
        backgroundRuns.delete(id);
        if (destroyed) return reason;
        // The reply's unread dot comes with the list.
        refreshSessions();
        if (id === sessionId) resumeQueue(id);
        return reason;
      });
    backgroundRuns.set(id, run);
  }

  /** The open chat has queued prompts: send the next one once nothing runs there any more. */
  function resumeQueue(id) {
    if (!id || id !== sessionId || streaming || liveStream || sendQueued || !nextTurns.length) return;
    if (backgroundRuns.has(id)) {
      // It stops on its own now that the chat is open and then calls back here.
      // Until then the reply it sent is followed live.
      watchPending(id);
      return;
    }
    watchPending(id).then((found) => {
      if (found && id === sessionId && !streaming) flushNext();
    });
  }

  /** Before the screen shows another chat: the old chat keeps its draft and its queue. */
  function leaveChat() {
    const from = sessionId;
    if (sendQueued) {
      // Picked for sending but not out yet: it goes back to its own chat.
      chatQueues.of(from).unshift(sendQueued);
      sendQueued = null;
    }
    leaveChatStream();
    // After the caller has switched sessionId, so the old chat no longer counts as open.
    if (from) window.setTimeout(() => sendQueueInBackground(from), 0);
    // A new chat that never got an id has nowhere to send them.
    else chatQueues.drop("");
  }

  function haltStream({ keepQueue = true, keepSpeech = false } = {}) {
    streamToken += 1;
    watchGen += 1;
    if (streamAbort) {
      streamAbort.abort();
      streamAbort = null;
    }
    if (streamDrainRaf) {
      cancelAnimationFrame(streamDrainRaf);
      streamDrainRaf = 0;
    }
    streamFinal = true;
    revealAllNow();
    streamBuf = "";
    streamFull = "";
    streamPainted = "";
    streamNode = null;
    streamFinal = false;
    if (keepSpeech) resetSpeechTurn();
    else haltSpeech();
    const waiters = streamWaiters;
    streamWaiters = [];
    waiters.forEach((fn) => fn());
    streaming = false;
    liveStream = false;
    if (!keepQueue) {
      nextTurns.length = 0;
      sendQueued = null;
    }
    renderNext();
    const live = logEl.querySelector(".bubble.assistant.streaming");
    if (live) {
      live.classList.remove("streaming");
      stampReply(live);
      settleTools(live);
      setActivity(live, "");
      const text = String(live.querySelector(".text")?.content || live.querySelector(".text")?.textContent || "").trim();
      const tools = live.querySelector(".tools");
      if (!text && !tools?.children?.length) live.remove();
    }
    resizeComposer();
  }

  function abandonStream({ keepSpeech = false } = {}) {
    haltStream({ keepQueue: keepQueueOnHalt("send"), keepSpeech });
  }

  // Leaving a chat: its queued prompts were written for it and must not go out in the next one.
  // They stay on that chat's own list (see leaveChat) and never move into the composer.
  function leaveChatStream() {
    haltStream({ keepQueue: keepQueueOnHalt("switch") });
  }

  async function stopTurn() {
    if (turnStopDone) {
      await turnStopDone;
      return;
    }
    if (!streaming && !liveStream) return;
    const chatId = sessionId;
    turnStopping = true;
    // Stop cancels the queue too. The first queued prompt goes back into an empty composer,
    // so a typed prompt is not lost without a trace.
    restoreQueued();
    haltStream({ keepQueue: keepQueueOnHalt("stop") });
    const done = (async () => {
      if (!chatId) return;
      try {
        await apiFetch(`${API}/sessions/${chatId}/stop`, { method: "POST" });
      } catch (_err) {
        /* lock is released when the job ends */
      }
    })();
    turnStopDone = done;
    try {
      await done;
    } finally {
      turnStopping = false;
      if (turnStopDone === done) turnStopDone = null;
    }
    syncCopyChat();
    resizeComposer();
  }

  function hasDraft() {
    return Boolean(String(messageEl?.value || "").trim() || pending.length);
  }

  function canStopTurn() {
    return (streaming || liveStream || turnStopping) && !hasDraft();
  }

  function syncSendButton() {
    const halt = canStopTurn();
    const label = t(halt ? "stop_reply" : "send");
    const icon = halt ? "mdi:stop" : haUi ? "mdi:send" : "mdi:arrow-up";
    for (const btn of composerControls(".send")) {
      btn.disabled = halt ? false : !hasDraft();
      btn.classList.toggle("is-stop", halt);
      btn.label = label;
      btn.setAttribute("aria-label", label);
      btn.setAttribute("label", label);
      const glyph = btn.querySelector("ha-icon");
      if (glyph) glyph.setAttribute("icon", icon);
    }
  }

  function writeStreamVisible(force = false) {
    if (!streamNode) return false;
    const done = streamFinal && !streamBuf;
    const visible = rewriteAssistantLinks(stableStreamMarkdown(streamFull, done), done);
    if (visible === streamPainted) return false;
    streamPainted = visible;
    setMarkdown(streamNode, visible);
    streamNode.hidden = !visible;
    styleMarkdownTables(streamNode);
    const bubble = streamNode.closest(".bubble");
    bubble?.classList.toggle("has-text", Boolean(visible));
    if (visible && bubble) {
      noteTextPainted(bubble);
      setActivity(bubble, "");
    }
    if (bubble) retargetHaLinks(bubble);
    return true;
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
    writeStreamVisible(!streamBuf);
    easeToBottom(dt);
    if (streamBuf) {
      streamDrainRaf = requestAnimationFrame(pumpStream);
      return;
    }
    followBottom();
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
    writeStreamVisible(true);
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

  function easeToBottom(dt) {
    if (holdFollow || !pinBottom || keyboardOpen) return false;
    if (reduceMotion) {
      stickToBottom();
      return false;
    }
    const max = followMax();
    const dist = max - chatEl.scrollTop;
    if (dist <= 0.5) {
      if (dist > 0) writeScrollTop(max);
      return false;
    }
    const eased = dist * (1 - Math.exp(-dt * 5.5));
    const step = Math.min(dist, Math.max(eased, 48 * dt), 720 * dt);
    writeScrollTop(chatEl.scrollTop + step);
    return true;
  }

  function followBottom() {
    if (holdFollow || !pinBottom || followRaf || streamDrainRaf || keyboardOpen) return;
    followLast = 0;
    const tick = (now) => {
      if (!followLast) followLast = now;
      const dt = Math.min(0.033, (now - followLast) / 1000);
      followLast = now;
      if (easeToBottom(dt)) {
        followRaf = requestAnimationFrame(tick);
        return;
      }
      followRaf = 0;
      syncScrollBottomBtn();
    };
    followRaf = requestAnimationFrame(tick);
  }

  function scrollChatToBottom() {
    followBottom();
  }

  // The open chat was deleted (another device or tab). Keep its messages on screen, say so,
  // and make the next message start a new chat.
  function chatGone(restore = null) {
    if (!sessionId) return;
    watchGen += 1;
    const goneId = sessionId;
    chatQueues.drop(goneId);
    // What was typed stays on screen and now belongs to the new chat.
    dropDraft(goneId);
    draftOwner = NEW_CHAT_DRAFT;
    nextTurns = chatQueues.of("");
    renderNext();
    sessionId = "";
    freshChat = true;
    goToSession("", true);
    selectSessionRow("");
    titleEl.textContent = t("new_chat");
    logEl.querySelector(".chat-gone")?.remove();
    const note = document.createElement("p");
    note.classList.add("chat-gone");
    const restored = Boolean(restore?.text || restore?.pending?.length);
    note.textContent = t(restored ? "chat_deleted_resend" : "chat_deleted");
    logEl.appendChild(note);
    if (restored && !String(messageEl.value || "").trim() && !pending.length) {
      setComposerText(restore.text || "");
      pending = restore.pending || [];
      renderThumbs();
    }
    resizeComposer();
    stickToBottom();
    if (!compact) loadSessions();
  }

  function showEmpty() {
    setWelcome(true);
    turnHasHistory = false;
    logEl.replaceChildren();
    const note = document.createElement("p");
    note.className = "empty";
    note.textContent = t("empty");
    logEl.appendChild(note);
  }

  let defaultProvider = "api";
  // Agent and model of the open chat; "" means new chat: default agent, the agent's own model.
  let chatAgent = "";
  let chatModel = "";
  let defaultAgentId = "";
  let modelSwitcher = false;
  let providerItems = [];
  const modelLists = new Map();
  let voice = { dictate: true, stt: "browser", speak: false, tts: false, ttsHeavy: false, ttsNatural: true };
  let turnHasHistory = false;

  function knownAgent(id) {
    return Boolean(id) && providerItems.some((item) => item.id === id);
  }

  function selectedAgent() {
    if (knownAgent(chatAgent)) return chatAgent;
    if (!providerItems.length) return chatAgent || defaultProvider;
    const last = localStorage.getItem("ai_workspace_agent") || "";
    const pick = pickAgent(providerItems, knownAgent(defaultAgentId) ? defaultAgentId : last);
    return pick?.id || defaultProvider;
  }

  function agentText(item) {
    if (!item) return "";
    if (item.kind === "assist") return item.label;
    const title = item.title || item.label;
    return modelSwitcher || !item.model ? title : `${title} / ${item.model}`;
  }

  function setChatChoice(agent, model) {
    chatAgent = agent || "";
    chatModel = model || "";
    renderAgentPicker();
  }

  function saveChatChoice(body) {
    if (!sessionId || freshChat) return;
    apiFetch(`${API}/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(body) });
  }

  function renderAgentPicker() {
    const current = selectedAgent();
    const item = providerItems.find((row) => row.id === current);
    // Checks chatUsageShown first: safe before the header's usage line exists.
    rerenderChatUsage();
    if (!agentPicker || !agentMenu || !agentLabel) return;
    const ready = agentChoices(providerItems);
    const models = modelSwitcher && item && item.kind !== "assist";
    agentPicker.hidden = ready.length < 2 && !models;
    agentMenu.hidden = ready.length < 2 && !models;
    agentLabel.textContent = agentText(item);
    agentMenu.querySelectorAll("ha-dropdown-item").forEach((node) => node.remove());
    for (const row of providerItems) {
      const option = document.createElement("ha-dropdown-item");
      option.value = row.id;
      option.disabled = !row.available;
      option.selected = row.id === current;
      if (!row.available) option.setAttribute("disabled", "");
      if (row.id === current) option.setAttribute("selected", "");
      option.textContent = agentText(row);
      agentMenu.appendChild(option);
    }
    renderModelPicker();
  }

  function agentModels(id) {
    let list = modelLists.get(id);
    if (!list) {
      list = apiFetch(`${API}/models?agent_id=${encodeURIComponent(id)}`)
        .then((response) => (response?.ok ? response.json() : null))
        .catch(() => null);
      modelLists.set(id, list);
      list.then((body) => {
        if (!body?.models?.length) modelLists.delete(id);
      });
    }
    return list;
  }

  async function renderModelPicker() {
    if (!modelMenu || !modelLabel) return;
    const id = selectedAgent();
    const item = providerItems.find((row) => row.id === id);
    const show = modelSwitcher && item && item.kind !== "assist";
    modelMenu.hidden = !show;
    if (!show) return;
    modelLabel.textContent = chatModel || item.model || "";
    const body = await agentModels(id);
    if (id !== selectedAgent()) return;
    const current = chatModel || body?.default || item.model || "";
    const names = [...(body?.models || [])];
    if (current && !names.includes(current)) names.unshift(current);
    modelLabel.textContent = current;
    modelMenu.querySelectorAll("ha-dropdown-item").forEach((node) => node.remove());
    for (const name of names) {
      const option = document.createElement("ha-dropdown-item");
      option.value = name;
      option.selected = name === current;
      if (name === current) option.setAttribute("selected", "");
      option.textContent = name;
      modelMenu.appendChild(option);
    }
  }

  function agentChoices(items) {
    return items.filter((item) => item.available);
  }

  function pickAgent(items, previous) {
    const ours = items.filter((item) => item.kind !== "assist");
    const assist = items.filter((item) => item.kind === "assist");
    const readyOurs = ours.filter((item) => item.available);
    const readyAssist = assist.filter((item) => item.available);
    return (
      items.find((item) => item.id === previous) ||
      readyOurs[0] ||
      ours[0] ||
      readyAssist[0] ||
      items[0]
    );
  }

  let providerRetry = 0;
  let sessionsLoad = 0;
  let searchTimer = 0;
  const MIN_CHATS_FOR_SEARCH = 2;

  async function loadProviders() {
    const response = await apiFetch(`${API}/providers`);
    if (!response?.ok) return;
    const items = await response.json();
    const ready = agentChoices(items);
    providerItems = items;
    modelLists.clear();
    renderAgentPicker();
    const chosen = items.find((item) => item.id === selectedAgent()) || ready[0] || items[0];
    if (chosen?.id) defaultProvider = chosen.id;
    if (chosen && !chosen.available) {
      setHint("");
      clearMicHelp();
      bannerEl.hidden = false;
      bannerEl.textContent = chosen.reason || t("configure_provider");
      if (providerRetry < 8) {
        providerRetry += 1;
        window.setTimeout(() => {
          if (bannerEl && !bannerEl.hidden) loadProviders();
        }, Math.min(2000 * providerRetry, 15000));
      }
    } else if ((chosen?.notice_key || chosen?.notice) && bannerEl && !bannerEl.classList.contains("mic-help")) {
      providerRetry = 0;
      const noticeParams = { ...(chosen.notice_params || {}) };
      if (chosen.notice_key === "outdated_runtime" && !noticeParams.have) {
        noticeParams.have = t("outdated_runtime_unknown");
      }
      const noticeText = chosen.notice_key ? t(chosen.notice_key, noticeParams) : chosen.notice;
      if (compact) {
        setBanner(noticeText);
      } else {
        setHint(noticeText);
      }
    } else if (bannerEl && !bannerEl.classList.contains("hold") && !bannerEl.classList.contains("mic-help")) {
      setHint("");
      providerRetry = 0;
      bannerEl.hidden = true;
      bannerEl.textContent = "";
    }
  }

  function closeSessionMenu() {
    root.querySelectorAll("ha-dropdown.session-menu").forEach((menu) => {
      menu.open = false;
    });
    root.querySelectorAll(".session-more[aria-expanded='true']").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });
  }

  function bindSessionMenu(row, session, more) {
    if (row.querySelector("ha-dropdown.session-menu")) return;
    const menu = document.createElement("ha-dropdown");
    menu.className = "session-menu";
    menu.placement = "bottom-end";
    more.slot = "trigger";
    menu.addEventListener("click", (event) => event.stopPropagation());
    menu.addEventListener("keydown", (event) => event.stopPropagation());
    menu.addEventListener("wa-show", () => more.setAttribute("aria-expanded", "true"));
    menu.addEventListener("wa-hide", () => more.setAttribute("aria-expanded", "false"));
    menu.addEventListener("wa-select", (event) => {
      const value = event.detail?.item?.value;
      if (value === "pin") pinSession(session);
      else if (value === "rename") renameSession(session);
      else if (value === "delete") deleteSession(session);
    });
    menu.append(
      more,
      sessionAction(session.pinned ? t("unpin") : t("pin"), "pin"),
      sessionAction(t("rename"), "rename"),
      sessionAction(t("delete"), "delete", "danger"),
    );
    const host = row.querySelector(".session-menu");
    if (host && host.localName !== "ha-dropdown") host.replaceWith(menu);
    else more.replaceWith(menu);
  }

  function sessionAction(label, value, variant) {
    const item = document.createElement("ha-dropdown-item");
    item.value = value;
    if (variant) item.variant = variant;
    item.textContent = label;
    return item;
  }

  function openDialog(dialog) {
    root.appendChild(dialog);
    customElements.whenDefined("ha-dialog").then(() => {
      dialog.open = true;
    });
  }

  function askText(title, value) {
    return new Promise((resolve) => {
      const dialog = document.createElement("ha-dialog");
      dialog.setAttribute("header-title", title);
      dialog.setAttribute("width", "small");
      const input = document.createElement("input");
      input.className = "dialog-field";
      input.type = "text";
      input.value = value || "";
      input.maxLength = 80;
      const footer = document.createElement("ha-dialog-footer");
      footer.slot = "footer";
      const cancel = document.createElement("ha-button");
      cancel.setAttribute("appearance", "plain");
      cancel.slot = "secondaryAction";
      cancel.textContent = t("cancel");
      const save = document.createElement("ha-button");
      save.setAttribute("variant", "brand");
      save.slot = "primaryAction";
      save.textContent = t("save");
      footer.append(cancel, save);
      dialog.append(input, footer);
      let result = null;
      const finish = (next) => {
        result = next;
        dialog.open = false;
      };
      cancel.addEventListener("click", () => finish(null));
      save.addEventListener("click", () => finish(input.value));
      input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        finish(input.value);
      });
      dialog.addEventListener("opened", () => {
        input.focus();
        input.select();
      }, { once: true });
      dialog.addEventListener("closed", () => {
        dialog.remove();
        resolve(result);
      });
      openDialog(dialog);
    });
  }

  function askConfirm(title, body, confirmLabel) {
    return new Promise((resolve) => {
      const dialog = document.createElement("ha-dialog");
      dialog.setAttribute("header-title", title);
      dialog.setAttribute("width", "small");
      dialog.setAttribute("type", "alert");
      const copy = document.createElement("p");
      copy.className = "dialog-copy";
      copy.textContent = body;
      const footer = document.createElement("ha-dialog-footer");
      footer.slot = "footer";
      const cancel = document.createElement("ha-button");
      cancel.setAttribute("appearance", "plain");
      cancel.slot = "secondaryAction";
      cancel.textContent = t("cancel");
      const ok = document.createElement("ha-button");
      ok.setAttribute("variant", "danger");
      ok.slot = "primaryAction";
      ok.textContent = confirmLabel;
      footer.append(cancel, ok);
      dialog.append(copy, footer);
      let confirmed = false;
      cancel.addEventListener("click", () => {
        dialog.open = false;
      });
      ok.addEventListener("click", () => {
        confirmed = true;
        dialog.open = false;
      });
      dialog.addEventListener("closed", () => {
        dialog.remove();
        resolve(confirmed);
      });
      openDialog(dialog);
    });
  }

  function askAlert(title, body) {
    return new Promise((resolve) => {
      const dialog = document.createElement("ha-dialog");
      dialog.setAttribute("header-title", title);
      dialog.setAttribute("width", "small");
      dialog.setAttribute("type", "alert");
      const copy = document.createElement("p");
      copy.className = "dialog-copy";
      copy.textContent = body;
      const footer = document.createElement("ha-dialog-footer");
      footer.slot = "footer";
      const ok = document.createElement("ha-button");
      ok.slot = "primaryAction";
      ok.textContent = t("close");
      footer.append(ok);
      dialog.append(copy, footer);
      ok.addEventListener("click", () => {
        dialog.open = false;
      });
      dialog.addEventListener("closed", () => {
        dialog.remove();
        resolve();
      });
      openDialog(dialog);
    });
  }

  async function pinSession(session) {
    const pinned = !session.pinned;
    const response = await apiFetch(`${API}/sessions/${session.id}`, {
      method: "PATCH",
      body: JSON.stringify({ pinned }),
    });
    if (!response?.ok) {
      showNotice(await errorText(response));
      return;
    }
    loadSessions();
  }

  async function renameSession(session) {
    session = listedSession(session);
    const next = await askText(t("rename_prompt"), displayTitle(session.title));
    if (next == null) return;
    const title = next.trim().replace(/\s+/g, " ").slice(0, 80);
    if (!title || title === session.title) return;
    const response = await apiFetch(`${API}/sessions/${session.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    if (!response?.ok) {
      showNotice(await errorText(response));
      return;
    }
    if (session.id === sessionId) titleEl.textContent = title;
    await loadSessions();
  }

  async function deleteSession(session) {
    session = listedSession(session);
    const ok = await askConfirm(
      t("delete"),
      t("delete_confirm", { title: displayTitle(session.title) }),
      t("delete"),
    );
    if (!ok) return;
    const response = await apiFetch(`${API}/sessions/${session.id}`, { method: "DELETE" });
    if (!response || (!response.ok && response.status !== 204)) {
      showNotice(await errorText(response));
      return;
    }
    clearChatCache(localStorage, chatCacheSlot(), { id: session.id });
    if (session.id === sessionId) startNewChat();
    chatQueues.drop(session.id);
    dropDraft(session.id);
    await loadSessions();
  }

  function displayTitle(title) {
    return headerTitle(title, t("new_chat"));
  }

  /** The header still says "New chat" while the server may already have the title: ask it. */
  async function syncHeaderTitle(id) {
    if (!id || sessionId !== id || !isPlaceholderTitle(titleEl.textContent, t("new_chat"))) return;
    let session = null;
    try {
      const response = await apiFetch(`${API}/sessions/${id}`, {}, { timeout: LOAD_TIMEOUT_MS });
      if (response?.ok) session = await response.json();
    } catch (_error) {
      return;
    }
    const title = realTitle(session?.title, t("new_chat"));
    if (title) applySessionTitle(id, title);
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

  function listedSession(session) {
    const row = sessionsEl?.querySelector(`.session-row[data-session-id="${session.id}"]`);
    if (!row) return session;
    const title = row.dataset.title || session.title;
    const pinned = row.dataset.pinned === "1";
    if (title === session.title && pinned === Boolean(session.pinned)) return session;
    return { ...session, title, pinned };
  }

  function applySessionTitle(id, title) {
    if (!id || !title) return;
    const labelText = displayTitle(title);
    if (sessionId === id) titleEl.textContent = labelText;
    const row = sessionsEl?.querySelector(`.session-row[data-session-id="${id}"]`);
    if (row) row.dataset.title = title;
    const label = row?.querySelector(".item-text");
    if (label) label.textContent = labelText;
  }

  function markSessionSelected(node, on) {
    if (!node) return;
    node.classList.toggle("selected", on);
    if (node.localName === "ha-list-item-button") {
      if (on) node.setAttribute("selected", "");
      else node.removeAttribute("selected");
    }
  }

  function selectSessionRow(id) {
    if (!sessionsEl) return;
    sessionsEl.querySelectorAll(".session-row.selected, .session.selected").forEach((node) => {
      markSessionSelected(node, false);
    });
    const row = sessionsEl.querySelector(`.session-row[data-session-id="${id}"]`);
    if (!row) return;
    markSessionSelected(row, true);
    markSessionSelected(row.querySelector(".session"), true);
  }

  function bumpSession(id, title, pinned) {
    if (!sessionsEl || !id || compact) return;
    let row = sessionsEl.querySelector(`.session-row[data-session-id="${id}"]`);
    const stayPinned = pinned === undefined ? row?.dataset.pinned === "1" : Boolean(pinned);
    if (!row) {
      row = sessionRow({ id, title: title || "", pinned: stayPinned });
    } else if (title) {
      applySessionTitle(id, title);
    }
    row.dataset.pinned = stayPinned ? "1" : "0";
    sessionsEl.querySelector(".sessions-empty")?.remove();
    const labels = [...sessionsEl.querySelectorAll(".chats-label")];
    const anchor = stayPinned ? labels[0] : labels[labels.length - 1];
    if (anchor) anchor.after(row);
    else sessionsEl.prepend(row);
    selectSessionRow(sessionId);
    syncSearchIcon();
  }

  // Unread agent replies: a dot on the chat's row and on the buttons that open the chat list.
  const readSent = new Map();

  function paintRowUnread(row, on) {
    if (!row) return;
    row.dataset.unread = on ? "1" : "0";
    const item = row.querySelector(".session");
    let dot = row.querySelector(".unread-dot");
    if (!on) {
      dot?.remove();
      return;
    }
    if (dot || !item) return;
    dot = document.createElement("span");
    dot.className = "unread-dot";
    dot.setAttribute("role", "img");
    dot.setAttribute("aria-label", t("unread_reply"));
    dot.title = t("unread_reply");
    const label = item.querySelector(".item-text");
    if (label) label.after(dot);
    else item.prepend(dot);
  }

  function setRowUnread(id, on) {
    const row = sessionsEl?.querySelector(`.session-row[data-session-id="${id}"]`);
    if (on && id === sessionId && chatVisible()) {
      // The open chat on this screen: the reply is being read right now.
      markRead(id);
      return;
    }
    paintRowUnread(row, on);
  }

  function syncUnreadBadge() {
    const rows = [...(sessionsEl?.querySelectorAll(".session-row[data-unread='1']") || [])];
    const unread = anyUnread(
      rows.map((row) => ({ id: row.dataset.sessionId, unread: true })),
      sessionId,
      chatVisible(),
    );
    root.querySelectorAll(".chat-nav-toggle").forEach((btn) => {
      let dot = btn.querySelector(".unread-dot");
      if (!unread) {
        dot?.remove();
        btn.removeAttribute("data-unread");
        return;
      }
      btn.setAttribute("data-unread", "1");
      if (!dot) {
        dot = document.createElement("span");
        dot.className = "unread-dot";
        dot.setAttribute("aria-hidden", "true");
        btn.appendChild(dot);
      }
    });
    options.onUnread?.(unread);
  }

  /** The open, visible chat was seen up to its newest message: on the server, so on every device. */
  function markRead(id, messages = null) {
    if (!id || id !== sessionId || !chatVisible()) return;
    const last = Array.isArray(messages) && messages.length ? messages[messages.length - 1]?.id : null;
    const row = sessionsEl?.querySelector(`.session-row[data-session-id="${id}"]`);
    const wasUnread = row?.dataset.unread === "1";
    paintRowUnread(row, false);
    syncUnreadBadge();
    const key = last == null ? `*${Date.now()}` : String(last);
    if (!wasUnread && readSent.get(id) === key) return;
    readSent.set(id, key);
    void apiFetch(`${API}/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ read: typeof last === "number" ? last : true }),
    });
  }

  // While a reply runs in the background the list is asked again soon; otherwise now and then,
  // so a reply finished on another device or in another chat gets its dot.
  let sessionsPoll = 0;
  const SESSIONS_POLL_BUSY_MS = 4000;
  const SESSIONS_POLL_IDLE_MS = 60000;

  function scheduleSessionsPoll(sessions) {
    window.clearTimeout(sessionsPoll);
    if (compact || !sessionsEl) return;
    const busy = (sessions || []).some((session) => session?.pending);
    sessionsPoll = window.setTimeout(refreshSessions, busy ? SESSIONS_POLL_BUSY_MS : SESSIONS_POLL_IDLE_MS);
  }
  teardown.push(() => window.clearTimeout(sessionsPoll));

  function listShape(sessions) {
    return sessions.map((session) => `${session.id}|${session.title || ""}|${session.pinned ? 1 : 0}`).join(",");
  }

  async function refreshSessions() {
    if (compact || !sessionsEl) return;
    if (document.visibilityState === "hidden" || searchInput?.value.trim()) {
      scheduleSessionsPoll(cachedSessions);
      return;
    }
    const response = await apiFetch(`${API}/sessions`, {}, { timeout: LOAD_TIMEOUT_MS });
    if (!response?.ok) {
      scheduleSessionsPoll([]);
      return;
    }
    const sessions = await response.json();
    if (searchInput?.value.trim()) return;
    const shown = [...sessionsEl.querySelectorAll(".session-row")].map((row) => ({
      id: row.dataset.sessionId,
      title: row.dataset.title,
      pinned: row.dataset.pinned === "1",
    }));
    cachedSessions = sessions;
    writeSessionCache(sessions);
    const menuOpen = sessionsEl.querySelector(".session-more[aria-expanded='true']");
    if (listShape(shown) !== listShape(sessions) && !menuOpen) paintSessionList(sessions);
    else for (const session of sessions) setRowUnread(session.id, Boolean(session.unread));
    syncUnreadBadge();
    scheduleSessionsPoll(sessions);
  }

  // Placeholder rows until the first list arrives; a busy system can take a few seconds.
  function sessionSkeleton() {
    const widths = [72, 58, 84, 64, 76, 52, 68];
    const rows = widths.map((w) => `<div class="session-skeleton" style="--w:${w}%"></div>`).join("");
    return `<div class="chats-label skeleton-label" aria-hidden="true"></div><div aria-hidden="true">${rows}</div>`;
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
    row.dataset.title = session.title || "";
    row.dataset.pinned = session.pinned ? "1" : "0";
    row.role = "listitem";
    if (session.id === sessionId) titleEl.textContent = displayTitle(session.title);
    const item = document.createElement("div");
    item.className = "session session-plain";
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.addEventListener("keydown", (event) => {
      if (event.target !== item || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      item.click();
    });
    const label = document.createElement("span");
    label.className = "item-text";
    label.textContent = displayTitle(session.title);
    item.appendChild(label);
    row.dataset.unread = "0";
    if (session.id !== sessionId && rowDrafts().has(session.id)) {
      const mark = document.createElement("span");
      mark.className = "draft-mark";
      mark.textContent = t("draft");
      label.after(mark);
    }
    const openHere = session.id === sessionId && chatVisible();
    if (session.unread && !openHere) paintRowUnread(row, true);
    if (session.id === sessionId) {
      markSessionSelected(item, true);
      markSessionSelected(row, true);
    }
    item.addEventListener("click", () => {
      closeSessionMenu();
      closeNavIfOverlay();
      openSession(session.id);
    });
    if (session.unread && openHere) queueMicrotask(() => markRead(session.id));
    const host = document.createElement("div");
    host.className = "session-menu";
    const more = document.createElement("ha-icon-button");
    more.className = "session-more";
    more.label = t("chat_actions");
    more.setAttribute("aria-haspopup", "menu");
    more.setAttribute("aria-expanded", "false");
    const dots = document.createElement("ha-icon");
    dots.setAttribute("icon", "mdi:dots-vertical");
    more.appendChild(dots);
    more.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const open = row.querySelector("ha-dropdown.session-menu");
      if (open) {
        open.open = !open.open;
        return;
      }
      bindSessionMenu(row, listedSession(session), more);
      const menu = row.querySelector("ha-dropdown.session-menu");
      customElements.whenDefined("ha-dropdown").then(() => {
        if (menu) menu.open = true;
      });
    });
    more.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      event.stopPropagation();
      more.click();
    });
    host.append(more);
    item.append(host);
    row.append(item);
    return row;
  }

  function paintSessionList(sessions, query = "") {
    if (!sessionsEl) return;
    const pinned = sessions.filter((session) => session.pinned);
    const rest = sessions.filter((session) => !session.pinned);
    const frag = document.createDocumentFragment();
    if (pinned.length) {
      frag.appendChild(sessionLabel(t("pinned")));
      for (const session of pinned) frag.appendChild(sessionRow(session));
    }
    if (rest.length || !query) {
      frag.appendChild(sessionLabel(t("chats")));
      for (const session of rest) frag.appendChild(sessionRow(session));
    }
    if (query && !sessions.length) {
      const empty = document.createElement("p");
      empty.className = "sessions-empty";
      empty.textContent = t("no_chats_found");
      frag.appendChild(empty);
    }
    sessionsEl.replaceChildren(frag);
    sessionsEl.removeAttribute("aria-busy");
    selectSessionRow(sessionId);
    syncSearchIcon();
  }

  async function loadSessions() {
    if (compact || !sessionsEl) return;
    closeSessionMenu();
    const query = searchInput?.value.trim() || "";
    if (!query && cachedSessions.length && sessionsEl.querySelector(".session-skeleton")) {
      paintSessionList(cachedSessions);
    }
    const mark = ++sessionsLoad;
    const response = await apiFetch(`${API}/sessions${query ? `?q=${encodeURIComponent(query)}` : ""}`);
    if (!response?.ok) {
      // Do not leave the placeholder rows up when the list cannot load.
      if (mark === sessionsLoad && sessionsEl.querySelector(".session-skeleton")) sessionsEl.replaceChildren();
      sessionsEl.removeAttribute("aria-busy");
      return;
    }
    const sessions = await response.json();
    // A slower answer for an older search must not replace a newer one.
    if (mark !== sessionsLoad) return;
    if (!query) {
      cachedSessions = sessions;
      writeSessionCache(sessions);
    }
    paintSessionList(sessions, query);
    syncUnreadBadge();
    scheduleSessionsPoll(sessions);
  }

  // Rows only count all chats while nothing filters them, and an active search keeps its way out.
  function syncSearchIcon() {
    if (!searchOpen || !searchBox || !searchInput) return;
    if (!searchBox.hidden || searchInput.value.trim()) return;
    searchOpen.hidden = sessionsEl.querySelectorAll(".session-row").length <= MIN_CHATS_FOR_SEARCH;
  }

  function setSearchOpen(open) {
    if (!searchBox || !searchInput) return;
    searchBox.hidden = !open;
    searchOpen?.setAttribute("aria-pressed", open ? "true" : "false");
    window.clearTimeout(searchTimer);
    if (open) {
      searchInput.focus({ preventScroll: true });
      return;
    }
    const filtered = Boolean(searchInput.value.trim());
    searchInput.value = "";
    if (filtered) loadSessions();
    else syncSearchIcon();
  }

  // The filter stays on: picking a result also takes focus from the box.
  function hideSearch() {
    searchBox.hidden = true;
    searchOpen?.setAttribute("aria-pressed", searchInput.value.trim() ? "true" : "false");
    syncSearchIcon();
  }

  // Keeps the box focused, so a click on the icon closes it instead of hiding and reopening it.
  searchOpen?.addEventListener("mousedown", (event) => event.preventDefault());
  searchOpen?.addEventListener("click", () => {
    if (wrap.classList.contains("nav-collapsed")) {
      toggleNav();
      setSearchOpen(true);
      return;
    }
    setSearchOpen(searchBox.hidden);
  });
  searchInput?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(loadSessions, 200);
  });
  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      window.clearTimeout(searchTimer);
      loadSessions();
      hideSearch();
      return;
    }
    if (event.key !== "Escape") return;
    event.stopPropagation();
    setSearchOpen(false);
  });
  searchInput?.addEventListener("blur", () => {
    // Switching tab or window is not leaving the search.
    if (!searchBox.hidden && document.hasFocus()) hideSearch();
  });

  async function createSession() {
    const mark = streamToken;
    const created = await apiFetch(`${API}/sessions`, {
      method: "POST",
      body: JSON.stringify({ provider: selectedAgent(), model: modelSwitcher ? chatModel : "" }),
    });
    if (!created?.ok) throw new Error(await errorText(created));
    const session = await created.json();
    if (mark !== streamToken) {
      apiFetch(`${API}/sessions/${session.id}`, { method: "DELETE" });
      return null;
    }
    sessionId = session.id;
    adoptNewChat(session.id);
    freshChat = false;
    chatAgent = session.provider || chatAgent;
    bumpSession(session.id, session.title, session.pinned);
    goToSession(sessionId, true);
    if (compact) localStorage.setItem("ai_workspace_session", sessionId);
    return session;
  }

  function knownSessionId() {
    if (freshChat) return "";
    if (sessionId) return sessionId;
    if (!compact) return sessionIdFromPath();
    return localStorage.getItem("ai_workspace_session") || "";
  }

  async function openSession(id, fromUrl = false) {
    const work = loadSession(id, fromUrl);
    sessionLoad = work.then(() => {}, () => {});
    return work;
  }

  // Placeholder while a chat loads: Standard layout (user right, plain assistant text and reply row).
  function skeletonLines(lines) {
    return lines.map((w) => `<span class="skeleton-line" style="--w:${w}%"></span>`).join("");
  }

  function messageSkeleton() {
    const turns = [
      ["user", [[58]]],
      ["assistant", [[94], [82], [48]], true],
      ["user", [[42]]],
      ["assistant", [[88], [62]], true],
      ["user", [[50]]],
      ["assistant", [[72], [54]], true],
    ];
    const blocks = turns
      .map(([role, lines, actions]) => {
        const text = `<div class="skeleton-text">${skeletonLines(lines)}</div>`;
        const row = actions
          ? '<div class="skeleton-reply-actions" aria-hidden="true"><span class="skeleton-icon"></span><span class="skeleton-icon"></span><span class="skeleton-time"></span></div>'
          : "";
        return `<div class="skeleton-bubble ${role}">${text}${row}</div>`;
      })
      .join("");
    return `<div class="message-skeleton" aria-hidden="true">${blocks}</div><p class="sr" role="status">${htmlAttr(t("chat_loading"))}</p>`;
  }

  let skeletonTimer = 0;
  let slowTimer = 0;

  function clearLoadTimers() {
    window.clearTimeout(skeletonTimer);
    window.clearTimeout(slowTimer);
    skeletonTimer = 0;
    slowTimer = 0;
  }

  function clearLoadState() {
    clearLoadTimers();
    logEl.removeAttribute("aria-busy");
    logEl.querySelector(".message-skeleton")?.remove();
    logEl.querySelector(".chat-load-hint")?.remove();
    logEl.querySelector(".sr[role='status']")?.remove();
    logEl.classList.remove("is-revealing");
    logEl.style.minHeight = "";
  }

  function dismissLoadSkeleton() {
    const skeleton = logEl.querySelector(".message-skeleton");
    logEl.removeAttribute("aria-busy");
    logEl.querySelector(".chat-load-hint")?.remove();
    if (!skeleton) {
      logEl.querySelector(".sr[role='status']")?.remove();
      logEl.classList.remove("is-revealing");
      logEl.style.minHeight = "";
      return;
    }
    const done = () => {
      skeleton.remove();
      logEl.querySelector(".sr[role='status']")?.remove();
      logEl.classList.remove("is-revealing");
      logEl.style.minHeight = "";
    };
    if (reduceMotion) {
      done();
      return;
    }
    skeleton.classList.add("is-leaving");
    skeleton.addEventListener(
      "transitionend",
      (event) => {
        if (event.target === skeleton) done();
      },
      { once: true },
    );
    window.setTimeout(done, 320);
  }

  function showMessageSkeleton() {
    setWelcome(false, false);
    logEl.setAttribute("aria-busy", "true");
    logEl.innerHTML = messageSkeleton();
  }

  // Loading the chat failed (timeout, 5xx, network). Keep the chat and its address, offer a retry.
  function showLoadError(id) {
    clearLoadState();
    setWelcome(false, false);
    const card = document.createElement("div");
    card.className = "chat-load-error";
    card.setAttribute("role", "alert");
    const text = document.createElement("p");
    text.textContent = t("chat_load_failed");
    const retry = document.createElement("ha-button");
    retry.setAttribute("appearance", "accent");
    retry.setAttribute("size", "s");
    retry.className = "chat-load-retry";
    retry.textContent = t("retry");
    retry.addEventListener("click", () => {
      card.remove();
      sessionId = "";
      openSession(id, true);
    });
    card.append(text, retry);
    logEl.replaceChildren(card);
  }

  let firstLoad = true;

  async function fetchSession(id) {
    const early = takeSessionPrefetch(id);
    if (early) return early;
    try {
      const response = await apiFetch(`${API}/sessions/${id}`, { priority: "high" }, { raise: true, timeout: LOAD_TIMEOUT_MS });
      return { response, body: response?.ok ? await response.json() : null };
    } catch (error) {
      return { response: null, body: null, timedOut: error?.name === "TimeoutError" || error?.name === "AbortError" };
    }
  }

  async function loadSession(id, fromUrl = false) {
    if (id && id === sessionId && (streaming || liveStream)) {
      selectSessionRow(id);
      return;
    }
    const switching = id !== sessionId;
    if (switching) {
      leaveChat();
      clearApprovals();
    }
    watchGen += 1;
    clearLoadState();
    if (!id) {
      routeGen += 1;
      sessionId = "";
      if (switching || draftOwner == null) switchComposer("");
      freshChat = true;
      setChatChoice("", "");
      titleEl.textContent = t("new_chat");
      showEmpty();
      if (!fromUrl) goToSession("");
      selectSessionRow("");
      refreshChatUsage();
      return;
    }
    if (fromUrl && id === sessionId) return;
    const gen = ++routeGen;
    const initial = firstLoad;
    firstLoad = false;
    sessionId = id;
    if (switching || draftOwner == null) switchComposer(id);
    freshChat = false;
    const listed = sessionsEl?.querySelector(`.session-row[data-session-id="${id}"]`);
    if (listed?.dataset.title) titleEl.textContent = displayTitle(listed.dataset.title);
    selectSessionRow(id);
    if (compact) localStorage.setItem("ai_workspace_session", id);
    if (!fromUrl) goToSession(id);
    // The last chat seen in this browser paints at once; the server's answer replaces it if it differs.
    const cached = readChatCache(localStorage, chatCacheSlot(), id);
    if (cached) {
      setChatChoice(cached.provider, cached.model);
      paintSession(cached, gen);
    } else if (initial) {
      showMessageSkeleton();
    } else if (switching) {
      logEl.replaceChildren();
      // A quick switch never flashes placeholders.
      skeletonTimer = window.setTimeout(() => {
        if (gen === routeGen) showMessageSkeleton();
      }, SKELETON_DELAY_MS);
    }
    slowTimer = window.setTimeout(() => {
      if (gen !== routeGen || cached || (!logEl.querySelector(".message-skeleton") && !switching && !initial)) return;
      const hint = document.createElement("p");
      hint.className = "chat-load-hint";
      hint.textContent = t("chat_slow");
      if (!logEl.querySelector(".message-skeleton")) showMessageSkeleton();
      logEl.appendChild(hint);
    }, SLOW_HINT_MS);
    const { response, body, timedOut } = await fetchSession(id);
    if (gen !== routeGen) return;
    clearLoadTimers();
    const outcome = loadOutcome(response, timedOut);
    if (outcome === "gone") {
      clearLoadState();
      // Only a chat that is really gone falls back to a new chat.
      clearChatCache(localStorage, chatCacheSlot(), { id });
      chatQueues.drop(id);
      dropDraft(id);
      sessionId = "";
      switchComposer("");
      titleEl.textContent = t("new_chat");
      showEmpty();
      goToSession("", true);
      return;
    }
    if (outcome !== "ok" || !body) {
      if (!cached) showLoadError(id);
      return;
    }
    const session = body;
    setChatChoice(session.provider, session.model);
    if (!cached || !sameChat(cached, session)) paintSession(session, gen);
    else {
      // Same newest messages: only the older ones, which the cache leaves out, are added above.
      turnHasHistory = Boolean(session.has_activity);
      prependOlder(session.messages, olderCount(cached, session));
    }
    writeChatCache(localStorage, chatCacheSlot(), session);
    if (Array.isArray(session.approvals)) syncApprovals(session.approvals, id);
    selectSessionRow(id);
    // Queued prompts of this chat (written before switching away) go on from here.
    if (nextTurns.length) resumeQueue(id);
    else if (session.pending) watchPending(id);
    else markRead(id, session.messages);
    refreshChatUsage();
  }

  function prependOlder(messages, count) {
    if (!count) return;
    const head = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const message = messages[i];
      addBubble(message.role, message.content, message.events, {
        animate: false,
        follow: false,
        createdAt: message.created_at,
        parent: head,
      });
    }
    holdChatScroll(() => {
      const first = logEl.querySelector(".bubble");
      if (first) logEl.insertBefore(head, first);
      else logEl.prepend(head);
    });
    settleTools(logEl);
    syncCopyChat();
    stickToBottom();
  }

  function paintSession(session, gen = routeGen) {
    clearMicHelp();
    titleEl.textContent = displayTitle(session.title);
    const skeleton = logEl.querySelector(".message-skeleton");
    const revealing = Boolean(skeleton);
    if (revealing) {
      logEl.classList.add("is-revealing");
      logEl.style.minHeight = `${skeleton.offsetHeight}px`;
      skeleton.classList.add("is-overlay");
    } else {
      logEl.replaceChildren();
    }
    const messages = session.messages || [];
    turnHasHistory = Boolean(session.has_activity);
    if (!messages.length) {
      if (revealing) clearLoadState();
      else logEl.replaceChildren();
      showEmpty();
      turnHasHistory = Boolean(session.has_activity);
      syncCopyChat();
      if (!("has_activity" in session)) refreshTurnHistory();
      return;
    }
    setWelcome(false, false);
    const paintRange = (from, to, parent) => {
      for (let i = from; i < to; i += 1) {
        const message = messages[i];
        addBubble(message.role, message.content, message.events, {
          animate: false,
          follow: false,
          createdAt: message.created_at,
          parent,
        });
      }
    };
    const finish = () => {
      if (gen !== routeGen) return;
      settleTools(logEl);
      syncCopyChat();
      if (!("has_activity" in session)) refreshTurnHistory();
      clipToBottom();
      stickToBottom();
      requestAnimationFrame(() => requestAnimationFrame(stickToBottom));
      window.setTimeout(stickToBottom, 50);
      window.setTimeout(stickToBottom, 250);
      window.setTimeout(stickToBottom, 700);
    };
    const tailAt = Math.max(0, messages.length - PAINT_TAIL);
    const frag = document.createDocumentFragment();
    paintRange(tailAt, messages.length, frag);
    if (revealing) logEl.insertBefore(frag, skeleton);
    else logEl.appendChild(frag);
    finish();
    if (revealing) dismissLoadSkeleton();
    if (!tailAt) return;
    requestAnimationFrame(() => {
      if (gen !== routeGen) return;
      const head = document.createDocumentFragment();
      paintRange(0, tailAt, head);
      const first = logEl.querySelector(".bubble");
      if (first) logEl.insertBefore(head, first);
      else logEl.prepend(head);
      settleTools(logEl);
      // Older replies get their own action row too.
      syncCopyChat();
      stickToBottom();
    });
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

  // After a reload, follow the reply that is still running: tools, status and text so far,
  // then the rest as it happens. False when nothing can be followed; the caller then polls.
  async function followLive(id, gen) {
    const abort = new AbortController();
    let response;
    try {
      response = await apiFetch(`${API}/sessions/${id}/live`, { signal: abort.signal });
    } catch (_error) {
      return false;
    }
    if (!response?.ok || response.status === 204 || !response.body) return false;
    const stale = () => gen !== watchGen || sessionId !== id || liveStream;
    if (stale()) {
      abort.abort();
      return false;
    }
    ensureThinkingBubble();
    const bubble = logEl.querySelector(".bubble.assistant.streaming");
    const textNode = bubble?.querySelector(".text");
    if (!bubble || !textNode) {
      abort.abort();
      return false;
    }
    // The stream starts from the beginning of the reply, so the bubble does too.
    bubble.querySelector(".tools")?.remove();
    const tools = document.createElement("div");
    tools.className = "tools";
    streamFull = "";
    streamBuf = "";
    streamPainted = "";
    streamFinal = false;
    streamNode = textNode;
    setMarkdown(textNode, "");
    textNode.hidden = true;
    bubble.classList.remove("has-text");
    let caughtUp = false;
    try {
      await readSSE(response, (name, data) => {
        if (stale()) {
          abort.abort();
          return;
        }
        if (name === "caught_up") {
          // What happened before the reload shows at once; only new text is typed out.
          revealAllNow();
          caughtUp = true;
          scrollChatToBottom();
          return;
        }
        if (name === "text") {
          appendAssistantText(textNode, data.delta || "");
          return;
        }
        if (name === "tool" && data.text) {
          if (!tools.parentElement) bubble.insertBefore(tools, textNode);
          textPaintedAt = 0;
          addChip(tools, data, caughtUp);
          setActivity(bubble, "");
        } else if (name === "tool_progress") {
          showToolProgress(bubble, tools, data);
        } else if (name === "status") {
          setActivity(bubble, data.text);
        } else if (name === "plan_notice") {
          appendPlanNotice(data);
        } else if (name === "fallback") {
          applyFallback(data);
        } else if (name === "approval") {
          showApproval(data.approval);
        } else if (name === "title" && data.title) {
          applySessionTitle(id, data.title);
        } else if (name === "done" || name === "error") {
          settleTools(bubble);
        }
        if (caughtUp) scrollChatToBottom();
      });
    } catch (_error) {
      // A dropped connection is fine: the caller looks at the chat again.
    }
    revealAllNow();
    return true;
  }

  async function watchPending(id) {
    if (!id || liveStream || !chatVisible()) return false;
    const gen = ++watchGen;
    // Only auto-speak when we were waiting on a background reply — not when polling
    // an already-finished chat (overlay resume, visibility, etc.).
    let sawPending = Boolean(logEl.querySelector(".bubble.assistant.streaming"));
    // Polling every 2 seconds for up to an hour; following a live reply does not use up attempts.
    for (let attempt = 0; attempt < 1800; attempt += 1) {
      if (gen !== watchGen || sessionId !== id || liveStream || !chatVisible()) return false;
      let session;
      try {
        const pendingResponse = await apiFetch(`${API}/sessions/${id}`);
        if (gen !== watchGen || sessionId !== id || liveStream) return false;
        if (pendingResponse?.status === 404) {
          chatGone();
          return false;
        }
        if (!pendingResponse?.ok) return false;
        session = await pendingResponse.json();
      } catch (error) {
        if (!isDisconnect(error) && attempt > 2) return false;
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        continue;
      }
      if (session.pending) {
        sawPending = true;
        ensureThinkingBubble();
        const followed = performance.now();
        if (await followLive(id, gen)) {
          // A follow that ends at once (dropped connection) must not turn into a tight loop.
          if (performance.now() - followed < 2000) await new Promise((resolve) => window.setTimeout(resolve, 1000));
          else attempt -= 1;
          continue;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        continue;
      }
      if (needsPaint(session)) paintSession(session);
      else {
        const live = logEl.querySelector(".bubble.assistant.streaming");
        if (live) {
          live.classList.remove("streaming");
          stampReply(live);
          setActivity(live, "");
        }
        // Nothing runs any more, so no tool chip can still be busy. Without this a reply
        // followed after a dropped connection kept "Calling N tools" and its shimmer.
        settleTools(logEl);
      }
      streaming = false;
      resizeComposer();
      syncCopyChat();
      applySessionTitle(id, session.title);
      bumpSession(id, session.title, session.pinned);
      writeChatCache(localStorage, chatCacheSlot(), session);
      markRead(id, session.messages);
      if (sawPending && voice.speak && voice.tts) {
        const leftover = speechTail(speakRaw, lastAssistantText());
        if (leftover) {
          feedSpeech(leftover);
          drainSpeech(true);
        }
      }
      return true;
    }
    return false;
  }

  async function readSSE(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const emit = (raw) => {
      let event = "message";
      const dataLines = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      if (!dataLines.length) return;
      let data;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch (_err) {
        console.debug("AI Workspace skipped a malformed event", raw);
        return;
      }
      onEvent(event, data);
    };
    const drain = () => {
      buffer = buffer.replace(/\r\n/g, "\n");
      let splitAt;
      while ((splitAt = buffer.indexOf("\n\n")) !== -1) {
        emit(buffer.slice(0, splitAt));
        buffer = buffer.slice(splitAt + 2);
      }
    };
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      drain();
    }
    buffer += decoder.decode();
    drain();
    if (buffer.trim()) emit(buffer);
  }

  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let capture = null;
  let captureStarting = false;
  let captureTicket = 0;
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
    try {
      if (typeof createImageBitmap === "function") {
        return await createImageBitmap(file);
      }
    } catch (_err) {
      /* WebView / HEIC: try an <img> decode next. */
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
    if (!file) return null;
    try {
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
    } catch (_err) {
      return null;
    }
  }

  function isImageFile(file) {
    const type = String(file?.type || "").toLowerCase();
    if (type.startsWith("image/")) return true;
    return /\.(jpe?g|png|webp|gif|heic|heif)$/i.test(file?.name || "");
  }

  function freezeFiles(files, slots = MAX_ATTACH) {
    const list = filesToRead(files, slots);
    if (!list.length) return Promise.resolve([]);
    return Promise.all(
      list.map(
        (file) =>
          new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = () => {
              const buf = reader.result;
              resolve(new File([buf], file.name || "image", { type: file.type || "application/octet-stream" }));
            };
            reader.onerror = () => resolve(file);
            reader.readAsArrayBuffer(file);
          }),
      ),
    );
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
        const chip = composerCreate("ha-input-chip", "div");
        chip.className = "file-chip pending";
        haChipLabel(chip, item.name);
        const drop = () => {
          pending.splice(index, 1);
          renderThumbs();
          resizeComposer();
        };
        if (chip.localName === "ha-input-chip") {
          chip.removable = true;
          chip.addEventListener("remove", (event) => {
            event.preventDefault();
            drop();
          });
        } else {
          const name = document.createElement("span");
          name.className = "name";
          name.textContent = item.name;
          const remove = document.createElement("ha-icon-button");
          remove.className = "thumb-remove";
          remove.label = t("remove_file");
          const icon = document.createElement("ha-icon");
          icon.setAttribute("icon", "mdi:close");
          remove.append(icon);
          remove.addEventListener("click", drop);
          chip.replaceChildren(name, remove);
        }
        attachRow.appendChild(chip);
        return;
      }
      const thumb = document.createElement("div");
      thumb.className = "thumb";
      const picture = document.createElement("img");
      picture.src = item.src;
      picture.alt = item.name || t("image");
      const remove = document.createElement("ha-icon-button");
      remove.className = "thumb-remove";
      remove.label = t("remove_image");
      const closeIcon = document.createElement("ha-icon");
      closeIcon.setAttribute("icon", "mdi:close");
      remove.append(closeIcon);
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
          const image = await fileToImage(file);
          if (image) pending.push(image);
          else notice = "attach_unsupported";
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

  form.querySelectorAll(".file-input").forEach((input) => {
    input.addEventListener("change", async () => {
      const slots = MAX_ATTACH - pending.length;
      const picked = input.files?.length || 0;
      const frozen = await takeInputFiles(input, freezeFiles, slots);
      if (frozen.length) await addFiles(frozen);
      if (filesLeftOut(picked, slots)) showAttachNotice("attach_limit");
    });
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
    if (!files.length) return;
    const slots = MAX_ATTACH - pending.length;
    await addFiles(await freezeFiles(files, slots));
    if (filesLeftOut(files.length, slots)) showAttachNotice("attach_limit");
  });
  form.addEventListener("paste", async (event) => {
    if (!fromComposerField(event)) return;
    const files = imageFilesFromClipboard(event);
    if (!files.length) return;
    event.preventDefault();
    const slots = MAX_ATTACH - pending.length;
    await addFiles(await freezeFiles(files, slots));
    if (filesLeftOut(files.length, slots)) showAttachNotice("attach_limit");
  });

  function speechLanguage() {
    const hass = document.querySelector("home-assistant")?.hass;
    return hass?.locale?.language || hass?.language || navigator.language || "en";
  }

  function stopSpeech() {
    listening = false;
    for (const btn of composerControls(".mic")) {
      btn.classList.remove("listening");
      btn.label = t("dictate");
      btn.querySelector("ha-icon")?.setAttribute("icon", "mdi:microphone");
    }
    try {
      recognition?.stop();
    } catch (_err) {
      /* already stopped */
    }
    captureTicket += 1;
    const active = capture;
    capture = null;
    active?.stop().catch(() => {});
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
    if (!primaryMicButton()) return;
    if (!SpeechRecognitionAPI || !window.isSecureContext) {
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
        const spoken = parts.join(" ").replace(/\s+/g, " ").trim();
        setComposerText(interim ? `${spoken} ` : spoken);
        resizeComposer();
      };
      recognition.onerror = (event) => {
        if (event.error === "not-allowed") {
          for (const btn of composerControls(".mic")) btn.label = t("mic_blocked");
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
    setMicListening(true);
    try {
      recognition.start();
    } catch (_err) {
      stopSpeech();
      showMicHelp();
    }
  }

  agentMenu?.addEventListener("wa-select", (event) => {
    const picked = event.detail?.item;
    const id = picked?.value;
    if (!id || picked.disabled) return;
    localStorage.setItem("ai_workspace_agent", id);
    defaultProvider = id;
    setChatChoice(id, "");
    saveChatChoice({ provider: id, model: "" });
  });
  modelMenu?.addEventListener("wa-select", (event) => {
    const name = event.detail?.item?.value;
    if (!name) return;
    const item = providerItems.find((row) => row.id === selectedAgent());
    chatModel = name === item?.model ? "" : name;
    renderModelPicker();
    saveChatChoice({ model: chatModel });
  });
  modelMenu?.addEventListener("wa-show", () => {
    modelTrigger?.setAttribute("aria-expanded", "true");
  });
  modelMenu?.addEventListener("wa-hide", () => {
    modelTrigger?.setAttribute("aria-expanded", "false");
  });
  agentMenu?.addEventListener("wa-show", () => {
    agentTrigger?.setAttribute("aria-expanded", "true");
  });
  agentMenu?.addEventListener("wa-hide", () => {
    agentTrigger?.setAttribute("aria-expanded", "false");
  });

  let replyAudio = null;
  let replyObjectUrl = "";
  let speakGen = 0;
  let speakHeld = "";
  let speakRaw = "";
  let speakStarted = false;
  let speakFromUser = false;
  let speakBusy = false;
  let speakFlush = false;
  let speakFresh = false;
  let speakRelease = null;
  let speakTarget = null;
  const speakPending = [];
  const speakInflight = [];
  const SILENCE =
    "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";

  async function unlockOutput() {
    if (!replyAudio) {
      replyAudio = new Audio();
      replyAudio.setAttribute("playsinline", "");
      bindReplyAudio();
    }
    try {
      replyAudio.src = SILENCE;
      await replyAudio.play();
    } catch (_err) {
      /* WebView may still block until a later tap */
    }
    // Unlocked now; drop the silent clip at once so Android gives audio focus back.
    if (String(replyAudio.src || "").startsWith("data:")) releaseAudio(replyAudio);
  }

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
    if (capture || captureStarting) return;
    captureStarting = true;
    const ticket = ++captureTicket;
    let stream = null;
    let ctx = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
      if (ticket !== captureTicket) {
        // Stopped or sent while the browser was still asking for the microphone.
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      ctx = new AudioContext();
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
      capture = {
        async stop() {
          proc.disconnect();
          source.disconnect();
          stream.getTracks().forEach((track) => track.stop());
          await ctx.close();
          return encodeWav(chunks, ctx.sampleRate || 16000);
        },
      };
      listening = true;
      setMicListening(true);
    } catch (err) {
      stream?.getTracks().forEach((track) => track.stop());
      ctx?.close().catch(() => {});
      throw err;
    } finally {
      captureStarting = false;
    }
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
    setComposerText([base, said].filter(Boolean).join(" "));
    resizeComposer();
  }

  function showSpeakHelp() {
    if (!bannerEl) return;
    bannerEl.classList.add("mic-help");
    bannerEl.hidden = false;
    bannerEl.textContent = t("speak_failed");
    if (micNoticeTimer) clearTimeout(micNoticeTimer);
    micNoticeTimer = window.setTimeout(() => {
      clearMicHelp();
    }, 6000);
  }

  function setSpeakUi(state) {
    syncCopyChat();
    const btn = logEl.querySelector(".speak-chat");
    if (!btn) return;
    const icon = btn.querySelector("ha-icon");
    if (state === "playing") {
      icon?.setAttribute("icon", "mdi:pause");
      btn.label = t("pause_reply");
      btn.classList.add("speaking");
    } else if (state === "paused") {
      icon?.setAttribute("icon", "mdi:play");
      btn.label = t("speak_reply");
      btn.classList.remove("speaking");
    } else {
      icon?.setAttribute("icon", "mdi:volume-high");
      btn.label = t("speak_reply");
      btn.classList.remove("speaking");
    }
  }

  function bindReplyAudio() {
    if (!replyAudio || replyAudio._speakBound) return;
    replyAudio._speakBound = true;
    replyAudio.addEventListener("play", () => {
      if (String(replyAudio.src || "").startsWith("data:")) return;
      setSpeakUi("playing");
    });
    replyAudio.addEventListener("pause", () => {
      if (!replyAudio || replyAudio.ended || !replyObjectUrl || String(replyAudio.src || "").startsWith("data:")) {
        if (replyAudio?.ended) setSpeakUi("idle");
        return;
      }
      setSpeakUi("paused");
    });
    replyAudio.addEventListener("ended", () => setSpeakUi("idle"));
  }

  function haltSpeech() {
    speakGen += 1;
    speakTarget = null;
    speakHeld = "";
    speakRaw = "";
    speakStarted = false;
    speakBusy = false;
    speakFromUser = false;
    speakFlush = false;
    speakFresh = false;
    speakPending.length = 0;
    speakInflight.length = 0;
    if (speakRelease) speakRelease();
    if (replyObjectUrl) {
      URL.revokeObjectURL(replyObjectUrl);
      replyObjectUrl = "";
    }
    releaseAudio(replyAudio);
    setSpeakUi("idle");
  }

  function resetSpeechTurn() {
    speakHeld = "";
    speakRaw = "";
    speakStarted = false;
    speakFlush = false;
    speakFresh = true;
  }

  function drainSpeech(flush, pause = false) {
    if (flush) speakFlush = true;
    const taken = takeSpeech(speakHeld, speakStarted, flush, {
      heavy: voice.ttsHeavy,
      pause,
      fresh: speakFresh,
    });
    speakHeld = taken.rest;
    for (const piece of taken.pieces) {
      speakStarted = true;
      speakFresh = false;
      queueSpeech(piece);
    }
    if (taken.pieces.length) syncCopyChat();
    if (flush) fillSpeakAhead();
    if (pause) speakFresh = true;
  }

  function feedSpeech(delta) {
    // A reply picked by hand is being read: the live reply does not cut in.
    if (!voice.speak || !delta || speakTarget) return;
    speakRaw += delta;
    speakHeld += delta;
    drainSpeech(false);
  }

  function syncSpeechTo(full) {
    if (!voice.speak || !full) return;
    const extra = speechTail(speakRaw, full);
    if (extra) feedSpeech(extra);
  }

  function queueSpeech(text) {
    const clean = String(text || "").trim();
    if (!clean) return;
    speakPending.push(clean);
    fillSpeakAhead();
    kickSpeak();
  }

  function fillSpeakAhead() {
    // Local engines (Piper) often drop a second overlapping request; AI voices need a
    // prefetch so the next clip is ready when the current one ends.
    const ahead = voice.ttsHeavy ? 2 : 1;
    while (speakInflight.length < ahead && speakPending.length) {
      let text = "";
      if (voice.ttsHeavy) {
        if (!speakInflight.length) {
          const parts = splitSpeechClip(speakPending.shift(), MAX_CHARS, spokenLength);
          text = parts.shift() || "";
          if (parts.length) speakPending.unshift(...parts);
        } else {
          text = takePendingClip(speakPending, { flush: speakFlush, measure: spokenLength });
        }
      } else {
        const parts = splitSpeechClip(speakPending.shift(), MAX_CHARS, spokenLength);
        text = parts.shift() || "";
        if (parts.length) speakPending.unshift(...parts);
      }
      if (!text) {
        if (!speakPending.length) break;
        continue;
      }
      speakInflight.push(fetchSpeech(text, speakGen));
    }
  }

  function plainForTts(text) {
    return speechPlain(text, { natural: voice.ttsNatural !== false });
  }

  function spokenLength(text) {
    return plainForTts(text).length;
  }

  async function fetchSpeech(text, gen) {
    const plain = plainForTts(text);
    if (!plain) return null;
    const wait = Math.min(60000, 20000 + plain.length * 50);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (gen !== speakGen) return null;
      const ac = new AbortController();
      const timer = window.setTimeout(() => ac.abort(), wait);
      try {
        const response = await apiFetch(`${API}/tts`, {
          method: "POST",
          body: JSON.stringify({ text: plain, language: speechLanguage(), session_id: sessionId || "" }),
          signal: ac.signal,
        });
        if (gen !== speakGen) return null;
        if (!response?.ok) continue;
        const blob = await response.blob();
        if (gen !== speakGen) return null;
        if (!blob || blob.size < 32) continue;
        return blob;
      } catch (_err) {
        /* retry once — a long README used to abort every clip after the first paragraph */
      } finally {
        window.clearTimeout(timer);
      }
    }
    return null;
  }

  function playSpeechBlob(blob, gen) {
    return new Promise((resolve) => {
      if (gen !== speakGen) {
        resolve();
        return;
      }
      if (replyObjectUrl) URL.revokeObjectURL(replyObjectUrl);
      replyObjectUrl = URL.createObjectURL(blob);
      if (!replyAudio) {
        replyAudio = new Audio();
        replyAudio.setAttribute("playsinline", "");
      }
      bindReplyAudio();
      let settled = false;
      let watchdog = 0;
      let started = false;
      const startedAt = Date.now();
      let lastProgress = startedAt;
      let lastTime = 0;
      const onPlaying = () => {
        started = true;
        lastProgress = Date.now();
      };
      const done = () => {
        if (settled) return;
        settled = true;
        if (watchdog) window.clearInterval(watchdog);
        replyAudio.removeEventListener("ended", done);
        replyAudio.removeEventListener("error", done);
        replyAudio.removeEventListener("playing", onPlaying);
        if (speakRelease === done) speakRelease = null;
        resolve();
      };
      // Moves on when a clip never reports `ended` or stalls, but never while the user paused it.
      const check = () => {
        if (settled) return;
        const now = Date.now();
        const time = Number(replyAudio.currentTime) || 0;
        if (replyAudio.paused || time !== lastTime) lastProgress = now;
        lastTime = time;
        const verdict = clipWatch({
          now,
          startedAt,
          lastProgress,
          started,
          paused: replyAudio.paused,
          ended: replyAudio.ended,
          currentTime: time,
          duration: Number(replyAudio.duration),
        });
        if (verdict === "done") done();
      };
      speakRelease = done;
      replyAudio.addEventListener("ended", done);
      replyAudio.addEventListener("error", done);
      replyAudio.addEventListener("playing", onPlaying);
      watchdog = window.setInterval(check, 1000);
      replyAudio.pause();
      replyAudio.src = replyObjectUrl;
      replyAudio.play().catch(() => {
        if (speakFromUser) showSpeakHelp();
        done();
      });
    });
  }

  function kickSpeak() {
    if (speakBusy) return;
    speakBusy = true;
    const gen = speakGen;
    const fromUser = speakFromUser;
    (async () => {
      let played = false;
      while (gen === speakGen && (speakInflight.length || speakPending.length)) {
        fillSpeakAhead();
        if (!speakInflight.length) break;
        const blob = await speakInflight.shift();
        fillSpeakAhead();
        if (gen !== speakGen || !blob) continue;
        played = true;
        await playSpeechBlob(blob, gen);
      }
      if (gen === speakGen && fromUser && !played) showSpeakHelp();
    })()
      .finally(() => {
        speakBusy = false;
        if (speakPending.length || speakInflight.length) kickSpeak();
        else if (gen === speakGen && played && replyAudio) {
          // Read-aloud finished: give audio focus back so other apps are no longer ducked.
          if (replyObjectUrl) {
            URL.revokeObjectURL(replyObjectUrl);
            replyObjectUrl = "";
          }
          releaseAudio(replyAudio);
          speakTarget = null;
          setSpeakUi("idle");
        } else if (gen === speakGen && speakTarget) {
          // Nothing could be played for this reply: its button goes back to "read aloud".
          speakTarget = null;
          setSpeakUi("idle");
        }
      });
  }

  function speechPaused() {
    const btn = logEl.querySelector(".speak-chat");
    return Boolean(btn?.classList.contains("speaking") && replyAudio?.paused && !replyAudio.ended);
  }

  async function toggleSpeak() {
    if (replyAudio && !replyAudio.paused && !replyAudio.ended) {
      if (streaming || speakPending.length || speakInflight.length) haltSpeech();
      else replyAudio.pause();
      return;
    }
    if (speechPaused()) {
      try {
        await replyAudio.play();
      } catch (_err) {
        showSpeakHelp();
      }
      return;
    }
    const text = lastAssistantText();
    if (!text) return;
    await speakReply(text, true);
  }

  async function speakReply(text, fromUser = false, target = null) {
    if (!voice.tts || !String(text || "").trim()) return;
    haltSpeech();
    // The reply whose own button started this; its button shows "stop" while it plays.
    speakTarget = target;
    speakFromUser = fromUser;
    const gen = speakGen;
    if (fromUser) await unlockOutput();
    // Another reply was started (or this one stopped) while the output unlocked.
    if (gen !== speakGen) return;
    speakFlush = true;
    const taken = takeSpeech(String(text), false, true, { heavy: voice.ttsHeavy });
    for (const piece of taken.pieces) queueSpeech(piece);
    // Show "stop" at once, not only when the first clip starts playing.
    if (target) syncCopyChat();
  }

  function lastAssistantText() {
    const bubbles = [...logEl.querySelectorAll(".bubble.assistant")];
    for (let i = bubbles.length - 1; i >= 0; i -= 1) {
      const md = bubbles[i].querySelector("ha-markdown.text");
      const text = String(md?.content || md?.textContent || "").trim();
      if (text) return text;
    }
    return "";
  }

  function setMicShown(show) {
    const visible = Boolean(show);
    for (const btn of composerControls(".mic")) {
      btn.classList.toggle("is-hidden", !visible);
      if (visible) btn.removeAttribute("hidden");
      else btn.setAttribute("hidden", "");
      btn.hidden = !visible;
    }
    if (!visible) stopSpeech();
  }

  function setChangeHistoryShown(visible) {
    root.querySelectorAll(".history-open").forEach((btn) => {
      btn.hidden = !visible;
      btn.classList.toggle("is-hidden", !visible);
    });
    if (!visible) closeHistory();
  }

  function setUsageShown(visible) {
    root.querySelectorAll(".usage-open").forEach((btn) => {
      btn.hidden = !visible;
      btn.classList.toggle("is-hidden", !visible);
    });
    if (!visible) {
      if (wrap.classList.contains("page-usage")) leaveUsage();
      closeUsageOverlay();
      const line = root.querySelector(".chat-usage");
      if (line) {
        line.hidden = true;
        line.textContent = "";
      }
    }
  }

  async function remountForUiTheme(nextTheme) {
    if (uiRemountInFlight || nextTheme === activeUiTheme) return;
    uiRemountInFlight = true;
    try {
      const savedSession = sessionId;
      uiTheme = nextTheme;
      uiThemeLoaded = true;
      destroy();
      const api = await mountAiWorkspace(root, {
        ...options,
        forceUiTheme: true,
        restoreSessionId: savedSession,
      });
      options.onRemount?.(api);
    } finally {
      uiRemountInFlight = false;
    }
  }

  let usageTracking = true;
  let showChatUsage = true;

  async function loadDictate() {
    // Stay hidden until /ui explicitly allows the mic (also covers the overlay drawer).
    let show = false;
    let historyOn = true;
    let usageOn = true;
    let headerUsageOn = true;
    try {
      const body = await fetchUiBody(getToken);
      if (body) {
        show = body.dictate === true;
        historyOn = body.change_history !== false;
        usageOn = body.track_usage !== false;
        headerUsageOn = body.show_chat_usage !== false;
        const nextDefault = String(body.default_agent || "");
        const nextSwitcher = body.model_switcher === true;
        if (nextDefault !== defaultAgentId || nextSwitcher !== modelSwitcher) {
          defaultAgentId = nextDefault;
          modelSwitcher = nextSwitcher;
          renderAgentPicker();
        }
        const nextTheme = body.ui_theme === "ha_components" ? "ha_components" : "standard";
        uiTheme = nextTheme;
        uiThemeLoaded = true;
        if (nextTheme !== activeUiTheme) {
          await remountForUiTheme(nextTheme);
          return;
        }
        voice = {
          dictate: show,
          stt: body.stt || "browser",
          speak: body.speak === true,
          tts: Boolean(body.tts) && body.tts !== "off",
          ttsHeavy: body.tts_heavy === true,
          ttsNatural: body.tts_natural !== false,
        };
      }
    } catch (_err) {
      show = false;
    }
    usageTracking = usageOn;
    showChatUsage = usageOn && headerUsageOn;
    setChangeHistoryShown(historyOn);
    setUsageShown(usageOn);
    if (!showChatUsage && chatUsageEl) {
      chatUsageEl.hidden = true;
      chatUsageEl.textContent = "";
    } else if (showChatUsage) {
      refreshChatUsage();
    }
    setMicShown(show);
    syncCopyChat();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    typingAt = 0;
    // Taken before any wait: the chat a queued prompt was written in; it must not go out anywhere else.
    const picked = sendQueued;
    sendQueued = null;
    let queuedFrom = picked ? sessionId : null;
    let queuedTurn = null;
    if (turnStopDone) await turnStopDone;
    let keepComposer = false;
    let text;
    let attachments;
    if (picked) {
      const turn = picked;
      queuedTurn = turn;
      text = turn.text;
      attachments = turn.attachments.slice();
      keepComposer = true;
    } else {
      text = messageEl.value.trim();
      attachments = pending.slice();
      if (streaming) {
        if (!text && !attachments.length) return;
        clipToBottom();
        queueTurn(text, attachments);
        stickToBottom();
        return;
      }
      if (!text && !attachments.length) {
        if (!nextTurns.length) return;
        const turn = nextTurns.shift();
        queuedFrom = sessionId;
        queuedTurn = turn;
        text = turn.text;
        attachments = turn.attachments.slice();
        renderNext();
        keepComposer = true;
      }
    }
    const handBack = () => {
      // Back on its own chat's list, first in line; sent there when that chat is free.
      if (!queuedTurn) return;
      chatQueues.of(queuedFrom).unshift(queuedTurn);
      queuedTurn = null;
      if (queuedFrom === sessionId) renderNext();
      else if (queuedFrom) sendQueueInBackground(queuedFrom);
    };
    const images = attachments.filter((item) => item.kind === "image");
    const files = attachments.filter((item) => item.kind === "file");
    if (!text && !attachments.length) return;
    await sessionLoad;
    if (!sessionId) {
      const known = knownSessionId();
      if (known) await openSession(known, true);
    }
    if (queuedTurn && sessionId !== queuedFrom) {
      // The user switched chats while it was being picked up.
      handBack();
      return;
    }
    abandonStream({ keepSpeech: keepComposer });
    const token = streamToken;
    const abort = new AbortController();
    streamAbort = abort;
    stopSpeech();
    const speechPlaying = Boolean(
      speakBusy || (replyAudio && !replyAudio.paused && !replyAudio.ended && replyObjectUrl),
    );
    // Only when the reply is read aloud automatically — otherwise leave audio alone
    // (unlocking plays a silent clip, and Android ducks other apps for it).
    if (unlockOnSend(voice) && (!keepComposer || !speechPlaying)) unlockOutput();
    if (keepComposerFocus()) messageEl.focus();
    else hideKeyboard();
    streaming = true;
    syncCopyChat();
    turnHasHistory = false;
    const turnSince = new Date().toISOString();
    watchGen += 1;
    clearKeyboardLock();
    resetOuterScroll();
    const sentPending = pending.slice();
    if (!keepComposer) {
      pending = [];
      renderThumbs();
      setComposerText("");
      dropDraft(sessionId);
    }
    resizeComposer();
    syncSendButton();
    setWelcome(false);
    clipToBottom();
    dropUnsent();
    const userBubble = addBubble("user", text, [
      ...images.map((img) => ({ type: "image", name: img.name, src: img.src })),
      ...files.map((file) => ({ type: "file", name: file.name })),
    ]);
    const assistant = addBubble("assistant", "");
    assistant.classList.add("streaming");
    stickToBottom();
    streamFull = "";
    streamBuf = "";
    streamPainted = "";
    const tools = document.createElement("div");
    tools.className = "tools";
    ensureActivitySlot(assistant);
    setActivity(assistant, t("thinking"));
    let recover = false;
    let sawDone = false;
    let busyRetry = false;
    let chatId = "";
    liveStream = true;
    try {
      if (token !== streamToken) return;
      if (!sessionId) {
        const created = await createSession();
        if (token !== streamToken || !created) return;
        titleEl.textContent = promptTitle(text) || attachments[0]?.name || t("new_chat");
        bumpSession(sessionId, realTitle(titleEl.textContent, t("new_chat")));
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
          model: modelSwitcher ? chatModel : undefined,
        });
      let response = await apiFetch(
        `${API}/sessions/${chatId}/chat`,
        { method: "POST", body: payload, signal: abort.signal },
        { raise: true },
      );
      if (token !== streamToken) return;
      if (response?.status === 409) {
        // A reply still runs in this chat (sent from the background or another device): wait in line.
        for (const bubble of [userBubble, assistant]) bubble?.remove();
        if (queuedTurn) handBack();
        else {
          nextTurns.push({ text, attachments: sentPending.length ? sentPending : attachments.slice() });
          renderNext();
        }
        busyRetry = true;
        return;
      }
      if (response?.status === 404) {
        // Deleted, most likely on another device. Hand the message back for a new chat.
        for (const bubble of [userBubble, assistant]) bubble?.remove();
        chatGone({ text, pending: sentPending });
        return;
      }
      if (!response?.ok || !response.body) {
        const node = assistant.querySelector(".text");
        setMarkdown(node, await errorText(response));
        node.hidden = !node.content;
        assistant.classList.add("error", "has-text");
        setActivity(assistant, "");
        return;
      }
      await readSSE(response, (name, data) => {
        if (token !== streamToken) return;
        if (name === "text") {
          appendAssistantText(assistant.querySelector(".text"), data.delta || "");
          feedSpeech(data.delta || "");
          return;
        }
        if (name === "tool" && data.text) {
          if (!tools.parentElement) {
            const textNode = assistant.querySelector(".text");
            if (textNode) assistant.insertBefore(tools, textNode);
            else assistant.appendChild(tools);
          }
          // A tool step ends the sentence before it, so the status comes back right away.
          textPaintedAt = 0;
          addChip(tools, data, true);
          setActivity(assistant, "");
          drainSpeech(false, true);
        } else if (name === "tool_progress") {
          showToolProgress(assistant, tools, data);
        } else if (name === "status") {
          setStatus(data.text);
          drainSpeech(false, true);
        } else if (name === "plan_notice") {
          appendPlanNotice(data);
        } else if (name === "fallback") {
          applyFallback(data);
        } else if (name === "approval") {
          showApproval(data.approval);
        } else if (name === "error" && data.connection && !streamFull) {
          // Nothing was sent: the header says why, the prompt gets the message back.
          drainSpeech(true);
          streamFinal = true;
          sawDone = true;
          streaming = false;
          showConnectionError(shownError(data.message) || t("error"));
          assistant.remove();
          markNotSent(userBubble, { text, pending: sentPending });
          resizeComposer();
        } else if (name === "error") {
          drainSpeech(true);
          streamFinal = true;
          revealAllNow();
          assistant.classList.add("error");
          const textNode = assistant.querySelector(".text");
          if (!streamFull) {
            setMarkdown(textNode, shownError(data.message) || t("error"));
            textNode.hidden = !textNode.content;
            assistant.classList.add("has-text");
          }
          settleTools(assistant);
          setActivity(assistant, "");
          if (sessionId === chatId) markRead(chatId);
        } else if (name === "done") {
          sawDone = true;
          streamFinal = true;
          clearConnectionError();
          streamNode = streamNode || assistant.querySelector(".text");
          if (data.answer) {
            queueStreamAnswer(data.answer);
          }
          startStreamPump();
          if (voice.speak) syncSpeechTo(String(data.answer || lastAssistantText() || ""));
          drainSpeech(true);
          settleTools(assistant);
          streaming = false;
          assistant.classList.remove("streaming");
          stampReply(assistant);
          setActivity(assistant, "");
          resizeComposer();
          // The header belongs to the open chat; "New chat" there is no title for this row.
          bumpSession(chatId, sessionId === chatId ? realTitle(titleEl.textContent, t("new_chat")) : undefined);
          // Seen as it arrived: no unread dot here or on the user's other devices.
          if (sessionId === chatId) markRead(chatId);
          waitForStream().then(() => {
            if (token === streamToken && sessionId === chatId) {
              syncCopyChat();
              flushNext();
              if (bannerEl && !bannerEl.hidden) loadProviders();
            }
          });
        } else if (name === "title" && data.title) {
          applySessionTitle(chatId, data.title);
          bumpSession(chatId, data.title);
        } else if (name === "usage") {
          applyTurnUsage(data);
        }
        if (name !== "text") scrollChatToBottom();
      });
      await waitForStream();
      streamNode = null;
      if (!sawDone) recover = true;
      // The floating chat has no chat list that would bring the title in later.
      else void syncHeaderTitle(chatId);
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
          setMarkdown(node, shownError(error?.message || error) || t("error"));
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
          stampReply(assistant);
          settleTools(assistant);
          setActivity(assistant, "");
          if (!streamFull) {
            assistant.classList.add("error");
            const node = assistant.querySelector(".text");
            if (node && !node.content) {
              // The connection dropped and the reply did not show up; say so instead of "Thinking".
              setMarkdown(node, t("reply_lost"));
              node.hidden = false;
              assistant.classList.add("has-text");
            } else {
              // Part of the reply arrived, then it stopped: do not let it look finished.
              assistant.classList.remove("error");
              markReplyCut(assistant);
            }
          }
        }
      } else {
        streaming = false;
        settleTools(assistant);
        assistant.classList.remove("streaming");
        stampReply(assistant);
        setActivity(assistant, "");
      }
      syncCopyChat();
      resizeComposer();
      window.setTimeout(() => {
        if (token === streamToken && sessionId === chatId) refreshTurnHistory(turnSince);
      }, 500);
      if (busyRetry) {
        streaming = false;
        resizeComposer();
        window.setTimeout(() => resumeQueue(chatId), 1500);
        return;
      }
      if (followUp && sessionId === chatId && nextTurns.length) {
        flushNext();
        return;
      }
      // A draft already started on the phone should keep the keyboard.
      if (composerFocused()) {
        syncKeyboardInset();
        return;
      }
      if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
      else hideKeyboard();
    }
  });

  chatEl.addEventListener("scroll", () => {
    const top = chatEl.scrollTop;
    syncHeaderShadow();
    if (!scrollLock && typingGuard() && Math.abs(top - acceptedTop) > 0.5) {
      restoreTypingScroll();
      return;
    }
    acceptedTop = top;
    const movedUp = top < lastScrollTop - 1;
    const movedDown = top > lastScrollTop + 1;
    lastScrollTop = top;
    syncScrollBottomBtn();
    if (scrollLock) return;
    if (movedUp && isUserScroll()) {
      releaseFollow();
      return;
    }
    if (holdFollow) {
      if (movedDown && nearBottom()) {
        clipToBottom();
        followBottom();
      }
      return;
    }
    if (nearBottom() && !movedUp && !holdFollow && !keyboardOpen) {
      clipToBottom();
      followBottom();
    }
  }, { passive: true });
  syncHeaderShadow();

  let lastTouchY = 0;

  function fromComposer(event) {
    const path = typeof event.composedPath === "function" ? event.composedPath() : [];
    return path.some((node) => node?.classList?.contains("composer"))
      || Boolean(event.target?.closest?.(".composer"));
  }

  function onLeaveClip(event, y) {
    if (fromComposer(event)) return;
    markUserScroll();
    if (y > lastTouchY + 8) releaseFollow();
    lastTouchY = y;
  }

  chatEl.addEventListener("touchstart", (event) => {
    lastTouchY = event.touches[0]?.clientY || 0;
    if (!fromComposer(event)) markUserScroll();
  }, { passive: true });
  chatEl.addEventListener("touchmove", (event) => {
    onLeaveClip(event, event.touches[0]?.clientY || 0);
  }, { passive: true });
  chatEl.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary) return;
    lastTouchY = event.clientY;
    if (!fromComposer(event)) markUserScroll();
  }, { passive: true });
  chatEl.addEventListener("pointermove", (event) => {
    if (!event.isPrimary) return;
    if (event.pointerType === "mouse" && !event.buttons) return;
    onLeaveClip(event, event.clientY);
  }, { passive: true });
  chatEl.addEventListener("wheel", (event) => {
    if (fromComposer(event)) return;
    markUserScroll();
    if (event.deltaY < 0) releaseFollow();
  }, { passive: true });

  if (messageEl) {
    messageEl.addEventListener("focus", () => {
      if (!nearBottom()) releaseFollow();
      if (keepComposerFocus()) return;
      syncKeyboardInset();
      window.setTimeout(syncKeyboardInset, 280);
    });
    messageEl.addEventListener("blur", () => {
      window.setTimeout(() => {
        if (!composerFocused()) clearKeyboardLock();
      }, 60);
    });
  }
  listen(window.visualViewport, "resize", syncKeyboardInset);
  listen(window.visualViewport, "scroll", () => {
    if (composerFocused()) syncKeyboardInset();
  });
  function fromComposerField(event) {
    for (const node of event.composedPath?.() || [event.target]) {
      if (node?.id === "ai-message" || node?.id === "message-input") return true;
      if (node?.localName === "ha-textarea") return true;
    }
    return false;
  }
  for (const type of ["pointerdown", "focusin", "keydown", "beforeinput"]) {
    form.addEventListener(type, (event) => {
      if (fromComposerField(event)) typingAt = performance.now();
    }, { capture: true });
  }
  form.addEventListener("input", (event) => {
    if (!fromComposerField(event)) return;
    typingAt = performance.now();
    saveDraftSoon();
    if (!nearBottom()) releaseFollow();
    holdChatScroll(resizeComposer);
  });
  // Capture: ha-textarea stops key events from bubbling past itself.
  form.addEventListener("keydown", (event) => {
    if (!fromComposerField(event)) return;
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    // Phones insert a line break. The send button is the only way to submit.
    if (window.matchMedia("(pointer: coarse)").matches) return;
    event.preventDefault();
    form.requestSubmit();
  }, { capture: true });
  form.addEventListener("click", (event) => {
    const attach = event.target.closest?.(".attach");
    if (attach?.closest?.(".composer")) {
      event.preventDefault();
      event.stopPropagation();
      if (pending.length >= MAX_ATTACH) return;
      attach.closest(".composer-row, .input")?.querySelector(".file-input")?.click();
      return;
    }
    const send = event.target.closest?.(".send");
    if (send?.closest?.(".composer")) {
      event.preventDefault();
      if (canStopTurn()) {
        stopTurn();
        return;
      }
      form.requestSubmit();
      return;
    }
    const mic = event.target.closest?.(".mic");
    if (!mic?.closest?.(".composer") || mic.hidden) return;
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
  scrollBottomBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    jumpToBottom();
  });
  const scrollBtnWatch = new ResizeObserver(() => {
    if (keyboardOpen || composerFocused()) {
      syncScrollBottomBtn();
      if (!pinBottom || holdFollow || !nearBottom()) return;
    }
    if (pinBottom && nearBottom()) followBottom();
    else syncScrollBottomBtn();
  });
  scrollBtnWatch.observe(logEl);
  teardown.push(() => scrollBtnWatch.disconnect());

  function startNewChat() {
    setSearchOpen(false);
    const wasNew = !sessionId && draftOwner === NEW_CHAT_DRAFT;
    leaveChat();
    clearMicHelp();
    routeGen += 1;
    watchGen += 1;
    sessionId = "";
    if (!wasNew) switchComposer("");
    freshChat = true;
    setChatChoice("", "");
    renderThumbs();
    if (compact) localStorage.removeItem("ai_workspace_session");
    closeNavIfOverlay();
    goToSession("");
    titleEl.textContent = t("new_chat");
    showEmpty();
    selectSessionRow("");
    refreshChatUsage();
    if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
  }

  const historyEl = root.querySelector(".history");
  const historyList = root.querySelector(".history-list");
  const usageEl = root.querySelector(".usage");
  const usageList = root.querySelector(".usage-list");
  const usageRangeEl = root.querySelector(".usage-range");
  const usageFiltersEl = root.querySelector(".usage-filters");
  const chatUsageEl = root.querySelector(".chat-usage");
  let usageRange = "month";
  let usageAgent = "";
  let usageModel = "";
  let usageChat = "";
  let usageSince = "";
  let usageUntil = "";
  let usageLoadGen = 0;
  let usagePickerQuiet = false;
  let usageSelectQuiet = false;

  function activityWhen(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function syncHistoryButtons(open) {
    root.querySelectorAll(".history-open").forEach((btn) => {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function historyIsOpen() {
    return wrap.classList.contains("history-open") || Boolean(historyEl && !historyEl.hidden);
  }

  function closeHistory() {
    wrap.classList.remove("history-open");
    syncHistoryButtons(false);
    if (!historyEl) return;
    historyEl.setAttribute("aria-hidden", "true");
    const hide = (event) => {
      if (event && event.target !== historyEl) return;
      if (event && event.propertyName && event.propertyName !== "transform") return;
      if (!wrap.classList.contains("history-open")) historyEl.hidden = true;
    };
    historyEl.addEventListener("transitionend", hide, { once: true });
    window.setTimeout(hide, 320);
  }

  async function refreshTurnHistory(sinceIso) {
    turnHasHistory = false;
    const chatId = String(sessionId || "").trim();
    if (!chatId) {
      syncCopyChat();
      return;
    }
    try {
      const resp = await apiFetch(`${API}/activity`);
      if (!resp?.ok) {
        syncCopyChat();
        return;
      }
      const rows = await resp.json();
      const since = Date.parse(sinceIso || "") || 0;
      turnHasHistory = (Array.isArray(rows) ? rows : []).some((row) => {
        if (String(row.session_id || "") !== chatId) return false;
        if (!since) return true;
        const at = Date.parse(row.created_at || "") || 0;
        return at >= since - 2500;
      });
    } catch (_err) {
      turnHasHistory = false;
    }
    syncCopyChat();
  }

  async function loadHistory() {
    if (!historyList) return;
    historyList.replaceChildren();
    const resp = await apiFetch(`${API}/activity`);
    const emptyHistory = () => {
      const note = document.createElement("p");
      note.className = "history-empty";
      note.textContent = t("activity_empty");
      historyList.appendChild(note);
    };
    if (!resp || !resp.ok) {
      emptyHistory();
      return;
    }
    const rows = await resp.json();
    if (!Array.isArray(rows) || !rows.length) {
      emptyHistory();
      return;
    }
    for (const row of rows) historyList.appendChild(historyRow(row));
  }

  function historyRow(row) {
    const item = document.createElement("article");
    item.className = "history-row panel-card";
    const when = document.createElement("p");
    when.className = "history-when";
    when.textContent = activityWhen(row.created_at);
    const line = document.createElement("p");
    line.className = "history-summary";
    line.textContent = row.summary || "";
    const who = document.createElement("p");
    who.className = "history-who";
    const title = displayTitle(row.chat) || row.user_name || "";
    const chatId = String(row.session_id || "").trim();
    if (chatId && title) {
      const link = document.createElement("a");
      link.className = "history-chat";
      link.href = sessionPath(chatId);
      link.textContent = title;
      link.addEventListener("click", (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
        event.preventDefault();
        closeHistory();
        openSession(chatId);
      });
      who.append(link, row.agent ? ` · ${String(row.agent).replace(/Â·/g, "·")}` : "");
    } else {
      who.textContent = [title, String(row.agent || "").replace(/Â·/g, "·")].filter(Boolean).join(" · ");
    }
    item.append(when, line, who);
    if (row.undone_at) {
      const restored = document.createElement("p");
      restored.className = "history-restored";
      restored.textContent = t("restored");
      item.appendChild(restored);
      return item;
    }
    if (row.can_rollback) {
      const button = document.createElement("ha-button");
      button.className = "history-rollback";
      button.setAttribute("size", "s");
      button.setAttribute("appearance", "plain");
      button.textContent = t("rollback");
      button.addEventListener("click", async () => {
        const ok = await askConfirm(t("rollback"), t("rollback_confirm", { summary: row.summary || "" }), t("rollback"));
        if (!ok) return;
        button.disabled = true;
        const resp = await apiFetch(`${API}/activity/${row.id}/rollback`, { method: "POST", body: "{}" });
        if (!resp || !resp.ok) {
          button.disabled = false;
          button.textContent = t("rollback_failed");
          let detail = "";
          if (resp) {
            detail = (await resp.text()).trim();
            if (detail) button.title = detail.slice(0, 300);
          }
          if (row.agent_undo) {
            // The snapshot could not be written back; the agent may still undo it with its tools.
            const why = detail ? `${detail}\n\n` : "";
            if (await askConfirm(t("rollback_failed"), `${why}${t("rollback_try_agent")}`, t("ask_restore"))) {
              undoWithAgent(row);
            }
            return;
          }
          await askAlert(t("rollback_failed"), detail || t("rollback_failed"));
          return;
        }
        await loadHistory();
      });
      item.appendChild(button);
    }
    if (row.ask_restore) {
      const button = document.createElement("ha-button");
      button.className = "history-rollback";
      button.setAttribute("size", "s");
      button.setAttribute("appearance", "plain");
      button.textContent = t("ask_restore");
      button.addEventListener("click", async () => {
        const ok = await askConfirm(
          t("ask_restore"),
          t("ask_restore_confirm", { summary: row.summary || "" }),
          t("ask_restore"),
        );
        if (!ok) return;
        undoWithAgent(row);
      });
      item.appendChild(button);
      return item;
    }
    return item;
  }

  function undoWithAgent(row) {
    closeHistory();
    setComposerText(restorePrompt(row));
    form.requestSubmit();
  }

  function restorePrompt(row) {
    const lines = [`Change: ${row.summary || ""}`, `When: ${row.created_at || ""}`];
    if (row.logical_commit && row.change_count > 1) {
      lines.push(`Logical commit: ${row.change_count} related writes in one agent turn.`);
    }
    const targets = Array.isArray(row.restore_targets) ? row.restore_targets : [];
    if (targets.length) {
      targets.forEach((target, index) => {
        const parts = [
          target.kind ? `Kind: ${target.kind}` : "",
          target.id ? `Id: ${target.id}` : "",
          target.label ? `Label: ${target.label}` : "",
        ].filter(Boolean);
        if (parts.length) lines.push(`${index + 1}. ${parts.join(" · ")}`);
      });
    } else {
      if (row.restore_kind) lines.push(`Kind: ${row.restore_kind}`);
      if (row.restore_id) lines.push(`Id: ${row.restore_id}`);
      if (row.restore_label) lines.push(`Label: ${row.restore_label}`);
    }
    if (row.tool) lines.push(`Tool: ${row.tool}`);
    return t("ask_restore_prompt", { details: lines.join("\n") });
  }

  async function openHistory() {
    if (!historyEl) return;
    if (!wrap.classList.contains("page-usage")) closeUsageOverlay();
    historyEl.hidden = false;
    historyEl.setAttribute("aria-hidden", "false");
    syncHistoryButtons(true);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => wrap.classList.add("history-open"));
    });
    await loadHistory();
  }

  function toggleHistory() {
    if (historyIsOpen()) closeHistory();
    else openHistory();
  }

  root.querySelectorAll(".history-open").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      toggleHistory();
    });
  });
  root.querySelector(".history-close")?.addEventListener("click", (event) => {
    event.preventDefault();
    closeHistory();
  });

  function money(usd) {
    if (usd == null || Number.isNaN(Number(usd))) return t("usage_unknown_cost");
    return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 4 }).format(Number(usd));
  }

  function tokenLabel(count) {
    const n = Number(count) || 0;
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
    return String(n);
  }

  function turnWord(count) {
    return Number(count) === 1 ? t("usage_turn") : t("usage_turns");
  }

  function cachedTokens(summary) {
    return Number(summary?.cache_read_tokens || 0) + Number(summary?.cache_write_tokens || 0);
  }

  // A summary's line in parts: before the cost, the cost, after it (the chat header swaps the cost).
  function usageParts(summary) {
    const before = [`${tokenLabel(summary.total_tokens || 0)} ${t("usage_tokens")}`];
    const cached = cachedTokens(summary);
    if (cached) before.push(`${tokenLabel(cached)} ${t("usage_cached")}`);
    let cost = "";
    if (summary.cost_usd != null) cost = money(summary.cost_usd);
    else if (summary.missing_cost) cost = t("usage_unknown_cost");
    const after = summary.turns ? [`${summary.turns} ${turnWord(summary.turns)}`] : [];
    return { before, cost, after };
  }

  function usageLine(summary) {
    if (!summary) return "";
    const { before, cost, after } = usageParts(summary);
    return [...before, ...(cost ? [cost] : []), ...after].join(" · ");
  }

  function applyTurnUsage(data) {
    if (!data || !usageTracking) return;
    // A worker job's usage is stored on its own; the "last" line stays this turn's.
    if (chatUsageEl && showChatUsage && !data.worker) {
      const cost = data.cost_usd == null ? t("usage_unknown_cost") : money(data.cost_usd);
      setChatUsageLine(
        t("usage_last"),
        { before: [tokenLabel(data.total_tokens || 0)], after: [] },
        cost,
        chatPlanSnap(),
      );
    }
    refreshChatUsage();
    if (usageIsVisible()) loadUsage();
  }

  async function refreshChatUsage() {
    if (!chatUsageEl || !usageTracking || !showChatUsage) {
      if (chatUsageEl) {
        chatUsageEl.hidden = true;
        chatUsageEl.textContent = "";
      }
      return;
    }
    if (!sessionId) {
      chatUsageEl.hidden = true;
      chatUsageEl.textContent = "";
      return;
    }
    try {
      const resp = await apiFetch(`${API}/usage?session_id=${encodeURIComponent(sessionId)}`);
      if (!resp?.ok) return;
      const body = await resp.json();
      if (body.plan_quota && typeof body.plan_quota === "object") lastPlanQuota = body.plan_quota;
      const summary = body.session;
      if (!summary || !summary.turns) {
        chatUsageEl.hidden = true;
        return;
      }
      const { before, cost, after } = usageParts(summary);
      setChatUsageLine("", { before, after }, cost, chatPlanSnap());
    } catch (_err) {
      /* keep last */
    }
  }

  function metricCard(label, summary, kind) {
    const card = document.createElement("article");
    card.className = "usage-card";
    const title = document.createElement("p");
    title.className = "usage-card-title";
    title.textContent = label;
    const cost = document.createElement("p");
    cost.className = "usage-card-cost";
    cost.textContent = summary?.missing_cost && !summary.cost_usd ? t("usage_unknown_cost") : money(summary?.cost_usd || 0);
    const meta = document.createElement("p");
    meta.className = "usage-card-meta";
    if (kind === "tts") {
      meta.textContent = `${tokenLabel(summary?.characters || 0)} ${t("usage_characters")} · ${summary?.turns || 0} ${t("usage_reads")}`;
    } else {
      const cached = cachedTokens(summary);
      const bits = [`${tokenLabel(summary?.total_tokens || 0)} ${t("usage_tokens")}`];
      if (cached) bits.push(`${tokenLabel(cached)} ${t("usage_cached")}`);
      bits.push(`${summary?.turns || 0} ${turnWord(summary?.turns || 0)}`);
      meta.textContent = bits.join(" · ");
    }
    card.append(title, cost, meta);
    return card;
  }

  function kpiCard(label, row) {
    const card = document.createElement("article");
    card.className = "usage-card usage-kpi";
    const title = document.createElement("p");
    title.className = "usage-card-title";
    title.textContent = label;
    const name = document.createElement("p");
    name.className = "usage-kpi-model";
    name.textContent = row?.model || "—";
    const meta = document.createElement("p");
    meta.className = "usage-card-meta";
    const bits = [];
    if (row) bits.push(usageLine(row));
    if (row?.tokens_per_turn) bits.push(`${tokenLabel(row.tokens_per_turn)} ${t("usage_tokens_per_turn")}`);
    if (row?.cost_per_turn != null) bits.push(`${money(row.cost_per_turn)} ${t("usage_cost_per_turn")}`);
    meta.textContent = bits.join(" · ") || t("usage_empty");
    card.append(title, name, meta);
    return card;
  }

  function svgNode(name, attrs = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  }

  function usageChart(title, points, valueKey, formatTick) {
    const card = document.createElement("article");
    card.className = "usage-chart";
    const heading = document.createElement("p");
    heading.className = "usage-chart-title";
    heading.textContent = title;
    const svg = svgNode("svg", { viewBox: "0 0 640 180", role: "img", class: "usage-chart-svg" });
    svg.setAttribute("aria-label", title);
    const values = (Array.isArray(points) ? points : []).map((point) => Number(point[valueKey]) || 0);
    const max = Math.max(...values, 0);
    const padL = 6;
    const padR = 6;
    const padT = 10;
    const padB = 28;
    const width = 640;
    const height = 180;
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;
    const count = Math.max(values.length, 1);
    const gap = innerW / count;
    const barW = Math.max(3, gap * 0.62);
    const axis = svgNode("line", {
      x1: padL,
      x2: width - padR,
      y1: height - padB,
      y2: height - padB,
      class: "usage-chart-axis",
    });
    svg.appendChild(axis);
    values.forEach((value, index) => {
      const barHeight = max > 0 ? (value / max) * innerH : 0;
      const x = padL + index * gap + (gap - barW) / 2;
      const y = height - padB - barHeight;
      const rect = svgNode("rect", {
        x,
        y: value > 0 ? y : height - padB,
        width: barW,
        height: value > 0 ? Math.max(barHeight, 1) : 0,
        rx: 2,
        class: "usage-chart-bar",
      });
      const tip = svgNode("title");
      const day = points[index]?.date || "";
      tip.textContent = `${day}: ${formatTick(value)}`;
      rect.appendChild(tip);
      svg.appendChild(rect);
    });
    if (points.length) {
      const first = svgNode("text", { x: padL, y: height - 8, class: "usage-chart-label" });
      first.textContent = String(points[0].date || "").slice(5);
      const last = svgNode("text", { x: width - padR, y: height - 8, class: "usage-chart-label", "text-anchor": "end" });
      last.textContent = String(points[points.length - 1].date || "").slice(5);
      svg.append(first, last);
    }
    card.append(heading, svg);
    return card;
  }

  function modelTable(models) {
    const wrapTable = document.createElement("div");
    wrapTable.className = "usage-table-wrap";
    const table = document.createElement("table");
    table.className = "usage-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const label of [
      t("usage_model"),
      t("usage_turns"),
      t("usage_tokens"),
      t("usage_cost"),
      t("usage_tokens_per_turn"),
      t("usage_cost_per_turn"),
      t("usage_per_1k"),
    ]) {
      const th = document.createElement("th");
      th.textContent = label;
      if (label !== t("usage_model")) th.className = "num";
      headRow.appendChild(th);
    }
    head.appendChild(headRow);
    const body = document.createElement("tbody");
    for (const row of models) {
      const tr = document.createElement("tr");
      const cells = [
        row.model || t("usage_model"),
        String(row.turns || 0),
        tokenLabel(row.total_tokens || 0),
        row.cost_usd == null && row.missing_cost ? t("usage_unknown_cost") : money(row.cost_usd || 0),
        tokenLabel(row.tokens_per_turn || 0),
        row.cost_per_turn == null ? "—" : money(row.cost_per_turn),
        row.cost_per_1k == null ? "—" : money(row.cost_per_1k),
      ];
      cells.forEach((value, index) => {
        const td = document.createElement("td");
        td.textContent = value;
        if (index) td.className = "num";
        if (index === 0 && row.agent && row.agent !== row.model) {
          const sub = document.createElement("span");
          sub.className = "usage-table-agent";
          sub.textContent = ` · ${row.agent}`;
          td.appendChild(sub);
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    }
    table.append(head, body);
    wrapTable.appendChild(table);
    return wrapTable;
  }

  function renderUsageRange(current) {
    if (!usageRangeEl) return;
    const keep = [
      ...usageRangeEl.querySelectorAll("ha-date-range-nav, ha-date-range-picker, .usage-native-dates"),
    ];
    usageRangeEl.replaceChildren();
    for (const key of ["today", "month", "all"]) {
      const btn = document.createElement(haHas("ha-button") ? "ha-button" : "button");
      btn.className = "usage-range-btn";
      if (btn.localName === "ha-button") {
        btn.setAttribute("size", "s");
        btn.setAttribute("variant", "brand");
        btn.setAttribute("appearance", current === key ? "accent" : "plain");
      } else {
        btn.type = "button";
      }
      btn.setAttribute("aria-pressed", current === key ? "true" : "false");
      btn.textContent = t(`usage_${key}`);
      btn.addEventListener("click", () => {
        if (usageRange === key && !usageSince && !usageUntil) return;
        usageRange = key;
        usageSince = "";
        usageUntil = "";
        loadUsage();
      });
      usageRangeEl.appendChild(btn);
    }
    for (const el of keep) usageRangeEl.appendChild(el);
  }

  function canUseHaSelect() {
    if (!haHas("ha-select")) return false;
    const el = document.createElement("ha-select");
    return "options" in el;
  }

  function usageFilterSelectEl(className) {
    return usageFiltersEl?.querySelector(`ha-select.${className}, select.${className}`);
  }

  function usageSelectValue(raw) {
    const value = raw == null ? "" : String(raw);
    return !value || value === "all" ? "" : value;
  }

  function usageDayText(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function usageDayDate(text, end = false) {
    const match = String(text || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    const date = match
      ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
      : new Date();
    if (end) date.setHours(23, 59, 59, 999);
    else date.setHours(0, 0, 0, 0);
    return date;
  }

  function usageSameDay(left, right) {
    return left.getFullYear() === right.getFullYear()
      && left.getMonth() === right.getMonth()
      && left.getDate() === right.getDate();
  }

  function usagePresetRange(key) {
    const end = new Date();
    end.setHours(23, 59, 59, 999);
    if (key === "today") {
      const start = new Date();
      start.setHours(0, 0, 0, 0);
      return { start, end };
    }
    const start = new Date(end.getFullYear(), end.getMonth(), 1);
    start.setHours(0, 0, 0, 0);
    return { start, end };
  }

  function usageCurrentRange() {
    if (usageSince || usageUntil) {
      return {
        start: usageDayDate(usageSince || usageUntil, false),
        end: usageDayDate(usageUntil || usageSince, true),
      };
    }
    return usagePresetRange(usageRange === "today" ? "today" : "month");
  }

  function applyUsagePickerRange(startDate, endDate) {
    let start = startDate;
    let end = endDate;
    if (start > end) [start, end] = [end, start];
    const today = usagePresetRange("today");
    const month = usagePresetRange("month");
    let nextRange = "custom";
    let nextSince = "";
    let nextUntil = "";
    if (usageSameDay(start, today.start) && usageSameDay(end, today.end)) {
      nextRange = "today";
    } else if (usageSameDay(start, month.start) && usageSameDay(end, month.end)) {
      nextRange = "month";
    } else {
      nextSince = usageDayText(start);
      nextUntil = usageDayText(end);
    }
    if (usageRange === nextRange && usageSince === nextSince && usageUntil === nextUntil) return;
    usageRange = nextRange;
    usageSince = nextSince;
    usageUntil = nextUntil;
    loadUsage();
  }

  function fillUsageSelect(select, items, current) {
    if (!select) return;
    const options = [
      { value: "all", label: t("usage_filter_all") },
      ...items.map((item) => ({
        value: String(item.id || item),
        label: String(item.title || item),
      })),
    ];
    if (current && !options.some((item) => item.value === current)) {
      options.push({ value: current, label: current });
    }
    const value = current || "all";
    usageSelectQuiet = true;
    if (select.localName === "ha-select") {
      select.options = options;
      select.value = value;
    } else {
      select.replaceChildren();
      for (const item of options) {
        const opt = document.createElement("option");
        opt.value = item.value === "all" ? "" : item.value;
        opt.textContent = item.label;
        select.appendChild(opt);
      }
      select.value = current || "";
    }
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        usageSelectQuiet = false;
      });
    });
  }

  function createUsageSelect(className, label, onChange) {
    if (canUseHaSelect()) {
      const select = document.createElement("ha-select");
      select.className = `${className} usage-filter`;
      select.label = label;
      select.addEventListener("selected", (event) => onChange(event.detail?.value));
      return select;
    }
    const wrap = document.createElement("label");
    wrap.className = "usage-filter";
    const cap = document.createElement("span");
    cap.textContent = label;
    const select = document.createElement("select");
    select.className = className;
    select.addEventListener("change", () => onChange(select.value));
    wrap.append(cap, select);
    return wrap;
  }

  function createUsageDateFilter() {
    const tag = haHas("ha-date-range-nav")
      ? "ha-date-range-nav"
      : haHas("ha-date-range-picker")
        ? "ha-date-range-picker"
        : "";
    if (tag) {
      const picker = document.createElement(tag);
      picker.className = "usage-filter usage-filter-dates";
      if ("extendedPresets" in picker) picker.extendedPresets = true;
      const hass = hassObj();
      if (hass && "hass" in picker) picker.hass = hass;
      const { start, end } = usageCurrentRange();
      usagePickerQuiet = true;
      picker.startDate = start;
      picker.endDate = end;
      picker.addEventListener("value-changed", (event) => {
        if (usagePickerQuiet) return;
        const value = event.detail?.value || {};
        const startDate = value.startDate instanceof Date ? value.startDate : picker.startDate;
        const endDate = value.endDate instanceof Date ? value.endDate : picker.endDate;
        if (!(startDate instanceof Date) || !(endDate instanceof Date)) return;
        applyUsagePickerRange(startDate, endDate);
      });
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          usagePickerQuiet = false;
        });
      });
      return [picker];
    }
    const wrap = document.createElement("div");
    wrap.className = "usage-native-dates";
    const fromWrap = document.createElement("label");
    fromWrap.className = "usage-filter";
    const fromCap = document.createElement("span");
    fromCap.textContent = t("usage_filter_from");
    const fromInput = document.createElement("input");
    fromInput.type = "date";
    fromInput.className = "usage-filter-from";
    fromInput.addEventListener("change", () => {
      usageSince = fromInput.value;
      usageRange = usageSince || usageUntil ? "custom" : "month";
      loadUsage();
    });
    fromWrap.append(fromCap, fromInput);
    const toWrap = document.createElement("label");
    toWrap.className = "usage-filter";
    const toCap = document.createElement("span");
    toCap.textContent = t("usage_filter_to");
    const toInput = document.createElement("input");
    toInput.type = "date";
    toInput.className = "usage-filter-to";
    toInput.addEventListener("change", () => {
      usageUntil = toInput.value;
      usageRange = usageSince || usageUntil ? "custom" : "month";
      loadUsage();
    });
    toWrap.append(toCap, toInput);
    wrap.append(fromWrap, toWrap);
    return [wrap];
  }

  function usageDateHost() {
    return usageRangeEl || usageFiltersEl;
  }

  function usageFiltersNeedRebuild() {
    const host = usageDateHost();
    if (!usageFiltersEl?.childElementCount) return true;
    const wantPicker = haHas("ha-date-range-nav") || haHas("ha-date-range-picker");
    const hasPicker = Boolean(host?.querySelector("ha-date-range-nav, ha-date-range-picker"));
    const wantSelect = canUseHaSelect();
    const hasSelect = Boolean(usageFiltersEl.querySelector("ha-select"));
    const hasChat = Boolean(usageFiltersEl.querySelector(".usage-filter-chat"));
    return wantPicker !== hasPicker || wantSelect !== hasSelect || !hasChat;
  }

  function syncUsageDateFilter() {
    const host = usageDateHost();
    const picker = host?.querySelector("ha-date-range-nav, ha-date-range-picker");
    if (picker) {
      const { start, end } = usageCurrentRange();
      if (picker.startDate?.getTime?.() === start.getTime() && picker.endDate?.getTime?.() === end.getTime()) {
        return;
      }
      usagePickerQuiet = true;
      picker.startDate = start;
      picker.endDate = end;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          usagePickerQuiet = false;
        });
      });
      return;
    }
    const fromInput = host?.querySelector(".usage-filter-from");
    const toInput = host?.querySelector(".usage-filter-to");
    if (fromInput) fromInput.value = usageSince;
    if (toInput) toInput.value = usageUntil;
  }

  function renderUsageFilters(body) {
    if (!usageFiltersEl) return;
    const filters = body?.filters || {};
    if (usageFiltersNeedRebuild()) {
      usageFiltersEl.replaceChildren();
      const host = usageDateHost();
      host?.querySelectorAll("ha-date-range-nav, ha-date-range-picker, .usage-native-dates").forEach((el) => el.remove());
      usageFiltersEl.append(
        createUsageSelect("usage-filter-agent", t("usage_filter_agent"), (value) => {
          if (usageSelectQuiet) return;
          const next = usageSelectValue(value);
          if (next === usageAgent) return;
          usageAgent = next;
          usageModel = "";
          loadUsage();
        }),
        createUsageSelect("usage-filter-model", t("usage_filter_model"), (value) => {
          if (usageSelectQuiet) return;
          const next = usageSelectValue(value);
          if (next === usageModel) return;
          usageModel = next;
          loadUsage();
        }),
        createUsageSelect("usage-filter-chat", t("usage_filter_chat"), (value) => {
          if (usageSelectQuiet) return;
          const next = usageSelectValue(value);
          if (next === usageChat) return;
          usageChat = next;
          loadUsage();
        }),
      );
      host?.append(...createUsageDateFilter());
    }
    const chats = Array.isArray(filters.chats) ? filters.chats : [];
    if (usageChat && !chats.some((row) => String(row.id || row) === usageChat)) {
      usageChat = "";
      loadUsage();
      return;
    }
    fillUsageSelect(usageFilterSelectEl("usage-filter-agent"), Array.isArray(filters.agents) ? filters.agents : [], usageAgent);
    fillUsageSelect(usageFilterSelectEl("usage-filter-model"), Array.isArray(filters.models) ? filters.models : [], usageModel);
    fillUsageSelect(usageFilterSelectEl("usage-filter-chat"), chats, usageChat);
    syncUsageDateFilter();
  }

  async function loadUsage() {
    if (!usageList) return;
    const gen = ++usageLoadGen;
    const stale = () => gen !== usageLoadGen;
    await ensureHaComponents(["ha-select", "ha-date-range-nav", "ha-date-range-picker"]);
    if (stale()) return;
    renderUsageRange(usageRange);
    const query = new URLSearchParams({ range: usageRange });
    if (usageChat) query.set("session_id", usageChat);
    if (usageAgent) query.set("agent_id", usageAgent);
    if (usageModel) query.set("model", usageModel);
    if (usageSince) query.set("since", usageSince);
    if (usageUntil) query.set("until", usageUntil);
    const resp = await apiFetch(`${API}/usage?${query}`);
    if (stale()) return;
    if (!resp || !resp.ok) {
      renderUsageFilters();
      if (stale()) return;
      const note = document.createElement("p");
      note.className = "usage-empty";
      note.textContent = t("usage_empty");
      usageList.replaceChildren(note);
      return;
    }
    const body = await resp.json();
    if (stale()) return;
    renderUsageFilters(body);
    if (stale()) return;
    const frag = document.createDocumentFragment();
    if (body.enabled === false) {
      const note = document.createElement("p");
      note.className = "usage-empty";
      note.textContent = t("usage_disabled");
      frag.appendChild(note);
      if (stale()) return;
      usageList.replaceChildren(frag);
      return;
    }
    const plan = body.plan_quota || {};
    if (plan && typeof plan === "object") lastPlanQuota = plan;
    const planLinks = body.plan_links || {};
    const engineOrder = ["claude", "cursor", "codex"];
    const planRows = engineOrder
      .map((engine) => [engine, plan[engine]])
      .filter(([, snap]) => planHasData(snap));
    const planSection = document.createDocumentFragment();
    const planHeading = document.createElement("p");
    planHeading.className = "usage-heading";
    planHeading.textContent = t("usage_plan_heading");
    planSection.appendChild(planHeading);
    if (planRows.length) {
      const planGrid = document.createElement("div");
      planGrid.className = "usage-grid usage-plans";
      for (const [engine, snap] of planRows) planGrid.appendChild(planCard(engine, snap, planLinks[engine]));
      planSection.appendChild(planGrid);
    } else {
      const note = document.createElement("p");
      note.className = "usage-empty";
      note.textContent = t("usage_plan_empty");
      planSection.appendChild(note);
    }
    // On a subscription the limits are what counts: plan cards first, the $ estimates below.
    if (planRows.length) frag.appendChild(planSection);
    const grid = document.createElement("div");
    grid.className = "usage-grid";
    if (body.range === "custom" && body.totals?.selected) {
      grid.append(metricCard(t("usage_selected"), body.totals.selected));
    }
    grid.append(
      metricCard(t("usage_today"), body.totals?.today),
      metricCard(t("usage_month"), body.totals?.month),
      metricCard(t("usage_all"), body.totals?.all),
    );
    frag.appendChild(grid);
    const planAgents = planAgentIds(plan);
    if (planAgents.size) {
      const note = document.createElement("p");
      note.className = "usage-card-meta usage-plan-cost-note";
      note.textContent = t("usage_plan_cost_note");
      frag.appendChild(note);
    }
    if (!planRows.length) frag.appendChild(planSection);
    if (body.tts?.today?.turns || body.tts?.all?.turns) {
      frag.appendChild(metricCard(t("usage_tts"), body.tts.today, "tts"));
    }
    if (body.tasks?.month?.turns) {
      // Agent task runs (ai_workspace.run_task) this month; they also count in the totals.
      frag.appendChild(metricCard(taskStrings(hassLanguage()).tasks, body.tasks.month, "tokens"));
    }
    const kpis = body.kpis || {};
    if (kpis.most_spend || kpis.most_used || kpis.most_efficient || kpis.leanest) {
      const heading = document.createElement("p");
      heading.className = "usage-heading";
      heading.textContent = t("usage_compare");
      frag.appendChild(heading);
      const kpiGrid = document.createElement("div");
      kpiGrid.className = "usage-kpis";
      if (kpis.most_spend) kpiGrid.appendChild(kpiCard(t("usage_kpi_spend"), kpis.most_spend));
      if (kpis.most_used) kpiGrid.appendChild(kpiCard(t("usage_kpi_used"), kpis.most_used));
      if (kpis.most_efficient) kpiGrid.appendChild(kpiCard(t("usage_kpi_efficient"), kpis.most_efficient));
      if (kpis.leanest) kpiGrid.appendChild(kpiCard(t("usage_kpi_lean"), kpis.leanest));
      frag.appendChild(kpiGrid);
    }
    const days = Array.isArray(body.days) ? body.days : [];
    if (days.length) {
      const chartsHead = document.createElement("p");
      chartsHead.className = "usage-heading";
      const from = body.filters?.since || "";
      const to = body.filters?.until || "";
      if (body.range === "custom" && from && to) chartsHead.textContent = t("usage_days_range", { from, to });
      else if (body.range === "custom" && from) chartsHead.textContent = t("usage_days_from", { from });
      else if (body.range === "custom" && to) chartsHead.textContent = t("usage_days_until", { to });
      else chartsHead.textContent = t("usage_days");
      frag.appendChild(chartsHead);
      const charts = document.createElement("div");
      charts.className = "usage-charts";
      charts.append(
        usageChart(t("usage_chart_cost"), days, "cost_usd", (value) => money(value)),
        usageChart(t("usage_chart_tokens"), days, "total_tokens", (value) => tokenLabel(value)),
      );
      frag.appendChild(charts);
    }
    const models = Array.isArray(body.models) ? body.models : [];
    if (models.length) {
      const heading = document.createElement("p");
      heading.className = "usage-heading";
      heading.textContent = t("usage_models");
      frag.appendChild(heading);
      frag.appendChild(modelTable(models));
    }
    const agents = Array.isArray(body.agents) ? body.agents : [];
    if (agents.length) {
      const heading = document.createElement("p");
      heading.className = "usage-heading";
      heading.textContent = t("usage_agents");
      frag.appendChild(heading);
      for (const agent of agents) {
        const row = document.createElement("article");
        row.className = "usage-agent";
        const name = document.createElement("p");
        name.className = "usage-agent-name";
        name.textContent = agent.title || agent.id || t("agent");
        const today = document.createElement("p");
        today.className = "usage-agent-today";
        today.textContent = `${t("usage_today")}: ${usageLine(agent.today)}`;
        const all = document.createElement("p");
        all.className = "usage-agent-all";
        all.textContent = `${t("usage_all")}: ${usageLine(agent.all)}`;
        row.append(name, today, all);
        if (planAgents.has(agent.id)) {
          const note = document.createElement("p");
          note.className = "usage-agent-all";
          note.textContent = t("usage_plan_theoretical");
          row.appendChild(note);
        }
        frag.appendChild(row);
      }
    }
    if (!body.totals?.all?.turns) {
      const note = document.createElement("p");
      note.className = "usage-empty";
      note.textContent = t("usage_empty");
      frag.appendChild(note);
    }
    const hint = document.createElement("p");
    hint.className = "usage-hint";
    hint.textContent = t("usage_ha_hint");
    frag.appendChild(hint);
    if (stale()) return;
    usageList.replaceChildren(frag);
  }

  function syncUsageButtons(open) {
    root.querySelectorAll(".usage-open").forEach((btn) => {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
  }

  function usageIsOpen() {
    return wrap.classList.contains("usage-open") || Boolean(usageEl && !usageEl.hidden && !wrap.classList.contains("page-usage"));
  }

  function usageIsVisible() {
    return wrap.classList.contains("page-usage") || usageIsOpen();
  }

  function closeUsageOverlay() {
    wrap.classList.remove("usage-open");
    if (wrap.classList.contains("page-usage")) return;
    syncUsageButtons(false);
    if (!usageEl) return;
    usageEl.setAttribute("aria-hidden", "true");
    const hide = (event) => {
      if (event && event.target !== usageEl) return;
      if (event && event.propertyName && event.propertyName !== "transform") return;
      if (!wrap.classList.contains("usage-open") && !wrap.classList.contains("page-usage")) usageEl.hidden = true;
    };
    if (usageEl.hidden) return;
    usageEl.addEventListener("transitionend", hide, { once: true });
    window.setTimeout(() => hide(), 320);
  }

  function openUsageOverlay() {
    if (!usageEl) return;
    closeHistory();
    usageEl.hidden = false;
    usageEl.setAttribute("aria-hidden", "false");
    syncUsageButtons(true);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => wrap.classList.add("usage-open"));
    });
    loadUsage();
  }

  function openUsagePage() {
    closeHistory();
    closeNavIfOverlay();
    const already = wrap.classList.contains("page-usage") && Boolean(usageEl) && !usageEl.hidden;
    wrap.classList.add("page-usage");
    wrap.classList.remove("usage-open");
    if (usageEl) {
      usageEl.hidden = false;
      usageEl.setAttribute("aria-hidden", "false");
    }
    syncUsageButtons(true);
    if (!already) loadUsage();
  }

  function closeUsagePage() {
    if (!wrap.classList.contains("page-usage")) return;
    wrap.classList.remove("page-usage");
    syncUsageButtons(false);
    if (!usageEl) return;
    usageEl.hidden = true;
    usageEl.setAttribute("aria-hidden", "true");
  }

  function leaveUsage() {
    if (routed) goToSession(sessionId || "");
    else closeUsageOverlay();
  }

  function goToUsage() {
    if (wrap.classList.contains("page-usage") || (!routed && typeof navigate === "function" && location.pathname.replace(/\/$/, "") === usagePath())) {
      return;
    }
    if (routed || typeof navigate === "function") {
      const path = usagePath();
      if (typeof navigate === "function") navigate(path);
      else {
        history.pushState(null, "", path);
        window.dispatchEvent(new CustomEvent("location-changed"));
      }
      return;
    }
    if (usageIsOpen()) closeUsageOverlay();
    else openUsageOverlay();
  }

  root.querySelectorAll(".usage-open").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      goToUsage();
    });
  });

  // Tasks page: lives at /ai-workspace/tasks; tasks_page.js loads the first time it opens.
  const tasksEl = root.querySelector(".tasks-page");
  let tasksPage = null;

  function syncTasksButtons(open) {
    root.querySelectorAll(".tasks-open").forEach((btn) => {
      if (open) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
  }

  async function openTasksPage() {
    if (!tasksEl) return;
    closeHistory();
    closeNavIfOverlay();
    wrap.classList.add("page-tasks");
    tasksEl.hidden = false;
    tasksEl.setAttribute("aria-hidden", "false");
    syncTasksButtons(true);
    if (!tasksPage) {
      const { mountTasksPage } = await import(`./tasks_page.js${CACHE}`);
      tasksPage = mountTasksPage(tasksEl, {
        hass: hassObj,
        lang: hassLanguage(),
        apiFetch,
        openPath: openHaPath,
        openChat: (id) => goToSession(id),
      });
    }
    await tasksPage.load();
  }

  function closeTasksPage() {
    if (!wrap.classList.contains("page-tasks")) return;
    wrap.classList.remove("page-tasks");
    syncTasksButtons(false);
    if (!tasksEl) return;
    tasksEl.hidden = true;
    tasksEl.setAttribute("aria-hidden", "true");
  }

  root.querySelectorAll(".tasks-open").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      if (wrap.classList.contains("page-tasks")) return;
      const path = "/ai-workspace/tasks";
      if (typeof navigate === "function") navigate(path);
      else {
        history.pushState(null, "", path);
        window.dispatchEvent(new CustomEvent("location-changed"));
      }
    });
  });
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
  sessionsEl?.addEventListener("scroll", closeSessionMenu, { passive: true });
  listen(window, "keydown", (event) => {
    if (event.key !== "Escape") return;
    if (wrap.classList.contains("history-open")) {
      closeHistory();
      return;
    }
    if (wrap.classList.contains("page-usage")) {
      leaveUsage();
      return;
    }
    if (wrap.classList.contains("page-tasks") && !root.querySelector(".tasks-form:not([hidden])")) {
      goToSession(sessionId || "");
      return;
    }
    if (wrap.classList.contains("usage-open")) {
      closeUsageOverlay();
      return;
    }
    if (root.querySelector("ha-dialog[open]")) return;
    if (root.querySelector(".session-more[aria-expanded='true'], .agent-trigger[aria-expanded='true']")) return;
    if (wrap.classList.contains("nav-open")) setNavOpen(false);
  });
  listen(mqNarrow, "change", () => setNarrow(options.narrow));

  logEl.addEventListener("click", onReplyAction);
  logEl.addEventListener("animationend", (event) => {
    if (event.target?.classList?.contains("reply-actions")) event.target.classList.remove("is-fresh");
  });

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
    listen(window, "location-changed", applyRoute);
    listen(window, "popstate", applyRoute);
  }
  if (compact) {
    const drawer = overlayDrawer();
    if (drawer) {
      const watchOpen = new MutationObserver(() => {
        if (!drawer.classList.contains("open")) haltSpeech();
      });
      watchOpen.observe(drawer, { attributes: true, attributeFilter: ["class"] });
      teardown.push(() => watchOpen.disconnect());
    }
  }
  listen(window, "location-changed", loadDictate);
  listen(window, "focus", loadDictate);
  listen(document, "visibilitychange", () => {
    loadDictate();
    // Back on the page: a reply that finished meanwhile gets its dot, or is read when its chat is open.
    if (!document.hidden) void refreshSessions();
    if (sessionId && chatVisible()) watchPending(sessionId);
    if (sessionId && chatVisible() && !document.hidden) refreshApprovals(sessionId);
    if (bannerEl && !bannerEl.hidden) loadProviders();
  });
  listen(window, "resize", () => {
    if (messageEl) resizeComposer();
  });
  listen(window, "pageshow", () => {
    if (sessionId && chatVisible()) watchPending(sessionId);
    if (sessionId && chatVisible()) refreshApprovals(sessionId);
  });

  const startRoute = compact || !routed ? { view: "chat", sessionId: "" } : workspaceRoute();
  const startId =
    options.restoreSessionId ||
    (compact ? localStorage.getItem("ai_workspace_session") || "" : startRoute.sessionId);
  if (!compact) {
    if (cachedSessions.length) paintSessionList(cachedSessions);
    loadSessions();
  }
  if (!compact && routed && startRoute.view === "usage") {
    showEmpty();
    openUsagePage();
  } else if (startId) openSession(startId, true);
  else showEmpty();
  if (draftOwner == null && !startId) switchComposer("");
  resizeComposer();
  // Agents, mic and usage settings and the HA component chunks are not needed to read the chat:
  // they load once it is on screen, or when the browser is idle.
  let deferredStarted = false;
  const startDeferred = () => {
    if (deferredStarted) return;
    deferredStarted = true;
    loadProviders();
    loadDictate();
    if (haUi) void ensureHaComponents(HA_COMPOSER_PRELOAD);
  };
  const whenIdle = (fn) =>
    typeof window.requestIdleCallback === "function" ? window.requestIdleCallback(fn, { timeout: 800 }) : window.setTimeout(fn, 0);
  sessionLoad.then(() => whenIdle(startDeferred));
  const deferredTimer = window.setTimeout(startDeferred, 2500);
  teardown.push(() => window.clearTimeout(deferredTimer));
  // Mounted with the theme last seen in this browser; switch when /ui says otherwise.
  fetchUiBody(getToken).then((body) => {
    if (!body || !root.isConnected) return;
    const next = body.ui_theme === "ha_components" ? "ha_components" : "standard";
    if (next !== activeUiTheme) void remountForUiTheme(next);
  });
  const linkWatch = new MutationObserver(() => retargetHaLinks(logEl));
  linkWatch.observe(logEl, { subtree: true, childList: true, attributes: true, attributeFilter: ["href", "target"] });
  teardown.push(() => linkWatch.disconnect());
  function resume() {
    loadDictate();
    if (sessionId && nextTurns.length) resumeQueue(sessionId);
    else if (sessionId) watchPending(sessionId);
  }

  function destroy() {
    saveDraft();
    const openChat = sessionId;
    if (sendQueued) chatQueues.of(openChat).unshift(sendQueued);
    sendQueued = null;
    haltStream({ keepQueue: keepQueueOnHalt("destroy") });
    destroyed = true;
    // Queued prompts of the open chat still go out there, also with the panel closed.
    if (openChat) sendQueueInBackground(openChat);
    stopSpeech();
    watchGen += 1;
    routeGen += 1;
    for (const undo of teardown.splice(0)) undo();
    if (followRaf) cancelAnimationFrame(followRaf);
    if (keyboardRaf) cancelAnimationFrame(keyboardRaf);
    releaseAudio(replyAudio);
    replyAudio = null;
    root.replaceChildren();
  }

  return { openSession, applyRoute, setNarrow, toggleNav, startNewChat, loadDictate, resume, destroy, haltSpeech };
}
