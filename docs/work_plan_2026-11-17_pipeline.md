# 作業手順書：PDF→Qdrant 登録パイプラインと RAG 実行環境の分離・整理

作成日: 2026-11-17
対象: RAG_practice（github.com/SHUHEI-NAGAOKA/RAG_practice）

この手順書の順に作業し、各フェーズの「確認」が通ったら次へ進む。
途中で中断したら、チェックボックス（[ ] → [x]）の状態から再開する。

---

## 0. 目的と決定事項

### 目的
- PDF から Qdrant 登録までを、工程ごとに分かれたパイプライン（コード）にする
- RAG の実行環境（Qdrant・Ollama・FastAPI・画面）を、パイプラインと依存関係のない
  独立した Docker 環境にする（本番ではこれだけを切り出して外で使う）
- 画面（JS）と API（FastAPI）を、役割ごとのファイルに分けて保守しやすくする

### ユーザーの決定（2026-11-16〜17）
| 項目 | 決定 |
|---|---|
| 階層の整理（工程3） | Claude CLI が操作リスト（JSON）を出し、ツールの CLI（tools/doc_editor/cli.js）が適用・検証する |
| 入れ子化・要約付与 | 両方とも工程に入れる（設定でオフにできる） |
| 3B / 7B の切り替え | Ollama を1つにまとめ、`.env` の `LLM_MODEL` で切り替える |
| 図の対象 | すべての図を処理する（大きさで絞らない） |
| Claude の利用 | `claude -p`（Claude Code の CLI）を使う。API キーは使わない |
| 作業の進め方 | この手順書を元に、フェーズごとに進めて報告する |
| 依存関係 | パイプライン（登録まで）と RAG 実行環境（登録後の利用）は依存させない |

### 依存関係の決まり（重要）
```
ingest/（パイプライン・開発機で実行）  ──書き込み──▶  Qdrant  ◀──読み取り──  runtime/（RAG 実行環境・Docker）
```
- `runtime/` は `ingest/`・`tools/`・`evaluation/`・ルートの `.venv` を一切 import / 参照しない。
  `runtime/` フォルダだけをコピーすれば `docker compose up` で動く。
- `ingest/` も `runtime/` のコードを import しない。
- 両者の約束（コレクション名・payload の項目・Embedding モデルと接頭辞・ベクトル次元）は
  `runtime/contract/qdrant_schema.json`（RAG 側が持つ「約束の正本」）と、
  `ingest/qdrant_schema.json`（パイプライン側の写し）に同じ内容で書く。
  食い違いはテスト `tests/test_contract.py` で検出する（コードの依存ではなくデータの照合）。
- 本番の Qdrant へは、パイプラインの `--qdrant-url` で直接登録するか、
  Qdrant のスナップショットを作って本番側で復元する（runtime/qdrant/ の手順）。
- 前回の決定「Qdrant の処理を共通パッケージにする」は、この分離の要望により取りやめ、
  上の「約束ファイル＋照合テスト」に置き換える。

---

## 1. 完成後のフォルダ構成

