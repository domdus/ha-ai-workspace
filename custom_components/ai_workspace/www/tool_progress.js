// MCP tool progress (notifications/progress) for the running tool step in the chat.
// Pure helpers (no DOM), tested in tests/test_tool_progress.mjs.

const MAX_CHARS = 160;

// The text for a tool_progress event: the server's message, else "n/total" or a percentage.
export function toolProgressText(event) {
  const message = String(event?.text ?? event?.message ?? "").replace(/\s+/g, " ").trim();
  if (message) return message.length > MAX_CHARS ? `${message.slice(0, MAX_CHARS - 1)}…` : message;
  const progress = Number(event?.progress);
  const total = Number(event?.total);
  if (Number.isFinite(progress) && Number.isFinite(total) && total > 0) {
    return `${Math.max(0, Math.min(100, Math.round((progress / total) * 100)))}%`;
  }
  return "";
}

function sameTool(chipTool, name) {
  const tool = String(chipTool || "").toLowerCase();
  const wanted = String(name || "").toLowerCase();
  if (!tool || !wanted) return false;
  if (tool === wanted) return true;
  // Engines prefix MCP tools with their server: mcp__server__tool, server.tool, server-tool.
  return [`__${wanted}`, `.${wanted}`, `-${wanted}`, `_${wanted}`, `/${wanted}`].some((end) => tool.endsWith(end));
}

// The running chip the progress belongs to: same call id, else same tool, else the newest running one.
// chips: running chips only, each with a dataset ({ tool, callId }).
export function progressChip(chips, event) {
  const list = Array.from(chips || []);
  if (!list.length) return null;
  const callId = String(event?.id || event?.call_id || "");
  if (callId) {
    const byId = list.find((chip) => chip?.dataset?.callId === callId);
    if (byId) return byId;
  }
  const byName = [...list].reverse().find((chip) => sameTool(chip?.dataset?.tool, event?.name));
  return byName || list[list.length - 1];
}
