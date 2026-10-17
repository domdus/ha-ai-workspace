const TARGET_CHARS = 280;
const MAX_CHARS = 560;

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
    .replace(/^[ \t]*\d+\.\s+/gm, "")
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
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

function pullSentence(text) {
  const para = /^[\s\S]*?\n\s*\n/.exec(text);
  const sentence = /^[\s\S]*?[.!?。！？]["»«”’')\]]*?(?=\s+(?:\p{Lu}|\p{Lt}|[„"«(])|\s*\n)/u.exec(text);
  let piece = "";
  if (sentence) piece = sentence[0];
  if (para && (!piece || para[0].length < piece.length)) piece = para[0];
  if (!piece) return null;
  return { piece, rest: text.slice(piece.length) };
}

function pullHeavyUnit(text) {
  const para = /^[\s\S]*?\n\s*\n/.exec(text);
  const introThenList = /^[^\n]+\n(?=[ \t]*(?:[-*•] |\d+\. ))/.exec(text);
  const listItem = /^(?:[ \t]*[-*•] |\d+\. ).+(?:\n|$)/.exec(text);
  const sentence = /^[\s\S]*?[.!?。！？]["»«”’')\]]*?(?=\s+(?:\p{Lu}|\p{Lt}|[„"«(])|\s*\n)/u.exec(text);
  const units = [para, introThenList, listItem, sentence].filter(Boolean);
  if (!units.length) return null;
  units.sort((a, b) => a[0].length - b[0].length);
  const piece = units[0][0];
  return { piece, rest: text.slice(piece.length) };
}

function trailingSentence(text) {
  const match = /^([\s\S]*?[.!?。！？]["»«”’')\]]*)\s*$/u.exec(text);
  if (!match || !match[1].trim()) return null;
  return { piece: match[0], rest: "" };
}

function takeLightSpeech(held, started, flush) {
  const pieces = [];
  let rest = String(held || "");
  let bundle = "";
  let open = !started;
  while (rest) {
    let next = pullSentence(rest);
    if (!next) {
      const tail = trailingSentence(rest);
      if (!tail || (open && !flush && speechIsShort(bundle + tail.piece))) break;
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
      const spoken = `${bundle}${rest}`.trim();
      if (spoken) pieces.push(spoken);
      rest = "";
    } else rest = bundle + rest;
  } else if (flush && rest.trim()) {
    pieces.push(rest.trim());
    rest = "";
  }
  return { pieces: pieces.filter(Boolean), rest };
}

function takeHeavySpeech(held, started, flush) {
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

  while (rest) {
    let next = pullHeavyUnit(rest);
    if (!next) {
      const tail = trailingSentence(rest);
      if (!tail) break;
      const nextSize = size(bundle + tail.piece);
      if (!flush && first && speechIsShort(bundle + tail.piece)) break;
      if (!flush && !first && nextSize < TARGET_CHARS) break;
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
    if (size(bundle) >= TARGET_CHARS) {
      emit();
      first = false;
    }
  }
  if (flush) {
    const spoken = `${bundle}${rest}`.trim();
    if (spoken) pieces.push(spoken);
    rest = "";
  } else rest = bundle + rest;
  return { pieces: pieces.filter(Boolean), rest };
}

export function takeSpeech(held, started, flush, options = {}) {
  if (options && options.heavy) return takeHeavySpeech(held, started, flush);
  return takeLightSpeech(held, started, flush);
}
