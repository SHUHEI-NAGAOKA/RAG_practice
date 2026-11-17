"""質問文をベクトルにする（Ruri v3）。

登録側（パイプライン）は文書に「検索文書: 」を付けてベクトル化している。
こちらは質問に「検索クエリ: 」を付ける（Ruri v3 の使い方。contract/qdrant_schema.json 参照）。
"""

from sentence_transformers import SentenceTransformer

from .config import settings


class QueryEmbedder:
    """起動時に1回だけモデルを読み込み、質問のベクトル化に使い回す。"""

    def __init__(self, model_name: str = settings.embedding_model, prefix: str = settings.query_prefix):
        self.model = SentenceTransformer(model_name, device="cpu")
        self.prefix = prefix

    def encode(self, question: str) -> list[float]:
        """入力: 質問文 / 出力: 正規化したベクトル（list[float]）"""
        return self.model.encode(self.prefix + question, normalize_embeddings=True).tolist()
