#!/usr/bin/env bash
# Qdrant のコレクションの状態を確認する（件数・ベクトル設定・payload の索引）
# 入力: QDRANT_URL（省略時 http://localhost:6333）
# 出力: コレクションごとの件数・ベクトルの次元と距離・索引の一覧（標準出力）
# 実行: runtime/ で ./qdrant/inspect.sh
set -euo pipefail
URL=${QDRANT_URL:-http://localhost:6333}
for name in $(curl -s "$URL/collections" | python3 -c 'import json,sys;print(" ".join(c["name"] for c in json.load(sys.stdin)["result"]["collections"]))' 2>/dev/null || curl -s "$URL/collections" | grep -o '"name":"[^"]*"' | cut -d'"' -f4); do
  echo "== $name"
  curl -s "$URL/collections/$name" | python3 -c '
import json,sys
r=json.load(sys.stdin)["result"]
print("  件数:", r.get("points_count"))
print("  ベクトル:", json.dumps(r["config"]["params"].get("vectors"), ensure_ascii=False))
print("  索引:", ", ".join("%s(%s)" % (k, v.get("data_type")) for k, v in r.get("payload_schema", {}).items()))
' 2>/dev/null || curl -s "$URL/collections/$name"
done
