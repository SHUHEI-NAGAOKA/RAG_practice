"""RAG API の入口: FastAPI を作り、起動時の準備とルートの登録だけを行う。

起動: uvicorn app.main:app --host 0.0.0.0 --port 8000（runtime/rag_api/Dockerfile）

起動時に1回だけ用意するもの（app.state に置き、deps.py で取り出す）:
  - embedder: 質問を Embedding する Ruri v3
  - qdrant  : Qdrant のクライアント
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .embedding import QueryEmbedder
from .qdrant_store import connect
from .routes import evaluation, qa, search, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時: モデルと Qdrant の接続を用意する / 終了時: 接続を閉じる"""
    app.state.embedder = QueryEmbedder()
    app.state.qdrant = connect()
    yield
    app.state.qdrant.close()


app = FastAPI(title="RAG API", lifespan=lifespan)

# 画面の CSS・JS（/static/...）
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

app.include_router(system.router)
app.include_router(search.router)
app.include_router(qa.router)
if settings.eval_enabled:
    app.include_router(evaluation.router)
