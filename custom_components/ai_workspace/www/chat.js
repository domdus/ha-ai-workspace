const CACHE = new URL(import.meta.url).search;
const { stringsFor } = await import(`./i18n.js${CACHE}`);
const { takeSpeech, speechPlain, takePendingClip, speechTail, splitSpeechClip, MAX_CHARS, clipWatch } = await import(
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

const API = "/api/ai_workspace";
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
        })),
      ),
    );
  } catch (_err) {
    /* private mode */
  }
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

const HA_COMPONENT_PRELOAD = [
  "ha-card",
  "ha-alert",
  "ha-empty-state",
  "ha-assist-chip",
  "ha-chip-set",
  "ha-input",
  "ha-textarea",
  "ha-input-chip",
  "ha-list-item-button",
  "ha-markdown",
  "ha-dialog",
  "ha-dialog-footer",
  "ha-button",
  "ha-icon-button",
  "ha-dropdown",
  "ha-dropdown-item",
  "ha-select",
];

let uiTheme = "standard";
let uiThemeLoaded = false;

export function haComponentsUi() {
  return uiTheme === "ha_components";
}

function uiCreate(...names) {
  if (!haComponentsUi()) {
    return document.createElement(names[names.length - 1] || "div");
  }
  return haCreate(...names);
}

async function fetchUiTheme(getToken) {
  const hass = hassObj();
  const token = (typeof getToken === "function" ? getToken() : "") || hass?.auth?.data?.access_token || "";
  if (typeof hass?.fetchWithAuth !== "function" && !token) return uiTheme;
  const headers = { Accept: "application/json" };
  try {
    const response =
      typeof hass?.fetchWithAuth === "function"
        ? await hass.fetchWithAuth(`${API}/ui`, { headers })
        : await fetch(`${API}/ui`, { headers: { ...headers, Authorization: `Bearer ${token}` } });
    if (response?.status === 401 || response?.status === 403) return uiTheme;
    if (response?.ok) {
      const body = await response.json();
      uiTheme = body.ui_theme === "ha_components" ? "ha_components" : "standard";
      uiThemeLoaded = true;
    }
  } catch (_err) {
    return uiTheme;
  }
  return uiTheme;
}

export function invalidateUiThemeCache() {
  uiThemeLoaded = false;
}

