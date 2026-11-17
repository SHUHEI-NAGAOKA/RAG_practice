# RAG_practice

行政文書（PDF）を Qdrant に登録し、ローカル LLM で質問に答える RAG の学習・実験用プロジェクト。

大きく2つに分かれていて、**お互いのコードに依存しない**。

| 部分 | 役割 | 動かす場所 |
|---|---|---|
| `ingest/` | PDF → Qdrant 登録までのパイプライン | 開発機（ホストの `.venv` と node） |
| `runtime/` | 登録済みのデータで質問に答える RAG 実行環境 | Docker（**本番ではこのフォルダだけを切り出す**） |

両者の約束（Qdrant のコレクション名・payload の形・Embedding）は
`runtime/contract/qdrant_schema.json`（正本）と `ingest/qdrant_schema.json`（写し）に書き、
`tests/test_contract.py` で食い違いを確かめる。

```
ingest/（書き込み） ──▶ Qdrant ◀── runtime/（読み取り）
```

## フォルダ構成
```
RAG_practice/
├─ ingest/                 # パイプライン（工程ごとに1ファイル）
│  ├─ run.py               # 入口（工程を順に実行）
│  ├─ config.py            # 入出力のパスと設定
│  ├─ claude_cli.py        # `claude -p`（Claude Code の CLI）を呼ぶ。API は使わない
│  ├─ doc_tool.py          # 文書の編集ツール（tools/doc_editor/cli.js）に操作リストを渡す
│  ├─ docling_io.py        # 文書 JSON をたどる補助
│  ├─ embedding.py         # 文書側のベクトル化（Ruri v3）
│  ├─ qdrant_writer.py     # Qdrant への登録
│  ├─ qdrant_schema.json   # Qdrant の約束（写し）
│  ├─ prompts/             # Claude CLI への指示文
│  └─ steps/s01〜s08       # 各工程
├─ runtime/                # RAG 実行環境（詳しくは runtime/README.md）
├─ tools/doc_editor/       # 文書（DoclingDocument JSON）の編集ツール（GUI と CLI）
├─ evaluation/eval_ragas.py  # RAGAS の採点（API を使わず、Claude Code が会話の中で判定）
├─ tests/                  # 約束・分離・画面のテスト
├─ docs/                   # 作業記録・作業手順書
├─ legacy/                 # 旧ファイル（参照用）
└─ data/
   ├─ input/               # 入力 PDF
   ├─ pipeline/<文書名>/   # パイプラインの各工程の出力
   └─ eval/                # 評価の質問集と記録
```

## パイプライン（PDF → Qdrant）
| 工程 | 内容 | 入力 → 出力（data/pipeline/<文書名>/） | Claude CLI |
|---|---|---|---|
| s01 | PDF を Docling で読み取る | PDF → `01_docling.json`・`01_artifacts/`（図）・`01_pages/` | - |
| s02 | 見出しの階層の md を作る | PDF → `02_outline.md` | ○ |
| s03 | md を参考に階層・不要な文字（・・・）・分かれた文を整える | 01 ＋ 02 → `03_ops.json` → `03_structured.json` | ○ → ツール |
| s04 | 見出しの下に本文をぶら下げる（入れ子） | 03 → `04_nested.json` | - → ツール |
| s05 | すべての図の意味・文脈・数値一覧を図の直後に追加 | 04 ＋ 図 → `05_figures.jsonl` → `05_figures.json` | ○ → ツール |
| s06 | 節の要約を本文の先頭に付ける | 05 → `06_summaries.jsonl` → `06_summary.json` | ○ → ツール |
| s07 | チャンク化（HybridChunker・512トークン） | 06 → `07_chunks.jsonl` | - |
| s08 | Embedding して Qdrant に登録 | 07 ＋ 06 → Qdrant（2コレクション） | - |

- 「ツール」は `tools/doc_editor/cli.js`。GUI と同じ処理で操作を適用し、検証してから書き出す。
- Claude CLI の返答（02・03・05・06）は保存し、再実行のときは使い回す（作り直すなら `--force`）。
- Claude CLI は API キーを使わず、ログイン済みの Claude Code で動く（`ANTHROPIC_API_KEY` は外して呼ぶ）。

### 実行
```bash
# 前提: uv sync（.venv）、cd tools/doc_editor && npm install、runtime の Qdrant が起動していること
.venv/bin/python -m ingest.run --pdf data/input/那須烏山市総合計画.pdf            # 全工程
.venv/bin/python -m ingest.run --pdf data/input/那須烏山市総合計画.pdf --from s07  # s07 から
.venv/bin/python -m ingest.run --pdf data/input/那須烏山市総合計画.pdf --only s08 --recreate
# 少量で試す（Claude CLI の利用を抑える）
.venv/bin/python -m ingest.run --pdf data/input/那須烏山市総合計画.pdf --name sample_check \
  --from s02 --to s07 --sample-pages 6 --sample-items 60 --sample-figures 3 --sample-sections 5
# 本番の Qdrant へ直接登録
.venv/bin/python -m ingest.run --pdf data/input/那須烏山市総合計画.pdf --only s08 --qdrant-url http://<本番>:6333
```
主なオプション: `--no-nest`・`--no-summaries`（任意の工程を使わない）、`--claude-model sonnet`（Claude CLI のモデル）、
`--doc-title "那須烏山市 第2次総合計画"`・`--doc-note "…"`（s04 で文書タイトルを書き換え、直後に説明文を足す。複数の文書を区別する）

- 複数の文書を登録するときは、2つ目以降の s08 に **`--recreate` を付けない**（付けると既に登録した文書が消える）
- 進捗は `data/pipeline/<文書名>/PROGRESS.md` に工程ごとに書かれる。止まったらそこにある再開コマンドで続ける（`--force` は付けない）
- 登録済みの文書: 那須烏山市総合計画（第3次）・那須烏山市第二次総合計画（3ファイルを結合した230ページ）

## RAG 実行環境
```bash
cd runtime
cp .env.example .env      # LLM_MODEL=qwen2.5:3b / qwen2.5:7b で切り替え
docker compose up -d --build
./ollama/pull_models.sh   # 初回のみ
```
画面: http://localhost:8000 ・ 詳しくは `runtime/README.md`。
**`docker compose down -v` は使わない**（Qdrant とモデルのデータが消える）。

## 評価（RAGAS）
1. `runtime/.env` で `EVAL_ENABLED=true`・`EVAL_HOST_DIR=../data/eval` にして、画面を `?eval=1` で開き、質問ごとに話題を選んで記録する
2. `.venv/bin/python evaluation/eval_ragas.py sheet data/eval/results/<記録名>` で判定用の資料を作る
3. Claude Code（会話の中）が判定して `judgments.jsonl` を書く
4. `.venv/bin/python evaluation/eval_ragas.py score data/eval/results/<記録名> --compare <比べる記録>`

## テスト
```bash
.venv/bin/python tests/test_contract.py            # ingest と runtime の Qdrant の約束が一致
.venv/bin/python tests/test_runtime_isolation.py   # runtime/ が外を参照していない
node tests/ui_runtime_e2e.mjs                      # 画面を jsdom で操作（rag-api が起動していること）
node tools/doc_editor/test/core_tests.js           # ツール（core）
node tools/doc_editor/test/cli_tests.js            # ツール（CLI の ref 付け替え）
node tools/doc_editor/test/ui_tests.js             # ツール（GUI）
.venv/bin/python tools/doc_editor/test/check_outputs.py   # ツールの出力を docling でチャンク化
```
