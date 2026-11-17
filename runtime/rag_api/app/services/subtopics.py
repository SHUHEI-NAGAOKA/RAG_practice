"""② 選んだ見出し（複数可） → 配下のチャンクをすべて数え、1段下の見出しを話題にする。"""

from qdrant_client import QdrantClient

from ..qdrant_store import chunks
from ..schemas import HeadingNode, SubtopicGroup, SubtopicsResponse


def outermost(paths: list[list[str]]) -> list[list[str]]:
    """入力: 選んだ見出しの経路 / 出力: 重複と、ほかの選択の配下に入っている選択を除いた経路
    （親を選んでいれば子は不要）"""
    result = []
    for p in paths:
        if p in result:
            continue
        if any(len(o) < len(p) and p[: len(o)] == o for o in paths):
            continue
        result.append(p)
    return result


def subtopic_group(client: QdrantClient, path: list[str]) -> SubtopicGroup:
    """入力: 見出しの経路1つ / 出力: その配下の1段下の見出しとチャンク数（文書順）
    直下に本文がある場合は「（全体）」の話題を先頭に置く（配下すべてと同じ範囲）。"""
    points = chunks.scroll_under(client, [path])
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
        topics.append(HeadingNode(path=path, title=f"{path[-1]}（全体）", chunk_count=len(points)))
    topics += [HeadingNode(path=path + [t], title=t, chunk_count=groups[t]) for t in order]
    return SubtopicGroup(path=path, title=path[-1], total=len(points), topics=topics)


def subtopics(client: QdrantClient, paths: list[list[str]]) -> SubtopicsResponse:
    """入力: ①で選んだ見出しの経路 / 出力: 経路ごとの1段下の話題と、全体のチャンク数"""
    paths = outermost(paths)
    groups = [subtopic_group(client, p) for p in paths]
    return SubtopicsResponse(paths=paths, total=chunks.count_under(client, paths), groups=groups)
