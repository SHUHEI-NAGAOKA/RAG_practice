"""API の入出力の型（FastAPI がこの形で受け取り・返す）。

画面（static/js/api.js）とやり取りする JSON の形はすべてここで決まる。
"""

from pydantic import BaseModel, Field


# ==========================================
# 共通: 検索で当たったチャンク
# ==========================================

class Source(BaseModel):
    """検索で当たったチャンク1件（Qdrant の payload を画面向けに整えたもの）。"""
    source_number: int  # 何番目の資料か（1 から）
    score: float  # 類似度（検索で取ったとき。範囲で取ったときは 0）
    document_id: str | None
    headings: list[str]  # 文書タイトルからこのチャンクまでの見出しの経路
    page_numbers: list[int]
    text: str
    chunk_id: str | None = None
    source_refs: list[str] = []  # チャンクの元になった文書要素（rag_doc_items の self_ref）


# ==========================================
# /search /ask
# ==========================================

class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="質問文")
    top_k: int = Field(5, ge=1, le=20, description="取得するチャンク数")


class SearchResponse(BaseModel):
    question: str
    sources: list[Source]


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[Source]


# ==========================================
# ① /levels: 質問 → 見出しの候補と話題
# ==========================================

class LevelsRequest(BaseModel):
    question: str = Field(..., min_length=1)
    offset: int = Field(0, ge=0, description="何件目から見るか（次の候補を探すとき）")


class HeadingNode(BaseModel):
    path: list[str]  # 先頭からこの見出しまでの経路
    title: str
    chunk_count: int  # この見出しの配下にあるチャンクの数（すべて）


class LevelHit(BaseModel):
    rank: int
    score: float
    nodes: list[HeadingNode]  # 浅い段から順に（文書タイトルは除く）


class LevelTopic(BaseModel):
    title: str  # 分かりやすい言葉の話題名（LLM が作る）
    description: str
    node: HeadingNode  # 話題に対応する見出し（この範囲で②に進む）


class LevelsResponse(BaseModel):
    question: str
    topics: list[LevelTopic]
    hits: list[LevelHit]  # 見出しから直接選ぶ用
    next_offset: int
    has_more: bool
    prompt_tokens: int | None


# ==========================================
# ② /subtopics: 選んだ範囲 → 1段下の話題
# ==========================================

class SubtopicsRequest(BaseModel):
    paths: list[list[str]] = Field(..., min_length=1, description="①で選んだ見出しの経路（複数可）")


class SubtopicGroup(BaseModel):
    path: list[str]
    title: str
    total: int  # この見出しの配下のチャンク数
    topics: list[HeadingNode]  # 1段下の見出し


class SubtopicsResponse(BaseModel):
    paths: list[list[str]]
    total: int  # 選んだ見出しすべての配下のチャンク数（重なりは除く）
    groups: list[SubtopicGroup]


# ==========================================
# ③ /answer: 選んだ話題 → 回答
# ==========================================

class AnswerRequest(BaseModel):
    question: str = Field(..., min_length=1)
    paths: list[list[str]] = Field(..., min_length=1, description="選んだ話題の見出しの経路")


class JsonSection(BaseModel):
    title: str
    chars: int
    truncated: bool  # 長さの上限で途中までにしたか


class AnswerResponse(BaseModel):
    question: str
    answer: str
    total_chunks: int
    mode: str  # "all"（全チャンク） / "top5+json"（上位5チャンク＋JSONの節）
    sources: list[Source]
    json_sections: list[JsonSection]
    contexts: list[str]  # LLM に実際に渡した資料（評価用）
    prompt_tokens: int | None
    num_ctx: int


# ==========================================
# 評価モード /eval/*
# ==========================================

class EvalRecord(BaseModel):
    """画面で回答まで進めた1問分の結果（collected.jsonl に1行で保存する）。"""
    run: str
    id: str
    question: str
    level_picks: list[dict] = Field(default_factory=list)     # ①で選んだ話題 {label, path}
    subtopic_picks: list[dict] = Field(default_factory=list)  # ②で選んだ話題 {title, path}
    answer: str = ""
    contexts: list[str] = Field(default_factory=list)
    mode: str = ""
    total_chunks: int = 0
    prompt_tokens: int | None = None
    seconds: float | None = None
    skipped: bool = False
