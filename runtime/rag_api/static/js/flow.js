// 階層を選んで回答する流れ（① 話題を選ぶ → ② 細かい話題を選ぶ → ③ 回答）
// 各段で「FastAPI に送る（api.js）→ 返ってきた候補を表示（choices_view.js）
//         → 選択を受ける（selection.js）→ 選択を次の段に送る」を繰り返し、③ で回答を表示（answer_view.js）

import { fetchAnswer, fetchLevels, fetchSubtopics } from "./api.js";
import { actionRow, headingRow, renderSubtopicGroups, syncSelected, topicButton } from "./choices_view.js";
import {
  addUserMessage, backButton, botMessage, button, clearEmpty, el, log, scrollBottom, tokenHint, truncateAfter, withStatus,
} from "./dom.js";
import { describeMode, renderAnswer, renderSources } from "./answer_view.js";
import { pathKey, Selection, chunkTotal } from "./selection.js";

const MANY_CHUNKS = 6; // これ以上のチャンクを選ぶと回答に時間がかかる（rag_api の settings.many_chunks と同じ）

// 評価モードなど外から差し込む処理（eval_mode.js が設定する）
//   onLevelPicks(picks): ① で選んだ話題が決まったとき（picks: [{label, path}]）
//   afterAnswer(bot, question, topics, data, seconds): ③ の回答を表示した後
export const hooks = { onLevelPicks: null, afterAnswer: null };

// 再検索の入力欄（元の質問を入れておき、書き換えて ① からやり直す）
// 入力: 元の質問・やり直す前に呼ぶ処理 / 出力: 入力欄の行の要素
function researchBox(question, onBefore) {
  const research = el("div", "research");
  const input = el("input");
  input.value = question;
  input.placeholder = "再検索する質問";
  const again = button("再検索", "sub");
  research.appendChild(input);
  research.appendChild(again);
  const go = () => { const v = input.value.trim(); if (!v) return; onBefore(); askLevels(v); };
  again.addEventListener("click", go);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); go(); } });
  return research;
}

// ① 質問 → LLM が作った話題と、当たった見出しの経路を選択肢で表示（複数選択）
// 入力: 質問 / 出力: なし（画面に積む。「次の候補を探す」で 10 件ずつ追加）
export async function askLevels(question) {
  clearEmpty();
  addUserMessage(question);
  const bot = botMessage("知りたい範囲");
  bot.appendChild(el("div", "topics-title", "調べたい話題を選んでください（複数可）。（ ）内はその話題の資料（チャンク）の数です。"));
  const topicBox = el("div", "topics");
  bot.appendChild(topicBox);
  // LLM の話題が合わないとき用: 当たった見出しの経路から直接選ぶ（右ほど細かい範囲）
  const direct = el("details", "direct");
  direct.appendChild(el("summary", "", "見出しから直接選ぶ"));
  const list = el("div", "levels");
  direct.appendChild(list);
  bot.appendChild(direct);
  const { actions, go: next, count } = actionRow("選んだ話題で次へ");
  const more = button("次の候補を探す", "sub");
  actions.appendChild(more);
  bot.appendChild(actions);
  bot.appendChild(researchBox(question, () => truncateAfter(bot)));
  log.appendChild(bot);

  // 選択を受ける: 話題・見出しのどちらのボタンでも切り替え、同じ範囲のボタンは連動させる
  const selection = new Selection((sel) => {
    syncSelected(bot, sel);
    count.textContent = `${sel.size} 件選択中`;
    next.disabled = sel.size === 0;
  });
  const choose = (node, label) => selection.toggle(node.path, { node, label });

  // 選択を次の段（②）へ送る
  next.addEventListener("click", () => {
    truncateAfter(bot);
    const picks = selection.values();
    if (hooks.onLevelPicks) hooks.onLevelPicks(picks.map((x) => ({ label: x.label, path: x.node.path })));
    askSubtopics(question, picks);
  });

  let offset = 0;
  const shown = new Set();       // 表示済みの見出しの経路
  const shownTopics = new Set(); // 表示済みの話題の経路
  async function load() {
    more.disabled = true;
    const data = await withStatus(topicBox, "見出しを検索して話題を作成中", () => fetchLevels(question, offset));
    if (!data) { more.disabled = false; return; }
    // 返ってきた話題を選択肢として表示（表示済みは飛ばす）
    let addedTopics = 0;
    for (const t of data.topics) {
      const k = pathKey(t.node.path);
      if (shownTopics.has(k)) continue;
      shownTopics.add(k);
      addedTopics++;
      topicBox.appendChild(topicButton(t, choose));
    }
    if (!addedTopics) topicBox.appendChild(el("div", "hint", `${offset + 1}〜${offset + 10}件目からは新しい話題を作れませんでした。「見出しから直接選ぶ」も使えます。`));
    // 見出しの経路も選択肢として表示
    let added = 0;
    for (const h of data.hits) {
      const key = pathKey(h.nodes[h.nodes.length - 1].path);
      if (shown.has(key)) continue;
      shown.add(key);
      added++;
      list.appendChild(headingRow(h, choose));
    }
    if (!added) list.appendChild(el("div", "hint", `${offset + 1}〜${offset + 10}件目に新しい見出しはありませんでした。`));
    syncSelected(bot, selection);
    offset = data.next_offset;
    more.disabled = !data.has_more;
    if (!data.has_more) more.textContent = "これ以上の候補はありません";
    scrollBottom();
  }
  more.addEventListener("click", load);
  await load();
}

