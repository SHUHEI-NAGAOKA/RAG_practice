"""Qdrant からの読み取り（RAG 実行側は読み取り専用。登録はパイプライン ingest/ が行う）。

- chunks.py    : チャンクのコレクション（ベクトル検索・見出しの範囲で数える／全部取る）
- doc_items.py : 文書要素のコレクション（self_ref で取る・親や子をたどる・節の本文を集める）

コレクションの形は runtime/contract/qdrant_schema.json に書いてある。
"""

from qdrant_client import QdrantClient

from ..config import settings


def connect() -> QdrantClient:
    """入力: なし（settings.qdrant_url） / 出力: Qdrant のクライアント"""
    return QdrantClient(url=settings.qdrant_url, timeout=30)
