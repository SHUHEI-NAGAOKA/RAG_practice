/*
 * core.js の機能テスト（単体・組み合わせ）
 * 各テストは元 JSON の新しいコピーに操作を適用し、構造を検証してから
 * data/edited/tests/<名前>.json に書き出す。Python 側（check_outputs.py）で
 * DoclingDocument の読み込みとチャンク化を検証する。
 *
 * 実行: node tools/doc_editor/test/core_tests.js
 *
 * 使う階層（元データ）:
 *   L0 body
 *   L1 #/groups/169 (key_value_area) / #/groups/0 (list) / #/pictures/5 / #/texts/0
 *   L2 #/groups/170 (list, groups/169 の子) / #/pictures/5 の子 text
 *   L3 #/texts/2696〜2698 (list_item, groups/170 の子) ← 一番小さい子要素
 */
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const C = require("../core.js");

const ROOT = path.resolve(__dirname, "../../..");
const SRC = path.join(ROOT, "data/output/那須烏山市総合計画/那須烏山市総合計画のコピー.json");
const OUT = path.join(ROOT, "data/edited/tests");
fs.mkdirSync(OUT, { recursive: true });

const SRC_TEXT = fs.readFileSync(SRC, "utf8");
const BASE_WARN = C.validate(C.parse(SRC_TEXT)).warnings.length; // 元から 3件（空グループ）
const fresh = () => C.parse(SRC_TEXT);

const results = [];
const manifest = [];

function okRes(r) { assert.ok(r.ok, r.error); }
function ngRes(r, pattern) {
  assert.ok(!r.ok, "失敗するはずの操作が成功しました");
  if (pattern) assert.match(r.error, pattern);
}
const parentOf = (d, r) => C.parentRef(d, r);
const kids = (d, r) => C.childRefs(d, r);

function test(name, desc, fn, opts = {}) {
  const doc = fresh();
  try {
    const extra = fn(doc) || {};
    const v = C.validate(doc);
    assert.ok(v.ok, "検証エラー: " + v.errors.slice(0, 3).join(" / "));
    if (opts.maxWarn !== undefined) {
      assert.ok(v.warnings.length <= opts.maxWarn, `警告が多すぎます(${v.warnings.length}): ${v.warnings.join(" / ")}`);
    }
    const file = path.join(OUT, `${name}.json`);
    fs.writeFileSync(file, C.serialize(doc));
    manifest.push({ name, file, expect: extra.expect || [], expectDoc: extra.expectDoc || [], absent: extra.absent || [] });
    results.push(["PASS", name, desc, `警告${v.warnings.length}`]);
  } catch (e) {
    results.push(["FAIL", name, desc, e.message]);
  }
}

// ==========================================
// Stage 1: 読み込み → 書き出し
// ==========================================
test("S1_roundtrip", "無編集で書き出し（スキーマ検証のみ）", (d) => {
  assert.strictEqual(C.serialize(d).length > 0, true);
}, { maxWarn: BASE_WARN });

// ==========================================
// Stage 2: ラベル編集（単体）
// ==========================================
test("L1_text_to_header", "text → section_header（level が付く）", (d) => {
  okRes(C.setLabels(d, { refs: ["#/texts/1"], label: "section_header", level: 2 }));
  const it = C.getItem(d, "#/texts/1");
  assert.strictEqual(it.label, "section_header");
  assert.strictEqual(it.level, 2);
}, { maxWarn: BASE_WARN });

test("L2_header_to_text", "section_header → text（level が消える）", (d) => {
  okRes(C.setLabels(d, { refs: ["#/texts/0"], label: "text" }));
  const it = C.getItem(d, "#/texts/0");
  assert.strictEqual(it.label, "text");
  assert.ok(!("level" in it));
}, { maxWarn: BASE_WARN });

test("L3_listitem_to_text", "list_item → text（enumerated/marker が消える、リスト内なので警告+1）", (d) => {
  okRes(C.setLabels(d, { refs: ["#/texts/2696"], label: "text" }));
  const it = C.getItem(d, "#/texts/2696");
  assert.ok(!("enumerated" in it) && !("marker" in it));
}, { maxWarn: BASE_WARN + 1 });

