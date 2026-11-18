# BM25 ハイブリッド検索の検討（Claude によるレビューと実装案）

作成: 2026-11-17 ／ 元にした調査: `docs/bm25_codex_report.md`（Codex がコードを読んで作成。読み取りのみ）

この文書は、Codex のレポートを Claude が確認・追加検証し、実装方針を決めるための案です。**まだ実装はしていません。**

---

## 1. Codex レポートの確認結果

### 1.1 正しいと確認できた点
| Codex の記述 | 確認 |
|---|---|
| 検索の入口は `services/search.py` の `search_chunks()` → `qdrant_store/chunks.py` の `search()`（dense のみ） | 正しい。①（`levels.py`）・③（`answer.py`）・`/search`・`/ask` がすべてここを通る |
| ③で検索順位が効くのは 6 チャンク以上（`top5+json`）のときだけ | 正しい（`answer.py` の分岐） |
| ②は質問を使わない階層の閲覧なので、BM25 は後回し | 同意 |
| Qdrant の IDF modifier だけでは BM25 にならない（sparse 方式は文書側の重み設計と語ID管理が必要） | 正しい。sparse 方式は ingest と runtime で同じ分かち書きを持つ必要があり、分離の決まりと相性が悪い |
| `chunk_id` は文書をまたいで重複する（runtime 側で結合するならキーに使えない） | 正しい（両文書とも `chunk_0000` から） |
| `qdrant/qdrant:latest` のままでは版が揺れる | 同意。**版の固定は必須**（下の方式 C は 1.20 以降の機能） |
| 要約の繰り返しが BM25 の語頻度に影響し得る（推測） | **実測で確認**: `embedding_text` に【要約】が平均 1.5〜1.6 回、最大 10 回入る。2 回以上のチャンクは 第3次 247/540・第2次 334/1029 |

### 1.2 Codex が「未確認」とした点を確認した結果
| 項目 | 結果 |
|---|---|
| 稼働中の Qdrant の版 | サーバー **1.20.1**、qdrant-client **1.20.0**（ホスト・runtime コンテナとも） |
| 全文索引の BM25（`scoring: bm25`） | **使える**。`TextIndexParams(tokenizer=multilingual, scoring=BM25)` と `TextQuery(..., using="embedding_text")` で動作 |
| 日本語の分かち書き（multilingual） | **動く**。一時コレクション（今のチャンク 1569 件の写し。試験後に削除）で検索でき、1 回 2〜40 ms |
| dense と BM25 の RRF 統合 | **動く**。`query_points(prefetch=[dense, TextQuery], query=FusionQuery(RRF))` |

試験の例（一時コレクション）:
- 「ニューツーリズム」→ 第2次の「重点施策3-4-(1) ニューツーリズムの推進」が上位（語の一致に強い）
- 「平成28年の観光入込数」→ 第2次の「（図 産業-7）観光入込数」が 1 位
- 「2060年の目標人口は、第2次と第3次でどう違う？」（c04）→ **dense も BM25 も RRF も第3次ばかり**。第2次の「目標人口」は上位 5 件に入らない

### 1.3 Codex の推奨と違う判断
Codex は「まず runtime のメモリ上の BM25（rank_bm25 + 形態素解析）で試す」を推奨しました。
**Claude は、方式 C（Qdrant 全文索引の BM25）を最初から使うことを勧めます。** 理由:

1. **確認済みで動く**（1.2）。Codex が懸念した「版と日本語対応」は解消した
2. **既存データを作り直さない**: 今のコレクションに payload index を足すだけ（Embedding のやり直し不要）
3. **runtime に形態素解析器を入れない**: 分かち書きは Qdrant が行う → ingest と runtime で同じ分かち書きコードを持つ必要がなく、**分離の決まり（runtime だけ切り出す）と矛盾しない**
4. メモリ方式の課題（起動時の全件読み込み、更新の追従、プロセスごとの索引）が無い
5. 絞り込み（③の `paths_filter`）をそのまま両方の prefetch に付けられる

メモリ方式は「Qdrant の分かち書きが行政用語に合わない」と分かったときの代替として残します。

### 1.4 Codex レポートで足りない点
- **c04 のような比較の質問の取りこぼしは、BM25 では直らない**（実測）。原因は「上位がどちらかの文書で埋まる」ことなので、別の対策（文書ごとに候補を出す）が要る → 3.3 に追加
- 要約の繰り返しへの対策（BM25 用の文字列を別に作る）→ 2.2

---

## 2. 実装案（方式 C: Qdrant 全文索引 BM25 ＋ RRF）

### 2.1 全体像
```
質問 ─┬─ Ruri で dense ベクトル ─┐
      └─ 文字列のまま（Qdrant が分かち書き・BM25）─┤→ Qdrant で RRF 統合 → 上位チャンク
                     （③では両方に paths_filter を付ける）
```

