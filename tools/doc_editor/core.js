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

  // CLI・テストから名前で呼ぶための一覧
  const OPS = {
    setLabel: (doc, o) => setLabels(doc, { refs: o.refs || [o.ref], label: o.label, level: o.level }),
    move: (doc, o) => moveItems(doc, { refs: o.refs || [o.ref], target: o.target, index: o.index }),
    setText: (doc, o) => setText(doc, o),
    updateItem: (doc, o) => updateItem(doc, o),
  };

  return {
    ARRAYS, ROOTS, LABELS, canRaw,
    parse, serialize,
    getItem, arrayOf, childRefs, parentRef, allRefs, describe,
    validate,
    ancestors, isDescendant, descendants, topmost,
    labelOptions, setLabels, moveItems, setText, updateItem, OPS,
  };
});
