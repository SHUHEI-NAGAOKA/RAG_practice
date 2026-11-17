"""Ollama（ローカル LLM）への問い合わせ。

使うモデルは settings.llm_model（.env の LLM_MODEL で 3B / 7B を切り替える）。
"""

import requests
from fastapi import HTTPException

from .config import settings


def chat(system: str, user: str, schema: dict | None = None, use_num_ctx: bool = True) -> tuple[str, int | None]:
    """Ollama の /api/chat に1往復で問い合わせる。

    入力: system（役割の指示）・user（資料と質問）・schema（JSON で返させるときの形）
          use_num_ctx（コンテキスト長 settings.num_ctx を指定するか）
    出力: (LLM の返答の文字列, LLM に入力したトークン数)
    """
    body = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    if use_num_ctx:
        body["options"] = {"num_ctx": settings.num_ctx}
    if schema:
        body["format"] = schema
    try:
        res = requests.post(f"{settings.ollama_url}/api/chat", json=body, timeout=settings.ollama_timeout)
        res.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Ollamaエラー: {e}")
    data = res.json()
    return data["message"]["content"], data.get("prompt_eval_count")
