#!/usr/bin/env node
/*
 * DoclingDocument エディター：コマンドライン版
 * GUI と同じ core.js を使い、操作リスト（JSON）を順に適用して書き出す。
 *
 * 使い方:
 *   node tools/doc_editor/cli.js <入力.json> <出力.json> [操作リスト.json]
 *
 * 操作リスト: [{ "op": "setLabel", "ref": "#/texts/0", "label": "text" }, ...]
 */
"use strict";
const fs = require("fs");
const Core = require("./core.js");

function applyOps(doc, ops) {
  for (const [i, o] of ops.entries()) {
    const fn = Core.OPS && Core.OPS[o.op];
    if (!fn) throw new Error(`操作${i + 1}: 未知の操作 ${o.op}`);
    const res = fn(doc, o);
    if (!res.ok) throw new Error(`操作${i + 1}（${o.op}）失敗: ${res.error}`);
  }
}

function main() {
  const [input, output, opsPath] = process.argv.slice(2);
  if (!input || !output) {
    console.error("使い方: node cli.js <入力.json> <出力.json> [操作リスト.json]");
    process.exit(2);
  }
  const doc = Core.parse(fs.readFileSync(input, "utf8"));
  if (opsPath) applyOps(doc, JSON.parse(fs.readFileSync(opsPath, "utf8")));

  const v = Core.validate(doc);
  v.warnings.forEach((w) => console.log("警告:", w));
  if (!v.ok) {
    v.errors.forEach((e) => console.error("エラー:", e));
    process.exit(1);
  }
  fs.writeFileSync(output, Core.serialize(doc));
  console.log(`出力: ${output}（エラー0 / 警告${v.warnings.length}）`);
}

if (require.main === module) main();
module.exports = { applyOps };
