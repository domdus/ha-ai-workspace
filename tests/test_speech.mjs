import { takeSpeech, speechPlain } from "../custom_components/ai_workspace/www/speech.js";

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

console.log("ok");