test("L4_group_label", "グループのラベル key_value_area → section", (d) => {
  okRes(C.setLabels(d, { refs: ["#/groups/169"], label: "section" }));
  assert.strictEqual(C.getItem(d, "#/groups/169").label, "section");
}, { maxWarn: BASE_WARN });

test("L5_invalid_label", "不正なラベル（text に table / ルート）は拒否・無変更", (d) => {
  const before = C.serialize(d);
  ngRes(C.setLabels(d, { refs: ["#/texts/1"], label: "table" }), /使えません/);
  ngRes(C.setLabels(d, { refs: ["#/body"], label: "text" }));
  ngRes(C.setLabels(d, { refs: ["#/texts/1", "#/tables/0"], label: "text" })); // 1つでも不可なら全体中止
  assert.strictEqual(C.serialize(d), before);
}, { maxWarn: BASE_WARN });

test("L6_bulk_label", "一括ラベル変更（直下の子3件を section_header に）", (d) => {
  const refs = kids(d, "#/pictures/5");
  assert.strictEqual(refs.length, 3);
  okRes(C.setLabels(d, { refs, label: "section_header" }));
  refs.forEach((r) => assert.strictEqual(C.getItem(d, r).level, 1));
}, { maxWarn: BASE_WARN });

// ==========================================
// Stage 3: 階層変更（単体）
// ==========================================
test("M1_L3_to_body_top", "一番小さい子(L3)を一番上の親 body の先頭へ", (d) => {
  okRes(C.moveItems(d, { refs: ["#/texts/2696"], target: "#/body", index: 0 }));
  assert.strictEqual(kids(d, "#/body")[0], "#/texts/2696");
  assert.strictEqual(parentOf(d, "#/texts/2696"), "#/body");
  assert.ok(!kids(d, "#/groups/170").includes("#/texts/2696"));
  return { expect: ["①市内事業経営者"] };
}, { maxWarn: BASE_WARN + 1 }); // list_item がリスト外 → 警告（読み込み時に自動でリストに包まれる）

test("M2_L3_to_L1", "L3 の子を L1 の親（#/groups/0 リスト）へ", (d) => {
  okRes(C.moveItems(d, { refs: ["#/texts/2697"], target: "#/groups/0" }));
  const k = kids(d, "#/groups/0");
  assert.strictEqual(k[k.length - 1], "#/texts/2697");
  assert.strictEqual(parentOf(d, "#/texts/2697"), "#/groups/0");
}, { maxWarn: BASE_WARN });

test("M3_L1_subtree", "子を持つ L1 要素(#/pictures/5)を別の L1 の下へ（子も一緒に移動）", (d) => {
  const before = kids(d, "#/pictures/5");
  okRes(C.moveItems(d, { refs: ["#/pictures/5"], target: "#/groups/169" }));
  assert.strictEqual(parentOf(d, "#/pictures/5"), "#/groups/169");
  assert.deepStrictEqual(kids(d, "#/pictures/5"), before);
  assert.ok(!kids(d, "#/body").includes("#/pictures/5"));
}, { maxWarn: BASE_WARN });

test("M4_cycle_rejected", "自分の子孫や自分自身への移動は拒否・無変更", (d) => {
  const before = C.serialize(d);
  ngRes(C.moveItems(d, { refs: ["#/groups/169"], target: "#/texts/2696" }), /子孫/);
  ngRes(C.moveItems(d, { refs: ["#/groups/169"], target: "#/groups/169" }), /自分自身/);
  ngRes(C.moveItems(d, { refs: ["#/body"], target: "#/groups/0" }));
  ngRes(C.moveItems(d, { refs: ["#/texts/1"], target: "#/texts/99999" }), /存在しません/);
  assert.strictEqual(C.serialize(d), before);
}, { maxWarn: BASE_WARN });

