# 依存関係

| 範囲・根拠 | 主な依存と用途 |
| --- | --- |
| `pyproject.toml` | Python >=3.12。`docling` 文書変換・チャンク、`sentence-transformers`/`transformers` 埋め込み・トークナイザー、`qdrant-client` DB、`onnxruntime` 推論基盤、`ragas` 評価関連、`anthropic` と `python-dotenv` も宣言 |
| `runtime/rag_api/requirements.txt` | FastAPI、uvicorn、sentence-transformers、qdrant-client >=1.20、requests。API 専用で ingest の Docling を含まない |
| `runtime/rag_api/Dockerfile` | Python 3.12 slim、CPU 版 torch を別途インストール |
| `runtime/compose.yaml` | Qdrant v1.20.1、Ollama latest、API の独立イメージ |
| `tools/doc_editor/package.json` | Node CommonJS、開発依存 jsdom（画面テスト）。CLI を ingest から使用 |
| ルート `Dockerfile` | Python 3.12 slim と uv を用意し `sleep infinity`。現行 runtime の Compose からはビルドされない |

`ingest/steps/s01_convert_pdf.py` と s02 は `pypdfium2`、s07 は `docling_core` も直接 import するが、これらはルートの直接依存一覧にはない。`evaluation/` は requests を直接 import するがルートの直接依存一覧にない。推移的依存に頼る可能性があり確認対象。`ragas` は宣言されるが現行 `evaluation/eval_ragas.py` は同様の式を独自実装し、ragas を import していない。Claude は `ingest/claude_cli.py` が CLI を subprocess で呼ぶ。

ルートには `uv.lock` と Node の lock があるが全文は調べていない。runtime の requirements と torch は多くがバージョン未固定、Ollama は latest であり再ビルド時の再現性に注意。実際のインストール済みバージョンやモデルの取得状態は確認していない。
