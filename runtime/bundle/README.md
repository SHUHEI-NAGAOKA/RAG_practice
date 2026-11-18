# 持ち出し用 RAG 実行環境（bundle）

Qdrant の登録済みデータ・LLM（qwen2.5:3b）・Embedding モデル（Ruri v3）を**イメージの中に入れた**コンテナ群。
持ち出し先の Mac（Apple シリコン）では、ネットにつながなくても `docker load` → `docker compose up` で同じように使える。

| イメージ | 中身 | 元にしたもの（版は固定） |
|---|---|---|
| `rag-bundle/qdrant:<TAG>` | 登録済みの2つのコレクション（チャンク・文書要素） | `qdrant/qdrant:v1.20.1` |
| `rag-bundle/ollama:<TAG>` | LLM（既定 qwen2.5:3b のみ） | `ollama/ollama:0.40.16` |
| `rag-bundle/api:<TAG>` | RAG API と画面・Ruri v3 のキャッシュ（オフライン） | `runtime/rag_api/Dockerfile`（Python・torch・pip の版を固定） |

- データはイメージの中にあり、ボリュームは使わない。`docker compose down` → `up` で常に作ったときの状態から始まる
- 公開するのは RAG API（画面）だけで、そのマシンからだけ見られる（`127.0.0.1`）。Qdrant と Ollama は外に出さない
- 評価モードは入れていない（`EVAL_ENABLED=false`）

## 開発機で作る（runtime/ で実行）
```bash
./bundle/build.sh                 # イメージ3つを作る（タグは今日の日付。BUNDLE_TAG=... で指定可）
./bundle/export.sh 20261118       # bundle/dist/rag_bundle_20261118/ に持ち出し用フォルダを作る
```
- `build.sh` は Qdrant のデータを写す間だけ開発用の `rag-qdrant` を止め、写し終えたら起動し直す
- 入れる LLM は `BUNDLE_MODELS="qwen2.5:3b qwen2.5:7b"` のように変えられる（開発機の Ollama に入っているもの）
- 文書を登録し直したら `build.sh` → `export.sh` をやり直す（データはその時点の写し）

## 持ち出し先で使う
`rag_bundle_<TAG>/` フォルダをそのままコピーして:
```bash
cd rag_bundle_<TAG>
./start.sh          # 初回は images.tar を読み込む → 起動 → /health を確認
```
画面: http://localhost:8000（ポートは `.env` の `API_PORT`）

| 操作 | コマンド |
|---|---|
| 止める | `docker compose stop` |
| 再開 | `docker compose start` |
| 検索方式を変える | `.env` の `SEARCH_MODE`（dense / bm25 / hybrid）を書き換えて `docker compose up -d` |
| ログ | `docker compose logs -f rag-api` |

必要なもの: Docker Desktop（Apple シリコンの Mac）。メモリは Docker に 8GB 以上を割り当てる（3B の LLM と Embedding モデルを読み込むため）。
