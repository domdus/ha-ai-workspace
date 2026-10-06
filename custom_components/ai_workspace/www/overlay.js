const CACHE = new URL(import.meta.url).search;
const [{ mountAiWorkspace }, { stringsFor }] = await Promise.all([
  import(`./chat.js${CACHE}`),
  import(`./i18n.js${CACHE}`),
]);

const HOST_ID = "ha-ai-workspace-overlay";

function hassObj() {
  return document.querySelector("home-assistant")?.hass;
}

function hideFab() {
  const path = location.pathname;
  return path.includes("/ai-workspace") || path.startsWith("/config");
}

function ensureHost() {
  let host = document.getElementById(HOST_ID);
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
        border-bottom: 1px solid var(--divider-color);
        font-weight: var(--ha-font-weight-heading);
        font-size: var(--ha-font-size-m);
      }
      .body { flex: 1; min-height: 0; height: 100%; }
      .hidden { display: none !important; }
    </style>
    <ha-button class="fab" size="l" variant="brand" appearance="accent" title="${ui.title}">
      <ha-icon slot="start" icon="mdi:robot"></ha-icon>
      AI
    </ha-button>
    <aside class="drawer">
      <div class="bar">
        <span>${ui.title}</span>
        <ha-icon-button class="close" label="${ui.close}">
          <ha-icon icon="mdi:close"></ha-icon>
        </ha-icon-button>
      </div>
      <div class="body"></div>
    </aside>
  `;
  const fab = shadow.querySelector(".fab");
  const drawer = shadow.querySelector(".drawer");
  const body = shadow.querySelector(".body");
  const close = shadow.querySelector(".close");
  let mounted = false;
  const sync = () => {
    fab.classList.toggle("hidden", hideFab());
    if (hideFab()) drawer.classList.remove("open");
  };
  fab.addEventListener("click", () => {
    drawer.classList.add("open");
    if (!mounted) {
      mounted = true;
      mountAiWorkspace(body, {
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
    }
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
