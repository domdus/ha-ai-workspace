/**
 * Chat header title: which stored titles still mean "no title yet".
 * The server stores "New Chat" until the first message; older chats may hold the
 * English or German UI default.
 */
export const PLACEHOLDER_TITLES = Object.freeze(["New Chat", "New chat", "Neuer Chat"]);

export function isPlaceholderTitle(title, placeholder = "") {
  const text = String(title || "").trim();
  if (!text) return true;
  if (PLACEHOLDER_TITLES.includes(text)) return true;
  return Boolean(placeholder) && text === String(placeholder).trim();
}

/** What the header shows for a stored title. */
export function headerTitle(title, placeholder) {
  return isPlaceholderTitle(title, placeholder) ? placeholder : String(title).trim();
}

/** A real title for the chat list, or undefined so an existing row keeps its own. */
export function realTitle(title, placeholder = "") {
  return isPlaceholderTitle(title, placeholder) ? undefined : String(title).trim();
}
