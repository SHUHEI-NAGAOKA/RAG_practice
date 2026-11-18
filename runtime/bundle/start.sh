#!/usr/bin/env bash
# 持ち出し先で RAG 実行環境を起動する
# 入力: このフォルダの images.tar・compose.yaml・.env
# 出力: コンテナ rag-bundle-{qdrant,ollama,api} が起動し、http://localhost:<API_PORT> で使える
# 実行: このフォルダで ./start.sh（イメージが未読み込みなら images.tar から読み込む）
set -euo pipefail
cd "$(dirname "$0")"

TAG=$(grep -E '^BUNDLE_TAG=' .env | cut -d= -f2-)
PORT=${API_PORT:-$(grep -E '^API_PORT=' .env | cut -d= -f2-)}; PORT=${PORT:-8000}  # 環境変数 API_PORT が優先
[ -n "$TAG" ] || { echo ".env に BUNDLE_TAG がありません" >&2; exit 1; }

if ! docker image inspect "rag-bundle/api:$TAG" >/dev/null 2>&1; then
  echo "== イメージを読み込む（初回のみ。数分かかる）"
  docker load -i images.tar
fi

docker compose up -d
echo "== 起動を待つ（Embedding モデルの読み込みに少しかかる）"
for _ in $(seq 1 60); do
  if curl -fs "http://localhost:$PORT/health" >/dev/null 2>&1; then
    curl -s "http://localhost:$PORT/health"; echo
    echo "起動しました: http://localhost:$PORT"
    exit 0
  fi
  sleep 2
done
echo "起動を確認できませんでした: docker compose logs rag-api を確認してください" >&2
exit 1
