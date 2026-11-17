"""RAGAS の指標で RAG（階層を選んで回答するフロー）を評価する。API は使わない。

流れ:
  1. 回答を集める（どちらか）
     - 手動: Web 画面の「評価モード」で質問ごとに自分で話題を選び、記録する
             → data/eval/results/<記録名>/collected.jsonl（rag-api の評価モードが書き込む。runtime/.env の EVAL_HOST_DIR）
     - 自動: collect で各段の一番上の候補を選んで回答させる
  2. sheet : 判定用の資料（質問・正解・回答・LLM に渡した資料）を grading_sheet.md に出す
  3. 判定  : Claude Code（会話の中の Claude）が資料を読み、judgments.jsonl に判定を書く
  4. score : 判定から RAGAS と同じ式で 4 指標を計算し、scores.csv / summary.json に出す

judgments.jsonl（1行1問）の形:
  {"id": "q01",
   "answer_claims":    [{"claim": "回答の主張", "supported": true}],      # faithfulness 用
   "gen_questions":    ["回答から逆に作った質問", "...", "..."],           # answer_relevancy 用（3つ）
   "noncommittal":     false,                                           # 回答がはぐらかし（分からない等）なら true
   "context_verdicts": [true, false],                                   # 渡した資料ごとに正解を導くのに役立つか（順番どおり）
   "reference_claims": [{"claim": "正解の文", "attributed": true}],     # context_recall 用
   "note": "判定メモ"}

指標の式（RAGAS 0.4 と同じ）:
  faithfulness       = 資料で裏付けられた回答の主張 / 回答の主張の数
  answer_relevancy   = mean(cos(元の質問, 回答から作った質問)) × (はぐらかしでなければ 1、そうなら 0)
                       （Embedding は Ruri v3。"検索クエリ: " を付けて比べる）
  context_precision  = Σ_k (precision@k × v_k) / 役立つ資料の数（v_k は k 番目の資料が役立つなら 1）
  context_recall     = 資料から導ける正解の文 / 正解の文の数

実行（プロジェクトのルートで）:
  .venv/bin/python evaluation/eval_ragas.py collect [--name 設定名] [--testset testset_v2.jsonl]
  .venv/bin/python evaluation/eval_ragas.py sheet data/eval/results/<記録名>
  .venv/bin/python evaluation/eval_ragas.py score data/eval/results/<記録名> [--compare data/eval/results/<別の記録>]
"""

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data/eval"
RESULTS = EVAL / "results"
API = "http://localhost:8000"

EMBEDDING_MODEL = "cl-nagoya/ruri-v3-310m"
QUERY_PREFIX = "検索クエリ: "
METRICS = ["faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall"]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ==========================================
# 1. collect: 自動で一番上の候補を選んで回答を集める
# ==========================================

def post(path: str, body: dict) -> dict:
    res = requests.post(f"{API}{path}", json=body, timeout=900)
    res.raise_for_status()
    return res.json()


def run_flow(question: str) -> dict:
    """階層のフローを、各段で一番上の候補を選んで最後まで実行する。"""
    started = time.time()
    lv = post("/levels", {"question": question, "offset": 0})
    if lv["topics"]:
        node, picked = lv["topics"][0]["node"], lv["topics"][0]["title"]
    elif lv["hits"]:
        node = lv["hits"][0]["nodes"][-1]
        picked = node["title"]
    else:
        raise RuntimeError("候補がありません")

    sub = post("/subtopics", {"paths": [node["path"]]})
    topic = sub["groups"][0]["topics"][0]

    ans = post("/answer", {"question": question, "paths": [topic["path"]]})
    return {
        "level_picks": [{"label": picked, "path": node["path"]}],
        "subtopic_picks": [{"title": topic["title"], "path": topic["path"]}],
        "answer": ans["answer"],
        "contexts": ans["contexts"],
        "mode": ans["mode"],
        "total_chunks": ans["total_chunks"],
        "prompt_tokens": ans["prompt_tokens"],
        "seconds": round(time.time() - started, 1),
    }


def collect(name: str, testset: str) -> Path:
    items = read_jsonl(EVAL / testset)
    out_dir = RESULTS / f"{datetime.now():%Y%m%d_%H%M}_{name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "collected.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for i, it in enumerate(items, start=1):
            try:
                rec = {**it, **run_flow(it["question"])}
            except Exception as e:  # 1問の失敗で全体を止めない
                rec = {**it, "error": repr(e)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}/{len(items)}] {it['id']} {rec.get('seconds', '-')}秒 "
                  f"{rec.get('mode', rec.get('error'))}", flush=True)
    print("保存:", out.relative_to(ROOT))
    return out_dir


# ==========================================
# 2. sheet: 判定用の資料を作る
# ==========================================

def usable(recs: list[dict]) -> list[dict]:
    """採点の対象（スキップ・エラー・回答なしを除く）。"""
    return [r for r in recs if not r.get("skipped") and "error" not in r and r.get("answer")]


def picks_text(r: dict) -> str:
    lv = "、".join(p.get("label") or p.get("title", "") for p in r.get("level_picks", []))
    st = "、".join(p.get("title", "") for p in r.get("subtopic_picks", []))
    return f"①{lv or '-'} → ②{st or '-'}"


