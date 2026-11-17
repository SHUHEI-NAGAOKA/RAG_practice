"""DoclingDocument JSON の読み書きと、文書の木をたどる補助（docling を使わず JSON のまま扱う）。

要素は self_ref（"#/texts/12" など）で指し、親子は parent・children の {"$ref": ...} でつながる。
Claude に渡すときは brief() で1行の要約にする。
"""

import json
from pathlib import Path

ARRAYS = ["texts", "groups", "pictures", "tables", "key_value_items", "form_items"]
HEADING_LABELS = ("section_header", "title")


def load(path: Path) -> dict:
    """入力: JSON のパス / 出力: 文書（dict）"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def get(doc: dict, ref: str) -> dict:
    """入力: 文書・self_ref / 出力: その要素（#/body も可）"""
    if ref in ("#/body", "#/furniture"):
        return doc[ref[2:]]
    _, arr, i = ref.split("/")
    return doc[arr][int(i)]


def children(doc: dict, ref: str) -> list[str]:
    """入力: 文書・self_ref / 出力: 子の self_ref（順番どおり）"""
    return [c["$ref"] for c in get(doc, ref).get("children", [])]


def parent(doc: dict, ref: str) -> str | None:
    """入力: 文書・self_ref / 出力: 親の self_ref"""
    p = get(doc, ref).get("parent")
    return p["$ref"] if p else None


def reading_order(doc: dict, root: str = "#/body", into_pictures: bool = True) -> list[str]:
    """入力: 文書 / 出力: body から深さ優先でたどった全要素の self_ref（文書の並び順）"""
    out = []

    def walk(r: str):
        for c in children(doc, r):
            out.append(c)
            if into_pictures or not c.startswith("#/pictures/"):
                walk(c)

    walk(root)
    return out


def text_of(item: dict) -> str:
    """入力: 要素 / 出力: 本文（表はセルを | でつないだ行、グループは名前、無ければ空）"""
    if "text" in item and isinstance(item["text"], str):
        return item["text"]
    if "data" in item:  # 表
        rows = []
        for row in item["data"].get("grid", []):
            cells = []
            for c in row:
                t = (c.get("text") or "").strip()
                if not cells or cells[-1] != t:
                    cells.append(t)
            rows.append(" | ".join(cells))
        return "\n".join(rows)
    return ""


def brief(doc: dict, ref: str, width: int = 80) -> str:
    """入力: 文書・self_ref / 出力: 「ref | ラベル(level) | p.ページ | 本文の頭」の1行（Claude に渡す一覧用）"""
    it = get(doc, ref)
    label = it.get("label", "")
    if label == "section_header":
        label += f"(L{it.get('level')})"
    page = it.get("prov", [{}])[0].get("page_no", "-") if it.get("prov") else "-"
    t = " ".join(text_of(it).split())
    if len(t) > width:
        t = t[:width] + "…"
    return f"{ref} | {label} | p.{page} | {t}"


def heading_path(doc: dict, ref: str) -> list[str]:
    """入力: 文書・self_ref / 出力: 親をたどった見出しの本文（上から順）"""
    path, r = [], parent(doc, ref)
    while r and r not in ("#/body", "#/furniture"):
        it = get(doc, r)
        if it.get("label") in HEADING_LABELS:
            path.append(text_of(it).split("\n")[-1].strip())
        r = parent(doc, r)
    return list(reversed(path))
