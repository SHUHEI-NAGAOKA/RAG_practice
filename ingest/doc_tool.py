"""文書の編集ツール（tools/doc_editor/cli.js）に操作リストを渡して適用する。

ツールは GUI と同じ core.js で操作を適用し、検証してから書き出す（エラーがあれば書き出さない）。
入力: 元の JSON・操作リスト（ref は元の番号で書いてよい。削除・合体で詰まった番号はツールが付け替える）
出力: 操作後の JSON（ファイル）と、ツールの結果（追加した要素の ref・番号の対応など）
"""

import json
import subprocess
from pathlib import Path

from .config import TOOL_CLI


class DocToolError(RuntimeError):
    pass


def apply_ops(src: Path, dst: Path, ops: list[dict], ops_path: Path) -> dict:
    """操作リストをツールで適用する。

    入力: 元の JSON・書き出し先・操作リスト・操作リストの保存先（記録として残す）
    出力: ツールの結果 {results, mapping, added, ops, warnings_before, warnings_after}
    """
    ops_path.write_text(json.dumps(ops, ensure_ascii=False, indent=1), encoding="utf-8")
    report_path = ops_path.with_name(ops_path.stem + "_report.json")
    proc = subprocess.run(
        ["node", str(TOOL_CLI), str(src), str(dst), str(ops_path), "--report", str(report_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise DocToolError(f"ツールでの適用に失敗: {proc.stderr.strip() or proc.stdout.strip()}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["stdout"] = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return report
