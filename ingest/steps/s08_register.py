"""s08: チャンクを Embedding して Qdrant に登録し、文書要素も Qdrant に登録する。

入力: 07_chunks.jsonl・最終の文書 JSON・cfg.qdrant_url（本番へ直接登録するときは本番の URL）
出力: Qdrant の2つのコレクション（名前と形は ingest/qdrant_schema.json の約束どおり）
  chunks    : チャンク＋ベクトル（RAG 実行側が検索する）
  doc_items : 文書の全要素（RAG 実行側が親の節をたどる）
cfg.recreate なら、登録の前にコレクションを作り直す（古い文書のチャンクが残らない）。
"""

import json
from pathlib import Path

from .. import docling_io as dio
from .. import qdrant_writer as qw
from ..config import PipelineConfig
from ..embedding import DocumentEmbedder
from . import final_doc

NAME = "s08"
TITLE = "Embedding → Qdrant 登録"
USES_CLAUDE = False


def outputs(cfg: PipelineConfig) -> list[Path]:
    return []  # 出力はファイルではなく Qdrant なので、毎回実行する


def run(cfg: PipelineConfig) -> dict:
    records = [json.loads(l) for l in cfg.path("07_chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if not records:
        raise ValueError("チャンクがありません（s07 を先に実行してください）")
    vectors = DocumentEmbedder().encode([r["embedding_text"] for r in records])

    client = qw.connect(cfg.qdrant_url)
    chunks_name = qw.ensure_collection(client, "chunks", cfg.recreate)
    n_chunks = qw.upsert_chunks(client, chunks_name, records, vectors)

    doc_path = final_doc(cfg)
    doc = dio.load(doc_path)
    document_id = records[0]["document_id"]  # チャンクと同じ文書ID（DoclingDocument の name）
    items_name = qw.ensure_collection(client, "doc_items", cfg.recreate)
    n_items = qw.upsert_doc_items(client, items_name, doc, document_id)
    client.close()
    return {"qdrant": cfg.qdrant_url, chunks_name: n_chunks, items_name: n_items, "doc": doc_path.name}
