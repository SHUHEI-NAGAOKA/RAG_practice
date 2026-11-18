# 取り込みパイプライン

入口 `ingest/run.py` は s01〜s08 を順に実行する。出力先は `data/pipeline/<文書名>/`（`ingest/config.py`）。以下の番号付きファイルはその配下。途中成果物があれば通常スキップし、`--force` で再生成する。s08 は外部 DB が出力なので毎回実行される。

| 工程・根拠 | 入力 → 主な出力・役割 |
| --- | --- |
| `ingest/steps/s01_convert_pdf.py` | PDF → `01_docling.json`、`01_artifacts/`、`01_pages/`。Docling 変換、画像抽出 |
| `ingest/steps/s02_outline_md.py` | PDF と変換結果 → `02_outline.md`。Claude CLI で見出し構造を作る |
| `ingest/steps/s03_structure.py` | 文書 JSON と見出し → `03_ops.json`、`03_structured.json`。構造・文字・分割文を修正 |
| `ingest/steps/s04_nest.py` | 前の JSON → `04_nested.json`。見出しレベルに従い入れ子化、タイトル等の設定も適用 |
| `ingest/steps/s05_figures.py` | 文書と画像 → `05_figures.jsonl`、`05_figures.json`。図の説明を追加 |
| `ingest/steps/s06_summaries.py` | 文書 → `06_summaries.jsonl`、`06_summary.json`。節の要約を追加 |
| `ingest/steps/s07_chunk.py` | 最終 JSON → `07_chunks.jsonl` と確認用 CSV。HybridChunker、Ruri トークナイザー、既定 512 tokens |
| `ingest/steps/s08_register.py` | チャンクと最終 JSON → 文書ベクトルと文書要素を Qdrant に登録 |

`ingest/steps/__init__.py` は s04/s06 の無効化時に直前の有効な文書を選ぶ。s02、s03、s05、s06 は `ingest/claude_cli.py` 経由の Claude CLI と `ingest/prompts/` を利用し、s03〜s06 の編集は `ingest/doc_tool.py` が `tools/doc_editor/cli.js` を呼ぶ。Python 以外に Node とログイン済み Claude Code が必要。埋め込みは MPS が使えれば MPS、それ以外は CPU（`ingest/embedding.py`）。

`--from`、`--to`、`--only` で範囲を選べ、`--no-nest`、`--no-summaries`、サンプル件数指定がある。`--index-only` は既存コレクションに不足索引を追加する。`--recreate` はコレクション全体を削除して作り直すため、他文書も消える。通常の同一 ID upsert は上書きだが、文書が短くなった際の古い余剰点の削除は `qdrant_writer.py` にない。実行例は `README.md`。
