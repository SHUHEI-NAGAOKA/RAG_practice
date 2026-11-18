"""検索方式（dense / bm25 / hybrid）を、LLM を通さずに比べる。

①（/levels）は質問でチャンクを検索し、当たったチャンクの見出しを話題の候補にする。
ここでは rag-api の /search（mode を指定）で同じ件数を取り、正解の見出しの配下のチャンクが
上位に入るかを数える。

入力: data/eval/<testset>（質問）・data/eval/search_gold_v3.json（質問ごとの正解の見出しの経路）
      rag-api（http://localhost:8000）。/search の mode で方式を切り替えるので、SEARCH_MODE は何でもよい
出力: 画面に表と、data/eval/results/search_compare_<日時>.json（質問ごとの順位）
指標:
  hit@k      : 上位 k 件のどれかが正解の見出しのどれかの配下にある問題の割合（k=5,10。①は10件を見る）
  all@10     : 正解の見出しが複数あるとき、すべてが上位10件に現れる割合（比べる質問で両方の文書が出るか）
  MRR        : 最初に正解が出た順位の逆数の平均（出なければ 0）
実行: .venv/bin/python evaluation/compare_search.py [--gold data/eval/search_gold_v3.json] [--k 10]
"""

import argparse
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8000"
MODES = ["dense", "bm25", "hybrid"]
SEP = " > "


def under(source: dict, path: list[str]) -> bool:
    """入力: 検索結果の1件・見出しの経路 / 出力: そのチャンクが経路の配下にあるか"""
    return source["headings"][: len(path)] == path


def judge(sources: list[dict], gold: list[list[str]], k: int) -> dict:
    """入力: 検索結果（順位順）・正解の経路・見る件数 / 出力: 最初の正解の順位、各正解が現れたか"""
    first = next((i for i, s in enumerate(sources[:k], 1) if any(under(s, g) for g in gold)), None)
    each = [any(under(s, g) for s in sources[:k]) for g in gold]
    return {"first": first, "each": each}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=str(ROOT / "data/eval/search_gold_v3.json"))
    ap.add_argument("--k", type=int, default=10)
    a = ap.parse_args()
    spec = json.loads(Path(a.gold).read_text(encoding="utf-8"))
    questions = {}
    for line in (ROOT / "data/eval" / spec["testset"]).read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            questions[q["id"]] = q

    rows = []
    for qid, gold in spec["gold"].items():
        q = questions[qid]
        row = {"id": qid, "type": q["type"], "question": q["question"]}
        for m in MODES:
            r = requests.post(f"{API}/search", json={"question": q["question"], "top_k": a.k, "mode": m}, timeout=300)
            r.raise_for_status()
            row[m] = judge(r.json()["sources"], gold, a.k)
        rows.append(row)
        print(qid, " ".join(f"{m}:{row[m]['first'] or '-'}" for m in MODES), flush=True)

    def summary(sel):
        out = {}
        for m in MODES:
            firsts = [r[m]["first"] for r in sel]
            multi = [r for r in sel if len(r[m]["each"]) > 1]
            out[m] = {
                "hit@5": round(sum(1 for f in firsts if f and f <= 5) / len(sel), 3),
                f"hit@{a.k}": round(sum(1 for f in firsts if f) / len(sel), 3),
                f"all@{a.k}": round(sum(all(r[m]["each"]) for r in multi) / len(multi), 3) if multi else None,
                "MRR": round(sum(1 / f for f in firsts if f) / len(sel), 3),
            }
        return out

    result = {"gold": a.gold, "k": a.k, "all": summary(rows), "by_type": {}}
    for t in sorted({r["type"] for r in rows}):
        result["by_type"][t] = summary([r for r in rows if r["type"] == t])
    result["rows"] = rows
    out = ROOT / "data/eval/results" / f"search_compare_{time.strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n全体（{len(rows)}問）")
    for m, v in result["all"].items():
        print(f"  {m:7s}", v)
    for t, s in result["by_type"].items():
        print(f"[{t}]", " / ".join(f"{m} hit@{a.k}={s[m][f'hit@{a.k}']} MRR={s[m]['MRR']}" for m in MODES))
    print("保存:", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
