"""s05: すべての図について、意味・文脈・数値一覧を Claude CLI に書かせ、ツールで図の直後に本文として追加する。

図（画像）はそのままではチャンクに入らないため、説明の文章を新しい要素（label=text）として
図のすぐ後ろ（同じ親の下）に追加し、同じ節のチャンクに入るようにする。

入力: s04 の出力（04_nested.json）、01_artifacts/（図の画像）
出力: 05_inputs/batch_NNN.json（Claude に渡した図の情報）
      05_figures.jsonl（図ごとの Claude の返答。1行1図。再実行時は済んだ図を飛ばす）
      05_ops.json（追加の操作リスト）、05_figures.json（図の説明を追加した文書）
追加する本文の形:
  【図の説明】題名
  文脈：…
  図の内容：…
  【数値一覧】題名        ← 数値や要素がある図だけ
  - 1行目
"""

import json
from pathlib import Path

from .. import docling_io as dio
from ..claude_cli import load_prompt, rel, run_json
from ..config import PipelineConfig
from ..doc_tool import apply_ops
from . import input_doc

NAME = "s05"
TITLE = "図の意味・文脈・数値一覧を追加（Claude CLI → ツール）"
USES_CLAUDE = True

SCHEMA = {
    "type": "object",
    "properties": {
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "title": {"type": "string"},
                    "context": {"type": "string"},
                    "content": {"type": "string"},
                    "table_title": {"type": "string"},
                    "rows": {"type": "array", "items": {"type": "string"}},
                    "decorative": {"type": "boolean"},
                },
                "required": ["ref", "title", "context", "content", "table_title", "rows", "decorative"],
            },
        }
    },
    "required": ["figures"],
}


def outputs(cfg: PipelineConfig) -> list[Path]:
    return [cfg.path("05_figures.json")]


def image_path(cfg: PipelineConfig, pic: dict) -> Path | None:
    """入力: 設定・図の要素 / 出力: 図の画像ファイル（JSON の uri。無ければ 01_artifacts/ の同名ファイル）"""
    uri = (pic.get("image") or {}).get("uri")
    if not uri:
        return None
    p = Path(uri)
    if p.exists():
        return p
    alt = cfg.artifacts_dir / p.name
    return alt if alt.exists() else None


def figure_info(cfg: PipelineConfig, doc: dict, ref: str, order: list[str]) -> dict:
    """図1つの情報を集める（Claude に渡す）。

    入力: 設定・文書・図の ref・文書の並び順
    出力: {ref, image, page, headings, caption, before, after, inside}
    """
    pic = dio.get(doc, ref)
    inside = set(dio.reading_order(doc, root=ref))
    idx = order.index(ref)

    def nearby(rng) -> list[str]:
        out = []
        for i in rng:
            r = order[i]
            it = dio.get(doc, r)
            if r in inside or it.get("label") in ("page_header", "page_footer") or not r.startswith("#/texts/"):
                continue
            out.append(dio.text_of(it)[:300])
            if len(out) == 3:
                break
        return out

    img = image_path(cfg, pic)
    return {
        "ref": ref,
        "image": rel(img) if img else None,
        "page": pic["prov"][0]["page_no"] if pic.get("prov") else None,
        "headings": dio.heading_path(doc, ref),
        "caption": " / ".join(dio.text_of(dio.get(doc, c["$ref"])) for c in pic.get("captions", [])),
        "before": list(reversed(nearby(range(idx - 1, -1, -1)))),
        "after": nearby(range(idx + 1, len(order))),
        "inside": " ｜ ".join(dio.text_of(dio.get(doc, r)) for r in dio.children(doc, ref) if r.startswith("#/texts/"))[:500],
    }


def description_text(f: dict) -> str:
    """入力: Claude の返答（図1つ分） / 出力: 図の直後に追加する本文"""
    text = f"【図の説明】{f['title']}\n文脈：{f['context']}\n図の内容：{f['content']}"
    rows = [r for r in f.get("rows", []) if r.strip()]
    if rows:
        text += f"\n【数値一覧】{f.get('table_title') or '数値'}\n" + "\n".join(f"- {r}" for r in rows)
    return text


def load_done(path: Path) -> dict[str, dict]:
    """入力: 05_figures.jsonl / 出力: 説明済みの図（ref → 返答）"""
    if not path.exists():
        return {}
    return {d["ref"]: d for d in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def run(cfg: PipelineConfig) -> dict:
    src = input_doc(cfg, NAME)
    doc = dio.load(src)
    order = dio.reading_order(doc)
    pictures = [r for r in order if r.startswith("#/pictures/")]
    if cfg.sample_figures:
        pictures = pictures[: cfg.sample_figures]

    done_path = cfg.path("05_figures.jsonl")
    if cfg.force and done_path.exists():
        done_path.unlink()
    done = load_done(done_path)
    todo = [r for r in pictures if r not in done]
    inputs_dir = cfg.path("05_inputs")
    inputs_dir.mkdir(exist_ok=True)

    calls, no_image = 0, []
    step = cfg.figures_per_call
    for n, i in enumerate(range(0, len(todo), step), start=1):
        infos = [figure_info(cfg, doc, r, order) for r in todo[i: i + step]]
        no_image += [x["ref"] for x in infos if not x["image"]]
        infos = [x for x in infos if x["image"]]
        if not infos:
            continue
        input_file = inputs_dir / f"batch_{len(done) + i:03d}.json"
        input_file.write_text(json.dumps(infos, ensure_ascii=False, indent=1), encoding="utf-8")
        result = run_json(cfg, load_prompt("figure_describe", figures=rel(input_file)), SCHEMA, f"s05_{input_file.stem}")
        calls += 1
        asked = {x["ref"] for x in infos}
        with done_path.open("a", encoding="utf-8") as f:
            for fig in result["figures"]:
                if fig["ref"] in asked:  # 渡していない ref の返答は使わない
                    f.write(json.dumps(fig, ensure_ascii=False) + "\n")
                    done[fig["ref"]] = fig

    # 図の直後に説明を追加する（ref は元の番号。追加しても既存の番号は変わらない）
    ops = [{"op": "addText", "after": r, "label": "text", "text": description_text(done[r])} for r in pictures if r in done]
    report = apply_ops(src, cfg.path("05_figures.json"), ops, cfg.path("05_ops.json"))
    return {
        "pictures": len(pictures), "described": len(ops), "claude_calls": calls,
        "decorative": sum(1 for r in pictures if r in done and done[r].get("decorative")),
        "no_image": len(no_image), "warnings": report["warnings_after"],
    }
