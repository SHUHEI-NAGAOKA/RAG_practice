/*
 * GUI（index.html）の操作テスト
 * jsdom で index.html を実際に読み込み、ボタン・チェックボックス・入力欄を操作して検証する。
 * 書き出したJSONは data/edited/ui_tests/ に保存し、check_outputs.py で docling 検証する。
 *
 * 実行: node tools/doc_editor/test/ui_tests.js
 * 最後の GOAL では コピーJSON を編集して data/edited/那須烏山市総合計画のコピー_edited.json を書き出す。
 */
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const { JSDOM } = require("jsdom");

const TOOL = path.resolve(__dirname, "..");
const ROOT = path.resolve(TOOL, "../..");
const SRC = path.join(ROOT, "data/output/那須烏山市総合計画/那須烏山市総合計画のコピー.json");
const OUT = path.join(ROOT, "data/edited/ui_tests");
const GOAL_OUT = path.join(ROOT, "data/edited/那須烏山市総合計画のコピー_edited.json");
fs.mkdirSync(OUT, { recursive: true });
const SRC_TEXT = fs.readFileSync(SRC, "utf8");

// ==========================================
// GUI を開いて操作するための小さなドライバー
// ==========================================
async function openEditor() {
  const dom = await JSDOM.fromFile(path.join(TOOL, "index.html"), {
    runScripts: "dangerously",
    resources: "usable",
  });
  await new Promise((res) => {
    if (dom.window.DocEditor) return res();
    dom.window.addEventListener("load", res);
  });
  const w = dom.window;
  const $ = (id) => w.document.getElementById(id);
  const ui = {
    w, $,
    click(id) { assert.ok(!$(id).disabled, `${id} が押せません`); $(id).click(); },
    set(id, v) { $(id).value = v; },
    row(ref) { return w.document.querySelector(`.row[data-ref="${ref}"]`); },
    // ジャンプ欄で表示してから行をクリック（フォーカス）
    focus(ref) {
      ui.set("jumpRef", ref);
      ui.click("btnJump");
      ui.row(ref).querySelector(".txt").click();
      assert.strictEqual(w.DocEditor.state.focus, ref);
    },
    // 行のチェックボックスを1つずつクリック
    tick(ref) {
      ui.set("jumpRef", ref);
      ui.click("btnJump");
      const cb = ui.row(ref).querySelector("input[type=checkbox]");
      if (!cb.checked) cb.click();
      assert.ok(w.DocEditor.state.checked.has(ref), `${ref} がチェックされていません`);
    },
    untick(ref) {
      const cb = ui.row(ref).querySelector("input[type=checkbox]");
      if (cb.checked) cb.click();
    },
    label(label, level) {
      ui.set("labelSelect", label);
      assert.strictEqual($("labelSelect").value, label, `ラベル候補に ${label} がありません`);
      if (level) ui.set("levelInput", String(level));
    },
    target(ref, index) {
      ui.focus(ref);
      ui.click("btnSetTarget");
      ui.set("moveIndex", index === undefined ? "" : String(index));
    },
    lastLog() { const l = $("log").lastElementChild; return l ? l.textContent : ""; },
    doc() { return w.DocEditor.state.doc; },
    // jsdom 側の配列を Node 側の配列に変換（assert.deepStrictEqual 用）
    kids(ref) { return [...w.DocCore.childRefs(w.DocEditor.state.doc, ref)]; },
    C: w.DocCore,
    export(file) {
      ui.click("btnExport");
      const text = w.DocEditor.state.lastExport;
      assert.ok(text, "書き出しに失敗: " + ui.lastLog());
      fs.writeFileSync(file, text);
      return text;
    },
  };
  w.DocEditor.loadText(SRC_TEXT, "那須烏山市総合計画のコピー.json");
  return ui;
}

const results = [];
const manifest = [];

