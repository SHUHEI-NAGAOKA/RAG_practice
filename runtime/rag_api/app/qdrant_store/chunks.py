"""チャンクのコレクション（既定 rag_ruri_v3_310m）を読む。

payload の主な項目（contract/qdrant_schema.json）:
  text, headings, heading_paths（"A > B" 形式で各段の経路）, page_numbers, chunk_id,
  document_id, source_refs
"""

from fastapi import HTTPException
from qdrant_client import QdrantClient, models

from ..config import settings
from ..schemas import Source

COLLECTION = settings.chunks_collection
SEP = settings.heading_sep


def to_source(i: int, point) -> Source:
    """入力: 番号・Qdrant の点 / 出力: 画面向けの Source（payload を詰め替える）"""
    payload = point.payload or {}
    return Source(
        source_number=i,
        score=getattr(point, "score", None) or 0.0,
        document_id=payload.get("document_id"),
        headings=payload.get("headings") or [],
        page_numbers=payload.get("page_numbers") or [],
        text=payload.get("text") or "",
        chunk_id=payload.get("chunk_id"),
        source_refs=payload.get("source_refs") or [],
    )


def paths_filter(paths: list[list[str]]) -> models.Filter:
    """入力: 見出しの経路のリスト / 出力: どれかの見出しの配下にあるチャンクを選ぶ条件
    （heading_paths の完全一致。経路は settings.heading_sep でつないだ文字列で照合する）"""
    return models.Filter(should=[
        models.FieldCondition(key="heading_paths", match=models.MatchValue(value=SEP.join(p)))
        for p in paths
    ])


def count_under(client: QdrantClient, paths: list[list[str]]) -> int:
    """入力: 見出しの経路のリスト / 出力: その配下のチャンク数（重なりは1回だけ数える）"""
    return client.count(COLLECTION, count_filter=paths_filter(paths), exact=True).count


def scroll_under(client: QdrantClient, paths: list[list[str]]) -> list:
    """入力: 見出しの経路のリスト / 出力: その配下のチャンク（Qdrant の点）すべて"""
    points, offset = [], None
    while True:
        batch, offset = client.scroll(
            COLLECTION, scroll_filter=paths_filter(paths), limit=256, offset=offset,
            with_payload=True, with_vectors=False,
        )
        points += batch
        if offset is None:
            return points


def search(
    client: QdrantClient, query_vector: list[float], top_k: int,
    offset: int = 0, query_filter: models.Filter | None = None,
) -> list[Source]:
    """入力: 質問のベクトル・件数・何件目から・絞り込み条件
    出力: 類似度の高い順の Source（source_number は offset+1 から）"""
    try:
        response = client.query_points(
            collection_name=COLLECTION,
            query=query_vector,
            limit=top_k,
            offset=offset,
            query_filter=query_filter,
            with_payload=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant検索エラー: {e}")
    return [to_source(offset + i, p) for i, p in enumerate(response.points, start=1)]
