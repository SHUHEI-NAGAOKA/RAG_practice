"""HTTP の受け口（画面から呼ばれる URL）。中身の処理は services/ に任せる。

- system.py     : /（画面） /health
- search.py     : /search /ask
- qa.py         : /levels /subtopics /answer（階層を選んで回答するフロー）
- evaluation.py : /eval/questions /eval/status /eval/record（EVAL_ENABLED のときだけ登録）
"""
