"""RAGAS で RAG（階層を選んで回答するフロー）を評価する。

2段階に分けて実行する:
  collect : テスト用の質問を rag-api に送り、回答と LLM に渡した資料を集める（ローカルのみ・費用なし）
  score   : 集めた結果を RAGAS で採点する（評価用の LLM に Claude を使う・API 費用あり）

階層のフローはボタンで選ぶため、評価では自動で「一番上の候補」を選ぶ:
  ① /levels の話題の1件目（話題が無ければ、検索1位のチャンクの一番細かい見出し）
  ② /subtopics の話題の1件目
  ③ /answer で回答

実行（プロジェクトのルートで）:
  .venv/bin/python src/eval_ragas.py collect [--name 設定名]
  .venv/bin/python src/eval_ragas.py score data/eval/results/<日時>_<設定名>
APIキー: プロジェクトのルートの .env に ANTHROPIC_API_KEY=... を書く（.gitignore 済み）
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TESTSET = ROOT / "data/eval/testset.jsonl"
RESULTS = ROOT / "data/eval/results"
API = "http://localhost:8000"

JUDGE_MODEL = "claude-opus-5-5"
EMBEDDING_MODEL = "cl-nagoya/ruri-v3-310m"


# ==========================================
# 1. collect: rag-api に質問を送って回答と資料を集める
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
        node, picked = lv["topics"][0]["node"], f"話題: {lv['topics'][0]['title']}"
    elif lv["hits"]:
        node, picked = lv["hits"][0]["nodes"][-1], "見出し（検索1位）"
    else:
        raise RuntimeError("候補がありません")

    sub = post("/subtopics", {"paths": [node["path"]]})
    topic = sub["groups"][0]["topics"][0]

    ans = post("/answer", {"question": question, "paths": [topic["path"]]})
    return {
        "level_pick": picked,
        "level_path": node["path"],
        "subtopic_path": topic["path"],
        "answer": ans["answer"],
        "contexts": ans["contexts"],
        "mode": ans["mode"],
        "total_chunks": ans["total_chunks"],
        "prompt_tokens": ans["prompt_tokens"],
        "seconds": round(time.time() - started, 1),
    }


def collect(name: str) -> Path:
    items = [json.loads(l) for l in TESTSET.read_text(encoding="utf-8").splitlines() if l.strip()]
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
# 2. score: Claude（評価用 LLM）と Ruri（Embedding）で RAGAS を実行
# ==========================================

def build_judge():
    import anthropic
    from langchain_core.outputs import Generation, LLMResult
    from ragas.llms.base import BaseRagasLLM

    class ClaudeJudge(BaseRagasLLM):
        """RAGAS の採点用 LLM として Claude を呼ぶ（公式 SDK を直接使う）。

        Claude Opus 5.5 は temperature を受け付けないので、RAGAS が渡す temperature は使わない。
        n 個の回答を求められたときは n 回呼ぶ。
        """

        def __init__(self, model: str):
            super().__init__()
            self.model = model
            self.client = anthropic.Anthropic()
            self.aclient = anthropic.AsyncAnthropic()

        def _params(self, prompt) -> dict:
            return dict(
                model=self.model,
                max_tokens=16000,
                output_config={"effort": "medium"},
                messages=[{"role": "user", "content": prompt.to_string()}],
                # 安全分類で断られたときは、API 側で別モデルに切り替えて続行する
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )

        @staticmethod
        def _to_generation(msg) -> Generation:
            if msg.stop_reason == "refusal":
                raise RuntimeError(f"採点が拒否されました: {msg.stop_details}")
            text = "".join(b.text for b in msg.content if b.type == "text")
            return Generation(text=text, generation_info={"stop_reason": msg.stop_reason})

        def generate_text(self, prompt, n=1, temperature=0.01, stop=None, callbacks=None):
            gens = [self._to_generation(self.client.beta.messages.create(**self._params(prompt)))
                    for _ in range(n)]
            return LLMResult(generations=[gens])

        async def agenerate_text(self, prompt, n=1, temperature=0.01, stop=None, callbacks=None):
            gens = []
            for _ in range(n):
                msg = await self.aclient.beta.messages.create(**self._params(prompt))
                gens.append(self._to_generation(msg))
            return LLMResult(generations=[gens])

        def is_finished(self, response) -> bool:
            return all(
                g.generation_info.get("stop_reason") != "max_tokens"
                for gs in response.generations for g in gs
            )

    return ClaudeJudge(JUDGE_MODEL)


def build_embeddings():
    from ragas.embeddings.base import BaseRagasEmbeddings
    from sentence_transformers import SentenceTransformer

    class RuriEmbeddings(BaseRagasEmbeddings):
        """Answer Relevancy で「回答から作った質問」と「元の質問」を比べるための Ruri v3。"""

        PREFIX = "検索クエリ: "  # 比べるのはどちらも質問文

        def __init__(self):
            super().__init__()
            self.model = EMBEDDING_MODEL  # RAGAS が利用記録にモデル名（文字列）として読む
            self._st = SentenceTransformer(EMBEDDING_MODEL)

        def embed_query(self, text):
            return self._st.encode(self.PREFIX + text, normalize_embeddings=True).tolist()

        def embed_documents(self, texts):
            return self._st.encode([self.PREFIX + t for t in texts], normalize_embeddings=True).tolist()

        async def aembed_query(self, text):
            return self.embed_query(text)

        async def aembed_documents(self, texts):
            return self.embed_documents(texts)

    return RuriEmbeddings()


def score(run_dir: Path, only: list[str] | None = None):
    from dotenv import load_dotenv
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import (
        Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy,
    )
    from ragas.run_config import RunConfig

    load_dotenv(ROOT / ".env")
    recs = [json.loads(l) for l in (run_dir / "collected.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = [r for r in recs if "error" not in r]
    print(f"採点対象 {len(ok)}/{len(recs)} 問（評価用 LLM: {JUDGE_MODEL}）")

    dataset = EvaluationDataset(samples=[
        SingleTurnSample(
            user_input=r["question"], response=r["answer"],
            retrieved_contexts=r["contexts"], reference=r["reference"],
        )
        for r in ok
    ])
    all_metrics = {
        "faithfulness": Faithfulness(), "answer_relevancy": ResponseRelevancy(),
        "llm_context_precision_with_reference": LLMContextPrecisionWithReference(),
        "context_recall": LLMContextRecall(),
    }
    chosen = [all_metrics[m] for m in (only or all_metrics)]
    result = evaluate(
        dataset=dataset,
        metrics=chosen,
        llm=build_judge(),
        embeddings=build_embeddings(),
        run_config=RunConfig(max_workers=4, timeout=600),
    )

    df = result.to_pandas()
    if only and (run_dir / "scores.csv").exists():
        # 指定した指標だけ採点し直し、前回の scores.csv の列を置き換える
        import pandas as pd
        prev = pd.read_csv(run_dir / "scores.csv")
        for m in only:
            prev[m] = df[m].values
        df = prev
    else:
        df.insert(0, "id", [r["id"] for r in ok])
        df.insert(1, "type", [r["type"] for r in ok])
        df["mode"] = [r["mode"] for r in ok]
        df["level_pick"] = [r["level_pick"] for r in ok]
    df.to_csv(run_dir / "scores.csv", index=False, encoding="utf-8-sig")

    metrics = ["faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall"]
    metrics = [m for m in metrics if m in df.columns]
    summary = {
        "judge_model": JUDGE_MODEL,
        "questions": len(ok),
        "mean": {m: round(float(df[m].mean()), 3) for m in metrics},
        "mean_by_type": {
            t: {m: round(float(g[m].mean()), 3) for m in metrics} for t, g in df.groupby("type")
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("保存:", (run_dir / "scores.csv").relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collect")
    c.add_argument("--name", default="current")
    s = sp.add_parser("score")
    s.add_argument("run_dir")
    s.add_argument("--only", nargs="+", help="この指標だけ採点し直す（例: answer_relevancy）")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.name)
    else:
        score(Path(a.run_dir), a.only)


if __name__ == "__main__":
    sys.exit(main())
