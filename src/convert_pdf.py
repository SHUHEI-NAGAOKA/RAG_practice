"""PDFをDoclingで変換し、JSONとMarkdownで出力する。

実行（コンテナ内 /app で）:
    python src/convert_pdf.py
入力: data/input/*.pdf
出力: data/output/<PDF名>/
    <PDF名>.json        Docling形式のJSON（画像はファイル参照）
    <PDF名>.md          Markdown（図は画像ファイル参照）
    <PDF名>_artifacts/  JSON・Markdownから参照される画像
    pages/page_001.png  ページ画像
"""

from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode

# ==========================================
# 設定
# ==========================================
OCR_LANG = ["iso:ja"]  # RapidOCR の日本語指定
IMAGES_SCALE = 1.0  # 画像の解像度倍率（1.0 = 72dpi相当）

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"


def build_converter() -> DocumentConverter:
    """変換設定を組み立てる。backend は標準（ThreadedDoclingParseDocumentBackend）。"""
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=RapidOcrOptions(lang=OCR_LANG),
        do_table_structure=True,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
        images_scale=IMAGES_SCALE,
        generate_page_images=True,
        generate_picture_images=True,
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


def save_page_images(doc, pages_dir: Path) -> int:
    """ページ画像を pages/page_001.png の形で保存する。"""
    pages_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for page_no, page in sorted(doc.pages.items()):
        if page.image is None or page.image.pil_image is None:
            continue
        page.image.pil_image.save(pages_dir / f"page_{page_no:03d}.png", "PNG")
        count += 1
    return count


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdf_paths:
        print(f"PDFがありません: {INPUT_DIR}")
        return

    converter = build_converter()

    for pdf_path in pdf_paths:
        print(f"変換中: {pdf_path.name}")
        doc = converter.convert(pdf_path).document

        out_dir = OUTPUT_DIR / pdf_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = out_dir / f"{pdf_path.stem}_artifacts"

        doc.save_as_json(
            out_dir / f"{pdf_path.stem}.json",
            artifacts_dir=artifacts_dir,
            image_mode=ImageRefMode.REFERENCED,
            ensure_ascii=False,  # 日本語をエスケープせずそのまま出力
        )
        doc.save_as_markdown(
            out_dir / f"{pdf_path.stem}.md",
            artifacts_dir=artifacts_dir,
            image_mode=ImageRefMode.REFERENCED,
        )
        page_count = save_page_images(doc, out_dir / "pages")

        print(f"出力: {out_dir}（ページ画像 {page_count}枚）")


if __name__ == "__main__":
    main()
