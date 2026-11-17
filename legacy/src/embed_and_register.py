"""chunks.jsonl を Ruri v3 で Embedding し、Docker内の Qdrant に登録する。

実行（プロジェクトのルートで）:
    uv run python src/embed_and_register.py [チャンクのフォルダ] [--recreate]
入力: data/chunks/<文書名>/chunks.jsonl（フォルダ指定時はその下の chunks.jsonl）
--recreate: 既存のコレクションを削除してから作り直す
登録先: http://localhost:6333 のコレクション rag_ruri_v3_310m
"""

import json
import sys
import uuid
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models


# ==========================================
# 1. 設定
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent
CHUNKS_DIR = BASE_DIR / "data" / "chunks"

MODEL_ID = "cl-nagoya/ruri-v3-310m"
COLLECTION_NAME = "rag_ruri_v3_310m"
QDRANT_URL = "http://localhost:6333"
BATCH_SIZE = 16

# Ruri v3 のモデルカードの推奨形式: 検索対象の文書は「検索文書: 」、質問は「検索クエリ: 」
DOCUMENT_PREFIX = "検索文書: "


# ==========================================
# 2. チャンクの読み込み
# ==========================================

def load_records(chunks_dir):
    records = []
    paths = sorted(chunks_dir.glob("chunks.jsonl")) or sorted(chunks_dir.glob("*/chunks.jsonl"))
    for path in paths:
        with path.open(encoding="utf-8") as f:
            records.extend(json.loads(line) for line in f if line.strip())
    return records


# ==========================================
# 3. ポイントIDの生成
# ==========================================

def make_point_id(record):
    """document_id と chunk_id から毎回同じUUIDを作る（再実行時は上書き更新になる）。"""
    key = f"{record['document_id']}:{record['chunk_id']}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    recreate = "--recreate" in sys.argv[1:]
    chunks_dir = Path(args[0]).resolve() if args else CHUNKS_DIR

    records = load_records(chunks_dir)
    print("入力:", chunks_dir)
    print("チャンク数:", len(records))
    if not records:
        print(f"chunks.jsonl がありません: {chunks_dir}")
        return

    # ==========================================
    # 4. Ruri の読み込み（Mac の MPS を使う）
    # ==========================================
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print("デバイス:", device)

    model = SentenceTransformer(MODEL_ID, device=device)
    print("入力上限:", model.max_seq_length)

    # ==========================================
    # 5. Embedding
    # ==========================================
    texts = [DOCUMENT_PREFIX + r["embedding_text"] for r in records]

    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    print("Embedding形状:", vectors.shape)

    vector_size = vectors.shape[1]
    print("ベクトル次元数:", vector_size)

    # ==========================================
    # 6. コレクションの作成（なければ）。--recreate なら削除してから作り直す
    # ==========================================
    client = QdrantClient(url=QDRANT_URL)

    if recreate and client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
        print("既存のコレクションを削除しました")

    if client.collection_exists(COLLECTION_NAME):
        print("既存のコレクションを使用します")
    else:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        client.create_payload_index(
            COLLECTION_NAME, "heading_paths", models.PayloadSchemaType.KEYWORD
        )
        print("コレクションを作成しました")

    # ==========================================
    # 7. ポイントの生成
    # ==========================================
    points = []
    for record, vector in zip(records, vectors):
        payload = {
            "chunk_id": record["chunk_id"],
            "document_id": record["document_id"],
            "text": record["text"],
            "headings": record["headings"],
            # 見出しの経路を先頭から順につないだもの（配下のチャンクを完全一致で絞り込む）
            "heading_paths": [
                " > ".join(record["headings"][: i + 1]) for i in range(len(record["headings"]))
            ],
            "embedding_text": record["embedding_text"],
            "source_refs": record["source_refs"],
            "page_numbers": record["page_numbers"],
            "token_count": record["token_count"],
            "parent_id": record.get("parent_id"),
        }
        points.append(
            models.PointStruct(
                id=make_point_id(record),
                vector=vector.tolist(),
                payload=payload,
            )
        )

    # ==========================================
    # 8. Qdrant への登録
    # ==========================================
    for start in range(0, len(points), BATCH_SIZE):
        batch = points[start:start + BATCH_SIZE]
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=batch,
            wait=True,
        )
        print(f"登録済み: {start + len(batch)}/{len(points)}")

    count = client.count(collection_name=COLLECTION_NAME, exact=True).count
    print("Qdrant内のポイント数:", count)
    print("登録処理が完了しました")


if __name__ == "__main__":
    main()
