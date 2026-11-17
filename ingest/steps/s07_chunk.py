"""s07: 完成した文書 JSON をチャンクに分ける（Docling の HybridChunker、Ruri のトークナイザー）。

入力: 最終の文書 JSON（s06 の 06_summary.json。s06 がオフならその前の工程の出力）
出力: 07_chunks.jsonl（1行1チャンク）・07_chunks.csv（確認用）
チャンクの項目: chunk_id, document_id, text, headings, source_refs, page_numbers, embedding_text, token_count
  embedding_text = 見出し＋本文（ベクトル化する文字列）。上限は cfg.max_tokens（512）トークン
"""

import csv
import json
import warnings
from pathlib import Path

from ..config import PipelineConfig
from . import final_doc

NAME = "s07"
TITLE = "文書 JSON → チャンク"
USES_CLAUDE = False


def outputs(cfg: PipelineConfig) -> list[Path]:
    return [cfg.path("07_chunks.jsonl")]


def build_chunker(model_id: str = "cl-nagoya/ruri-v3-310m", max_tokens: int = 512):
    """入力: トークナイザーのモデル・上限トークン数 / 出力: (HF のトークナイザー, HybridChunker)"""
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from transformers import AutoTokenizer

    hf = AutoTokenizer.from_pretrained(model_id)
    chunker = HybridChunker(tokenizer=HuggingFaceTokenizer(tokenizer=hf, max_tokens=max_tokens), merge_peers=True)
    return hf, chunker


def to_records(doc, chunker, hf) -> list[dict]:
    """入力: DoclingDocument・チャンカー・トークナイザー / 出力: チャンクの dict のリスト（文書順）"""
    records = []
    for i, chunk in enumerate(chunker.chunk(doc)):
        embedding_text = chunker.contextualize(chunk)
        items = chunk.meta.doc_items or []
        records.append({
            "chunk_id": f"chunk_{i:04d}",
            "document_id": doc.name,
            "text": chunk.text,
            "headings": chunk.meta.headings or [],
            "source_refs": [it.self_ref for it in items],
            "page_numbers": sorted({p.page_no for it in items for p in (it.prov or [])}),
            "embedding_text": embedding_text,
            "token_count": len(hf.encode(embedding_text, add_special_tokens=True)),
        })
    return records


def rule_warnings(doc) -> list[str]:
    """入力: DoclingDocument / 出力: docling のルール違反の警告（空グループなど。エラーではない）"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc._validate_rules(raise_on_error=False)
    return [str(w.message) for w in caught]


def write_outputs(records: list[dict], jsonl: Path, csv_path: Path) -> None:
    """入力: チャンク・出力先 / 出力: なし（JSONL と CSV を書く）"""
    with jsonl.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chunk_id", "token_count", "page_numbers", "headings", "text"])
        for r in records:
            w.writerow([r["chunk_id"], r["token_count"], " ".join(map(str, r["page_numbers"])),
                        " > ".join(r["headings"]), r["text"]])


def chunk_file(src: Path, model_id: str, max_tokens: int) -> tuple[list[dict], list[str]]:
    """入力: 文書 JSON・トークナイザー・上限 / 出力: (チャンク, ルールの警告)"""
    from docling_core.types.doc import DoclingDocument

    doc = DoclingDocument.load_from_json(src)
    hf, chunker = build_chunker(model_id, max_tokens)
    return to_records(doc, chunker, hf), rule_warnings(doc)


def run(cfg: PipelineConfig) -> dict:
    src = final_doc(cfg)
    records, warns = chunk_file(src, cfg.tokenizer_model, cfg.max_tokens)
    write_outputs(records, cfg.path("07_chunks.jsonl"), cfg.path("07_chunks.csv"))
    return {
        "input": src.name, "chunks": len(records), "max_tokens": max(r["token_count"] for r in records),
        "rule_warnings": len(warns),
    }
