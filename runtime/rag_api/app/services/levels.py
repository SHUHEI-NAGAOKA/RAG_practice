"""① 質問 → 当たったチャンクの見出しの経路と、LLM が作る分かりやすい話題。

流れ:
  1. 質問で検索（10件＋続きがあるかの確認用に1件）
  2. 当たったチャンクの見出しの経路を、段ごとの見出し（HeadingNode）に分ける。配下のチャンク数も数える
  3. 見出しを重複なしの番号付き一覧にし、LLM に「話題名・説明・どの見出しか」を JSON で作らせる
"""

import json

from qdrant_client import QdrantClient

from ..config import settings
from ..embedding import QueryEmbedder
from ..llm import chat
from ..prompts import LEVEL_TOPICS_SCHEMA, LEVEL_TOPICS_SYSTEM
from ..qdrant_store import chunks
from ..schemas import HeadingNode, LevelHit, LevelsResponse, LevelTopic
from .search import search_chunks

SEP = settings.heading_sep


def parse_topics(text: str) -> list[dict]:
    """入力: LLM の返答（JSON 文字列） / 出力: 話題の dict のリスト（壊れていれば空）"""
    try:
        value = json.loads(text).get("topics", [])
        return [t for t in value if isinstance(t, dict)] if isinstance(value, list) else []
    except (json.JSONDecodeError, AttributeError):
        return []


def build_hits(client: QdrantClient, sources) -> list[LevelHit]:
    """入力: 検索で当たったチャンク / 出力: チャンクごとの見出しの経路（同じ経路は1つにまとめる）"""
    counts: dict[str, int] = {}
    hits, seen = [], set()
    for s in sources:
        key = SEP.join(s.headings)
        if key in seen:
            continue
        seen.add(key)
        nodes = []
        for d in range(1, len(s.headings)):  # 0 は文書タイトル（全体）なので除く
            path = s.headings[: d + 1]
            k = SEP.join(path)
            if k not in counts:
                counts[k] = chunks.count_under(client, [path])
            nodes.append(HeadingNode(path=path, title=path[-1], chunk_count=counts[k]))
        if nodes:
            hits.append(LevelHit(rank=s.source_number, score=s.score, nodes=nodes))
    return hits


def make_topics(question: str, hits: list[LevelHit]) -> tuple[list[LevelTopic], int | None]:
    """入力: 質問・見出しの経路 / 出力: (LLM が作った話題, LLM の入力トークン数)
    LLM には本文を渡さず、見出しの一覧だけを渡す。一覧にない番号・重複した番号の話題は捨てる。"""
    unique: list[HeadingNode] = []
    for h in hits:
        for n in h.nodes:
            if all(u.path != n.path for u in unique):
                unique.append(n)
    if not unique:
        return [], None
    listing = "\n".join(
        f"[{i}] {SEP.join(n.path[1:])}（{n.chunk_count}）" for i, n in enumerate(unique, start=1)
    )
    content, tokens = chat(LEVEL_TOPICS_SYSTEM, f"【見出しの一覧】\n{listing}\n\n【質問】\n{question}", LEVEL_TOPICS_SCHEMA)
    topics, used = [], set()
    for t in parse_topics(content):
        i = t.get("node")
        title = str(t.get("title", "")).strip()
        if not isinstance(i, int) or not 1 <= i <= len(unique) or i in used or not title:
            continue
        used.add(i)
        topics.append(LevelTopic(title=title, description=str(t.get("description", "")).strip(), node=unique[i - 1]))
    return topics, tokens


def levels(embedder: QueryEmbedder, client: QdrantClient, question: str, offset: int) -> LevelsResponse:
    """入力: 質問・何件目から / 出力: 話題・見出しの経路・続きの有無（LevelsResponse）"""
    page = settings.levels_page
    sources = search_chunks(embedder, client, question, page + 1, offset=offset)
    has_more = len(sources) > page
    hits = build_hits(client, sources[:page])
    topics, tokens = make_topics(question, hits)
    return LevelsResponse(
        question=question, topics=topics, hits=hits,
        next_offset=offset + page, has_more=has_more, prompt_tokens=tokens,
    )