export async function prefetchUiTheme(getToken, { force = false } = {}) {
  if (force) invalidateUiThemeCache();
  if (uiThemeLoaded && !force) {
    void fetchUiTheme(getToken);
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
  await prefetchUiTheme(options.getToken, { force: Boolean(options.forceUiTheme) });
  const haUi = haComponentsUi();
  let activeUiTheme = haUi ? "ha_components" : "standard";
  if (haUi) void ensureHaComponents(HA_COMPONENT_PRELOAD);
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
    haUi ? "ui-theme-ha-components" : "ui-theme-standard",
    compact ? "compact" : "",
    options.chrome === "panel" ? "has-app-bar" : "",
    overlayStart ? "narrow" : "",
    collapsedStart ? "nav-collapsed" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const themeCss = haUi
    ? `<link rel="stylesheet" href="/ai_workspace/static/chat-layout.css${CACHE}"><link rel="stylesheet" href="/ai_workspace/static/chat-ha-components.css${CACHE}">`
    : `<link rel="stylesheet" href="/ai_workspace/static/chat.css${CACHE}">`;
  const bannerMarkup = haUi
    ? `<ha-alert class="banner" alert-type="error" hidden></ha-alert>`
    : `<p class="banner" hidden></p>`;
  const workspaceLinkMarkup =
    compact && hassObj()?.user?.is_admin
      ? haUi
        ? `<ha-button class="workspace-link" appearance="plain" size="s" href="/ai-workspace">${t("open_workspace")}</ha-button>`
        : `<a class="workspace-link" href="/ai-workspace">${t("open_workspace")}</a>`
      : "";
  const scrollBottomMarkup = haUi
    ? `<ha-icon-button class="scroll-bottom" tabindex="-1" label="${t("scroll_to_bottom")}"><ha-icon icon="mdi:arrow-down"></ha-icon></ha-icon-button>`
    : `<button type="button" class="scroll-bottom" tabindex="-1" aria-label="${t("scroll_to_bottom")}"><ha-icon icon="mdi:arrow-down"></ha-icon></button>`;
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
    ${themeCss}
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
          <div class="${haUi ? "log messages ha-scrollbar" : "log"}"><p class="empty">${t("empty")}</p></div>
          <form class="composer">
            ${scrollBottomMarkup}
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
    </div>
  `;

  const wrap = root.querySelector(".wrap");
  releaseMountHold(root);
  const scrim = root.querySelector(".nav-scrim");
  const chatEl = root.querySelector(".chat");
  const headerEl = chatEl?.querySelector("header");
  const stageEl = root.querySelector(".stage");
  const logEl = root.querySelector(".log");
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
  bindHaTree(root);
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
      openUsagePage();
      return;
    }
    const leavingUsage = wrap.classList.contains("page-usage");
    closeUsagePage();
    const id = route.sessionId;
    if (id === sessionId && !leavingUsage) return;
    if (id) openSession(id, true);
    else {
      restoreQueued();
      leaveChatStream();
      sessionId = "";
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
  let nextTurns = [];
  let sendQueued = null;
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

  function resizeComposer() {
    syncComposerField();
    if (!messageEl) return;
    const holdTop = chatEl.scrollTop;
    syncFieldLines();
    if (messageEl.localName === "textarea") {
      const minH = 36;
      const maxH = 160;
      messageEl.style.height = "auto";
      const scrollH = messageEl.scrollHeight;
      const h = Math.min(Math.max(scrollH, minH), maxH);
      messageEl.style.height = `${h}px`;
      // Avoid a stray in-field scrollbar until content actually exceeds the cap.
      const overflows = scrollH > maxH;
      messageEl.style.overflowY = overflows ? "auto" : "hidden";
      messageEl.classList.toggle("message-overflows", overflows);
    }
    syncSendButton();
    setComposerDisabled(".attach", pending.length >= MAX_ATTACH);
    const prompt = streaming ? t("placeholder_next") : t("placeholder");
    if (messageEl.localName === "ha-textarea") {
      if ("placeholder" in messageEl) messageEl.placeholder = prompt;
    } else {
      if ("placeholder" in messageEl) messageEl.placeholder = prompt;
      messageEl.setAttribute("placeholder", prompt);
    }
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
    const inner = ha
      ? messageEl.shadowRoot?.querySelector("wa-textarea")?.shadowRoot?.querySelector("textarea")
      : messageEl;
    if (!field || !actions || !inner || !field.clientWidth) return;
    // The inner textarea is current during the input event; ha-textarea's value catches up later.
    const value = String(inner.value ?? messageEl.value ?? "");
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
  async function apiFetch(url, options = {}, { raise = false } = {}) {
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
      return toolGlyphKind(last.dataset.tool && last.dataset.tool.toLowerCase() !== "mcp" ? last.dataset.tool : haChipLabel(last));
    }
    const label = String(bubble?.querySelector(".activity .label")?.textContent || "").trim();
    if (label && label === t("thinking")) return "think";
    if (WAIT_STATUS.test(label)) return "wait";
    return "work";
  }

  function activityGlyph(kind = "work") {
    if (haUi) return null;
    const glyph = document.createElement("span");
    glyph.className = "glyph";
    glyph.dataset.kind = kind;
    glyph.innerHTML = ACTIVITY_GLYPHS[kind];
    return glyph;
  }

  function fillActivitySlot(el, label) {
    const glyph = activityGlyph();
    if (glyph) el.replaceChildren(glyph, label);
    else el.replaceChildren(label);
  }

  // A tool icon stays at least this long, so quick tool calls in a row do not flicker.
  const GLYPH_HOLD_MS = 700;

  function syncActivityGlyph(bubble) {
    if (haUi) return;
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
    // Keep the status chip under tools and text so it never shifts the answer.
    if (el.parentElement !== bubble || bubble.lastElementChild !== el) {
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
    } else if (!haUi && !el.querySelector(".glyph")) {
      const glyph = activityGlyph();
      if (glyph) el.prepend(glyph);
    } else if (haUi) {
      el.querySelector(".glyph")?.remove();
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

  function setBanner(text, { alertType = "error" } = {}) {
    if (!bannerEl) return;
    const msg = String(text || "");
    if (bannerEl.localName === "ha-alert") {
      bannerEl.setAttribute("alert-type", alertType);
    }
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
    setBanner(text, { alertType: "error" });
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
    setBanner(text, { alertType: "error" });
    bannerEl.classList.add("hold", "connection");
  }

  function clearConnectionError() {
    if (!bannerEl?.classList.contains("connection")) return;
    bannerEl.classList.remove("hold", "connection");
    setBanner("");
  }

  function markNotSent(userBubble, restore) {
    const anchor = userBubble?.closest(".message-container") || userBubble;
    if (!anchor?.parentElement) return;
    const restored = Boolean(restore?.text || restore?.pending?.length) && !String(messageEl.value || "").trim() && !pending.length;
    if (restored) {
      messageEl.value = restore.text || "";
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
    if (chip.active !== undefined) chip.active = false;
  }

  function ensureToolsChrome(tools) {
    let list = tools.querySelector(".tools-list");
    if (list) return list;
    const summary = uiCreate("ha-assist-chip", "button");
    summary.type = "button";
    summary.className = "tools-summary";
    summary.hidden = true;
    summary.setAttribute("aria-expanded", "false");
    const chevron = document.createElement("ha-icon");
    chevron.className = "tools-chevron";
    chevron.setAttribute("icon", "mdi:chevron-right");
    if (summary.localName === "ha-assist-chip") {
      chevron.slot = "icon";
      summary.append(chevron);
    } else {
      const label = document.createElement("span");
      label.className = "tools-summary-label";
      summary.append(chevron, label);
    }
    summary.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      tools.classList.toggle("expanded");
      tools.dataset.userToggle = "1";
      syncToolsSummary(tools);
    });
    list = uiCreate("ha-chip-set", "div");
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
    const labelText = toolsSummaryLabel(chips, busy);
    const labelEl = summary.querySelector(".tools-summary-label");
    if (labelEl) labelEl.textContent = labelText;
    else haChipLabel(summary, labelText);
    if (!tools.dataset.userToggle) {
      tools.classList.remove("expanded");
    }
    const open = tools.classList.contains("expanded");
    summary.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function isPendingChip(el) {
    return el.classList.contains("busy") || Boolean(el.active) || /^calling\b/i.test(haChipLabel(el));
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
        if (label) haChipLabel(pending, label);
        settleChip(pending);
        syncToolsSummary(tools);
        syncActivityGlyph(tools.closest?.(".bubble"));
        return;
      }
    }
    const chip = uiCreate("ha-assist-chip", "span");
    chip.className = kind;
    if (name) chip.dataset.tool = name;
    if (callId) chip.dataset.callId = callId;
    if (chip.active !== undefined) chip.active = kind === "busy";
    if (!animate || reduceMotion || kind !== "busy") chip.style.animation = "none";
    haChipLabel(chip, label);
    list.appendChild(chip);
    syncToolsSummary(tools);
    syncActivityGlyph(tools.closest?.(".bubble"));
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
    const row = uiCreate("ha-chip-set", "div");
    row.className = "bubble-files";
    for (const file of files) {
      const chip = uiCreate("ha-assist-chip", "span");
      chip.className = "file-chip";
      haChipLabel(chip, file.name);
      row.appendChild(chip);
    }
    bubble.appendChild(row);
    return files;
  }

  function addBubble(role, content, events, opts = {}) {
    const empty = logEl.querySelector(".empty");
    if (empty) empty.remove();
    setWelcome(false, opts.animate !== false);
    const isError = (events || []).some((event) => event && event.type === "error");
    if (isError && role === "assistant") content = shownError(content);
    const assistWho = role === "user" ? "user" : "hass";
    let bubble;
    let mount;
    if (haUi) {
      const container = document.createElement("div");
      container.className = `message-container ${assistWho}`;
      bubble = document.createElement("div");
      bubble.className = `bubble message ${assistWho} ${role}`;
      if (isError) bubble.classList.add("error");
      container.appendChild(bubble);
      mount = container;
    } else {
      bubble = isError ? uiCreate("ha-alert", "ha-card", "div") : uiCreate("ha-card", "div");
      bubble.className = `bubble ${role}`;
      if (isError) {
        if (bubble.localName === "ha-alert") bubble.setAttribute("alert-type", "error");
        else bubble.classList.add("error");
      }
      mount = bubble;
    }
    if (opts.createdAt) bubble.dataset.createdAt = String(opts.createdAt);
    if (opts.animate === false || reduceMotion) bubble.classList.add("instant");
    const pics = addBubbleImages(bubble, events);
    const files = addBubbleFiles(bubble, events);
    const chips = (events || []).filter(
      (event) => event && event.type !== "image" && event.type !== "file" && event.type !== "error",
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
    } else if (content && !((pics.length || files.length) && isDefaultImageCaption(content))) {
      const text = uiCreate("ha-markdown", "div");
      text.className = "text";
      if (text.localName === "ha-markdown") {
        text.setAttribute("breaks", "");
        text.setAttribute("cache", "");
        text.breaks = true;
        text.cache = true;
        fillHaMarkdown(text, content);
      } else {
        text.textContent = content;
      }
      bubble.appendChild(text);
      bubble.classList.add("has-text");
    }
    const parent = opts.parent || logEl;
    parent.appendChild(mount);
    retargetHaLinks(bubble);
    if (!opts.parent) {
      syncCopyChat();
      if (opts.follow !== false) scrollChatToBottom(opts.smooth !== false);
    }
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
        ...[...bubble.querySelectorAll(".bubble-files .file-chip")].map((el) => haChipLabel(el).trim()),
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

  function speechLive() {
    return Boolean(
      speakStarted ||
        speakBusy ||
        speakPending.length > 0 ||
        speakInflight.length > 0 ||
        (replyObjectUrl && replyAudio && !replyAudio.ended),
    );
  }

  function syncCopyChat() {
    let row = logEl.querySelector(".chat-actions");
    const hasChat = Boolean(logEl.querySelector(".bubble.has-text, .bubble .bubble-files, .bubble .bubble-images"));
    const busy = streaming || Boolean(logEl.querySelector(".bubble.streaming"));
    const live = speechLive();
    const showSpeak = Boolean(voice.tts && (live || (Boolean(lastAssistantText()) && !busy)));
    const showCopy = hasChat && !busy;
    const showHistory = Boolean(turnHasHistory);
    if (!showCopy && !showSpeak && !showHistory) {
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
    const copyBtn = row.querySelector(".copy-chat");
    if (copyBtn) copyBtn.hidden = !showCopy;
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
        row.appendChild(speakBtn);
      }
      speakBtn.hidden = !showSpeak;
    } else if (speakBtn) {
      speakBtn.hidden = true;
    }
    let historyBtn = row.querySelector(".history-chat");
    if (!historyBtn) {
      historyBtn = document.createElement("ha-icon-button");
      historyBtn.className = "history-chat";
      historyBtn.type = "button";
      historyBtn.label = t("activity");
      const historyIcon = document.createElement("ha-icon");
      historyIcon.setAttribute("icon", "mdi:history");
      historyBtn.appendChild(historyIcon);
      historyBtn.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        await openHistory();
      });
      row.appendChild(historyBtn);
    }
    historyBtn.hidden = !turnHasHistory;
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
      const set = uiCreate("ha-chip-set", "div");
      set.className = "next-chips";
      nextTurns.forEach((turn, index) => {
        const chip = uiCreate("ha-input-chip", "div");
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
        bindHaTree(chip);
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
    messageEl.value = "";
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
      messageEl.value = pulled.text;
      pending = pulled.attachments;
    }
    renderThumbs();
    renderNext();
    resizeComposer();
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
      settleTools(live);
      setActivity(live, "");
      const text = String(live.querySelector(".text")?.content || live.querySelector(".text")?.textContent || "").trim();
      const tools = live.querySelector(".tools");
      if (!text && !tools?.children?.length) (live.closest(".message-container") || live).remove();
    }
    resizeComposer();
  }

  function abandonStream({ keepSpeech = false } = {}) {
    haltStream({ keepQueue: keepQueueOnHalt("send"), keepSpeech });
  }

  // Leaving a chat: its queued prompts were written for it and must not go out in the next one.
  // restoreQueued() has already moved the first one into an empty composer.
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
    sessionId = "";
    freshChat = true;
    goToSession("", true);
    selectSessionRow("");
    titleEl.textContent = t("new_chat");
    logEl.querySelector(".chat-gone")?.remove();
    const note = uiCreate("ha-alert", "p");
    note.classList.add("chat-gone");
    if (note.localName === "ha-alert") note.setAttribute("alert-type", "info");
    const restored = Boolean(restore?.text || restore?.pending?.length);
    note.textContent = t(restored ? "chat_deleted_resend" : "chat_deleted");
    logEl.appendChild(note);
    if (restored && !String(messageEl.value || "").trim() && !pending.length) {
      messageEl.value = restore.text || "";
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
    if (!agentPicker || !agentMenu || !agentLabel) return;
    const current = selectedAgent();
    const item = providerItems.find((row) => row.id === current);
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
        setBanner(noticeText, { alertType: "warning" });
      } else {
        setHint(noticeText);
        if (bannerEl.getAttribute("alert-type") === "warning" && !bannerEl.classList.contains("hold")) setBanner("");
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
      const input = uiCreate("ha-input", "ha-textfield", "input");
      input.className = "dialog-field";
      if (input.localName === "input") input.type = "text";
      else input.setAttribute("type", "text");
      input.value = value || "";
      input.maxLength = 80;
      if (input.label !== undefined) input.label = title;
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
    if (session.id === sessionId) startNewChat();
    await loadSessions();
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
    if (session.id === sessionId) {
      markSessionSelected(item, true);
      markSessionSelected(row, true);
    }
    item.addEventListener("click", () => {
      closeSessionMenu();
      closeNavIfOverlay();
      openSession(session.id);
    });
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

  async function loadSession(id, fromUrl = false) {
    if (id && id === sessionId && (streaming || liveStream)) {
      selectSessionRow(id);
      return;
    }
    const switching = id !== sessionId;
    if (switching) {
      restoreQueued();
      leaveChatStream();
    }
    watchGen += 1;
    if (!id) {
      routeGen += 1;
      sessionId = "";
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
    sessionId = id;
    freshChat = false;
    const listed = sessionsEl?.querySelector(`.session-row[data-session-id="${id}"]`);
    if (listed?.dataset.title) titleEl.textContent = displayTitle(listed.dataset.title);
    selectSessionRow(id);
    if (switching) logEl.replaceChildren();
    if (compact) localStorage.setItem("ai_workspace_session", id);
    if (!fromUrl) goToSession(id);
    const response = await apiFetch(`${API}/sessions/${id}`);
    if (gen !== routeGen) return;
    if (!response?.ok) {
      sessionId = "";
      titleEl.textContent = t("new_chat");
      showEmpty();
      goToSession("", true);
      return;
    }
    const session = await response.json();
    setChatChoice(session.provider, session.model);
    paintSession(session, gen);
    selectSessionRow(id);
    if (session.pending) watchPending(id);
    refreshChatUsage();
  }

  function paintSession(session, gen = routeGen) {
    clearMicHelp();
    titleEl.textContent = displayTitle(session.title);
    logEl.replaceChildren();
    const messages = session.messages || [];
    turnHasHistory = Boolean(session.has_activity);
    if (!messages.length) {
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
    logEl.appendChild(frag);
    finish();
    if (!tailAt) return;
    requestAnimationFrame(() => {
      if (gen !== routeGen) return;
      const head = document.createDocumentFragment();
      paintRange(0, tailAt, head);
      const first = logEl.querySelector(".message-container, .bubble");
      if (first) logEl.insertBefore(head, first);
      else logEl.prepend(head);
      settleTools(logEl);
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
        } else if (name === "status") {
          setActivity(bubble, data.text);
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
          setActivity(live, "");
        }
        // Nothing runs any more, so no tool chip can still be busy. Without this a reply
        // followed after a dropped connection kept "Calling N tools" and its shimmer.
        settleTools(logEl);
      }
      streaming = false;
      resizeComposer();
      syncCopyChat();
      bumpSession(id, session.title, session.pinned);
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
        const chip = uiCreate("ha-input-chip", "div");
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
        messageEl.value = parts.join(" ").replace(/\s+/g, " ").trim();
        if (interim) messageEl.value += " ";
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
      replyAudio.pause();
      replyAudio.currentTime = 0;
    } catch (_err) {
      /* WebView may still block until a later tap */
    }
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
    messageEl.value = [base, said].filter(Boolean).join(" ");
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
    const btn = logEl.querySelector(".speak-chat");
    if (!btn) return;
    syncCopyChat();
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
    if (replyAudio && !replyAudio.paused && !replyAudio.ended) replyAudio.pause();
    if (replyObjectUrl) {
      URL.revokeObjectURL(replyObjectUrl);
      replyObjectUrl = "";
    }
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
    if (!voice.speak || !delta) return;
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

  async function speakReply(text, fromUser = false) {
    if (!voice.tts || !String(text || "").trim()) return;
    haltSpeech();
    speakFromUser = fromUser;
    if (fromUser) await unlockOutput();
    speakFlush = true;
    const taken = takeSpeech(String(text), false, true, { heavy: voice.ttsHeavy });
    for (const piece of taken.pieces) queueSpeech(piece);
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
      const response = await apiFetch(`${API}/ui`);
      if (response?.ok) {
        const body = await response.json();
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
    if (turnStopDone) await turnStopDone;
    let keepComposer = false;
    let text;
    let attachments;
    if (sendQueued) {
      const turn = sendQueued;
      sendQueued = null;
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
        text = turn.text;
        attachments = turn.attachments.slice();
        renderNext();
        keepComposer = true;
      }
    }
    const images = attachments.filter((item) => item.kind === "image");
    const files = attachments.filter((item) => item.kind === "file");
    if (!text && !attachments.length) return;
    await sessionLoad;
    if (!sessionId) {
      const known = knownSessionId();
      if (known) await openSession(known, true);
    }
    abandonStream({ keepSpeech: keepComposer });
    const token = streamToken;
    const abort = new AbortController();
    streamAbort = abort;
    stopSpeech();
    const speechPlaying = Boolean(
      speakBusy || (replyAudio && !replyAudio.paused && !replyAudio.ended && replyObjectUrl),
    );
    if (!keepComposer || !speechPlaying) unlockOutput();
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
      messageEl.value = "";
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
    let chatId = "";
    liveStream = true;
    try {
      if (token !== streamToken) return;
      if (!sessionId) {
        const created = await createSession();
        if (token !== streamToken || !created) return;
        titleEl.textContent = promptTitle(text) || attachments[0]?.name || t("new_chat");
        bumpSession(sessionId, titleEl.textContent);
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
      if (response?.status === 404) {
        // Deleted, most likely on another device. Hand the message back for a new chat.
        for (const bubble of [userBubble, assistant]) (bubble?.closest(".message-container") || bubble)?.remove();
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
        } else if (name === "status") {
          setStatus(data.text);
          drainSpeech(false, true);
        } else if (name === "error" && data.connection && !streamFull) {
          // Nothing was sent: the header says why, the prompt gets the message back.
          drainSpeech(true);
          streamFinal = true;
          sawDone = true;
          streaming = false;
          showConnectionError(shownError(data.message) || t("error"));
          (assistant.closest(".message-container") || assistant).remove();
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
          setActivity(assistant, "");
          resizeComposer();
          bumpSession(chatId, titleEl.textContent);
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
      window.setTimeout(() => {
        if (token === streamToken && sessionId === chatId) refreshTurnHistory(turnSince);
      }, 500);
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
    restoreQueued();
    leaveChatStream();
    clearMicHelp();
    routeGen += 1;
    watchGen += 1;
    sessionId = "";
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
    item.className = "history-row";
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
    messageEl.value = restorePrompt(row);
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

  function usageLine(summary) {
    if (!summary) return "";
    const bits = [`${tokenLabel(summary.total_tokens || 0)} ${t("usage_tokens")}`];
    const cached = cachedTokens(summary);
    if (cached) bits.push(`${tokenLabel(cached)} ${t("usage_cached")}`);
    if (summary.cost_usd != null) bits.push(money(summary.cost_usd));
    else if (summary.missing_cost) bits.push(t("usage_unknown_cost"));
    if (summary.turns) bits.push(`${summary.turns} ${turnWord(summary.turns)}`);
    return bits.join(" · ");
  }

  function applyTurnUsage(data) {
    if (!data || !usageTracking) return;
    if (chatUsageEl && showChatUsage) {
      const cost = data.cost_usd == null ? t("usage_unknown_cost") : money(data.cost_usd);
      chatUsageEl.hidden = false;
      chatUsageEl.textContent = `${t("usage_last")}: ${tokenLabel(data.total_tokens || 0)} · ${cost}`;
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
      const summary = body.session;
      if (!summary || !summary.turns) {
        chatUsageEl.hidden = true;
        return;
      }
      chatUsageEl.hidden = false;
      chatUsageEl.textContent = usageLine(summary);
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
    if (body.tts?.today?.turns || body.tts?.all?.turns) {
      frag.appendChild(metricCard(t("usage_tts"), body.tts.today, "tts"));
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
    if (wrap.classList.contains("usage-open")) {
      closeUsageOverlay();
      return;
    }
    if (root.querySelector("ha-dialog[open]")) return;
    if (root.querySelector(".session-more[aria-expanded='true'], .agent-trigger[aria-expanded='true']")) return;
    if (wrap.classList.contains("nav-open")) setNavOpen(false);
  });
  listen(mqNarrow, "change", () => setNarrow(options.narrow));

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
    if (sessionId && chatVisible()) watchPending(sessionId);
    if (bannerEl && !bannerEl.hidden) loadProviders();
  });
  listen(window, "resize", () => {
    if (messageEl) resizeComposer();
  });
  listen(window, "pageshow", () => {
    if (sessionId && chatVisible()) watchPending(sessionId);
  });

  loadProviders();
  loadDictate();
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
  resizeComposer();
  const linkWatch = new MutationObserver(() => retargetHaLinks(logEl));
  linkWatch.observe(logEl, { subtree: true, childList: true, attributes: true, attributeFilter: ["href", "target"] });
  teardown.push(() => linkWatch.disconnect());
  function resume() {
    loadDictate();
    if (sessionId) watchPending(sessionId);
  }

  function destroy() {
    haltStream({ keepQueue: keepQueueOnHalt("destroy") });
    stopSpeech();
    watchGen += 1;
    routeGen += 1;
    for (const undo of teardown.splice(0)) undo();
    if (followRaf) cancelAnimationFrame(followRaf);
    if (keyboardRaf) cancelAnimationFrame(keyboardRaf);
    replyAudio?.pause();
    replyAudio = null;
    root.replaceChildren();
  }

  return { openSession, applyRoute, setNarrow, toggleNav, startNewChat, loadDictate, resume, destroy, haltSpeech };
}
