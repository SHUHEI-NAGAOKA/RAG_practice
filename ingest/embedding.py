"""チャンクの本文をベクトルにする（Ruri v3、文書側の接頭辞「検索文書: 」）。

モデル名・接頭辞・次元は ingest/qdrant_schema.json（RAG 実行側との約束）から読む。
"""

import json

from .config import SCHEMA_FILE


def schema() -> dict:
    """入力: なし / 出力: Qdrant の約束（ingest/qdrant_schema.json）"""
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


class DocumentEmbedder:
    """入力: なし（約束からモデルを選ぶ） / 使い方: encode(texts) で正規化したベクトルの配列"""

    def __init__(self, batch_size: int = 16):
        import torch
        from sentence_transformers import SentenceTransformer

        emb = schema()["embedding"]
        self.prefix = emb["document_prefix"]
        self.dimension = emb["dimension"]
        self.batch_size = batch_size
        device = "mps" if torch.backends.mps.is_available() else "cpu"  # Mac の GPU があれば使う
        self.model = SentenceTransformer(emb["model"], device=device)

    def encode(self, texts: list[str]):
        """入力: 本文（見出し＋本文）のリスト / 出力: ベクトルの配列（numpy、行ごとに1件）"""
        vectors = self.model.encode(
            [self.prefix + t for t in texts],
            batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=True,
        )
        if vectors.shape[1] != self.dimension:
            raise ValueError(f"ベクトルの次元 {vectors.shape[1]} が約束（{self.dimension}）と違います")
        return vectors
