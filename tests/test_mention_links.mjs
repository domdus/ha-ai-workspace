/**
 * Automatic name links in replies (chat.js linkifyHaMentions).
 * Run: node tests/test_mention_links.mjs
 */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../custom_components/ai_workspace/www/chat.js", import.meta.url), "utf8");
const grab = (name) => {
  const start = src.indexOf(name);
  if (start < 0) throw new Error(`missing ${name}`);
  let depth = 0;
  for (let i = src.indexOf("{", start); i < src.length; i++) {
    if (src[i] === "{") depth++;
    if (src[i] === "}" && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error(`unclosed ${name}`);
};
const line = (prefix) => src.split("\n").find((row) => row.startsWith(prefix));
const states = {
  "zone.home": { attributes: { friendly_name: "Home" } },
  "conversation.home_assistant": { attributes: { friendly_name: "Home Assistant" } },
  "automation.bewasserung": { attributes: { friendly_name: "Bewässerung" } },
  "light.kitchen_main": { attributes: { friendly_name: "Kitchen Main" } },
};
const code = [
  line("const UNLINKED_NAMES"),
  line("const QUOTED"),
  grab("function escapeRe("),
  grab("function rememberUniqueName("),
  "let linkCatalog = null;",
  grab("function mentionPattern("),
  grab("function haLinkCatalog("),
  grab("function linkifyHaMentions("),
  "return linkifyHaMentions;",
].join("\n");
const linkify = new Function(
  "hassObj",
  "pathForEntity",
  "linkifyHaPaths",
  code,
)(() => ({ states, entities: {}, devices: { d1: { id: "d1", name: "Wohnzimmer" } } }), (id) => `/e/${id}`, (t) => t);

let failed = 0;
const ok = (cond, label) => {
  if (!cond) failed++;
  console.log(`${cond ? "ok" : "FAIL"} ${label}`);
};

ok(linkify("Back Home in Wohnzimmer.") === "Back Home in Wohnzimmer.", "one-word names stay plain");
ok(linkify("Asked Home Assistant.") === "Asked Home Assistant.", "Home Assistant stays plain");
ok(linkify("Kitchen Main is on.") === "[Kitchen Main](/e/light.kitchen_main) is on.", "longer names link");
ok(
  linkify("Kitchen Main is on, Kitchen Main stays on.") === "[Kitchen Main](/e/light.kitchen_main) is on, Kitchen Main stays on.",
  "only the first mention links",
);
ok(linkify("Section „Kitchen Main“ is open.") === "Section „Kitchen Main“ is open.", "quoted names stay plain");
ok(linkify('Card "Kitchen Main" moved.') === 'Card "Kitchen Main" moved.', "straight quotes too");
ok(linkify("See light.kitchen_main now").includes("[light.kitchen_main](/e/light.kitchen_main)"), "entity ids still link");
ok(linkify("[Kitchen Main](/x) and Kitchen Main") === "[Kitchen Main](/x) and [Kitchen Main](/e/light.kitchen_main)", "agent links stay as written");

if (failed) {
  console.error(`${failed} failed`);
  process.exit(1);
}
