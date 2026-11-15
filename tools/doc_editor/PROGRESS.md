# DoclingDocument 階層エディター 作業進捗記録

途中で中断した場合は、この記録の「次にやること」から再開する。

## ゴール
- `data/output/那須烏山市総合計画/那須烏山市総合計画のコピー.json` を GUI ツールで編集・出力し、
  エラーなくチャンク化できることを確認する
- GUI の機能: バリュー変更 / 階層（親子）変更 / ラベル変更 / 一括選択・一括移動 / 個別チェック移動 /
  選択要素の JSON 表示 / 編集結果の JSON 出力
- UI: ダーク（暗めのグレー）・角丸なし・白に近いグレーの区切り線・グレーのボタン・
  ハイライトはコバルトブルー寄りのグレー・文字は白
- 進め方: 最小機能から段階的に追加。各段階でテスト → 最後にチャンク化まで検証

## ファイル構成
| ファイル | 役割 |
|---|---|
| `tools/doc_editor/core.js` | 編集ロジック（ブラウザ・Node 共通、DOM なし） |
| `tools/doc_editor/cli.js` | core.js を使うコマンドライン版（操作リスト JSON を適用して書き出し） |
| `tools/doc_editor/index.html` | GUI（未作成） |
| `tools/doc_editor/test/core_tests.js` | core.js の単体・組み合わせテスト → `data/edited/tests/*.json` と `manifest.json` を出力 |
| `tools/doc_editor/test/check_outputs.py` | 上記出力を docling で読み込み + HybridChunker でチャンク化して検証 |
| `src/validate_doc.py` | 任意の編集済み JSON を検証（`--chunk` で `data/chunks_edited/<名>/` に出力） |

## 重要な仕様メモ
- docling-core はモデルが `extra="forbid"`。ラベル変更で型が変わるので
  `section_header` は `level` 必須、`list_item` は `enumerated`/`marker`、それ以外はこれらを持てない → core.js の `applyLabel` で付け外し
- `origin.binary_hash` が 2^53 超 → `JSON.parse` の source + `JSON.rawJSON` で桁を保持（Node 26 / Chrome 114+）
- 元データの時点で docling ルール警告が 3件（空グループ `#/groups/6, 11, 18`）
- list_item をリスト外に置くと警告（docling は読み込み時に自動でリストに包む）。空グループも警告。どちらもエラーではない
- 見出しの直後に本文がない `section_header` はチャンクに現れない（HybridChunker の仕様）

## 進捗
- [x] Stage 1: 読み込み → 書き出し（無編集で元と完全一致、binary_hash 保持、docling 読み込み OK）
- [x] Stage 2: ラベル編集（単体・一括、型フィールドの付け外し、不正ラベル拒否）— core.js `setLabels`
- [x] Stage 3: 階層変更（移動・並べ替え・循環防止・一括/個別選択・親子同時選択は親のみ移動）— core.js `moveItems`, `descendants`, `topmost`
- [x] Stage 4: バリュー編集（本文変更、JSON 直接編集・構造キーの変更拒否・エラー時ロールバック）— core.js `setText`, `updateItem`
- [x] core テスト 23/23 PASS（`node tools/doc_editor/test/core_tests.js`）
- [x] docling + チャンク化検証 23/23 PASS（`.venv/bin/python tools/doc_editor/test/check_outputs.py`）
      C2 は本文のない見出しがチャンクに出ない仕様のため `expectDoc`（docling 上の label/text/parent 確認）で検証
- [x] GUI（index.html）作成: 読み込み・ツリー・JSON 表示・書き出し / ラベル / 移動・チェック選択 / 本文・JSON 編集
- [x] GUI 操作テスト 16/16 PASS（`node tools/doc_editor/test/ui_tests.js`、jsdom で実際のボタン・チェックボックス操作）
      ※ 途中 U09/U10 が FAIL → 原因は jsdom と Node で配列の realm が違い deepStrictEqual が不一致になるテスト側の問題。`ui.kids()` で変換して解決
- [x] GUI 出力の docling + チャンク化検証 16/16 PASS（`check_outputs.py data/edited/ui_tests/manifest.json`）
- [x] 本番（GOAL）: コピー JSON を GUI 操作で編集 → `data/edited/那須烏山市総合計画のコピー_edited.json` →
      `src/validate_doc.py --chunk` でエラーなくチャンク化（446件、ルール警告は元と同じ3件）→ `data/chunks_edited/那須烏山市総合計画のコピー_edited/`

## 完了（2026-11-15）
全テスト PASS。残っている制約:
- 要素の削除・新規グループ作成は未実装（GOAL の「の実現に向けて」は text に変えたため本文に重複して残る）
- テストは jsdom 上の操作。実ブラウザでの目視確認は未実施

## 再実行コマンド
```
node tools/doc_editor/test/core_tests.js
.venv/bin/python tools/doc_editor/test/check_outputs.py
node tools/doc_editor/test/ui_tests.js
.venv/bin/python tools/doc_editor/test/check_outputs.py data/edited/ui_tests/manifest.json
.venv/bin/python src/validate_doc.py "data/edited/那須烏山市総合計画のコピー_edited.json" --chunk
```（読み込み・ツリー・JSON 表示・書き出し → ラベル → 移動・選択 → バリュー編集の順で配線）
