"""変換済みのDoclingDocument(JSON)を ruri v3 のトークナイザー基準でチャンク化する。

実行:
    .venv/bin/python src/chunk_doc.py
入力: data/output/<文書名>/<文書名>.json
出力: data/chunks/<文書名>/
    chunks.jsonl  1行1チャンク
    chunks.csv    目視確認用（UTF-8 BOM付き）
"""

import csv
import json
from pathlib import Path

from transformers import AutoTokenizer
from docling_core.types.doc import DoclingDocument
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import (
    HuggingFaceTokenizer,
)


# =====================================
# 1. 設定
# =====================================

MODEL_ID = "cl-nagoya/ruri-v3-310m"
MAX_TOKENS = 512

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "output"
OUTPUT_DIR = BASE_DIR / "data" / "chunks"


# =====================================
# 2. Ruri Tokenizer / HybridChunker の設定
# =====================================

def build_chunker():
    hf_tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

    tokenizer = HuggingFaceTokenizer(
        tokenizer=hf_tokenizer,
        max_tokens=MAX_TOKENS,
    )

    chunker = HybridChunker(
        tokenizer=tokenizer,
        merge_peers=True,
    )
    return hf_tokenizer, chunker


# =====================================
# 3. チャンクを独自のJSON形式に変換
# =====================================

def to_records(doc, chunker, hf_tokenizer):
    records = []

    for i, chunk in enumerate(chunker.chunk(doc)):

        # 本文と文脈付きテキスト
        text = chunk.text
        embedding_text = chunker.contextualize(chunk)

        # 見出し情報
        headings = chunk.meta.headings or []

        # 元のDoclingDocument要素
        doc_items = chunk.meta.doc_items or []

        # 元要素の参照ID
        source_refs = [item.self_ref for item in doc_items]

        # ページ番号
        page_numbers = sorted({
            prov.page_no
            for item in doc_items
            for prov in (item.prov or [])
        })

        # 実際のEmbedding用文字列のトークン数
        token_count = len(
            hf_tokenizer.encode(embedding_text, add_special_tokens=True)
        )

        records.append({
            "chunk_id": f"chunk_{i:04d}",
            "document_id": doc.name,
            "text": text,
            "headings": headings,
            "source_refs": source_refs,
            "page_numbers": page_numbers,
            "embedding_text": embedding_text,
            "token_count": token_count,
        })

    return records


# =====================================
# 4. JSONL / CSV 出力
# =====================================

def write_jsonl(records, path):
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(records, path):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "chunk_id",
            "headings",
            "page_numbers",
            "token_count",
            "text",
            "embedding_text",
            "source_refs",
        ])
        for record in records:
            writer.writerow([
                record["chunk_id"],
                " > ".join(record["headings"]),
                record["page_numbers"],
                record["token_count"],
                record["text"],
                record["embedding_text"],
                record["source_refs"],
            ])


# =====================================
# 5. 結果確認（サマリーのみ表示）
# =====================================

def print_summary(records, jsonl_path, csv_path):
    counts = [r["token_count"] for r in records]
    over_limit = [r["chunk_id"] for r in records if r["token_count"] > MAX_TOKENS]

    print("チャンク数:", len(records))
    if counts:
        print("トークン数 最大:", max(counts))
        print("トークン数 平均:", round(sum(counts) / len(counts), 1))
    print("上限超過チャンク:", len(over_limit), over_limit)
    print("JSONL:", jsonl_path)
    print("CSV:", csv_path)


def main():
    json_paths = sorted(INPUT_DIR.glob("*/*.json"))
    if not json_paths:
        print(f"JSONがありません: {INPUT_DIR}")
        return

    hf_tokenizer, chunker = build_chunker()

    for json_path in json_paths:
        doc = DoclingDocument.load_from_json(json_path)
        print("\n==============================")
        print("文書名:", doc.name)

        records = to_records(doc, chunker, hf_tokenizer)

        out_dir = OUTPUT_DIR / json_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = out_dir / "chunks.jsonl"
        csv_path = out_dir / "chunks.csv"

        write_jsonl(records, jsonl_path)
        write_csv(records, csv_path)
        print_summary(records, jsonl_path, csv_path)

    print("\n完了")


if __name__ == "__main__":
    main()
