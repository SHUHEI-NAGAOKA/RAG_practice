# パイプラインの進捗: 那須烏山市総合計画

- 更新: 2026-11-17 23:47:14
- 入力: data/input/那須烏山市総合計画.pdf

| 工程 | 状態 | 開始 | 終了 | 秒 | 結果 |
|---|---|---|---|---|---|
| s08 Embedding → Qdrant 登録 | 完了 | 23:47:14 | 23:47:14 | 0.3 | {"qdrant": "http://localhost:6333", "index_only": true, "created": {"rag_ruri_v3_310m": ["embedding_text"], "rag_doc_items": []}} |

## 再開のしかた
止まった工程から、次のコマンドで続ける（済んだ工程は出力があるので飛ばされる。
Claude CLI の返答も 02_outline_parts/・03_ops_parts/・05_figures.jsonl・06_summaries.jsonl に
少しずつ保存してあり、済んだ分は呼び直さない）。**--force は付けない**（付けると保存した返答を捨てて作り直す）。

```bash
.venv/bin/python -m ingest.run --pdf 'data/input/那須烏山市総合計画.pdf' --only s08 --index-only
```