```
RAG_practice/
├─ README.md                    # 全体の構成と使い方（新規）
├─ ingest/                      # パイプライン（PDF → Qdrant）。ホストの .venv と node で実行
│  ├─ run.py                    # 工程を順に実行する入口（--from/--to/--only、--qdrant-url）
│  ├─ config.py                 # 文書名・入出力パス・工程ごとの設定
│  ├─ claude_cli.py             # `claude -p` を呼ぶ共通処理（入力: 指示文・読むファイル / 出力: テキスト or JSON）
│  ├─ doc_tool.py               # ツール（tools/doc_editor/cli.js）に操作リストを渡して適用する共通処理
│  ├─ docling_io.py             # DoclingDocument JSON の読み書き・要素の一覧化（Claude に渡す形へ）
│  ├─ embedding.py              # Ruri v3 で文書側のベクトルを作る（接頭辞 "検索文書: "）
│  ├─ qdrant_writer.py          # コレクション作成・索引・チャンク登録・文書要素登録（書き込み専用）
│  ├─ qdrant_schema.json        # Qdrant の約束（runtime/contract/qdrant_schema.json の写し）
│  ├─ prompts/                  # Claude CLI への指示文（工程ごと）
│  │  ├─ outline_md.md
│  │  ├─ structure_ops.md
│  │  ├─ figure_describe.md
│  │  └─ section_summary.md
│  └─ steps/
│     ├─ s01_convert_pdf.py     # PDF → DoclingDocument JSON・図の画像・ページ画像
│     ├─ s02_outline_md.py      # PDF → 階層が分かる md（Claude CLI）
│     ├─ s03_structure.py       # JSON + md → 操作リスト（Claude CLI）→ ツールで適用（階層・・・・の削除・合体）
│     ├─ s04_nest.py            # 見出しの level から入れ子（parent/children）を作る（ツールで移動）
│     ├─ s05_figures.py         # すべての図 → 意味・文脈・数値一覧（Claude CLI）→ ツールで図の直後に追加
│     ├─ s06_summaries.py       # 節ごとの要約（Claude CLI）→ ツールで本文の先頭に付ける
│     ├─ s07_chunk.py           # JSON → チャンク（HybridChunker）
│     └─ s08_register.py        # チャンクを Embedding して Qdrant へ・文書要素を Qdrant へ
├─ runtime/                     # RAG 実行環境（本番ではこのフォルダだけを切り出す）
│  ├─ compose.yaml              # qdrant / ollama / rag-api（project 名は rag_practice のまま＝既存ボリュームを使う）
│  ├─ .env.example              # LLM_MODEL=qwen2.5:3b など（コピーして .env を作る）
│  ├─ README.md                 # 実行環境だけの使い方（本番用）
│  ├─ contract/qdrant_schema.json  # Qdrant の約束の正本
│  ├─ qdrant/                   # Qdrant 側の管理（スナップショットの作成・復元、コレクションの確認）
│  │  ├─ snapshot.sh
│  │  └─ inspect.sh
│  ├─ ollama/pull_models.sh     # 使うモデル（3B・7B）を Ollama に入れる
│  └─ rag_api/
│     ├─ Dockerfile
│     ├─ requirements.txt
│     ├─ app/
│     │  ├─ main.py             # FastAPI の作成・起動時の準備・ルート登録のみ
│     │  ├─ config.py           # 環境変数（LLM_MODEL・NUM_CTX・EVAL_ENABLED など）
│     │  ├─ schemas.py          # API の入出力の型
│     │  ├─ embedding.py        # 質問のベクトル化（接頭辞 "検索クエリ: "）
│     │  ├─ qdrant_store/
│     │  │  ├─ chunks.py        # チャンクの検索・見出し範囲での数え上げと取得（読み取り専用）
│     │  │  └─ doc_items.py     # 文書要素の取得・祖先や節の本文をたどる（読み取り専用）
│     │  ├─ llm.py              # Ollama への問い合わせ（JSON スキーマ付き）
│     │  ├─ services/
│     │  │  ├─ levels.py        # ① 質問 → 見出しの候補と話題
│     │  │  ├─ subtopics.py     # ② 選んだ範囲 → 1段下の話題
│     │  │  ├─ answer.py        # ③ 選んだ話題 → 資料を作って回答
│     │  │  └─ evaluation.py    # 評価モードの記録
│     │  └─ routes/
│     │     ├─ qa.py            # /levels /subtopics /answer
│     │     ├─ search.py        # /search /ask
│     │     ├─ evaluation.py    # /eval/*（EVAL_ENABLED=false なら登録しない）
│     │     └─ system.py        # / /health
│     └─ static/
│        ├─ index.html
│        ├─ css/style.css
│        └─ js/
│           ├─ main.js            # 起動（各モジュールを組み立てる）
│           ├─ flow.js            # ①→②→③ の流れ（送信・表示・選択をつなぐ）
│           ├─ api.js             # FastAPI への送信と受信（通信はすべてここ）
│           ├─ question_input.js  # 質問を受ける（入力欄・送信）
│           ├─ choices_view.js    # 返ってきた候補を選択肢として表示する
│           ├─ selection.js       # 選択を受けて保持する（複数選択・重なり除外の数え上げ）
│           ├─ answer_view.js     # 回答・出典を表示する
│           ├─ dom.js             # 要素作成・待ち時間表示など画面の共通部品
│           └─ eval_mode.js       # 評価モード
├─ evaluation/
│  └─ eval_ragas.py             # RAGAS の採点（src/eval_ragas.py を移動）
├─ tools/doc_editor/            # 既存ツール（変更なし）
├─ tests/
│  ├─ test_contract.py          # ingest と runtime の Qdrant の約束が一致するか
│  └─ test_runtime_isolation.py # runtime/ が runtime の外を参照していないか
├─ legacy/src/                  # 旧スクリプト（移動のみ・削除しない）
└─ data/
   ├─ input/                    # 入力 PDF
   ├─ pipeline/<文書名>/        # 工程ごとの出力（番号付き、途中から再実行できる）
   └─ eval/                     # 評価の質問集と結果
```

