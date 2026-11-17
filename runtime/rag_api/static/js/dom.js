// 画面の共通部品（要素の作成・スクロール・待ち時間の表示・戻るボタン）

export const $ = (id) => document.getElementById(id);
export const log = $("log");          // やり取りを積む欄
export const scroller = $("scroller"); // スクロールする外枠

// 入力: タグ名・クラス名・文字 / 出力: 作った要素
export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// 入力: 文字 / 出力: type="button" のボタン（form の送信にならないように）
export function button(text, cls = "") {
  const b = el("button", cls, text);
  b.type = "button";
  return b;
}

export function scrollBottom() { scroller.scrollTop = scroller.scrollHeight; }

// 最初の「質問を入力してください。」を消す
export function clearEmpty() { $("empty")?.remove(); }

// 待ち時間を表示しながら fn を実行する（LLM が CPU で動くため数十秒〜数分かかる）
// 入力: 表示先の要素・表示する文言・実行する非同期関数 / 出力: fn の結果（失敗したら null、エラーを表示）
// 実行にかかった秒数は container.dataset.seconds に残す
export async function withStatus(container, label, fn) {
  const status = el("div", "loading", `${label}… 0秒`);
  container.appendChild(status);
  scrollBottom();
  const started = Date.now();
  const timer = setInterval(() => {
    status.textContent = `${label}… ${Math.floor((Date.now() - started) / 1000)}秒`;
  }, 1000);
  try {
    return await fn();
  } catch (err) {
    container.appendChild(el("div", "error", `エラー: ${err.message}`));
    return null;
  } finally {
    clearInterval(timer);
    status.remove();
    container.dataset.seconds = ((Date.now() - started) / 1000).toFixed(1);
    scrollBottom();
  }
}

// 入力: API の結果・秒数 / 出力: 「秒数 / LLM入力のトークン数」の小さな注記
export function tokenHint(data, seconds) {
  const tok = data.prompt_tokens != null ? ` / LLM入力 ${data.prompt_tokens} トークン（上限 ${data.num_ctx}）` : "";
  return el("div", "hint", `${seconds}秒${tok}`);
}

// 戻る: ある段より後ろのやり取りを消す（前の段のボタンは押せるまま残すので、選び直せる）
export function truncateAfter(node) {
  while (node.nextSibling) node.nextSibling.remove();
}

// 入力: ボタンの文字・その段のユーザー発言と応答 / 出力: 押すとその段以降を消して前の段に戻るボタン
export function backButton(label, userMsg, bot) {
  const b = button(label, "sub back");
  b.addEventListener("click", () => {
    const prev = userMsg.previousSibling;
    userMsg.remove();
    bot.remove();
    truncateAfter(prev);
    prev.scrollIntoView ? prev.scrollIntoView({ block: "end" }) : scrollBottom();
  });
  return b;
}

// ユーザーの発言（右寄せの吹き出し）を積む
export function addUserMessage(text) {
  const m = el("div", "msg user", text);
  log.appendChild(m);
  return m;
}

// 応答の枠（役割名つき）を作る。積むのは呼び出し側で行う
export function botMessage(role) {
  const bot = el("div", "msg bot");
  bot.appendChild(el("div", "role", role));
  return bot;
}
