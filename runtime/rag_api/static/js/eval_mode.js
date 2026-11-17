// 評価モード: テストの質問を1問ずつ自分で選んで回答し、結果を FastAPI 経由で記録する
// 記録先: data/eval/results/<記録名>/collected.jsonl（採点は runtime の外の evaluation/eval_ragas.py）

import { fetchEvalQuestions, fetchEvalStatus, postEvalRecord } from "./api.js";
import { $, button, el, log } from "./dom.js";
import { askLevels, hooks } from "./flow.js";
import { modeSel } from "./question_input.js";

const RUN_KEY = "rag-eval-run"; // ブラウザに記録名を覚えておくキー（閉じても続きから再開する）
const state = { on: false, model: "", questions: [], recorded: {}, current: null, levelPicks: [] };

// 入力: なし / 出力: 新しい記録名（日時_manual_モデル 例: 20261117_1030_manual_qwen2-5-7b）
function newRunName() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  const model = (state.model || "").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}_manual${model ? "_" + model : ""}`;
}
const getRun = () => $("evalRun").value.trim();
function saveRun() { try { localStorage.setItem(RUN_KEY, getRun()); } catch (e) { /* 保存できなくても続行 */ } }
function loadRun() { try { return localStorage.getItem(RUN_KEY); } catch (e) { return null; } }

// 記録の状況を取り直し、問題の一覧（✓ 記録済み / － スキップ）と進み具合を表示する
// 入力: 選んでおく問題の id（省略時は今の選択か、最初の未記録） / 出力: なし
async function refresh(selectId) {
  state.recorded = (await fetchEvalStatus(getRun())).recorded;
  const sel = $("evalSelect");
  const keep = selectId || sel.value;
  sel.textContent = "";
  for (const x of state.questions) {
    const st = state.recorded[x.id];
    const o = el("option", "", `${st === "done" ? "✓" : st === "skipped" ? "－" : "　"} ${x.id} [${x.type}] ${x.question}`);
    o.value = x.id;
    sel.appendChild(o);
  }
  const firstTodo = state.questions.find((x) => !state.recorded[x.id]);
  sel.value = keep && state.questions.some((x) => x.id === keep) ? keep : (firstTodo || state.questions[0] || {}).id;
  $("evalProgress").textContent = `記録 ${Object.keys(state.recorded).length} / ${state.questions.length} 問`;
}

// 評価モードのオン・オフ（オンにしたとき質問集と記録名を用意する）
async function setEval(on) {
  state.on = on;
  $("evalBar").classList.toggle("on", on);
  if (!on) return;
  modeSel.value = "levels";
  if (!state.questions.length) {
    try {
      state.questions = (await fetchEvalQuestions()).questions;
    } catch (err) {
      $("evalQuestion").textContent = `質問集を読めません: ${err.message}`;
      return;
    }
  }
  if (!getRun()) {
    // 保存されている記録名が別のモデルのもの（末尾がモデル名でない）なら、上書きしないよう新しい記録にする
    const saved = loadRun();
    const fresh = newRunName();
    const suffix = fresh.slice(fresh.indexOf("_manual"));
    $("evalRun").value = saved && saved.endsWith(suffix) ? saved : fresh;
    saveRun();
  }
  await refresh();
}

// 選んだ問題で ① から始める（前のやり取りは消す）
function start() {
  const x = state.questions.find((y) => y.id === $("evalSelect").value);
  if (!x) return;
  state.current = x;
  state.levelPicks = [];
  $("evalQuestion").textContent = `${x.id}：${x.question}`;
  log.textContent = "";
  modeSel.value = "levels";
  askLevels(x.question);
}

// 1問分の結果を送って記録し、次の未記録の問題を選んでおく
// 入力: 記録内容・結果を表示する要素 / 出力: 成功したか
async function record(payload, msgBox) {
  try {
    const r = await postEvalRecord({ run: getRun(), ...payload });
    msgBox.textContent = `記録しました（${r.saved}、${r.count} 問）`;
    const idx = state.questions.findIndex((y) => y.id === payload.id);
    await refresh();
    const next = state.questions.slice(idx + 1).find((y) => !state.recorded[y.id]);
    if (next) $("evalSelect").value = next.id;
    return true;
  } catch (err) {
    msgBox.textContent = `記録に失敗: ${err.message}`;
    return false;
  }
}

// ③ の回答の下に「この回答を記録して次へ」を出す（flow.js の hooks.afterAnswer から呼ばれる）
function addRecordButton(bot, question, topics, data, seconds) {
  if (!state.on || !state.current) return;
  const x = state.current;
  const box = el("div", "eval-actions");
  box.appendChild(el("div", "topics-title", `評価：${x.id} の回答として記録します`));
  const actions = el("div", "actions");
  const save = button("この回答を記録して次へ");
  actions.appendChild(save);
  box.appendChild(actions);
  const msg = el("div", "hint", state.recorded[x.id] ? "※ この質問は記録済みです。記録すると置き換えます。" : "");
  box.appendChild(msg);
  save.addEventListener("click", async () => {
    save.disabled = true;
    const ok = await record({
      id: x.id, question,
      level_picks: state.levelPicks,
      subtopic_picks: topics.map((t) => ({ title: t.title, path: t.path })),
      answer: data.answer, contexts: data.contexts, mode: data.mode,
      total_chunks: data.total_chunks, prompt_tokens: data.prompt_tokens, seconds: Number(seconds),
    }, msg);
    if (ok) start(); else save.disabled = false;
  });
  bot.appendChild(box);
}

// 回答まで進めない問題はスキップとして記録する（採点の対象外）
async function skip() {
  const x = state.questions.find((y) => y.id === $("evalSelect").value);
  if (!x) return;
  if (await record({ id: x.id, question: x.question, skipped: true }, $("evalQuestion"))) start();
}

// 評価モードのボタンにイベントを付ける（main.js から呼ぶ）
// 入力: 動作中の LLM のモデル名・評価モードが使えるか / 出力: なし
export function initEvalMode(model, enabled) {
  if (!enabled) { $("evalToggleLabel").style.display = "none"; return; }
  state.model = model || "";
  $("evalProgress").title = `LLM: ${state.model}`;
  hooks.onLevelPicks = (picks) => { state.levelPicks = picks; };
  hooks.afterAnswer = addRecordButton;
  $("evalToggle").addEventListener("change", (e) => setEval(e.target.checked));
  $("evalStart").addEventListener("click", start);
  $("evalSkip").addEventListener("click", skip);
  $("evalRun").addEventListener("change", () => { saveRun(); refresh(); });
  $("evalNewRun").addEventListener("click", () => { $("evalRun").value = newRunName(); saveRun(); refresh(); });
  if (new URLSearchParams(location.search).get("eval") === "1") {
    $("evalToggle").checked = true;
    setEval(true);
  }
}
