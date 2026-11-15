"""入れ子にした DoclingDocument JSON の要素を Qdrant に登録する（ベクトルなし・payload のみ）。

rag_api がチャンクの source_refs から親をたどり、1段上の節の本文を取るための参照先。

実行（プロジェクトのルートで）:
    .venv/bin/python src/register_doc_items.py <JSON> [--recreate]
登録先: http://localhost:6333 のコレクション rag_doc_items
"""

import json
import sys
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "rag_doc_items"
ARRAYS = ["texts", "tables", "groups", "pictures", "key_value_items", "form_items"]
BATCH_SIZE = 256


def table_text(item: dict) -> str:
    """表をセルを | でつないだ行の文字列にする（結合セルの繰り返しは1つに）。"""
    rows = []
    for row in item.get("data", {}).get("grid", []):
        cells = []
        for c in row:
            t = (c.get("text") or "").strip()
            if not cells or cells[-1] != t:
                cells.append(t)
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def to_payloads(doc: dict, document_id: str) -> list[dict]:
    items = [doc["body"]]
    for arr in ARRAYS:
        items += doc.get(arr) or []
    payloads = []
    for it in items:
        ref = it["self_ref"]
        text = table_text(it) if ref.startswith("#/tables/") else it.get("text", "")
        payloads.append({
            "document_id": document_id,
            "self_ref": ref,
            "label": it.get("label"),
            "text": text,
            "level": it.get("level"),
            "parent_ref": (it.get("parent") or {}).get("$ref"),
            "children_refs": [c["$ref"] for c in it.get("children", [])],
        })
    return payloads


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("使い方: register_doc_items.py <JSON> [--recreate]")
    path = Path(args[0])
    doc = json.loads(path.read_text(encoding="utf-8"))
    # チャンクの document_id と同じ（DoclingDocument の name）
    document_id = doc.get("name") or path.stem
    payloads = to_payloads(doc, document_id)
    print("文書:", document_id, "/ 要素数:", len(payloads))

    client = QdrantClient(url=QDRANT_URL)
    if "--recreate" in sys.argv[1:] and client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
        print("既存のコレクションを削除しました")
    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(collection_name=COLLECTION_NAME, vectors_config={})  # ベクトルなし
        for field in ("self_ref", "document_id"):
            client.create_payload_index(COLLECTION_NAME, field, models.PayloadSchemaType.KEYWORD)
        print("コレクションを作成しました")

    points = [
        models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{p['document_id']}:{p['self_ref']}")),
            vector={},
            payload=p,
        )
        for p in payloads
    ]
    for start in range(0, len(points), BATCH_SIZE):
        client.upsert(COLLECTION_NAME, points=points[start:start + BATCH_SIZE], wait=True)
    print("Qdrant内のポイント数:", client.count(COLLECTION_NAME, exact=True).count)


if __name__ == "__main__":
    main()
