"""routes が使う共有の部品（起動時に main.py の lifespan で作ったもの）を取り出す。

FastAPI の Depends で受け取る:
  embedder: QueryEmbedder = Depends(get_embedder)
  client:   QdrantClient  = Depends(get_qdrant)
"""

from fastapi import Request
from qdrant_client import QdrantClient

from .embedding import QueryEmbedder


def get_embedder(request: Request) -> QueryEmbedder:
    """入力: リクエスト / 出力: 起動時に読み込んだ質問用の Embedding モデル"""
    return request.app.state.embedder


def get_qdrant(request: Request) -> QdrantClient:
    """入力: リクエスト / 出力: 起動時に作った Qdrant のクライアント"""
    return request.app.state.qdrant
