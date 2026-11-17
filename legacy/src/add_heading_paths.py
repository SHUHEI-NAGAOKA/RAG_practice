"""登録済みチャンクの payload に heading_paths を追加する（Embedding はやり直さない）。

heading_paths: headings を先頭から順につないだもの
    ["A", "B", "C"] → ["A", "A > B", "A > B > C"]
「この見出しの配下のチャンク」を Qdrant の完全一致フィルターで取れるようにする。

実行（プロジェクトのルートで）:
    .venv/bin/python src/add_heading_paths.py
"""

from qdrant_client import QdrantClient, models

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "rag_ruri_v3_310m"
SEP = " > "


def heading_paths(headings: list[str]) -> list[str]:
    return [SEP.join(headings[: i + 1]) for i in range(len(headings))]


def main():
    client = QdrantClient(url=QDRANT_URL)
    client.create_payload_index(COLLECTION_NAME, "heading_paths", models.PayloadSchemaType.KEYWORD)

    updated, offset = 0, None
    while True:
        points, offset = client.scroll(
            COLLECTION_NAME, limit=256, offset=offset, with_payload=["headings"], with_vectors=False
        )
        for p in points:
            client.set_payload(
                COLLECTION_NAME,
                payload={"heading_paths": heading_paths(p.payload.get("headings") or [])},
                points=[p.id],
            )
            updated += 1
        if offset is None:
            break
    print("heading_paths を追加:", updated, "件")


if __name__ == "__main__":
    main()
