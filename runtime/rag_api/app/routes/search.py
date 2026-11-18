"""/search（検索のみ）と /ask（検索結果で回答）。"""

from fastapi import APIRouter, Depends
from qdrant_client import QdrantClient

from ..deps import get_embedder, get_qdrant
from ..embedding import QueryEmbedder
from ..qdrant_store import chunks
from ..schemas import AskResponse, QuestionRequest, SearchResponse
from ..services.search import answer_with_sources, search_chunks

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
def search(body: QuestionRequest, embedder: QueryEmbedder = Depends(get_embedder), client: QdrantClient = Depends(get_qdrant)):
    """入力: {question, top_k, mode?, paths?} / 出力: 順位の高いチャンク top_k 件
    mode で検索方式（dense / bm25 / hybrid）を、paths で見出しの範囲を指定できる（検索の比較・確認用）"""
    query_filter = chunks.paths_filter(body.paths) if body.paths else None
    sources = search_chunks(embedder, client, body.question, body.top_k, query_filter=query_filter, mode=body.mode)
    return SearchResponse(question=body.question, sources=sources)


@router.post("/ask", response_model=AskResponse)
def ask(body: QuestionRequest, embedder: QueryEmbedder = Depends(get_embedder), client: QdrantClient = Depends(get_qdrant)):
    """入力: {question, top_k} / 出力: 検索で当たったチャンクを根拠にした回答とそのチャンク"""
    sources = search_chunks(embedder, client, body.question, body.top_k)
    return AskResponse(question=body.question, answer=answer_with_sources(body.question, sources), sources=sources)
