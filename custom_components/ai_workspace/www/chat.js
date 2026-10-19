const CACHE = new URL(import.meta.url).search;
const { stringsFor } = await import(`./i18n.js${CACHE}`);
const { takeSpeech, speechPlain } = await import(`./speech.js${CACHE}`);

const API = "/api/ai_workspace";

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

function fillHaMarkdown(el, body) {
  const text = String(body || "");
  el.content = text;
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
  "ha-input-chip",
  "ha-list-item-button",
  "ha-markdown",
  "ha-dialog",
  "ha-dialog-footer",
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
  return `/config/entities/entity/${entityId}`;
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

function rememberUniqueName(map, name, path) {
  const text = String(name || "").trim();
  if (text.length < 3) return;
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
    rememberUniqueName(nameToPath, device.name_by_user || device.name, `/config/devices/device/${id}`);
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
  const { names, ids, paths } = mentions ? haLinkCatalog() : {};
  for (const re of [names, ids]) {
    if (!re) continue;
    re.lastIndex = 0;
    text = text.replace(re, (_whole, lead, matched) => `${lead}${hold(`[${matched}](${paths.get(matched)})`)}`);
  }
  return text.replace(/\u0000HA(\d+)\u0000/g, (_m, index) => held[Number(index)] || "");
}

function safeImageUrl(raw) {
  const value = String(raw || "").trim().replace(/^<|>$/g, "");
  if (/^data:image\//i.test(value)) return true;
  if (value.startsWith("/") && !value.startsWith("//")) return true;
  try {
    return new URL(value).origin === window.location.origin;
  } catch (_err) {
    return false;
  }
}

function stripRemoteImages(text) {
  return String(text || "")
    .replace(/!\[([^\]]*)\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+"[^"]*")?\s*\)/g, (whole, alt, url) => {
      if (safeImageUrl(url)) return whole;
      const target = url.replace(/^<|>$/g, "");
      return `[${alt || target}](${target})`;
    })
    .replace(/<img\b[^>]*>/gi, (tag) => {
      const src = /\bsrc\s*=\s*["']?([^"'\s>]+)/i.exec(tag)?.[1] || "";
      return safeImageUrl(src) ? tag : "";
    });
}

export async function mountAiWorkspace(root, options = {}) {
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
  const nextRemoveMarkup = haUi
    ? `<ha-icon-button class="next-remove" label="${t("queued_remove")}"><ha-icon icon="mdi:close"></ha-icon></ha-icon-button>`
    : `<button type="button" class="next-remove"></button>`;
  const fileInputMarkup =
    `<input class="file-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif,.yaml,.yml,.json,.txt,.md,.csv,.xml,.toml,.html,.css,.js,.ts,.py,.log,.cfg,.ini,.conf" multiple hidden>`;
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
                <ha-input id="message-input" class="message" label="${htmlAttr(t("message"))}" placeholder="${htmlAttr(t("placeholder"))}">
                  <div slot="end">
                    ${attachBtnMarkup}
                    ${micBtnMarkup}
                    ${sendMarkup}
                  </div>
                </ha-input>
              </div>`;
  const agentTriggerMarkup = haUi
    ? `<ha-button type="button" class="agent-trigger" slot="trigger" appearance="plain" size="s" aria-haspopup="menu" aria-expanded="false" aria-label="${t("agent")}"><span class="agent-trigger-label"></span><ha-icon slot="end" icon="mdi:chevron-down"></ha-icon></ha-button>`
    : `<button type="button" class="agent-trigger" slot="trigger" aria-haspopup="menu" aria-expanded="false" aria-label="${t("agent")}"><span class="agent-trigger-label"></span><ha-icon icon="mdi:chevron-down"></ha-icon></button>`;
  root.innerHTML = `
    ${themeCss}
    <div class="${wrapClass}">
      <button type="button" class="nav-scrim" hidden aria-label="${t("close")}"></button>
      <aside>
        <div class="nav-head">
          <div class="nav-toolbar">
            <div class="nav-tools">
              <ha-icon-button class="history-open" label="${t("activity")}">
                <ha-icon icon="mdi:history"></ha-icon>
              </ha-icon-button>
              <ha-icon-button class="usage-open" label="${t("usage")}">
                <ha-icon icon="mdi:chart-bar"></ha-icon>
              </ha-icon-button>
            </div>
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
        </div>
        <div class="sessions" role="list"></div>
      </aside>
      <section class="chat welcome">
        <header>
          <div class="header-row">
            <ha-icon-button class="nav-toggle chat-nav-toggle" label="${t("show_chats")}">
              <ha-icon icon="mdi:forum-outline"></ha-icon>
            </ha-icon-button>
            ${compact ? "" : `<ha-icon-button class="history-open header-history" label="${t("activity")}">
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
              <div class="next-row" hidden>
                <p class="next-copy"></p>
                ${nextRemoveMarkup}
              </div>
              <div class="attach-row" hidden></div>
              ${haComposerInputMarkup}
              <div class="agent-picker" hidden>
                <ha-dropdown class="agent-menu" placement="top-start">
                  ${agentTriggerMarkup}
                </ha-dropdown>
              </div>
            </${composerTag}>` : `<${composerTag} class="composer-box">
              <div class="next-row" hidden>
                <p class="next-copy"></p>
                ${nextRemoveMarkup}
              </div>
              <div class="attach-row" hidden></div>
              ${standardComposerRowMarkup}
            </${composerTag}>
            <div class="agent-picker" hidden>
              <ha-dropdown class="agent-menu" placement="top-start">
                ${agentTriggerMarkup}
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
          <span>${t("usage")}</span>
          <div class="usage-bar-actions">
            <ha-icon-button class="usage-close" label="${t("usage_back")}">
              <ha-icon icon="mdi:close"></ha-icon>
            </ha-icon-button>
          </div>
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
  const scrim = root.querySelector(".nav-scrim");
  const chatEl = root.querySelector(".chat");
  const logEl = root.querySelector(".log");
  const sessionsEl = root.querySelector(".sessions");
  const titleEl = root.querySelector(".title");
  const bannerEl = root.querySelector(".banner");
  const form = root.querySelector(".composer");
  const scrollBottomBtn = root.querySelector(".scroll-bottom");
  let messageEl = root.querySelector("#ai-message") || root.querySelector("#message-input");
  function syncComposerField() {
    const haField = root.querySelector("#message-input");
    if (haUi && haField?.localName === "ha-input" && haHas("ha-input")) messageEl = haField;
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
  const agentTrigger = root.querySelector(".agent-trigger");
  const agentLabel = root.querySelector(".agent-trigger-label");
  const agentMenu = root.querySelector(".agent-menu");
  const fileInput = form.querySelector(".file-input");
  const attachRow = root.querySelector(".attach-row");
  const nextRow = root.querySelector(".next-row");
  const nextCopy = root.querySelector(".next-copy");
  const nextRemove = root.querySelector(".next-remove");
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
    customElements.whenDefined("ha-input").then(() => {
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
    const route = workspaceRoute();
    if (route.view === "usage") {
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
      abandonStream();
      sessionId = "";
      freshChat = true;
      titleEl.textContent = t("new_chat");
      showEmpty();
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
  let holdFollow = false;
  let jumping = false;
  let jumpTimer = 0;
  let lastScrollTop = 0;
  let followRaf = 0;
  let followLast = 0;
  let motionTimer = 0;
  let userScrollAt = 0;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function resizeComposer() {
    syncComposerField();
    if (!messageEl) return;
    const holdTop = chatEl.scrollTop;
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
    const hasDraft = Boolean(String(messageEl.value || "").trim() || pending.length);
    setComposerDisabled(".send", !hasDraft);
    setComposerDisabled(".attach", pending.length >= MAX_ATTACH);
    const prompt = streaming ? t("placeholder_next") : t("placeholder");
    if (messageEl.localName === "ha-input") {
      if ("placeholder" in messageEl) messageEl.placeholder = prompt;
    } else {
      if ("placeholder" in messageEl) messageEl.placeholder = prompt;
      messageEl.setAttribute("placeholder", prompt);
    }
    chatEl.scrollTop = holdTop;
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
    wrap.classList.remove("keyboard-open");
    wrap.style.height = "";
    wrap.style.removeProperty("--ai-keyboard-inset");
  }

  function syncKeyboardInset() {
    if (keepComposerFocus()) return;
    if (keyboardRaf) return;
    keyboardRaf = requestAnimationFrame(applyKeyboardInset);
  }

  function applyKeyboardInset() {
    keyboardRaf = 0;
    if (keepComposerFocus()) return;
    const vv = window.visualViewport;
    // Overlay keyboards shrink visualViewport.height. Ignore offsetTop so IME
    // pan does not chase the composer (that loop is the rubber-band).
    const next = vv ? Math.max(0, Math.round(window.innerHeight - vv.height)) : 0;
    const open = composerFocused() && next > 80;
    if (!open) {
      if (keyboardOpen) clearKeyboardLock();
      return;
    }
    if (keyboardOpen && Math.abs(next - keyboardInset) < 8) return;
    const opened = !keyboardOpen;
    keyboardOpen = true;
    keyboardInset = next;
    wrap.style.setProperty("--ai-keyboard-inset", `${next}px`);
    if (opened) {
      if (followRaf) {
        cancelAnimationFrame(followRaf);
        followRaf = 0;
      }
      wrap.classList.add("keyboard-open");
      if (pinBottom && !holdFollow) {
        chatEl.scrollTop = Math.max(0, chatEl.scrollHeight - chatEl.clientHeight);
        lastScrollTop = chatEl.scrollTop;
      }
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

  function prettyStatus(text) {
    const raw = String(text || "").trim();
    if (!raw || /^done\.?$/i.test(raw)) return "";
    if (/^no mcp servers configured\.?$/i.test(raw)) return "";
    if (/^mcp:\s/i.test(raw)) return "";
    if (/^running$/i.test(raw)) return t("working");
    if (/^working\.{0,3}$/i.test(raw)) return t("working");
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

  function lastAssistantBubble() {
    const live = logEl.querySelector(".bubble.assistant.streaming");
    if (live) return live;
    const bubbles = logEl.querySelectorAll(".bubble.assistant");
    return bubbles[bubbles.length - 1] || null;
  }

  function setStatus(text) {
    const bubble = lastAssistantBubble();
    if (!bubble) return;
    const busyChip = bubble.querySelector(".tools span.busy");
    if (busyChip && /^running$/i.test(String(text || "").trim())) {
      setActivity(bubble, "");
      return;
    }
    setActivity(bubble, text);
  }

  function rewriteAssistantLinks(content, mentions = true) {
    let text = stripRemoteImages(content);
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

  function showNotice(text) {
    if (!text) return;
    clearMicHelp();
    setBanner(text, { alertType: "error" });
    if (noticeTimer) clearTimeout(noticeTimer);
    noticeTimer = window.setTimeout(() => {
      if (bannerEl && bannerEl.textContent === text) setBanner("");
    }, 6000);
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
    if (chip.active !== undefined) chip.active = false;
    if (text) haChipLabel(chip, chipLabel(text));
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
    const chip = uiCreate("ha-assist-chip", "span");
    chip.className = kind;
    if (name) chip.dataset.tool = name;
    if (callId) chip.dataset.callId = callId;
    if (chip.active !== undefined) chip.active = kind === "busy";
    if (!animate || reduceMotion || kind !== "busy") chip.style.animation = "none";
    haChipLabel(chip, label);
    list.appendChild(chip);
    syncToolsSummary(tools);
  }

  function settleTools(root) {
    root?.querySelectorAll(".tools .busy").forEach((chip) => {
      const name = chip.dataset.tool || haChipLabel(chip);
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
    logEl.appendChild(mount);
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

  function syncCopyChat() {
    let row = logEl.querySelector(".chat-actions");
    const hasChat = Boolean(logEl.querySelector(".bubble.has-text, .bubble .bubble-files, .bubble .bubble-images"));
    const busy = streaming || Boolean(logEl.querySelector(".bubble.streaming"));
    const speechActive =
      speakStarted ||
      speakBusy ||
      speakPending.length > 0 ||
      speakInflight.length > 0 ||
      Boolean(replyAudio && !replyAudio.ended);
    const showSpeak = Boolean(voice.tts && ((hasChat && !busy) || speechActive));
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
    const node = root.getRootNode?.();
    node?.querySelector?.(".drawer")?.classList.remove("open");
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
      nextRemove.label = t("queued_remove");
      nextRemove.setAttribute("label", t("queued_remove"));
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

  function restoreQueued() {
    if (!nextTurn) return;
    const turn = nextTurn;
    nextTurn = null;
    if (!messageEl.value.trim()) messageEl.value = turn.text;
    pending = [...pending, ...turn.attachments].slice(0, MAX_ATTACH);
    renderThumbs();
    renderNext();
    resizeComposer();
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
    streamPainted = "";
    streamNode = null;
    streamFinal = false;
    haltSpeech();
    const waiters = streamWaiters;
    streamWaiters = [];
    waiters.forEach((fn) => fn());
    streaming = false;
    liveStream = false;
    nextTurn = null;
    renderNext();
    resizeComposer();
  }

  function writeStreamVisible(force = false) {
    if (!streamNode) return false;
    const done = streamFinal && !streamBuf;
    const visible = rewriteAssistantLinks(stableStreamMarkdown(streamFull, done), done);
    if (visible === streamPainted) return false;
    streamPainted = visible;
    streamNode.content = visible;
    streamNode.hidden = !visible;
    styleMarkdownTables(streamNode);
    const bubble = streamNode.closest(".bubble");
    bubble?.classList.toggle("has-text", Boolean(visible));
    if (visible && bubble && !bubble.querySelector(".tools span.busy")) setActivity(bubble, "");
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
  let agentId = "";
  let voice = { dictate: true, stt: "browser", speak: false, tts: false, ttsHeavy: false, ttsNatural: true };
  let turnHasHistory = false;

  function selectedAgent() {
    return agentId || defaultProvider;
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

  async function loadProviders() {
    const response = await apiFetch(`${API}/providers`);
    if (!response?.ok) return;
    const items = await response.json();
    const ready = agentChoices(items);
    const previous = agentId || localStorage.getItem("ai_workspace_agent") || "";
    const pick = pickAgent(items, previous);
    agentId = pick?.id || "";
    if (agentPicker && agentMenu && agentLabel) {
      agentPicker.hidden = ready.length < 2;
      agentLabel.textContent = pick?.label || "";
      agentMenu.querySelectorAll("ha-dropdown-item").forEach((node) => node.remove());
      for (const item of items) {
        const option = document.createElement("ha-dropdown-item");
        option.value = item.id;
        option.disabled = !item.available;
        option.selected = item.id === agentId;
        if (!item.available) option.setAttribute("disabled", "");
        if (item.id === agentId) option.setAttribute("selected", "");
        option.textContent = item.label;
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

  function closeSessionMenu() {
    root.querySelectorAll("ha-dropdown.session-menu").forEach((menu) => {
      menu.open = false;
    });
    root.querySelectorAll(".session-more[aria-expanded='true']").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });
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
    const title = row?.dataset.title;
    if (!title || title === session.title) return session;
    return { ...session, title };
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
    const labels = [...sessionsEl.querySelectorAll(".chats-label")];
    const anchor = stayPinned ? labels[0] : labels[labels.length - 1];
    if (anchor) anchor.after(row);
    else sessionsEl.prepend(row);
    selectSessionRow(sessionId);
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
    const menu = document.createElement("ha-dropdown");
    menu.className = "session-menu";
    menu.placement = "bottom-end";
    const more = document.createElement("ha-icon-button");
    more.className = "session-more";
    more.slot = "trigger";
    more.label = t("chat_actions");
    more.setAttribute("aria-haspopup", "menu");
    more.setAttribute("aria-expanded", "false");
    const dots = document.createElement("ha-icon");
    dots.setAttribute("icon", "mdi:dots-vertical");
    more.appendChild(dots);
    more.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      event.stopPropagation();
      more.click();
    });
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
    item.append(menu);
    row.append(item);
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
    if (!created?.ok) throw new Error(await errorText(created));
    const session = await created.json();
    if (mark !== streamToken) {
      apiFetch(`${API}/sessions/${session.id}`, { method: "DELETE" });
      return null;
    }
    sessionId = session.id;
    freshChat = false;
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
    if (id !== sessionId) {
      restoreQueued();
      abandonStream();
    }
    watchGen += 1;
    if (!id) {
      routeGen += 1;
      sessionId = "";
      freshChat = true;
      titleEl.textContent = t("new_chat");
      showEmpty();
      if (!fromUrl) goToSession("");
      selectSessionRow("");
      refreshChatUsage();
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
      return;
    }
    sessionId = id;
    freshChat = false;
    if (compact) localStorage.setItem("ai_workspace_session", id);
    if (!fromUrl) goToSession(id);
    const session = await response.json();
    paintSession(session);
    if (!sessionsEl?.querySelector(".session-row")) await loadSessions();
    selectSessionRow(id);
    if (session.pending) watchPending(id);
    refreshChatUsage();
  }

  function paintSession(session) {
    clearMicHelp();
    titleEl.textContent = displayTitle(session.title);
    logEl.replaceChildren();
    const messages = session.messages || [];
    if (!messages.length) showEmpty();
    else setWelcome(false, false);
    for (const message of messages) {
      addBubble(message.role, message.content, message.events, {
        animate: false,
        follow: false,
        createdAt: message.created_at,
      });
    }
    settleTools(logEl);
    // Any Change History row for this chat — not only the last user turn.
    refreshTurnHistory();
    clipToBottom();
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
    // Only auto-speak when we were waiting on a background reply — not when polling
    // an already-finished chat (overlay resume, visibility, etc.).
    let sawPending = Boolean(logEl.querySelector(".bubble.assistant.streaming"));
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
        sawPending = true;
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
      bumpSession(id, session.title, session.pinned);
      if (sawPending && voice.speak && voice.tts && !speakStarted) {
        const leftover = lastAssistantText();
        if (leftover) {
          speakHeld = leftover;
          speakRaw = leftover;
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

  form.querySelectorAll(".file-input").forEach((input) => {
    input.addEventListener("change", async () => {
      await addFiles([...input.files]);
      input.value = "";
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
    if (files.length) await addFiles(files);
  });
  form.addEventListener("paste", async (event) => {
    if (!fromComposerField(event)) return;
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
    agentId = id;
    localStorage.setItem("ai_workspace_agent", agentId);
    defaultProvider = agentId;
    const label = picked.textContent.replace(/\s+/g, " ").trim();
    if (agentLabel && label) agentLabel.textContent = label;
    agentMenu.querySelectorAll("ha-dropdown-item").forEach((other) => {
      const on = other.value === agentId;
      other.selected = on;
      other.toggleAttribute("selected", on);
    });
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
    let stream = null;
    let ctx = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
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
    speakFromUser = false;
    speakFlush = false;
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

  function drainSpeech(flush) {
    if (flush) speakFlush = true;
    const taken = takeSpeech(speakHeld, speakStarted, flush, { heavy: voice.ttsHeavy });
    speakHeld = taken.rest;
    for (const piece of taken.pieces) {
      speakStarted = true;
      queueSpeech(piece);
    }
    if (taken.pieces.length) syncCopyChat();
    if (flush) fillSpeakAhead();
  }

  function feedSpeech(delta) {
    if (!voice.speak || !delta) return;
    speakRaw += delta;
    speakHeld += delta;
    drainSpeech(false);
  }

  function syncSpeechTo(full) {
    if (!voice.speak || !full || !full.startsWith(speakRaw)) return;
    const extra = full.slice(speakRaw.length);
    if (extra) feedSpeech(extra);
  }

  function queueSpeech(text) {
    const clean = String(text || "").trim();
    if (!clean) return;
    speakPending.push(clean);
    fillSpeakAhead();
    kickSpeak();
  }

  function pendingChars() {
    return speakPending.reduce((sum, item) => sum + plainForTts(item).length, 0);
  }

  function takePendingClip() {
    let clip = "";
    while (speakPending.length) {
      const next = speakPending[0];
      const combined = clip ? `${clip}\n${next}` : next;
      if (clip && plainForTts(combined).length > 560) break;
      speakPending.shift();
      clip = combined;
      const size = plainForTts(clip).length;
      if (size < 280) continue;
      if (!speakFlush) break;
      if (!speakPending.length) break;
      if (plainForTts(`${clip}\n${speakPending[0]}`).length > 560) break;
    }
    return clip.trim();
  }

  function fillSpeakAhead() {
    while (speakInflight.length < 2 && speakPending.length) {
      if (voice.ttsHeavy) {
        if (!speakInflight.length) {
          speakInflight.push(fetchSpeech(speakPending.shift(), speakGen));
          continue;
        }
        if (!speakFlush && pendingChars() < 280) break;
        const text = takePendingClip();
        if (!text) break;
        speakInflight.push(fetchSpeech(text, speakGen));
        continue;
      }
      const text = speakPending.shift();
      speakInflight.push(fetchSpeech(text, speakGen));
    }
  }

  function plainForTts(text) {
    return speechPlain(text, { natural: voice.ttsNatural !== false });
  }

  async function fetchSpeech(text, gen) {
    const plain = plainForTts(text);
    if (!plain) return null;
    const ac = new AbortController();
    const timer = window.setTimeout(() => ac.abort(), 20000);
    try {
      const response = await apiFetch(`${API}/tts`, {
        method: "POST",
        body: JSON.stringify({ text: plain, language: speechLanguage(), session_id: sessionId || "" }),
        signal: ac.signal,
      });
      if (gen !== speakGen || !response?.ok) return null;
      const blob = await response.blob();
      if (gen !== speakGen || !blob || blob.size < 32) return null;
      return blob;
    } catch (_err) {
      return null;
    } finally {
      window.clearTimeout(timer);
    }
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
      const done = () => {
        replyAudio.removeEventListener("ended", done);
        if (speakRelease === done) speakRelease = null;
        resolve();
      };
      speakRelease = done;
      replyAudio.addEventListener("ended", done);
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
    let text = messageEl.value.trim();
    let attachments = pending.slice();
    if (streaming) {
      if (!text && !attachments.length) return;
      clipToBottom();
      queueTurn(text, attachments);
      stickToBottom();
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
    await sessionLoad;
    if (!sessionId) {
      const known = knownSessionId();
      if (known) await openSession(known, true);
    }
    abandonStream();
    const token = streamToken;
    const abort = new AbortController();
    streamAbort = abort;
    stopSpeech();
    unlockOutput();
    if (keepComposerFocus()) messageEl.focus();
    else hideKeyboard();
    streaming = true;
    syncCopyChat();
    turnHasHistory = false;
    const turnSince = new Date().toISOString();
    watchGen += 1;
    clearKeyboardLock();
    resetOuterScroll();
    setComposerDisabled(".send", true);
    pending = [];
    renderThumbs();
    messageEl.value = "";
    resizeComposer();
    setWelcome(false);
    clipToBottom();
    addBubble("user", text, [
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
        });
      let response = await apiFetch(
        `${API}/sessions/${chatId}/chat`,
        { method: "POST", body: payload, signal: abort.signal },
        { raise: true },
      );
      if (token !== streamToken) return;
      if (response?.status === 404) {
        const node = assistant.querySelector(".text");
        node.content = await errorText(response);
        node.hidden = !node.content;
        assistant.classList.add("error", "has-text");
        setActivity(assistant, "");
        return;
      }
      if (!response?.ok || !response.body) {
        const node = assistant.querySelector(".text");
        node.content = await errorText(response);
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
          addChip(tools, data, true);
          if (assistant.querySelector(".tools span.busy")) setActivity(assistant, "");
        } else if (name === "status") {
          setStatus(data.text);
        } else if (name === "error") {
          drainSpeech(true);
          streamFinal = true;
          revealAllNow();
          assistant.classList.add("error");
          const textNode = assistant.querySelector(".text");
          if (!streamFull) {
            textNode.content = data.message || t("error");
            textNode.hidden = !textNode.content;
            assistant.classList.add("has-text");
          }
          settleTools(assistant);
          setActivity(assistant, "");
        } else if (name === "done") {
          sawDone = true;
          streamFinal = true;
          streamNode = streamNode || assistant.querySelector(".text");
          if (data.answer) {
            queueStreamAnswer(data.answer);
            syncSpeechTo(data.answer);
          }
          startStreamPump();
          drainSpeech(true);
          if (voice.speak && !speakStarted) {
            const leftover = String(data.answer || lastAssistantText() || "").trim();
            if (leftover) {
              speakHeld = leftover;
              speakRaw = leftover;
              drainSpeech(true);
            }
          }
          settleTools(assistant);
          setActivity(assistant, "");
          streaming = false;
          assistant.classList.remove("streaming");
          resizeComposer();
          bumpSession(chatId, titleEl.textContent);
          waitForStream().then(() => {
            if (token === streamToken && sessionId === chatId) {
              syncCopyChat();
              flushNext();
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
      window.setTimeout(() => {
        if (token === streamToken && sessionId === chatId) refreshTurnHistory(turnSince);
      }, 500);
      if (followUp && sessionId === chatId && nextTurn) {
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
    if (!composerFocused()) return;
    const vv = window.visualViewport;
    const next = vv ? Math.max(0, Math.round(window.innerHeight - vv.height)) : 0;
    if (Math.abs(next - keyboardInset) < 24) return;
    syncKeyboardInset();
  });
  function fromComposerField(event) {
    for (const node of event.composedPath?.() || [event.target]) {
      if (node?.id === "ai-message" || node?.id === "message-input") return true;
      if (node?.localName === "ha-input") return true;
    }
    return false;
  }
  form.addEventListener("input", (event) => {
    if (!fromComposerField(event)) return;
    if (!nearBottom()) releaseFollow();
    holdChatScroll(resizeComposer);
  });
  form.addEventListener("keydown", (event) => {
    if (!fromComposerField(event)) return;
    if (event.key !== "Enter" || event.shiftKey) return;
    // Phones insert a line break. The send button is the only way to submit.
    if (window.matchMedia("(pointer: coarse)").matches) return;
    event.preventDefault();
    form.requestSubmit();
  });
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
  nextRemove?.addEventListener("click", (event) => {
    event.preventDefault();
    nextTurn = null;
    renderNext();
    resizeComposer();
    if (keepComposerFocus()) messageEl.focus({ preventScroll: true });
  });

  function startNewChat() {
    restoreQueued();
    abandonStream();
    clearMicHelp();
    routeGen += 1;
    watchGen += 1;
    sessionId = "";
    freshChat = true;
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
  let usageSince = "";
  let usageUntil = "";

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
        closeHistory();
        messageEl.value = restorePrompt(row);
        form.requestSubmit();
      });
      item.appendChild(button);
      return item;
    }
    if (!row.can_rollback) return item;
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
        return;
      }
      await loadHistory();
    });
    item.appendChild(button);
    return item;
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

  function usageLine(summary) {
    if (!summary) return "";
    const bits = [`${tokenLabel(summary.total_tokens || 0)} ${t("usage_tokens")}`];
    if (summary.cost_usd != null) bits.push(money(summary.cost_usd));
    else if (summary.missing_cost) bits.push(t("usage_unknown_cost"));
    if (summary.turns) bits.push(`${summary.turns} ${t("usage_turns")}`);
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
      meta.textContent = `${tokenLabel(summary?.total_tokens || 0)} ${t("usage_tokens")} · ${summary?.turns || 0} ${t("usage_turns")}`;
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
    usageRangeEl.replaceChildren();
    for (const key of ["today", "month", "all"]) {
      const btn = document.createElement(haUi ? "ha-button" : "button");
      btn.className = "usage-range-btn";
      if (haUi) {
        btn.setAttribute("size", "s");
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
  }

  function fillUsageSelect(select, items, current) {
    if (!select) return;
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = t("usage_filter_all");
    select.appendChild(all);
    for (const item of items) {
      const opt = document.createElement("option");
      opt.value = item.id || item;
      opt.textContent = item.title || item;
      select.appendChild(opt);
    }
    if (current && ![...select.options].some((opt) => opt.value === current)) {
      const extra = document.createElement("option");
      extra.value = current;
      extra.textContent = current;
      select.appendChild(extra);
    }
    select.value = current || "";
  }

  function renderUsageFilters(body) {
    if (!usageFiltersEl) return;
    const filters = body?.filters || {};
    if (!usageFiltersEl.childElementCount) {
      const agentWrap = document.createElement("label");
      agentWrap.className = "usage-filter";
      const agentCap = document.createElement("span");
      agentCap.textContent = t("usage_filter_agent");
      const agentSelect = document.createElement("select");
      agentSelect.className = "usage-filter-agent";
      agentSelect.addEventListener("change", () => {
        usageAgent = agentSelect.value;
        usageModel = "";
        loadUsage();
      });
      agentWrap.append(agentCap, agentSelect);
      const modelWrap = document.createElement("label");
      modelWrap.className = "usage-filter";
      const modelCap = document.createElement("span");
      modelCap.textContent = t("usage_filter_model");
      const modelSelect = document.createElement("select");
      modelSelect.className = "usage-filter-model";
      modelSelect.addEventListener("change", () => {
        usageModel = modelSelect.value;
        loadUsage();
      });
      modelWrap.append(modelCap, modelSelect);
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
      usageFiltersEl.append(agentWrap, modelWrap, fromWrap, toWrap);
    }
    const agentSelect = usageFiltersEl.querySelector(".usage-filter-agent");
    const modelSelect = usageFiltersEl.querySelector(".usage-filter-model");
    const fromInput = usageFiltersEl.querySelector(".usage-filter-from");
    const toInput = usageFiltersEl.querySelector(".usage-filter-to");
    fillUsageSelect(agentSelect, Array.isArray(filters.agents) ? filters.agents : [], usageAgent);
    fillUsageSelect(modelSelect, Array.isArray(filters.models) ? filters.models : [], usageModel);
    if (fromInput) fromInput.value = usageSince;
    if (toInput) toInput.value = usageUntil;
  }

  async function loadUsage() {
    if (!usageList) return;
    usageList.replaceChildren();
    renderUsageRange(usageRange);
    const query = new URLSearchParams({ range: usageRange });
    if (sessionId) query.set("session_id", sessionId);
    if (usageAgent) query.set("agent_id", usageAgent);
    if (usageModel) query.set("model", usageModel);
    if (usageSince) query.set("since", usageSince);
    if (usageUntil) query.set("until", usageUntil);
    const resp = await apiFetch(`${API}/usage?${query}`);
    if (!resp || !resp.ok) {
      renderUsageFilters();
      const note = document.createElement("p");
      note.className = "usage-empty";
      note.textContent = t("usage_empty");
      usageList.appendChild(note);
      return;
    }
    const body = await resp.json();
    renderUsageFilters(body);
    if (body.enabled === false) {
      const note = document.createElement("p");
      note.className = "usage-empty";
      note.textContent = t("usage_disabled");
      usageList.appendChild(note);
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
    usageList.appendChild(grid);
    if (body.session && body.session.turns) {
      usageList.appendChild(metricCard(t("usage_this_chat"), body.session));
    }
    if (body.tts?.today?.turns || body.tts?.all?.turns) {
      usageList.appendChild(metricCard(t("usage_tts"), body.tts.today, "tts"));
    }
    const kpis = body.kpis || {};
    if (kpis.most_spend || kpis.most_used || kpis.most_efficient || kpis.leanest) {
      const heading = document.createElement("p");
      heading.className = "usage-heading";
      heading.textContent = t("usage_compare");
      usageList.appendChild(heading);
      const kpiGrid = document.createElement("div");
      kpiGrid.className = "usage-kpis";
      if (kpis.most_spend) kpiGrid.appendChild(kpiCard(t("usage_kpi_spend"), kpis.most_spend));
      if (kpis.most_used) kpiGrid.appendChild(kpiCard(t("usage_kpi_used"), kpis.most_used));
      if (kpis.most_efficient) kpiGrid.appendChild(kpiCard(t("usage_kpi_efficient"), kpis.most_efficient));
      if (kpis.leanest) kpiGrid.appendChild(kpiCard(t("usage_kpi_lean"), kpis.leanest));
      usageList.appendChild(kpiGrid);
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
      usageList.appendChild(chartsHead);
      const charts = document.createElement("div");
      charts.className = "usage-charts";
      charts.append(
        usageChart(t("usage_chart_cost"), days, "cost_usd", (value) => money(value)),
        usageChart(t("usage_chart_tokens"), days, "total_tokens", (value) => tokenLabel(value)),
      );
      usageList.appendChild(charts);
    }
    const models = Array.isArray(body.models) ? body.models : [];
    if (models.length) {
      const heading = document.createElement("p");
      heading.className = "usage-heading";
      heading.textContent = t("usage_models");
      usageList.appendChild(heading);
      usageList.appendChild(modelTable(models));
    }
    const agents = Array.isArray(body.agents) ? body.agents : [];
    if (agents.length) {
      const heading = document.createElement("p");
      heading.className = "usage-heading";
      heading.textContent = t("usage_agents");
      usageList.appendChild(heading);
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
        usageList.appendChild(row);
      }
    }
    if (!body.totals?.all?.turns) {
      const note = document.createElement("p");
      note.className = "usage-empty";
      note.textContent = t("usage_empty");
      usageList.appendChild(note);
    }
    const hint = document.createElement("p");
    hint.className = "usage-hint";
    hint.textContent = t("usage_ha_hint");
    usageList.appendChild(hint);
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
    wrap.classList.add("page-usage");
    wrap.classList.remove("usage-open");
    if (usageEl) {
      usageEl.hidden = false;
      usageEl.setAttribute("aria-hidden", "false");
    }
    syncUsageButtons(true);
    loadUsage();
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
  root.querySelector(".usage-close")?.addEventListener("click", (event) => {
    event.preventDefault();
    leaveUsage();
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
  listen(window, "location-changed", loadDictate);
  listen(window, "focus", loadDictate);
  listen(document, "visibilitychange", () => {
    loadDictate();
    if (sessionId && chatVisible()) watchPending(sessionId);
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
  if (!compact && routed && startRoute.view === "usage") {
    showEmpty();
    loadSessions();
    openUsagePage();
  } else if (startId) openSession(startId, true);
  else {
    showEmpty();
    loadSessions();
  }
  resizeComposer();
  const linkWatch = new MutationObserver(() => retargetHaLinks(logEl));
  linkWatch.observe(logEl, { subtree: true, childList: true, attributes: true, attributeFilter: ["href", "target"] });
  teardown.push(() => linkWatch.disconnect());
  function resume() {
    loadDictate();
    if (sessionId) watchPending(sessionId);
  }

  function destroy() {
    abandonStream();
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

  return { openSession, applyRoute, setNarrow, toggleNav, startNewChat, loadDictate, resume, destroy };
}