test("M5_reorder_same_parent", "同じ親の中で並べ替え（body の 5番目を 1番目へ）", (d) => {
  const b = kids(d, "#/body");
  const r = b[5];
  okRes(C.moveItems(d, { refs: [r], target: "#/body", index: 1 }));
  const a = kids(d, "#/body");
  assert.strictEqual(a[1], r);
  assert.strictEqual(a.length, b.length);
  // 後ろ方向への移動（0番目を 3番目の位置へ）
  const r0 = a[0];
  okRes(C.moveItems(d, { refs: [r0], target: "#/body", index: 4 }));
  assert.strictEqual(kids(d, "#/body")[3], r0);
}, { maxWarn: BASE_WARN });

// ==========================================
// Stage 3: 一括選択・個別選択
// ==========================================
test("B1_bulk_direct_children", "直下の子を一括選択して body へ一括移動（順序を保持）", (d) => {
  const refs = kids(d, "#/pictures/7");
  okRes(C.moveItems(d, { refs, target: "#/body", index: 2 }));
  assert.deepStrictEqual(kids(d, "#/body").slice(2, 2 + refs.length), refs);
  assert.strictEqual(kids(d, "#/pictures/7").length, 0);
}, { maxWarn: BASE_WARN });

test("B2_bulk_descendants", "全子孫を一括選択（親子とも選択）→ 親ごと移動して内部構造を保持", (d) => {
  const desc = C.descendants(d, "#/groups/169");
  assert.ok(desc.includes("#/groups/170") && desc.includes("#/texts/2696"));
  assert.deepStrictEqual(C.topmost(d, desc), kids(d, "#/groups/169"));
  const inner = kids(d, "#/groups/170");
  okRes(C.moveItems(d, { refs: desc, target: "#/body", index: 0 }));
  assert.strictEqual(parentOf(d, "#/groups/170"), "#/body");
  assert.deepStrictEqual(kids(d, "#/groups/170"), inner); // 孫の親子関係はそのまま
}, { maxWarn: BASE_WARN + 1 }); // groups/169 が空になる → 警告

test("B3_individual_checks", "1つずつチェックして（別々の親・階層から）まとめて移動", (d) => {
  const checked = [];
  checked.push("#/texts/2698");                     // L3
  checked.push(kids(d, "#/pictures/10")[0]);         // L2
  checked.push(kids(d, "#/body")[1]);                // L1
  okRes(C.moveItems(d, { refs: checked, target: "#/groups/169", index: 0 }));
  assert.deepStrictEqual(kids(d, "#/groups/169").slice(0, 3), checked);
  checked.forEach((r) => assert.strictEqual(parentOf(d, r), "#/groups/169"));
}, { maxWarn: BASE_WARN + 1 }); // list_item がリスト外

// ==========================================
// Stage 4: バリュー編集（単体）
// ==========================================
test("V1_set_text", "本文の変更（orig も同期）", (d) => {
  okRes(C.setText(d, { ref: "#/texts/1", text: "令和5年度【編集テスト本文】", syncOrig: true }));
  const it = C.getItem(d, "#/texts/1");
  assert.strictEqual(it.text, "令和5年度【編集テスト本文】");
  assert.strictEqual(it.orig, it.text);
  return { expect: ["【編集テスト本文】"] };
}, { maxWarn: BASE_WARN });

test("V2_update_json", "JSON を直接編集（label と text と level を書き換え）", (d) => {
  const it = JSON.parse(C.serialize(C.getItem(d, "#/texts/2")));
  it.label = "section_header";
  it.level = 3;
  it.text = "【JSON編集した見出し】";
  okRes(C.updateItem(d, { ref: "#/texts/2", json: JSON.stringify(it) }));
  assert.strictEqual(C.getItem(d, "#/texts/2").level, 3);
  return { expect: ["【JSON編集した見出し】"] };
}, { maxWarn: BASE_WARN });

