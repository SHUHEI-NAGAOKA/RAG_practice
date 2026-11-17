#!/usr/bin/env bash
# Qdrant のスナップショット（コレクションの丸ごとの写し）を作る・戻す
# 本番へのデータの受け渡しに使う（開発機で create → ファイルを本番へ → 本番で restore）
#
# 使い方（runtime/ で実行。QDRANT_URL 省略時は http://localhost:6333）:
#   ./qdrant/snapshot.sh create  <コレクション名> [保存先フォルダ]
#       入力: コレクション名 / 出力: <保存先>/<コレクション名>.snapshot（既定の保存先 ./qdrant/snapshots）
#   ./qdrant/snapshot.sh restore <コレクション名> <スナップショットのファイル>
#       入力: コレクション名・ファイル / 出力: そのコレクションがファイルの内容で置き換わる
# 例: 2つのコレクションを両方受け渡す
#   ./qdrant/snapshot.sh create rag_ruri_v3_310m && ./qdrant/snapshot.sh create rag_doc_items
set -euo pipefail
URL=${QDRANT_URL:-http://localhost:6333}
cmd=${1:-}; name=${2:-}
[ -n "$cmd" ] && [ -n "$name" ] || { sed -n '2,12p' "$0"; exit 1; }

case "$cmd" in
  create)
    out=${3:-"$(dirname "$0")/snapshots"}
    mkdir -p "$out"
    snap=$(curl -s -X POST "$URL/collections/$name/snapshots" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["name"])')
    curl -s -o "$out/$name.snapshot" "$URL/collections/$name/snapshots/$snap"
    echo "作成: $out/$name.snapshot（Qdrant 内の名前: ${snap}）"
    ;;
  restore)
    file=${3:?スナップショットのファイルを指定してください}
    curl -s -X POST "$URL/collections/$name/snapshots/upload?priority=snapshot" -F "snapshot=@$file"
    echo
    echo "復元: $name ← $file"
    ;;
  *)
    sed -n '2,12p' "$0"; exit 1 ;;
esac
