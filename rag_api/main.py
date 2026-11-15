"""RAG API: Ruri で質問を Embedding → Qdrant で検索 → Ollama で回答生成。

POST /search : 検索結果のみ返す
POST /ask    : 検索結果を根拠に LLM で回答を生成して返す
階層を選んで回答するフロー:
POST /levels    : 質問で検索し、当たったチャンクの見出しから LLM が話題を作る（10件ずつ、続きも取れる）
POST /subtopics : 選んだ見出しの配下のチャンクをすべて数え、1段下の見出しを話題として返す
POST /answer    : 選んだ話題の配下のチャンクが6個未満なら全部、6個以上なら上位5個＋JSONの節の本文で回答
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models


# =====================================
# 1. 環境変数
# =====================================

QDRANT_URL = os.getenv("QDRANT_URL")
OLLAMA_URL = os.getenv("OLLAMA_URL")
COLLECTION = os.getenv("COLLECTION_NAME")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
LLM_MODEL = os.getenv("LLM_MODEL")

# 登録時（文書側「検索文書: 」）と対になる Ruri v3 の検索クエリ形式
QUERY_PREFIX = "検索クエリ: "

OLLAMA_TIMEOUT = 600  # CPU推論のため長めに設定（秒）

# 入れ子にした DoclingDocument JSON の要素（register_doc_items.py で登録。上位の節をたどる）
DOC_ITEMS_COLLECTION = os.getenv("DOC_ITEMS_COLLECTION", "rag_doc_items")

# LLM のコンテキスト長と、回答用に空けておく分（トークン）
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))
RESERVE_OUTPUT = 1024
PROMPT_MARGIN = 300  # 見出し・区切りなどの余白


# =====================================
# 2. 起動時にモデルを読み込む
# =====================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.embedding_model = SentenceTransformer(
        EMBEDDING_MODEL,
        device="cpu",
    )
    app.state.qdrant = QdrantClient(
        url=QDRANT_URL,
        timeout=30,
    )
    yield
    app.state.qdrant.close()


app = FastAPI(title="RAG API", lifespan=lifespan)


# =====================================
# 3. リクエスト / レスポンスの型
# =====================================

class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="質問文")
    top_k: int = Field(5, ge=1, le=20, description="取得するチャンク数")


class Source(BaseModel):
    source_number: int
    score: float
    document_id: str | None
    headings: list[str]
    page_numbers: list[int]
    text: str
    chunk_id: str | None = None
    source_refs: list[str] = []


class SearchResponse(BaseModel):
    question: str
    sources: list[Source]


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[Source]


SEP = " > "  # heading_paths の区切り（add_heading_paths.py と同じ）
LEVELS_PAGE = 10  # /levels で1回に見るチャンク数
MANY_CHUNKS = 6  # これ以上なら上位5チャンク＋JSONの節の本文で回答
TOP_CHUNKS = 5


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


# =====================================
# 4. 検索処理
# =====================================

def to_source(i: int, point) -> Source:
    payload = point.payload or {}
    return Source(
        source_number=i,
        score=getattr(point, "score", None) or 0.0,
        document_id=payload.get("document_id"),
        headings=payload.get("headings") or [],
        page_numbers=payload.get("page_numbers") or [],
        text=payload.get("text") or "",
        chunk_id=payload.get("chunk_id"),
        source_refs=payload.get("source_refs") or [],
    )


def paths_filter(paths: list[list[str]]) -> models.Filter:
    """どれかの見出しの配下にあるチャンク（heading_paths の完全一致）。"""
    return models.Filter(should=[
        models.FieldCondition(key="heading_paths", match=models.MatchValue(value=SEP.join(p)))
        for p in paths
    ])


def count_under(client: QdrantClient, paths: list[list[str]]) -> int:
    return client.count(COLLECTION, count_filter=paths_filter(paths), exact=True).count


def scroll_under(client: QdrantClient, paths: list[list[str]]) -> list:
    """見出しの配下のチャンクを件数の制限なくすべて取る。"""
    points, offset = [], None
    while True:
        batch, offset = client.scroll(
            COLLECTION, scroll_filter=paths_filter(paths), limit=256, offset=offset,
            with_payload=True, with_vectors=False,
        )
        points += batch
        if offset is None:
            return points


def search_chunks(
    request: Request, question: str, top_k: int,
    offset: int = 0, query_filter: models.Filter | None = None,
) -> list[Source]:
    model = request.app.state.embedding_model
    client = request.app.state.qdrant

    # 質問をEmbedding
    query_vector = model.encode(
        QUERY_PREFIX + question,
        normalize_embeddings=True,
    ).tolist()

    # Qdrantで検索
    try:
        response = client.query_points(
            collection_name=COLLECTION,
            query=query_vector,
            limit=top_k,
            offset=offset,
            query_filter=query_filter,
            with_payload=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Qdrant検索エラー: {e}")

    return [to_source(offset + i, p) for i, p in enumerate(response.points, start=1)]


# =====================================
# 4-2. Qdrant の文書要素（rag_doc_items）から節の本文を取る
# =====================================

class DocItems:
    """1回のリクエストの中で、要素を self_ref で Qdrant から取り出す（取ったものは覚えておく）。"""

    def __init__(self, client: QdrantClient, document_id: str):
        self.client = client
        self.document_id = document_id
        self.cache: dict[str, dict] = {}

    def fetch(self, refs: list[str]) -> None:
        need = [r for r in dict.fromkeys(refs) if r not in self.cache]
        if not need:
            return
        points, _ = self.client.scroll(
            collection_name=DOC_ITEMS_COLLECTION,
            scroll_filter=models.Filter(must=[
                models.FieldCondition(key="document_id", match=models.MatchValue(value=self.document_id)),
                models.FieldCondition(key="self_ref", match=models.MatchAny(any=need)),
            ]),
            limit=len(need),
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            self.cache[p.payload["self_ref"]] = p.payload
        for r in need:  # 見つからない ref は空にしておく（同じ問い合わせを繰り返さない）
            self.cache.setdefault(r, {})

    def get(self, ref: str) -> dict:
        self.fetch([ref])
        return self.cache[ref]


def is_heading(item: dict) -> bool:
    return item.get("label") in ("section_header", "title")


def heading_ancestors(items: DocItems, ref: str) -> list[str]:
    """ref から parent をたどり、見出しの要素だけを近い順に返す（グループは通り抜ける）。"""
    result = []
    item = items.get(ref)
    while item.get("parent_ref"):
        pref = item["parent_ref"]
        item = items.get(pref)
        if is_heading(item):
            result.append(pref)
    return result


def collect_text(items: DocItems, ref: str) -> str:
    """見出しの要素とその子孫の本文を文書順につなげる（階層ごとにまとめて問い合わせる）。"""
    frontier = [ref]
    while frontier:
        items.fetch(frontier)
        frontier = [c for r in frontier for c in items.cache[r].get("children_refs", [])]

    lines = []

    def walk(r: str):
        item = items.cache.get(r, {})
        text = (item.get("text") or "").strip()
        if text:
            lines.append(f"【{text}】" if is_heading(item) else text)
        for c in item.get("children_refs", []):
            walk(c)

    walk(ref)
    return "\n".join(lines)


def section_ref(items: DocItems, source_ref: str, title: str) -> str | None:
    """チャンクの要素から親をたどり、見出しの文字が title の要素（その節）を返す。"""
    for ref in heading_ancestors(items, source_ref):
        if (items.get(ref).get("text") or "").strip() == title.strip():
            return ref
    return None


def context_budget(*texts: str) -> int:
    return NUM_CTX - RESERVE_OUTPUT - PROMPT_MARGIN - sum(len(t) for t in texts)


# =====================================
# 5. 回答生成（Ollama）
# =====================================

SYSTEM_PROMPT = (
    "あなたは行政文書に基づいて質問に答えるアシスタントです。"
    "必ず与えられた【資料】の内容だけを根拠に、日本語で回答してください。"
    "根拠にした資料は［資料1］のように番号で示してください。"
    "資料に答えが無い場合は「資料からは分かりません」と答えてください。"
)


def build_context(sources: list[Source]) -> str:
    blocks = []
    for s in sources:
        heading = " > ".join(s.headings) if s.headings else "（見出しなし）"
        blocks.append(
            f"［資料{s.source_number}］見出し: {heading} / ページ: {s.page_numbers}\n{s.text}"
        )
    return "\n\n".join(blocks)


def generate_answer(question: str, sources: list[Source]) -> str:
    user_prompt = f"【資料】\n{build_context(sources)}\n\n【質問】\n{question}"

    try:
        res = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            },
            timeout=OLLAMA_TIMEOUT,
        )
        res.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Ollamaエラー: {e}")

    return res.json()["message"]["content"]


def chat(system: str, user: str, schema: dict | None = None) -> tuple[str, int | None]:
    """Ollama に問い合わせる。schema を渡すとその形の JSON で返させる。"""
    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_ctx": NUM_CTX},
    }
    if schema:
        body["format"] = schema
    try:
        res = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=OLLAMA_TIMEOUT)
        res.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Ollamaエラー: {e}")
    data = res.json()
    return data["message"]["content"], data.get("prompt_eval_count")


LEVEL_TOPICS_SYSTEM = (
    "あなたは行政文書の調査を手伝うアシスタントです。"
    "質問に関係しそうな文書の見出しの一覧（番号つき、> は階層、（ ）内はその範囲の資料の数）が与えられます。"
    "見出しをまとめて、質問者が調べたい話題の候補を3〜6個作ってください。"
    "title は見出しの言葉や番号（「４」「（１）」「Ⅱ」など）をそのまま使わず、"
    "一般の人が一目で内容が分かる平易な言葉で15文字程度にしてください。"
    "description はその話題で何が分かるかを30文字程度で書いてください。"
    "node には、その話題を調べるのにちょうどよい範囲の見出しの番号を1つ書いてください。"
    "広い話題なら上の階層、具体的な話題なら下の階層の番号を選んでください。"
    "同じ番号を複数の話題に使わないでください。"
)
LEVEL_TOPICS_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "node": {"type": "integer"},
                },
                "required": ["title", "description", "node"],
            },
        }
    },
    "required": ["topics"],
}


def parse_topics(text: str) -> list[dict]:
    try:
        value = json.loads(text).get("topics", [])
        return [t for t in value if isinstance(t, dict)] if isinstance(value, list) else []
    except (json.JSONDecodeError, AttributeError):
        return []


ANSWER_SYSTEM = SYSTEM_PROMPT + (
    "ユーザーが選んだ話題が複数ある場合は、話題ごとに見出しを付けて答えてください。"
)


# =====================================
# 6. API
# =====================================

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
def search(body: QuestionRequest, request: Request):
    sources = search_chunks(request, body.question, body.top_k)
    return SearchResponse(question=body.question, sources=sources)


@app.post("/ask", response_model=AskResponse)
def ask(body: QuestionRequest, request: Request):
    sources = search_chunks(request, body.question, body.top_k)
    answer = generate_answer(body.question, sources)
    return AskResponse(question=body.question, answer=answer, sources=sources)


@app.post("/levels", response_model=LevelsResponse)
def levels(body: LevelsRequest, request: Request):
    """① 質問で検索し、当たったチャンクの見出しの経路だけを返す（LLM は使わない）。"""
    client = request.app.state.qdrant
    sources = search_chunks(request, body.question, LEVELS_PAGE + 1, offset=body.offset)
    has_more = len(sources) > LEVELS_PAGE
    sources = sources[:LEVELS_PAGE]

    counts: dict[str, int] = {}
    hits, seen = [], set()
    for s in sources:
        key = SEP.join(s.headings)
        if key in seen:  # 同じ経路のチャンクは1つにまとめる
            continue
        seen.add(key)
        nodes = []
        for d in range(1, len(s.headings)):  # 0 は文書タイトル（全体）なので除く
            path = s.headings[: d + 1]
            k = SEP.join(path)
            if k not in counts:
                counts[k] = count_under(client, [path])
            nodes.append(HeadingNode(path=path, title=path[-1], chunk_count=counts[k]))
        if nodes:
            hits.append(LevelHit(rank=s.source_number, score=s.score, nodes=nodes))

    # 見出しを重複なしで番号つきの一覧にし、LLM に話題を作らせる（本文は渡さない）
    unique: list[HeadingNode] = []
    for h in hits:
        for n in h.nodes:
            if all(u.path != n.path for u in unique):
                unique.append(n)
    topics, tokens = [], None
    if unique:
        listing = "\n".join(
            f"[{i}] {SEP.join(n.path[1:])}（{n.chunk_count}）" for i, n in enumerate(unique, start=1)
        )
        content, tokens = chat(
            LEVEL_TOPICS_SYSTEM,
            f"【見出しの一覧】\n{listing}\n\n【質問】\n{body.question}",
            LEVEL_TOPICS_SCHEMA,
        )
        used = set()
        for t in parse_topics(content):
            i = t.get("node")
            title = str(t.get("title", "")).strip()
            # 一覧にない番号・重複した番号の話題は捨てる
            if not isinstance(i, int) or not 1 <= i <= len(unique) or i in used or not title:
                continue
            used.add(i)
            topics.append(LevelTopic(
                title=title, description=str(t.get("description", "")).strip(), node=unique[i - 1],
            ))
    return LevelsResponse(
        question=body.question, topics=topics, hits=hits,
        next_offset=body.offset + LEVELS_PAGE, has_more=has_more, prompt_tokens=tokens,
    )


@app.post("/subtopics", response_model=SubtopicsResponse)
def subtopics(body: SubtopicsRequest, request: Request):
    """② 選んだ見出し（複数可）の配下のチャンクをすべて取り、それぞれ1段下の見出しを話題にする。"""
    client = request.app.state.qdrant
    paths = outermost(body.paths)
    groups = [subtopic_group(client, p) for p in paths]
    return SubtopicsResponse(paths=paths, total=count_under(client, paths), groups=groups)


def outermost(paths: list[list[str]]) -> list[list[str]]:
    """重複と、ほかの選択の配下に入っている選択を除く（親を選んでいれば子は不要）。"""
    result = []
    for p in paths:
        if p in result:
            continue
        if any(len(o) < len(p) and p[: len(o)] == o for o in paths):
            continue
        result.append(p)
    return result


def subtopic_group(client: QdrantClient, path: list[str]) -> SubtopicGroup:
    points = scroll_under(client, [path])
    depth = len(path)
    groups: dict[str, int] = {}
    order: list[str] = []
    direct = 0  # 選んだ見出しの直下の本文（下位の見出しがないチャンク）
    for p in sorted(points, key=lambda x: x.payload.get("chunk_id") or ""):  # 文書順
        h = p.payload.get("headings") or []
        if len(h) <= depth:
            direct += 1
            continue
        if h[depth] not in groups:
            groups[h[depth]] = 0
            order.append(h[depth])
        groups[h[depth]] += 1
    topics = []
    if direct:
        # 直下の本文だけを指す経路はないので、見出しそのものを話題にする（配下すべてと同じ）
        topics.append(HeadingNode(path=path, title=f"{path[-1]}（全体）", chunk_count=len(points)))
    topics += [HeadingNode(path=path + [t], title=t, chunk_count=groups[t]) for t in order]
    return SubtopicGroup(path=path, title=path[-1], total=len(points), topics=topics)


@app.post("/answer", response_model=AnswerResponse)
def answer(body: AnswerRequest, request: Request):
    """③ 選んだ話題の配下のチャンク数で、渡す資料を変えて回答する。"""
    client = request.app.state.qdrant
    total = count_under(client, body.paths)
    question = body.question
    budget = context_budget(ANSWER_SYSTEM, question)
    blocks, sections = [], []

    if total < MANY_CHUNKS:
        # 6個未満: 配下のチャンクをすべて渡す（文書順）
        mode = "all"
        points = sorted(scroll_under(client, body.paths), key=lambda x: x.payload.get("chunk_id") or "")
        sources = [to_source(i, p) for i, p in enumerate(points, start=1)]
    else:
        # 6個以上: 質問に近い上位5チャンク（選んだ話題の範囲で検索）
        mode = "top5+json"
        sources = search_chunks(request, question, TOP_CHUNKS, query_filter=paths_filter(body.paths))

    used = 0
    for s in sources:
        heading = SEP.join(s.headings) if s.headings else "（見出しなし）"
        block = f"［資料{s.source_number}］見出し: {heading} / ページ: {s.page_numbers}\n{s.text}"
        if blocks and used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)

    if mode == "top5+json":
        # 選んだ話題の節の本文を、JSON（rag_doc_items）から取って追加する
        items_by_doc: dict[str, DocItems] = {}
        for path in body.paths:
            pts = scroll_under(client, [path])[:1]
            if not pts:
                continue
            src = to_source(0, pts[0])
            items = items_by_doc.setdefault(src.document_id, DocItems(client, src.document_id))
            ref = section_ref(items, src.source_refs[0], path[-1]) if src.source_refs else None
            if not ref:
                continue
            text = collect_text(items, ref)
            header = f"［節: {path[-1]}］見出し: {SEP.join(path)}（文書の該当する節の全文）\n"
            room = budget - used - len(header)
            if room <= 0:
                sections.append(JsonSection(title=path[-1], chars=0, truncated=True))
                continue
            truncated = len(text) > room
            text = text[:room]
            blocks.append(header + text)
            used += len(header) + len(text)
            sections.append(JsonSection(title=path[-1], chars=len(text), truncated=truncated))

    content, tokens = chat(
        ANSWER_SYSTEM, f"【資料】\n{chr(10).join(blocks)}\n\n【質問】\n{question}"
    )
    return AnswerResponse(
        question=question, answer=content, total_chunks=total, mode=mode,
        sources=sources, json_sections=sections, contexts=blocks,
        prompt_tokens=tokens, num_ctx=NUM_CTX,
    )
