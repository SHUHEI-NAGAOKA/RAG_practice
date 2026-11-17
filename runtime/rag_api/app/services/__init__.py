"""処理の中身（routes から呼ばれる）。HTTP の受け取り方には関わらない。

- search.py     : 質問で検索する・検索結果で回答する（/search /ask）
- levels.py     : ① 質問 → 見出しの候補と話題（/levels）
- subtopics.py  : ② 選んだ範囲 → 1段下の話題（/subtopics）
- answer.py     : ③ 選んだ話題 → 資料を作って回答（/answer）
- evaluation.py : 評価モードの質問集の読み込みと記録（/eval/*）
"""
