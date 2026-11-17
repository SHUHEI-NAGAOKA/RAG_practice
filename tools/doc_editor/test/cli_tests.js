/*
 * cli.js のテスト: 操作リストの ref を「元の番号」で書き、削除・合体で番号が詰まっても
 * 後の操作が正しい要素に当たるか（RefMapper の付け替え）を確かめる。
 * 入力: 元の コピー JSON / 出力: PASS・FAIL の一覧（失敗なら終了コード 1）
 * 実行: node tools/doc_editor/test/cli_tests.js
 */
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const C = require("../core.js");
const { applyOps } = require("../cli.js");

const ROOT = path.resolve(__dirname, "../../..");
const SRC_TEXT = fs.readFileSync(path.join(ROOT, "data/output/那須烏山市総合計画/那須烏山市総合計画のコピー.json"), "utf8");
const results = [];
function test(name, fn) {
  try { fn(C.parse(SRC_TEXT)); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, e.message]); }
}
const text = (d, r) => C.getItem(d, r).text;
const findText = (d, t) => d.texts.findIndex((x) => x.text === t);

test("T1 削除の後も元の番号で別の要素を編集できる", (d) => {
  const t2698 = text(d, "#/texts/2698"), t3000 = text(d, "#/texts/3000");
  applyOps(d, [
    { op: "delete", ref: "#/texts/2697" },
    { op: "setText", ref: "#/texts/2698", text: "【元2698】" + t2698 },   // 今は 2697
    { op: "setText", ref: "#/texts/3000", text: "【元3000】" + t3000 },   // 今は 2999
  ]);
  assert.strictEqual(text(d, "#/texts/2697"), "【元2698】" + t2698);
  assert.strictEqual(text(d, "#/texts/2999"), "【元3000】" + t3000);
  assert.ok(C.validate(d).ok);
});

test("T2 合体の後も元の番号で編集でき、合体先は元の番号で指せる", (d) => {
  const t4 = text(d, "#/texts/4"), t5 = text(d, "#/texts/5"), t9 = text(d, "#/texts/9");
  applyOps(d, [
    { op: "merge", refs: ["#/texts/4", "#/texts/5"], sep: "" },
    { op: "setText", ref: "#/texts/4", text: "【合体先】" },
    { op: "setText", ref: "#/texts/9", text: "【元9】" + t9 },
  ]);
  assert.strictEqual(text(d, "#/texts/4"), "【合体先】");
  assert.strictEqual(text(d, "#/texts/8"), "【元9】" + t9);
  assert.ok(t4 + t5); // 合体は成功
});

test("T3 削除・合体した要素を後で使うと分かりやすいエラーになる", (d) => {
  assert.throws(() => applyOps(d, [
    { op: "delete", ref: "#/texts/10" },
    { op: "setText", ref: "#/texts/10", text: "x" },
  ]), /削除・合体されています/);
});

test("T4 追加した要素を @new:n で指せる（その後に削除があっても）", (d) => {
  const r = applyOps(d, [
    { op: "addText", after: "#/pictures/5", text: "【追加A】" },
    { op: "delete", ref: "#/texts/1" },
    { op: "setText", ref: "@new:0", text: "【追加A・書き換え】" },
    { op: "addText", after: "@new:0", text: "【追加B】" },
  ]);
  assert.ok(findText(d, "【追加A・書き換え】") >= 0);
  const b = d.body.children.map((c) => c.$ref);
  const ia = b.indexOf(`#/texts/${findText(d, "【追加A・書き換え】")}`);
  assert.strictEqual(b[ia + 1], `#/texts/${findText(d, "【追加B】")}`);
  assert.strictEqual(r.added.length, 2);
  assert.ok(C.validate(d).ok);
});

test("T5 移動先・after・refs も付け替えられる", (d) => {
  const t2698 = text(d, "#/texts/2698");
  applyOps(d, [
    { op: "delete", ref: "#/texts/3" },
    { op: "move", refs: ["#/texts/2698"], target: "#/texts/7", index: 0 },  // 元 2698→2697、元7→6
  ]);
  assert.strictEqual(text(d, C.childRefs(d, "#/texts/6")[0]), t2698);
});

for (const r of results) console.log(r.join("\t"));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`\n${results.length - failed}/${results.length} PASS`);
process.exit(failed ? 1 : 0);
