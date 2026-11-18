# RAG 実行環境

`runtime/rag_api/app/main.py` は起動時に質問用埋め込みモデルと Qdrant クライアントを用意し、FastAPI の routes と `static/` の画面を登録する。`routes/` は受け口、`services/` は処理、`qdrant_store/` は読み取り、`schemas.py` は入出力型。`llm.py` は Ollama の HTTP API を呼ぶ。

| API | 用途 |
| --- | --- |
| `GET /health` | 設定・稼働情報 |
| `POST /search`, `/ask` | チャンク検索、検索結果に基づく簡易回答 |
| `POST /levels`, `/subtopics`, `/answer` | 話題候補 → 下位話題 → 選択範囲から回答 |
| `/eval/questions`, `/eval/status`, `/eval/record` | 評価モードの質問と記録。条件付きでルートを登録 |

`services/search.py` と `qdrant_store/chunks.py` により、dense は正規化 Ruri クエリベクトル、bm25 は Qdrant の `embedding_text` 全文索引、hybrid は両者を prefetch して RRF で統合する。見出し範囲フィルタは hybrid の両候補に適用。`/search` はリクエスト単位で方式を指定可能。`services/answer.py` は選択範囲が 6 チャンク未満なら全件、以上なら上位 5 件と文書要素から復元した節本文を使う。コンテキストの長さは文字数で近似し、要約重複を抑制する。

設定の出所は `runtime/rag_api/app/config.py` と `runtime/compose.yaml`、設定例は `runtime/.env.example`。主な項目は `LLM_MODEL`（既定 qwen2.5:3b）、`NUM_CTX`、`SEARCH_MODE`、`HYBRID_PREFETCH`、`SUMMARY_DEDUP`、`EVAL_ENABLED`、`EVAL_HOST_DIR`、公開ポート。Compose は評価を既定 false にするが、Compose を通さない Python 設定の既定は true である。`depends_on` は起動順であり、準備完了のヘルスチェックではない。モデル取得手順と API の詳細は `runtime/README.md`。
