"""階層を選んで回答するフロー（画面の ①→②→③ に対応）。"""

from fastapi import APIRouter, Depends
from qdrant_client import QdrantClient

from ..deps import get_embedder, get_qdrant
from ..embedding import QueryEmbedder
from ..schemas import (
    AnswerRequest, AnswerResponse, LevelsRequest, LevelsResponse, SubtopicsRequest, SubtopicsResponse,
)
from ..services import answer as answer_service
from ..services import levels as levels_service
from ..services import subtopics as subtopics_service

router = APIRouter()


@router.post("/levels", response_model=LevelsResponse)
def levels(body: LevelsRequest, embedder: QueryEmbedder = Depends(get_embedder), client: QdrantClient = Depends(get_qdrant)):
    """① 入力: {question, offset} / 出力: LLM が作った話題・当たった見出しの経路（10件ずつ）"""
    return levels_service.levels(embedder, client, body.question, body.offset)


@router.post("/subtopics", response_model=SubtopicsResponse)
def subtopics(body: SubtopicsRequest, client: QdrantClient = Depends(get_qdrant)):
    """② 入力: {paths: ①で選んだ見出しの経路} / 出力: 1段下の話題とチャンク数"""
    return subtopics_service.subtopics(client, body.paths)


@router.post("/answer", response_model=AnswerResponse)
def answer(body: AnswerRequest, embedder: QueryEmbedder = Depends(get_embedder), client: QdrantClient = Depends(get_qdrant)):
    """③ 入力: {question, paths: ②で選んだ話題の経路} / 出力: 回答と LLM に渡した資料"""
    return answer_service.answer(embedder, client, body.question, body.paths)
