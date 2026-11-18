"""runtime/（RAG 実行環境）が、runtime の外を参照していないかを確かめる。

本番では runtime/ だけを切り出して使うため、次を禁止する:
  - Python で ingest・evaluation・src・tools・legacy を import する
  - Dockerfile・compose.yaml でビルドやボリュームに runtime の外のパスを使う
    （例外: .env の EVAL_HOST_DIR は開発機だけの設定なので .env は対象外。.env.example は対象）
入力: runtime/ 以下のファイル / 出力: 問題の一覧（無ければ PASS）
実行: .venv/bin/python tests/test_runtime_isolation.py（pytest でも可）
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
FORBIDDEN_IMPORTS = re.compile(r"^\s*(from|import)\s+(ingest|evaluation|src|tools|legacy)\b", re.M)
OUTSIDE_PATH = re.compile(r"(\.\./|/Users/|RAG_practice/(ingest|src|tools|data|evaluation))")


def problems() -> list[str]:
    found = []
    for p in RUNTIME.rglob("*"):
        if not p.is_file() or "snapshots" in p.parts or p.name == ".env" or "__pycache__" in p.parts:
            continue
        # bundle/build・bundle/dist はデータ・モデルの写し（大きい生成物）なので見ない
        if "bundle" in p.parts and ({"build", "dist"} & set(p.parts)):
            continue
        rel = p.relative_to(ROOT)
        text = p.read_text(encoding="utf-8", errors="ignore")
        if p.suffix == ".py" and FORBIDDEN_IMPORTS.search(text):
            found.append(f"{rel}: runtime の外のモジュールを import しています")
        if p.name in ("Dockerfile", "compose.yaml", ".env.example") or p.suffix in (".sh", ".py", ".js", ".html"):
            for line in text.splitlines():
                if OUTSIDE_PATH.search(line) and not line.lstrip().startswith(("#", "//")):
                    found.append(f"{rel}: runtime の外のパス: {line.strip()[:80]}")
    return found


def test_runtime_isolation():
    assert problems() == []


if __name__ == "__main__":
    ps = problems()
    for x in ps:
        print("FAIL", x)
    print("PASS runtime/ は外を参照していません" if not ps else f"{len(ps)} 件の問題")
    sys.exit(1 if ps else 0)
