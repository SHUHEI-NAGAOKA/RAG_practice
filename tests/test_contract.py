"""パイプライン（ingest/）と RAG 実行環境（runtime/）の Qdrant の約束が一致しているかを確かめる。

コードの依存はさせず、2つの約束ファイルと、runtime の設定値を照合する。
runtime は約束ファイル（正本）を config.py で読むので、config.py が約束から読んでいること、
compose に約束の値を重ねて書いていないこと、イメージの版が固定されていることも確かめる。
入力: runtime/contract/qdrant_schema.json（正本）・ingest/qdrant_schema.json（写し）
      runtime の config.py・compose.yaml・Dockerfile・bundle/
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

    # runtime は約束ファイルから値を読む（config.py・compose に同じ値を重ねて書かない）
    config = (ROOT / "runtime/rag_api/app/config.py").read_text(encoding="utf-8")
    compose = (ROOT / "runtime/compose.yaml").read_text(encoding="utf-8")
    bundle_compose = (ROOT / "runtime/bundle/compose.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "runtime/rag_api/Dockerfile").read_text(encoding="utf-8")
    cols = master["collections"]
    reads = {
        "chunks_collection": 'CONTRACT["collections"]["chunks"]["name"]',
        "doc_items_collection": 'CONTRACT["collections"]["doc_items"]["name"]',
        "embedding_model": 'CONTRACT["embedding"]["model"]',
        "query_prefix": 'CONTRACT["embedding"]["query_prefix"]',
        "heading_sep": 'CONTRACT["heading_sep"]',
        "bm25_field": 'CONTRACT["search"]["bm25_field"]',
    }
    for name, expr in reads.items():
        if not re.search(rf"^\s*{name}: str = {re.escape(expr)}", config, re.M):
            found.append(f"runtime/rag_api/app/config.py の {name} が約束ファイルから読まれていません")
    for value in (cols["chunks"]["name"], cols["doc_items"]["name"], master["embedding"]["model"]):
        for label, text in (("runtime/compose.yaml", compose), ("runtime/bundle/compose.yaml", bundle_compose)):
            if value in text:
                found.append(f"{label} に約束の値 {value} が重ねて書かれています（約束ファイルだけに書く）")
    if "COPY contract/" not in dockerfile:
        found.append("runtime/rag_api/Dockerfile が contract/ をイメージに入れていません")

    # 検索方式（BM25 の全文索引）: runtime の方式名・compose の設定・Qdrant の版
    search = master["search"]
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

    # 再登録で古い点を消すため、chunks・doc_items の両方に document_id の索引がある
    for key in ("chunks", "doc_items"):
        if cols[key]["payload_indexes"].get("document_id") != "keyword":
            found.append(f"約束の {key} に document_id の keyword 索引がありません")

    # 版の固定: latest や版なしのイメージを使わない（開発用・持ち出し用の compose と Dockerfile）
    for label, text in (("runtime/compose.yaml", compose), ("runtime/bundle/Dockerfile.*", _bundle_dockerfiles()),
                        ("runtime/rag_api/Dockerfile", dockerfile)):
        for ref in re.findall(r"(?:image:|FROM)\s+(\S+)", text):
            if ref.startswith("${") or ref.startswith("rag-bundle/") or ref == "base":
                continue
            if ":" not in ref or ref.endswith(":latest"):
                found.append(f"{label} のイメージ {ref} の版が固定されていません")
    return found


def _bundle_dockerfiles() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "runtime/bundle").glob("Dockerfile.*")))


def test_contract():
    assert problems() == []


if __name__ == "__main__":
    ps = problems()
    for x in ps:
        print("FAIL", x)
    print("PASS ingest と runtime の Qdrant の約束は一致しています" if not ps else f"{len(ps)} 件の食い違い")
    sys.exit(1 if ps else 0)
