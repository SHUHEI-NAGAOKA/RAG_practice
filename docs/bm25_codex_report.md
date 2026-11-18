# BM25 とベクトル検索を組み合わせるための調査レポート

調査日：2026年11月17日  
対象：日本語の行政文書を扱う RAG 学習用リポジトリ

本調査ではコード・データを読み取り、ファイルの変更は行っていない。本文の行番号は調査時点の目安である。Qdrant の稼働環境に対する検索・移行実験は行っていない。

## 1. 結論

**まず runtime 内で完結するメモリ上の BM25 索引を作り、既存のベクトル検索と RRF で統合する実験を推奨する。** 索引の元データは登録済み Qdrant の payload から取得する。この方法なら既存コレクションを変更せず、①の話題候補生成と③の上位チャンク選択への効果を切り分けて確認できる。

効果を確認した後、データ量・更新頻度に応じて Qdrant の sparse vector 方式へ移す。さらに、調査時点の公式資料では **Qdrant v1.20.0 以降は全文 payload index 自体に BM25 scoring を設定できる**ため、実際の導入バージョンを確認したうえで、この方式も有力候補とする。[Qdrant の索引仕様](https://qdrant.tech/documentation/manage-data/indexing/)

現状の評価には検索候補の不足と、資料取得後の回答誤りが混在する。BM25 による改善を期待できるのは主に前者であり、数値の読み違いや文書間比較の誤りまで解決するとは判断できない。

## 2. 現状の検索の流れ

### 2.1 共通の質問検索

| 処理 | ファイル・関数 | 内容 |
|---|---|---|
| 起動準備 | `runtime/rag_api/app/main.py` の `lifespan()` | `QueryEmbedder` と Qdrant クライアントを作り、`app.state` に保持する |
| 質問のベクトル化 | `runtime/rag_api/app/embedding.py` の `QueryEmbedder.encode()`、19〜21行付近 | 質問に `検索クエリ: ` を付け、Ruri v3 で正規化したベクトルにする |
| 共通検索入口 | `runtime/rag_api/app/services/search.py` の `search_chunks()`、12〜17行付近 | 質問をベクトル化し、`chunks.search()` を呼ぶ |
| Qdrant 検索 | `runtime/rag_api/app/qdrant_store/chunks.py` の `search()`、60〜77行付近 | `client.query_points()` にベクトル・件数・offset・絞り込み条件を渡す |
| 結果変換 | 同ファイルの `to_source()`、18〜30行付近 | payload と score を API 用の `Source` に変換する |

現在の `query_points()` は単一の dense vector による検索であり、sparse vector、BM25、prefetch、fusion は使っていない。

### 2.2 ① 質問から話題候補を作る

入口は `runtime/rag_api/app/routes/qa.py` の `levels()`、処理本体は `services/levels.py` の `levels()` である。

1. `levels()` は `search_chunks()` で **11チャンク**を取得する。10件が表示対象、残り1件は続きを判定するために使う。
2. `build_hits()` は取得したチャンクの見出し経路を重複排除し、文書タイトルを除く各階層を `HeadingNode` にする。
3. 配下のチャンク数は `chunks.count_under()` で取得する。
4. `make_topics()` は見出し一覧と質問を LLM に渡し、話題名・説明・対応する見出し番号を作らせる。
5. 一覧にない番号や重複した番号を除いて返す。

根拠：`services/levels.py` の33〜88行付近。

**この段階の LLM にチャンク本文は渡されない。** 検索結果に正しい見出しが含まれなければ、その見出しを根拠とした候補は作れない。また、検索結果に含まれても LLM が話題として選ばない可能性は残る。

### 2.3 ② 選んだ話題の下位候補を出す

入口は `routes/qa.py` の `subtopics()`、処理本体は `services/subtopics.py` である。

- `outermost()`：選択経路の重複を除き、親が選ばれている場合は子の選択を除く。
- `subtopic_group()`：`chunks.scroll_under()` で配下の全チャンクを取得し、1段下の見出しを文書順に並べる。
- 選んだ見出しの直下に本文がある場合は「（全体）」を候補に追加する。
- `subtopics()`：候補と配下のチャンク数を返す。

根拠：`services/subtopics.py` の9〜50行付近。

②は質問を受け取らず、Embedding・類似検索・LLM を使わない。現在は選択済み範囲を階層的に閲覧する処理である。

### 2.4 ③ 選んだ範囲から回答する

入口は `routes/qa.py` の `answer()`、処理本体は `services/answer.py` の `answer()`、71〜95行付近である。

| 選択範囲のチャンク数 | 処理 |
|---|---|
| 6件未満 | `scroll_under()` で全件を取得し、`chunk_id` 順に並べる。`mode="all"` |
| 6件以上 | `heading_paths` で範囲を限定して質問検索し、上位5件を取得する。`mode="top5+json"` |

上位5件を使う場合は `section_blocks()` が文書要素も補う。

- チャンクの `source_refs` を起点に、`doc_items.py` の `section_ref()`・`heading_ancestors()` で対象見出しを探す。
- `collect_text()` で見出しと子孫の本文を文書順に集める。
- `chunk_blocks()` と `section_blocks()` が文字数による概算予算内で資料を構成する。
- `llm.chat()` に資料・質問を渡し、回答を得る。

根拠：`services/answer.py` の24〜95行、`qdrant_store/doc_items.py` の59〜98行付近。

したがって、**③で検索順位を変える効果が直接出るのは、主に6件以上の分岐**である。6件未満では現在は検索順位を使わない。

### 2.5 階層選択を使わない API

`routes/search.py` の `search()` は `/search`、`ask()` は `/ask` を受ける。両方とも共通の `search_chunks()` を使い、`/ask` は `services/search.py` の `answer_with_sources()` で回答する。

共通検索を変更すれば、①・③に加えてこの2つの API にも影響する。

## 3. データの形と ingest・runtime の約束

### 3.1 PDF から登録まで

- `ingest/steps/s07_chunk.py`
  - `build_chunker()`：Ruri のトークナイザーと Docling の `HybridChunker` を作る。既定上限は512トークン。
  - `to_records()`：本文、見出し、出典参照、ページ番号などをチャンク単位にまとめる。
  - `embedding_text` は `chunker.contextualize()` が作る見出し付き本文。
- `ingest/embedding.py`
  - `DocumentEmbedder.encode()`：`embedding_text` に `検索文書: ` を付け、正規化した dense vector を生成する。
- `ingest/steps/s08_register.py`
  - `run()`：チャンクをベクトル化し、チャンクと文書要素を2コレクションに登録する。
- `ingest/qdrant_writer.py`
  - `ensure_collection()`：コレクション・payload index を作る。
  - `chunk_payload()`：チャンクに `heading_paths` などを付ける。
  - `upsert_chunks()`・`upsert_doc_items()`：UUID を付けて登録する。

根拠：`s07_chunk.py` の26〜53行、`embedding.py` の16〜38行、`s08_register.py` の28〜44行、`qdrant_writer.py` の25〜104行付近。

なお、Docling の **HybridChunker はチャンク分割方式の名称**であり、本調査で提案する dense＋BM25 のハイブリッド検索とは別の処理である。

### 3.2 コレクション・ベクトル・ID

| 項目 | チャンク | 文書要素 |
|---|---|---|
| コレクション | `rag_ruri_v3_310m` | `rag_doc_items` |
| ベクトル | 名前なしの dense vector、768次元、Cosine | なし。登録時は `{}` |
| ID | `uuid5(NAMESPACE_URL, "<document_id>:<chunk_id>")` | `uuid5(NAMESPACE_URL, "<document_id>:<self_ref>")` |
| payload index | `heading_paths`: keyword | `self_ref`・`document_id`: keyword |
| 用途 | 質問検索・範囲選択 | 文書の木をたどり、節本文を復元 |

モデルは `cl-nagoya/ruri-v3-310m`。文書・質問とも正規化し、接頭辞だけを使い分ける。

根拠：両 `qdrant_schema.json`、`qdrant_writer.py` の37〜45行・66〜104行付近。

### 3.3 payload

チャンク payload は次の項目を持つ。

| 項目 | 意味 |
|---|---|
| `chunk_id` | 文書内のチャンク番号。実装では `chunk_0000` から始まる |
| `document_id` | DoclingDocument の `name` |
| `text` | LLM に渡す本文 |
| `headings` | 文書タイトルから対象箇所までの見出し列 |
| `heading_paths` | 各階層までを ` > ` で結んだ経路の配列 |
| `embedding_text` | 見出し＋本文。Embedding 用接頭辞は含まない |
| `source_refs` | 元の文書要素への参照 |
| `page_numbers` | ページ番号の配列 |
| `token_count` | Ruri のトークナイザーによるトークン数 |
| `parent_id` | 任意値。未指定なら登録時に `null` |

文書要素 payload は `document_id`、`self_ref`、`label`、`text`、`level`、`parent_ref`、`children_refs` を持つ。

`heading_paths` は文字列の前方一致ではなく、**各階層の経路を配列に格納し、その要素への完全一致で配下を選ぶ**仕組みである。複数経路は OR 条件になる。

根拠：`qdrant_writer.py` の49〜63行・80〜93行、`chunks.py` の33〜57行付近。

### 3.4 実データの確認

以下のファイルの先頭を各1行だけ読んだ。

- `data/pipeline/那須烏山市総合計画/07_chunks.jsonl`
- `data/pipeline/那須烏山市第二次総合計画/07_chunks.jsonl`

どちらも `chunk_0000` で、`text`、`headings`、`embedding_text`、`source_refs`、`page_numbers`、`token_count` を持つ。先頭レコードには `heading_paths`・`parent_id` はなく、これらは登録時に補われる。

第3次文書の先頭では要約文の反復も確認できた。**推測として**、同様の反復が索引全体にあれば BM25 の語頻度に影響し得る。ただし、先頭1行だけから全体の状態は判断できない。

### 3.5 contract と分離

正本は `runtime/contract/qdrant_schema.json`、写しは `ingest/qdrant_schema.json` である。

`tests/test_contract.py` の `problems()` は次を確認する。

- 両ファイルの `version`・`embedding`・`heading_sep`・`collections` の一致。
- runtime の `config.py` と `compose.yaml` にコレクション名・モデル名が含まれること。
- 質問接頭辞・見出し区切りの一致。

ただし、実際の Qdrant 設定や登録済みベクトルの内容までは検証しない。

`tests/test_runtime_isolation.py` の `problems()` は runtime 外の import・パス参照を静的に検査する。本番では **runtime だけを切り出して動かす**ため、BM25 を導入しても以下を守る必要がある。

- runtime から `ingest` を import しない。
- runtime が `data/pipeline/.../07_chunks.jsonl` を直接読まない。
- 必要な辞書・設定・索引資産は runtime 内または Qdrant 等の配備先で完結させる。
- Qdrant の登録・索引作成・移行は書き込み側で行い、runtime は読み取り側を維持する。

本調査で両テストを `python3 -B` で実行し、いずれも PASS を確認した。

## 4. BM25 導入方式の比較

### 4.1 候補一覧

| 方式 | 長所 | 短所・注意点 | 主な変更箇所 |
|---|---|---|---|
| **A. Qdrant sparse vector＋IDF modifier＋RRF** | dense と同じポイント・payload・フィルターで統合できる。runtime に全文索引を保持しない | sparse 生成仕様と移行が必要。日本語の分割・語彙ID・重み付けを両側で一致させる必要がある | 両 contract、`ingest/qdrant_writer.py`、`s08_register.py`、新設 sparse 処理、runtime の `search.py`・`chunks.py` |
| **B. runtime のメモリ上の BM25＋RRF** | 既存 Qdrant を変更せず試せる。単語分割を比較しやすい | 起動時の全件取得、メモリ、プロセスごとの索引重複、更新追従が課題 | runtime の新設 BM25 処理、`main.py`・`deps.py`・`config.py`・`services/search.py`・requirements |
| **C. Qdrant 全文 payload index** | 既存文字列 payload を利用できる。対応版ではサーバー側 BM25 も可能 | 通常の全文フィルターと BM25 ranking は別機能。バージョン・日本語トークナイザー確認が必要 | contract の索引定義、ingest の索引作成、runtime の Query API |
| **D. Elasticsearch／OpenSearch 等** | 日本語解析・辞書・検索語調整を検索エンジン側に集約しやすい | サービスと永続化・同期・バックアップが増える。学習用構成としては負担が大きい | ingest に外部登録、runtime に検索クライアント、compose にサービス・ボリューム |

### 4.2 A：Qdrant sparse vector＋IDF modifier

既存 dense vector を維持し、同じチャンクポイントに名前付き sparse vector、例えば `bm25` を追加する。

概念上は次の検索になる。

1. 質問を既存 Ruri で dense vector にする。
2. 同じ質問を日本語解析し、sparse query にする。
3. `query_points()` の prefetch で dense・sparse を取得する。
4. 外側の fusion query で RRF 統合する。

Qdrant の Query API は prefetch と RRF を提供する。offset は主検索に作用するため、各 prefetch の候補数には少なくとも `offset + limit` が必要である。[Query API と fusion](https://qdrant.tech/documentation/hybrid-queries/)

注意すべき点は、**IDF modifier を付けるだけでは BM25 にならない**ことである。文書側に TF の飽和と文書長補正を含む重みを作り、Qdrant に IDF を担当させる設計が必要となる。IDF の二重適用を避け、`k1`・`b`・平均長の定義も固定する。[Qdrant の sparse BM25](https://qdrant.tech/documentation/search/text-search/sparse-vector-search/)

日本語解析を独自に行う場合は、語から sparse 次元IDへの変換も契約に含める。Python のプロセス依存 `hash()` は使用せず、固定語彙または安定した変換方式を採用し、衝突時の扱いを決める。

③では **dense・sparse の両 prefetch に同じ `paths_filter()` を適用する**。選択範囲外の候補を混ぜてから後で除く方式では、範囲内の必要資料を取りこぼしやすい。

### 4.3 B：runtime のメモリ上に BM25 索引を作る

起動時に Qdrant から全チャンクの payload を scroll し、`embedding_text` を単語分割して `rank_bm25.BM25Okapi` 等に渡す。質問時は BM25 上位と dense 上位をポイントIDで統合し、RRF で順位を作る。

`rank_bm25` 自体は前処理・日本語分割を行わないため、文書と質問に同じ前処理が必要である。[rank_bm25 の説明](https://github.com/dorianbrown/rank_bm25)

このリポジトリでの注意点：

- 現在の `Source` は Qdrant ポイントIDを保持しない。統合処理内でIDを保持するか、`document_id` と `chunk_id` の組を使う。
- `chunk_id` 単独は複数文書で重複するため統合キーにできない。
- ③では選択範囲内のレコードだけを候補として順位付けし、その後で上位を切る。
- 初期実験ではコーパス全体で IDF を計算し、範囲制限は候補マスクで行う。範囲ごとに索引を作り直す方式とは順位が異なる。
- 未一致のチャンクを BM25 候補に機械的に混ぜない。空トークン・未知語のみの質問も扱う。
- 索引更新方法を明示する。初期案は ingest 完了後の runtime 再起動で再構築し、実運用では世代付きの原子的差し替えを検討する。

全件取得は新しい専用関数が必要である。既存の `scroll_under()` は見出し範囲を指定するための関数である。

### 4.4 C：Qdrant 全文 payload index

2つの使い方を区別する。

**全文フィルターとして使う場合：** `MatchText` 等で語の一致を条件にできるが、それだけでは BM25 順位との統合にならない。必須フィルターにすると言い換えを失うため、質問全体への一律適用は避ける。

**BM25 ranking として使う場合：** 調査時点の公式資料では v1.20.0 以降、全文索引に `scoring: bm25` を設定できる。`embedding_text` を索引対象にし、dense prefetch と RRF 統合する構成が候補となる。[全文検索の仕様](https://qdrant.tech/documentation/search/text-search/full-text-search/)

日本語には `multilingual` tokenizer が候補となり、公式資料では日本語解析に Vaporetto を使うと説明されている。ただし、行政用語・年号・固有名詞に対する分割品質は未検証である。[トークナイザー仕様](https://qdrant.tech/documentation/manage-data/indexing/)

現在の `compose.yaml` は `qdrant/qdrant:latest` であり、稼働版は特定できない。**「全文索引には BM25 がない」と一括して扱うことも、「現在すぐ利用できる」と判断することもできない。**

### 4.5 D：外部検索エンジン

Elasticsearch／OpenSearch 等に同じチャンクを登録し、BM25 結果と Qdrant 結果を runtime で RRF 統合する案である。

採用する場合は Qdrant と同じ文書・チャンクの対応、削除、更新、選択範囲の再現が必要となる。本番を runtime だけで配備するため、外部エンジンの接続設定や起動定義も runtime 側で完結させる。

現段階ではサービス追加の負担に対して効果が未確認であり、初手としての優先度は低い。

## 5. 日本語の単語分割と Docker

BM25 はトークンの一致に基づくため、日本語では空白分割だけでは不十分である。Embedding 用のサブワード分割を、そのまま BM25 の語単位として採用することも慎重に評価する必要がある。

現在の runtime イメージは `python:3.12-slim` である。

| 方法 | 利点 | 欠点 | Docker への導入 |
|---|---|---|---|
| **SudachiPy** | A/B/C の分割粒度、正規化形を選べる。複合語への対応を調整しやすい | 辞書サイズ・版・分割モードで索引が変わる。未知の固有名詞は保証されない | `SudachiPy` と `sudachidict_core` 等を requirements に追加する案。対象CPU・Python版の配布物を確認する |
| **fugashi／MeCab** | 高速な解析と辞書選択が可能 | 辞書により出力仕様が異なり、利用するフィールドを固定する必要がある | `fugashi[unidic-lite]` が候補。wheel がない環境ではビルド依存が増える可能性がある |
| **Janome** | Pure Python、辞書同梱で導入が単純 | 解析速度・辞書の語彙を評価する必要がある | pip 導入しやすい。公式資料は導入時の辞書処理に500〜600MB程度のメモリを挙げている |
| **文字 n-gram** | 辞書不要。未知語や部分一致を拾える | 偶然一致、索引肥大化、単語境界の喪失。年号・数字の部分一致が増える | Python だけで実装可能 |
| **Qdrant multilingual** | runtime に形態素解析器を追加せずサーバー側で解析できる | Sudachi 等と解析結果を共通化できず、バージョンにも依存する | 対応 Qdrant と tokenizer 設定の検証が必要 |

導入条件の根拠：[SudachiPy](https://github.com/WorksApplications/SudachiPy)、[fugashi](https://github.com/polm/fugashi)、[Janome](https://janome.mocobeta.dev/en/)。

初期実験には **SudachiPy＋固定した辞書・分割モード**を推奨する。文字 bigram は比較対象とする。

前処理の設計では次を固定する。

- Unicode 正規化、全角・半角、英数字大小文字、空白の扱い。
- 表層形・正規化形の使い分け。
- 「平成28年」「平成 28 年」「平成２８年」の照合方法。
- 数値、年号、地名、専門用語を削除しない方針。
- 固有名詞の分割結果を確認し、必要なら複合語やユーザー辞書を追加する。

元の payload・表示本文は保持し、検索用文字列にだけ正規化を適用する。和暦から西暦への変換などは別の追加仕様として扱う。

## 6. どの段階で BM25 を使うと効くか

### 6.1 ①の候補生成を優先する

①で必要な見出しが出ないと、②・③の対象範囲から外れ得る。BM25 により、質問中の固有名詞・見出し語と一致するチャンクを dense 検索に補える可能性がある。

例：

- 「烏山の山あげ行事」：長い固有名詞。
- 「特化係数」：専門語・図の説明に現れる語。
- 「平成28年」：年号と数値の組。

ただし、実際の `testset_v3.jsonl` では「特化係数」「平成28年」は主に正解文に含まれ、該当質問にそのまま出るとは限らない。**質問に存在しない語を BM25 が自動で補うわけではない**ため、dense 検索は維持する。

### 6.2 ③の上位5件選択にも適用する

6件以上の範囲では、BM25 が年号・名称・見出し語を含む根拠チャンクを上位に押し上げる可能性がある。

一方、現在はチャンク資料を先に配置し、その残りに節本文を入れる。順位改善後も文脈長による切り詰めが起こり得る。複数文書の比較では、一方の文書だけで上位が埋まる問題も別途評価する。

根拠：`services/answer.py` の29〜68行・76〜90行付近。

### 6.3 ②への適用は後回しにする

②は選択範囲の下位見出しを文書順に示す。BM25 を入れるには質問を API に追加する変更が必要となる。

初期段階では現在の階層閲覧を維持し、必要性が確認された場合に候補順の補助として検討する。

### 6.4 既存評価から分かること

`data/eval/results/20261117_v3_twodocs_qwen25-3b/summary.json` では30問の平均は次のとおり。

| 指標 | 平均 |
|---|---:|
| faithfulness | 0.794 |
| answer_relevancy | 0.847 |
| llm_context_precision_with_reference | 0.810 |
| context_recall | 0.899 |

個別記録では次の違いがある。

| 問題 | 記録で確認できる状況 | BM25 への示唆 |
|---|---|---|
| `c04` | ①で第2次の見出しが候補に出ず、第3次だけになった。context recall は0.333 | 候補検索改善の検証対象 |
| `a09` | 「烏山の山あげ行事」の質問は正答 | 現時点の失敗例とはいえない。維持できるかを確認する対象 |
| `t07` | 特化係数に関係する質問は正答 | 言い換えを dense が拾う能力を維持したい |
| `g02` | 正解に必要な資料はあるが、最多年を平成28年と誤答 | 検索だけでは解決しない |
| `c05` | 比較資料は揃っているが文書間の値・最新年を誤答 | 文書識別と回答生成の課題が残る |

根拠：同ディレクトリの `scores.csv`、`judgments.jsonl` の9・12・20・24・25行付近。

したがって、固有名詞・数値・見出し語を含む質問での取りこぼしは**起こり得るという仮説**である。これらの語すべてで既存検索が失敗したという証拠はない。

## 7. 推奨する段階的な実装手順

以下は将来の変更案であり、本調査では実装していない。

### 段階1：再現可能な baseline を作る

1. Qdrant のサーバー・クライアント版を記録し、検証版を固定する。
2. 2コレクションの件数・設定・スナップショットを記録する。
3. dense のみで `testset_v3.jsonl` を再評価する。
4. 質問ごとの検索順位・ポイントID・候補経路・最終選択・実際に渡した `contexts` を記録する。

現状は `qdrant:latest` とバージョン指定のない `qdrant-client` を使うため、依存更新を検索方式の効果と混同しないようにする。

### 段階2：メモリ BM25 で実験する

| ファイル | 変更案 |
|---|---|
| `runtime/rag_api/app/config.py` | `dense`・`bm25`・`hybrid` の切替、候補数、RRF 定数、解析設定を集約 |
| 新設 `app/lexical.py` 等 | 日本語解析と正規化を実装 |
| 新設 BM25 索引モジュール | Qdrant payload から索引構築、範囲制限付き候補取得 |
| `qdrant_store/chunks.py` | 全件 scroll と、統合に必要なポイントIDの保持 |
| `main.py`・`deps.py` | 起動時の索引構築・依存注入 |
| `services/search.py` | dense・BM25 の取得と RRF 統合。既存呼び出し側の引数を保つ |
| `requirements.txt` | `rank_bm25` と解析器・辞書の依存を追加 |
| `compose.yaml`・`.env.example` | 検索モード等を設定可能にする |
| `runtime/README.md` | 索引再構築・更新反映・必要メモリの説明 |

最初は `embedding_text` を索引対象とする。見出しを含めるためである。Ruri 用の `検索文書: `・`検索クエリ: ` は BM25 側に追加しない。

RRF は生の cosine score と BM25 score を足さず、順位を統合する。クライアント実装と Qdrant 実装を比較する場合は定数と順位の数え方を合わせる。

### 段階3：①と③を分けて効果を確認する

比較条件を次の4つに分ける。

1. dense のみ。
2. ①のみ hybrid。
3. ③のみ hybrid。
4. ①・③とも hybrid。

BM25 単独も比較対象にすると、言い換えへの弱さと語一致への強さを把握しやすい。

`levels()` の offset に応じて候補取得数を単純に増やすだけでは、RRF の候補集合が変わりページ間順位も変わり得る。十分な固定候補数、または質問単位の順位キャッシュを検討する。

### 段階4：必要なら Qdrant sparse 方式へ移す

| ファイル | 変更案 |
|---|---|
| 両 `qdrant_schema.json` | version 更新。sparse 名、解析器・辞書版、正規化、語ID生成、BM25 パラメーターを定義 |
| 新設 ingest の sparse 処理 | 文書側 sparse vector を生成 |
| `ingest/steps/s08_register.py` | dense と sparse を生成して登録 |
| `ingest/qdrant_writer.py` | sparse 設定・IDF modifier・登録処理を追加 |
| runtime の新設 sparse 処理 | 契約に合う質問側 sparse vector を生成 |
| `services/search.py`・`qdrant_store/chunks.py` | prefetch＋RRF と両検索への範囲フィルター適用 |
| requirements・compose | 検証済み依存・Qdrant 版を固定 |

ingest と runtime に共通処理が必要でも、相互 import は避ける。契約と固定テストケースで互換性を確認する。

v1.20 以降を採用できる場合は、同じ段階で全文索引 BM25 も比較する。サーバー側日本語解析で十分な品質が出れば、独自 sparse 生成・語ID管理を省ける可能性がある。

## 8. 互換性・移行・テスト

### 8.1 コレクションを作り直す必要があるか

| 方式 | 方針 |
|---|---|
| メモリ BM25 | 作り直し不要。既存 payload を読む |
| 全文 payload index | 対応版なら既存 payload への索引追加が候補。dense の再計算は不要 |
| sparse vector | 設定追加と既存全ポイントへの sparse backfill が必要。採用版で既存構成への追加可否を確認する |
| 新しい named dense＋sparse 構成 | 新コレクションへの移行として扱う。既存 dense 値は条件が同じなら再利用を検討できる |
| 外部エンジン | Qdrant の再作成は不要だが、外部索引の全件構築が必要 |

現在の dense vector は名前なしである。例示コードに合わせるためだけに `dense` と命名すると、それ自体が移行になる。既存構成を維持する案と分けて判断する。

また、現在の `ensure_collection()` は**既存コレクションの設定を移行しない**。索引作成も新規作成の分岐内だけである。contract の変更だけでは実データに反映されない。

根拠：`ingest/qdrant_writer.py` の25〜46行付近。

安全な移行案は、新しいコレクションに全対象文書を登録して検証後に接続先を切り替える方法である。既存を移行する場合も、スナップショットと dense データの保持を確認する。`--recreate` は対象コレクション全体を削除するため、複数文書の一部だけを再登録する操作と混同しない。

### 8.2 contract とテストの更新

`tests/test_contract.py` には両 JSON の一致に加え、次の検証を追加する案が必要である。

- ベクトル名・sparse 設定・IDF modifier。
- 解析器・辞書・正規化・語ID変換の互換性。
- 文書側・質問側の固定入力に対する出力。
- sparse 更新後も既存 dense vector が保持されること。
- 同じ語への IDF 二重適用がないこと。

検索の振る舞いについては、以下を確認する。

- 複数文書で同じ `chunk_id` を持っていても別候補として扱う。
- ③の範囲外チャンクが混入しない。
- 未一致語・空トークンでも正常に処理する。
- offset と候補数に矛盾がない。
- 更新・削除が索引に反映される。

`test_runtime_isolation.py` は引き続き通す。ただし静的検査なので、runtime だけのディレクトリと配備資産でコンテナを構築・起動する確認も必要である。

## 9. 評価方法

### 9.1 既存 RAGAS 手順を使う

`evaluation/eval_ragas.py` は、回答を収集して判定資料を作り、会話内で記入した判定から RAGAS と同じ式で4指標を計算する独自スクリプトである。外部の自動 judge API を呼ぶ構成ではない。

実装後の比較例：

```bash
.venv/bin/python evaluation/eval_ragas.py collect \
  --name dense_v3 --testset testset_v3.jsonl

.venv/bin/python evaluation/eval_ragas.py collect \
  --name hybrid_v3 --testset testset_v3.jsonl

.venv/bin/python evaluation/eval_ragas.py sheet \
  data/eval/results/<hybrid記録名>

# grading_sheet.md を判定し、judgments.jsonl を作成した後
.venv/bin/python evaluation/eval_ragas.py score \
  data/eval/results/<hybrid記録名> \
  --compare data/eval/results/<dense記録名>
```

各 `collect` 前に検索設定を切り替え、同じ LLM・コンテキスト長・コーパス・選択方針で比較する。

根拠：`evaluation/eval_ragas.py` の1〜34行・97〜113行・211〜255行付近。

### 9.2 選択方針を揃える

`run_flow()` は①の最初の候補、②の最初の候補を選ぶ。複数文書の候補を自動で複数選択する処理ではない。

根拠：同ファイルの69〜94行付近。

既存の `v3_twodocs` 記録には複数選択があるため、自動収集結果とそのまま比べると検索方式と選択方針の差が混ざる。次の2系統で評価する。

- **検索段階の比較**：③の選択経路を固定し、取得資料の差を見る。
- **全体フローの比較**：①から同じ選択規則で進み、候補生成から回答までを見る。

### 9.3 検索指標も追加する

RAGAS の回答指標だけでなく、以下を測る。

| 対象 | 指標 |
|---|---|
| ① | 必要な見出しが最初のページに含まれる割合、順位 |
| ③ | 正解根拠チャンクの Recall@5、MRR、必要なら nDCG |
| 比較問題 | 必要な両文書の根拠が取得できた割合 |
| 運用 | 検索時間、起動時索引構築時間、メモリ |
| 安定性 | エラー・候補なし・未採点件数 |

`testset_v3.jsonl` の `source` は説明的な文字列であり、厳密な正解チャンクID一覧ではない。検索評価には文書ID・見出し経路・根拠チャンクの対応付けが必要である。

さらに、「烏山の山あげ行事」「特化係数」「平成28年」を直接含む質問と、その言い換えを追加の検証セットとして用意する。30問だけへの過適合を避け、調整用と確認用を分ける。

`usable()` はエラー・スキップ等を除外するため、平均指標とともに母数も必ず報告する。根拠：同ファイルの120〜122行付近。

## 10. リスク・未確認事項

| 項目 | 確認状況・対処 |
|---|---|
| 稼働 Qdrant の版 | 未確認。`latest` 指定から実バージョンは判断できない |
| sparse の既存コレクションへの追加 | 採用版と現在の名前なし dense 構成で実機確認が必要 |
| 全文索引 BM25 の利用可否 | 公式資料では v1.20.0 以降。現在の環境で使えるかは未確認 |
| 日本語の分割品質 | 各解析器を未実行。固有名詞・専門語・年号の分割結果を比較する必要がある |
| Docker の導入可否 | 依存追加・ビルドは未実施。Python 3.12 と配備CPUに合う wheel・辞書を確認する |
| BM25 の改善幅 | 未測定。dense が既に正答する問題を悪化させる可能性もある |
| 要約・図説明の反復 | サンプル先頭で反復を確認。索引全体の頻度や順位への影響は未確認 |
| 索引更新の整合性 | メモリ方式では更新反映を設計する必要がある。sparse 方式でも不完全な backfill を避ける |
| 再チャンク化後の古いポイント | 現在は同じIDの upsert。チャンク数減少時などの古いポイントを自動削除する処理は `upsert_chunks()` にない |
| 取りこぼしの原因 | ①の dense 検索、LLM の話題選択、人の選択を分けて記録しないと原因を断定できない |
| 回答の数値誤り | 既存記録で資料取得後にも発生。BM25 の効果と別に評価する |
| 評価資料と実際の入力 | `AnswerResponse.sources` には切り詰め前の候補も残り得るため、採点は実際に渡した `contexts` を基準にする |

実装着手時は、既存構造を保つメモリ BM25 で効果を測り、その結果と配備版の機能を根拠に、Qdrant sparse 方式または全文索引 BM25 方式への移行を判断する。