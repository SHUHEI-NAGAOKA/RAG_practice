"""質問で検索する・検索結果を根拠に回答する。"""

from qdrant_client import QdrantClient, models

from ..embedding import QueryEmbedder
from ..llm import chat
from ..prompts import SYSTEM_PROMPT
from ..qdrant_store import chunks
from ..schemas import Source


def search_chunks(
    embedder: QueryEmbedder, client: QdrantClient, question: str, top_k: int,
    offset: int = 0, query_filter: models.Filter | None = None,
) -> list[Source]:
    """入力: 質問・件数・何件目から・絞り込み条件 / 出力: 類似度の高い順のチャンク（Source）"""
    return chunks.search(client, embedder.encode(question), top_k, offset, query_filter)


def build_context(sources: list[Source]) -> str:
    """入力: チャンク / 出力: LLM に渡す【資料】の文字列（［資料n］見出し・ページ・本文）"""
    blocks = []
    for s in sources:
        heading = " > ".join(s.headings) if s.headings else "（見出しなし）"
        blocks.append(f"［資料{s.source_number}］見出し: {heading} / ページ: {s.page_numbers}\n{s.text}")
    return "\n\n".join(blocks)


def answer_with_sources(question: str, sources: list[Source]) -> str:
    """入力: 質問・検索で当たったチャンク / 出力: LLM の回答（/ask 用。コンテキスト長は指定しない）"""
    content, _ = chat(SYSTEM_PROMPT, f"【資料】\n{build_context(sources)}\n\n【質問】\n{question}", use_num_ctx=False)
    return content
