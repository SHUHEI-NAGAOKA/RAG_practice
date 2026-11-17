"""s03: 見出しの階層の md を参考に、Claude CLI に操作リストを作らせ、ツールで文書 JSON を整える。

行うこと（Claude が操作リストを作り、ツール tools/doc_editor/cli.js が適用・検証する）:
  - 見出しの label と level を md の階層に揃える（setLabel）
  - 目次の点線「・・・」などの意味のない文字を取り除く（setText）・意味のない要素を消す（delete）
  - 改行・改ページで分かれた見出しや文をつなぐ（merge）

入力: 01_docling.json、02_outline.md
出力: 03_items/batch_NNN.txt（Claude に渡した要素の一覧）、03_ops_parts/batch_NNN.json（Claude の返答）
      03_ops.json（全体の操作リスト）、03_structured.json（整えた文書）
進め方: 文書の並び順の要素（図の中の文字は除く）を cfg.structure_items_per_call 件ずつ渡す。
        Claude の操作は、ここで形を検査してから（一覧に無い ref・使えない操作は捨てる）ツールに渡す。
"""

import json
from pathlib import Path

from .. import docling_io as dio
from ..claude_cli import load_prompt, rel, run_json
from ..config import PipelineConfig
from ..doc_tool import apply_ops
from . import input_doc

NAME = "s03"
TITLE = "md を参考に階層・不要な文字・合体を整える（Claude CLI → ツール）"
USES_CLAUDE = True

ALLOWED_OPS = {"setLabel", "setText", "merge", "delete"}
ALLOWED_LABELS = {"section_header", "title", "text"}
UNTOUCHABLE = {"page_header", "page_footer", "table", "picture", "chart"}  # 変えない要素

