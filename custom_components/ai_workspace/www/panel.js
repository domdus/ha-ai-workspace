const CACHE = new URL(import.meta.url).search;

function resetHaShellScroll(startEl) {
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
}

class HaAiWorkspacePanel extends HTMLElement {
  constructor() {
    super();
    this._mounted = false;
    this._mounting = false;
    this._narrow = false;
    this._mq = window.matchMedia("(max-width: 870px)");
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          min-height: 0;
          background: var(--primary-background-color);
        }
      </style>
    `;
    this._mods = Promise.all([
      import(`./chat.js${CACHE}`),
      import(`./i18n.js${CACHE}`),
    ]);
    this._onMq = () => {
      this._syncChrome();
      this._ui?.setNarrow?.(this._overlayNav());
    };
    this._onNav = () => {
      if (!location.pathname.startsWith("/ai-workspace")) return;
      this._scrollShellIntoView();
    };
  }

  _scrollShellIntoView() {
    resetHaShellScroll(this);
    requestAnimationFrame(() => resetHaShellScroll(this));
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
    this._scrollShellIntoView();
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
    this._mq.addEventListener("change", this._onMq);
    window.addEventListener("location-changed", this._onNav);
    window.addEventListener("popstate", this._onNav);
    this._scrollShellIntoView();
    this._mount();
  }

  disconnectedCallback() {
    this._mq.removeEventListener("change", this._onMq);
    window.removeEventListener("location-changed", this._onNav);
    window.removeEventListener("popstate", this._onNav);
    // HA sometimes moves the panel; only tear down when it stays detached.
    window.setTimeout(() => {
      if (this.isConnected || !this._ui) return;
      this._ui.destroy?.();
      this._ui = null;
      this._mounted = false;
      this._mounting = false;
    }, 0);
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

  async _mount() {
    if (this._mounted || this._mounting || !this._hass || !this.shadowRoot) return;
    this._mounting = true;
    let mountAiWorkspace;
    let prefetchUiTheme;
    let stringsFor;
    try {
      [{ mountAiWorkspace, prefetchUiTheme }, { stringsFor }] = await this._mods;
    } catch (err) {
      this._mounting = false;
      console.error("AI Workspace failed to load", err);
      return;
    }
    if (this._mounted) return;
    this._mounted = true;
    await prefetchUiTheme(() => this._hass?.auth?.data?.access_token || "");
    const ui = stringsFor(this._hass.locale?.language || this._hass.language);
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          min-height: 0;
        }
        ha-top-app-bar-fixed {
          height: 100%;
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
        .content:not(.ready) > .wrap {
          visibility: hidden;
        }
        .chats-menu[hidden] {
          display: none !important;
        }
        .page-title {
          font-size: inherit;
          font-weight: inherit;
          line-height: inherit;
          margin: 0;
        }
      </style>
      <ha-top-app-bar-fixed>
        <ha-menu-button slot="navigationIcon"></ha-menu-button>
        <h1 class="page-title" slot="title">${ui.title}</h1>
        <ha-icon-button class="chats-menu" slot="actionItems" label="${ui.chats}" hidden>
          <ha-icon icon="mdi:forum-outline"></ha-icon>
        </ha-icon-button>
        <div class="content"></div>
      </ha-top-app-bar-fixed>
    `;
    this._syncChrome();
    const content = this.shadowRoot.querySelector(".content");
    this._scrollShellIntoView();
    this._ui = await mountAiWorkspace(content, {
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
    const reveal = () => content?.classList.add("ready");
    const css = [...(content?.querySelectorAll("link[rel='stylesheet']") || [])];
    if (css.length && css.every((link) => link.sheet)) {
      reveal();
    } else {
      let left = Math.max(css.length, 1);
      const done = () => {
        left -= 1;
        if (left <= 0) reveal();
      };
      if (css.length) {
        for (const link of css) {
          link.addEventListener("load", done, { once: true });
          link.addEventListener("error", done, { once: true });
        }
      } else {
        done();
      }
      window.setTimeout(reveal, 400);
    }
    this.shadowRoot.querySelector(".chats-menu")?.addEventListener("click", () => {
      this._ui?.toggleNav?.();
    });
  }
}

if (!customElements.get("ha-ai-workspace-panel")) {
  customElements.define("ha-ai-workspace-panel", HaAiWorkspacePanel);
}
