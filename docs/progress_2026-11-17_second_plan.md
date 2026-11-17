# 作業記録: 第2次総合計画をパイプラインに入れて RAG から参照する（2026-11-17〜）

途中で止まったら（トークン切れ・利用上限など）、この記録の「次にやること」から再開する。
工程ごとの細かい状態は `data/pipeline/那須烏山市第二次総合計画/PROGRESS.md`（パイプラインが自動で書く）。

## 依頼
- `那須烏山市第二次総合計画` をパイプラインに入れる
- JSON の編集で、第2次総合計画だと分かる文字を加える
- Qdrant への登録まで進め、RAG がこれも参照するようにする（第3次総合計画のデータは残す）

## 決めたこと・やったこと
| # | 内容 | 状態 |
|---|---|---|
| 1 | 入力は3ファイルに分かれていた（名前と中身が食い違い）。ページ順に1つにまとめた → `data/input/那須烏山市第二次総合計画.pdf`（230ページ）。元の3ファイルは残してある | 済 |
|   | ・`_資料編.pdf`（62p）= 表紙・基本構想（〜p.58） / `_基本計画.pdf`（130p）= 基本計画（p.59〜188） / `_.pdf`（38p）= 資料編（p.189〜226） | |
| 2 | `--doc-title` / `--doc-note` を追加（ingest/config.py・run.py・steps/s04_nest.py）。s04 でタイトルを書き換え（setText）、直後に説明文を追加（addText）。ツール（cli.js）で適用 | 済・試験済み |
| 3 | s01: 230ページを一度に変換すると落ちる（exit 139）→ 60ページずつ変換して `DoclingDocument.concatenate` でつなぐ（config.convert_batch_pages） | 済 |
| 4 | s02: Claude CLI は pdftoppm が無く PDF を読めない → Docling が取り出した文字（ページ・ラベル付き）を渡して見出しを判断させる（prompts/outline_md_text.md） | 済 |
| 5 | run.py: 工程ごとに PROGRESS.md を書く（開始・完了・失敗、再開コマンド） | 済（次の実行から有効） |
| 6 | s01〜s07 の実行 | 完了（s05 で利用上限により一度停止 → 再開） |
| 6b | s04: 見出しを含むグループ（リスト等）を解体して中身を body に戻す（plan_flatten、move・delete）。グループ内の見出し 24→0、警告 29→19。第3次の「Ⅰ」戦略の問題も同じ処理で直せる | 済（第2次に適用） |
| 7 | s08: Qdrant に追加登録（`--recreate` なし）。登録前のスナップショット: runtime/qdrant/snapshots/before_2nd/ | 済: チャンク 540＋1029＝1569、要素 3783＋6261＝10044 |
| 8 | 確認: 件数、第2次の質問（将来像 →「地域の魅力と活力にあふれる暮らしやすい那須烏山市」と正答）、第3次の質問は第3次の見出しが候補、test_contract / isolation / ui_e2e 12/12 PASS | 済 |

## パイプラインの実行状況（s01〜s07）
| 工程 | 状態 | メモ |
|---|---|---|
| s01 Docling | 完了 | 230ページ、texts 5115 / tables 341 / pictures 182、788秒 |
| s02 見出しの md | 完了 | 見出し 1108、Claude CLI 16回、449秒 |
| s03 構成の整理 | 完了 | Claude CLI 9回、ops 1148（setLabel 1113・merge 28・delete 6）、却下 0、539秒 |
| s04 入れ子・名前付け | 完了（グループ解体を足して作り直し済み） | タイトル「那須烏山市 第2次総合計画」＋説明文を確認。グループ解体 18、移動 2914 |
| s05 図の説明 | 完了（利用上限で一度停止 → 解除後に `--from s05` で再開） | 182図（うち飾り 138）、Claude CLI 46回、1321秒 |
| s06 節の要約 | 完了 | 595節、Claude CLI 24回、576秒 |
| s07 チャンク化 | 完了 | 1029チャンク。見出しの先頭はすべて「那須烏山市 第2次総合計画」、点線 0、図の説明 174・数値一覧 45・要約 740 |
| s08 登録 | 完了 | 131秒 |

## 状態: 完了（2026-11-17）

## 再開のしかた（参考: 途中で止まったときの手順）
1. 17:50 以降（Claude の利用上限の解除後）に再開する。実行中かどうか確認: `ps aux | grep "ingest.run" | grep -v grep`
2. 次のコマンドで続きから（**--force は付けない**。付けると Claude CLI の保存済みの返答を捨てる。s01〜s04 は出力があるので飛ばされる）:
   ```bash
   .venv/bin/python -u -m ingest.run --pdf data/input/那須烏山市第二次総合計画.pdf --from s05 --to s07 \
     --doc-title "那須烏山市 第2次総合計画" --doc-note "この文書は那須烏山市 第2次総合計画です（第3次総合計画の前の計画）。" \
     > data/pipeline/那須烏山市第二次総合計画/logs/run_resume.log 2>&1
   ```
3. s07 が済んだらチャンクを確認（07_chunks.jsonl の件数、見出しの先頭が「那須烏山市 第2次総合計画」か）
4. スナップショット: `cd runtime && ./qdrant/snapshot.sh create rag_ruri_v3_310m qdrant/snapshots/before_2nd && ./qdrant/snapshot.sh create rag_doc_items qdrant/snapshots/before_2nd`
5. 追加登録: `.venv/bin/python -m ingest.run --pdf data/input/那須烏山市第二次総合計画.pdf --only s08`（**--recreate なし**）
6. `cd runtime && docker compose restart rag-api`、件数と画面の流れを確認、`.venv/bin/python tests/test_contract.py`

## 補足
- 今の Qdrant: 第3次総合計画のパイプライン版（540チャンク / 3783要素）。手作業版は `runtime/qdrant/snapshots/manual_520/` に保存
- 既知の問題（今回は直さない）: 「Ⅰ」の戦略の見出しがリストのグループ内に残り、チャンクの見出しにならない（第3次）

## 残っている小さな問題
- Docling の文字の並びの都合で、見出しの表記が崩れたものがある（例:「本市の将来像 [基本構想] 第 1 部」「計画策定にあたって て」）
- 第3次総合計画は、s04 のグループ解体を入れる前のデータのまま（「Ⅰ」の戦略が②に出ない）。s04 から作り直せば直る