SCHEMA = {
    "type": "object",
    "properties": {
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": sorted(ALLOWED_OPS)},
                    "ref": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                    "label": {"type": "string"},
                    "level": {"type": "integer"},
                    "text": {"type": "string"},
                    "sep": {"type": "string"},
                },
                "required": ["op"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["ops"],
}


def outputs(cfg: PipelineConfig) -> list[Path]:
    return [cfg.path("03_structured.json")]


def target_refs(doc: dict) -> list[str]:
    """入力: 文書 / 出力: 整える対象の要素（並び順。図の中の文字とグループ自体は除く）"""
    return [r for r in dio.reading_order(doc, into_pictures=False) if not r.startswith("#/groups/")]


def check_op(op: dict, allowed: set[str], doc: dict) -> str | None:
    """Claude の操作1件を検査する。

    入力: 操作・今回の一覧の ref・文書
    出力: 問題があればその理由（無ければ None）
    """
    kind = op.get("op")
    if kind not in ALLOWED_OPS:
        return f"使えない操作 {kind}"
    refs = op.get("refs") if kind == "merge" else [op.get("ref")]
    if not refs or any(r not in allowed for r in refs):
        return f"一覧に無い ref {refs}"
    if any(dio.get(doc, r).get("label") in UNTOUCHABLE for r in refs):
        return f"変えない要素 {refs}"
    if kind == "merge" and len(refs) < 2:
        return "合体は2件以上"
    if kind == "setLabel":
        if op.get("label") not in ALLOWED_LABELS:
            return f"使えないラベル {op.get('label')}"
        if op["label"] == "section_header" and not (isinstance(op.get("level"), int) and 1 <= op["level"] <= 10):
            return f"level が不正 {op.get('level')}"
    if kind == "setText" and not isinstance(op.get("text"), str):
        return "text が無い"
    return None


def clean_op(op: dict) -> dict:
    """入力: 検査済みの操作 / 出力: ツールに渡す形（必要な項目だけ）"""
    kind = op["op"]
    if kind == "merge":
        return {"op": "merge", "refs": op["refs"], "sep": op.get("sep", "")}
    if kind == "setLabel":
        o = {"op": "setLabel", "ref": op["ref"], "label": op["label"]}
        if op["label"] == "section_header":
            o["level"] = op["level"]
        return o
    if kind == "setText":
        return {"op": "setText", "ref": op["ref"], "text": op["text"], "syncOrig": False}
    return {"op": "delete", "ref": op["ref"]}


def drop_conflicts(ops: list[dict], order: list[str]) -> tuple[list[dict], list[dict]]:
    """合体と重なる操作を捨てる。

    入力: 操作・要素の並び順 / 出力: (残す操作, 捨てた操作と理由)
    - 合体に含まれる要素への setText は捨てる（合体した本文を一部で上書きしてしまうため）
    - 合体先（並び順で先頭）以外への setLabel は捨てる（合体で消える要素のため）
    """
    pos = {r: i for i, r in enumerate(order)}
    members, heads = set(), set()
    for o in ops:
        if o["op"] == "merge":
            rs = sorted(o["refs"], key=lambda r: pos.get(r, 0))
            members |= set(rs)
            heads.add(rs[0])
    keep, dropped = [], []
    for o in ops:
        if o["op"] == "setText" and o["ref"] in members:
            dropped.append({"op": o, "reason": "合体する要素の本文の書き換え"})
        elif o["op"] == "setLabel" and o["ref"] in members - heads:
            dropped.append({"op": o, "reason": "合体で消える要素のラベル変更"})
        else:
            keep.append(o)
    return keep, dropped


def order_ops(ops: list[dict]) -> list[dict]:
    """入力: 操作 / 出力: 適用の順番に並べた操作
    合体→ラベル→本文→削除 の順にする（合体した見出しへのラベル付けが合体の後になるように。
    削除で消える要素への操作が先に済むように）"""
    rank = {"merge": 0, "setLabel": 1, "setText": 2, "delete": 3}
    return sorted(ops, key=lambda o: rank[o["op"]])


def run(cfg: PipelineConfig) -> dict:
    src = input_doc(cfg, NAME)
    doc = dio.load(src)
    refs = target_refs(doc)
    if cfg.sample_items:
        refs = refs[: cfg.sample_items]
    items_dir, parts_dir = cfg.path("03_items"), cfg.path("03_ops_parts")
    items_dir.mkdir(exist_ok=True)
    parts_dir.mkdir(exist_ok=True)

    all_ops, rejected, calls = [], [], 0
    used_refs: set[str] = set()  # 1つの要素に、合体・削除が重ならないように
    step = cfg.structure_items_per_call
    for n, i in enumerate(range(0, len(refs), step), start=1):
        batch = refs[i: i + step]
        items_file = items_dir / f"batch_{n:03d}.txt"
        items_file.write_text("\n".join(dio.brief(doc, r) for r in batch) + "\n", encoding="utf-8")
        part_file = parts_dir / f"batch_{n:03d}.json"
        if part_file.exists() and not cfg.force:
            part = json.loads(part_file.read_text(encoding="utf-8"))
        else:
            prompt = load_prompt("structure_ops", outline=rel(cfg.path("02_outline.md")), items=rel(items_file))
            part = run_json(cfg, prompt, SCHEMA, f"s03_batch_{n:03d}")
            part_file.write_text(json.dumps(part, ensure_ascii=False, indent=1), encoding="utf-8")
            calls += 1
        allowed = set(batch)
        for op in part.get("ops", []):
            reason = check_op(op, allowed, doc)
            touched = op.get("refs") if op.get("op") == "merge" else [op.get("ref")]
            if not reason and op.get("op") in ("merge", "delete") and used_refs & set(touched):
                reason = "同じ要素への合体・削除が重なっています"
            if reason:
                rejected.append({"op": op, "reason": reason})
                continue
            if op["op"] in ("merge", "delete"):
                used_refs |= set(touched)
            all_ops.append(clean_op(op))

    all_ops, more_rejected = drop_conflicts(all_ops, refs)
    rejected += more_rejected
    ops = order_ops(all_ops)
    (cfg.path("03_rejected.json")).write_text(json.dumps(rejected, ensure_ascii=False, indent=1), encoding="utf-8")
    report = apply_ops(src, cfg.path("03_structured.json"), ops, cfg.path("03_ops.json"))
    count = lambda k: sum(1 for o in ops if o["op"] == k)
    return {
        "items": len(refs), "claude_calls": calls, "ops": len(ops), "rejected": len(rejected),
        "setLabel": count("setLabel"), "setText": count("setText"), "merge": count("merge"), "delete": count("delete"),
        "warnings": report["warnings_after"],
    }
