"""評価モード: テストの質問集を読み、画面で選んで回答した結果を記録する。

置き場所: settings.eval_dir（compose で data/eval をつなぐ）
  入力: <eval_dir>/<settings.eval_testset>（1行1問の JSONL: id, type, question, reference, source）
  出力: <eval_dir>/results/<記録名>/collected.jsonl（1行1問。同じ id は置き換え）
採点は runtime の外（evaluation/eval_ragas.py）で行う。
"""

import json
from pathlib import Path

from fastapi import HTTPException

from ..config import settings
from ..schemas import EvalRecord


def read_jsonl(path: Path) -> list[dict]:
    """入力: JSONL のパス / 出力: 1行ずつの dict（ファイルが無ければ空）"""
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def testset() -> list[dict]:
    """入力: なし / 出力: 質問集の全問"""
    return read_jsonl(settings.eval_dir / settings.eval_testset)


def run_dir(run: str) -> Path:
    """入力: 記録名 / 出力: 記録のフォルダ（英数字と _ - 以外は拒否してパスの外に出さない）"""
    if not run or not all(c.isalnum() or c in "_-" for c in run):
        raise HTTPException(400, "run の名前が不正です")
    return settings.eval_dir / "results" / run


def questions() -> dict:
    """入力: なし / 出力: 画面に出す質問の一覧（正解 reference は選び方に影響しないよう渡さない）"""
    items = testset()
    if not items:
        raise HTTPException(404, f"{settings.eval_testset} が見つかりません（compose で data/eval をつないでください）")
    return {"testset": settings.eval_testset, "questions": [
        {"id": x["id"], "type": x["type"], "question": x["question"]} for x in items]}


def status(run: str) -> dict:
    """入力: 記録名 / 出力: 記録済みの問題（id → "done" / "skipped"）"""
    recs = read_jsonl(run_dir(run) / "collected.jsonl")
    return {"run": run, "recorded": {r["id"]: ("skipped" if r.get("skipped") else "done") for r in recs}}


def record(body: EvalRecord) -> dict:
    """入力: 1問分の結果 / 出力: 保存先と記録済みの数
    質問集の type・reference・source も一緒に残す。同じ id があれば置き換える（やり直し用）。"""
    items = testset()
    order = {x["id"]: i for i, x in enumerate(items)}
    ref = next((x for x in items if x["id"] == body.id), None)
    if not ref:
        raise HTTPException(400, f"{body.id} は質問集にありません")
    d = run_dir(body.run)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "collected.jsonl"
    recs = [r for r in read_jsonl(path) if r["id"] != body.id]
    rec = {**ref, **body.model_dump(exclude={"run"})}
    rec["question"] = ref["question"]  # 採点は元の質問文で行う（再検索で書き換えても）
    rec["asked_question"] = body.question
    recs.append(rec)
    recs.sort(key=lambda r: order.get(r["id"], len(order)))  # 質問集の順に並べる
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return {"ok": True, "saved": str(path.relative_to(settings.eval_dir)), "count": len(recs)}
