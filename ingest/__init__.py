"""PDF → Qdrant 登録パイプライン（開発機で実行する。RAG 実行環境 runtime/ には依存しない）。

実行: .venv/bin/python -m ingest.run --pdf data/input/<文書>.pdf
工程（ingest/steps/）:
  s01 PDF → DoclingDocument          s02 PDF → 階層の md（Claude CLI）
  s03 階層・不要文字・合体（Claude CLI → ツール）  s04 入れ子化（ツール）
  s05 図の説明と数値一覧（Claude CLI → ツール）    s06 節の要約（Claude CLI → ツール）
  s07 チャンク化                      s08 Embedding → Qdrant
"""
