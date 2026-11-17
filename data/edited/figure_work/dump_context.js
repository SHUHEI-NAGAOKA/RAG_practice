// 対象の図（_target の付いた画像）ごとに、見出し・前後の本文・キャプション・図の中の文字を集める
"use strict";
const fs = require("fs"), path = require("path");
const C = require("../../../tools/doc_editor/core.js");
const ROOT = path.resolve(__dirname, "../../..");
const SRC = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_summary.json");
const ART = path.join(ROOT, "data/output/那須烏山市総合計画/那須烏山市総合計画_artifacts");
const d = C.parse(fs.readFileSync(SRC, "utf8"));
const targets = fs.readdirSync(ART).filter((f) => f.includes("_target"));
const byStem = new Map(d.pictures.map((p) => [path.basename(p.image.uri).replace(/\.png$/, ""), p]));
const order = [...C.descendants(d, "#/body")];
const strip = (t) => t.replace(/^【要約】[^\n]*\n/, "");
const txt = (r) => { const it = C.getItem(d, r); return it && typeof it.text === "string" ? it.text : null; };
const out = [];
for (const f of targets.sort()) {
  const p = byStem.get(f.replace("_target", "").replace(/\.png$/, ""));
  if (!p) { out.push({ file: f, inJson: false }); continue; }
  const r = p.self_ref;
  const heads = C.ancestors(d, r).reverse().map((a) => C.getItem(d, a)).filter((it) => it && it.label === "section_header").map((it) => strip(it.text));
  const inside = new Set(C.descendants(d, r));
  const idx = order.indexOf(r);
  const before = [], after = [];
  for (let i = idx - 1; i >= 0 && before.length < 3; i--) { const t = txt(order[i]); if (t && !inside.has(order[i]) && C.getItem(d, order[i]).label !== "section_header") before.unshift(strip(t)); }
  for (let i = idx + 1; i < order.length && after.length < 3; i++) { if (inside.has(order[i])) continue; const t = txt(order[i]); if (t) after.push(`[${C.getItem(d, order[i]).label}] ` + strip(t)); }
  const summary = (txt(C.childRefs(d, r)[0]) || txt(before.length ? order[idx - 1] : r) || "").match(/^【要約】[^\n]*/);
  out.push({
    file: f, ref: r, page: p.prov[0].page_no, parent: p.parent.$ref,
    headings: heads, captions: p.captions.map((c) => strip(txt(c.$ref))),
    inside: C.childRefs(d, r).map((c) => strip(txt(c) || "")).filter(Boolean).join(" ｜ ").slice(0, 400),
    before: before.map((t) => t.slice(0, 300)), after: after.map((t) => t.slice(0, 200)),
  });
}
fs.writeFileSync(path.join(__dirname, "contexts.json"), JSON.stringify(out, null, 1));
console.log(out.length, "件");
