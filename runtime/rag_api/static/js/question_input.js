// 質問を受ける（入力欄と送信）。モードに応じて FastAPI に投げ、結果を表示する
//   levels : 階層を選んで回答（flow.js の ① へ渡す）
//   ask    : /ask（検索結果で回答）
//   search : /search（検索のみ）

import { fetchAsk, fetchSearch } from "./api.js";
import { $, addUserMessage, botMessage, clearEmpty, el, log, scrollBottom } from "./dom.js";
import { renderAnswer, renderSources } from "./answer_view.js";
import { askLevels } from "./flow.js";

const form = $("form");
const q = $("q");
const send = $("send");
export const modeSel = $("mode");
const topkInput = $("topk");

// 入力: なし / 出力: top_k（1〜10 以外なら 3）
function getTopK() {
  const topK = parseInt(topkInput.value, 10);
  return topK >= 1 && topK <= 10 ? topK : 3;
}

// 入力欄を空にして高さを戻す
function resetInput() {
  q.value = "";
  q.style.height = "";
}

// /search・/ask: 質問を送り、回答（ask のとき）と出典を表示する
// 入力: 質問・モード / 出力: なし
async function askSimple(question, mode) {
  clearEmpty();
  addUserMessage(question);
  const bot = botMessage(mode === "ask" ? "回答" : "検索結果");
  const status = el("div", "loading", mode === "ask" ? "回答生成中… 0秒" : "検索中…");
  bot.appendChild(status);
  log.appendChild(bot);
  scrollBottom();
  const started = Date.now();
  const timer = setInterval(() => {
    if (mode === "ask") status.textContent = `回答生成中… ${Math.floor((Date.now() - started) / 1000)}秒`;
  }, 1000);
  try {
    const data = mode === "ask" ? await fetchAsk(question, getTopK()) : await fetchSearch(question, getTopK());
    status.remove();
    if (mode === "ask") renderAnswer(bot, data.answer);
    renderSources(bot, data.sources);
    if (mode === "ask") bot.appendChild(el("div", "hint", `${((Date.now() - started) / 1000).toFixed(1)}秒`));
  } catch (err) {
    status.remove();
    bot.appendChild(el("div", "error", `エラー: ${err.message}`));
  } finally {
    clearInterval(timer);
    scrollBottom();
  }
}

// 送信: 入力欄の質問を、選んでいるモードで処理する
async function submit() {
  const question = q.value.trim();
  if (!question) return;
  const mode = modeSel.value;
  resetInput();
  send.disabled = true;
  try {
    if (mode === "levels") await askLevels(question);
    else await askSimple(question, mode);
  } finally {
    send.disabled = false;
    q.focus();
  }
}

// 入力欄と送信ボタンにイベントを付ける（main.js から1回呼ぶ）
export function initQuestionInput() {
  form.addEventListener("submit", (e) => { e.preventDefault(); if (!send.disabled) submit(); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (!send.disabled) submit();
    }
  });
  q.addEventListener("input", () => {
    q.style.height = "";
    q.style.height = Math.min(q.scrollHeight, 160) + "px";
  });
}
