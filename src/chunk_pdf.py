"""PDFをDoclingで変換し、ruri v3 のトークナイザー基準でチャンク化してJSONに出力する。

実行（コンテナ内 /app で）:
    python src/chunk_pdf.py
入力: data/input/*.pdf
出力: data/output/<PDF名>_chunks.json
"""

import json
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

# ==========================================
# 設定
# ==========================================
EMBED_MODEL_ID = "cl-nagoya/ruri-v3-310m"  # ruri v3（30m〜310m はトークナイザー共通）
MAX_TOKENS = 512  # 1チャンクの最大トークン数（まずは512で試す）

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"


def build_chunker() -> HybridChunker:
    """ruri のトークナイザーでトークン数を数える HybridChunker を作る。"""
    tokenizer = HuggingFaceTokenizer.from_pretrained(
        model_name=EMBED_MODEL_ID,
        max_tokens=MAX_TOKENS,
    )
    return HybridChunker(tokenizer=tokenizer, merge_peers=True)


def chunk_to_dict(chunk_id: int, chunk, chunker: HybridChunker) -> dict:
    """目視確認しやすい形に1チャンクを整形する。"""
    contextualized = chunker.contextualize(chunk=chunk)
    page_numbers = sorted(
        {prov.page_no for item in chunk.meta.doc_items for prov in item.prov}
    )
    return {
        "chunk_id": chunk_id,
        "headings": chunk.meta.headings or [],
        "page_numbers": page_numbers,
        "token_count": chunker.tokenizer.count_tokens(contextualized),
        "text": chunk.text,
        "contextualized_text": contextualized,
    }


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdf_paths:
        print(f"PDFがありません: {INPUT_DIR}")
        return

    converter = DocumentConverter()
    chunker = build_chunker()

    for pdf_path in pdf_paths:
        print(f"変換中: {pdf_path.name}")
        doc = converter.convert(pdf_path).document

        chunks = [
            chunk_to_dict(i, chunk, chunker)
            for i, chunk in enumerate(chunker.chunk(dl_doc=doc))
        ]

        output = {
            "source": pdf_path.name,
            "embed_model": EMBED_MODEL_ID,
            "max_tokens": MAX_TOKENS,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
        out_path = OUTPUT_DIR / f"{pdf_path.stem}_chunks.json"
        out_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"出力: {out_path}（{len(chunks)}チャンク）")


if __name__ == "__main__":
    main()
