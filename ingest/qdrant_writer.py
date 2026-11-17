"""Qdrant への書き込み（パイプライン側。RAG 実行側は読むだけ）。

コレクション名・payload の形・索引は ingest/qdrant_schema.json（約束）に従う。
  chunks    : チャンク（ベクトルあり）。点の ID は uuid5("<document_id>:<chunk_id>")
  doc_items : 文書要素（ベクトルなし）。点の ID は uuid5("<document_id>:<self_ref>")
同じ ID で登録し直すと上書きになる（--recreate ならコレクションごと作り直す）。
"""

import uuid

from qdrant_client import QdrantClient, models

from . import docling_io
from .embedding import schema

BATCH = 256
HEADING_SEP = schema()["heading_sep"]


def connect(url: str) -> QdrantClient:
    """入力: Qdrant の URL / 出力: クライアント"""
    return QdrantClient(url=url, timeout=60)


def ensure_collection(client: QdrantClient, key: str, recreate: bool) -> str:
    """約束どおりのコレクションを用意する。

    入力: クライアント・約束のキー（"chunks" / "doc_items"）・作り直すか
    出力: コレクション名
    """
    s = schema()
    spec = s["collections"][key]
    name = spec["name"]
    if recreate and client.collection_exists(name):
        client.delete_collection(name)
    if not client.collection_exists(name):
        if spec["vectors"]:
            vectors = models.VectorParams(
                size=s["embedding"]["dimension"], distance=getattr(models.Distance, s["embedding"]["distance"].upper()),
            )
        else:
            vectors = {}
        client.create_collection(collection_name=name, vectors_config=vectors)
        for field, kind in spec["payload_indexes"].items():
            client.create_payload_index(name, field, getattr(models.PayloadSchemaType, kind.upper()))
    return name


def chunk_payload(r: dict) -> dict:
    """入力: チャンク1件（07_chunks.jsonl の1行） / 出力: Qdrant の payload（約束の形）"""
    return {
        "chunk_id": r["chunk_id"],
        "document_id": r["document_id"],
        "text": r["text"],
        "headings": r["headings"],
        # 見出しの経路を先頭から順につないだもの（配下のチャンクを完全一致で絞り込む）
        "heading_paths": [HEADING_SEP.join(r["headings"][: i + 1]) for i in range(len(r["headings"]))],
        "embedding_text": r["embedding_text"],
        "source_refs": r["source_refs"],
        "page_numbers": r["page_numbers"],
        "token_count": r["token_count"],
        "parent_id": r.get("parent_id"),
    }


def upsert_chunks(client: QdrantClient, name: str, records: list[dict], vectors) -> int:
    """入力: クライアント・コレクション名・チャンク・ベクトル / 出力: 登録後の件数"""
    points = [
        models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{r['document_id']}:{r['chunk_id']}")),
            vector=v.tolist(), payload=chunk_payload(r),
        )
        for r, v in zip(records, vectors)
    ]
    for i in range(0, len(points), BATCH):
        client.upsert(name, points=points[i:i + BATCH], wait=True)
    return client.count(name, exact=True).count


def doc_item_payloads(doc: dict, document_id: str) -> list[dict]:
    """入力: 文書・文書ID / 出力: 全要素（#/body を含む）の payload（約束の形）"""
    items = [doc["body"]]
    for arr in docling_io.ARRAYS:
        items += doc.get(arr) or []
    return [{
        "document_id": document_id,
        "self_ref": it["self_ref"],
        "label": it.get("label"),
        "text": docling_io.text_of(it),
        "level": it.get("level"),
        "parent_ref": (it.get("parent") or {}).get("$ref"),
        "children_refs": [c["$ref"] for c in it.get("children", [])],
    } for it in items]


def upsert_doc_items(client: QdrantClient, name: str, doc: dict, document_id: str) -> int:
    """入力: クライアント・コレクション名・文書・文書ID / 出力: 登録後の件数"""
    points = [
        models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{p['document_id']}:{p['self_ref']}")), vector={}, payload=p)
        for p in doc_item_payloads(doc, document_id)
    ]
    for i in range(0, len(points), BATCH):
        client.upsert(name, points=points[i:i + BATCH], wait=True)
    return client.count(name, exact=True).count