### パイプラインの工程の入出力（data/pipeline/<文書名>/）
| 工程 | 入力 | 出力 | Claude CLI |
|---|---|---|---|
| s01 | data/input/<文書>.pdf | 01_docling.json、01_artifacts/（図の画像）、01_pages/ | なし |
| s02 | PDF | 02_outline.md（章・節を # で階層化） | あり |
| s03 | 01_docling.json、02_outline.md | 03_ops.json（操作リスト）、03_structured.json | あり（操作リスト）→ ツール |
| s04 | 03_structured.json | 04_ops.json、04_nested.json | なし → ツール |
| s05 | 04_nested.json、01_artifacts/ | 05_figures.jsonl（図ごとの説明・数値一覧）、05_ops.json、05_figures.json | あり（図ごと）→ ツール |
| s06 | 05_figures.json | 06_summaries.jsonl、06_ops.json、06_summary.json | あり（節のまとまりごと）→ ツール |
| s07 | 06_summary.json（s06 オフなら 05） | 07_chunks.jsonl、07_chunks.csv | なし |
| s08 | 07_chunks.jsonl、最終 JSON | Qdrant: rag_ruri_v3_310m、rag_doc_items | なし |

- Claude CLI の結果（02・03_ops・05・06）はファイルに残し、再実行時は既にあれば使い回す（`--force` で作り直す）。
- ツールに渡す操作は `setLabel / move / setText / addText / merge / delete`（tools/doc_editor/core.js の OPS）。
- 各工程の最後にツールの `validate` を通し、エラーが増えたら止める。

---

## 2. フェーズと作業

### フェーズ0：準備
- [x] 0-1 作業ブランチ `refactor/pipeline-runtime` を作る（main は今の動く状態のまま残す）
- [x] 0-2 今の動作の基準を記録する（/levels・/subtopics・/answer の応答の形、ツールのテスト結果）
- 確認: ブランチ上で `git status` がきれい

### フェーズ1：RAG 実行環境 `runtime/` を作る（いま動いているものの移設と分割）
- [x] 1-1 `runtime/rag_api/app/` に main.py を分割（中身の動きは変えない）
      config / schemas / embedding / qdrant_store / llm / services / routes
- [x] 1-2 `runtime/rag_api/static/` に画面を分割（index.html・css・js 8ファイル、ES モジュール）
- [x] 1-3 `runtime/contract/qdrant_schema.json` を作る（2コレクションの名前・payload・索引・ベクトル）
- [x] 1-4 `runtime/compose.yaml`（`name: rag_practice` を指定し既存のボリューム名を維持）
      Ollama を1つにまとめる（既存の `rag_practice_ollama_7b_data` を使い、3B を追加で入れる）
      `.env` の `LLM_MODEL` で 3B / 7B を切り替え。評価モードは `EVAL_ENABLED`・`EVAL_DIR` で指定
