// runtime の画面（ES モジュールに分けた JS）を jsdom で開き、動いている rag-api に対して
// ① 話題 → ② 細かい話題 → ③ 回答 と、評価モードの表示までを実際に操作して確かめる。
// 入力: http://localhost:8000 で動いている rag-api / 出力: 各段の確認結果（標準出力）、失敗なら終了コード 1
// 実行: node tests/ui_runtime_e2e.mjs（LLM を2回使うので数分かかる。記録はしない）
import { createRequire } from "module";
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const require = createRequire(import.meta.url);
const { JSDOM } = require("../tools/doc_editor/node_modules/jsdom");
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const STATIC = path.join(ROOT, "runtime/rag_api/static");
const BASE = process.env.API_BASE || "http://localhost:8000";

// 画面の HTML を読み込み、ブラウザの代わりの global を用意する
const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8").replace(/<script type="module".*?<\/script>/, "");
const dom = new JSDOM(html, { url: BASE + "/?eval=1" });
for (const k of ["window", "document", "location", "localStorage", "Event", "URLSearchParams"]) {
  globalThis[k] = dom.window[k];
}
const realFetch = globalThis.fetch;
globalThis.fetch = (u, opt) => realFetch(new URL(u, BASE), opt); // 相対パスを rag-api に向ける

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, label, ms = 600000) {
  const t = Date.now();
  while (Date.now() - t < ms) { const v = fn(); if (v) return v; await sleep(500); }
  throw new Error(`待ち切れません: ${label}`);
}
const results = [];
const check = (ok, name, info = "") => { results.push([ok ? "PASS" : "FAIL", name, info]); if (!ok) throw new Error(name + " " + info); };

try {
  await import(pathToFileURL(path.join(STATIC, "js/main.js")).href);

  // 評価モード（?eval=1 で自動でオン）: 質問集と記録名
  await waitFor(() => $("evalSelect").options.length > 0, "評価モードの質問一覧");
  check($("evalBar").classList.contains("on"), "評価モードのバーが表示される");
  check(/_manual_qwen2-5-/.test($("evalRun").value), "記録名にモデル名が入る", $("evalRun").value);
  check($("evalSelect").options.length === 30, "質問30問が並ぶ", String($("evalSelect").options.length));

  // ① 質問を送る（質問集の先頭で開始。testset により id が違うので決め打ちしない）→ 話題のボタン
  $("evalSelect").value = $("evalSelect").options[0].value;
  $("evalStart").click();
  const topic = await waitFor(() => document.querySelector(".topics .topic"), "① の話題");
  check(true, "① LLM の話題が表示される", topic.textContent.slice(0, 30));
  const next = [...document.querySelectorAll("button")].find((b) => b.textContent === "選んだ話題で次へ");
  check(next.disabled, "① 未選択では次へが押せない");
  topic.click();
  check(topic.classList.contains("on") && !next.disabled, "① 選択すると次へが押せる");
  next.click();

  // ② 細かい話題 → 選択 → 回答
  const sub = await waitFor(() => [...document.querySelectorAll(".msg.bot")].at(-1).querySelector(".topic"), "② の話題");
  check(true, "② 1段下の話題が表示される", sub.textContent.slice(0, 30));
  sub.click();
  const go = [...document.querySelectorAll("button")].find((b) => b.textContent === "選んだ話題で回答");
  check(!go.disabled, "② 選択すると回答が押せる", document.querySelector(".actions .count")?.textContent);
  go.click();

  // ③ 回答・出典・評価の記録ボタン
  const ans = await waitFor(() => document.querySelector(".msg.bot .answer"), "③ の回答");
  check(ans.textContent.length > 0, "③ 回答が表示される", ans.textContent.slice(0, 40));
  check(!!document.querySelector(".sources details"), "③ 出典が表示される");
  check(!!document.querySelector(".eval-actions button"), "③ 評価の記録ボタンが出る");

  // 戻る: ③ を消して ② を選び直せる
  const back = [...document.querySelectorAll("button")].find((b) => b.textContent === "← 話題を選び直す");
  back.click();
  check(!document.querySelector(".msg.bot .answer"), "戻るで ③ が消える");
} catch (e) {
  results.push(["FAIL", "例外", e.message]);
}
for (const r of results) console.log(r.join("\t"));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`\n${results.length - failed}/${results.length} PASS`);
process.exit(failed ? 1 : 0);
