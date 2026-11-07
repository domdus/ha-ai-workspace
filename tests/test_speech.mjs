import { takeSpeech, speechPlain, takePendingClip } from "../custom_components/ai_workspace/www/speech.js";

function eq(actual, expected, label) {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) throw new Error(`${label}: ${left} !== ${right}`);
}

eq(takeSpeech("Hi! I'm here.", false, true).pieces, ["Hi! I'm here."], "short greeting with a second sentence");
eq(takeSpeech("Hi there!", false, true).pieces, ["Hi there!"], "short flush");
eq(takeSpeech("You’re talking to OpenAI gpt-5.", false, true).pieces, ["You’re talking to OpenAI gpt-5."], "one sentence");
eq(takeSpeech("Hi!", false, false).rest, "Hi!", "hold a short opener until more text arrives");

const streamed = takeSpeech("Hello there. More text follows now.", false, true);
if (!streamed.pieces.join(" ").includes("More text follows now.")) {
  throw new Error("flush dropped the rest of the reply");
}

const two = takeSpeech(
  "The kitchen lights are already on. The hallway motion light is also on.",
  false,
  true,
);
if (two.pieces.length < 2) {
  throw new Error(`google-style chunking should emit sentences: ${JSON.stringify(two.pieces)}`);
}

const list = `Here are your automations:
- [Close balcony reminder](/config/automation/edit/close_balcony_reminder) — on
- [Evening living room lights](/config/automation/edit/evening_living_room) — on
- [Hallway motion light](/config/automation/edit/hallway_motion_light) — on`;
const firstLook = takeSpeech(
  "Ich suche in der Installation nach Bewässerung und dem heutigen Verlauf.",
  false,
  false,
  { heavy: true },
);
if (firstLook.pieces.length !== 1 || !firstLook.pieces[0].includes("Bewässerung")) {
  throw new Error(`heavy TTS should speak the first sentence immediately: ${JSON.stringify(firstLook)}`);
}

const listed = takeSpeech(list, false, true, { heavy: true });
eq(listed.pieces.length, 1, "heavy TTS keeps a short list as one clip");
if (!listed.pieces[0].includes("Here are your automations")) {
  throw new Error(`list intro missing: ${JSON.stringify(listed.pieces)}`);
}
eq(
  speechPlain(list).split("\n")[1],
  "Close balcony reminder — on",
  "plain speech drops markdown links",
);

const lightList = takeSpeech(list, false, true);
eq(lightList.pieces.length, 1, "google-style flush still speaks a list without sentence punctuation");

const steps = speechPlain("Here are the steps:\n1. Turn off the kitchen lights.\n2. Close the blinds\n3. Lock the door");
eq(steps, "Here are the steps:\n1. Turn off the kitchen lights.\n2. Close the blinds.\n3. Lock the door.", "numbered items keep 1. and end with a period");
for (const heavy of [false, true]) {
  const spoken = takeSpeech(steps, heavy, true).pieces;
  if (spoken.some((piece) => /^\d+\.$/.test(piece.trim()))) {
    throw new Error(`a list number was spoken on its own: ${JSON.stringify(spoken)}`);
  }
}
eq(takeSpeech("The kitchen is off. 2.", false, false).pieces.includes("2."), false, "hold a list number until its item arrives");

const p1 = "Ich mache 1.5.0b18 fertig — zuerst schaue ich, wie die letzten Betas rausgekommen sind.";
const p2 = "Ich schaue die Änderungen und den letzten Release-Ablauf an, dann kommt 1.5.0b18.";
const p3 =
  "Version, Changelog und Release kommen jetzt auf 1.5.0b18. Runtime bleibt b13, nur die Nummer zieht mit.";
const firstStatus = takeSpeech(p1, false, false, { heavy: true });
eq(firstStatus.pieces.length, 1, "first status paragraph speaks immediately");
if (!firstStatus.pieces[0].includes("1.5.0b18")) {
  throw new Error(`first status missing: ${JSON.stringify(firstStatus)}`);
}

const heldNext = takeSpeech(`\n\n${p2}`, true, false, { heavy: true });
eq(heldNext.pieces.length, 0, "second short paragraph waits while text may still grow");
if (!heldNext.rest.includes("Änderungen")) {
  throw new Error(`second paragraph should stay held: ${JSON.stringify(heldNext)}`);
}

const afterPause = takeSpeech(heldNext.rest, true, false, { heavy: true, pause: true });
eq(afterPause.pieces.length, 1, "thinking pause speaks the held paragraph");
if (!afterPause.pieces[0].includes("Änderungen")) {
  throw new Error(`pause should speak paragraph two: ${JSON.stringify(afterPause)}`);
}

const twoParas = takeSpeech(`${p2}\n\n${p3}`, true, false, { heavy: true });
if (twoParas.pieces.length !== 1 || !twoParas.pieces[0].includes("Änderungen")) {
  throw new Error(`blank line should speak the finished paragraph: ${JSON.stringify(twoParas)}`);
}
if (!twoParas.rest.includes("Changelog")) {
  throw new Error(`later paragraph stays held until it is complete: ${JSON.stringify(twoParas)}`);
}

const thirdPause = takeSpeech(twoParas.rest, true, false, { heavy: true, pause: true });
if (thirdPause.pieces.length !== 1 || !thirdPause.pieces[0].includes("Changelog")) {
  throw new Error(`pause should speak paragraph three: ${JSON.stringify(thirdPause)}`);
}

eq(takeSpeech("Hi!", false, false, { pause: true }).pieces, ["Hi!"], "pause speaks a short complete opener");
eq(takeSpeech("Hi!", false, false).rest, "Hi!", "without a pause the short opener still waits");

eq(takePendingClip([]), "", "empty pending yields no clip");
{
  const pending = ["Short one.", "Also short."];
  eq(takePendingClip(pending), "Short one.\nAlso short.", "prefetch bundles short paragraphs");
  eq(pending.length, 0, "bundling consumes pending");
}
{
  const first = "A".repeat(280);
  const second = "B".repeat(200);
  const pending = [first, second, "tail"];
  const clip = takePendingClip(pending);
  eq(clip, first, "prefetch stops once the clip reaches 280");
  eq(pending.join("|"), `${second}|tail`, "leftover stays queued");
}
{
  const a = "A".repeat(200);
  const b = "B".repeat(200);
  const pending = [a, b];
  const clip = takePendingClip(pending, { flush: true });
  eq(clip, `${a}\n${b}`, "flush packs remaining shorts into one clip");
  eq(pending.length, 0, "flush drains pending");
}
{
  const pending = [];
  eq(takePendingClip(pending, { flush: true }), "", "empty pending does not loop");
}

console.log("ok");
