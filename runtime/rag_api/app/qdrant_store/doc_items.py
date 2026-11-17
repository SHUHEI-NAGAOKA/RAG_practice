"""文書要素のコレクション（既定 rag_doc_items、ベクトルなし）を読み、文書の木をたどる。

payload の項目（contract/qdrant_schema.json）:
  document_id, self_ref（"#/texts/12" など）, label, text, level, parent_ref, children_refs

チャンクの source_refs から親の見出しをたどり、その節の本文をまとめて取るのに使う。
"""

from qdrant_client import QdrantClient, models

from ..config import settings

COLLECTION = settings.doc_items_collection


class DocItems:
    """1回のリクエストの中で、要素を self_ref で取り出す（取ったものは覚えておく）。

    入力: Qdrant のクライアント・文書ID
    使い方: get(ref) で1件、fetch(refs) でまとめて先読み
    """

    def __init__(self, client: QdrantClient, document_id: str):
        self.client = client
        self.document_id = document_id
        self.cache: dict[str, dict] = {}

    def fetch(self, refs: list[str]) -> None:
        """入力: self_ref のリスト / 出力: なし（self.cache に payload を入れる）"""
        need = [r for r in dict.fromkeys(refs) if r not in self.cache]
        if not need:
            return
        points, _ = self.client.scroll(
            collection_name=COLLECTION,
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
        """入力: self_ref / 出力: その要素の payload（無ければ空の dict）"""
        self.fetch([ref])
        return self.cache[ref]


def is_heading(item: dict) -> bool:
    """入力: 要素の payload / 出力: 見出し（section_header・title）かどうか"""
    return item.get("label") in ("section_header", "title")


def heading_ancestors(items: DocItems, ref: str) -> list[str]:
    """入力: 要素の self_ref / 出力: 親をたどった見出しの self_ref（近い順。グループは通り抜ける）"""
    result = []
    item = items.get(ref)
    while item.get("parent_ref"):
        pref = item["parent_ref"]
        item = items.get(pref)
        if is_heading(item):
            result.append(pref)
    return result


def collect_text(items: DocItems, ref: str) -> str:
    """入力: 見出しの self_ref / 出力: その見出しと子孫の本文を文書順につなげた文字列
    （見出しは【】で囲む。階層ごとにまとめて Qdrant に問い合わせる）"""
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
    """入力: チャンクの元の要素・節の見出しの文字 / 出力: 親をたどって見つけたその節の self_ref"""
    for ref in heading_ancestors(items, source_ref):
        if (items.get(ref).get("text") or "").strip() == title.strip():
            return ref
    return None
