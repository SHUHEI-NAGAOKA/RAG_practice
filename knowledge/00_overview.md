# 全体像

行政文書の PDF を検索可能な形に加工し、質問に資料を付けて回答する RAG の学習・実験プロジェクト。静的なコード調査に基づく。実行やテストはしていない。

| パス | 役割 |
| --- | --- |
| `ingest/` | ホストで PDF を変換・加工・チャンク化し Qdrant に登録 |
| `tools/doc_editor/` | Docling 文書編集の GUI・CLI。ingest から Node CLI を呼ぶ |
| `runtime/` | Qdrant、Ollama、FastAPI と画面。RAG の実行環境 |
| `evaluation/` | ホスト側の採点・検索方式比較 |
| `tests/` | 契約・分離・画面のテスト |
| `data/` | 入力、工程成果物、評価データ。大きな内容は未調査 |
| `legacy/` | 旧実装の参照用。現行の入口ではない（`legacy/README.md`） |
| `docs/` | 設計・作業記録。ルート `Dockerfile` は待機用の汎用イメージ |

推奨順序は [アーキテクチャ](01_architecture.md) → [取り込み](02_ingest_pipeline.md) → [実行環境](03_runtime_rag.md) → [依存](04_packages.md) → [テストと評価](05_tests_and_eval.md) → [レビュー候補](06_review_notes.md)。入口は `ingest/run.py`、`runtime/compose.yaml`、`runtime/rag_api/app/main.py`。
