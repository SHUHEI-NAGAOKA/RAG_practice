"""Claude Code の CLI（`claude -p`）を呼ぶ共通処理。Claude の API は使わない。

入力: 指示文（prompt）・返答の形（JSON スキーマ）・記録名
出力: スキーマどおりの dict（CLI の structured_output）

- API キーで課金される経路を使わないよう、CLI を呼ぶときは ANTHROPIC_API_KEY などの
  API 用の環境変数を外す（CLI はログイン済みの Claude Code の契約で動く）
- 指示文は標準入力で渡す（長くてもよい）
- Claude が使えるツールは Read だけ（PDF・画像・JSON などプロジェクト内のファイルを読ませる）
- 呼び出しごとに logs/<記録名>.json に指示文・返答・所要時間・利用量を残す
"""

import json
import os
import subprocess
import time
from pathlib import Path

from .config import ROOT, PipelineConfig

# CLI を API 課金で動かしてしまう環境変数（呼び出し時に必ず外す）
API_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def cli_env() -> dict:
    """入力: なし / 出力: API 用の環境変数を除いた環境（CLI に渡す）"""
    return {k: v for k, v in os.environ.items() if k not in API_ENV_VARS}


class ClaudeCliError(RuntimeError):
    pass


def run_json(cfg: PipelineConfig, prompt: str, schema: dict, log_name: str) -> dict:
    """Claude CLI に1回問い合わせ、スキーマどおりの JSON を受け取る。

    入力: 設定・指示文・返答の JSON スキーマ・記録名（ファイル名に使う）
    出力: 返答の dict（失敗が cfg.claude_retries 回続いたら ClaudeCliError）
    """
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--allowedTools", "Read",
        "--disallowedTools", "Bash", "Write", "Edit",
        "--no-session-persistence",
    ]
    if cfg.claude_model:
        cmd += ["--model", cfg.claude_model]

    last_error = ""
    for attempt in range(1, cfg.claude_retries + 2):
        started = time.time()
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, cwd=ROOT, timeout=cfg.claude_timeout, env=cli_env(),
            )
        except subprocess.TimeoutExpired:
            last_error = f"{cfg.claude_timeout} 秒で終わりませんでした"
            continue
        seconds = round(time.time() - started, 1)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            last_error = f"CLI の出力が JSON ではありません（終了コード {proc.returncode}）: {proc.stderr[-500:] or proc.stdout[-500:]}"
            continue
        result = out.get("structured_output")
        _write_log(cfg.logs_dir / f"{log_name}.json", prompt, out, seconds, attempt)
        if out.get("is_error") or not isinstance(result, dict):
            last_error = f"返答がスキーマどおりではありません: {str(out.get('result'))[:300]}"
            continue
        return result
    raise ClaudeCliError(f"{log_name}: {last_error}")


def _write_log(path: Path, prompt: str, out: dict, seconds: float, attempt: int) -> None:
    """入力: 記録先・指示文・CLI の出力・秒数・何回目か / 出力: なし（JSON で保存）"""
    path.write_text(json.dumps({
        "attempt": attempt,
        "seconds": seconds,
        "cost_usd": out.get("total_cost_usd"),
        "num_turns": out.get("num_turns"),
        "is_error": out.get("is_error"),
        "prompt": prompt,
        "structured_output": out.get("structured_output"),
        "result": out.get("result"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def load_prompt(name: str, **values) -> str:
    """入力: ingest/prompts/<name>.md と、埋め込む値 / 出力: {キー} を置き換えた指示文"""
    from .config import PROMPTS_DIR
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def rel(path: Path) -> str:
    """入力: パス / 出力: リポジトリのルートからの相対パス（Claude に読ませるファイルの指定に使う）"""
    return str(Path(path).resolve().relative_to(ROOT))
