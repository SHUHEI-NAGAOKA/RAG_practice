"""パイプラインの工程（1工程1ファイル）。

各工程のモジュールは次を持つ:
  NAME        : 工程の短い名前（"s01" など）
  TITLE       : 何をするか
  USES_CLAUDE : Claude CLI を使うか
  outputs(cfg): 出力ファイルのリスト（すべてあれば、--force なしでは飛ばす）
  run(cfg)    : 実行する。出力: 結果の要約（dict）

文書 JSON は工程ごとに番号付きのファイルに書き出し、次の工程はその1つ前の JSON を読む。
任意の工程（s04 入れ子化・s06 要約）をオフにすると、その工程は飛ばして前の JSON を引き継ぐ。
"""

from pathlib import Path

from ..config import PipelineConfig

# 工程の順番（run.py の STEPS と同じ並び）
STEP_ORDER = ["s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08"]

# 文書 JSON を出す工程と、その出力ファイル（並び順＝工程の順）
DOC_OUTPUTS = [
    ("s01", "01_docling.json"),
    ("s03", "03_structured.json"),
    ("s04", "04_nested.json"),
    ("s05", "05_figures.json"),
    ("s06", "06_summary.json"),
]


def enabled(cfg: PipelineConfig, step: str) -> bool:
    """入力: 設定・工程名 / 出力: その工程を使うか（s04・s06 は設定でオフにできる）"""
    if step == "s04":
        return cfg.enable_nest
    if step == "s06":
        return cfg.enable_summaries
    return True


def input_doc(cfg: PipelineConfig, step: str) -> Path:
    """工程が読む文書 JSON を決める。

    入力: 設定・工程名（例 "s05"）
    出力: その工程より前で、使う設定になっている工程のうち最後の出力ファイル
    """
    before = [(s, f) for s, f in DOC_OUTPUTS if STEP_ORDER.index(s) < STEP_ORDER.index(step)]
    for s, f in reversed(before):
        if enabled(cfg, s):
            return cfg.path(f)
    raise ValueError(f"{step} の前に文書 JSON を出す工程がありません")


def final_doc(cfg: PipelineConfig) -> Path:
    """入力: 設定 / 出力: チャンク化・登録に使う最終の文書 JSON（使う工程のうち最後の出力）"""
    for s, f in reversed(DOC_OUTPUTS):
        if enabled(cfg, s):
            return cfg.path(f)
    raise ValueError("文書 JSON がありません")