test("V3_update_rejects", "JSON 直接編集の拒否（構文エラー / parent 変更 / level なし見出し / 不正ラベル）", (d) => {
  const before = C.serialize(d);
  ngRes(C.updateItem(d, { ref: "#/texts/3", json: "{ broken" }), /構文/);
  const base = () => JSON.parse(C.serialize(C.getItem(d, "#/texts/3")));
  let o = base(); o.parent = { $ref: "#/groups/0" };
  ngRes(C.updateItem(d, { ref: "#/texts/3", json: o }), /parent/);
  o = base(); o.children = [{ $ref: "#/texts/4" }];
  ngRes(C.updateItem(d, { ref: "#/texts/3", json: o }), /children/);
  o = base(); o.label = "section_header"; // level が無い
  ngRes(C.updateItem(d, { ref: "#/texts/3", json: o }), /level/);
  o = base(); o.label = "picture";
  ngRes(C.updateItem(d, { ref: "#/texts/3", json: o }), /使えません/);
  assert.strictEqual(C.serialize(d), before);
}, { maxWarn: BASE_WARN });

// ==========================================
// 組み合わせ
// ==========================================
test("C1_label_then_move", "ラベル変更してから移動（list_item→text にして body 先頭へ）", (d) => {
  okRes(C.setLabels(d, { refs: ["#/texts/3223"], label: "text" }));
  okRes(C.moveItems(d, { refs: ["#/texts/3223"], target: "#/body", index: 0 }));
  assert.strictEqual(kids(d, "#/body")[0], "#/texts/3223");
}, { maxWarn: BASE_WARN + 1 }); // groups/192 が空になる

test("C2_move_then_label_then_text", "移動 → ラベル変更 → 本文編集（L3 を L1 に上げて見出し化）", (d) => {
  okRes(C.moveItems(d, { refs: ["#/texts/2696"], target: "#/body", index: 0 }));
  okRes(C.setLabels(d, { refs: ["#/texts/2696"], label: "section_header", level: 1 }));
  okRes(C.setText(d, { ref: "#/texts/2696", text: "【昇格した見出し】", syncOrig: true }));
  const it = C.getItem(d, "#/texts/2696");
  assert.ok(it.label === "section_header" && !("marker" in it));
  // 直後が同レベル見出しで本文が無いため、チャンクではなく docling 上の要素で確認
  return { expectDoc: [{ ref: "#/texts/2696", label: "section_header", text: "【昇格した見出し】", parent: "#/body" }] };
}, { maxWarn: BASE_WARN });

test("C3_bulk_label_bulk_move", "一括選択 → 一括ラベル変更 → 一括移動（リストの子を text にして別の親へ）", (d) => {
  const refs = kids(d, "#/groups/1");
  okRes(C.setLabels(d, { refs, label: "text" }));
  okRes(C.moveItems(d, { refs, target: "#/groups/169", index: 0 }));
  assert.deepStrictEqual(kids(d, "#/groups/169").slice(0, refs.length), refs);
}, { maxWarn: BASE_WARN + 1 }); // groups/1 が空

test("C4_individual_and_bulk_mix", "個別チェック + 一括チェックを混ぜて移動し、その後 JSON 編集", (d) => {
  const sel = new Set(kids(d, "#/pictures/10"));  // 一括（直下の子）
  sel.add("#/texts/2698");                         // 個別（L3）
  sel.delete(kids(d, "#/pictures/10")[1]);         // 個別にチェックを外す
  const refs = [...sel];
  okRes(C.setLabels(d, { refs: ["#/texts/2698"], label: "text" }));
  okRes(C.moveItems(d, { refs, target: "#/texts/0" })); // 見出し要素の下へ
  assert.deepStrictEqual(kids(d, "#/texts/0"), refs);
  const o = JSON.parse(C.serialize(C.getItem(d, refs[0])));
  o.text = "【混在操作後の本文】";
  okRes(C.updateItem(d, { ref: refs[0], json: o }));
  return { expect: ["【混在操作後の本文】"] };
}, { maxWarn: BASE_WARN });

