// index.html（GUI）を jsdom で開き、ops.json の操作をボタン・入力欄で実行して書き出す
"use strict";
const fs = require("fs"), path = require("path"), assert = require("assert");
const TOOL = "/Users/nagaokashuuhei/Desktop/claude_project/project_dir/RAG_practice/tools/doc_editor";
const ROOT = path.resolve(TOOL, "../..");
const { JSDOM } = require(path.join(TOOL, "node_modules/jsdom"));
const SRC = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_nested.json");
const OUT = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_summary.json");
const ops = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

(async () => {
  const dom = await JSDOM.fromFile(path.join(TOOL, "index.html"), { runScripts: "dangerously", resources: "usable" });
  await new Promise((r) => (dom.window.DocEditor ? r() : dom.window.addEventListener("load", r)));
  const w = dom.window, $ = (id) => w.document.getElementById(id);
  const S = () => w.DocEditor.state;
  const log = () => ($("log").lastElementChild || {}).textContent || "";
  const click = (id) => { assert.ok(!$(id).disabled, `${id} が押せません`); $(id).click(); };
  const row = (ref) => w.document.querySelector(`.row[data-ref="${ref}"]`);
  const show = (ref) => { $("jumpRef").value = ref; click("btnJump"); assert.ok(row(ref), `${ref} の行がありません`); };
  const focus = (ref) => { show(ref); row(ref).querySelector(".txt").click(); assert.strictEqual(S().focus, ref); };
  const tick = (ref) => { show(ref); const cb = row(ref).querySelector("input[type=checkbox]"); if (!cb.checked) cb.click(); };
  const setLabel = (label, level) => {
    $("labelSelect").value = label; assert.strictEqual($("labelSelect").value, label, `候補に ${label} がない`);
    if (level) $("levelInput").value = String(level);
  };
  const changed = (before) => assert.notStrictEqual(JSON.stringify(S().doc), before, "変更されていません: " + log());

  w.DocEditor.loadText(fs.readFileSync(SRC, "utf8"), path.basename(SRC));
  let n = 0;
  for (const o of ops) {
    const before = JSON.stringify(S().doc);
    if (o.op === "text") {
      focus(o.ref); $("textEdit").value = o.text; $("syncOrig").checked = false; click("btnText");
      assert.strictEqual(w.DocCore.getItem(S().doc, o.ref).text, o.text, log());
    } else if (o.op === "label") {
      focus(o.ref); setLabel(o.label, o.level); click("btnLabelFocus"); changed(before);
    } else if (o.op === "bulkLabel") {
      if (!$("btnClear").disabled) click("btnClear"); for (const r of o.refs) tick(r);
      assert.strictEqual(S().checked.size, o.refs.length);
      setLabel(o.label, o.level); click("btnLabelChecked"); changed(before);
      for (const r of o.refs) assert.strictEqual(w.DocCore.getItem(S().doc, r).level, o.level, r);
      click("btnClear");
    } else if (o.op === "bulkMove") {
      if (!$("btnClear").disabled) click("btnClear");
      for (const r of o.refs) tick(r);
      assert.strictEqual(S().checked.size, o.refs.length);
      focus(o.target); click("btnSetTarget"); $("moveIndex").value = "";
      click("btnMoveChecked"); changed(before);
      const kids = w.DocCore.childRefs(S().doc, o.target);
      for (const r of o.refs) assert.ok(kids.includes(r), r + " が " + o.target + " の子になっていません");
    } else if (o.op === "stripDots") {
      focus(o.ref);
      const j = JSON.parse($("jsonView").value);
      const strip = (c) => { c.text = c.text.replace(/\s*(?:\.|…|‥|・){3,}\s*/g, " ").trim(); };
      j.data.table_cells.forEach(strip); j.data.grid.forEach((rw) => rw.forEach(strip));
      $("jsonView").value = JSON.stringify(j, null, 2); click("btnJson"); changed(before);
    }
    n++;
    if (n % 50 === 0 || n === ops.length) console.log(`OK ${n}/${ops.length} ${o.op} ${o.ref || o.refs.length + "件 level" + o.level}`);
  }
  click("btnValidate"); console.log("検証:", log());
  click("btnExport");
  assert.ok(S().lastExport, "書き出し失敗: " + log());
  fs.writeFileSync(OUT, S().lastExport);
  console.log("書き出し:", OUT, "|", log());
})().catch((e) => { console.error("FAIL", e.message); process.exit(1); });
