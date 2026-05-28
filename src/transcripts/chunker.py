import hashlib


def _token_count(text: str) -> int:
    return len(text.split())


def _chunk_id(meeting_id: str, kind: str, index: int) -> str:
    raw = f"{meeting_id}:{kind}:{index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _build_chapter_chunks(meeting: dict) -> list[dict]:
    meeting_id = meeting["id"]
    chapters = meeting.get("chapters") or []
    chunks = []
    for idx, ch in enumerate(chapters):
        headline = ch.get("headline") or ""
        summary = ch.get("summary") or ""
        text = f"{headline} — {summary}" if summary else headline
        if not text.strip():
            continue
        chunks.append({
            "id": _chunk_id(meeting_id, "chapter", idx),
            "meeting_id": meeting_id,
            "text": text,
            "kind": "chapter",
            "chapter_idx": idx,
            "start_ms": ch.get("start_ms"),
            "end_ms": ch.get("end_ms"),
            "speakers": "",
            "chapter_headline": headline,
        })
    return chunks


def _build_utterance_chunks(
    meeting: dict, target_tokens: int = 500, overlap_tokens: int = 100
) -> list[dict]:
    meeting_id = meeting["id"]
    utterances = meeting.get("utterances") or []
    if not utterances:
        return []

    chunks = []
    chunk_idx = 0
    i = 0  # index into utterances

    while i < len(utterances):
        window: list[dict] = []
        token_total = 0

        # Fill window up to target_tokens
        j = i
        while j < len(utterances) and token_total < target_tokens:
            u = utterances[j]
            text = u.get("text") or ""
            token_total += _token_count(text)
            window.append(u)
            j += 1

        if not window:
            break

        # Build chunk text with speaker labels
        lines = []
        speakers = set()
        for u in window:
            speaker = u.get("speaker") or "Unknown"
            speakers.add(speaker)
            lines.append(f"{speaker}: {u.get('text', '')}")
        text = "\n".join(lines)

        chunks.append({
            "id": _chunk_id(meeting_id, "utterance", chunk_idx),
            "meeting_id": meeting_id,
            "text": text,
            "kind": "utterance",
            "start_ms": window[0].get("start_ms"),
            "end_ms": window[-1].get("end_ms"),
            "speakers": ", ".join(sorted(speakers)),
        })
        chunk_idx += 1

        # Advance with overlap: step back enough utterances to keep
        # ~overlap_tokens worth of text from the end of the current window
        overlap_count = 0
        overlap_acc = 0
        for k in range(len(window) - 1, -1, -1):
            t = _token_count(window[k].get("text") or "")
            if overlap_acc + t > overlap_tokens and overlap_count > 0:
                break
            overlap_acc += t
            overlap_count += 1

        next_i = i + len(window) - overlap_count
        # Ensure we always advance by at least 1 utterance
        i = max(next_i, i + 1)

    return chunks


def build_chunks(meeting: dict) -> list[dict]:
    """Build two-tier chunks from a normalized meeting dict.

    Tier 1: One chunk per chapter (headline + summary).
    Tier 2: Sliding-window chunks over utterances (~500 tokens, ~100 overlap).
    """
    return _build_chapter_chunks(meeting) + _build_utterance_chunks(meeting)
