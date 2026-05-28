# Transcripts System — Build Plan for PyCharm + Claude Code

This is a runbook. You'll do some steps yourself (one-line terminal commands), and for the rest you'll paste the labeled **Claude Code prompt** blocks into PyCharm's Claude Code panel. Work through it in order — each step assumes the previous one succeeded.

The goal of Phase 1 is end-to-end search working in Claude Desktop on 10 sample transcripts. Once that lands, you scale to all 1500, then add topics (Phase 2) and the knowledge graph (Phase 3), then package for your client.

---

## 0. Prerequisites (5 minutes)

You need on your laptop:

- macOS or Linux with a terminal
- Python 3.11+ (we'll let `uv` manage this for us)
- PyCharm with the Claude Code plugin installed and signed in
- Claude Desktop installed and signed in (for testing the MCP integration locally before shipping)
- Your 1500 `*_transcribed.json` files in a known folder — for now we only need 10 of them

If `uv` isn't installed, run:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 1. Bootstrap the project (terminal, ~2 minutes)

Pick a stable location and run these commands yourself:

```bash
mkdir -p ~/projects/transcripts-system
cd ~/projects/transcripts-system

uv init --python 3.11 --no-readme
rm hello.py main.py 2>/dev/null  # uv may create one of these

mkdir -p src/transcripts data/raw .claude/skills/transcripts scripts tests/fixtures packaging
touch src/transcripts/__init__.py

# Copy 10 sample transcripts in so we have something to work with
cp /path/to/your/transcripts/*.json data/raw/ | head -n 10
# Or pick 10 manually — just make sure data/raw/ has ~10 *_transcribed.json files

# Initial git
git init
echo "data/" > .gitignore
echo ".venv/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
echo ".env" >> .gitignore
```

Open the folder in PyCharm. Open the Claude Code panel inside PyCharm.

---

## 2. Add dependencies and the package layout

**Claude Code prompt:**

> I'm building a transcript search and analysis system. Update `pyproject.toml` to use `src/` layout with the package name `transcripts`. Add these dependencies (latest stable versions, no upper bound pins): `chromadb`, `sentence-transformers`, `mcp[cli]`, `typer`, `python-dateutil`, `tqdm`, `numpy`, `rank-bm25`. Add a dev group with `pytest` and `ruff`. Add a `[project.scripts]` entry called `transcripts` pointing to `transcripts.cli:app`. After updating, run `uv sync` and confirm it completes without errors.

Verify when done: `uv run python -c "import chromadb, sentence_transformers, mcp; print('ok')"` prints `ok`.

---

## 3. Filename parser + config

The filenames look like `22_Ventures_Vaginal_Probiotics_Analysis_transcribed.json`. We need to split this into a client identifier and a topic.

**Claude Code prompt:**

> Create `src/transcripts/config.py` defining absolute paths: `PROJECT_ROOT` (resolved from this file), `DATA_DIR = PROJECT_ROOT / "data"`, `RAW_DIR = DATA_DIR / "raw"`, `DB_PATH = DATA_DIR / "transcripts.db"`, `CHROMA_DIR = DATA_DIR / "chroma"`. Make `DATA_DIR` available as an environment variable override `TRANSCRIPTS_DATA_DIR` for deployment. Also define `EMBEDDING_MODEL = "google/embeddinggemma-300m"` and `EMBEDDING_DIM = 768`. (You can truncate to 256 dim later via Matryoshka if Chroma storage matters; keep 768 for v1.)
>
> Then create `src/transcripts/filename_parser.py` with a function `parse_filename(filename: str) -> dict` that takes a string like `"22_Ventures_Vaginal_Probiotics_Analysis_transcribed.json"` and returns `{"client": "22 Ventures", "topic": "Vaginal Probiotics Analysis", "stem": "22_Ventures_Vaginal_Probiotics_Analysis"}`. The client is heuristically the first 1–3 underscore-separated tokens that look like a brand name; everything between client and `_transcribed` is the topic with underscores replaced by spaces. Cover edge cases: trailing `.json`, missing `_transcribed`, single-word filenames. Add 6–8 pytest cases in `tests/test_filename_parser.py` covering these edge cases. Run the tests and confirm they pass.

Verify: `uv run pytest tests/test_filename_parser.py -v` passes.

---

## 4. SQLite schema and storage layer

**Claude Code prompt:**

> Create `src/transcripts/store/sqlite_store.py` implementing the schema described below. Use plain `sqlite3` (stdlib), no ORM. Foreign keys ON, WAL mode ON.
>
> Tables:
> - `meetings(id TEXT PRIMARY KEY, filename TEXT, client TEXT, topic TEXT, file_mtime TEXT, audio_duration_sec INTEGER, audio_url TEXT, full_text TEXT, num_speakers INTEGER, num_utterances INTEGER, overall_confidence REAL, ingested_at TEXT)`
> - `utterances(id INTEGER PRIMARY KEY, meeting_id TEXT NOT NULL, speaker TEXT, text TEXT, start_ms INTEGER, end_ms INTEGER, confidence REAL, FOREIGN KEY(meeting_id) REFERENCES meetings(id))`
> - `chapters(id INTEGER PRIMARY KEY, meeting_id TEXT NOT NULL, headline TEXT, gist TEXT, summary TEXT, start_ms INTEGER, end_ms INTEGER, FOREIGN KEY(meeting_id) REFERENCES meetings(id))`
> - `entities(id INTEGER PRIMARY KEY, meeting_id TEXT NOT NULL, entity_type TEXT, text TEXT, speaker TEXT, start_ms INTEGER, FOREIGN KEY(meeting_id) REFERENCES meetings(id))`
> - `highlights(id INTEGER PRIMARY KEY, meeting_id TEXT NOT NULL, text TEXT, rank REAL, count INTEGER, FOREIGN KEY(meeting_id) REFERENCES meetings(id))`
> - `sentiment(id INTEGER PRIMARY KEY, meeting_id TEXT NOT NULL, speaker TEXT, text TEXT, sentiment TEXT, confidence REAL, start_ms INTEGER, FOREIGN KEY(meeting_id) REFERENCES meetings(id))`
> - FTS5 virtual table `utterances_fts(text, speaker, content='utterances', content_rowid='id', tokenize='porter unicode61')`
>
> Include triggers that keep `utterances_fts` in sync with INSERT/UPDATE/DELETE on `utterances`. Indexes on `utterances(meeting_id)`, `chapters(meeting_id)`, `entities(meeting_id, entity_type)`, `meetings(client)`.
>
> Public functions: `init_db(db_path: Path) -> None`, `connect(db_path: Path) -> sqlite3.Connection`, `insert_meeting(conn, meeting_dict) -> None`, `bulk_insert_utterances(conn, meeting_id, utterances_list) -> None`, and matching bulk inserters for `chapters`, `entities`, `highlights`, `sentiment`. Make all inserts idempotent on `meeting_id` (DELETE existing rows for that meeting_id first).

Verify: create a quick scratch script that calls `init_db()`, inspect the schema with `sqlite3 data/transcripts.db ".schema"`.

---

## 5. JSON loader + chunker + embedder

**Claude Code prompt:**

> Create three modules under `src/transcripts/`:
>
> `loader.py` — function `load_assemblyai_json(path: Path) -> dict` that reads an AssemblyAI transcript JSON and returns a normalized dict with keys: `id` (from JSON), `filename`, `audio_url`, `audio_duration_sec` (from `audio_duration`), `full_text` (from `text`), `utterances` (list of speaker turns with start_ms/end_ms), `chapters`, `entities`, `highlights` (from `auto_highlights_result.results`), `sentiment` (from `sentiment_analysis_results`), and a derived `num_speakers` from distinct speaker labels.
>
> Two important notes: (1) when `utterances` is a single degenerate mega-turn (one speaker), fall back to building turns from `words[]` by grouping consecutive same-speaker words with no gap >2s between them. (2) Strip any None values gracefully.
>
> `chunker.py` — function `build_chunks(meeting: dict) -> list[dict]`. Two-tier strategy: (a) one chunk per chapter where `chapter_text = headline + " — " + summary`, with metadata `{kind: "chapter", chapter_idx, start_ms, end_ms, speakers}`. (b) Sliding window chunks over utterances: target ~500 tokens with ~100 token overlap, never split mid-utterance, preserve speaker labels in chunk text formatted as `"Speaker A: ...\nSpeaker B: ..."`. Use a simple whitespace tokenizer for length counting. Each chunk returns `{id, meeting_id, text, kind, start_ms, end_ms, speakers, chapter_headline?}`.
>
> `embedder.py` — class `Embedder` that wraps `sentence-transformers` with `google/embeddinggemma-300m`. Lazy-load model on first use. Two methods: `embed_documents(texts: list[str]) -> np.ndarray` calling `model.encode_document()`, and `embed_query(text: str) -> np.ndarray` calling `model.encode_query()`. EmbeddingGemma is prompt-aware — these two methods apply the right task-specific prefix internally, and skipping the distinction hurts retrieval quality by several percent. Both methods use batch size 64 and show a tqdm progress bar when `len(texts) > 100`. Embeddings come L2-normalized from the model; no extra normalization needed.
>
> Add `tests/test_loader.py` with one test that loads a real JSON from `data/raw/` (whichever exists) and asserts the expected keys are present and types are right.

Verify: `uv run pytest tests/test_loader.py -v` passes.

---

## 6. Vector store wrapper

**Claude Code prompt:**

> Create `src/transcripts/store/vector_store.py` wrapping a persistent ChromaDB client at `CHROMA_DIR`. Collection name: `transcripts`. Embedding function: explicitly disabled (we pass precomputed embeddings).
>
> Public functions: `get_collection()`, `upsert_chunks(chunks: list[dict], embeddings: np.ndarray) -> None` storing chunk text in document, chunk id as id, and `{meeting_id, kind, start_ms, end_ms, speakers (comma-joined), chapter_headline}` as metadata. `query(query_embedding, top_k=20, where: dict | None = None) -> list[dict]` returning hits with id, document, metadata, distance. `delete_meeting(meeting_id: str) -> None`.

---

## 7. Top-level ingestion CLI

**Claude Code prompt:**

> Create `src/transcripts/cli.py` using Typer. Commands:
>
> - `transcripts init-db` — calls `init_db()` and ensures Chroma collection exists.
> - `transcripts ingest [PATH]` — if PATH is a file, ingest it; if PATH is a directory (default: `data/raw`), ingest every `*_transcribed.json` in it. For each file: load JSON, parse filename, insert meeting+utterances+chapters+entities+highlights+sentiment into SQLite (idempotent on meeting id), build chunks, embed them, upsert into Chroma. Show a tqdm progress bar across files. Print summary at the end: `Ingested N meetings, M chunks`.
> - `transcripts stats` — prints meeting count, utterance count, chunk count.
>
> Wire `transcripts` script entry in `pyproject.toml` to `transcripts.cli:app` (you already did this in step 2; just confirm).

Run it:

```bash
uv run transcripts init-db
uv run transcripts ingest
uv run transcripts stats
```

Verify: `stats` reports ~10 meetings, several hundred chunks. Open the DB in a SQLite viewer to spot-check a meeting and its utterances.

---

## 8. Hybrid retrieval

**Claude Code prompt:**

> Create `src/transcripts/retrieval.py` with one main function:
>
> `def search(query: str, top_k: int = 10, filters: dict | None = None) -> list[dict]` that runs hybrid retrieval:
>
> 1. Embed the query via `Embedder.embed_query()` — the query-specific method, *not* `embed_documents`. EmbeddingGemma uses different prompt prefixes for queries vs documents.
> 2. Vector search via Chroma — fetch `3 * top_k` candidates.
> 3. FTS5 search via SQLite — `SELECT meeting_id, rowid, bm25(utterances_fts) FROM utterances_fts WHERE utterances_fts MATCH ? ORDER BY rank LIMIT ?` with the query (escape special chars). Map utterance rowids to chunk-ish records by reading the utterance row.
> 4. Reciprocal Rank Fusion over the two lists with k=60. Return top_k merged hits, each containing `{chunk_id, meeting_id, text, score, source: "vector"|"fts"|"both", metadata}`.
>
> Add `get_meeting(meeting_id) -> dict` returning meeting metadata + chapters + highlights (no full utterances). Add `get_excerpt(meeting_id, start_ms, end_ms) -> list[dict]` returning utterances overlapping that window.
>
> Add a CLI command `transcripts search "query"` that calls `search()` and prints top 5 hits nicely (client, topic, score, snippet).

Run `uv run transcripts search "buy box"` (or some keyword from your sample transcripts) and confirm you get sensible hits.

---

## 9. MCP server

**Claude Code prompt:**

> Create `src/transcripts/mcp_server.py` using the `mcp` Python SDK with stdio transport. Server name: `transcripts`.
>
> Expose four tools:
>
> 1. `search_meetings(query: str, top_k: int = 10, client: str | None = None, kind: str | None = None) -> list[dict]` — calls `retrieval.search()` with optional metadata filters. Returns hits with meeting_id, client, topic, snippet (first 200 chars), score, start_ms, end_ms.
>
> 2. `get_meeting(meeting_id: str) -> dict` — returns full meeting metadata, chapter list (headline + gist + start_ms/end_ms), highlights.
>
> 3. `get_excerpt(meeting_id: str, start_ms: int, end_ms: int) -> list[dict]` — returns the utterances in that window with speaker labels.
>
> 4. `list_meetings(client: str | None = None, topic_contains: str | None = None, limit: int = 50) -> list[dict]` — discovery query against `meetings` table.
>
> Each tool has a clear docstring (becomes the tool description for Claude). Add `if __name__ == "__main__": run()` so the server can be launched as `uv run python -m transcripts.mcp_server`.

---

## 10. Register the MCP server with Claude Desktop (your laptop)

**Claude Code prompt:**

> Create `packaging/claude_desktop_config_snippet.json` with this content (substitute `{{PROJECT_PATH}}` and `{{DATA_PATH}}` placeholders):
>
> ```json
> {
>   "mcpServers": {
>     "transcripts": {
>       "command": "uv",
>       "args": ["--directory", "{{PROJECT_PATH}}", "run", "python", "-m", "transcripts.mcp_server"],
>       "env": {
>         "TRANSCRIPTS_DATA_DIR": "{{DATA_PATH}}"
>       }
>     }
>   }
> }
> ```
>
> Also create `.mcp.json` in the project root with the same content but with the real absolute paths filled in (read the project root via `pwd` equivalent). This makes the server available to Claude Code inside PyCharm as well.

Now manually edit your Claude Desktop config:

- macOS path: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Open it in any editor, merge in the `mcpServers.transcripts` entry from the snippet (use the absolute path version).
- Fully quit and reopen Claude Desktop.

In Claude Desktop, start a new chat and ask: "Use the transcripts MCP to search for 'buy box'." Confirm Claude calls `search_meetings` and returns results. Then ask: "Get the full meeting metadata for [meeting_id]" — confirm `get_meeting` works.

This is the Phase 1 end-to-end success milestone.

---

## 11. Project SKILL.md for Claude Code

**Claude Code prompt:**

> Create `.claude/skills/transcripts/SKILL.md` with YAML frontmatter:
>
> ```yaml
> ---
> name: transcripts
> description: Use when the user asks about meeting transcripts, client conversations, or CPG/retail-media discussions in the transcripts corpus. Triggers on phrases like "what did X say about Y", "find meetings about Z", "show me discussions of [topic]", or any mention of specific clients or products in the corpus.
> ---
> ```
>
> Body content covers: (1) what the corpus is (1500 client meeting transcripts, CPG/retail-media domain, AssemblyAI-transcribed), (2) the four MCP tools and when to use each, (3) filename conventions (client_topic_transcribed.json), (4) query patterns — for "what was discussed about X" start with `search_meetings`; for "give me the full context" follow up with `get_excerpt` using the start_ms/end_ms from the search hit; for "what topics does client X come up in" use `list_meetings` with the client filter, (5) timestamps are milliseconds and link back to `audio_url` for playback, (6) bash commands for maintenance: `uv run transcripts ingest` to add new files, `uv run transcripts stats` to inspect.

---

## 12. Scale to all 1500 transcripts

Drop your full set into `data/raw/`. Run:

```bash
uv run transcripts ingest
```

On a modern laptop with EmbeddingGemma on CPU this takes 10–25 minutes for embedding. The first run also downloads the ~600 MB model into the Hugging Face cache (one time only). Validate:

```bash
uv run transcripts stats
uv run transcripts search "lifetime value"
uv run transcripts search "amazon PPC"
```

Inspect a few results, make sure clients/topics look right, no obvious parsing failures. If filenames have edge cases your parser missed, fix those now — re-running ingest is idempotent.

**Phase 1 is done when:** Claude Desktop, on the client's eventual setup, would be able to answer "find meetings where lifetime value was discussed for [client]" using only the MCP tools, with citations to specific meetings and timestamps.

---

## Phase 2 outline — Topic modeling (do this after Phase 1 is stable)

You'll add three things:

- **`src/transcripts/topics/model.py`** — fits BERTopic on the chunks already in Chroma. Reuses existing embeddings via `BERTopic(embedding_model=None)` and `fit_transform(docs, embeddings=embeddings)`. Builds two-tier hierarchy via `hierarchical_topics()`. Saves model to `data/bertopic_model/`.
- **`src/transcripts/topics/labeler.py`** — extracts 10 representative docs per topic, writes them to `data/cluster_reps.json`. You then ask Claude (in PyCharm or Desktop) to label them; paste back a JSON map; tool reads it and updates topic names in SQLite.
- **New SQLite table** `topic_assignments(chunk_id, topic_id, probability)` and `topics(id, name, parent_id, level, keywords_json)`.
- **Two new MCP tools** `list_topics(parent_id=None)` and `get_topic(topic_id)`.
- **Streamlit dashboard** `dashboard/app.py` rendering BERTopic's `visualize_hierarchy()` and `visualize_topics()` plus a meeting list filtered by selected topic.

Phase 2 acceptance: in Claude Desktop, "what are the major themes in the corpus?" returns a meaningful list of 15–25 topics, and "show me LTV discussions" topic-gates retrieval correctly.

---

## Phase 3 outline — Knowledge graph

- **`src/transcripts/kg/populator.py`** — reads SQLite + topic assignments, populates a Kùzu graph with the schema-first design from earlier (Meeting, Client, Person, Product, Entity, Topic nodes; discusses/mentions/has-participant/parent-of/co-occurs-with edges). Entity resolution: normalize strings (lowercase, strip punctuation, collapse whitespace) and maintain an `aliases.csv` you curate by hand.
- **`src/transcripts/kg/queries.py`** — `entity_neighborhood(entity_name, depth)`, `connect_entities(a, b)`, `meetings_for_entity(entity_name)`.
- **Pyvis viz** — function that generates a standalone HTML file for a subgraph; new MCP tool `render_subgraph_viz` returns the local file path.
- **Three new MCP tools** mirroring the kg.queries functions.

Phase 3 acceptance: "which clients have discussed buy box issues?" returns a graph-traversed answer, and you can open the generated Pyvis HTML to see the neighborhood.

---

## Packaging for the client (after all phases are stable)

When you're ready to ship:

1. Run `uv run transcripts ingest` against the final corpus on your machine to produce a fresh `data/`.
2. Create `packaging/install.sh` that on the client's machine: installs `uv` if missing, runs `uv sync`, prints the absolute paths and the exact Claude Desktop config JSON to paste.
3. Zip the project directory excluding `.venv/`, `__pycache__/`, and `data/raw/` (you ship the pre-built indices, not the raw JSONs).
4. Walk the client through the install via screen-share once. Keep notes of every friction point — they become README v2.

---

## Working with Claude Code in PyCharm — practical tips

- **Paste one phase's prompt at a time.** Don't dump the whole runbook into Claude Code. Each numbered section is sized to be one focused Claude Code task.
- **Verify between steps.** The `Verify:` lines exist so you catch issues early. Don't proceed if a verification fails.
- **Commit after each successful step.** `git add -A && git commit -m "step N: <description>"`. Cheap insurance.
- **When Claude Code's output looks wrong, paste the error or unexpected output back to it.** Don't accept code that doesn't run.
- **You may need to nudge file paths.** Claude Code occasionally puts files in slightly wrong locations on a fresh project. Check before running.

---

## What you'll have when you're done

A single project directory (~700 MB with full corpus) that:

- Indexes 1500 AssemblyAI transcripts into SQLite + Chroma + Kùzu.
- Exposes a clean MCP tool surface to Claude Desktop (and Claude Code).
- Provides a local Streamlit dashboard for topic and KG exploration.
- Can be re-ingested incrementally as new meetings are added.
- Installs on the client's laptop in under 10 minutes with one config-paste.

Phase 1 alone — which is the smallest shippable cut — takes a focused half-day in PyCharm with Claude Code.
