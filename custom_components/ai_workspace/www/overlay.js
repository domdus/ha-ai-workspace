const CACHE = new URL(import.meta.url).search;
const loadChat = () =>
  Promise.all([import(`./chat.js${CACHE}`), import(`./i18n.js${CACHE}`)]);

const HOST_ID = "ha-ai-workspace-overlay";

function hassObj() {
  return document.querySelector("home-assistant")?.hass;
}

function hideFab() {
  const path = location.pathname;
  return path.includes("/ai-workspace") || path.startsWith("/config");
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
        position: fixed;
        right: var(--ha-space-4);
        bottom: var(--ha-space-4);
        z-index: 9;
      }
      .fab {
        --ha-space-1: 0px;
        --ha-space-2: 0px;
      }
      .fab ha-icon {
        --mdc-icon-size: 30px;
        margin: 0;
      }
      .fab::part(base) {
        width: 56px;
        height: 56px;
        min-width: 56px;
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
        box-shadow: var(--ha-card-box-shadow);
        display: none;
        flex-direction: column;
        color: var(--primary-text-color);
        font-family: var(--ha-font-family-body);
      }
      .drawer.open { display: flex; }
      .bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--ha-space-2) var(--ha-space-3);
        border-bottom: 1px solid var(--ha-color-border-neutral-normal, var(--divider-color));
        font-weight: var(--ha-font-weight-heading);
        font-size: var(--ha-font-size-m);
      }
      .bar-actions { display: flex; align-items: center; }
      .body { flex: 1; min-height: 0; height: 100%; }
      .hidden { display: none !important; }
      @media (max-width: 870px) {
        .fab {
          right: var(--ha-space-3);
          bottom: var(--ha-space-3);
        }
        .fab ha-icon { --mdc-icon-size: 26px; }
        .fab::part(base) {
          width: 48px;
          height: 48px;
          min-width: 48px;
        }
        .drawer { width: 100%; }
        .bar {
          padding-inline: max(var(--ha-space-6, 24px), env(safe-area-inset-left, 0px), env(safe-area-inset-right, 0px));
        }
      }
    </style>
    <ha-button class="fab" size="l" variant="brand" appearance="accent" title="${ui.title}"><ha-icon slot="start" icon="mdi:robot"></ha-icon></ha-button>
    <aside class="drawer">
      <div class="bar">
        <span>${ui.title}</span>
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
  const sync = () => {
    fab.classList.toggle("hidden", hideFab());
    if (hideFab()) drawer.classList.remove("open");
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
  fab.addEventListener("click", () => {
    drawer.classList.add("open");
    mountChat();
  });
  newChat.addEventListener("click", async () => {
    drawer.classList.add("open");
    const api = await mountChat();
    api.startNewChat();
  });
  close.addEventListener("click", () => drawer.classList.remove("open"));
  window.addEventListener("location-changed", sync);
  window.addEventListener("popstate", sync);
  sync();
  return host;
}

function start() {
  if (!customElements.get("home-assistant")) {
    customElements.whenDefined("home-assistant").then(start);
    return;
  }
  ensureHost();
}

start();
