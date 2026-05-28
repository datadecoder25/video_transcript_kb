import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meetings (
    id                  TEXT PRIMARY KEY,
    filename            TEXT,
    client              TEXT,
    topic               TEXT,
    file_mtime          TEXT,
    audio_duration_sec  INTEGER,
    audio_url           TEXT,
    full_text           TEXT,
    num_speakers        INTEGER,
    num_utterances      INTEGER,
    overall_confidence  REAL,
    ingested_at         TEXT
);

CREATE TABLE IF NOT EXISTS utterances (
    id          INTEGER PRIMARY KEY,
    meeting_id  TEXT NOT NULL,
    speaker     TEXT,
    text        TEXT,
    start_ms    INTEGER,
    end_ms      INTEGER,
    confidence  REAL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY,
    meeting_id  TEXT NOT NULL,
    headline    TEXT,
    gist        TEXT,
    summary     TEXT,
    start_ms    INTEGER,
    end_ms      INTEGER,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY,
    meeting_id  TEXT NOT NULL,
    entity_type TEXT,
    text        TEXT,
    speaker     TEXT,
    start_ms    INTEGER,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS highlights (
    id          INTEGER PRIMARY KEY,
    meeting_id  TEXT NOT NULL,
    text        TEXT,
    rank        REAL,
    count       INTEGER,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS sentiment (
    id          INTEGER PRIMARY KEY,
    meeting_id  TEXT NOT NULL,
    speaker     TEXT,
    text        TEXT,
    sentiment   TEXT,
    confidence  REAL,
    start_ms    INTEGER,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS utterances_fts USING fts5(
    text,
    speaker,
    content='utterances',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep utterances_fts in sync
CREATE TRIGGER IF NOT EXISTS utterances_ai AFTER INSERT ON utterances BEGIN
    INSERT INTO utterances_fts(rowid, text, speaker)
    VALUES (new.id, new.text, new.speaker);
END;

CREATE TRIGGER IF NOT EXISTS utterances_ad AFTER DELETE ON utterances BEGIN
    INSERT INTO utterances_fts(utterances_fts, rowid, text, speaker)
    VALUES ('delete', old.id, old.text, old.speaker);
END;

CREATE TRIGGER IF NOT EXISTS utterances_au AFTER UPDATE ON utterances BEGIN
    INSERT INTO utterances_fts(utterances_fts, rowid, text, speaker)
    VALUES ('delete', old.id, old.text, old.speaker);
    INSERT INTO utterances_fts(rowid, text, speaker)
    VALUES (new.id, new.text, new.speaker);
END;

CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY,
    name        TEXT,
    parent_id   INTEGER,
    level       INTEGER DEFAULT 0,
    keywords_json TEXT
);

CREATE TABLE IF NOT EXISTS topic_assignments (
    chunk_id    TEXT NOT NULL,
    topic_id    INTEGER NOT NULL,
    probability REAL,
    PRIMARY KEY (chunk_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_utterances_meeting_id ON utterances(meeting_id);
CREATE INDEX IF NOT EXISTS idx_chapters_meeting_id ON chapters(meeting_id);
CREATE INDEX IF NOT EXISTS idx_entities_meeting_id_type ON entities(meeting_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_meetings_client ON meetings(client);
CREATE INDEX IF NOT EXISTS idx_topic_assignments_topic ON topic_assignments(topic_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    conn.executescript(_SCHEMA)
    conn.close()


def _delete_meeting_cascade(conn: sqlite3.Connection, meeting_id: str) -> None:
    for table in ("utterances", "chapters", "entities", "highlights", "sentiment"):
        conn.execute(f"DELETE FROM {table} WHERE meeting_id = ?", (meeting_id,))
    conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))


def insert_meeting(conn: sqlite3.Connection, meeting: dict) -> None:
    mid = meeting["id"]
    _delete_meeting_cascade(conn, mid)
    conn.execute(
        """INSERT INTO meetings
           (id, filename, client, topic, file_mtime, audio_duration_sec,
            audio_url, full_text, num_speakers, num_utterances,
            overall_confidence, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mid,
            meeting.get("filename"),
            meeting.get("client"),
            meeting.get("topic"),
            meeting.get("file_mtime"),
            meeting.get("audio_duration_sec"),
            meeting.get("audio_url"),
            meeting.get("full_text"),
            meeting.get("num_speakers"),
            meeting.get("num_utterances"),
            meeting.get("overall_confidence"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def bulk_insert_utterances(
    conn: sqlite3.Connection, meeting_id: str, utterances: list[dict]
) -> None:
    conn.execute("DELETE FROM utterances WHERE meeting_id = ?", (meeting_id,))
    conn.executemany(
        """INSERT INTO utterances (meeting_id, speaker, text, start_ms, end_ms, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                meeting_id,
                u.get("speaker"),
                u.get("text"),
                u.get("start_ms"),
                u.get("end_ms"),
                u.get("confidence"),
            )
            for u in utterances
        ],
    )


def bulk_insert_chapters(
    conn: sqlite3.Connection, meeting_id: str, chapters: list[dict]
) -> None:
    conn.execute("DELETE FROM chapters WHERE meeting_id = ?", (meeting_id,))
    conn.executemany(
        """INSERT INTO chapters (meeting_id, headline, gist, summary, start_ms, end_ms)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                meeting_id,
                c.get("headline"),
                c.get("gist"),
                c.get("summary"),
                c.get("start_ms"),
                c.get("end_ms"),
            )
            for c in chapters
        ],
    )


def bulk_insert_entities(
    conn: sqlite3.Connection, meeting_id: str, entities: list[dict]
) -> None:
    conn.execute("DELETE FROM entities WHERE meeting_id = ?", (meeting_id,))
    conn.executemany(
        """INSERT INTO entities (meeting_id, entity_type, text, speaker, start_ms)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                meeting_id,
                e.get("entity_type"),
                e.get("text"),
                e.get("speaker"),
                e.get("start_ms"),
            )
            for e in entities
        ],
    )


def bulk_insert_highlights(
    conn: sqlite3.Connection, meeting_id: str, highlights: list[dict]
) -> None:
    conn.execute("DELETE FROM highlights WHERE meeting_id = ?", (meeting_id,))
    conn.executemany(
        """INSERT INTO highlights (meeting_id, text, rank, count)
           VALUES (?, ?, ?, ?)""",
        [
            (
                meeting_id,
                h.get("text"),
                h.get("rank"),
                h.get("count"),
            )
            for h in highlights
        ],
    )


def bulk_insert_sentiment(
    conn: sqlite3.Connection, meeting_id: str, sentiments: list[dict]
) -> None:
    conn.execute("DELETE FROM sentiment WHERE meeting_id = ?", (meeting_id,))
    conn.executemany(
        """INSERT INTO sentiment (meeting_id, speaker, text, sentiment, confidence, start_ms)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                meeting_id,
                s.get("speaker"),
                s.get("text"),
                s.get("sentiment"),
                s.get("confidence"),
                s.get("start_ms"),
            )
            for s in sentiments
        ],
    )
