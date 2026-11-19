// Reply meta in the chat action row: reply time and the "copy last reply" text.
// Pure helpers (no DOM), tested in tests/test_reply_meta.mjs.

function safeFormat(locale, options) {
  try {
    return new Intl.DateTimeFormat(locale || undefined, options);
  } catch (_err) {
    // Unknown time zone or locale: fall back to the browser's own.
    const { timeZone: _tz, ...rest } = options;
    try {
      return new Intl.DateTimeFormat(locale || undefined, rest);
    } catch (_err2) {
      return new Intl.DateTimeFormat(undefined, rest);
    }
  }
}

function dayKey(date, timeZone) {
  const parts = safeFormat("en-US", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const get = (type) => Number(parts.find((p) => p.type === type)?.value);
  return { y: get("year"), m: get("month"), d: get("day") };
}

function sameDay(a, b) {
  return a.y === b.y && a.m === b.m && a.d === b.d;
}

function dayBefore(day) {
  const at = new Date(Date.UTC(day.y, day.m - 1, day.d - 1));
  return { y: at.getUTCFullYear(), m: at.getUTCMonth() + 1, d: at.getUTCDate() };
}

/** A message time as a Date, or null. Accepts ISO strings, epoch ms and Dates. */
export function parseReplyTime(value) {
  if (value == null || value === "") return null;
  const at = value instanceof Date ? new Date(value.getTime()) : new Date(typeof value === "number" ? value : String(value));
  return Number.isFinite(at.getTime()) ? at : null;
}

/**
 * Short reply time: "21:04" today, "gestern, 21:04" yesterday, "17.11., 21:04" this year,
 * "17.11.2025, 21:04" in another year. `yesterday` is a template with {time}.
 */
export function replyTimeLabel(value, { now = new Date(), locale, timeZone, hour12, yesterday = "yesterday, {time}" } = {}) {
  const at = parseReplyTime(value);
  if (!at) return "";
  const clock = { hour: "2-digit", minute: "2-digit", timeZone };
  if (hour12 !== undefined) clock.hour12 = hour12;
  const time = safeFormat(locale, clock).format(at);
  const day = dayKey(at, timeZone);
  const today = dayKey(now, timeZone);
  if (sameDay(day, today)) return time;
  if (sameDay(day, dayBefore(today))) return String(yesterday).replace("{time}", time);
  const opts = { ...clock, day: "2-digit", month: "2-digit" };
  if (day.y !== today.y) opts.year = "numeric";
  return safeFormat(locale, opts).format(at);
}

/** Full date and time for the tooltip. */
export function replyTimeTitle(value, { locale, timeZone, hour12 } = {}) {
  const at = parseReplyTime(value);
  if (!at) return "";
  const opts = {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  };
  if (hour12 !== undefined) opts.hour12 = hour12;
  return safeFormat(locale, opts).format(at);
}

/** Home Assistant's clock setting ("12", "24", "language", "system") as Intl's hour12. */
export function haHour12(timeFormat) {
  if (timeFormat === "12") return true;
  if (timeFormat === "24") return false;
  return undefined;
}

/** Time zone to show: the HA server's, unless the user picked "local" in their profile. */
export function haTimeZone(hass) {
  if (hass?.locale?.time_zone === "local") return undefined;
  return hass?.config?.time_zone || undefined;
}

/**
 * The newest finished assistant reply among chat entries ({ role, text, streaming }),
 * or null. Only the reply text counts — tool chips and status lines are not part of it.
 */
export function lastReply(entries) {
  const list = Array.isArray(entries) ? entries : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const entry = list[i];
    if (!entry || entry.role !== "assistant" || entry.streaming) continue;
    const text = String(entry.text || "").trim();
    if (text) return { ...entry, text };
  }
  return null;
}

/** The reply time belongs in the action row only when the chat ends with a finished reply. */
export function replyTimeFor(entries) {
  const list = Array.isArray(entries) ? entries : [];
  const last = list[list.length - 1];
  if (!last || last.role !== "assistant" || last.streaming) return "";
  return last.createdAt || "";
}
