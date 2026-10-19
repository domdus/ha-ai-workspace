/**
 * Keep off-site media out of chat Markdown. A remote image URL loads by itself and can carry
 * chat text to another server, so anything not provably same-origin becomes a link or is dropped.
 */

const MEDIA_TAGS = "img|picture|source|video|audio|track|iframe|embed|object|image|input";
const ALWAYS_DROP = new Set(["iframe", "embed", "object", "image", "input", "track"]);
const URL_ATTRS = new Set(["src", "srcset", "poster", "data", "href", "xlink:href", "background", "lowsrc", "dynsrc"]);
const MEDIA_TAG = new RegExp(`<(${MEDIA_TAGS})(?=[\\s/>])((?:[^>"']|"[^"]*"|'[^']*')*)(>)?`, "gi");
const ATTR = /([^\s"'>/=]+)\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+)/g;
const INLINE_IMAGE =
  /!\[((?:[^[\]\\\n]|\\.)*)\]\(\s*(<[^>\n]*>|[^\s()]+)(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?\s*\)/y;
const FENCE = /^ {0,3}(`{3,}|~{3,})/;

function pageOrigin() {
  return globalThis.location?.origin || "";
}

export function safeMediaUrl(raw, origin = pageOrigin()) {
  const value = String(raw || "").trim().replace(/^<|>$/g, "");
  if (!value) return false;
  if (/^data:image\/[a-z0-9.+-]+[;,]/i.test(value)) return true;
  if (value.startsWith("/")) return /^\/(?![/\\])[^\s&\\]*$/.test(value);
  if (!origin || !/^https?:\/\//i.test(value)) return false;
  try {
    return new URL(value).origin === origin;
  } catch (_err) {
    return false;
  }
}

function srcsetUrls(value) {
  return String(value || "")
    .split(",")
    .map((part) => part.trim().split(/\s+/)[0])
    .filter(Boolean);
}

function unquote(value) {
  const text = String(value || "");
  return /^["']/.test(text) ? text.slice(1, -1) : text;
}

function tagIsSafe(name, attrs, origin) {
  if (ALWAYS_DROP.has(name)) return false;
  for (const match of attrs.matchAll(ATTR)) {
    const key = match[1].toLowerCase();
    if (!URL_ATTRS.has(key)) continue;
    const value = unquote(match[2]);
    const urls = key === "srcset" ? srcsetUrls(value) : [value];
    if (!urls.every((url) => safeMediaUrl(url, origin))) return false;
  }
  return true;
}

function guardHtml(text, origin) {
  return text.replace(MEDIA_TAG, (whole, tag, attrs, close) => {
    if (!close) return `&lt;${whole.slice(1)}`;
    return tagIsSafe(tag.toLowerCase(), attrs, origin) ? whole : "";
  });
}

function guardImages(text, origin) {
  return text.replace(/!\[/g, (mark, offset, source) => {
    INLINE_IMAGE.lastIndex = offset;
    const hit = INLINE_IMAGE.exec(source);
    return hit && safeMediaUrl(hit[2], origin) ? mark : "[";
  });
}

function guardProse(text, origin) {
  const held = [];
  const kept = text.replace(/`[^`\n]+`/g, (code) => `\u0000MG${held.push(code) - 1}\u0000`);
  return guardHtml(guardImages(kept, origin), origin).replace(/\u0000MG(\d+)\u0000/g, (_m, i) => held[Number(i)]);
}

/** Markdown in, Markdown out. Fenced code is left alone because it renders as text. */
export function stripRemoteMedia(text, origin = pageOrigin()) {
  const lines = String(text || "").split("\n");
  const out = [];
  let prose = [];
  let fence = "";
  const flush = () => {
    if (prose.length) out.push(guardProse(prose.join("\n"), origin));
    prose = [];
  };
  for (const line of lines) {
    const mark = FENCE.exec(line)?.[1] || "";
    if (fence) {
      out.push(line);
      if (mark && mark[0] === fence[0] && mark.length >= fence.length && !line.trim().slice(mark.length).trim()) fence = "";
      continue;
    }
    if (mark) {
      flush();
      fence = mark;
      out.push(line);
      continue;
    }
    prose.push(line);
  }
  flush();
  return out.join("\n");
}

const DOM_MEDIA = "img,picture,source,video,audio,track,iframe,embed,object,image,input[type=image]";

function nodeIsSafe(node, origin) {
  const name = String(node.localName || "").toLowerCase();
  if (ALWAYS_DROP.has(name) && !(name === "input" && node.getAttribute("type") !== "image")) return false;
  for (const attr of [...(node.attributes || [])]) {
    const key = attr.name.toLowerCase();
    if (!URL_ATTRS.has(key)) continue;
    const urls = key === "srcset" ? srcsetUrls(attr.value) : [attr.value];
    if (!urls.every((url) => safeMediaUrl(url, origin))) return false;
  }
  return true;
}

/** Second line of defence after ha-markdown rendered: remove media that slipped through. */
export function scrubRenderedMedia(root, origin = pageOrigin()) {
  if (!root?.querySelectorAll) return;
  for (const node of root.querySelectorAll(DOM_MEDIA)) {
    if (nodeIsSafe(node, origin)) continue;
    const src = node.getAttribute("src") || "";
    if (node.localName === "img" && /^https?:\/\//i.test(src)) {
      const link = node.ownerDocument.createElement("a");
      link.href = src;
      link.rel = "noreferrer noopener";
      link.target = "_blank";
      link.textContent = node.getAttribute("alt") || src;
      node.replaceWith(link);
    } else {
      node.remove();
    }
  }
  for (const inner of root.querySelectorAll("*")) {
    if (inner.shadowRoot) scrubRenderedMedia(inner.shadowRoot, origin);
  }
}

const watched = new WeakSet();

export function watchRenderedMedia(md, origin = pageOrigin()) {
  if (!md || watched.has(md) || typeof MutationObserver !== "function") return;
  watched.add(md);
  let tries = 0;
  const attach = () => {
    const root = md.shadowRoot || md;
    if (!md.shadowRoot && tries++ < 30) {
      requestAnimationFrame(attach);
      return;
    }
    scrubRenderedMedia(root, origin);
    new MutationObserver(() => scrubRenderedMedia(root, origin)).observe(root, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["src", "srcset", "poster", "href", "data"],
    });
  };
  attach();
}
