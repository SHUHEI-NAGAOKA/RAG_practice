"""s04: 見出しの level から入れ子（parent / children）を作る。Claude CLI は使わない。

Docling の出力は、見出しも本文も body の直下に平らに並んでいる。
ここでは見出しの下に、次の同じか上の階層の見出しまでの要素をぶら下げる（ツールの move で行う）。
RAG 実行側は、チャンクの元の要素から親をたどって「節の本文」を集めるので、この入れ子が必要。

規則:
  - 文書タイトル（label=title）を根にする（ほかの要素はすべてその下）
  - section_header(level=L) は、スタックから level>=L の見出しを外し、残った一番上の見出しの下へ
  - 見出し以外（本文・表・図・リスト・グループ）は、その時点の一番内側の見出しの下へ
  - 見出しを含むグループ（例: 図の中の見出しでない、グループ化された見出し）はグループごと動かし、
    グループの中の見出しをスタックに積む（後の要素はグループ内の見出しの下に入る）

見出しを含むグループの解体（先に行う）:
  - リストなどのグループの中に section_header があると、チャンク化で見出しとして使われない
    （例:「Ⅰ 将来を担う子育て支援戦略」「政策の柱 1-2-(3)…」が②の話題に出ない）
  - そこで body 直下の、見出しを含むグループは中身を同じ位置の body に戻し、空のグループを消す（move・delete）

文書の名前付け（--doc-title / --doc-note を指定したときだけ）:
  - タイトルの文字を doc_title に書き換える（setText）。見出しの経路の先頭がタイトルなので、
    すべてのチャンクの見出しに文書名が入り、検索でも LLM に渡す資料でも文書を区別できる
  - タイトルの直後に doc_note の本文を1つ足す（addText）
  - タイトルが無い文書では、body の先頭に title を足してから入れ子にする

入力: s03 の出力（03_structured.json）
出力: 04_flatten_ops.json・04_naming_ops.json・04_ops.json（解体・名前付け・移動の操作リスト）、04_nested.json
"""

from pathlib import Path

from .. import docling_io as dio
from ..config import PipelineConfig
from ..doc_tool import apply_ops
from . import input_doc

NAME = "s04"
TITLE = "見出しの level で入れ子にする（ツール）"
USES_CLAUDE = False


def outputs(cfg: PipelineConfig) -> list[Path]:
    return [cfg.path("04_nested.json")]


def heading_in_group(doc: dict, ref: str) -> tuple[str, int] | None:
    """入力: 文書・グループの ref / 出力: グループの直下にある最初の見出しの (ref, level)。無ければ None"""
    for c in dio.children(doc, ref):
        it = dio.get(doc, c)
        if it.get("label") == "section_header":
            return c, it.get("level", 1)
    return None


def plan_moves(doc: dict) -> list[dict]:
    """入力: 平らな文書 / 出力: 入れ子にする移動の操作リスト（body の並び順に1件ずつ、末尾に追加）"""
    top = dio.children(doc, "#/body")
    title = next((r for r in top if dio.get(doc, r).get("label") == "title"), None)
    stack: list[tuple[str, int]] = [(title, 0)] if title else []  # (見出しの ref, level)
    ops = []
    for r in top:
        if r == title:
            continue
        it = dio.get(doc, r)
        if it.get("label") == "section_header":
            level = it.get("level", 1)
            while stack and stack[-1][1] >= level and stack[-1][0] != title:
                stack.pop()
            if stack:
                ops.append({"op": "move", "ref": r, "target": stack[-1][0]})
            stack.append((r, level))
            continue
        inner = heading_in_group(doc, r) if r.startswith("#/groups/") else None
        if inner:
            hr, level = inner
            while stack and stack[-1][1] >= level and stack[-1][0] != title:
                stack.pop()
            if stack:
                ops.append({"op": "move", "ref": r, "target": stack[-1][0]})
            stack.append((hr, level))
            continue
        if stack:
            ops.append({"op": "move", "ref": r, "target": stack[-1][0]})
    return ops


def plan_flatten(doc: dict) -> list[dict]:
    """入力: 平らな文書 / 出力: 見出しを含むグループを解体する操作（move で中身を body へ戻し、delete で消す）
    後ろのグループから処理するので、前のグループの位置（index）はずれない。"""
    top = dio.children(doc, "#/body")
    targets = [(i, r) for i, r in enumerate(top) if r.startswith("#/groups/")
               and any(dio.get(doc, c).get("label") == "section_header" for c in dio.children(doc, r))]
    ops = []
    for i, g in reversed(targets):
        ops.append({"op": "move", "refs": dio.children(doc, g), "target": "#/body", "index": i})
    if targets:
        ops.append({"op": "delete", "refs": [g for _, g in targets]})
    return ops


def plan_naming(doc: dict, cfg: PipelineConfig) -> list[dict]:
    """入力: 平らな文書・設定 / 出力: タイトルの書き換えと説明文の追加の操作（指定が無ければ空）"""
    if not (cfg.doc_title or cfg.doc_note):
        return []
    top = dio.children(doc, "#/body")
    title = next((r for r in top if dio.get(doc, r).get("label") == "title"), None)
    ops = []
    if title and cfg.doc_title:
        ops.append({"op": "setText", "ref": title, "text": cfg.doc_title, "syncOrig": True})
    if not title:  # タイトルが無いときは先頭に作る（見出しの経路の根にするため）
        ops.append({"op": "addText", "parent": "#/body", "index": 0, "label": "title",
                    "text": cfg.doc_title or cfg.name, "provFrom": top[0] if top else None})
        title = "@new:0"
    if cfg.doc_note:
        ops.append({"op": "addText", "after": title, "label": "text", "text": cfg.doc_note})
    return ops


def run(cfg: PipelineConfig) -> dict:
    src = input_doc(cfg, NAME)
    doc = dio.load(src)
    flatten = plan_flatten(doc)
    if flatten:
        flat = cfg.path("04_flat.json")
        apply_ops(src, flat, flatten, cfg.path("04_flatten_ops.json"))
        src = flat
        doc = dio.load(src)
    naming = plan_naming(doc, cfg)
    if naming:  # 名前付けを先に適用し、その結果で入れ子の計画を立てる
        named = cfg.path("04_named.json")
        apply_ops(src, named, naming, cfg.path("04_naming_ops.json"))
        src = named
        doc = dio.load(src)
    ops = plan_moves(doc)
    report = apply_ops(src, cfg.path("04_nested.json"), ops, cfg.path("04_ops.json"))
    return {"input": src.name, "flatten_groups": max(len(flatten) - 1, 0), "naming": len(naming), "moves": len(ops), "warnings": report["warnings_after"]}
