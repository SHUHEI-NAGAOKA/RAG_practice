"""パイプラインの設定（入出力のパスと工程ごとの設定）。

入力: run.py のコマンドライン引数（と環境変数 CLAUDE_MODEL）
出力: PipelineConfig（各工程は cfg.path("01_docling.json") のように出力先を得る）

工程の出力はすべて data/pipeline/<文書名>/ に番号付きで置く（途中からやり直せる）。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # リポジトリのルート
TOOL_CLI = ROOT / "tools" / "doc_editor" / "cli.js"  # 文書の編集ツール（操作リストを適用する CLI）
SCHEMA_FILE = Path(__file__).resolve().parent / "qdrant_schema.json"  # Qdrant の約束（runtime の写し）
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass
class PipelineConfig:
    pdf: Path  # 入力の PDF
    name: str = ""  # 文書名（既定は PDF のファイル名）。出力フォルダ名にも使う
    out_root: Path = ROOT / "data" / "pipeline"
    qdrant_url: str = "http://localhost:6333"  # 本番へ直接登録するときは本番の URL
    force: bool = False  # 出力が既にあっても作り直す（Claude CLI の結果も作り直す）
    recreate: bool = False  # s08: Qdrant のコレクションを消してから登録し直す

    # --- 任意の工程のオン・オフ ---
    enable_nest: bool = True  # s04 入れ子化
    enable_summaries: bool = True  # s06 要約付与

    # --- 文書の名前付け（s04） ---
    doc_title: str = ""  # 文書タイトル（label=title）の文字をこれに書き換える（例: "那須烏山市 第2次総合計画"）
    doc_note: str = ""  # タイトルの直後に足す説明の文（どの文書かを本文でも分かるようにする）

    # --- Claude CLI ---
    claude_model: str | None = os.getenv("CLAUDE_MODEL")  # 例: sonnet / opus（未指定なら CLI の既定）
    claude_timeout: int = 1800  # 1回の呼び出しの上限（秒）
    claude_retries: int = 2  # 失敗したときのやり直し回数

    # --- s01 PDF の読み取り ---
    ocr_lang: list[str] = field(default_factory=lambda: ["iso:ja"])
    images_scale: float = 1.0  # 画像の解像度倍率（1.0 = 72dpi 相当）
    convert_batch_pages: int = 60  # これより多いページの PDF は、この枚数ずつ変換してからつなぐ（大きい PDF で落ちるのを防ぐ）

    # --- s02 / s03 / s05 / s06 の分割単位 ---
    outline_pages_per_call: int = 15  # s02: 1回に読ませる PDF のページ数
    structure_items_per_call: int = 400  # s03: 1回に渡す要素の数
    figures_per_call: int = 4  # s05: 1回に説明させる図の数
    summary_sections_per_call: int = 25  # s06: 1回に要約させる節の数

    # --- 試し実行（少量で動作を確かめる）。0 なら制限なし ---
    sample_pages: int = 0  # s02 で読むページ数の上限
    sample_items: int = 0  # s03 で扱う要素数の上限
    sample_figures: int = 0  # s05 で扱う図の数の上限
    sample_sections: int = 0  # s06 で扱う節の数の上限

    # --- s07 チャンク化 ---
    tokenizer_model: str = "cl-nagoya/ruri-v3-310m"
    max_tokens: int = 512

    def __post_init__(self):
        self.pdf = Path(self.pdf)
        if not self.name:
            self.name = self.pdf.stem
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def out_dir(self) -> Path:
        """出力フォルダ data/pipeline/<文書名>/"""
        return self.out_root / self.name

    @property
    def logs_dir(self) -> Path:
        """Claude CLI・ツールの呼び出しの記録"""
        return self.out_dir / "logs"

    def path(self, filename: str) -> Path:
        """入力: ファイル名 / 出力: 出力フォルダの中のパス"""
        return self.out_dir / filename

    @property
    def artifacts_dir(self) -> Path:
        """s01 が書き出す図の画像のフォルダ"""
        return self.path("01_artifacts")
