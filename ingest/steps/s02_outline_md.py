"""s02: Claude CLI に章・節などの見出しの階層を判断させ、Markdown にする。

見出しかどうか・階層は Claude CLI が決める（Docling の見出しの推定はそのまま使わない）。
Claude CLI に渡すのは、Docling が PDF から取り出した文字（ページ番号・ラベル付き、1要素1行）。
  ※ この環境の Claude CLI は PDF のページを画像にする道具（pdftoppm）が無く、PDF を直接読めないため
入力: 01_docling.json（ページごとの文字）
出力: 02_outline.md（`#` の数が階層、行末に (p.ページ)）
      02_outline_parts/part_NNN.json（ページ範囲ごとの Claude の返答。再実行時は使い回す）
進め方: cfg.outline_pages_per_call ページずつ読ませる。前の範囲の最後の見出しの経路を次の範囲に渡し、
        階層がつながるようにする。cfg.sample_pages があればそのページ数までで止める（試し実行）。
"""

import json
from pathlib import Path

from .. import docling_io as dio
from ..claude_cli import load_prompt, rel, run_json
from ..config import PipelineConfig

NAME = "s02"
TITLE = "PDF → 見出しの階層の md（Claude CLI）"
USES_CLAUDE = True

SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "last_path": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["markdown", "last_path"],
}


def outputs(cfg: PipelineConfig) -> list[Path]:
    return [cfg.path("02_outline.md")]


def page_count(cfg: PipelineConfig) -> int:
    """入力: 設定 / 出力: PDF のページ数（s01 の JSON の pages から。無ければ pypdfium2 で数える）"""
    src = cfg.path("01_docling.json")
    if src.exists():
        return len(dio.load(src).get("pages", {}))
    import pypdfium2
    return len(pypdfium2.PdfDocument(str(cfg.pdf)))


def page_lines(doc: dict, max_chars: int = 120) -> dict[int, list[str]]:
    """入力: 文書 / 出力: ページ番号 → その頁の要素の行（"p.12 [section_header] 文字"、読む順）"""
    lines: dict[int, list[str]] = {}
    for ref in dio.reading_order(doc):
        it = dio.get(doc, ref)
        text = (it.get("text") or "").replace("\n", " ").strip()
        if not text or not it.get("prov"):
            continue
        page = it["prov"][0]["page_no"]
        cut = text if len(text) <= max_chars else text[:max_chars] + "…"
        lines.setdefault(page, []).append(f"p.{page} [{it.get('label')}] {cut}")
    return lines


def run(cfg: PipelineConfig) -> dict:
    total = page_count(cfg)
    if cfg.sample_pages:
        total = min(total, cfg.sample_pages)
    parts_dir = cfg.path("02_outline_parts")
    parts_dir.mkdir(exist_ok=True)

    lines = page_lines(dio.load(cfg.path("01_docling.json")))
    markdown_parts, last_path, calls = [], [], 0
    for start in range(1, total + 1, cfg.outline_pages_per_call):
        end = min(start + cfg.outline_pages_per_call - 1, total)
        part_file = parts_dir / f"part_{start:03d}.json"
        if part_file.exists() and not cfg.force:
            part = json.loads(part_file.read_text(encoding="utf-8"))  # 前回の返答を使い回す
        else:
            prompt = load_prompt(
                "outline_md_text", start=start, end=end,
                previous_path=" > ".join(last_path) if last_path else "（なし）",
                page_text="\n".join(l for p in range(start, end + 1) for l in lines.get(p, [])) or "（文字なし）",
            )
            part = run_json(cfg, prompt, SCHEMA, f"s02_pages_{start:03d}_{end:03d}")
            part_file.write_text(json.dumps(part, ensure_ascii=False, indent=1), encoding="utf-8")
            calls += 1
        markdown_parts.append(part["markdown"].strip())
        last_path = part["last_path"] or last_path

    text = "\n".join(p for p in markdown_parts if p) + "\n"
    cfg.path("02_outline.md").write_text(text, encoding="utf-8")
    headings = [l for l in text.splitlines() if l.startswith("#")]
    return {"pages": total, "claude_calls": calls, "headings": len(headings)}
