/*
 * DoclingDocument エディター：コアロジック
 * ブラウザ（index.html）と Node（cli.js / テスト）の両方から同じ処理を使う。
 * DOM には一切触れない純粋な処理だけを置く。
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.DocCore = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // DoclingDocument の要素配列（self_ref は "#/<配列名>/<番号>"）
  const ARRAYS = [
    "groups", "texts", "pictures", "tables",
    "key_value_items", "form_items", "field_regions", "field_items",
  ];
  const ROOTS = ["#/body", "#/furniture"];

  // ==========================================
  // 1. 読み込み・書き出し
  // ==========================================

  // 2^53 を超える整数（origin.binary_hash など）は JS の number だと桁が壊れるので、
  // 元の文字列のまま保持して、そのまま書き出す。
  const canRaw = typeof JSON.rawJSON === "function";

  function parse(text) {
    return JSON.parse(text, function (key, value, context) {
      if (
        canRaw && typeof value === "number" && Number.isInteger(value) &&
        !Number.isSafeInteger(value) && context && typeof context.source === "string"
      ) {
        return JSON.rawJSON(context.source);
      }
      return value;
    });
  }

  function serialize(doc) {
    return JSON.stringify(doc, null, 2);
  }

  // ==========================================
  // 2. 参照の解決
  // ==========================================

  function getItem(doc, ref) {
    if (ref === "#/body") return doc.body;
    if (ref === "#/furniture") return doc.furniture;
    const m = /^#\/(\w+)\/(\d+)$/.exec(ref || "");
    if (!m || !Array.isArray(doc[m[1]])) return undefined;
    return doc[m[1]][Number(m[2])];
  }

  function arrayOf(ref) {
    const m = /^#\/(\w+)\//.exec(ref || "");
    return m ? m[1] : null;
  }

  function childRefs(doc, ref) {
    const item = getItem(doc, ref);
    return item && Array.isArray(item.children) ? item.children.map((c) => c.$ref) : [];
  }

  function parentRef(doc, ref) {
    const item = getItem(doc, ref);
    return item && item.parent ? item.parent.$ref : null;
  }

  function allRefs(doc) {
    const refs = [];
    for (const arr of ARRAYS) {
      (doc[arr] || []).forEach((_, i) => refs.push(`#/${arr}/${i}`));
    }
    return refs;
  }

  // 表示用の短い説明
  function describe(doc, ref) {
    const item = getItem(doc, ref);
    if (!item) return ref;
    if (ROOTS.includes(ref)) return ref.slice(2);
    const label = item.label || "";
    let text = "";
    if (typeof item.text === "string") text = item.text;
    else if (item.name && arrayOf(ref) === "groups") text = item.name;
    text = text.replace(/\s+/g, " ").trim();
    if (text.length > 60) text = text.slice(0, 60) + "…";
    return `${label}${text ? " | " + text : ""}`;
  }

  // ==========================================
  // 3. 検証
  // ==========================================

  // DoclingDocument（docling-core）の型ごとに許されるラベル
  const LABELS = {
    texts: [
      "text", "paragraph", "section_header", "title", "list_item",
      "caption", "footnote", "page_header", "page_footer", "reference",
      "checkbox_selected", "checkbox_unselected", "empty_value",
      "field_key", "field_hint", "marker", "handwritten_text",
      "code", "formula",
    ],
    groups: [
      "unspecified", "list", "ordered_list", "chapter", "section", "sheet",
      "slide", "form_area", "key_value_area", "comment_section", "inline",
      "picture_area",
    ],
    tables: ["table", "document_index"],
    pictures: ["picture", "chart"],
  };

  // ラベルによって型（クラス）が変わり、持てるフィールドが変わるもの
  const TEXT_CLASS_FIELDS = {
    section_header: { level: 1 },
    list_item: { enumerated: false, marker: "-" },
  };
  const TEXT_SPECIAL_FIELDS = ["level", "enumerated", "marker"];

  function validate(doc) {
    const errors = [];
    const warnings = [];

    for (const r of ROOTS) {
      const it = getItem(doc, r);
      if (!it) errors.push(`${r} がありません`);
      else if (it.self_ref !== r) errors.push(`${r} の self_ref が不正: ${it.self_ref}`);
    }

    // self_ref が配列内の位置と一致しているか
    for (const arr of ARRAYS) {
      (doc[arr] || []).forEach((it, i) => {
        const expect = `#/${arr}/${i}`;
        if (!it || it.self_ref !== expect) {
          errors.push(`${expect} の self_ref が不正: ${it && it.self_ref}`);
        }
      });
    }

    // 親子参照の整合性
    const referencedBy = new Map();
    const nodes = ROOTS.concat(allRefs(doc));
    for (const ref of nodes) {
      const it = getItem(doc, ref);
      if (!it) continue;
      for (const c of it.children || []) {
        const cref = c && c.$ref;
        const child = getItem(doc, cref);
        if (!child) {
          errors.push(`${ref} の子 ${cref} が存在しません`);
          continue;
        }
        if (referencedBy.has(cref)) {
          errors.push(`${cref} が複数の親（${referencedBy.get(cref)}, ${ref}）から参照されています`);
        } else {
          referencedBy.set(cref, ref);
        }
        if (!child.parent || child.parent.$ref !== ref) {
          errors.push(`${cref} の parent が ${child.parent && child.parent.$ref} ですが、${ref} の子に入っています`);
        }
      }
    }
    for (const ref of allRefs(doc)) {
      const it = getItem(doc, ref);
      const p = it.parent && it.parent.$ref;
      if (!p) {
        errors.push(`${ref} に parent がありません`);
        continue;
      }
      if (!getItem(doc, p)) {
        errors.push(`${ref} の parent ${p} が存在しません`);
      } else if (!childRefs(doc, p).includes(ref)) {
        errors.push(`${ref} は parent ${p} の children に入っていません`);
      }
    }

    // 到達可能性・循環（body / furniture から辿れない要素はチャンク化されない）
    const reached = new Set();
    for (const r of ROOTS) {
      const stack = [r];
      while (stack.length) {
        const cur = stack.pop();
        for (const c of childRefs(doc, cur)) {
          if (reached.has(c) || ROOTS.includes(c)) continue;
          reached.add(c);
          stack.push(c);
        }
      }
    }
    for (const ref of allRefs(doc)) {
      if (!reached.has(ref)) errors.push(`${ref} は body / furniture から辿れません（循環または孤立）`);
    }

    // ラベルと型ごとのフィールド
    for (const arr of Object.keys(LABELS)) {
      (doc[arr] || []).forEach((it, i) => {
        const ref = `#/${arr}/${i}`;
        if (!LABELS[arr].includes(it.label)) {
          errors.push(`${ref} のラベル "${it.label}" は ${arr} では使えません`);
        }
        if (arr === "texts") {
          for (const f of TEXT_SPECIAL_FIELDS) {
            const need = TEXT_CLASS_FIELDS[it.label] && f in TEXT_CLASS_FIELDS[it.label];
            if (!need && f in it) errors.push(`${ref}（${it.label}）は ${f} を持てません`);
          }
          if (it.label === "section_header" && !(Number.isInteger(it.level) && it.level >= 1 && it.level <= 100)) {
            errors.push(`${ref} の level は 1〜100 の整数が必要です`);
          }
          if (typeof it.text !== "string" || typeof it.orig !== "string") {
            errors.push(`${ref} の text / orig は文字列が必要です`);
          }
        }
      });
    }

    // docling-core のルール（読み込みは通るが警告になるもの）
    for (const ref of allRefs(doc)) {
      const it = getItem(doc, ref);
      const p = it.parent && getItem(doc, it.parent.$ref);
      if (arrayOf(ref) === "groups") {
        if (!(it.children || []).length) warnings.push(`${ref}（グループ）に子がありません`);
        if (it.label === "list") {
          for (const c of childRefs(doc, ref)) {
            const ch = getItem(doc, c);
            if (ch && ch.label !== "list_item") warnings.push(`リスト ${ref} に list_item 以外の ${c}（${ch.label}）があります`);
          }
        }
      }
      if (it.label === "list_item" && arrayOf(ref) === "texts" && !(p && p.label === "list" && arrayOf(it.parent.$ref) === "groups")) {
        warnings.push(`list_item ${ref} の親がリストではありません（読み込み時に自動でリストに包まれます）`);
      }
    }

    return { ok: errors.length === 0, errors, warnings };
  }

  // ==========================================
  // 4. 選択の補助
  // ==========================================

  function ancestors(doc, ref) {
    const out = [];
    let p = parentRef(doc, ref);
    const guard = new Set();
    while (p && !guard.has(p)) {
      out.push(p);
      guard.add(p);
      p = parentRef(doc, p);
    }
    return out;
  }

  function isDescendant(doc, ref, ofRef) {
    return ancestors(doc, ref).includes(ofRef);
  }

  function descendants(doc, ref) {
    const out = [];
    const stack = childRefs(doc, ref).slice().reverse();
    while (stack.length) {
      const cur = stack.pop();
      out.push(cur);
      stack.push(...childRefs(doc, cur).slice().reverse());
    }
    return out;
  }

  // 親と子が両方選ばれている場合は親だけ残す（親ごと移動して内部の親子関係を保つ）
  function topmost(doc, refs) {
    const set = new Set(refs);
    return refs.filter((r) => !ancestors(doc, r).some((a) => set.has(a)));
  }

  // ==========================================
  // 5. 編集操作（すべて {ok, error} を返す。失敗時は文書を変更しない）
  // ==========================================

  const ok = () => ({ ok: true });
  const fail = (error) => ({ ok: false, error });

  function labelOptions(ref) {
    const arr = arrayOf(ref);
    if (!LABELS[arr]) return [];
    if (arr === "texts") return LABELS.texts.filter((l) => l !== "code" && l !== "formula");
    return LABELS[arr];
  }

  function checkLabel(doc, ref, label) {
    const item = getItem(doc, ref);
    if (!item || ROOTS.includes(ref)) return `${ref} はラベルを変更できません`;
    const arr = arrayOf(ref);
    if (arr === "texts" && (item.label === "code" || item.label === "formula")) {
      return `${ref}（${item.label}）のラベル変更には対応していません`;
    }
    if (!labelOptions(ref).includes(label)) return `${ref}（${arr}）にラベル "${label}" は使えません`;
    return null;
  }

  function applyLabel(doc, ref, label, level) {
    const item = getItem(doc, ref);
    if (arrayOf(ref) === "texts") {
      const keepLevel = item.label === "section_header" ? item.level : undefined;
      for (const f of TEXT_SPECIAL_FIELDS) delete item[f];
      Object.assign(item, TEXT_CLASS_FIELDS[label] || {});
      if (label === "section_header") item.level = level || keepLevel || 1;
    }
    item.label = label;
  }

  // 1要素または複数要素のラベルを変更（どれか1つでも不可なら何もしない）
  function setLabels(doc, { refs, label, level }) {
    if (!refs || !refs.length) return fail("要素が選択されていません");
    if (level !== undefined && !(Number.isInteger(level) && level >= 1 && level <= 100)) {
      return fail("level は 1〜100 の整数で指定してください");
    }
    for (const r of refs) {
      const e = checkLabel(doc, r, label);
      if (e) return fail(e);
    }
    refs.forEach((r) => applyLabel(doc, r, label, level));
    return ok();
  }

  // 要素を別の親へ移動（複数可）。index 未指定なら末尾に追加
  function moveItems(doc, { refs, target, index }) {
    if (!refs || !refs.length) return fail("移動する要素が選択されていません");
    const tgt = getItem(doc, target);
    if (!tgt) return fail(`移動先 ${target} が存在しません`);
    const moving = topmost(doc, refs);
    for (const r of moving) {
      if (ROOTS.includes(r)) return fail(`${r} は移動できません`);
      if (!getItem(doc, r)) return fail(`${r} が存在しません`);
      if (r === target) return fail(`${r} を自分自身の下には移動できません`);
      if (isDescendant(doc, target, r)) return fail(`${r} を自分の子孫 ${target} の下には移動できません`);
    }
    if (!Array.isArray(tgt.children)) tgt.children = [];
    let pos = Number.isInteger(index) ? Math.max(0, Math.min(index, tgt.children.length)) : null;

    for (const r of moving) {
      const item = getItem(doc, r);
      const oldParent = getItem(doc, item.parent.$ref);
      const oldIdx = oldParent.children.findIndex((c) => c.$ref === r);
      oldParent.children.splice(oldIdx, 1);
      if (pos !== null && oldParent === tgt && oldIdx < pos) pos -= 1;

      if (pos === null) tgt.children.push({ $ref: r });
      else tgt.children.splice(pos++, 0, { $ref: r });
      item.parent = { $ref: target };
    }
    return ok();
  }

  // 本文（text）を変更。syncOrig=true なら orig も同じ値にする
  function setText(doc, { ref, text, syncOrig }) {
    const item = getItem(doc, ref);
    if (!item || arrayOf(ref) !== "texts") return fail(`${ref} は本文を持つ要素ではありません`);
    if (typeof text !== "string") return fail("text は文字列で指定してください");
    item.text = text;
    if (syncOrig) item.orig = text;
    return ok();
  }

  // 要素の JSON を直接書き換える。self_ref / parent / children は変更不可
  // （階層は「移動」で変える）。書き換え後に新たなエラーが出たら元に戻す。
  function updateItem(doc, { ref, json }) {
    const item = getItem(doc, ref);
    if (!item || ROOTS.includes(ref)) return fail(`${ref} は編集できません`);
    let obj;
    try {
      obj = typeof json === "string" ? parse(json) : json;
    } catch (e) {
      return fail(`JSON の構文エラー: ${e.message}`);
    }
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return fail("オブジェクトを指定してください");
    for (const k of ["self_ref", "parent", "children"]) {
      if (JSON.stringify(obj[k]) !== JSON.stringify(item[k])) {
        return fail(`${k} はここでは変更できません（階層の変更は移動機能を使ってください）`);
      }
    }
    if (obj.label !== item.label) {
      const e = checkLabel(doc, ref, obj.label);
      if (e) return fail(e);
    }
    const before = validate(doc).errors.length;
    const arr = arrayOf(ref);
    const i = Number(ref.split("/")[2]);
    const backup = doc[arr][i];
    doc[arr][i] = obj;
    const after = validate(doc);
    if (after.errors.length > before) {
      doc[arr][i] = backup;
      return fail(`編集後にエラーが発生するため反映しません: ${after.errors[after.errors.length - 1]}`);
    }
    return ok();
  }

  // ==========================================
  // 6. 要素の追加・削除・合体
  // ==========================================

  // 文書の並び順（body → furniture を深さ優先でたどった順）での位置
  function readingOrder(doc) {
    const order = new Map();
    let n = 0;
    for (const r of ROOTS) {
      for (const d of descendants(doc, r)) order.set(d, n++);
    }
    return order;
  }

  const isRawJSON = (o) => typeof JSON.isRawJSON === "function" && JSON.isRawJSON(o);

  // 削除した要素を配列から取り除き、残った要素の番号を詰め直す。
  // 文書中のすべての {"$ref": ...}（parent / children / captions など）を新しい番号に書き換え、
  // 削除した要素への参照は配列から取り除く。戻り値: 旧ref → 新ref の対応表
  function removeAndRenumber(doc, removed) {
    const map = new Map();
    for (const arr of ARRAYS) {
      if (!Array.isArray(doc[arr])) continue;
      const kept = [];
      doc[arr].forEach((it, i) => {
        const old = `#/${arr}/${i}`;
        if (removed.has(old)) return;
        const neu = `#/${arr}/${kept.length}`;
        map.set(old, neu);
        it.self_ref = neu;
        kept.push(it);
      });
      doc[arr] = kept;
    }
    const isDeadRef = (v) => v && typeof v === "object" && typeof v.$ref === "string" && removed.has(v.$ref);
    (function walk(o) {
      if (!o || typeof o !== "object" || isRawJSON(o)) return;
      if (Array.isArray(o)) {
        for (let i = o.length - 1; i >= 0; i--) {
          if (isDeadRef(o[i])) o.splice(i, 1);
          else walk(o[i]);
        }
        return;
      }
      if (typeof o.$ref === "string" && map.has(o.$ref)) o.$ref = map.get(o.$ref);
      for (const k of Object.keys(o)) walk(o[k]);
    })(doc);
    return map;
  }

  // 操作を試し、検証エラーが増えたら文書を元に戻す（削除・合体は変更範囲が広いため）
  function guarded(doc, fn) {
    const before = validate(doc).errors.length;
    const backup = serialize(doc);
    const res = fn();
    if (!res.ok) return res;
    const after = validate(doc);
    if (after.errors.length > before) {
      const restored = parse(backup);
      for (const k of Object.keys(doc)) delete doc[k];
      Object.assign(doc, restored);
      return fail(`操作後にエラーが発生するため取り消しました: ${after.errors[after.errors.length - 1]}`);
    }
    return res;
  }

  // 要素を削除する。keepChildren=true なら子は削除する要素の位置に残す（親へ繰り上げ）、
  // false なら子孫ごと削除する。
  function deleteItems(doc, { refs, keepChildren }) {
    if (!refs || !refs.length) return fail("削除する要素が選択されていません");
    for (const r of refs) {
      if (ROOTS.includes(r)) return fail(`${r} は削除できません`);
      if (!getItem(doc, r)) return fail(`${r} が存在しません`);
    }
    return guarded(doc, () => {
      const removed = new Set();
      if (keepChildren) {
        // 深い要素から順に処理し、子を自分の親の同じ位置へ繰り上げる
        const order = refs.slice().sort((a, b) => ancestors(doc, b).length - ancestors(doc, a).length);
        for (const r of order) {
          const p = parentRef(doc, r);
          const idx = childRefs(doc, p).indexOf(r);
          const kids = childRefs(doc, r);
          if (kids.length) moveItems(doc, { refs: kids, target: p, index: idx + 1 });
          removed.add(r);
        }
      } else {
        for (const r of topmost(doc, refs)) {
          removed.add(r);
          descendants(doc, r).forEach((d) => removed.add(d));
        }
      }
      for (const r of removed) {
        const p = getItem(doc, parentRef(doc, r));
        if (p && Array.isArray(p.children)) p.children = p.children.filter((c) => c.$ref !== r);
      }
      const map = removeAndRenumber(doc, removed);
      return { ok: true, removed: [...removed], map };
    });
  }

  // 本文を持つ要素（texts）を新しく作る。
  //   after を指定 → その要素の直後（同じ親）に置く
  //   parent を指定 → その要素の子として index の位置（未指定なら末尾）に置く
  // prov（ページ位置）は provFrom（未指定なら after / 親）の要素から引き継ぐ（ページ番号をチャンクに残すため）
  function addText(doc, { after, parent, index, label, level, text, orig, provFrom }) {
    label = label || "text";
    if (typeof text !== "string" || !text.length) return fail("本文を入力してください");
    if (!labelOptions("#/texts/0").includes(label)) return fail(`ラベル "${label}" は本文の要素には使えません`);
    if (level !== undefined && !(Number.isInteger(level) && level >= 1 && level <= 100)) {
      return fail("level は 1〜100 の整数で指定してください");
    }
    let target, pos;
    if (after) {
      if (!getItem(doc, after) || ROOTS.includes(after)) return fail(`${after} の直後には追加できません`);
      target = parentRef(doc, after);
      pos = childRefs(doc, target).indexOf(after) + 1;
    } else {
      if (!getItem(doc, parent)) return fail(`追加先 ${parent} が存在しません`);
      target = parent;
      const n = childRefs(doc, target).length;
      pos = Number.isInteger(index) ? Math.max(0, Math.min(index, n)) : n;
    }
    const src = getItem(doc, provFrom || after || target);
    const prov = (src && Array.isArray(src.prov) ? src.prov.slice(0, 1) : []).map((p) => ({
      page_no: p.page_no,
      bbox: Object.assign({}, p.bbox),
      charspan: [0, (orig === undefined ? text : orig).length],
    }));

    if (!Array.isArray(doc.texts)) doc.texts = [];
    const ref = `#/texts/${doc.texts.length}`;
    const item = {
      self_ref: ref,
      parent: { $ref: target },
      children: [],
      content_layer: (getItem(doc, target) && getItem(doc, target).content_layer) || (target === "#/furniture" ? "furniture" : "body"),
      label: "text",
      prov,
      orig: orig === undefined ? text : orig,
      text,
    };
    doc.texts.push(item);
    applyLabel(doc, ref, label, level);
    const tgt = getItem(doc, target);
    if (!Array.isArray(tgt.children)) tgt.children = [];
    tgt.children.splice(pos, 0, { $ref: ref });
    return { ok: true, ref };
  }

  // 本文を持つ要素（texts）を、文書の並び順で先頭の要素に1つにまとめる。
  // 本文・orig は sep でつなぎ、prov（ページ位置）も合わせる。
  // まとめられる側の子要素は先頭の要素の子（末尾）に移し、まとめられる側は削除する。
  function mergeTexts(doc, { refs, sep }) {
    sep = sep === undefined ? "" : sep;
    const uniq = [...new Set(refs || [])];
    if (uniq.length < 2) return fail("合体するには 2 件以上を選んでください");
    for (const r of uniq) {
      if (arrayOf(r) !== "texts" || !getItem(doc, r)) return fail(`${r} は本文を持つ要素ではないため合体できません`);
    }
    const order = readingOrder(doc);
    const sorted = uniq.slice().sort((a, b) => order.get(a) - order.get(b));
    for (const r of sorted.slice(1)) {
      if (isDescendant(doc, sorted[0], r)) return fail(`${sorted[0]} は ${r} の子孫なので合体できません`);
    }
    const head = sorted[0];
    return guarded(doc, () => {
      const h = getItem(doc, head);
      for (const r of sorted.slice(1)) {
        const it = getItem(doc, r);
        h.text = h.text + sep + it.text;
        h.orig = h.orig + sep + it.orig;
        h.prov = (h.prov || []).concat(it.prov || []);
        const kids = childRefs(doc, r).filter((k) => !sorted.includes(k));
        if (kids.length) moveItems(doc, { refs: kids, target: head });
      }
      // 合体される要素どうしが親子の場合も、残った子は先頭の要素へ移してから削除する
      const rest = sorted.slice(1);
      const res = deleteItems(doc, { refs: rest, keepChildren: true });
      if (!res.ok) return res;
      return { ok: true, ref: res.map.get(head) || head, map: res.map, removed: res.removed };
    });
  }

  // CLI・テストから名前で呼ぶための一覧
  const OPS = {
    setLabel: (doc, o) => setLabels(doc, { refs: o.refs || [o.ref], label: o.label, level: o.level }),
    move: (doc, o) => moveItems(doc, { refs: o.refs || [o.ref], target: o.target, index: o.index }),
    setText: (doc, o) => setText(doc, o),
    updateItem: (doc, o) => updateItem(doc, o),
    addText: (doc, o) => addText(doc, o),
    merge: (doc, o) => mergeTexts(doc, o),
    delete: (doc, o) => deleteItems(doc, { refs: o.refs || [o.ref], keepChildren: !!o.keepChildren }),
  };

  return {
    ARRAYS, ROOTS, LABELS, canRaw,
    parse, serialize,
    getItem, arrayOf, childRefs, parentRef, allRefs, describe,
    validate,
    ancestors, isDescendant, descendants, topmost, readingOrder,
    labelOptions, setLabels, moveItems, setText, updateItem,
    addText, mergeTexts, deleteItems, OPS,
  };
});
