import json

from mcp.server.fastmcp import FastMCP

from transcripts.config import DB_PATH
from transcripts.store.sqlite_store import connect
from transcripts.retrieval import (
    search as hybrid_search,
    get_meeting as _get_meeting,
    get_excerpt as _get_excerpt,
)

mcp = FastMCP("transcripts")


@mcp.tool()
def search_meetings(
    query: str,
    top_k: int = 10,
    client: str | None = None,
    kind: str | None = None,
) -> str:
    """Search across all meeting transcripts using hybrid vector + full-text retrieval.

    Use this to find meetings and transcript passages matching a query.
    Returns ranked results with meeting context, relevance scores, and text snippets.

    Args:
        query: Natural language search query (e.g. "buy box strategy", "lifetime value").
        top_k: Number of results to return (default 10).
        client: Optional client name filter to scope results to a specific client.
        kind: Optional chunk kind filter ("chapter" or "utterance").
    """
    filters = {}
    if client:
        filters["meeting_id"] = client  # Will be ignored; build where clause
    if kind:
        filters["kind"] = kind

    where = filters if filters else None
    # Client filtering is on meeting_id metadata; for client name we need
    # to filter post-hoc since Chroma metadata stores meeting_id not client.
    hits = hybrid_search(query, top_k=top_k * 2 if client else top_k, filters=where if kind and not client else None)

    results = []
    for hit in hits:
        meeting = _get_meeting(hit["meeting_id"])
        if client and client.lower() not in (meeting.get("client") or "").lower():
            continue
        results.append({
            "meeting_id": hit["meeting_id"],
            "client": meeting.get("client") or "",
            "topic": meeting.get("topic") or "",
            "snippet": hit["text"][:200],
            "score": round(hit["score"], 4),
            "source": hit["source"],
            "start_ms": hit["metadata"].get("start_ms", 0),
            "end_ms": hit["metadata"].get("end_ms", 0),
        })
        if len(results) >= top_k:
            break

    return json.dumps(results, indent=2)


@mcp.tool()
def get_meeting(meeting_id: str) -> str:
    """Get full metadata for a specific meeting, including chapters and highlights.

    Use this after search_meetings to get detailed context about a specific meeting.
    Returns meeting info (client, topic, duration, speakers), chapter summaries,
    and auto-detected highlights.

    Args:
        meeting_id: The meeting ID returned from search_meetings.
    """
    result = _get_meeting(meeting_id)
    if not result:
        return json.dumps({"error": f"Meeting {meeting_id} not found"})
    return json.dumps(result, indent=2)


@mcp.tool()
def get_excerpt(meeting_id: str, start_ms: int, end_ms: int) -> str:
    """Get the speaker-labeled transcript excerpt for a specific time window.

    Use this to read the actual conversation around a search hit.
    Returns utterances with speaker labels, timestamps, and confidence scores.

    Args:
        meeting_id: The meeting ID.
        start_ms: Start of the time window in milliseconds.
        end_ms: End of the time window in milliseconds.
    """
    utterances = _get_excerpt(meeting_id, start_ms, end_ms)
    if not utterances:
        return json.dumps({"error": "No utterances found in that window"})
    return json.dumps(utterances, indent=2)


@mcp.tool()
def list_meetings(
    client: str | None = None,
    topic_contains: str | None = None,
    limit: int = 50,
) -> str:
    """List meetings in the corpus, optionally filtered by client or topic keyword.

    Use this for discovery: browsing what meetings exist, finding all meetings
    for a specific client, or searching for meetings by topic keyword.

    Args:
        client: Optional client name to filter by (case-insensitive partial match).
        topic_contains: Optional keyword to search within topic names.
        limit: Maximum number of meetings to return (default 50).
    """
    conn = connect(DB_PATH)
    query = """SELECT id, filename, client, topic, audio_duration_sec,
                      num_speakers, num_utterances, ingested_at
               FROM meetings WHERE 1=1"""
    params: list = []

    if client:
        query += " AND client LIKE ?"
        params.append(f"%{client}%")
    if topic_contains:
        query += " AND topic LIKE ?"
        params.append(f"%{topic_contains}%")

    query += " ORDER BY ingested_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return json.dumps([dict(r) for r in rows], indent=2)


