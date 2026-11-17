// 画面の起動: 各モジュールを組み立てる
//
// モジュールの役割:
//   api.js            FastAPI への送信と受信（通信はすべてここ）
//   question_input.js 質問を受ける（入力欄・送信、/search・/ask の表示）
//   flow.js           ① 話題 → ② 細かい話題 → ③ 回答 の流れ（各段の送信・表示・選択をつなぐ）
//   choices_view.js   返ってきた候補を選択肢（ボタン）として表示する
//   selection.js      選択を受けて保持する（複数選択・重なりを除いたチャンク数）
//   answer_view.js    回答と出典を表示する
//   dom.js            画面の共通部品（要素作成・待ち時間・戻るボタン）
//   eval_mode.js      評価モード（RAGAS 用の記録）

import { fetchHealth } from "./api.js";
import { initEvalMode } from "./eval_mode.js";
import { initQuestionInput } from "./question_input.js";

initQuestionInput();

// 動作中の LLM のモデル名と、評価モードが使えるかを FastAPI に聞いてから評価モードを用意する
fetchHealth()
  .then((h) => initEvalMode(h.llm_model, h.eval_enabled !== false))
  .catch(() => initEvalMode("", true));
