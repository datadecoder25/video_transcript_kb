import chromadb
import numpy as np

from transcripts.config import CHROMA_DIR

_COLLECTION_NAME = "transcripts"
_client: chromadb.ClientAPI | None = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_collection() -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=None,
    )


def upsert_chunks(chunks: list[dict], embeddings: np.ndarray) -> None:
    coll = get_collection()
    ids = [c["id"] for c in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {
            "meeting_id": c["meeting_id"],
            "kind": c["kind"],
            "start_ms": c.get("start_ms") or 0,
            "end_ms": c.get("end_ms") or 0,
            "speakers": c.get("speakers") or "",
            "chapter_headline": c.get("chapter_headline") or "",
        }
        for c in chunks
    ]
    coll.upsert(
        ids=ids,
        embeddings=embeddings.tolist(),
        documents=documents,
        metadatas=metadatas,
    )


def query(
    query_embedding: np.ndarray,
    top_k: int = 20,
    where: dict | None = None,
) -> list[dict]:
    coll = get_collection()
    kwargs: dict = {
        "query_embeddings": [query_embedding.tolist()],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where
    results = coll.query(**kwargs)

    hits = []
    for i in range(len(results["ids"][0])):
        hits.append({
            "id": results["ids"][0][i],
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return hits


def delete_meeting(meeting_id: str) -> None:
    coll = get_collection()
    coll.delete(where={"meeting_id": meeting_id})