### 2.2 BM25 で索引する文字列
| 案 | 内容 | 作り直し |
|---|---|---|
| A | 既存の `embedding_text` をそのまま索引 | 不要（索引を足すだけ） |
| **B（推奨）** | 新しい payload `bm25_text` = 見出し＋本文、**【要約】の重複行を1回にする** | payload の追加だけ（`set_payload` で既存の点に足せる。Embedding は不要） |

まず A で効果を測り、要約の重複で順位が偏るようなら B に進む、の 2 段でもよい。

### 2.3 ファイルごとの変更
| 場所 | 変更 |
|---|---|
| `runtime/contract/qdrant_schema.json`（正本）・`ingest/qdrant_schema.json`（写し） | `version: 2`。chunks の `payload_indexes` に `embedding_text`（または `bm25_text`）: `{"type": "text", "tokenizer": "multilingual", "lowercase": true, "scoring": "bm25"}`、`qdrant_min_version: "1.20.0"` |
| `ingest/qdrant_writer.py` | `ensure_collection()` で、**既存のコレクションにも**索引を作る（今は新規作成時だけ）。`create_payload_index` は同じ索引があっても安全に呼べるようにする |
| `ingest/run.py` / `steps/s08_register.py` | 既存のコレクションに索引だけ足すオプション（例: `--only s08 --index-only`）。`--recreate` は使わない |
| `runtime/rag_api/app/config.py` | `SEARCH_MODE`（`dense` / `bm25` / `hybrid`、既定は当面 `dense`）、`HYBRID_PREFETCH`（例 30）、`BM25_FIELD` |
| `runtime/rag_api/app/qdrant_store/chunks.py` | `search()` に `question` を渡せるようにし、モードに応じて dense / `TextQuery` / `prefetch + FusionQuery(RRF)` を組み立てる。`query_filter` は**両方の prefetch**に付ける。offset は prefetch の件数を `offset + limit` 以上にする |
| `runtime/rag_api/app/services/search.py` | `search_chunks()` から質問文も渡す（呼び出し側 levels / answer / search ルートは変更不要にする） |
| `runtime/rag_api/app/routes/system.py` | `/health` に `search_mode` を出す（評価の記録に残すため） |
| `runtime/compose.yaml`・`.env.example` | `qdrant/qdrant:v1.20.1` に固定、`SEARCH_MODE` を追加 |
| `runtime/rag_api/requirements.txt` | `qdrant-client>=1.20` に固定（追加の依存は無し） |
| `tests/test_contract.py` | 索引定義の一致と、runtime の設定名の一致を確認 |
| （新規）`tests/test_qdrant_live.py` | 動いている Qdrant に索引があり、`TextQuery` が結果を返すか（任意・Qdrant 起動時のみ） |
| `runtime/README.md`・`README.md` | 検索モードと切り替え方 |

### 2.4 評価のしかた
1. **検索だけの比較**（LLM を通さない）: testset_v3 の 30 問で、③と同じ絞り込みのもと dense / bm25 / hybrid の上位 5 件に正解の節が入るか（Recall@5）。①の上位 10 件に正解の見出しが入るか
2. **RAGAS**: 直近と同じ手順で、①②の選択を固定（`picks_level.json` / `picks_sub.json` を再利用）して③だけ hybrid にした回答と、①から hybrid で選び直した回答の 2 本を、`20261117_v3_twodocs_qwen25-3b` と比べる
3. 既に正答している問題（a09・t07 など）が悪化しないかを見る

---

## 3. 段階的な進め方
| 段階 | 内容 | 既存データへの影響 |
|---|---|---|
| 0 | Qdrant の版を compose で固定（v1.20.1）。スナップショットを取る | なし |
| 1 | contract v2・ingest で既存コレクションに BM25 索引を追加（案 A: `embedding_text`） | 索引の追加のみ（点・ベクトルは変えない） |
| 2 | runtime に `SEARCH_MODE` を実装（既定 `dense` のまま）。テスト更新 | なし（既定の動作は同じ） |
| 3 | 検索だけの比較（2.4-1）→ RAGAS（2.4-2） | なし |
| 4 | 効果があれば既定を `hybrid` に。要約の重複が効いていれば案 B（`bm25_text`） | 案 B は payload の追加 |

### 3.3 BM25 とは別に、比較の質問のための対策（提案）
c04 のように「第2次と第3次を比べる」質問では、上位がどちらかの文書で埋まる。対策案:
- ①の検索を**文書ごとに prefetch**（`document_id` で絞った dense / BM25 をそれぞれ取り RRF）し、両文書の見出しが候補に出るようにする
- 質問に「第2次」「第3次」が両方あるときだけ、この文書ごとの検索に切り替える

---

## 4. 決めていただきたいこと
1. 方式 C（Qdrant 全文索引 BM25）で進めてよいか（メモリ BM25 は代替として残す）
2. 索引する文字列: まず案 A（`embedding_text` のまま）で測るか、最初から案 B（`bm25_text` を新設）にするか
3. 適用する段: ①と③の両方（推奨）か、どちらかだけか
4. 3.3（比較の質問向けの文書ごとの検索）も一緒に検討するか
