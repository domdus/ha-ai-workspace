export const MAX_ATTACH = 4;
export const MAX_QUEUE = 10;

/** Cap the file list before any bytes are read. */
export function filesToRead(files, slots = MAX_ATTACH) {
  return [...(files || [])].filter(Boolean).slice(0, Math.max(0, slots));
}

/**
 * Copy file bytes first, then clear the picker.
 * Clearing first can invalidate File objects in the Companion app.
 */
export async function takeInputFiles(input, freeze, slots) {
  const files = input?.files;
  if (!files?.length) {
    if (input) input.value = "";
    return [];
  }
  const frozen = await freeze(files, slots);
  if (input) input.value = "";
  return frozen;
}

/**
 * If the composer is empty, move the first queued turn into it.
 * Remaining turns stay on the queue (caller must not wipe them).
 */
export function pullQueuedDraft(queue, { draftText = "", pending = [], maxAttach = MAX_ATTACH } = {}) {
  if (!queue?.length) return { pulled: false };
  if (String(draftText || "").trim() || pending.length) return { pulled: false };
  const turn = queue.shift();
  return {
    pulled: true,
    text: turn.text || "",
    attachments: (turn.attachments || []).slice(0, maxAttach),
  };
}

/** Destroying the panel drops the stack; stop, send, and chat switch keep it. */
export function keepQueueOnHalt(reason = "send") {
  return reason !== "destroy";
}
