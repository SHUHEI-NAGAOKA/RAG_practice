#!/usr/bin/env bash
# Ollama に LLM のモデルを入れる（初回・モデルを増やしたとき）
# 入力: runtime/.env の OLLAMA_MODELS（例: "qwen2.5:3b qwen2.5:7b"）
# 出力: Ollama のボリュームにモデルが保存される（入っていれば差分だけ取得）
# 実行: runtime/ で ./ollama/pull_models.sh（rag-ollama コンテナが起動していること）
set -euo pipefail
cd "$(dirname "$0")/.."
MODELS=$(grep -E '^OLLAMA_MODELS=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
MODELS=${MODELS:-"qwen2.5:3b qwen2.5:7b"}
for m in $MODELS; do
  echo "== $m"
  docker exec rag-ollama ollama pull "$m"
done
docker exec rag-ollama ollama list