def sheet(run_dir: Path):
    recs = read_jsonl(run_dir / "collected.jsonl")
    ok = usable(recs)
    lines = [f"# 判定用の資料: {run_dir.name}\n",
             f"採点対象 {len(ok)} / 記録 {len(recs)} 問（スキップ・回答なしは対象外）\n"]
    for r in ok:
        lines += [
            f"\n---\n\n## {r['id']}（{r['type']}）{r['question']}\n",
            f"- 選んだ話題: {picks_text(r)} / 回答方式: {r.get('mode')} / チャンク {r.get('total_chunks')} 個\n",
            f"### 正解（reference）\n{r['reference']}\n",
            f"### 回答\n{r['answer']}\n",
            f"### LLM に渡した資料（{len(r['contexts'])} 件）\n",
        ]
        for i, c in enumerate(r["contexts"], start=1):
            lines.append(f"#### 資料{i}\n```\n{c}\n```\n")
    out = run_dir / "grading_sheet.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"保存: {out}（{len(ok)} 問）")


# ==========================================
# 3. score: 判定から RAGAS と同じ式で計算する
# ==========================================

def ratio(items: list[dict], key: str) -> float:
    return sum(1 for x in items if x[key]) / len(items) if items else math.nan


def average_precision(verdicts: list[bool]) -> float:
    if not verdicts:
        return math.nan
    cumsum, numerator = 0, 0.0
    for i, v in enumerate(verdicts):
        cumsum += int(v)
        if v:
            numerator += cumsum / (i + 1)
    return numerator / (cumsum + 1e-10)


class Relevancy:
    """answer_relevancy: 元の質問と、回答から作った質問のコサイン類似度（Ruri v3）。"""

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(EMBEDDING_MODEL)

    def __call__(self, question: str, gen_questions: list[str], noncommittal: bool) -> float:
        gen = [g for g in gen_questions if g.strip()]
        if not gen:
            return math.nan
        vecs = self.model.encode([QUERY_PREFIX + t for t in [question] + gen], normalize_embeddings=True)
        sims = [float(vecs[0] @ v) for v in vecs[1:]]
        return (sum(sims) / len(sims)) * (0 if noncommittal else 1)


def mean(xs: list[float]) -> float:
    xs = [x for x in xs if not math.isnan(x)]
    return round(sum(xs) / len(xs), 3) if xs else math.nan


def summarize(rows: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    return {
        "questions": len(rows),
        "mean": {m: mean([r[m] for r in rows]) for m in METRICS},
        "mean_by_type": {t: {m: mean([r[m] for r in g]) for m in METRICS} for t, g in by_type.items()},
    }


def load_prev_scores(run_dir: Path) -> dict[str, dict]:
    """比べる記録の scores.csv（id → 指標）。"""
    path = run_dir / "scores.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def score(run_dir: Path, compare: Path | None):
    recs = {r["id"]: r for r in usable(read_jsonl(run_dir / "collected.jsonl"))}
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    missing = [i for i in recs if i not in {j["id"] for j in judgments}]
    if missing:
        print("判定が無い問題:", ", ".join(missing))
    rel = Relevancy()

    rows = []
    for j in judgments:
        r = recs.get(j["id"])
        if not r:
            print(f"{j['id']} は採点対象の記録にないため飛ばします")
            continue
        n_ctx = len(r["contexts"])
        if len(j["context_verdicts"]) != n_ctx:
            raise SystemExit(f"{j['id']}: context_verdicts が {len(j['context_verdicts'])} 件ですが、資料は {n_ctx} 件です")
        rows.append({
            "id": j["id"], "type": r["type"],
            "faithfulness": ratio(j["answer_claims"], "supported"),
            "answer_relevancy": rel(r["question"], j["gen_questions"], j.get("noncommittal", False)),
            "llm_context_precision_with_reference": average_precision(j["context_verdicts"]),
            "context_recall": ratio(j["reference_claims"], "attributed"),
            "picks": picks_text(r), "mode": r.get("mode"), "contexts": n_ctx, "note": j.get("note", ""),
        })

    with (run_dir / "scores.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in rows)

    summary = {"judge": "Claude Code（会話内で判定・API 不使用）", "embedding": EMBEDDING_MODEL, **summarize(rows)}

    if compare:
        # 同じ問題どうしで比べる（今回 − 比較先）
        prev = load_prev_scores(compare)
        common = [r for r in rows if r["id"] in prev]
        diff = {}
        for m in METRICS:
            pairs = [(r[m], float(prev[r["id"]][m])) for r in common
                     if prev[r["id"]].get(m) not in (None, "", "nan") and not math.isnan(r[m])]
            if pairs:
                diff[m] = {"今回": mean([a for a, _ in pairs]), "比較先": mean([b for _, b in pairs]),
                           "差": round(mean([a for a, _ in pairs]) - mean([b for _, b in pairs]), 3), "問題数": len(pairs)}
        summary["compare"] = {"run": compare.name, "共通の問題": len(common), "指標": diff}

    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("保存:", run_dir / "scores.csv")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collect")
    c.add_argument("--name", default="auto")
    c.add_argument("--testset", default="testset_v2.jsonl")
    s = sp.add_parser("sheet")
    s.add_argument("run_dir")
    sc = sp.add_parser("score")
    sc.add_argument("run_dir")
    sc.add_argument("--compare", help="比べる記録のフォルダ（scores.csv がある）")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.name, a.testset)
    elif a.cmd == "sheet":
        sheet(Path(a.run_dir))
    else:
        score(Path(a.run_dir), Path(a.compare) if a.compare else None)


if __name__ == "__main__":
    sys.exit(main())