test("C5_all_features", "全機能を順に使用（ラベル・単体移動・一括移動・並べ替え・本文・JSON編集）", (d) => {
  // 1. L3 → body 先頭、ラベルを text に
  okRes(C.setLabels(d, { refs: ["#/texts/2696"], label: "text" }));
  okRes(C.moveItems(d, { refs: ["#/texts/2696"], target: "#/body", index: 0 }));
  // 2. L3 → L1（リストへ）
  okRes(C.moveItems(d, { refs: ["#/texts/2697"], target: "#/groups/0" }));
  // 3. L1 サブツリー → L1 の下
  okRes(C.moveItems(d, { refs: ["#/pictures/5"], target: "#/groups/169" }));
  // 4. 全子孫選択 → 親ごと移動
  okRes(C.moveItems(d, { refs: C.descendants(d, "#/groups/191"), target: "#/body", index: 1 }));
  // 5. 一括ラベル変更
  okRes(C.setLabels(d, { refs: kids(d, "#/pictures/7"), label: "section_header", level: 2 }));
  // 6. 並べ替え
  okRes(C.moveItems(d, { refs: [kids(d, "#/body")[3]], target: "#/body", index: 0 }));
  // 7. 本文変更・JSON 編集
  okRes(C.setText(d, { ref: "#/texts/1", text: "【全機能テスト】", syncOrig: true }));
  const o = JSON.parse(C.serialize(C.getItem(d, "#/groups/169")));
  o.name = "edited-group";
  okRes(C.updateItem(d, { ref: "#/groups/169", json: o }));
  assert.strictEqual(C.getItem(d, "#/groups/169").name, "edited-group");
  return { expect: ["【全機能テスト】"] };
}, { maxWarn: BASE_WARN + 1 }); // groups/191 が空

// ==========================================
// Stage 5: 要素の追加
// ==========================================
test("A1_add_after", "#/pictures/5 の直後（兄弟）に本文を追加（ページ位置を引き継ぐ）", (d) => {
  const n = d.texts.length;
  const res = C.addText(d, { after: "#/pictures/5", text: "【追加した図の説明】テスト" });
  okRes(res);
  assert.strictEqual(res.ref, `#/texts/${n}`);
  const b = kids(d, "#/body");
  assert.strictEqual(b[b.indexOf("#/pictures/5") + 1], res.ref);
  const it = C.getItem(d, res.ref);
  assert.strictEqual(it.parent.$ref, "#/body");
  assert.strictEqual(it.prov[0].page_no, C.getItem(d, "#/pictures/5").prov[0].page_no);
  assert.strictEqual(it.orig, it.text);
  return { expect: ["【追加した図の説明】テスト"] };
}, { maxWarn: BASE_WARN });

test("A2_add_child_header_and_text", "見出し（L2）を子として追加し、その直後に本文を追加", (d) => {
  const h = C.addText(d, { parent: "#/body", index: 0, label: "section_header", level: 2, text: "【追加見出し】" });
  okRes(h);
  assert.strictEqual(kids(d, "#/body")[0], h.ref);
  assert.strictEqual(C.getItem(d, h.ref).level, 2);
  const t = C.addText(d, { after: h.ref, text: "【追加見出しの本文】", provFrom: "#/texts/0" });
  okRes(t);
  assert.strictEqual(kids(d, "#/body")[1], t.ref);
  return { expect: ["【追加見出しの本文】"] };
}, { maxWarn: BASE_WARN });

test("A3_add_list_item", "リスト（#/groups/170）の先頭に list_item を追加（enumerated/marker が付く）", (d) => {
  const res = C.addText(d, { parent: "#/groups/170", index: 0, label: "list_item", text: "【追加した項目】" });
  okRes(res);
  const it = C.getItem(d, res.ref);
  assert.ok("enumerated" in it && "marker" in it && !("level" in it));
  assert.strictEqual(kids(d, "#/groups/170")[0], res.ref);
  return { expect: ["【追加した項目】"] };
}, { maxWarn: BASE_WARN });

test("A4_add_rejects", "追加の拒否（空の本文 / 不正ラベル / 存在しない親 / ルートの直後）・無変更", (d) => {
  const before = C.serialize(d);
  ngRes(C.addText(d, { after: "#/texts/1", text: "" }), /本文/);
  ngRes(C.addText(d, { after: "#/texts/1", text: "x", label: "picture" }), /使えません/);
  ngRes(C.addText(d, { parent: "#/texts/99999", text: "x" }), /存在しません/);
  ngRes(C.addText(d, { after: "#/body", text: "x" }), /追加できません/);
  ngRes(C.addText(d, { after: "#/texts/1", text: "x", label: "section_header", level: 0 }), /level/);
  assert.strictEqual(C.serialize(d), before);
}, { maxWarn: BASE_WARN });

