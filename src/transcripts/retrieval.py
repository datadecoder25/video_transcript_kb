import re
import sqlite3

from transcripts.config import DB_PATH
from transcripts.embedder import Embedder
from transcripts.store.sqlite_store import connect
from transcripts.store.vector_store import query as vector_query

_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def _escape_fts_query(q: str) -> str:
    """Escape special FTS5 characters and wrap each token in quotes."""
    q = re.sub(r'[^\w\s]', ' ', q)
    tokens = q.split()
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens)


def _fts_search(conn: sqlite3.Connection, query: str, limit: int) -> list[dict]:
    escaped = _escape_fts_query(query)
    try:
        rows = conn.execute(
            """SELECT u.meeting_id, u.id AS utt_id, u.speaker, u.text,
                      u.start_ms, u.end_ms, bm25(utterances_fts) AS rank
               FROM utterances_fts
               JOIN utterances u ON u.id = utterances_fts.rowid
               WHERE utterances_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (escaped, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    return [
        {
            "chunk_id": f"fts-{row['utt_id']}",
            "meeting_id": row["meeting_id"],
            "text": f"{row['speaker'] or 'Unknown'}: {row['text']}",
            "bm25_rank": row["rank"],
            "metadata": {
                "meeting_id": row["meeting_id"],
                "kind": "utterance",
                "start_ms": row["start_ms"] or 0,
                "end_ms": row["end_ms"] or 0,
                "speakers": row["speaker"] or "",
            },
        }
        for row in rows
    ]


def _reciprocal_rank_fusion(
    vector_hits: list[dict],
    fts_hits: list[dict],
    k: int = 60,
) -> list[dict]:
    scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    items: dict[str, dict] = {}

    for rank, hit in enumerate(vector_hits):
        key = hit.get("id") or hit["chunk_id"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        sources.setdefault(key, set()).add("vector")
        items[key] = {
            "chunk_id": key,
            "meeting_id": hit["metadata"]["meeting_id"],
            "text": hit.get("document") or hit.get("text", ""),
            "metadata": hit["metadata"],
        }

    for rank, hit in enumerate(fts_hits):
        key = hit["chunk_id"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        sources.setdefault(key, set()).add("fts")
        if key not in items:
            items[key] = {
                "chunk_id": key,
                "meeting_id": hit["meeting_id"],
                "text": hit["text"],
                "metadata": hit["metadata"],
            }

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    results = []
    for key, score in ranked:
        item = items[key]
        src = sources[key]
        item["score"] = score
        item["source"] = "both" if len(src) > 1 else next(iter(src))
        results.append(item)
    return results


def search(
    query: str, top_k: int = 10, filters: dict | None = None
) -> list[dict]:
    """Hybrid retrieval: vector search + FTS5, merged with RRF."""
    embedder = _get_embedder()
    query_emb = embedder.embed_query(query)

    # Vector search
    vector_hits = vector_query(
        query_emb, top_k=3 * top_k, where=filters
    )

    # FTS search
    conn = connect(DB_PATH)
    fts_hits = _fts_search(conn, query, limit=3 * top_k)
    conn.close()

    merged = _reciprocal_rank_fusion(vector_hits, fts_hits)
    return merged[:top_k]


def get_meeting(meeting_id: str) -> dict:
    """Return meeting metadata + chapters + highlights (no utterances)."""
    conn = connect(DB_PATH)

    row = conn.execute(
        """SELECT id, filename, client, topic, file_mtime,
                  audio_duration_sec, audio_url, num_speakers,
                  num_utterances, overall_confidence, ingested_at
           FROM meetings WHERE id = ?""",
        (meeting_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {}

    meeting = dict(row)

    chapters = conn.execute(
        """SELECT headline, gist, summary, start_ms, end_ms
           FROM chapters WHERE meeting_id = ? ORDER BY start_ms""",
        (meeting_id,),
    ).fetchall()
    meeting["chapters"] = [dict(c) for c in chapters]

    highlights = conn.execute(
        """SELECT text, rank, count
           FROM highlights WHERE meeting_id = ? ORDER BY rank DESC""",
        (meeting_id,),
    ).fetchall()
    meeting["highlights"] = [dict(h) for h in highlights]

    conn.close()
    return meeting


def get_excerpt(
    meeting_id: str, start_ms: int, end_ms: int
) -> list[dict]:
    """Return utterances overlapping [start_ms, end_ms]."""
    conn = connect(DB_PATH)
    rows = conn.execute(
        """SELECT speaker, text, start_ms, end_ms, confidence
           FROM utterances
           WHERE meeting_id = ? AND end_ms >= ? AND start_ms <= ?
           ORDER BY start_ms""",
        (meeting_id, start_ms, end_ms),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