- [x] 1-5 `runtime/ollama/pull_models.sh`、`runtime/qdrant/snapshot.sh`・`inspect.py`、`runtime/README.md`
- [x] 1-6 ルートの compose.yaml・rag_api/ を runtime/ に置き換える（旧ファイルは legacy/ へ移動）
- 確認:
  - `docker compose -f runtime/compose.yaml up -d --build` で起動し、既存の Qdrant データが見える
  - LLM_MODEL を 3B / 7B に変えて /health のモデル名が変わる
  - /search・/levels・/subtopics・/answer・/eval/* がフェーズ0の基準と同じ形で応答する
  - 画面で ①→②→③・戻る・評価モードが動く
  - `tests/test_runtime_isolation.py` が通る（runtime/ の外を参照していない）
  - 3B 用だった古いボリューム `rag_practice_ollama_data` は削除しない

### フェーズ2：パイプラインの土台 `ingest/`
- [x] 2-1 config.py・run.py（工程の登録・順実行・--from/--to/--only/--force/--qdrant-url）
- [x] 2-2 claude_cli.py（`claude -p` の実行、JSON 出力の取り出し、失敗時の再試行、ログ保存）
- [x] 2-3 doc_tool.py（操作リストを cli.js に渡して適用・検証）、docling_io.py
- [x] 2-4 embedding.py・qdrant_writer.py・qdrant_schema.json（旧 embed_and_register.py・register_doc_items.py から移す）
- 確認: `python -m ingest.run --help` が動く、`tests/test_contract.py` が通る

### フェーズ3：Claude CLI を使わない工程（s01・s04・s07・s08）
- [x] 3-1 s01_convert_pdf.py（旧 convert_pdf.py）
- [x] 3-2 s04_nest.py（見出しの level から入れ子の移動操作を作りツールで適用）
- [x] 3-3 s07_chunk.py（旧 chunk_doc.py・validate_doc.py）
- [x] 3-4 s08_register.py（Qdrant への登録、--recreate）
- 確認: 既存の編集済み JSON（_figures_v2.json）から s07→s08 を流し、チャンク数 520・
  Qdrant 件数がいまと同じになる。s04 を _hierarchy.json に適用し、旧 _nested.json とチャンクが一致する

### フェーズ4：Claude CLI を使う工程（s02・s03・s05・s06）
- [x] 4-1 指示文 prompts/*.md を作る（今回の会話で行った処理の基準を文章化）
- [x] 4-2 s02_outline_md.py（PDF をページ範囲ごとに読ませ、# の階層の md を作る）
- [x] 4-3 s03_structure.py（要素の一覧と md を渡し、操作リストを JSON で返させる → ツール）
- [x] 4-4 s05_figures.py（すべての図：画像・見出し・前後の本文・キャプションを渡し、
      説明・文脈・数値一覧を JSON で返させる → ツールで図の直後に追加）
- [x] 4-5 s06_summaries.py（節ごとに本文を渡し要約を返させる → ツールで本文の先頭へ）
- 確認（少量で）: PDF の数ページ・図 2〜3 枚・節 数個で各工程を動かし、出力の形とツールの検証を確認する
  （全工程を通しで実行するのはフェーズ6、ユーザーの許可を得てから）

### フェーズ5：評価・テスト・ドキュメント
- [x] 5-1 evaluation/eval_ragas.py へ移動（API 不使用の採点のまま）
- [x] 5-2 tests/ を整える、ツールの既存テスト 4種類が全件通る
- [x] 5-3 README.md（全体）・runtime/README.md（本番用）を書く、旧 src/ を legacy/src/ へ移動
- 確認: README の手順どおりにコマンドが動く

### フェーズ6：通しでの実行（ユーザーの許可を得てから）
- [ ] 6-1 `python -m ingest.run --pdf data/input/那須烏山市総合計画.pdf` を最初から最後まで実行
      （Claude CLI の呼び出しが多い：PDF 122ページ、図 93枚、節 約300）
- [ ] 6-2 出来たチャンクを確認してもらい、OK なら Qdrant へ登録
- [ ] 6-3 評価モードで RAGAS を手動実行して、今までの結果と比べる

---

## 3. 注意点・リスク
- **ボリューム名**: compose.yaml を runtime/ に移すとプロジェクト名が変わり、別のボリュームが作られて
  データが空に見える。`name: rag_practice` を必ず指定する。`docker compose down -v` は使わない。
- **Ollama の統合**: 7B のボリュームに 3B を追加ダウンロード（約2GB、空き約30GB）。
- **Claude CLI**: 非対話（`claude -p`）で使う。読ませるファイルはプロジェクト内に限る。
  呼び出しごとの入力・出力・所要時間をログ（data/pipeline/<文書名>/logs/）に残す。
- **図の数**: すべての図（93枚）を処理する。アイコンなど意味の薄い図も短い説明を付ける。
- **既存データ**: 既存の data/edited・data/chunks_edited などは消さない（比較の基準に使う）。
- **戻し方**: 作業はブランチで行い、問題があれば main に戻る。

## 4. 進捗記録
| 日時 | フェーズ | 内容 | 結果 |
|---|---|---|---|
| 2026-11-17 | - | 手順書を作成 | - |
| 2026-11-17 | 0 | ブランチ refactor/pipeline-runtime 作成、基準の応答を data/refactor_baseline/ に保存 | 完了 |
| 2026-11-17 | 1 | runtime/ 作成（app 分割・画面を js 9ファイルに分割（flow.js を追加）・contract・compose・Ollama 統合・qdrant/ollama スクリプト・README）、旧 compose.yaml と rag_api/ を legacy/ へ | 完了: 基準と /search・/subtopics・/eval 完全一致、/levels・/answer は資料一致（LLM の文面のみ変化）、画面 E2E 12/12、3B⇔7B 切替確認、isolation テスト PASS |
| 2026-11-17 | 2 | ingest/ の土台（config・run・claude_cli・doc_tool・docling_io・embedding・qdrant_writer・qdrant_schema.json）。ツールの cli.js に ref の付け替え（RefMapper）と --report を追加 | 完了: cli_tests 5/5、test_contract PASS、`python -m ingest.run --help` |
| 2026-11-17 | 3 | s01・s04・s07・s08 | 完了: s01 122ページ 136秒（texts 3302/tables 112/pictures 93）、s04 を _hierarchy.json に適用し旧 _nested.json と親子 3701/3701・チャンク 455/455 一致、s07 で _figures_v2.json から 520 チャンク完全一致、s08 上書き登録で件数 520/3732 のまま（ID 一致） |
| 2026-11-17 | 4 | prompts 4本・s02・s03・s05・s06 | 完了: 少量（6ページ・60要素・図3枚・5節）で s02→s07 を通し各工程の出力とツールの検証を確認。1呼び出し 7〜26 秒 |
| 2026-11-17 | 5 | evaluation/ へ移動、src/ を legacy/src/ へ、check_outputs.py を ingest の s07 に向け直し、README.md | 完了: core 36/36・cli 5/5・ui 24/24・docling 36/36・24/24、contract・isolation PASS |

### 手順書の案から変えた点
- 画面の JS は 9 ファイル（①→②→③ の流れをつなぐ `flow.js` を追加）
- Qdrant の確認は Python ではなく `runtime/qdrant/inspect.sh`（本番に Python が無くても動くように）
- 要素の追加・合体・削除で番号が詰まるため、ツールの CLI に ref の付け替え（元の番号で操作を書ける）を追加
- Claude CLI を呼ぶときは ANTHROPIC_API_KEY などを外す（API 課金を使わないため）
