"""編集した DoclingDocument(JSON) を検証し、必要ならチャンク化まで通す。

実行:
    .venv/bin/python src/validate_doc.py <編集後.json> [--chunk]

検証内容:
    1. DoclingDocument.load_from_json() が通るか（スキーマ・親子ツリーの検証）
    2. docling-core のルール検査（_validate_rules）の警告数
    3. --chunk 指定時: chunk_doc.py と同じ設定で HybridChunker にかけ、
       data/chunks_edited/<ファイル名>/chunks.jsonl・.csv に出力
終了コード: 0 = 成功 / 1 = 失敗
"""

import sys
import warnings
from pathlib import Path

from docling_core.types.doc import DoclingDocument

BASE_DIR = Path(__file__).resolve().parent.parent
CHUNK_OUT_DIR = BASE_DIR / "data" / "chunks_edited"


def rule_warnings(doc: DoclingDocument) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc._validate_rules(raise_on_error=False)
    return [str(w.message) for w in caught]


def run_chunk(doc: DoclingDocument, name: str) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from chunk_doc import build_chunker, to_records, write_jsonl, write_csv

    hf_tokenizer, chunker = build_chunker()
    records = to_records(doc, chunker, hf_tokenizer)

    out_dir = CHUNK_OUT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(records, out_dir / "chunks.jsonl")
    write_csv(records, out_dir / "chunks.csv")
    print(f"チャンク数: {len(records)} → {out_dir}")
    return len(records)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    path = Path(args[0])

    try:
        doc = DoclingDocument.load_from_json(path)
    except Exception as e:
        print(f"NG 読み込み失敗: {e}")
        return 1
    print(f"OK 読み込み: {path.name}（texts {len(doc.texts)} / groups {len(doc.groups)}）")

    ws = rule_warnings(doc)
    print(f"ルール警告: {len(ws)}件")
    for w in ws[:10]:
        print("  -", w)

    if "--chunk" in sys.argv:
        try:
            n = run_chunk(doc, path.stem)
        except Exception as e:
            print(f"NG チャンク化失敗: {e!r}")
            return 1
        if n == 0:
            print("NG チャンクが0件です")
            return 1
        print("OK チャンク化")
    return 0


if __name__ == "__main__":
    sys.exit(main())
