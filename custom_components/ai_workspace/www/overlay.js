const CACHE = new URL(import.meta.url).search;
const loadChat = () =>
  Promise.all([import(`./chat.js${CACHE}`), import(`./i18n.js${CACHE}`)]);

const HOST_ID = "ha-ai-workspace-overlay";

function hassObj() {
  return document.querySelector("home-assistant")?.hass;
}

let usersAllowed = null;
let accessFlight = null;
let accessNextCheck = 0;
const ACCESS_TTL_MS = 5 * 60 * 1000;
const ACCESS_RETRY_MS = 30 * 1000;

function hideFab() {
  const user = hassObj()?.user;
  if (!user?.is_admin && usersAllowed !== true) return true;
  return location.pathname.includes("/ai-workspace");
}

function refreshAccess(onReady) {
  const hass = hassObj();
  const user = hass?.user;
  if (!user || user.is_admin || accessFlight) return;
  if (usersAllowed !== null && Date.now() < accessNextCheck) return;
  const token = hass.auth?.data?.access_token || "";
  if (!token && typeof hass.fetchWithAuth !== "function") return;
  const fetchUi = () => {
    if (typeof hass.fetchWithAuth === "function") {
      return hass.fetchWithAuth("/api/ai_workspace/ui", { headers: { Accept: "application/json" } });
    }
    return fetch("/api/ai_workspace/ui", {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  };
  const before = usersAllowed;
  accessFlight = fetchUi()
    .then((resp) => {
      if (resp.status === 401 || resp.status === 403) return { allowed: false };
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return resp.json();
    })
    .then((data) => {
      usersAllowed = data.allowed === true;
      accessNextCheck = Date.now() + (usersAllowed ? ACCESS_TTL_MS : ACCESS_RETRY_MS);
    })
    .catch(() => {
      accessNextCheck = Date.now() + ACCESS_RETRY_MS;
      if (usersAllowed === null) usersAllowed = false;
    })
    .finally(() => {
      accessFlight = null;
      if (usersAllowed !== before) onReady();
    });
}

async function ensureHost() {
  let host = document.getElementById(HOST_ID);
  if (host) return host;
  const [{ mountAiWorkspace }, { stringsFor }] = await loadChat();
  host = document.getElementById(HOST_ID);
  if (host) return host;
  host = document.createElement("div");
  host.id = HOST_ID;
  document.body.appendChild(host);
  const ui = stringsFor(hassObj()?.locale?.language || hassObj()?.language);
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      .fab {
        --ai-fab-rest: var(--ha-space-4);
        position: fixed;
        right: var(--ha-space-4);
        bottom: var(--ai-fab-bottom, var(--ai-fab-rest));
        z-index: 9;
        transition: bottom 280ms cubic-bezier(0.16, 1, 0.3, 1);
      }
      .fab {
        --ha-space-1: 0px;
        --ha-space-2: 0px;
      }
      .fab ha-icon {
        --mdc-icon-size: 26px;
        margin: 0;
      }
      .fab::part(base) {
        width: 48px;
        height: 48px;
        min-width: 48px;
        padding: 0;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .fab::part(start) {
        margin: 0;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .fab::part(label),
      .fab::part(end) { display: none; }
      .drawer {
        position: fixed;
        top: 0;
        right: 0;
        width: min(420px, 100vw);
        height: 100%;
        z-index: 10;
        background: var(--primary-background-color);
        border-left: 1px solid var(--divider-color);
        box-shadow: var(--ha-card-box-shadow);
        display: flex;
        flex-direction: column;
        color: var(--primary-text-color);
        font-family: var(--ha-font-family-body);
        transform: translateX(100%);
        opacity: 0;
        pointer-events: none;
        visibility: hidden;
        transition:
          transform 240ms cubic-bezier(0.16, 1, 0.3, 1),
          opacity 200ms ease,
          visibility 0s linear 240ms;
      }
      .drawer.open {
        transform: none;
        opacity: 1;
        pointer-events: auto;
        visibility: visible;
        transition:
          transform 240ms cubic-bezier(0.16, 1, 0.3, 1),
          opacity 200ms ease,
          visibility 0s linear 0s;
      }
      @media (prefers-reduced-motion: reduce) {
        .fab,
        .drawer { transition: none; }
      }
      .bar {
        box-sizing: border-box;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex: none;
        height: calc(var(--header-height, 56px) + env(safe-area-inset-top, 0px));
        padding: env(safe-area-inset-top, 0px) var(--ha-space-2) 0 var(--ha-space-6, 24px);
        background: var(--app-header-background-color, var(--sidebar-background-color));
        border-bottom: 1px solid var(--divider-color);
        font-weight: var(--ha-font-weight-heading);
        font-size: var(--ha-font-size-m);
      }
      .bar ha-icon-button {
        --mdc-icon-button-size: 40px;
        --ha-icon-button-size: 40px;
      }
      .bar .new-chat {
        color: var(--primary-color);
        --mdc-icon-button-icon-color: var(--primary-color);
      }
      .bar .new-chat ha-icon {
        color: var(--primary-color);
      }
      .bar .brand {
        display: flex;
        align-items: center;
        align-self: stretch;
        gap: var(--ha-space-2);
        min-width: 0;
        margin: 0;
        line-height: 1;
      }
      .brand ha-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        flex: none;
        --mdc-icon-size: 24px;
        color: var(--primary-color);
      }
      .brand span {
        line-height: 1;
      }
      .bar-actions { display: flex; align-items: center; }
      .body { flex: 1; min-height: 0; height: 100%; }
      .hidden { display: none !important; }
      @media (max-width: 870px) {
        .fab {
          --ai-fab-rest: var(--ha-space-3);
          right: var(--ha-space-3);
        }
        .drawer { width: 100%; border-left: 0; }
        .bar {
          padding-inline: max(var(--ha-space-6, 24px), env(safe-area-inset-left, 0px), env(safe-area-inset-right, 0px));
        }
      }
    </style>
    <ha-button class="fab" size="l" variant="brand" appearance="accent" title="${ui.title}"><ha-icon slot="start" icon="mdi:robot"></ha-icon></ha-button>
    <aside class="drawer">
      <div class="bar">
        <div class="brand">
          <ha-icon icon="mdi:robot"></ha-icon>
          <span>${ui.title}</span>
        </div>
        <div class="bar-actions">
          <ha-icon-button class="new-chat" label="${ui.new_chat}">
            <ha-icon icon="mdi:plus"></ha-icon>
          </ha-icon-button>
          <ha-icon-button class="close" label="${ui.close}">
            <ha-icon icon="mdi:close"></ha-icon>
          </ha-icon-button>
        </div>
      </div>
      <div class="body"></div>
    </aside>
  `;
  const fab = shadow.querySelector(".fab");
  const drawer = shadow.querySelector(".drawer");
  const body = shadow.querySelector(".body");
  const close = shadow.querySelector(".close");
  const newChat = shadow.querySelector(".new-chat");
  let chatApi = null;
  let mounting = null;
  let placeToken = 0;
  // Config add actions live in `#fab` (older HA used `ha-fab`). Skip the empty
  // wrapper — Dashboards still has the slot, but no button.
  const cornerButtons = () => {
    const boxes = [];
    const visit = (el, origin) => {
      if (!el || el === fab || el.id === HOST_ID) return;
      const style = el.ownerDocument.defaultView.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") return;
      const rect = el.getBoundingClientRect();
      if (rect.width < 36 || rect.height < 36 || rect.width > 96 || rect.height > 96) return;
      boxes.push({
        top: origin.top + rect.top,
        bottom: origin.top + rect.bottom,
        left: origin.left + rect.left,
        right: origin.left + rect.right,
      });
    };
    const fabNodes = (root) => {
      const nodes = [];
      if (!root?.querySelectorAll) return nodes;
      for (const el of root.querySelectorAll("ha-fab, [slot='fab']")) nodes.push(el);
      for (const wrap of root.querySelectorAll("#fab")) {
        const inner = wrap.querySelectorAll("ha-fab, ha-button, button, a, [slot='fab']");
        if (inner.length) nodes.push(...inner);
      }
      return nodes;
    };
    const walk = (root, origin) => {
      if (!root?.querySelectorAll) return;
      for (const el of fabNodes(root)) visit(el, origin);
      for (const el of root.querySelectorAll("*")) {
        if (el.id === HOST_ID) continue;
        if (el.shadowRoot) walk(el.shadowRoot, origin);
        if (el.tagName !== "IFRAME") continue;
        let doc = null;
        try {
          doc = el.contentDocument;
        } catch (err) {
          doc = null;
        }
        if (!doc) continue;
        const frame = el.getBoundingClientRect();
        walk(doc, { top: origin.top + frame.top, left: origin.left + frame.left });
      }
    };
    walk(document, { top: 0, left: 0 });
    return boxes;
  };
  const inCorner = (box) =>
    window.innerWidth - box.right < 120 && window.innerHeight - box.bottom < 180;
  const placeFab = () => {
    if (fab.classList.contains("hidden")) return;
    const hit = cornerButtons().filter(inCorner);
    if (!hit.length) {
      fab.style.removeProperty("--ai-fab-bottom");
      return;
    }
    const top = Math.min(...hit.map((box) => box.top));
    fab.style.setProperty("--ai-fab-bottom", `${Math.round(window.innerHeight - top + 12)}px`);
  };
  const schedulePlace = () => {
    const token = ++placeToken;
    placeFab();
    for (const delay of [400, 1200]) {
      window.setTimeout(() => {
        if (token === placeToken) placeFab();
      }, delay);
    }
  };
  let userWaits = 0;
  const sync = () => {
    refreshAccess(sync);
    if (!hassObj()?.user && userWaits < 40) {
      userWaits += 1;
      window.setTimeout(sync, 200);
    }
    fab.classList.toggle("hidden", hideFab());
    if (hideFab()) drawer.classList.remove("open");
    schedulePlace();
  };
  const mountChat = () => {
    if (chatApi) return Promise.resolve(chatApi);
    if (!mounting) {
      const api = mountAiWorkspace(body, {
        compact: true,
        getToken: () => hassObj()?.auth?.data?.access_token || "",
        navigate: (path) => {
          drawer.classList.remove("open");
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
        },
      });
      chatApi = api;
      mounting = Promise.resolve(api);
    }
    return mounting;
  };
  fab.addEventListener("click", async () => {
    drawer.classList.add("open");
    const api = await mountChat();
    api.resume?.();
  });
  newChat.addEventListener("click", async () => {
    drawer.classList.add("open");
    const api = await mountChat();
    api.startNewChat();
  });
  close.addEventListener("click", () => drawer.classList.remove("open"));
  window.addEventListener("location-changed", sync);
  window.addEventListener("popstate", sync);
  window.addEventListener("resize", schedulePlace);
  // `narrow` / `show-tabs` is what lifts the add button above the phone tab bar.
  const layoutHint = new MutationObserver(schedulePlace);
  layoutHint.observe(document.body, {
    subtree: true,
    attributes: true,
    attributeFilter: ["narrow", "show-tabs", "is-wide"],
  });
  sync();
  return host;
}

function boot(tries = 0) {
  if (document.getElementById(HOST_ID)) return;
  const user = hassObj()?.user;
  if (!user) {
    if (tries < 50) window.setTimeout(() => boot(tries + 1), 200);
    return;
  }
  if (user.is_admin || usersAllowed === true) {
    ensureHost();
    return;
  }
  refreshAccess(() => boot(tries));
}

function start() {
  if (!customElements.get("home-assistant")) {
    customElements.whenDefined("home-assistant").then(start);
    return;
  }
  // Users without access never download the chat UI; navigation re-checks after the retry delay.
  window.addEventListener("location-changed", () => boot());
  boot();
}

start();
