"""③ 選んだ話題 → LLM に渡す資料を作って回答する。

資料の作り方（チャンク数で切り替える）:
  - 配下のチャンクが settings.many_chunks（6）個未満 → すべてのチャンク（文書順）           mode="all"
  - それ以上 → 選んだ範囲で質問に近い上位 settings.top_chunks（5）個
                ＋ 選んだ話題の節の本文（文書要素のコレクションから集める）               mode="top5+json"
資料の合計の長さは、LLM のコンテキスト長に収まるように切り詰める（文字数≒トークン数で近似）。
渡す前に、重なった【要約】をまとめる（context_format.dedupe_summaries。SUMMARY_DEDUP で切り替え）。
"""

from qdrant_client import QdrantClient

from ..config import settings
from ..context_format import dedupe_summaries
from ..embedding import QueryEmbedder
from ..llm import chat
from ..prompts import ANSWER_SYSTEM
from ..qdrant_store import chunks
from ..qdrant_store.doc_items import DocItems, collect_text, section_ref
from ..schemas import AnswerResponse, JsonSection, Source
from .search import search_chunks

SEP = settings.heading_sep


def context_budget(*texts: str) -> int:
    """入力: 指示文・質問など先に使う文字列 / 出力: 資料に使える残りの長さ（文字数）"""
    return settings.num_ctx - settings.reserve_output - settings.prompt_margin - sum(len(t) for t in texts)


def chunk_blocks(sources: list[Source], budget: int) -> tuple[list[str], int]:
    """入力: チャンク・使える長さ / 出力: (［資料n］のブロック, 使った長さ)
    最初の1件は必ず入れ、2件目以降は長さに収まる分だけ入れる。"""
    blocks, used = [], 0
    for s in sources:
        heading = SEP.join(s.headings) if s.headings else "（見出しなし）"
        block = f"［資料{s.source_number}］見出し: {heading} / ページ: {s.page_numbers}\n{s.text}"
        if blocks and used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
    return blocks, used


def section_blocks(client: QdrantClient, paths: list[list[str]], room_total: int) -> tuple[list[str], list[JsonSection]]:
    """入力: 選んだ話題の経路・使える長さ / 出力: (節の本文のブロック, 各節の情報)
    話題の配下のチャンク1つから元の要素をたどって節の見出しを見つけ、その節の本文を集める。"""
    blocks, sections, used = [], [], 0
    items_by_doc: dict[str, DocItems] = {}
    for path in paths:
        pts = chunks.scroll_under(client, [path])[:1]
        if not pts:
            continue
        src = chunks.to_source(0, pts[0])
        items = items_by_doc.setdefault(src.document_id, DocItems(client, src.document_id))
        ref = section_ref(items, src.source_refs[0], path[-1]) if src.source_refs else None
        if not ref:
            continue
        text = collect_text(items, ref)
        header = f"［節: {path[-1]}］見出し: {SEP.join(path)}（文書の該当する節の全文）\n"
        room = room_total - used - len(header)
        if room <= 0:
            sections.append(JsonSection(title=path[-1], chars=0, truncated=True))
            continue
        truncated = len(text) > room
        text = text[:room]
        blocks.append(header + text)
        used += len(header) + len(text)
        sections.append(JsonSection(title=path[-1], chars=len(text), truncated=truncated))
    return blocks, sections


def answer(embedder: QueryEmbedder, client: QdrantClient, question: str, paths: list[list[str]]) -> AnswerResponse:
    """入力: 質問・選んだ話題の経路 / 出力: 回答と、LLM に渡した資料（AnswerResponse）"""
    total = chunks.count_under(client, paths)
    budget = context_budget(ANSWER_SYSTEM, question)

    if total < settings.many_chunks:
        mode = "all"
        points = sorted(chunks.scroll_under(client, paths), key=lambda x: x.payload.get("chunk_id") or "")
        sources = [chunks.to_source(i, p) for i, p in enumerate(points, start=1)]
    else:
        mode = "top5+json"
        sources = search_chunks(embedder, client, question, settings.top_chunks, query_filter=chunks.paths_filter(paths))

    blocks, used = chunk_blocks(sources, budget)
    sections: list[JsonSection] = []
    if mode == "top5+json":
        more, sections = section_blocks(client, paths, budget - used)
        blocks += more
    if settings.summary_dedup:  # 重なった【要約】を「【要約S1と同じ】」にまとめる
        blocks = dedupe_summaries(blocks, settings.summary_dedup_chars)

    content, tokens = chat(ANSWER_SYSTEM, f"【資料】\n{chr(10).join(blocks)}\n\n【質問】\n{question}")
    return AnswerResponse(
        question=question, answer=content, total_chunks=total, mode=mode,
        sources=sources, json_sections=sections, contexts=blocks,
        prompt_tokens=tokens, num_ctx=settings.num_ctx,
    )
