// FastAPI との通信（画面からの送信と受信はすべてこのファイルを通す）
// 入力: 各関数の引数（質問・選んだ経路など） / 出力: FastAPI が返した JSON（Promise）
// 失敗したときは Error を投げる（メッセージは FastAPI の detail か HTTP の状態）

async function request(method, path, payload) {
  const res = await fetch(path, {
    method,
    headers: payload ? { "Content-Type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : `HTTP ${res.status}`);
  return data;
}

export const postJson = (path, payload) => request("POST", path, payload);
export const getJson = (path) => request("GET", path);

// ---- 動作確認 ----
// 出力: {status, llm_model, eval_enabled}
export const fetchHealth = () => getJson("/health");

// ---- 検索のみ・検索結果で回答 ----
// 入力: 質問・件数 / 出力: {question, sources} または {question, answer, sources}
export const fetchSearch = (question, topK) => postJson("/search", { question, top_k: topK });
export const fetchAsk = (question, topK) => postJson("/ask", { question, top_k: topK });

// ---- 階層を選んで回答するフロー ----
// ① 入力: 質問・何件目から / 出力: {topics, hits, next_offset, has_more, prompt_tokens}
export const fetchLevels = (question, offset) => postJson("/levels", { question, offset });
// ② 入力: ①で選んだ見出しの経路のリスト / 出力: {paths, total, groups}
export const fetchSubtopics = (paths) => postJson("/subtopics", { paths });
// ③ 入力: 質問・②で選んだ話題の経路のリスト / 出力: {answer, mode, sources, json_sections, contexts, ...}
export const fetchAnswer = (question, paths) => postJson("/answer", { question, paths });

// ---- 評価モード ----
// 出力: {testset, questions: [{id, type, question}]}
export const fetchEvalQuestions = () => getJson("/eval/questions");
// 入力: 記録名 / 出力: {run, recorded: {id: "done"|"skipped"}}（失敗したら空として扱う）
export const fetchEvalStatus = (run) =>
  getJson(`/eval/status?run=${encodeURIComponent(run)}`).catch(() => ({ run, recorded: {} }));
// 入力: 1問分の結果 / 出力: {ok, saved, count}
export const postEvalRecord = (record) => postJson("/eval/record", record);
