// FastAPI から返ってきた候補を、選択肢（ボタン）として表示する
// ボタンを押したときの処理（選択の切り替え）は呼び出し側から onClick で受け取る

import { button, el } from "./dom.js";
import { pathKey } from "./selection.js";

// 入力: 話題ボタンが並ぶ領域・選択（Selection） / 出力: なし
// 同じ経路のボタンは何か所にあっても選択の見た目を揃える（data-key で連動）
export function syncSelected(container, selection) {
  container.querySelectorAll(".topic").forEach((x) => x.classList.toggle("on", selection.has(x.dataset.key)));
}

// ① LLM が作った話題のボタン
// 入力: 話題 {title, description, node: {path, chunk_count}}・押したときの処理
// 出力: ボタンの要素
export function topicButton(topic, onClick) {
  const b = button(`${topic.title}（${topic.node.chunk_count}）`, "topic");
  b.title = topic.node.path.slice(1).join(" > ");
  b.dataset.key = pathKey(topic.node.path);
  if (topic.description) b.appendChild(el("span", "desc", topic.description));
  b.addEventListener("click", () => onClick(topic.node, topic.title));
  return b;
}

// ① 見出しから直接選ぶ: 1件の検索結果の見出しの経路を、段ごとのボタンで1行に並べる
// 入力: hit {rank, nodes: [{path, title, chunk_count}]}・押したときの処理
// 出力: 1行の要素
export function headingRow(hit, onClick) {
  const row = el("div", "level-row");
  row.appendChild(el("span", "rank", `${hit.rank}`));
  hit.nodes.forEach((n, i) => {
    if (i) row.appendChild(el("span", "sep", "›"));
    const b = button(`${n.title}（${n.chunk_count}）`, "topic node");
    b.title = n.path.join(" > ");
    b.dataset.key = pathKey(n.path);
    b.addEventListener("click", () => onClick(n, n.title));
    row.appendChild(b);
  });
  return row;
}

// ② 1段下の話題のボタンを、①で選んだ範囲ごとにまとめて表示する
// 入力: 表示先・/subtopics の groups・押したときの処理（話題を受け取る）
// 出力: なし
export function renderSubtopicGroups(container, groups, onClick) {
  for (const g of groups) {
    if (groups.length > 1) container.appendChild(el("div", "group-title", `${g.title}（${g.total}）`));
    const box = el("div", "topics");
    for (const t of g.topics) {
      const b = button(`${t.title}（${t.chunk_count}）`, "topic");
      b.dataset.key = pathKey(t.path);
      b.addEventListener("click", () => onClick(t));
      box.appendChild(b);
    }
    container.appendChild(box);
  }
}

// 「選んだ話題で次へ」などの操作ボタンと件数表示の行
// 入力: 主ボタンの文字 / 出力: {actions: 行, go: 主ボタン, count: 件数表示, extra: 追加用の領域}
export function actionRow(goLabel) {
  const actions = el("div", "actions");
  const go = button(goLabel);
  go.disabled = true;
  const count = el("span", "count", "0 件選択中");
  actions.appendChild(go);
  actions.appendChild(count);
  return { actions, go, count };
}
