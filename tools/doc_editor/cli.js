#!/usr/bin/env node
/*
 * DoclingDocument エディター：コマンドライン版
 * GUI と同じ core.js を使い、操作リスト（JSON）を順に適用して書き出す。
 *
 * 使い方:
 *   node tools/doc_editor/cli.js <入力.json> <出力.json> [操作リスト.json] [--report <結果.json>]
 *
 * 入力: DoclingDocument JSON・操作リスト
 *   操作リスト: [{ "op": "setLabel", "ref": "#/texts/0", "label": "text" }, ...]
 *   使える op: setLabel / move / setText / updateItem / addText / merge / delete（core.js の OPS）
 * 出力: 操作後の JSON（検証エラーがあれば書き出さず終了コード 1）
 *       --report を付けると、各操作の結果（追加した要素の ref など）と元→今の ref の対応を JSON で書く
 *
 * 操作リストの ref はすべて「操作を始める前の文書」の番号で書いてよい。
 * 削除・合体で後ろの番号が詰まっても、後の操作の ref はこの CLI が今の番号に付け替える。
 * （追加した要素は "@new:<n>" で参照できる。n は addText の何番目か（0 から））
 */
"use strict";
const fs = require("fs");
const Core = require("./core.js");

// 操作の中で ref を持つ項目（単数・複数）
const REF_KEYS = ["ref", "target", "parent", "after", "provFrom"];
const REFS_KEYS = ["refs"];

// 元の番号 → 今の番号の対応を持ち、操作の ref を付け替える
// 最初に文書の全要素を「元＝今」で登録し、削除・合体のたびに全体を進める
class RefMapper {
  // 入力: 操作を始める前の文書
  constructor(doc) {
    this.map = new Map(Core.allRefs(doc).map((r) => [r, r])); // 元の ref → 今の ref（消えたら null）
    this.added = []; // addText で追加した要素の今の ref（"@new:n" 用。消えたら null）
  }
  // 入力: 元の ref（または "@new:n"、#/body など） / 出力: 今の ref（消えていれば例外）
  current(ref) {
    if (typeof ref !== "string") return ref;
    let r;
    if (ref.startsWith("@new:")) {
      r = this.added[Number(ref.slice(5))];
      if (r === undefined) throw new Error(`${ref} はまだ追加されていません`);
    } else {
      r = this.map.has(ref) ? this.map.get(ref) : ref; // #/body・#/furniture はそのまま
    }
    if (r === null) throw new Error(`${ref} は前の操作で削除・合体されています`);
    return r;
  }
  // 入力: 操作 / 出力: ref を今の番号にした操作（元の操作は変えない）
  translate(op) {
    const o = Object.assign({}, op);
    for (const k of REF_KEYS) if (k in o) o[k] = this.current(o[k]);
    for (const k of REFS_KEYS) if (Array.isArray(o[k])) o[k] = o[k].map((r) => this.current(r));
    return o;
  }
  // 削除・合体の結果を対応に反映する
  // 入力: resMap（Map: 操作前の今の ref → 操作後の ref。残った全要素を含む）・removed（消えた今の ref）
  update(resMap, removed) {
    const gone = new Set(removed || []);
    const step = (r) => (r === null || gone.has(r) ? null : resMap && resMap.has(r) ? resMap.get(r) : r);
    for (const [orig, cur] of this.map) this.map.set(orig, step(cur));
    this.added = this.added.map(step);
  }
}

// 入力: 文書・操作リスト / 出力: {results: 各操作の結果, mapping: 元→今の ref（変わったものだけ）, added}
function applyOps(doc, ops) {
  const mapper = new RefMapper(doc);
  const results = [];
  for (const [i, op] of ops.entries()) {
    const fn = Core.OPS && Core.OPS[op.op];
    if (!fn) throw new Error(`操作${i + 1}: 未知の操作 ${op.op}`);
    let o;
    try {
      o = mapper.translate(op);
    } catch (e) {
      throw new Error(`操作${i + 1}（${op.op}）: ${e.message}`);
    }
    const res = fn(doc, o);
    if (!res.ok) throw new Error(`操作${i + 1}（${op.op}）失敗: ${res.error}`);
    if (op.op === "addText") mapper.added.push(res.ref);
    if (res.map || res.removed) mapper.update(res.map, res.removed);
    results.push({ i, op: op.op, ref: res.ref || null, removed: res.removed ? res.removed.length : 0 });
  }
  const changed = [...mapper.map].filter(([a, b]) => a !== b);
  return { results, mapping: Object.fromEntries(changed), added: mapper.added };
}

function main() {
  const args = process.argv.slice(2);
  const ri = args.indexOf("--report");
  const reportPath = ri >= 0 ? args.splice(ri, 2)[1] : null;
  const [input, output, opsPath] = args;
  if (!input || !output) {
    console.error("使い方: node cli.js <入力.json> <出力.json> [操作リスト.json] [--report <結果.json>]");
    process.exit(2);
  }
  const doc = Core.parse(fs.readFileSync(input, "utf8"));
  const before = Core.validate(doc);
  let report = { results: [], mapping: {}, added: [] };
  if (opsPath) {
    try {
      report = applyOps(doc, JSON.parse(fs.readFileSync(opsPath, "utf8")));
    } catch (e) {
      console.error("エラー:", e.message);
      process.exit(1);
    }
  }

  const v = Core.validate(doc);
  v.warnings.forEach((w) => console.log("警告:", w));
  if (!v.ok) {
    v.errors.forEach((e) => console.error("エラー:", e));
    process.exit(1);
  }
  fs.writeFileSync(output, Core.serialize(doc));
  if (reportPath) {
    fs.writeFileSync(reportPath, JSON.stringify({
      ...report, ops: report.results.length, warnings_before: before.warnings.length, warnings_after: v.warnings.length,
    }, null, 2));
  }
  console.log(`出力: ${output}（操作 ${report.results.length} 件 / エラー0 / 警告${v.warnings.length}）`);
}

if (require.main === module) main();
module.exports = { applyOps, RefMapper };
