"""s01: PDF を Docling で読み取り、DoclingDocument（JSON）と図・ページの画像にする。

入力: cfg.pdf（PDF）
出力: 01_docling.json（DoclingDocument。図の画像は 01_artifacts/ を参照）
      01_artifacts/（図の画像 PNG）、01_pages/page_NNN.png（ページ画像。s02・s05 で Claude に見せる）
大きい PDF は cfg.convert_batch_pages ページずつ変換してつなぐ
設定: OCR は RapidOCR（日本語）、表は TableFormer（精度重視）、画像の倍率は cfg.images_scale
"""

from pathlib import Path

from ..config import PipelineConfig

NAME = "s01"
TITLE = "PDF → DoclingDocument（JSON）と画像"
USES_CLAUDE = False


def outputs(cfg: PipelineConfig) -> list[Path]:
    return [cfg.path("01_docling.json")]


def build_converter(cfg: PipelineConfig):
    """入力: 設定 / 出力: Docling の変換器（OCR・表・画像の設定込み）"""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions, RapidOcrOptions, TableFormerMode, TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=RapidOcrOptions(lang=cfg.ocr_lang),
        do_table_structure=True,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
        images_scale=cfg.images_scale,
        generate_page_images=True,
        generate_picture_images=True,
    )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def save_page_images(doc, pages_dir: Path) -> int:
    """入力: 変換した文書・保存先 / 出力: 保存したページ画像の枚数（page_001.png の形）"""
    pages_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for page_no, page in sorted(doc.pages.items()):
        if page.image is None or page.image.pil_image is None:
            continue
        page.image.pil_image.save(pages_dir / f"page_{page_no:03d}.png", "PNG")
        count += 1
    return count


def page_count(pdf: Path) -> int:
    """入力: PDF / 出力: ページ数"""
    import pypdfium2
    return len(pypdfium2.PdfDocument(str(pdf)))


def convert(cfg: PipelineConfig):
    """入力: 設定 / 出力: DoclingDocument
    ページ数が cfg.convert_batch_pages を超えるときは、ページの範囲ごとに変換して
    DoclingDocument.concatenate でつなぐ（範囲ごとの変換は元のページ番号を保つので、つないだ後も同じ番号）。
    230ページの PDF を一度に変換すると落ちた（exit 139）ための対策。"""
    from docling_core.types.doc import DoclingDocument

    converter = build_converter(cfg)
    n, step = page_count(cfg.pdf), cfg.convert_batch_pages
    if n <= step:
        doc = converter.convert(cfg.pdf).document
    else:
        parts = []
        for start in range(1, n + 1, step):
            end = min(start + step - 1, n)
            print(f"  ページ {start}〜{end} / {n}", flush=True)
            parts.append(converter.convert(cfg.pdf, page_range=(start, end)).document)
        doc = DoclingDocument.concatenate(parts)
    doc.name = cfg.pdf.stem  # 文書ID（document_id）になるので PDF の名前にそろえる
    return doc


def run(cfg: PipelineConfig) -> dict:
    from docling_core.types.doc import ImageRefMode

    doc = convert(cfg)
    doc.save_as_json(
        cfg.path("01_docling.json"),
        artifacts_dir=cfg.artifacts_dir,
        image_mode=ImageRefMode.REFERENCED,
        ensure_ascii=False,  # 日本語をエスケープせずに出力
    )
    pages = save_page_images(doc, cfg.path("01_pages"))
    return {
        "texts": len(doc.texts), "tables": len(doc.tables), "pictures": len(doc.pictures), "pages": pages,
    }
