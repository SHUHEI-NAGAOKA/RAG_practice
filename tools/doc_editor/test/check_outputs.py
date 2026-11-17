"""core_tests.js / ui_tests.js が書き出した JSON を Python(docling) 側で検証する。

1. DoclingDocument.load_from_json() が通る（スキーマ・ツリー検証）
2. HybridChunker（パイプラインの ingest/steps/s07_chunk.py と同じ設定）でエラーなくチャンク化できる
3. 編集した文字列（expect）がチャンクに含まれる

実行: .venv/bin/python tools/doc_editor/test/check_outputs.py [manifest.json ...]
"""

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from docling_core.types.doc import DoclingDocument  # noqa: E402
from ingest.steps.s07_chunk import build_chunker, to_records  # noqa: E402


def main() -> int:
    manifests = sys.argv[1:] or [str(ROOT / "data/edited/tests/manifest.json")]
    entries = []
    for m in manifests:
        entries += json.loads(Path(m).read_text(encoding="utf-8"))

    hf_tokenizer, chunker = build_chunker()
    failed = 0
    for e in entries:
        name = e["name"]
        try:
            doc = DoclingDocument.load_from_json(e["file"])
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                doc._validate_rules(raise_on_error=False)
            records = to_records(doc, chunker, hf_tokenizer)
            assert records, "チャンクが0件"
            joined = "\n".join(r["embedding_text"] for r in records)
            for s in e.get("expect", []):
                assert s in joined, f"チャンクに「{s}」がありません"
            # 削除した文字列（absent）がチャンクに残っていない
            for s in e.get("absent", []):
                assert s not in joined, f"削除したはずの「{s}」がチャンクに残っています"
            # docling 上の要素の確認（ラベル・本文・親）
            for x in e.get("expectDoc", []):
                item = next(i for i in doc.texts if i.self_ref == x["ref"])
                assert item.label.value == x["label"], f"{x['ref']} のラベルが {item.label.value}"
                assert item.text == x["text"], f"{x['ref']} の本文が {item.text!r}"
                assert item.parent.cref == x["parent"], f"{x['ref']} の親が {item.parent.cref}"
            print(f"PASS\t{name}\tチャンク{len(records)}件 / ルール警告{len(w)}件")
        except Exception as ex:
            failed += 1
            print(f"FAIL\t{name}\t{ex!r}")

    print(f"\n{len(entries) - failed}/{len(entries)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
