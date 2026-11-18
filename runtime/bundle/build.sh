#!/usr/bin/env bash
# 持ち出し用のイメージ3つを作る（Qdrant のデータ・LLM・Embedding モデル入り）
#
# 入力: 開発機の Docker ボリューム
#         Qdrant のデータ      : QDRANT_VOLUME（既定 rag_practice_qdrant_data）
#         Ollama のモデル      : OLLAMA_VOLUME（既定は runtime/.env の OLLAMA_VOLUME）
#         Hugging Face キャッシュ: HF_VOLUME（既定 rag_practice_huggingface_cache）
#       BUNDLE_MODELS: 入れる LLM（空白区切り。既定 "qwen2.5:3b"）
#       BUNDLE_TAG   : イメージのタグ（既定は今日の日付 YYYYMMDD）
# 出力: rag-bundle/qdrant:<TAG>・rag-bundle/ollama:<TAG>・rag-bundle/api:<TAG>
#
# 実行: runtime/ で ./bundle/build.sh
# 注意: Qdrant のデータを写す間だけ開発用の rag-qdrant を止める（写し終えたら起動し直す）
#       作業用の写しは bundle/build/ に作り、終わったら消す（BUNDLE_KEEP_BUILD=1 で残す）
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
RUNTIME=$(dirname "$HERE")
BUILD="$HERE/build"

TAG=${BUNDLE_TAG:-$(date +%Y%m%d)}
MODELS=${BUNDLE_MODELS:-"qwen2.5:3b"}
envval() { grep -E "^$1=" "$RUNTIME/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' || true; }
QDRANT_VOLUME=${QDRANT_VOLUME:-rag_practice_qdrant_data}
HF_VOLUME=${HF_VOLUME:-rag_practice_huggingface_cache}
OLLAMA_VOLUME=${OLLAMA_VOLUME:-$(envval OLLAMA_VOLUME)}
OLLAMA_VOLUME=${OLLAMA_VOLUME:-rag_practice_ollama_models}

# 写すときに使うイメージ（Dockerfile と同じ固定の版。余計なイメージを取りに行かない）
QDRANT_IMAGE=$(sed -n 's/^FROM //p' "$HERE/Dockerfile.qdrant")
OLLAMA_IMAGE=$(sed -n 's/^FROM //p' "$HERE/Dockerfile.ollama")
API_BASE="rag-bundle/api-base:$TAG"

for v in "$QDRANT_VOLUME" "$OLLAMA_VOLUME" "$HF_VOLUME"; do
  docker volume inspect "$v" >/dev/null 2>&1 || { echo "ボリュームがありません: $v" >&2; exit 1; }
done
echo "== タグ: $TAG / モデル: $MODELS"
echo "   Qdrant: $QDRANT_VOLUME / Ollama: $OLLAMA_VOLUME / HF: $HF_VOLUME"

rm -rf "$BUILD"
mkdir -p "$BUILD/qdrant/qdrant_storage" "$BUILD/ollama/ollama_models/blobs" "$BUILD/api/huggingface"

# 1) RAG API のイメージ（runtime/rag_api/Dockerfile。版はすべて固定）
echo "== 1/5 RAG API の土台をビルド"
docker build -q -f "$RUNTIME/rag_api/Dockerfile" -t "$API_BASE" "$RUNTIME"

# 2) Qdrant のデータ: 書き込み途中のものを写さないよう、開発用の Qdrant を止めてから写す
echo "== 2/5 Qdrant のデータを写す"
was_running=$(docker ps -q -f name='^rag-qdrant$')
[ -n "$was_running" ] && docker stop rag-qdrant >/dev/null
restart_qdrant() { [ -n "$was_running" ] && docker start rag-qdrant >/dev/null && echo "   開発用の rag-qdrant を起動し直しました"; true; }
trap restart_qdrant EXIT
docker run --rm --entrypoint sh -v "$QDRANT_VOLUME:/src:ro" -v "$BUILD/qdrant/qdrant_storage:/dst" \
  "$QDRANT_IMAGE" -c 'cp -R /src/. /dst/'
restart_qdrant; trap - EXIT

# 3) Ollama のモデル: 指定したモデルの manifest と、それが指す blob だけを写す
echo "== 3/5 Ollama のモデルを写す（${MODELS}）"
digests=""
for m in $MODELS; do
  name=${m%%:*}; tag=${m#*:}; [ "$tag" = "$m" ] && tag=latest
  case "$name" in */*) rel="registry.ollama.ai/$name/$tag" ;; *) rel="registry.ollama.ai/library/$name/$tag" ;; esac
  mkdir -p "$BUILD/ollama/ollama_models/manifests/$(dirname "$rel")"
  docker run --rm --entrypoint cat -v "$OLLAMA_VOLUME:/src:ro" "$OLLAMA_IMAGE" "/src/models/manifests/$rel" \
    > "$BUILD/ollama/ollama_models/manifests/$rel" || { echo "モデルがありません: ${m}（pull_models.sh で入れてください）" >&2; exit 1; }
  digests="$digests $(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(" ".join(x["digest"].replace(":", "-") for x in [m["config"], *m["layers"]]))' \
    "$BUILD/ollama/ollama_models/manifests/$rel")"
done
docker run --rm --entrypoint sh -e DIGESTS="$digests" -v "$OLLAMA_VOLUME:/src:ro" -v "$BUILD/ollama/ollama_models/blobs:/dst" \
  "$OLLAMA_IMAGE" -c 'for d in $DIGESTS; do cp "/src/models/blobs/$d" /dst/; done'

# 4) Hugging Face のキャッシュ（質問の Embedding に使う Ruri v3）
echo "== 4/5 Hugging Face のキャッシュを写す"
docker run --rm --entrypoint sh -v "$HF_VOLUME:/src:ro" -v "$BUILD/api/huggingface:/dst" \
  "$API_BASE" -c 'cp -R /src/. /dst/'

# 5) 持ち出し用イメージ（データ・モデル入り）
echo "== 5/5 持ち出し用イメージをビルド"
docker build -q -f "$HERE/Dockerfile.qdrant" -t "rag-bundle/qdrant:$TAG" "$BUILD/qdrant"
docker build -q -f "$HERE/Dockerfile.ollama" -t "rag-bundle/ollama:$TAG" "$BUILD/ollama"
docker build -q -f "$HERE/Dockerfile.api" --build-arg BASE="$API_BASE" -t "rag-bundle/api:$TAG" "$BUILD/api"

[ "${BUNDLE_KEEP_BUILD:-0}" = 1 ] || rm -rf "$BUILD"
for i in qdrant ollama api; do docker image ls "rag-bundle/$i:$TAG"; done
echo "完了: 次は ./bundle/export.sh $TAG で持ち出し用のフォルダを作る"
