# legacy（旧ファイル・参照用）

2026-11-17 の整理（docs/work_plan_2026-11-17_pipeline.md）で使わなくなったファイル。削除せずに残している。
動かすことは想定していない。

| 旧ファイル | 置き換え先 |
|---|---|
| compose.yaml | runtime/compose.yaml |
| rag_api/main.py | runtime/rag_api/app/（config・schemas・services・routes などに分割） |
| rag_api/static/index.html | runtime/rag_api/static/（index.html・css・js に分割） |
| src/*.py | ingest/steps/*.py（パイプラインの工程ごと） |
