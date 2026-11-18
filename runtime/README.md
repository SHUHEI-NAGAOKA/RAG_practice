# RAG 実行環境（runtime）

Qdrant に登録済みの文書を使って質問に答える環境。**このフォルダだけで動く**（本番ではこのフォルダを切り出して使う）。
文書の登録（PDF → Qdrant）はこのフォルダの外のパイプライン（`ingest/`）が行い、ここには依存しない。

## 構成
```
runtime/
├─ compose.yaml            # qdrant / ollama / rag-api
├─ .env.example            # 設定の見本（cp .env.example .env）
├─ contract/qdrant_schema.json  # Qdrant のコレクションの約束（登録側と同じ形であること）
├─ ollama/pull_models.sh   # LLM のモデルを入れる
├─ qdrant/
│  ├─ inspect.sh           # コレクションの件数・設定・索引を確認
│  └─ snapshot.sh          # スナップショットの作成・復元（データの受け渡し）
├─ eval/                   # 評価モードの質問集と記録（本番では使わない）
└─ rag_api/
   ├─ Dockerfile / requirements.txt
   ├─ app/                 # FastAPI
   │  ├─ main.py           # アプリの作成・起動時の準備・ルート登録
   │  ├─ config.py         # 環境変数（設定の出どころはここだけ）
   │  ├─ schemas.py        # API の入出力の型
   │  ├─ deps.py           # 起動時に作った部品（Embedding・Qdrant）を routes に渡す
   │  ├─ embedding.py      # 質問のベクトル化（Ruri v3、"検索クエリ: "）
   │  ├─ llm.py            # Ollama への問い合わせ
   │  ├─ prompts.py        # LLM への指示文
   │  ├─ qdrant_store/     # Qdrant の読み取り（chunks.py・doc_items.py）
   │  ├─ services/         # 処理の中身（search・levels・subtopics・answer・evaluation）
   │  └─ routes/           # URL の受け口（system・search・qa・evaluation）
   └─ static/              # 画面
      ├─ index.html / css/style.css
      └─ js/
         ├─ main.js            # 起動
         ├─ api.js             # FastAPI への送信と受信
         ├─ question_input.js  # 質問を受ける
         ├─ flow.js            # ①話題 → ②細かい話題 → ③回答 の流れ
         ├─ choices_view.js    # 候補を選択肢として表示
         ├─ selection.js       # 選択を受けて保持
         ├─ answer_view.js     # 回答と出典を表示
         ├─ dom.js             # 画面の共通部品
         └─ eval_mode.js       # 評価モード
```

## 起動
```bash
cd runtime
cp .env.example .env                 # 必要なら LLM_MODEL などを書き換える
docker compose up -d --build
./ollama/pull_models.sh              # 初回のみ（OLLAMA_MODELS のモデルを入れる）
curl localhost:8000/health           # {"status":"ok","llm_model":"qwen2.5:3b",...}
```
画面: http://localhost:8000

**注意**: `docker compose down -v` は使わない（Qdrant のデータとモデルが消える）。止めるときは `docker compose stop`。

## 3B / 7B の切り替え
`.env` の `LLM_MODEL` を `qwen2.5:3b` か `qwen2.5:7b` にして、rag-api だけ作り直す。
```bash
docker compose up -d rag-api
```
使うモデルは `pull_models.sh` で先に入れておく。

## 検索方式（dense / bm25 / hybrid）の切り替え
`.env` の `SEARCH_MODE` で、①（/levels）・③（/answer の上位チャンク）・/search・/ask の検索方式を選ぶ。
| 値 | 内容 |
|---|---|
| dense（既定） | Ruri v3 のベクトルで検索（これまでと同じ） |
| bm25 | `embedding_text` の全文索引で BM25 検索。日本語の分かち書きは Qdrant（multilingual）が行うので、runtime に形態素解析器は要らない |
| hybrid | dense と BM25 をそれぞれ `HYBRID_PREFETCH` 件ずつ取り、順位を RRF で統合する。③の見出しの範囲は両方に付ける |
```bash
docker compose up -d rag-api   # .env を書き換えた後
curl -s localhost:8000/health  # search_mode を確認
```
- BM25 の全文索引は Qdrant 1.20 以降の機能（compose で `qdrant/qdrant:v1.20.1` に固定）。索引はパイプラインが作る
  （既存のコレクションに足すとき: `.venv/bin/python -m ingest.run --pdf <任意のPDF> --only s08 --index-only`）
- /search は `{"mode": "hybrid", "paths": [[...]]}` で方式と見出しの範囲を1回ごとに指定できる（比較用）

## データ（Qdrant）の受け渡し
登録はパイプラインが行う。本番への渡し方は2通り:
1. パイプラインから本番の Qdrant に直接登録する（`--qdrant-url` を指定）
2. 開発機でスナップショットを作り、本番で復元する
   ```bash
   # 開発機
   ./qdrant/snapshot.sh create rag_ruri_v3_310m
   ./qdrant/snapshot.sh create rag_doc_items
   # 本番（ファイルを qdrant/snapshots/ に置いて）
   ./qdrant/snapshot.sh restore rag_ruri_v3_310m qdrant/snapshots/rag_ruri_v3_310m.snapshot
   ./qdrant/snapshot.sh restore rag_doc_items   qdrant/snapshots/rag_doc_items.snapshot
   ./qdrant/inspect.sh
   ```

## API
| URL | 入力 | 出力 |
|---|---|---|
| GET /health | - | 動作状況・使用中の LLM・検索方式・評価モードの有無 |
| POST /search | {question, top_k, mode?, paths?} | 順位の高いチャンク（方式・範囲を指定可） |
| POST /ask | {question, top_k} | 類似チャンクを根拠にした回答 |
| POST /levels | {question, offset} | ① LLM が作った話題・見出しの経路（10件ずつ） |
| POST /subtopics | {paths} | ② 選んだ範囲の1段下の話題 |
| POST /answer | {question, paths} | ③ 回答と LLM に渡した資料 |
| GET /eval/questions・/eval/status、POST /eval/record | - | 評価モード（EVAL_ENABLED=true のときだけ） |

## 設定（.env）
| 項目 | 意味 | 既定 |
|---|---|---|
| LLM_MODEL | 使う LLM | qwen2.5:3b |
| NUM_CTX | LLM のコンテキスト長 | 8192 |
| SEARCH_MODE | 検索方式 dense / bm25 / hybrid | dense |
| HYBRID_PREFETCH | hybrid で各方式から取る候補数 | 30 |
| SUMMARY_DEDUP / SUMMARY_DEDUP_CHARS | LLM に渡す資料の【要約】の重なりをまとめる（先頭 N 文字が同じ要約は「【要約S1と同じ】」） | true / 10 |
| EVAL_ENABLED | 評価モード | false |
| EVAL_HOST_DIR / EVAL_TESTSET | 評価の質問集と記録の場所 | ./eval / testset_v2.jsonl |
| API_PORT / QDRANT_PORT / OLLAMA_PORT | ホスト側のポート | 8000 / 6333 / 11434 |
| OLLAMA_VOLUME | モデルを置くボリューム名 | rag_practice_ollama_models |
| OLLAMA_MODELS | pull_models.sh で入れるモデル | "qwen2.5:3b qwen2.5:7b" |
