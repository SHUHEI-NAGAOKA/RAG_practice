# レビュー・リファクタリング候補

以下は静的調査による候補で、障害の再現や修正は行っていない。

1. **契約の重複と検証**: `runtime/contract/qdrant_schema.json`、`ingest/qdrant_schema.json`、`runtime/rag_api/app/config.py`、Compose に値が重複。`tests/test_contract.py` は文字列照合中心で実データを検証しない。互換性検査、生成や契約変更時の運用を検討する。
2. **登録の更新整合性**: `ingest/qdrant_writer.py` は同一 ID を upsert する一方、旧 ID の削除はない。チャンク数や要素数が減った再登録で余剰点が残り得る。s08 は 2 コレクションに順次書くため途中失敗時の整合性も確認する。
3. **移植と評価の境界**: `runtime/compose.yaml` のデータ・モデルは別ボリューム、評価採点は `evaluation/` と `data/eval/` にある。`runtime/` 単体で何を提供するか、スナップショット二つの対応・復元検証を明確化する。
4. **設定・依存の再現性**: `runtime/rag_api/app/config.py` の評価既定 true と Compose の false は異なる。runtime の依存・torch・Ollama の版固定や、直接 import するホスト依存の明示を検討する（`04_packages.md`）。
5. **回答と検索の境界**: `services/answer.py` は文字数でトークン予算を近似し、最初の資料は予算超過でも含める。複数文書の同一見出し経路、資料の順序や切り詰め時の挙動を評価する。
6. **重複・旧実装**: 埋め込みモデル名・接頭辞は `ingest/embedding.py`、runtime の設定、`evaluation/eval_ragas.py` などに分散。`legacy/README.md` は旧コードを参照用と明記するが、検索や変更時の誤認を避ける扱いを決める。`ingest/steps/__init__.py` の工程順と `ingest/run.py` の順も二重管理。
7. **テストの粒度**: 契約・分離テストは静的パターンで、DB の実スキーマ、snapshot 復元、検索・回答の境界ケースを保証しない。`tests/` と `tools/doc_editor/test/` を入口に、必要な統合テストや失敗ケースをレビューする。
