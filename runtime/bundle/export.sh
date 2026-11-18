#!/usr/bin/env bash
# 持ち出し用のフォルダを作る（イメージの tar・compose・設定・手順書・起動スクリプト）
#
# 入力: タグ（build.sh で付けたもの。省略時は BUNDLE_TAG、それも無ければ今日の日付）
# 出力: bundle/dist/rag_bundle_<TAG>/
#         images.tar   : rag-bundle/{qdrant,ollama,api}:<TAG>（docker save）
#         compose.yaml : 持ち出し用の構成
#         .env         : BUNDLE_TAG を書き込んだ設定
#         start.sh     : 読み込み（初回）→ 起動 → 稼働確認
#         README.md    : 持ち出し先での手順
# 実行: runtime/ で ./bundle/export.sh [TAG]
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
TAG=${1:-${BUNDLE_TAG:-$(date +%Y%m%d)}}
IMAGES="rag-bundle/qdrant:$TAG rag-bundle/ollama:$TAG rag-bundle/api:$TAG"
for i in $IMAGES; do
  docker image inspect "$i" >/dev/null 2>&1 || { echo "イメージがありません: ${i}（先に build.sh）" >&2; exit 1; }
done

OUT="$HERE/dist/rag_bundle_$TAG"
mkdir -p "$OUT"
echo "== イメージを書き出す（数分かかる）"
# shellcheck disable=SC2086
docker save -o "$OUT/images.tar" $IMAGES
cp "$HERE/compose.yaml" "$HERE/start.sh" "$HERE/README.md" "$OUT/"
sed "s/^BUNDLE_TAG=.*/BUNDLE_TAG=$TAG/" "$HERE/.env.example" > "$OUT/.env"
chmod +x "$OUT/start.sh"
du -sh "$OUT"/*
echo "完了: $OUT をフォルダごと持ち出し先の Mac にコピーし、そこで ./start.sh"
