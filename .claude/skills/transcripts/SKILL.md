---
name: transcripts
description: Use when the user asks about meeting transcripts, client conversations, or CPG/retail-media discussions in the transcripts corpus. Triggers on phrases like "what did X say about Y", "find meetings about Z", "show me discussions of [topic]", or any mention of specific clients or products in the corpus.
---

## Corpus

~1500 client meeting transcripts in the CPG and retail-media domain, transcribed by AssemblyAI. Each transcript includes speaker-diarized utterances, auto-generated chapters, named entities, sentiment analysis, and auto-highlights. All data is indexed in SQLite (structured) and ChromaDB (vector embeddings) for hybrid retrieval.

## MCP Tools

### search_meetings
Primary search tool. Runs hybrid vector + full-text retrieval across all transcripts.
- Use for: "what was discussed about X", "find meetings mentioning Y", any topical query.
- Params: `query` (required), `top_k`, `client` (filter by client name), `kind` ("chapter" or "utterance").
- Returns: ranked hits with `meeting_id`, `client`, `topic`, `snippet`, `score`, `start_ms`, `end_ms`.

### get_meeting
Fetch full metadata for a specific meeting.
- Use for: "tell me more about this meeting", drilling into a search result.
- Params: `meeting_id` (from search_meetings results).
- Returns: client, topic, duration, speaker count, chapter summaries (headline + gist + timestamps), highlights.

### get_excerpt
Read the actual speaker-labeled conversation for a time window.
- Use for: "show me what was said", "give me the full context around this hit".
- Params: `meeting_id`, `start_ms`, `end_ms` (from search_meetings results).
- Returns: utterances with speaker labels, timestamps, and confidence scores.

### list_meetings
Browse and discover meetings in the corpus.
- Use for: "what meetings do we have for client X", "list meetings about Y".
- Params: `client` (partial match), `topic_contains` (keyword in topic), `limit`.
- Returns: meeting list with id, filename, client, topic, duration, speaker count.

### list_topics
Browse discovered topic clusters across the entire corpus.
- Use for: "what are the major themes?", "what topics exist?", exploring the topic hierarchy.
- Params: `parent_id` (optional, to drill into a branch), `limit`.
- Returns: topics with `topic_id`, `name`, `chunk_count`, `top_keywords`.

### get_topic
Get detailed info about a specific topic cluster.
- Use for: "tell me about topic X", "which meetings discuss this theme?".
- Params: `topic_id` (from list_topics).
- Returns: keywords with weights, top associated meetings, chunk count.

## Query Patterns

- **"What was discussed about X?"** → `search_meetings(query="X")` → review snippets.
- **"Give me the full context"** → take `meeting_id`, `start_ms`, `end_ms` from a search hit → `get_excerpt(meeting_id, start_ms, end_ms)`.
- **"What topics does client X come up in?"** → `list_meetings(client="X")` to see all their meetings, then `search_meetings(query="...", client="X")` for specific topics.
- **"Tell me about meeting Y"** → `get_meeting(meeting_id="Y")` for chapters and highlights.
- **"What are the major themes in the corpus?"** → `list_topics()` to see all discovered topic clusters.
- **"Show me LTV discussions"** → `list_topics()` to find the relevant topic_id, then `get_topic(topic_id)` to see which meetings are in that cluster.
- **"What topics overlap with client X?"** → `list_meetings(client="X")` → for each meeting, check topic assignments via `get_topic()`.

## Filename Conventions

Transcript files follow the pattern `Client_Topic_Description_transcribed.json`. The client is heuristically extracted from the first 1–2 tokens of the filename; the rest becomes the topic. Examples:
- `22_Ventures_Vaginal_Probiotics_Analysis_transcribed.json` → client: "22 Ventures", topic: "Vaginal Probiotics Analysis"
- `Ad_launch____4_Product_targeting_campaign_transcribed.json` → client: "", topic: "Ad launch 4 Product targeting campaign"

## Timestamps

All timestamps are in **milliseconds**. Each meeting has an `audio_url` field — combine it with timestamps for audio playback reference.

## Maintenance Commands

```bash
# Ingest new transcript files (idempotent, safe to re-run)
uv run transcripts ingest

# Ingest a specific file or directory
uv run transcripts ingest /path/to/file_or_dir

# Check corpus stats
uv run transcripts stats

# Search from the command line
uv run transcripts search "buy box strategy"

# Initialize empty database
uv run transcripts init-db

# Fit topic clusters on existing embeddings
uv run transcripts fit-topics

# List discovered topics
uv run transcripts list-topics

# Apply human labels from a JSON file ({"0": "Buy Box Strategy", "1": "LTV Analysis", ...})
uv run transcripts label-topics data/topic_labels.json
```
