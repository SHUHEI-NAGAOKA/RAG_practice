"""Qdrant に登録したチャンクを Ruri v3 で類似度検索する（LLMは使わない）。

実行（プロジェクトのルートで）:
    uv run python src/search.py              # 対話形式（exit で終了）
    uv run python src/search.py "質問文"     # 1回だけ検索して終了
"""

import sys

import torch
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient


# =====================================
# 1. 設定
# =====================================

MODEL_ID = "cl-nagoya/ruri-v3-310m"
COLLECTION_NAME = "rag_ruri_v3_310m"
QDRANT_URL = "http://localhost:6333"
TOP_K = 5

# Ruri v3 の推奨形式（登録時の文書側は「検索文書: 」）
QUERY_PREFIX = "検索クエリ: "


# =====================================
# 2. Ruri の読み込み
# =====================================

device = "mps" if torch.backends.mps.is_available() else "cpu"
model = SentenceTransformer(MODEL_ID, device=device)


# =====================================
# 3. Qdrant への接続
# =====================================

client = QdrantClient(url=QDRANT_URL)


# =====================================
# 4. 検索関数
# =====================================

def search(query: str, top_k: int = 5):
    # 質問をEmbedding
    query_vector = model.encode(
        QUERY_PREFIX + query,
        normalize_embeddings=True,
    ).tolist()

    # Qdrantで検索
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )
    return response.points


def print_results(results):
    for i, point in enumerate(results, start=1):
        payload = point.payload or {}
        print(f"\n{'=' * 50}")
        print(f"順位: {i}")
        print(f"類似度スコア: {point.score:.4f}")
        print(f"文書: {payload.get('document_id')}")
        print(f"見出し: {payload.get('headings')}")
        print(f"ページ: {payload.get('page_numbers')}")
        print(f"本文:\n{payload.get('text')}")


# =====================================
# 5. 実行（引数あり: 1回検索 / 引数なし: 対話形式）
# =====================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print_results(search(" ".join(sys.argv[1:]), TOP_K))
        sys.exit(0)

    while True:
        try:
            query = input("\n質問を入力してください（exitで終了）: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if query.strip().lower() == "exit":
            break
        if not query.strip():
            continue

        print_results(search(query, TOP_K))
