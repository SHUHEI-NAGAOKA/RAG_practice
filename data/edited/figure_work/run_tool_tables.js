// doc_editor の画面（index.html）を jsdom で操作し、図の説明の要素の本文に「年ごとの数値」の箇条書きを足して書き出す
"use strict";
const fs = require("fs"), path = require("path"), assert = require("assert");
const { JSDOM } = require(path.resolve(__dirname, "../../../tools/doc_editor/node_modules/jsdom"));
const ROOT = path.resolve(__dirname, "../../..");
const SRC = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_figures.json");
const OUT = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_figures_v2.json");
const tables = JSON.parse(fs.readFileSync(path.join(__dirname, "figure_tables.json"), "utf8"));

(async () => {
  const dom = await JSDOM.fromFile(path.join(ROOT, "tools/doc_editor/index.html"), { runScripts: "dangerously", resources: "usable" });
  await new Promise((res) => (dom.window.DocEditor ? res() : dom.window.addEventListener("load", res)));
  const w = dom.window, $ = (id) => w.document.getElementById(id), C = w.DocCore;
  const click = (id) => { assert.ok(!$(id).disabled, `${id} が押せません`); $(id).click(); };
  const lastLog = () => $("log").lastElementChild.textContent;
  w.DocEditor.loadText(fs.readFileSync(SRC, "utf8"), path.basename(SRC));
  const doc = () => w.DocEditor.state.doc;
  const log = [];

  for (const [pic, t] of Object.entries(tables)) {
    // 図の説明の要素 = 図のすぐ後ろの兄弟で、本文に【図の説明】を含むもの
    const sibs = C.childRefs(doc(), C.parentRef(doc(), pic));
    const ref = sibs[sibs.indexOf(pic) + 1];
    const before = C.getItem(doc(), ref).text;
    assert.ok(before.includes("【図の説明】"), `${pic} の直後が図の説明ではありません: ${ref}`);
    assert.ok(!before.includes("【数値一覧】"), `${ref} は追加済みです`);
    const text = before + `\n【数値一覧】${t.title}\n` + t.rows.map((r) => `- ${r}`).join("\n");
    // 画面操作: ジャンプ → 行をクリック → 本文欄に入力 → 本文を反映（orig も同じ値に）
    $("jumpRef").value = ref; click("btnJump");
    w.document.querySelector(`.row[data-ref="${ref}"] .txt`).click();
    assert.strictEqual(w.DocEditor.state.focus, ref);
    $("textEdit").value = text;
    $("syncOrig").checked = true;
    click("btnText");
    assert.strictEqual(C.getItem(doc(), ref).text, text, lastLog());
    log.push(`${pic} → ${ref}：${t.rows.length} 行を追加`);
  }
  $("outName").value = path.basename(OUT);
  click("btnExport");
  assert.ok(w.DocEditor.state.lastExport, lastLog());
  fs.writeFileSync(OUT, w.DocEditor.state.lastExport);
  log.push(lastLog(), `出力: ${path.relative(ROOT, OUT)}`);
  fs.writeFileSync(path.join(__dirname, "run_tables.log"), log.join("\n") + "\n");
  console.log(log.join("\n"));
})().catch((e) => { console.error(e); process.exit(1); });