// ==========================================
// Stage 6: 要素の削除（番号の詰め直し）
// ==========================================
test("D1_delete_leaf", "末端の要素（L3 #/texts/2697）を削除 → 後ろの番号が詰まり参照も書き換わる", (d) => {
  const n = d.texts.length;
  const nextText = C.getItem(d, "#/texts/2698").text;
  const lastText = C.getItem(d, `#/texts/${n - 1}`).text;
  const res = C.deleteItems(d, { refs: ["#/texts/2697"] });
  okRes(res);
  assert.strictEqual(d.texts.length, n - 1);
  assert.strictEqual(C.getItem(d, "#/texts/2697").text, nextText); // 旧 2698 が 2697 に
  assert.strictEqual(C.parentRef(d, "#/texts/2697"), "#/groups/170");
  assert.deepStrictEqual(kids(d, "#/groups/170"), ["#/texts/2696", "#/texts/2697"]);
  assert.strictEqual(C.getItem(d, `#/texts/${n - 2}`).text, lastText);
  assert.strictEqual(res.map.get("#/texts/2698"), "#/texts/2697");
  return { absent: ["②子育て世代・女性団体との意見交換会"], expect: ["③タウンミーティング"] };
}, { maxWarn: BASE_WARN });

test("D2_delete_keep_children", "子を持つ #/pictures/5 を削除し、子は同じ位置に繰り上げ", (d) => {
  const np = d.pictures.length;
  const picKids = kids(d, "#/pictures/5").map((r) => C.getItem(d, r).text);
  const idx = kids(d, "#/body").indexOf("#/pictures/5");
  okRes(C.deleteItems(d, { refs: ["#/pictures/5"], keepChildren: true }));
  assert.strictEqual(d.pictures.length, np - 1);
  const b = kids(d, "#/body");
  assert.deepStrictEqual(b.slice(idx, idx + picKids.length).map((r) => C.getItem(d, r).text), picKids);
  b.slice(idx, idx + picKids.length).forEach((r) => assert.strictEqual(C.parentRef(d, r), "#/body"));
}, { maxWarn: BASE_WARN });

test("D3_delete_subtree", "#/groups/169 を子孫ごと削除（groups と texts の両方の番号が詰まる）", (d) => {
  const ng = d.groups.length, nt = d.texts.length;
  const desc = C.descendants(d, "#/groups/169");
  const nDescTexts = desc.filter((r) => C.arrayOf(r) === "texts").length;
  okRes(C.deleteItems(d, { refs: ["#/groups/169"], keepChildren: false }));
  assert.strictEqual(d.texts.length, nt - nDescTexts);
  assert.strictEqual(d.groups.length, ng - 1 - desc.filter((r) => C.arrayOf(r) === "groups").length);
  return { absent: ["①市内事業経営者、まちづくり団体等との意見交換会"] };
}, { maxWarn: BASE_WARN });

test("D4_delete_caption", "図のキャプション（#/texts/245）を削除 → 図の captions からも消える", (d) => {
  assert.deepStrictEqual(d.pictures[22].captions.map((c) => c.$ref), ["#/texts/245"]);
  okRes(C.deleteItems(d, { refs: ["#/texts/245"] }));
  assert.deepStrictEqual(d.pictures[22].captions, []);
  assert.deepStrictEqual(d.pictures[23].captions.map((c) => c.$ref), ["#/texts/441"]); // 旧 442
}, { maxWarn: BASE_WARN });

test("D5_delete_rejects", "削除の拒否（ルート / 存在しない要素 / 未選択）・無変更", (d) => {
  const before = C.serialize(d);
  ngRes(C.deleteItems(d, { refs: ["#/body"] }), /削除できません/);
  ngRes(C.deleteItems(d, { refs: ["#/texts/99999"] }), /存在しません/);
  ngRes(C.deleteItems(d, { refs: [] }), /選択/);
  assert.strictEqual(C.serialize(d), before);
}, { maxWarn: BASE_WARN });

