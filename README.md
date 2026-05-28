# Transcript Knowledge Base

Search and analyze 1,100+ meeting transcripts through Claude Desktop using natural language.

## What this does

This system indexes your meeting transcripts (AssemblyAI JSON format) into a searchable knowledge base. You interact with it entirely through **Claude Desktop** — just ask questions in plain English.

### Example questions you can ask Claude:

- "Find meetings about buy box strategy"
- "What are the major themes across all transcripts?"
- "Show me discussions about ROAS and ad spend"
- "Which meetings mention lifetime value?"
- "Give me the full conversation from that meeting around the 5-minute mark"
- "What topics does the Amazon Advertising category cover?"

## Quick Start (Client Setup)

### Prerequisites
- **Windows 10/11**, macOS, or Linux
- [Claude Desktop](https://claude.ai/download) installed and signed in

### Install

**Windows:**
```
# Unzip the package, then double-click:
packaging\install.bat

# Or from PowerShell:
powershell -ExecutionPolicy Bypass -File packaging\install.ps1
```

**macOS / Linux:**
```bash
cd video_transcript_kb
bash packaging/install.sh
```

The script will:
1. Install `uv` (Python package manager) if needed
2. Install all Python dependencies
3. Print the exact config to paste into Claude Desktop

### Configure Claude Desktop

1. Open the Claude Desktop config file:
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Add the `"transcripts"` block into the `"mcpServers"` section (the installer prints the exact JSON to paste)
3. **Fully quit** Claude Desktop (Windows: right-click tray icon > Quit; macOS: Cmd+Q)
4. Reopen Claude Desktop
5. Look for the hammer icon in the chat — that means the tools are connected

### Verify

In Claude Desktop, ask: **"What are the major themes in the transcripts?"**

Claude should call `list_topics` and return a structured overview of all topic clusters.

## Available Tools (what Claude can do)

| Tool | What it does |
|---|---|
| `search_meetings` | Hybrid vector + full-text search across all transcripts |
| `get_meeting` | Full metadata, chapters, and highlights for a specific meeting |
| `get_excerpt` | Speaker-labeled conversation for a time window |
| `list_meetings` | Browse meetings by client or topic keyword |
| `list_topics` | Browse discovered topic clusters and hierarchy |
| `get_topic` | Deep-dive into a topic: keywords, associated meetings |

## Adding New Transcripts

Place new `*_transcribed.json` files in `data/raw/`, then:

```bash
uv run transcripts ingest
uv run transcripts stats
```

To re-fit topic clusters after adding many new files:

```bash
uv run transcripts fit-topics
```

## CLI Reference

```bash
uv run transcripts init-db          # Initialize empty database
uv run transcripts ingest [PATH]    # Ingest transcripts (file or directory)
uv run transcripts stats            # Show corpus statistics
uv run transcripts search "query"   # Search from command line
uv run transcripts fit-topics       # Fit topic clusters
uv run transcripts list-topics      # List discovered topics
uv run transcripts label-topics F   # Apply labels from JSON file
```

## Architecture

```
data/
  raw/              ← Raw AssemblyAI JSON files (not shipped to client)
  transcripts.db    ← SQLite: meetings, utterances, chapters, entities, topics
  chroma/           ← ChromaDB: vector embeddings for semantic search
  bertopic_model/   ← Saved BERTopic model
  cluster_reps.json ← Representative docs per topic
  topic_hierarchy.json ← Nested topic tree

src/transcripts/
  cli.py            ← Typer CLI commands
  mcp_server.py     ← MCP server for Claude Desktop
  loader.py         ← AssemblyAI JSON parser
  chunker.py        ← Text chunking for embeddings
  embedder.py       ← Sentence-transformers wrapper
  retrieval.py      ← Hybrid search (vector + FTS5 + RRF)
  config.py         ← Paths and constants
  filename_parser.py← Extract client/topic from filenames
  store/
    sqlite_store.py ← SQLite schema and operations
    vector_store.py ← ChromaDB wrapper
  topics/
    model.py        ← BERTopic fitting and hierarchy
    labeler.py      ← Human-readable topic labels
```
