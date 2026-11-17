"""s06: 節ごとの要約を Claude CLI に書かせ、ツールでその節の本文の先頭に「【要約】…」を付ける。

チャンクは節の途中で分かれることがあるため、どのチャンクにも節の要約が入るようにして、
検索のときに節の内容が伝わるようにする（見出しの文字は変えない）。

入力: s05 の出力（05_figures.json）
出力: 06_inputs/batch_NNN.json（Claude に渡した節の情報）
      06_summaries.jsonl（節ごとの要約。1行1節。再実行時は済んだ節を飛ばす）
      06_ops.json（本文の書き換えの操作リスト）、06_summary.json（要約を付けた文書）
付け方: 見出し以外の本文の要素（texts）ごとに、いちばん近い親の見出しの要約を先頭に付ける。
        本文は「【要約】<要約>\n<元の本文>」、orig（元の文字）は変えない。
"""

import json
from pathlib import Path

from .. import docling_io as dio
from ..claude_cli import load_prompt, rel, run_json
from ..config import PipelineConfig
from ..doc_tool import apply_ops
from . import input_doc

NAME = "s06"
TITLE = "節の要約を本文の先頭に付ける（Claude CLI → ツール）"
USES_CLAUDE = True

SKIP_LABELS = ("section_header", "title", "page_header", "page_footer")
MAX_SECTION_CHARS = 2000  # Claude に渡す節の本文の上限（文字）

SCHEMA = {
    "type": "object",
    "properties": {
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"ref": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["ref", "summary"],
            },
        }
    },
    "required": ["summaries"],
}


def outputs(cfg: PipelineConfig) -> list[Path]:
    return [cfg.path("06_summary.json")]


def nearest_heading(doc: dict, ref: str) -> str | None:
    """入力: 文書・要素の ref / 出力: いちばん近い親の見出しの ref（無ければ None）"""
    r = dio.parent(doc, ref)
    while r and r not in ("#/body", "#/furniture"):
        if dio.get(doc, r).get("label") in dio.HEADING_LABELS:
            return r
        r = dio.parent(doc, r)
    return None


def sections(doc: dict) -> dict[str, list[str]]:
    """入力: 文書 / 出力: 見出しの ref → その直下の本文の要素の ref（並び順）
    （下位の見出しの中の本文は、その下位の見出しの節に入る）"""
    out: dict[str, list[str]] = {}
    for r in dio.reading_order(doc):
        if not r.startswith("#/texts/") or dio.get(doc, r).get("label") in SKIP_LABELS:
            continue
        h = nearest_heading(doc, r)
        if h:
            out.setdefault(h, []).append(r)
    return out


def load_done(path: Path) -> dict[str, str]:
    """入力: 06_summaries.jsonl / 出力: 要約済みの節（見出しの ref → 要約）"""
    if not path.exists():
        return {}
    return {d["ref"]: d["summary"] for d in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def run(cfg: PipelineConfig) -> dict:
    src = input_doc(cfg, NAME)
    doc = dio.load(src)
    secs = sections(doc)
    heads = list(secs)
    if cfg.sample_sections:
        heads = heads[: cfg.sample_sections]

    done_path = cfg.path("06_summaries.jsonl")
    if cfg.force and done_path.exists():
        done_path.unlink()
    done = load_done(done_path)
    todo = [h for h in heads if h not in done]
    inputs_dir = cfg.path("06_inputs")
    inputs_dir.mkdir(exist_ok=True)

    calls = 0
    step = cfg.summary_sections_per_call
    for i in range(0, len(todo), step):
        batch = todo[i: i + step]
        infos = [{
            "ref": h,
            "headings": dio.heading_path(doc, h) + [dio.text_of(dio.get(doc, h)).strip()],
            "text": "\n".join(dio.text_of(dio.get(doc, r)) for r in secs[h])[:MAX_SECTION_CHARS],
        } for h in batch]
        input_file = inputs_dir / f"batch_{len(done) + i:03d}.json"
        input_file.write_text(json.dumps(infos, ensure_ascii=False, indent=1), encoding="utf-8")
        result = run_json(cfg, load_prompt("section_summary", sections=rel(input_file)), SCHEMA, f"s06_{input_file.stem}")
        calls += 1
        with done_path.open("a", encoding="utf-8") as f:
            for s in result["summaries"]:
                if s["ref"] in batch and s["summary"].strip():
                    f.write(json.dumps(s, ensure_ascii=False) + "\n")
                    done[s["ref"]] = s["summary"].strip()

    # 本文の先頭に要約を付ける（orig は変えない）
    ops = []
    for h in heads:
        if h not in done:
            continue
        for r in secs[h]:
            text = dio.text_of(dio.get(doc, r))
            ops.append({"op": "setText", "ref": r, "text": f"【要約】{done[h]}\n{text}", "syncOrig": False})
    report = apply_ops(src, cfg.path("06_summary.json"), ops, cfg.path("06_ops.json"))
    return {
        "sections": len(heads), "summarized": sum(1 for h in heads if h in done), "claude_calls": calls,
        "texts_updated": len(ops), "warnings": report["warnings_after"],
    }