// ==========================================
// Stage 7: 要素の合体
// ==========================================
test("G1_merge_siblings", "見出しの続き（#/texts/6 と 7）を合体（つなぎ文字なし）", (d) => {
  const t6 = C.getItem(d, "#/texts/6").text, t7 = C.getItem(d, "#/texts/7").text;
  const n = d.texts.length;
  const res = C.mergeTexts(d, { refs: ["#/texts/7", "#/texts/6"] }); // 選択順に関係なく並び順の先頭へ
  okRes(res);
  assert.strictEqual(res.ref, "#/texts/6");
  assert.strictEqual(C.getItem(d, "#/texts/6").text, t6 + t7);
  assert.strictEqual(C.getItem(d, "#/texts/6").prov.length, 2);
  assert.strictEqual(d.texts.length, n - 1);
  assert.strictEqual(kids(d, "#/body")[7], "#/pictures/0"); // 旧 texts/7 の位置が詰まる
  return { expectDoc: [{ ref: "#/texts/6", label: "section_header", text: t6 + t7, parent: "#/body" }] };
}, { maxWarn: BASE_WARN });

test("G2_merge_with_children_sep", "子を持つ要素を改行つなぎで合体 → 子は先頭の要素へ移る", (d) => {
  okRes(C.moveItems(d, { refs: ["#/texts/2696"], target: "#/texts/5" })); // texts/5 に子を作る
  okRes(C.setLabels(d, { refs: ["#/texts/2696"], label: "text" }));
  const t4 = C.getItem(d, "#/texts/4").text, t5 = C.getItem(d, "#/texts/5").text;
  const res = C.mergeTexts(d, { refs: ["#/texts/4", "#/texts/5"], sep: "\n" });
  okRes(res);
  assert.strictEqual(C.getItem(d, "#/texts/4").text, t4 + "\n" + t5);
  const moved = kids(d, "#/texts/4");
  assert.strictEqual(moved.length, 1);
  assert.ok(C.getItem(d, moved[0]).text.startsWith("①市内事業経営者"));
  return { expect: ["①市内事業経営者"] };
}, { maxWarn: BASE_WARN });

test("G3_merge_rejects", "合体の拒否（1件のみ / 本文を持たない要素）・無変更", (d) => {
  const before = C.serialize(d);
  ngRes(C.mergeTexts(d, { refs: ["#/texts/4"] }), /2 件以上/);
  ngRes(C.mergeTexts(d, { refs: ["#/texts/4", "#/groups/0"] }), /合体できません/);
  ngRes(C.mergeTexts(d, { refs: ["#/texts/4", "#/pictures/5"] }), /合体できません/);
  assert.strictEqual(C.serialize(d), before);
}, { maxWarn: BASE_WARN });

test("C6_add_merge_delete_mix", "追加 → 移動 → 合体 → 削除 → ラベル変更を続けて使用", (d) => {
  const a = C.addText(d, { after: "#/pictures/5", text: "【組合せ-追加1】" });
  okRes(a);
  const b = C.addText(d, { after: a.ref, text: "【組合せ-追加2】" });
  okRes(b);
  okRes(C.moveItems(d, { refs: [b.ref], target: "#/body", index: kids(d, "#/body").indexOf(a.ref) + 1 }));
  const m = C.mergeTexts(d, { refs: [a.ref, b.ref], sep: " / " });
  okRes(m);
  okRes(C.deleteItems(d, { refs: ["#/texts/2697", "#/texts/2698"] }));
  okRes(C.setLabels(d, { refs: ["#/texts/2696"], label: "text" }));
  const merged = d.texts.find((t) => t.text === "【組合せ-追加1】 / 【組合せ-追加2】");
  assert.ok(merged, "合体した要素が見つかりません");
  return { expect: ["【組合せ-追加1】 / 【組合せ-追加2】"], absent: ["③タウンミーティング"] };
}, { maxWarn: BASE_WARN + 1 }); // texts/2696 の list_item→text でリスト内に text（警告）

// ==========================================
fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
for (const r of results) console.log(r.join("\t"));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`\n${results.length - failed}/${results.length} PASS`);
process.exit(failed ? 1 : 0);
