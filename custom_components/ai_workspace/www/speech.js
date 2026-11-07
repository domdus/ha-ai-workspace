export const TARGET_CHARS = 280;
export const MAX_CHARS = 560;

const ARROW_CHARS = /[→➡➜➤▶►▸▹↦⇒]+/g;

export function speechPlain(text, options = {}) {
  const natural = options.natural !== false;
  let out = String(text || "");
  if (!natural) {
    return out.trim();
  }
  return out
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[*_`#~]+/g, "")
    .replace(ARROW_CHARS, " ")
    .replace(/^\s*[-*_]{3,}\s*$/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^[ \t]*[-*•]\s+/gm, "")
    // Keep "1." on numbered lists: some engines read it as "first", which a bare list loses.
    .replace(/^[ \t]*(\d+\.)\s+/gm, "$1 ")
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    // A numbered item without end punctuation would run into the next number ("blinds 3.").
    .map((line) => (/^\d+\.\s/.test(line) && !/[.!?:;,…]$/.test(line) ? `${line}.` : line))
    .filter(Boolean)
    .join("\n")
    .trim();
}

function speechIsShort(text) {
  const words = String(text || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
  return words.length <= 3;
}

function speechIsCompleteSentence(text) {
  return /[.!?。！？]["»«”’')\]]*\s*$/u.test(String(text || "").trim());
}

const SENTENCE_END = /[.!?。！？]["»«”’')\]]*?(?=\s+(?:\p{Lu}|\p{Lt}|[„"«(])|\s*\n)/gu;
// "1." or "12." on its own is a list number, not the end of a sentence.
const LIST_NUMBER_END = /(?:^|\s)\d{1,3}\.$/;

function firstSentence(text) {
  SENTENCE_END.lastIndex = 0;
  let match;
  while ((match = SENTENCE_END.exec(text))) {
    const piece = text.slice(0, match.index + match[0].length);
    if (!LIST_NUMBER_END.test(piece)) return piece;
  }
  return "";
}

function pullSentence(text) {
  const para = /^[\s\S]*?\n\s*\n/.exec(text);
  let piece = firstSentence(text);
  if (para && (!piece || para[0].length < piece.length)) piece = para[0];
  if (!piece) return null;
  return { piece, rest: text.slice(piece.length) };
}

function pullHeavyUnit(text) {
  const para = /^[\s\S]*?\n\s*\n/.exec(text);
  const introThenList = /^[^\n]+\n(?=[ \t]*(?:[-*•] |\d+\. ))/.exec(text);
  const listItem = /^(?:[ \t]*[-*•] |\d+\. ).+(?:\n|$)/.exec(text);
  const sentence = firstSentence(text);
  const units = [para, introThenList, listItem, sentence ? [sentence] : null].filter(Boolean);
  if (!units.length) return null;
  units.sort((a, b) => a[0].length - b[0].length);
  const piece = units[0][0];
  return { piece, rest: text.slice(piece.length) };
}

function trailingSentence(text) {
  const match = /^([\s\S]*?[.!?。！？]["»«”’')\]]*)\s*$/u.exec(text);
  if (!match || !match[1].trim() || LIST_NUMBER_END.test(match[1].trim())) return null;
  return { piece: match[0], rest: "" };
}

function paragraphFollows(text) {
  return /^\s*\n\s*\n/.test(text);
}

function lastClipBreak(prefix) {
  const para = prefix.lastIndexOf("\n\n");
  if (para >= Math.min(40, prefix.length / 4)) return para + 2;
  const sentence = /[.!?。！？]["»«”’')\]]*(?:\s+|$)/gu;
  let last = -1;
  let match;
  while ((match = sentence.exec(prefix))) last = match.index + match[0].length;
  if (last >= Math.min(40, prefix.length / 4)) return last;
  const space = prefix.search(/\s+\S*$/);
  if (space > 0) return space + 1;
  return prefix.length;
}

/**
 * Split leftover TTS text so no clip is larger than `max` spoken characters.
 * Flush used to dump the rest of a long reply as one request; engines then
 * timed out or dropped it, so reading stopped after the first paragraph.
 */
export function splitSpeechClip(text, max = MAX_CHARS, measure) {
  const sizeOf = typeof measure === "function" ? measure : (value) => speechPlain(value).length;
  let rest = String(text || "").trim();
  const pieces = [];
  while (rest) {
    if (sizeOf(rest) <= max) {
      pieces.push(rest);
      break;
    }
    let lo = 1;
    let hi = rest.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (sizeOf(rest.slice(0, mid)) <= max) lo = mid;
      else hi = mid - 1;
    }
    let cut = lastClipBreak(rest.slice(0, Math.max(1, lo)));
    if (cut < 1) cut = Math.max(1, lo);
    const piece = rest.slice(0, cut).trim();
    rest = rest.slice(cut).trim();
    if (piece) pieces.push(piece);
    else {
      pieces.push(rest.slice(0, Math.max(1, lo)));
      rest = rest.slice(Math.max(1, lo)).trim();
    }
  }
  return pieces;
}

function takeLightSpeech(held, started, flush, pause) {
  const pieces = [];
  let rest = String(held || "");
  let bundle = "";
  let open = !started;
  while (rest) {
    let next = pullSentence(rest);
    if (!next) {
      const tail = trailingSentence(rest);
      if (!tail || (open && !flush && !pause && speechIsShort(bundle + tail.piece))) break;
      next = tail;
    }
    rest = next.rest;
    if (open) {
      bundle += next.piece;
      if (!speechIsShort(bundle)) {
        pieces.push(bundle.trim());
        bundle = "";
        open = false;
      }
      continue;
    }
    const bit = next.piece.trim();
    if (bit) pieces.push(bit);
  }
  if (open && bundle) {
    if (flush) {
      const leftover = `${bundle}${rest}`.trim();
      if (leftover) pieces.push(...splitSpeechClip(leftover));
      rest = "";
    } else if (pause) {
      const tail = trailingSentence(bundle);
      if (tail && tail.piece.trim()) {
        pieces.push(tail.piece.trim());
        rest = `${tail.rest}${rest}`;
      } else rest = bundle + rest;
    } else rest = bundle + rest;
  } else if (flush && rest.trim()) {
    pieces.push(...splitSpeechClip(rest.trim()));
    rest = "";
  }
  return { pieces: pieces.filter(Boolean).flatMap((piece) => splitSpeechClip(piece)), rest };
}

function takeHeavySpeech(held, started, flush, pause) {
  const pieces = [];
  let rest = String(held || "");
  let bundle = "";
  let first = !started;

  const emit = () => {
    const spoken = bundle.trim();
    if (spoken) pieces.push(spoken);
    bundle = "";
  };

  const size = (text) => speechPlain(text).length;
  const ready = () => Boolean(flush || pause);

  while (rest) {
    let next = pullHeavyUnit(rest);
    if (!next) {
      const tail = trailingSentence(rest);
      if (!tail) break;
      const nextSize = size(bundle + tail.piece);
      if (!ready() && first && speechIsShort(bundle + tail.piece)) break;
      if (!ready() && !first && nextSize < TARGET_CHARS) break;
      next = tail;
    }
    const candidate = `${bundle}${next.piece}`;
    if (bundle.trim() && size(candidate) > MAX_CHARS) {
      emit();
      first = false;
      continue;
    }
    rest = next.rest;
    bundle = candidate;
    if (first && !speechIsShort(bundle) && speechIsCompleteSentence(bundle)) {
      emit();
      first = false;
      continue;
    }
    // A blank line means this paragraph is done — don't wait for 280 more characters.
    if (size(bundle) >= TARGET_CHARS || (paragraphFollows(rest) && speechIsCompleteSentence(bundle))) {
      emit();
      first = false;
    }
  }
  if (flush) {
    const leftover = `${bundle}${rest}`.trim();
    bundle = "";
    rest = "";
    if (leftover) pieces.push(...splitSpeechClip(leftover, MAX_CHARS, size));
  } else {
    if (pause && bundle.trim() && speechIsCompleteSentence(bundle)) emit();
    rest = bundle + rest;
  }
  return { pieces: pieces.filter(Boolean).flatMap((piece) => splitSpeechClip(piece, MAX_CHARS, size)), rest };
}

export function takeSpeech(held, started, flush, options = {}) {
  const pause = Boolean(options && options.pause) && !flush;
  const began = Boolean(started) && !options.fresh;
  if (options && options.heavy) return takeHeavySpeech(held, began, flush, pause);
  return takeLightSpeech(held, began, flush, pause);
}

/**
 * Text in `full` that TTS has not already been fed (`spoken`).
 * Cursor often stores only the later answer, while the stream had the status intro.
 */
export function speechTail(spoken, full) {
  const have = String(spoken || "");
  const want = String(full || "");
  if (!want) return "";
  if (!have) return want;
  if (want.startsWith(have)) return want.slice(have.length);
  const haveTrim = have.trimEnd();
  const wantTrim = want.trimEnd();
  if (wantTrim.startsWith(haveTrim)) return wantTrim.slice(haveTrim.length);
  const compact = (text) => text.replace(/\s+/g, "");
  if (compact(have).includes(compact(wantTrim))) return "";
  const last = (haveTrim.split(/\n\s*\n/).pop() || haveTrim).trim();
  if (last) {
    const at = want.lastIndexOf(last);
    if (at >= 0) return want.slice(at + last.length);
  }
  return `\n\n${wantTrim}`;
}

/**
 * Bundle queued TTS clips. Mutates `pending` (shifts). Stops when pending is empty.
 * Prefetch (flush=false) packs up to `target` chars; end-of-reply packs up to `max`.
 */
export function takePendingClip(pending, { flush = false, target = TARGET_CHARS, max = MAX_CHARS, measure } = {}) {
  const sizeOf = typeof measure === "function" ? measure : (text) => String(text || "").length;
  let clip = "";
  while (pending.length) {
    const next = pending[0];
    if (!clip && sizeOf(next) > max) {
      const parts = splitSpeechClip(next, max, sizeOf);
      pending.shift();
      if (!parts.length) continue;
      clip = parts.shift();
      if (parts.length) pending.unshift(...parts);
      break;
    }
    const combined = clip ? `${clip}\n${next}` : next;
    if (clip && sizeOf(combined) > max) break;
    pending.shift();
    clip = combined;
    const size = sizeOf(clip);
    if (size < target) continue;
    if (!flush) break;
    if (!pending.length) break;
    if (sizeOf(`${clip}\n${pending[0]}`) > max) break;
  }
  return clip.trim();
}
