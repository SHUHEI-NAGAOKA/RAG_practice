"""パイプラインの入口: 工程を順に実行する。

実行（リポジトリのルートで）:
  .venv/bin/python -m ingest.run --pdf data/input/那須烏山市総合計画.pdf
  主なオプション:
    --from s03 --to s07      指定した範囲の工程だけ実行
    --only s08               1つの工程だけ実行
    --force                  出力が既にあっても作り直す（Claude CLI の結果も）
    --qdrant-url URL         登録先（本番へ直接登録するとき）
    --recreate               s08 で Qdrant のコレクションを作り直す
    --index-only             s08 で登録はせず、既存のコレクションに約束の索引だけを足す（BM25 の全文索引など）
    --no-nest / --no-summaries   任意の工程を使わない
    --sample-pages N など     少量で試す（Claude CLI の利用量を抑える）
    --claude-model sonnet    Claude CLI のモデル
入力: PDF / 出力: data/pipeline/<文書名>/ の各工程のファイル、Qdrant の2つのコレクション
"""

import argparse
import json
import sys
import time

from .config import PipelineConfig
from .steps import (
    enabled, s01_convert_pdf, s02_outline_md, s03_structure, s04_nest, s05_figures, s06_summaries, s07_chunk,
    s08_register,
)

# 工程の順番（ここを並べ替えれば実行順が変わる）
STEPS = [s01_convert_pdf, s02_outline_md, s03_structure, s04_nest, s05_figures, s06_summaries, s07_chunk, s08_register]


def parse_args() -> tuple[PipelineConfig, argparse.Namespace]:
    """入力: コマンドライン引数 / 出力: (設定, 引数)"""
    ap = argparse.ArgumentParser(description="PDF → Qdrant 登録パイプライン")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--name", default="", help="文書名（既定は PDF のファイル名）")
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("--recreate", action="store_true")
    ap.add_argument("--index-only", action="store_true")
    ap.add_argument("--no-nest", action="store_true")
    ap.add_argument("--no-summaries", action="store_true")
    ap.add_argument("--claude-model", default=None)
    ap.add_argument("--doc-title", default="", help="s04: 文書タイトルの文字を書き換える")
    ap.add_argument("--doc-note", default="", help="s04: タイトルの直後に足す説明の文")
    for k in ("pages", "items", "figures", "sections"):
        ap.add_argument(f"--sample-{k}", type=int, default=0)
    a = ap.parse_args()
    cfg = PipelineConfig(
        pdf=a.pdf, name=a.name, force=a.force, qdrant_url=a.qdrant_url, recreate=a.recreate, index_only=a.index_only,
        enable_nest=not a.no_nest, enable_summaries=not a.no_summaries,
        sample_pages=a.sample_pages, sample_items=a.sample_items,
        sample_figures=a.sample_figures, sample_sections=a.sample_sections,
        doc_title=a.doc_title, doc_note=a.doc_note,
    )
    if a.claude_model:
        cfg.claude_model = a.claude_model
    return cfg, a


def select_steps(a: argparse.Namespace) -> list:
    """入力: 引数 / 出力: 実行する工程のモジュール（--only / --from / --to で絞る）"""
    names = [s.NAME for s in STEPS]
    if a.only:
        return [STEPS[names.index(a.only)]]
    i = names.index(a.start) if a.start else 0
    j = names.index(a.end) if a.end else len(STEPS) - 1
    return STEPS[i: j + 1]


def resume_command() -> str:
    """入力: なし / 出力: 今の実行と同じ引数で --force を外したコマンド（途中から再開する用）"""
    import shlex
    args = [x for x in sys.argv[1:] if x != "--force"]
    return ".venv/bin/python -m ingest.run " + " ".join(shlex.quote(x) for x in args)


def write_progress(cfg: PipelineConfig, rows: list[dict], note: str = "") -> None:
    """入力: 設定・工程ごとの状態 / 出力: <出力フォルダ>/PROGRESS.md（工程が進むたびに書き直す）
    トークン切れなどで止まっても、このファイルを見れば続きから再開できるようにする。"""
    lines = [
        f"# パイプラインの進捗: {cfg.name}",
        "",
        f"- 更新: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 入力: {cfg.pdf}",
        "",
        "| 工程 | 状態 | 開始 | 終了 | 秒 | 結果 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['step']} {r['title']} | {r['status']} | {r.get('start', '')} | {r.get('end', '')} | "
                     f"{r.get('seconds', '')} | {r.get('result', '')} |")
    lines += [
        "",
        "## 再開のしかた",
        "止まった工程から、次のコマンドで続ける（済んだ工程は出力があるので飛ばされる。",
        "Claude CLI の返答も 02_outline_parts/・03_ops_parts/・05_figures.jsonl・06_summaries.jsonl に",
        "少しずつ保存してあり、済んだ分は呼び直さない）。**--force は付けない**（付けると保存した返答を捨てて作り直す）。",
        "",
        "```bash",
        resume_command(),
        "```",
    ]
    if note:
        lines += ["", "## 止まった理由", "```", note[-3000:], "```"]
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    (cfg.out_dir / "PROGRESS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg, a = parse_args()
    summary = []
    steps = select_steps(a)
    rows = [{"step": s.NAME, "title": s.TITLE, "status": "待ち"} for s in steps]
    now = lambda: time.strftime("%H:%M:%S")
    write_progress(cfg, rows)
    for row, step in zip(rows, steps):
        label = f"[{step.NAME}] {step.TITLE}"
        if not enabled(cfg, step.NAME):
            print(f"{label} … 設定でオフのため飛ばします")
            row["status"] = "オフ"
            write_progress(cfg, rows)
            continue
        outs = step.outputs(cfg)
        if outs and all(p.exists() for p in outs) and not cfg.force:
            print(f"{label} … 出力があるため飛ばします（作り直すなら --force）")
            row["status"] = "済み（前回まで）"
            write_progress(cfg, rows)
            continue
        print(f"{label} … 開始{'（Claude CLI を使います）' if step.USES_CLAUDE else ''}", flush=True)
        row.update(status="実行中", start=now())
        write_progress(cfg, rows)
        started = time.time()
        try:
            result = step.run(cfg)
        except BaseException as e:  # トークン切れ・中断なども記録してから止める
            import traceback
            row.update(status="失敗（ここから再開）", end=now())
            write_progress(cfg, rows, note=traceback.format_exc())
            raise
        sec = round(time.time() - started, 1)
        print(f"{label} … 完了 {sec}秒 {json.dumps(result, ensure_ascii=False)}", flush=True)
        row.update(status="完了", end=now(), seconds=sec, result=json.dumps(result, ensure_ascii=False).replace("|", "/"))
        write_progress(cfg, rows)
        summary.append({"step": step.NAME, "seconds": sec, **result})
    log = cfg.logs_dir / f"run_{time.strftime('%Y%m%d_%H%M%S')}.json"
    log.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("記録:", log)


if __name__ == "__main__":
    main()
