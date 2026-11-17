// doc_editor の画面（index.html）を jsdom で操作し、図ごとに「図の説明」の要素を図の直後に追加して書き出す
"use strict";
const fs = require("fs"), path = require("path"), assert = require("assert");
const { JSDOM } = require(path.resolve(__dirname, "../../../tools/doc_editor/node_modules/jsdom"));
const ROOT = path.resolve(__dirname, "../../..");
const TOOL = path.join(ROOT, "tools/doc_editor");
const SRC = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_summary.json");
const OUT = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_figures.json");

const rows = fs.readFileSync(path.join(__dirname, "descriptions.tsv"), "utf8").trim().split("\n").slice(1)
  .map((l) => { const [ref, title, context, content] = l.split("\t"); return { ref, title, context, content }; });

(async () => {
  const dom = await JSDOM.fromFile(path.join(TOOL, "index.html"), { runScripts: "dangerously", resources: "usable" });
  await new Promise((res) => (dom.window.DocEditor ? res() : dom.window.addEventListener("load", res)));
  const w = dom.window, $ = (id) => w.document.getElementById(id), C = w.DocCore;
  const click = (id) => { assert.ok(!$(id).disabled, `${id} が押せません`); $(id).click(); };
  const lastLog = () => $("log").lastElementChild.textContent;
  w.DocEditor.loadText(fs.readFileSync(SRC, "utf8"), path.basename(SRC));
  const doc = () => w.DocEditor.state.doc;
  const log = [];

  for (const r of rows) {
    // 親の要約（同じ親の下の本文に付いている【要約】の行）を先頭に付ける
    const parent = C.parentRef(doc(), r.ref);
    let summary = "";
    for (const sib of [...C.childRefs(doc(), parent), ...C.descendants(doc(), r.ref)]) {
      const t = C.getItem(doc(), sib).text;
      const m = typeof t === "string" && t.match(/^【要約】[^\n]*/);
      if (m) { summary = m[0]; break; }
    }
    const text = (summary ? summary + "\n" : "") +
      `【図の説明】${r.title}\n文脈：${r.context}\n図の内容：${r.content}`;
    // 画面操作: ジャンプ → 行をクリック（フォーカス）→ 追加欄に入力 → 追加
    $("jumpRef").value = r.ref; click("btnJump");
    w.document.querySelector(`.row[data-ref="${r.ref}"] .txt`).click();
    assert.strictEqual(w.DocEditor.state.focus, r.ref);
    $("addLabel").value = "text"; $("addPos").value = "after"; $("addText").value = text;
    click("btnAdd");
    const added = w.DocEditor.state.focus;
    const sibs = C.childRefs(doc(), parent);
    assert.strictEqual(sibs[sibs.indexOf(r.ref) + 1], added, lastLog());
    log.push(`${r.ref} → ${added}（親 ${parent}、要約${summary ? "あり" : "なし"}）`);
  }
  $("outName").value = path.basename(OUT);
  click("btnExport");
  assert.ok(w.DocEditor.state.lastExport, lastLog());
  fs.writeFileSync(OUT, w.DocEditor.state.lastExport);
  log.push(lastLog(), `出力: ${path.relative(ROOT, OUT)}`);
  fs.writeFileSync(path.join(__dirname, "run.log"), log.join("\n") + "\n");
  console.log(log.join("\n"));
})().catch((e) => { console.error(e); process.exit(1); });
