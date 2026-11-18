"""パイプライン（ingest/）と RAG 実行環境（runtime/）の Qdrant の約束が一致しているかを確かめる。

コードの依存はさせず、2つの約束ファイルと、runtime の設定値を照合する。
入力: runtime/contract/qdrant_schema.json（正本）・ingest/qdrant_schema.json（写し）・runtime の config.py と compose.yaml
出力: 食い違いの一覧（無ければ PASS）
実行: .venv/bin/python tests/test_contract.py（pytest でも可）
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "runtime/contract/qdrant_schema.json"
COPY = ROOT / "ingest/qdrant_schema.json"


def problems() -> list[str]:
    found = []
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    copy = json.loads(COPY.read_text(encoding="utf-8"))
    for k in ("version", "qdrant_min_version", "embedding", "heading_sep", "search", "collections"):
        if master.get(k) != copy.get(k):
            found.append(f"約束ファイルの {k} が runtime と ingest で違います")

    # runtime の既定値・compose の値が約束と同じか（文字列として照合する）
    config = (ROOT / "runtime/rag_api/app/config.py").read_text(encoding="utf-8")
    compose = (ROOT / "runtime/compose.yaml").read_text(encoding="utf-8")
    emb = master["embedding"]
    cols = master["collections"]
    expect = {
        "チャンクのコレクション名": cols["chunks"]["name"],
        "文書要素のコレクション名": cols["doc_items"]["name"],
        "Embedding モデル": emb["model"],
    }
    for label, value in expect.items():
        if value not in config:
            found.append(f"runtime/rag_api/app/config.py に{label} {value} がありません")
        if value not in compose:
            found.append(f"runtime/compose.yaml に{label} {value} がありません")
    if f'query_prefix: str = "{emb["query_prefix"]}"' not in config:
        found.append("runtime の query_prefix が約束と違います")
    if not re.search(re.escape(f'heading_sep: str = "{master["heading_sep"]}"'), config):
        found.append("runtime の heading_sep が約束と違います")

    # 検索方式（BM25 の全文索引）: runtime の項目名・方式名・compose の設定・Qdrant の版
    search = master["search"]
    if f'bm25_field: str = "{search["bm25_field"]}"' not in config:
        found.append("runtime の bm25_field が約束と違います")
    idx = cols["chunks"]["payload_indexes"].get(search["bm25_field"])
    if not (isinstance(idx, dict) and idx.get("type") == "text" and idx.get("scoring") == "bm25"):
        found.append(f"約束の chunks に {search['bm25_field']} の全文索引（BM25）がありません")
    chunks_py = (ROOT / "runtime/rag_api/app/qdrant_store/chunks.py").read_text(encoding="utf-8")
    m = re.search(r"MODES = \(([^)]*)\)", chunks_py)
    if not m or re.findall(r"[\"']([^\"']+)[\"']", m.group(1)) != search["modes"]:
        found.append("runtime の検索方式（MODES）が約束の search.modes と違います")
    if "SEARCH_MODE" not in compose:
        found.append("runtime/compose.yaml に SEARCH_MODE がありません")
    m = re.search(r"image: qdrant/qdrant:v?([\d.]+)", compose)
    want = tuple(int(x) for x in master["qdrant_min_version"].split("."))
    if not m or tuple(int(x) for x in m.group(1).split(".")) < want:
        found.append(f"runtime/compose.yaml の Qdrant の版を {master['qdrant_min_version']} 以上に固定してください")
    return found


def test_contract():
    assert problems() == []


if __name__ == "__main__":
    ps = problems()
    for x in ps:
        print("FAIL", x)
    print("PASS ingest と runtime の Qdrant の約束は一致しています" if not ps else f"{len(ps)} 件の食い違い")
    sys.exit(1 if ps else 0)
