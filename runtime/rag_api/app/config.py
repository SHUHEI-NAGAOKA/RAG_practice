"""環境変数から RAG API の設定を読む。

入力: 環境変数（runtime/compose.yaml と runtime/.env で指定）
出力: settings（Settings のインスタンス。ほかのモジュールはここから設定を読む）

このファイル以外では os.getenv を使わない（設定の出どころを1か所にする）。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


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

    # --- Qdrant のコレクションと Embedding（contract/qdrant_schema.json と同じ値にする）---
    chunks_collection: str = os.getenv("COLLECTION_NAME", "rag_ruri_v3_310m")
    doc_items_collection: str = os.getenv("DOC_ITEMS_COLLECTION", "rag_doc_items")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "cl-nagoya/ruri-v3-310m")
    query_prefix: str = "検索クエリ: "  # 登録側の「検索文書: 」と対になる Ruri v3 の接頭辞
    heading_sep: str = " > "  # payload の heading_paths の区切り

    # --- 階層を選んで回答するフローの設定 ---
    levels_page: int = 10  # /levels で1回に見るチャンク数
    many_chunks: int = 6  # 選んだ範囲のチャンクがこれ以上なら「上位＋節の本文」で回答
    top_chunks: int = 5  # その場合に使う上位チャンク数
    reserve_output: int = 1024  # 回答用に空けておくトークン
    prompt_margin: int = 300  # 見出し・区切りなどの余白

    # --- 評価モード（本番では EVAL_ENABLED=false にして無効化する）---
    eval_enabled: bool = _bool("EVAL_ENABLED", True)
    eval_dir: Path = Path(os.getenv("EVAL_DIR", "/app/eval"))
    eval_testset: str = os.getenv("EVAL_TESTSET", "testset_v2.jsonl")

    # --- 画面のファイル ---
    static_dir: Path = field(default=Path(__file__).resolve().parent.parent / "static")


settings = Settings()