async function test(name, desc, fn) {
  try {
    const ui = await openEditor();
    const extra = (await fn(ui)) || {};
    const file = path.join(OUT, `${name}.json`);
    ui.export(file);
    const v = ui.C.validate(ui.doc());
    manifest.push({ name: "UI_" + name, file, expect: extra.expect || [], expectDoc: extra.expectDoc || [], absent: extra.absent || [] });
    results.push(["PASS", name, desc, `警告${v.warnings.length}`]);
    ui.w.close();
  } catch (e) {
    results.push(["FAIL", name, desc, e.message]);
  }
}

(async () => {
  // ---------- Stage 1 ----------
  await test("U01_load_export", "読み込み → 無編集で書き出し（元と同一）", (ui) => {
    assert.strictEqual(ui.$("fileName").textContent, "那須烏山市総合計画のコピー.json");
    ui.click("btnExport");
    assert.strictEqual(JSON.stringify(JSON.parse(ui.w.DocEditor.state.lastExport)), JSON.stringify(JSON.parse(SRC_TEXT)));
    assert.ok(ui.w.DocEditor.state.lastExport.includes("3637144071399653076"), "binary_hash の桁が壊れています");
  });

  await test("U02_json_view", "選択した要素の JSON 表示（実際の記述）", (ui) => {
    ui.focus("#/texts/2696");
    const shown = JSON.parse(ui.$("jsonView").value);
    assert.strictEqual(shown.self_ref, "#/texts/2696");
    assert.strictEqual(shown.parent.$ref, "#/groups/170");
    assert.ok(ui.$("focusInfo").textContent.includes("親: #/groups/170"));
  });

  // ---------- Stage 2: ラベル ----------
  await test("U03_label_focus", "フォーカス要素のラベル変更（text → section_header L2）", (ui) => {
    ui.focus("#/texts/1");
    ui.label("section_header", 2);
    ui.click("btnLabelFocus");
    const it = ui.C.getItem(ui.doc(), "#/texts/1");
    assert.ok(it.label === "section_header" && it.level === 2, ui.lastLog());
    assert.ok(ui.row("#/texts/1").textContent.includes("section_header L2"));
  });

  await test("U04_label_bulk", "直下の子をチェック → 一括ラベル変更", (ui) => {
    ui.focus("#/pictures/5");
    ui.click("btnCheckChildren");
    assert.strictEqual(ui.$("checkCount").textContent, "3");
    ui.focus("#/texts/0");          // ラベル候補を texts 用にする
    ui.label("section_header", 3);
    ui.click("btnLabelChecked");
    for (const r of ui.kids("#/pictures/5")) {
      assert.strictEqual(ui.C.getItem(ui.doc(), r).level, 3);
    }
  });

  // ---------- Stage 3: 階層 ----------
  await test("U05_move_L3_to_body", "一番小さい子(L3)を一番上の親 body の先頭へ", (ui) => {
    ui.target("#/body", 0);
    ui.focus("#/texts/2696");
    ui.click("btnMoveFocus");
    assert.strictEqual(ui.kids("#/body")[0], "#/texts/2696", ui.lastLog());
    return { expect: ["①市内事業経営者"] };
  });

  await test("U06_move_L3_to_L1", "L3 の子を L1 の親（リスト #/groups/0）の末尾へ", (ui) => {
    ui.target("#/groups/0");
    ui.focus("#/texts/2697");
    ui.click("btnMoveFocus");
    assert.strictEqual(ui.C.parentRef(ui.doc(), "#/texts/2697"), "#/groups/0", ui.lastLog());
  });

  await test("U07_move_rejected", "循環になる移動は拒否（ログにエラー、文書は無変更）", (ui) => {
    const before = ui.C.serialize(ui.doc());
    ui.target("#/texts/2696");
    ui.focus("#/groups/169");
    ui.click("btnMoveFocus");
    assert.match(ui.lastLog(), /失敗.*子孫/);
    assert.strictEqual(ui.C.serialize(ui.doc()), before);
  });

  await test("U08_bulk_desc_move", "全子孫をチェック → 一括移動（親ごと移動して内部を保持）", (ui) => {
    ui.focus("#/groups/169");
    ui.click("btnCheckDesc");
    assert.strictEqual(ui.$("checkCount").textContent, "4");
    const inner = ui.kids("#/groups/170");
    ui.target("#/body", 0);
    ui.click("btnMoveChecked");
    assert.strictEqual(ui.C.parentRef(ui.doc(), "#/groups/170"), "#/body", ui.lastLog());
    assert.deepStrictEqual(ui.kids("#/groups/170"), inner);
    assert.strictEqual(ui.$("checkCount").textContent, "0");
  });

  await test("U09_individual_ticks", "1つずつチェック（L3・L2・L1）→ まとめて移動", (ui) => {
    const l2 = ui.kids("#/pictures/10")[0];
    const l1 = ui.kids("#/body")[1];
    ["#/texts/2698", l2, l1].forEach((r) => ui.tick(r));
    ui.focus("#/texts/2698");
    ui.label("text");
    ui.click("btnLabelFocus");                 // list_item のままリスト外に出さない
    ui.target("#/groups/169", 0);
    ui.click("btnMoveChecked");
    assert.deepStrictEqual(ui.kids("#/groups/169").slice(0, 3), ["#/texts/2698", l2, l1], "実際: " + ui.kids("#/groups/169").join(",") + " checked=" + [...ui.w.DocEditor.state.checked].join(","));
  });

  await test("U10_tick_untick", "一括チェック後に個別に外す → 残りだけ移動", (ui) => {
    ui.focus("#/pictures/7");
    ui.click("btnCheckChildren");
    const k = ui.kids("#/pictures/7");
    ui.untick(k[1]);
    ui.target("#/body", 2);
    ui.click("btnMoveChecked");
    assert.deepStrictEqual(ui.kids("#/pictures/7"), [k[1]], ui.lastLog());
    assert.deepStrictEqual(ui.kids("#/body").slice(2, 4), [k[0], k[2]]);
  });

  // ---------- Stage 4: バリュー ----------
  await test("U11_text_edit", "本文欄で本文を変更（orig も同期）", (ui) => {
    ui.focus("#/texts/1");
    ui.set("textEdit", "令和5年度【UI本文編集】");
    ui.click("btnText");
    const it = ui.C.getItem(ui.doc(), "#/texts/1");
    assert.ok(it.text === "令和5年度【UI本文編集】" && it.orig === it.text, ui.lastLog());
    return { expect: ["【UI本文編集】"] };
  });

  await test("U12_json_edit", "JSON 欄を直接編集して反映（text と prov 以外の値）", (ui) => {
    ui.focus("#/texts/5");
    const o = JSON.parse(ui.$("jsonView").value);
    o.text = "【UI-JSON編集】" + o.text;
    ui.set("jsonView", JSON.stringify(o, null, 2));
    ui.click("btnJson");
    assert.ok(ui.C.getItem(ui.doc(), "#/texts/5").text.startsWith("【UI-JSON編集】"), ui.lastLog());
    return { expect: ["【UI-JSON編集】"] };
  });

  await test("U13_json_rejects", "JSON 欄で parent 変更・構文エラーは拒否", (ui) => {
    const before = ui.C.serialize(ui.doc());
    ui.focus("#/texts/5");
    const o = JSON.parse(ui.$("jsonView").value);
    o.parent = { $ref: "#/groups/0" };
    ui.set("jsonView", JSON.stringify(o));
    ui.click("btnJson");
    assert.match(ui.lastLog(), /失敗.*parent/);
    ui.set("jsonView", "{ broken");
    ui.click("btnJson");
    assert.match(ui.lastLog(), /失敗.*構文/);
    ui.click("btnJsonReset");
    assert.strictEqual(JSON.parse(ui.$("jsonView").value).self_ref, "#/texts/5");
    assert.strictEqual(ui.C.serialize(ui.doc()), before);
  });

  // ---------- 組み合わせ ----------
  await test("U14_label_then_move", "ラベル変更 → 移動（list_item を text にして body 先頭へ）", (ui) => {
    ui.focus("#/texts/3223");
    ui.label("text");
    ui.click("btnLabelFocus");
    ui.target("#/body", 0);
    ui.focus("#/texts/3223");
    ui.click("btnMoveFocus");
    assert.strictEqual(ui.kids("#/body")[0], "#/texts/3223", ui.lastLog());
    assert.strictEqual(ui.C.getItem(ui.doc(), "#/texts/3223").label, "text");
  });

  await test("U15_all_features", "全機能を1つの文書で順に使用", (ui) => {
    // L3 → body（ラベルを先に text に）
    ui.focus("#/texts/2696"); ui.label("text"); ui.click("btnLabelFocus");
    ui.target("#/body", 0); ui.focus("#/texts/2696"); ui.click("btnMoveFocus");
    // L3 → L1 リスト
    ui.target("#/groups/0"); ui.focus("#/texts/2697"); ui.click("btnMoveFocus");
    // L1 サブツリー → L1 の下
    ui.target("#/groups/169"); ui.focus("#/pictures/5"); ui.click("btnMoveFocus");
    // 一括: 直下の子チェック → 一括ラベル → 一括移動
    ui.focus("#/pictures/7"); ui.click("btnCheckChildren");
    ui.focus("#/texts/0"); ui.label("section_header", 2); ui.click("btnLabelChecked");
    ui.target("#/body", 1); ui.click("btnMoveChecked");
    // 本文・JSON
    ui.focus("#/texts/1"); ui.set("textEdit", "【UI全機能】"); ui.click("btnText");
    ui.focus("#/groups/169");
    const o = JSON.parse(ui.$("jsonView").value); o.name = "edited-group";
    ui.set("jsonView", JSON.stringify(o)); ui.click("btnJson");
    const d = ui.doc();
    assert.strictEqual(ui.C.parentRef(d, "#/pictures/5"), "#/groups/169");
    assert.strictEqual(ui.C.getItem(d, "#/groups/169").name, "edited-group");
    assert.strictEqual(ui.C.childRefs(d, "#/pictures/7").length, 0);
    assert.ok(ui.C.validate(d).ok);
    return { expect: ["【UI全機能】"] };
  });

  // ---------- 追加・合体・削除 ----------
  await test("U16_add_after", "フォーカス要素の直後に本文を追加（追加した要素にフォーカスが移る）", (ui) => {
    const n = ui.doc().texts.length;
    ui.focus("#/pictures/5");
    ui.set("addLabel", "text");
    ui.set("addPos", "after");
    ui.set("addText", "【UI追加-図の説明】");
    ui.click("btnAdd");
    const ref = `#/texts/${n}`;
    assert.strictEqual(ui.w.DocEditor.state.focus, ref, ui.lastLog());
    const b = ui.kids("#/body");
    assert.strictEqual(b[b.indexOf("#/pictures/5") + 1], ref);
    assert.ok(ui.row(ref), "追加した行がツリーに表示されていません");
    assert.strictEqual(ui.$("addText").value, "");
    return { expect: ["【UI追加-図の説明】"] };
  });

  await test("U17_add_child_header", "フォーカス要素の子として見出し（L3）を追加 → 空の本文は拒否", (ui) => {
    ui.focus("#/groups/169");
    ui.set("addPos", "child");
    ui.set("addText", "");
    ui.click("btnAdd");
    assert.match(ui.lastLog(), /失敗.*本文/);
    assert.strictEqual(ui.$("btnUndo").disabled, true, "失敗した操作が元に戻す履歴に残っています");
    ui.set("addLabel", "section_header");
    ui.set("addLevel", "3");
    ui.set("addText", "【UI追加見出し】");
    ui.click("btnAdd");
    const k = ui.kids("#/groups/169");
    const it = ui.C.getItem(ui.doc(), k[k.length - 1]);
    assert.ok(it.label === "section_header" && it.level === 3 && it.text === "【UI追加見出し】", ui.lastLog());
  });

  await test("U18_merge_checked", "2件をチェック → 合体（つなぎ文字なし）→ 番号が詰まる", (ui) => {
    const t6 = ui.C.getItem(ui.doc(), "#/texts/6").text;
    const t7 = ui.C.getItem(ui.doc(), "#/texts/7").text;
    const n = ui.doc().texts.length;
    ui.tick("#/texts/7");
    assert.strictEqual(ui.$("btnMerge").disabled, true, "1件だけで合体ボタンが押せます");
    ui.tick("#/texts/6");
    ui.click("btnMerge");
    assert.strictEqual(ui.C.getItem(ui.doc(), "#/texts/6").text, t6 + t7, ui.lastLog());
    assert.strictEqual(ui.doc().texts.length, n - 1);
    assert.strictEqual(ui.w.DocEditor.state.focus, "#/texts/6");
    assert.strictEqual(ui.$("checkCount").textContent, "0");
    return { expectDoc: [{ ref: "#/texts/6", label: "section_header", text: t6 + t7, parent: "#/body" }] };
  });

  await test("U19_merge_newline", "改行でつなぐ合体（本文を持たない要素が混ざると拒否）", (ui) => {
    ui.tick("#/texts/4");
    ui.tick("#/groups/0");
    ui.click("btnMerge");
    assert.match(ui.lastLog(), /失敗.*合体できません/);
    ui.untick("#/groups/0");
    ui.tick("#/texts/5");
    ui.$("mergeNewline").checked = true;
    const t4 = ui.C.getItem(ui.doc(), "#/texts/4").text;
    const t5 = ui.C.getItem(ui.doc(), "#/texts/5").text;
    ui.click("btnMerge");
    assert.strictEqual(ui.C.getItem(ui.doc(), "#/texts/4").text, t4 + "\n" + t5, ui.lastLog());
  });

  await test("U20_delete_focus_keep", "フォーカス要素を削除（子は残す）→ 子が同じ位置に繰り上がる", (ui) => {
    const picKids = ui.kids("#/pictures/5").map((r) => ui.C.getItem(ui.doc(), r).text);
    const idx = ui.kids("#/body").indexOf("#/pictures/5");
    const np = ui.doc().pictures.length;
    ui.focus("#/pictures/5");
    ui.$("delKeepChildren").checked = true;
    ui.click("btnDeleteFocus");
    assert.strictEqual(ui.doc().pictures.length, np - 1, ui.lastLog());
    const b = ui.kids("#/body");
    assert.deepStrictEqual(b.slice(idx, idx + picKids.length).map((r) => ui.C.getItem(ui.doc(), r).text), picKids);
    assert.strictEqual(ui.w.DocEditor.state.focus, null);
  });

  await test("U21_delete_checked_subtree", "チェックした要素を子孫ごと削除", (ui) => {
    const nt = ui.doc().texts.length;
    ui.tick("#/groups/169");
    ui.$("delKeepChildren").checked = false;
    ui.click("btnDeleteChecked");
    assert.ok(ui.doc().texts.length < nt, ui.lastLog());
    assert.ok(ui.C.validate(ui.doc()).ok);
    return { absent: ["①市内事業経営者、まちづくり団体等との意見交換会"] };
  });

  await test("U22_undo", "削除 → 合体 → 元に戻す（2回）で元の文書に戻る", (ui) => {
    const before = ui.C.serialize(ui.doc());
    ui.focus("#/texts/2697");
    ui.click("btnDeleteFocus");
    ui.tick("#/texts/4"); ui.tick("#/texts/5");
    ui.click("btnMerge");
    assert.notStrictEqual(ui.C.serialize(ui.doc()), before);
    ui.click("btnUndo");
    ui.click("btnUndo");
    assert.strictEqual(ui.C.serialize(ui.doc()), before);
    assert.strictEqual(ui.$("btnUndo").disabled, true);
  });

  await test("U23_add_merge_delete_mix", "追加 → 合体 → 削除 → ラベル → 移動を1つの文書で使用", (ui) => {
    ui.focus("#/pictures/5");
    ui.set("addLabel", "text"); ui.set("addPos", "after");
    ui.set("addText", "【UI組合せ1】"); ui.click("btnAdd");
    const a = ui.w.DocEditor.state.focus;
    ui.set("addText", "【UI組合せ2】"); ui.click("btnAdd");
    const b = ui.w.DocEditor.state.focus;
    ui.$("mergeNewline").checked = false; ui.set("mergeSep", " / ");
    ui.tick(a); ui.tick(b); ui.click("btnMerge");
    ui.$("delKeepChildren").checked = true;
    ui.focus("#/texts/2698"); ui.click("btnDeleteFocus");
    // 削除で後ろの番号が詰まるので、合体した要素の現在の番号を本文から探す
    const mi = ui.doc().texts.findIndex((t) => t.text === "【UI組合せ1】 / 【UI組合せ2】");
    assert.ok(mi >= 0, "合体した要素が見つかりません");
    const merged = `#/texts/${mi}`;
    ui.focus("#/texts/2696"); ui.label("text"); ui.click("btnLabelFocus");
    ui.target("#/body", 0); ui.focus(merged); ui.click("btnMoveFocus");
    assert.strictEqual(ui.C.getItem(ui.doc(), ui.kids("#/body")[0]).text, "【UI組合せ1】 / 【UI組合せ2】", ui.lastLog());
    assert.ok(ui.C.validate(ui.doc()).ok);
    return { expect: ["【UI組合せ1】 / 【UI組合せ2】"], absent: ["③タウンミーティング"] };
  });

  // ==========================================
  // GOAL: コピー JSON を GUI で編集して書き出す（チャンク化に回す本番データ）
  // ==========================================
  try {
    const ui = await openEditor();
    const base = ui.C.validate(ui.doc()).warnings.length;
    // 1. 表紙のタイトルを title ラベルに
    ui.focus("#/texts/0"); ui.label("title"); ui.click("btnLabelFocus");
    // 2. 表紙の「令和 5 年度」の OCR 由来の空白を修正
    ui.focus("#/texts/1"); ui.set("textEdit", "令和5年度"); ui.click("btnText");
    // 3. 見出しの続き「の実現に向けて」を前の見出しに統合し、本文扱いに
    const t6 = ui.C.getItem(ui.doc(), "#/texts/6").text;
    const t7 = ui.C.getItem(ui.doc(), "#/texts/7").text;
    ui.focus("#/texts/6"); ui.set("textEdit", t6 + t7); ui.click("btnText");
    ui.focus("#/texts/7"); ui.label("text"); ui.click("btnLabelFocus");
    // 4. 図(#/pictures/5)内の文字3件を一括で図の直後（本文）へ出す
    const picIdx = ui.kids("#/body").indexOf("#/pictures/5");
    ui.focus("#/pictures/5"); ui.click("btnCheckChildren");
    ui.target("#/body", picIdx + 1); ui.click("btnMoveChecked");
    // 5. L3 の並べ替え（リスト内の3番目を先頭へ）
    ui.target("#/groups/170", 0); ui.focus("#/texts/2698"); ui.click("btnMoveFocus");
    // 6. JSON 直接編集で見出しレベルを修正
    ui.focus("#/texts/7");
    ui.focus("#/texts/8");
    const o = JSON.parse(ui.$("jsonView").value);
    if (o.label === "section_header") { o.level = 2; ui.set("jsonView", JSON.stringify(o, null, 2)); ui.click("btnJson"); }
    const v = ui.C.validate(ui.doc());
    assert.ok(v.ok, v.errors.join(" / "));
    assert.ok(v.warnings.length <= base, `警告が増えています: ${v.warnings.join(" / ")}`);
    ui.set("outName", path.basename(GOAL_OUT));
    ui.export(GOAL_OUT);
    manifest.push({
      name: "GOAL", file: GOAL_OUT, expect: ["令和5年度", t6 + t7],
      expectDoc: [{ ref: "#/texts/1", label: "text", text: "令和5年度", parent: "#/body" }],
    });
    results.push(["PASS", "GOAL", "コピー JSON を GUI で編集して書き出し", `警告${v.warnings.length}（元${base}）`]);
  } catch (e) {
    results.push(["FAIL", "GOAL", "コピー JSON を GUI で編集して書き出し", e.message]);
  }

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
  for (const r of results) console.log(r.join("\t"));
  const failed = results.filter((r) => r[0] === "FAIL").length;
  console.log(`\n${results.length - failed}/${results.length} PASS`);
  process.exit(failed ? 1 : 0);
})();
