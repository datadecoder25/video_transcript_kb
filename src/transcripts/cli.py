from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from tqdm import tqdm

from transcripts.config import DB_PATH, RAW_DIR
from transcripts.store.sqlite_store import (
    init_db,
    connect,
    insert_meeting,
    bulk_insert_utterances,
    bulk_insert_chapters,
    bulk_insert_entities,
    bulk_insert_highlights,
    bulk_insert_sentiment,
)
from transcripts.store.vector_store import get_collection, upsert_chunks, delete_meeting
from transcripts.loader import load_assemblyai_json
from transcripts.filename_parser import parse_filename
from transcripts.chunker import build_chunks

app = typer.Typer()


@app.command("init-db")
def init_db_cmd():
    """Initialize SQLite database and Chroma collection."""
    init_db(DB_PATH)
    get_collection()
    typer.echo(f"SQLite database ready at {DB_PATH}")
    typer.echo("Chroma collection ready.")


def _ingest_file(path: Path, conn, embedder) -> int:
    """Ingest a single transcript file. Returns chunk count."""
    meeting = load_assemblyai_json(path)
    parsed = parse_filename(path.name)
    meeting["client"] = parsed["client"]
    meeting["topic"] = parsed["topic"]
    meeting["file_mtime"] = datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    ).isoformat()

    mid = meeting["id"]

    # SQLite: idempotent insert (cascade delete handled inside insert_meeting)
    insert_meeting(conn, meeting)
    bulk_insert_utterances(conn, mid, meeting["utterances"])
    bulk_insert_chapters(conn, mid, meeting["chapters"])
    bulk_insert_entities(conn, mid, meeting["entities"])
    bulk_insert_highlights(conn, mid, meeting["highlights"])
    bulk_insert_sentiment(conn, mid, meeting["sentiment"])
    conn.commit()

    # Chroma: build chunks, embed, upsert
    chunks = build_chunks(meeting)
    if chunks:
        delete_meeting(mid)
        embeddings = embedder.embed_documents([c["text"] for c in chunks])
        upsert_chunks(chunks, embeddings)

    return len(chunks)


@app.command()
def ingest(
    path: Optional[Path] = typer.Argument(None, help="File or directory to ingest"),
):
    """Ingest transcript JSON(s) into SQLite and Chroma."""
    from transcripts.embedder import Embedder

    target = path or RAW_DIR
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(target.glob("*_transcribed.json"))
    else:
        typer.echo(f"Path not found: {target}", err=True)
        raise typer.Exit(1)

    if not files:
        typer.echo(f"No *_transcribed.json files found in {target}", err=True)
        raise typer.Exit(1)

    init_db(DB_PATH)
    conn = connect(DB_PATH)
    embedder = Embedder()
    total_chunks = 0

    for f in tqdm(files, desc="Ingesting"):
        total_chunks += _ingest_file(f, conn, embedder)

    conn.close()
    typer.echo(f"Ingested {len(files)} meetings, {total_chunks} chunks.")


@app.command()
def stats():
    """Print meeting, utterance, and chunk counts."""
    if not DB_PATH.exists():
        typer.echo("Database not found. Run `transcripts init-db` first.", err=True)
        raise typer.Exit(1)

    conn = connect(DB_PATH)
    meeting_count = conn.execute("SELECT count(*) FROM meetings").fetchone()[0]
    utterance_count = conn.execute("SELECT count(*) FROM utterances").fetchone()[0]
    conn.close()

    try:
        chunk_count = get_collection().count()
    except Exception:
        chunk_count = 0

    typer.echo(f"Meetings:   {meeting_count}")
    typer.echo(f"Utterances: {utterance_count}")
    typer.echo(f"Chunks:     {chunk_count}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results"),
):
    """Search transcripts using hybrid retrieval."""
    from transcripts.retrieval import search as hybrid_search, get_meeting

    hits = hybrid_search(query, top_k=top_k)
    if not hits:
        typer.echo("No results found.")
        return

    seen_meetings: dict[str, dict] = {}
    for i, hit in enumerate(hits, 1):
        mid = hit["meeting_id"]
        if mid not in seen_meetings:
            seen_meetings[mid] = get_meeting(mid)
        meeting = seen_meetings[mid]
        client = meeting.get("client") or "—"
        topic = meeting.get("topic") or "—"
        snippet = hit["text"][:200].replace("\n", " ")
        typer.echo(f"\n[{i}] score={hit['score']:.4f}  source={hit['source']}")
        typer.echo(f"    client: {client}  |  topic: {topic}")
        typer.echo(f"    {snippet}")


@app.command("fit-topics")
def fit_topics_cmd(
    min_topic_size: int = typer.Option(15, help="Minimum docs per topic"),
):
    """Fit BERTopic on chunk embeddings and store topic assignments."""
    from transcripts.topics.model import fit_topics

    typer.echo("Fitting topics (this may take a few minutes)...")
    result = fit_topics(min_topic_size=min_topic_size)
    typer.echo(f"Found {result['num_topics']} topics across {result.get('num_chapters', result.get('num_chunks', 0))} documents.")
    typer.echo(f"Outliers: {result['num_outliers']}")
    typer.echo(f"Model saved to: {result['model_path']}")
    typer.echo(f"Cluster reps saved to: {result['cluster_reps_path']}")


@app.command("list-topics")
def list_topics_cmd(
    limit: int = typer.Option(30, help="Max topics to show"),
):
    """List discovered topics with their keywords."""
    conn = connect(DB_PATH)
    rows = conn.execute(
        """SELECT t.id, t.name, t.keywords_json,
                  (SELECT count(*) FROM topic_assignments ta WHERE ta.topic_id = t.id) AS chunk_count
           FROM topics t
           ORDER BY chunk_count DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()

    if not rows:
        typer.echo("No topics found. Run `transcripts fit-topics` first.")
        return

    for row in rows:
        import json as _json
        keywords = _json.loads(row["keywords_json"] or "[]")
        kw_str = ", ".join(w for w, _ in keywords[:5])
        typer.echo(f"  [{row['id']:3d}] ({row['chunk_count']:4d} chunks) {row['name']}")
        typer.echo(f"        keywords: {kw_str}")


@app.command("label-topics")
def label_topics_cmd(
    labels_file: Path = typer.Argument(..., help="JSON file mapping topic_id -> label"),
):
    """Apply human-readable labels to topics from a JSON file."""
    import json as _json
    from transcripts.topics.labeler import apply_labels

    with open(labels_file) as f:
        labels = _json.load(f)

    updated = apply_labels(labels)
    typer.echo(f"Updated {updated} topic labels.")
