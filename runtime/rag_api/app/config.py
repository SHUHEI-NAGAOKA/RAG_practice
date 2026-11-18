"""環境変数と Qdrant の約束（contract）から RAG API の設定を読む。

入力: 環境変数（runtime/compose.yaml と runtime/.env で指定）
      contract/qdrant_schema.json（コレクション名・Embedding・区切り・BM25 の項目。正本）
出力: settings（Settings のインスタンス。ほかのモジュールはここから設定を読む）

このファイル以外では os.getenv を使わない（設定の出どころを1か所にする）。
Qdrant の形に関わる値は約束ファイルからだけ読む（compose・コードに同じ値を書かない）。
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _contract_path() -> Path:
    """約束ファイルの場所。イメージ内は /app/contract、開発機では runtime/contract"""
    here = Path(__file__).resolve()
    for p in (here.parents[1] / "contract", here.parents[2] / "contract"):
        if (p / "qdrant_schema.json").exists():
            return p / "qdrant_schema.json"
    raise FileNotFoundError("contract/qdrant_schema.json が見つかりません")


CONTRACT = json.loads(_contract_path().read_text(encoding="utf-8"))


def _bool(name: str, default: bool) -> bool:
    """環境変数を真偽値として読む（"1" "true" "yes" "on" を真とする）。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # --- 接続先 ---
    qdrant_url: str = os.getenv("QDRANT_URL", "http://qdrant:6333")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://ollama:11434")

    # --- LLM（3B / 7B の切り替えは .env の LLM_MODEL で行う）---
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:3b")
    num_ctx: int = int(os.getenv("NUM_CTX", "8192"))  # LLM のコンテキスト長（トークン）
    ollama_timeout: int = int(os.getenv("OLLAMA_TIMEOUT", "600"))  # CPU 推論のため長め（秒）

    # --- Qdrant のコレクションと Embedding（約束ファイルから読む）---
    chunks_collection: str = CONTRACT["collections"]["chunks"]["name"]
    doc_items_collection: str = CONTRACT["collections"]["doc_items"]["name"]
    embedding_model: str = CONTRACT["embedding"]["model"]
    query_prefix: str = CONTRACT["embedding"]["query_prefix"]  # 登録側の「検索文書: 」と対になる Ruri v3 の接頭辞
    heading_sep: str = CONTRACT["heading_sep"]  # payload の heading_paths の区切り

    # --- 検索方式 ---
    # dense=Ruri のベクトル / bm25=全文索引の BM25（Qdrant が分かち書き）/ hybrid=両方を RRF で統合
    search_mode: str = os.getenv("SEARCH_MODE", "dense")
    bm25_field: str = CONTRACT["search"]["bm25_field"]  # 全文索引（BM25）を付けた payload の項目
    hybrid_prefetch: int = int(os.getenv("HYBRID_PREFETCH", "30"))  # hybrid で dense・BM25 からそれぞれ取る候補数

    # --- 階層を選んで回答するフローの設定 ---
    levels_page: int = 10  # /levels で1回に見るチャンク数
    many_chunks: int = 6  # 選んだ範囲のチャンクがこれ以上なら「上位＋節の本文」で回答
    top_chunks: int = 5  # その場合に使う上位チャンク数
    reserve_output: int = 1024  # 回答用に空けておくトークン
    prompt_margin: int = 300  # 見出し・区切りなどの余白
    # LLM に渡す資料の【要約】の重なりをまとめる（先頭 summary_dedup_chars 文字が同じ要約は「【要約S1と同じ】」にする）
    summary_dedup: bool = _bool("SUMMARY_DEDUP", True)
    summary_dedup_chars: int = int(os.getenv("SUMMARY_DEDUP_CHARS", "10"))

    # --- 評価モード（既定は無効。開発機では .env で EVAL_ENABLED=true にする）---
    eval_enabled: bool = _bool("EVAL_ENABLED", False)
    eval_dir: Path = Path(os.getenv("EVAL_DIR", "/app/eval"))
    eval_testset: str = os.getenv("EVAL_TESTSET", "testset_v2.jsonl")

    # --- 画面のファイル ---
    static_dir: Path = field(default=Path(__file__).resolve().parent.parent / "static")


settings = Settings()
