"""変換済み DoclingDocument JSON の見出しに階層（level）を付け直して Markdown に出力する。

Docling は見出しをすべて level 1 で出すため、番号の付け方（第N部・Ⅰ・１・（１）・① など）から
階層を推定する。同じ種類の番号が再び出たら「兄弟」、初めての種類なら「子」とするスタック方式。
第N部・資料編を #、その下を ##, ### … とする（Markdown の上限は ######）。

実行: .venv/bin/python src/headings_to_md.py [入力JSON]
出力: 入力と同じフォルダの <名前>_hierarchy.md
"""

import re
import sys
from pathlib import Path

from docling_core.types.doc import DoclingDocument, ImageRefMode

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/output/那須烏山市総合計画/那須烏山市総合計画.json"

D = "[0-9０-９]"
# 上から順に判定する（種類名, パターン）
KINDS = [
    ("part", rf"^(第{D}+部|資料編)"),
    ("goal", rf"^基本目標\s*{D}"),
    ("field", r"^【\s*分野別計画"),
    ("dashgoal", r"^[－\-]\s*基本目標"),
    ("strategy", r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ][\s.．]*.*戦略\s*$"),
    ("roman", r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]"),
    ("policy", rf"^政策\s*{D}"),
    ("num", rf"^{D}+[\s.．]"),
    ("paren", rf"^[（(]{D}+[）)]"),
    ("circ", r"^[①-⑳]"),
    ("alpha", r"^[A-ZＡ-Ｚ][）)]"),
]
MAJOR = {"goal", "field"}  # 部・大区分の直下に戻る種類


def kind_of(text: str) -> str:
    t = text.strip()
    for name, pat in KINDS:
        if re.match(pat, t):
            return name
    return "plain"  # 番号なし（■、【】、施策の展開など）


def assign_levels(texts: list[str]) -> list[int]:
    """見出し文字列の並びから深さ（1=#）を返す。0 は見出しにしない（本文に戻す）。"""
    kinds = [kind_of(t) for t in texts]
    levels = []
    stack: list[str] = []  # 現在の見出しの種類の並び（親→子）
    seen_parts = set()
    skip_next = False
    for i, (text, k) in enumerate(zip(texts, kinds)):
        if i == 0:  # 表紙タイトル
            levels.append(1)
            continue
        if skip_next:  # 部の扉ページの副題 → 本文
            skip_next = False
            levels.append(0)
            continue
        if k == "part":
            key = re.match(rf"^(第{D}+部|資料編)", text.strip()).group(1)
            short = text.strip() == key and i + 1 < len(texts) and kinds[i + 1] == "plain"
            if short:  # 扉ページ「第１部」＋副題 → 見出しにせず、次ページの正式見出しを使う
                levels.append(0)
                skip_next = True
                continue
            if key in seen_parts:  # 各ページ上部の繰り返し
                levels.append(0)
                continue
            seen_parts.add(key)
            stack = ["part"]
            levels.append(1)
            continue
        if not stack:  # 第１部より前（表紙・目次など）→ タイトルの下
            levels.append(2)
            continue
        if k != "plain" and k in stack:
            del stack[stack.index(k):]  # 同じ種類 → 兄弟
        elif k in MAJOR:
            stack = [s for s in stack[:2] if s in ("part", "roman")]
        elif k == "strategy" and any(g in stack for g in ("goal", "dashgoal")):
            g = next(j for j, s in enumerate(stack) if s in ("goal", "dashgoal"))
            del stack[g + 1:]  # 戦略は基本目標の直下
        elif k == "num" and any(m in stack for m in MAJOR):
            del stack[next(j for j, s in enumerate(stack) if s in MAJOR):]  # 基本目標と同列に戻る
        elif k == "plain" and "plain" in stack:
            del stack[stack.index("plain"):]  # 番号なしは番号なしの兄弟
        stack.append(k)
        levels.append(min(len(stack), 6))  # stack[0] が部（#）
    return levels


HEADING = re.compile(r"^(#{1,6}) (.*)$")


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    doc = DoclingDocument.load_from_json(src)
    md = doc.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)

    # docling の Markdown の見出し行（出現順）を推定した深さで書き換える
    lines = md.split("\n")
    idx = [i for i, l in enumerate(lines) if HEADING.match(l)]
    texts = [HEADING.match(lines[i]).group(2) for i in idx]
    levels = assign_levels(texts)
    for i, lv in zip(idx, levels):
        body = HEADING.match(lines[i]).group(2)
        lines[i] = body if lv == 0 else "#" * lv + " " + body

    out = src.with_name(f"{src.stem}_hierarchy.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"見出し {sum(1 for l in levels if l)} 件 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
