"""LLM に渡す資料の整形: 重なった【要約】をまとめる。

チャンクの本文には、節の要約（パイプライン s06 が付けた「【要約】…」の行）が箇条書きの項目ごとに
繰り返し入っている。同じ要約が何度も LLM に渡ると、トークンを使い、注意も散る。
そこで資料の中の【要約】の行を上から順に見て、

  - 要約の文章の先頭 n 文字（settings.summary_dedup_chars、既定 10）が、それまでに出た要約と違う
      → 番号を付けて残す            例: 「【要約S1】公共交通網充実の重点戦略。…」
  - 先頭 n 文字が、それまでに出た要約と同じ
      → 文章を消し、どの要約と同じかだけを書く   例: 「【要約S1と同じ】」

資料（［資料n］）をまたいでも、同じ資料の中の繰り返しでも、同じ扱いにする。本文の行は変えない。
入力: 資料のブロックのリスト（［資料n］…／［節: …］…）
出力: 整形したブロックのリスト（LLM に渡し、評価の contexts にもこの形で残る）
"""

import re

SUMMARY_LINE = re.compile(r"^(?P<lead>\s*(?:-\s*)?)【要約】(?P<body>.*)$")


def dedupe_summaries(blocks: list[str], chars: int = 10) -> list[str]:
    """入力: 資料のブロック・比べる文字数 / 出力: 重なった要約をまとめたブロック"""
    seen: dict[str, str] = {}  # 要約の先頭 chars 文字 → 要約の番号（S1, S2, …）
    out = []
    for block in blocks:
        lines = []
        for line in block.split("\n"):
            m = SUMMARY_LINE.match(line)
            if not m:
                lines.append(line)
                continue
            body = m.group("body").strip()
            key = body[:chars]
            if key in seen:
                lines.append(f"{m.group('lead')}【要約{seen[key]}と同じ】")
            else:
                seen[key] = f"S{len(seen) + 1}"
                lines.append(f"{m.group('lead')}【要約{seen[key]}】{body}")
        out.append("\n".join(lines))
    return out
