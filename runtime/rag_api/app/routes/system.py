"""画面のファイルと、動作確認用の /health。"""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..config import settings

router = APIRouter()


@router.get("/", include_in_schema=False)
def index():
    """入力: なし / 出力: 画面（static/index.html）"""
    return FileResponse(settings.static_dir / "index.html")


@router.get("/health")
def health():
    """入力: なし / 出力: 動作中であることと、使っている LLM のモデル名・検索方式"""
    return {"status": "ok", "llm_model": settings.llm_model, "search_mode": settings.search_mode,
            "eval_enabled": settings.eval_enabled}