// ② ① で選んだ範囲 → 配下の 1 段下の話題を選択肢で表示（複数選択）
// 入力: 質問・① の選択 [{node, label}] / 出力: なし
export async function askSubtopics(question, picks) {
  const userMsg = addUserMessage(`選んだ話題: ${picks.map((x) => x.label).join("、")}`);
  const bot = botMessage("話題");
  log.appendChild(bot);
  const back = backButton("← 最初の話題を選び直す", userMsg, bot);
  const data = await withStatus(bot, "配下のチャンクを取得中", () => fetchSubtopics(picks.map((x) => x.node.path)));
  if (!data) { bot.appendChild(back); return; }

  bot.appendChild(el("div", "topics-title", `選んだ範囲の配下にチャンクが ${data.total} 個あります。知りたい話題を選んでください（複数可）。`));
  const { actions, go, count } = actionRow("選んだ話題で回答");
  const warn = el("span", "warn", "");
  actions.appendChild(warn);

  // 選択を受ける: 件数と、重なりを除いたチャンク数・時間がかかる警告を更新する
  const selection = new Selection((sel) => {
    syncSelected(bot, sel);
    const n = chunkTotal(sel.values());
    count.textContent = `${sel.size} 件選択中 / チャンク ${n} 個`;
    warn.textContent = n >= MANY_CHUNKS ? "チャンクが6個以上のため、回答に時間がかかります" : "";
    go.disabled = sel.size === 0;
  });
  renderSubtopicGroups(bot, data.groups, (t) => selection.toggle(t.path, t));

  bot.appendChild(actions);
  bot.appendChild(researchBox(question, () => truncateAfter(bot)));
  bot.appendChild(back);

  // 選択を次の段（③）へ送る
  go.addEventListener("click", () => {
    const topics = selection.values();
    truncateAfter(bot);
    askAnswer(question, topics, chunkTotal(topics) >= MANY_CHUNKS);
  });
  scrollBottom();
}

// ③ ② で選んだ話題 → 回答と出典を表示
// 入力: 質問・② の選択 [{title, path, chunk_count}]・チャンクが多いか / 出力: なし
export async function askAnswer(question, topics, many) {
  const userMsg = addUserMessage(`選んだ話題: ${topics.map((t) => t.title).join("、")}`);
  const bot = botMessage("回答");
  if (many) bot.appendChild(el("div", "warn", "チャンクが6個以上のため、回答に時間がかかります。"));
  log.appendChild(bot);
  const data = await withStatus(bot, "回答生成中", () => fetchAnswer(question, topics.map((t) => t.path)));
  if (!data) { bot.appendChild(backButton("← 話題を選び直す", userMsg, bot)); return; }
  bot.appendChild(el("div", "topics-title", describeMode(data)));
  renderAnswer(bot, data.answer);
  bot.appendChild(tokenHint(data, bot.dataset.seconds));
  renderSources(bot, data.sources);
  if (hooks.afterAnswer) hooks.afterAnswer(bot, question, topics, data, bot.dataset.seconds);
  bot.appendChild(backButton("← 話題を選び直す", userMsg, bot));
}
