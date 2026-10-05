import { mountAiWorkspace } from "./chat.js?v=22";

class HaAiWorkspacePanel extends HTMLElement {
  constructor() {
    super();
    this._mounted = false;
    this._narrow = false;
    this._mq = window.matchMedia("(max-width: 870px)");
    this.attachShadow({ mode: "open" });
    this._onMq = () => {
      this._syncChrome();
      this._ui?.setNarrow?.(this._overlayNav());
    };
    this._mq.addEventListener("change", this._onMq);
  }

  set hass(hass) {
    this._hass = hass;
    this._syncChrome();
    this._mount();
  }

  set narrow(narrow) {
    this._narrow = Boolean(narrow);
    this._syncChrome();
    this._ui?.setNarrow?.(this._overlayNav());
  }

  set route(route) {
    this._route = route;
    this._ui?.applyRoute?.();
  }

  connectedCallback() {
    this.style.display = "block";
    this.style.height = "100%";
    this.style.minHeight = "0";
    const panel = this.closest("ha-panel-custom");
    if (panel) {
      panel.style.display = "block";
      panel.style.height = "100%";
    }
    this._mount();
  }

  _overlayNav() {
    return Boolean(this._narrow) || this._mq.matches;
  }

  _syncChrome() {
    const root = this.shadowRoot;
    if (!root) return;
    const overlay = this._overlayNav();
    const bar = root.querySelector("ha-top-app-bar-fixed");
    const menu = root.querySelector("ha-menu-button");
    const chats = root.querySelector(".chats-menu");
    if (bar) bar.narrow = this._narrow;
    if (menu) {
      menu.narrow = this._narrow;
      if (this._hass) menu.hass = this._hass;
    }
    if (chats) chats.hidden = !overlay;
  }

  _mount() {
    if (this._mounted || !this._hass || !this.shadowRoot) return;
    this._mounted = true;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          min-height: 0;
        }
        ha-top-app-bar-fixed {
          height: 100vh;
        }
        .page-title {
          font-size: inherit;
          font-weight: inherit;
          line-height: inherit;
          margin: 0;
        }
        .content {
          box-sizing: border-box;
          height: calc(
            100vh - var(--header-height, 56px) - var(--safe-area-inset-top, 0px) -
              var(--safe-area-inset-bottom, 0px)
          );
          min-height: 0;
          overflow: hidden;
        }
        .chats-menu[hidden] {
          display: none !important;
        }
      </style>
      <ha-top-app-bar-fixed>
        <ha-menu-button slot="navigationIcon"></ha-menu-button>
        <h1 class="page-title" slot="title">AI Workspace</h1>
        <ha-icon-button class="chats-menu" slot="actionItems" label="Chats" hidden>
          <ha-icon icon="mdi:forum-outline"></ha-icon>
        </ha-icon-button>
        <div class="content"></div>
      </ha-top-app-bar-fixed>
    `;
    this._syncChrome();
    this._ui = mountAiWorkspace(this.shadowRoot.querySelector(".content"), {
      routed: true,
      narrow: this._overlayNav(),
      chrome: "panel",
      getToken: () => this._hass?.auth?.data?.access_token || "",
      navigate: (path, options = {}) => {
        const hass = this._hass;
        if (typeof hass?.navigate === "function") {
          hass.navigate(path, options);
          return;
        }
        const state = history.state && typeof history.state === "object" ? history.state : { root: true };
        history[options.replace ? "replaceState" : "pushState"](state, "", path);
        const event = new Event("location-changed", { bubbles: true, composed: true });
        event.detail = { replace: Boolean(options.replace) };
        window.dispatchEvent(event);
      },
    });
    this.shadowRoot.querySelector(".chats-menu")?.addEventListener("click", () => {
      this._ui?.toggleNav?.();
    });
  }
}

customElements.define("ha-ai-workspace-panel", HaAiWorkspacePanel);