@mcp.tool()
def list_topics(
    parent_id: int | None = None,
    limit: int = 50,
) -> str:
    """List discovered topics in the transcript corpus, optionally filtered by parent topic.

    Use this to answer "what are the major themes?" or to explore the topic hierarchy.
    Topics are discovered via clustering and may have auto-generated or human-curated names.
    Each topic includes keywords and the number of transcript chunks assigned to it.

    Args:
        parent_id: Optional parent topic ID to list child topics of a specific branch.
        limit: Maximum number of topics to return (default 50).
    """
    conn = connect(DB_PATH)
    if parent_id is not None:
        rows = conn.execute(
            """SELECT t.id, t.name, t.parent_id, t.level, t.keywords_json,
                      (SELECT count(*) FROM topic_assignments ta WHERE ta.topic_id = t.id) AS chunk_count
               FROM topics t
               WHERE t.parent_id = ?
               ORDER BY chunk_count DESC
               LIMIT ?""",
            (parent_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT t.id, t.name, t.parent_id, t.level, t.keywords_json,
                      (SELECT count(*) FROM topic_assignments ta WHERE ta.topic_id = t.id) AS chunk_count
               FROM topics t
               ORDER BY chunk_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()

    results = []
    for row in rows:
        keywords = json.loads(row["keywords_json"] or "[]")
        results.append({
            "topic_id": row["id"],
            "name": row["name"],
            "parent_id": row["parent_id"],
            "level": row["level"],
            "chunk_count": row["chunk_count"],
            "top_keywords": [w for w, _ in keywords[:5]],
        })
    return json.dumps(results, indent=2)


@mcp.tool()
def get_topic(topic_id: int) -> str:
    """Get detailed information about a specific topic, including its keywords,
    representative transcript chunks, and the meetings most associated with it.

    Use this to understand what a topic is about and which meetings discuss it.

    Args:
        topic_id: The topic ID from list_topics results.
    """
    conn = connect(DB_PATH)
    row = conn.execute(
        """SELECT t.id, t.name, t.parent_id, t.level, t.keywords_json,
                  (SELECT count(*) FROM topic_assignments ta WHERE ta.topic_id = t.id) AS chunk_count
           FROM topics t WHERE t.id = ?""",
        (topic_id,),
    ).fetchone()
    if not row:
        conn.close()
        return json.dumps({"error": f"Topic {topic_id} not found"})

    keywords = json.loads(row["keywords_json"] or "[]")

    # Get meetings associated with this topic via meeting: prefix assignments
    # and chapter-based assignments (chapter-NNN -> chapters table -> meeting_id)
    meeting_rows = conn.execute(
        """SELECT m.id, m.client, m.topic, count(*) AS cnt
           FROM topic_assignments ta
           JOIN chapters c ON c.id = CAST(REPLACE(ta.chunk_id, 'chapter-', '') AS INTEGER)
           JOIN meetings m ON m.id = c.meeting_id
           WHERE ta.topic_id = ? AND ta.chunk_id LIKE 'chapter-%'
           GROUP BY m.id
           ORDER BY cnt DESC
           LIMIT 15""",
        (topic_id,),
    ).fetchall()
    conn.close()

    top_meetings = [
        {
            "meeting_id": r["id"],
            "client": r["client"] or "",
            "topic": r["topic"] or "",
            "chunks_in_topic": r["cnt"],
        }
        for r in meeting_rows
    ]

    result = {
        "topic_id": row["id"],
        "name": row["name"],
        "parent_id": row["parent_id"],
        "level": row["level"],
        "chunk_count": row["chunk_count"],
        "keywords": [{"word": w, "weight": round(s, 4)} for w, s in keywords[:10]],
        "top_meetings": top_meetings,
    }
    return json.dumps(result, indent=2)


def run():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
