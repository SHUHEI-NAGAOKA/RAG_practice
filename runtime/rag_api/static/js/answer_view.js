// FastAPI から返ってきた回答と出典を表示する

import { el } from "./dom.js";

// 出典（検索で当たったチャンク）を開閉できる一覧で表示する
// 入力: 表示先・sources [{source_number, headings, page_numbers, score, text}] / 出力: なし
export function renderSources(container, sources) {
  if (!sources || sources.length === 0) return;
  const box = el("div", "sources");
  box.appendChild(el("div", "sources-title", "出典"));
  for (const s of sources) {
    const d = el("details");
    const sum = el("summary");
    const heading = s.headings && s.headings.length ? s.headings.join(" > ") : "（見出しなし）";
    sum.appendChild(document.createTextNode(`[${s.source_number}] ${heading} `));
    sum.appendChild(el("span", "meta", `p.${(s.page_numbers || []).join(", ")} / score ${s.score.toFixed(4)}`));
    d.appendChild(sum);
    d.appendChild(el("div", "body", s.text));
    box.appendChild(d);
  }
  container.appendChild(box);
}

// ③ の回答方式の説明（全チャンクか、上位チャンク＋節の本文か）
// 入力: /answer の結果 / 出力: 説明の文字列
export function describeMode(data) {
  if (data.mode === "all") return `チャンク ${data.total_chunks} 個をすべて使用`;
  const secs = data.json_sections
    .map((j) => `${j.title} ${j.chars}字${j.truncated ? "・上限で途中まで" : ""}`)
    .join("、");
  return `チャンク ${data.total_chunks} 個のうち上位 ${data.sources.length} 個 ＋ JSON の節の本文（${secs}）`;
}

// 回答の本文を表示する
// 入力: 表示先・回答の文字列 / 出力: なし
export function renderAnswer(container, answer) {
  container.appendChild(el("div", "answer", answer));
}
