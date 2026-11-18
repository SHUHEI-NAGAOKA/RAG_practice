# テストと評価

以下は実行方法の記録であり、今回実行していない。前提や詳細は `README.md` と各ファイル参照。

| 対象 | コマンド | 内容・制約 |
| --- | --- | --- |
| 契約 | `.venv/bin/python tests/test_contract.py` | JSON の主要キー、runtime 設定値、検索方式、Qdrant イメージ版を静的照合 |
| 分離 | `.venv/bin/python tests/test_runtime_isolation.py` | 禁止 import と外部パスを正規表現で検出。実際のビルド・外部依存の完全性は検証しない |
| 画面 | `node tests/ui_runtime_e2e.mjs` | jsdom で画面を操作。README は稼働中 API を前提とする |
| 編集ツール | `node tools/doc_editor/test/core_tests.js`、`node tools/doc_editor/test/cli_tests.js`、`node tools/doc_editor/test/ui_tests.js` | core・CLI・GUI の検証 |
| 編集結果 | `.venv/bin/python tools/doc_editor/test/check_outputs.py` | Docling で出力をチャンク化して確認 |

`evaluation/eval_ragas.py` は手動または `collect` で回答と資料を集め、`sheet` で判定資料を作り、Claude Code の会話内で作る `judgments.jsonl` から `score` で faithfulness、answer relevancy、context precision、context recall を計算する。RAGAS ライブラリの実行ではなく、同様の式と独自判定を使う。出力は `scores.csv`、`summary.json`。評価判定の品質は手動判断に依存する。

`evaluation/compare_search.py` は `/search` に方式を指定し、正解見出しに対する hit@k、all@k、MRR を比較する。両スクリプトは既定で `http://localhost:8000` と `data/eval/` を参照。画面の評価記録は `runtime/rag_api/app/services/evaluation.py` がマウント先に保存するが、採点自体はホスト側。詳細なコマンドと必要ファイルは各スクリプト冒頭を参照。
