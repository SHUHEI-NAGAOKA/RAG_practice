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


MODES = ("dense", "bm25", "hybrid")


def query_args(
    query_vector: list[float] | None, question: str | None, top_k: int, offset: int,
    query_filter: models.Filter | None, mode: str,
) -> dict:
    """入力: 質問のベクトル・質問文・件数・何件目から・絞り込み条件・検索方式
    出力: query_points に渡す引数
      dense : ベクトルで検索（これまでと同じ）
      bm25  : 質問文を全文索引（settings.bm25_field）で BM25 検索。分かち書きは Qdrant が行う
      hybrid: dense と BM25 をそれぞれ prefetch し、順位を RRF で統合する
              絞り込み（③の見出しの範囲）は両方の prefetch に付ける。候補数は offset+件数 以上にする"""
    if mode not in MODES:
        raise HTTPException(status_code=500, detail=f"SEARCH_MODE が不正です: {mode}（{'/'.join(MODES)}）")
    text_query = models.TextQuery(text=question or "")
    if mode == "dense":
        return {"query": query_vector, "query_filter": query_filter}
    if mode == "bm25":
        return {"query": text_query, "using": settings.bm25_field, "query_filter": query_filter}
    n = max(settings.hybrid_prefetch, offset + top_k)
    return {
        "prefetch": [
            models.Prefetch(query=query_vector, filter=query_filter, limit=n),
            models.Prefetch(query=text_query, using=settings.bm25_field, filter=query_filter, limit=n),
        ],
        "query": models.FusionQuery(fusion=models.Fusion.RRF),
    }


def search(
    client: QdrantClient, query_vector: list[float] | None, top_k: int,
    offset: int = 0, query_filter: models.Filter | None = None,
    question: str | None = None, mode: str | None = None,
) -> list[Source]:
    """入力: 質問のベクトル・件数・何件目から・絞り込み条件・質問文（bm25/hybrid で使う）・検索方式（既定は settings.search_mode）
    出力: 順位の高い順の Source（source_number は offset+1 から。score は方式ごとの値: cos 類似度・BM25・RRF）"""
    args = query_args(query_vector, question, top_k, offset, query_filter, mode or settings.search_mode)
    try:
        response = client.query_points(
            collection_name=COLLECTION, limit=top_k, offset=offset, with_payload=True, **args,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant検索エラー: {e}")
    return [to_source(offset + i, p) for i, p in enumerate(response.points, start=1)]
