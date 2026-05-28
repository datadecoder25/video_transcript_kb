import json
from pathlib import Path

_GAP_THRESHOLD_MS = 2000


def _build_turns_from_words(words: list[dict]) -> list[dict]:
    """Build utterance-like turns from word-level data.

    Groups consecutive same-speaker words, splitting when the speaker
    changes or the gap between words exceeds 2 seconds.
    """
    if not words:
        return []

    turns: list[dict] = []
    cur_speaker = words[0].get("speaker")
    cur_texts = [words[0]["text"]]
    cur_start = words[0]["start"]
    cur_end = words[0]["end"]
    cur_confs = [words[0].get("confidence", 0.0)]

    for w in words[1:]:
        speaker = w.get("speaker")
        gap = w["start"] - cur_end
        if speaker != cur_speaker or gap > _GAP_THRESHOLD_MS:
            turns.append({
                "speaker": cur_speaker,
                "text": " ".join(cur_texts),
                "start_ms": cur_start,
                "end_ms": cur_end,
                "confidence": sum(cur_confs) / len(cur_confs) if cur_confs else None,
            })
            cur_speaker = speaker
            cur_texts = [w["text"]]
            cur_start = w["start"]
            cur_end = w["end"]
            cur_confs = [w.get("confidence", 0.0)]
        else:
            cur_texts.append(w["text"])
            cur_end = w["end"]
            cur_confs.append(w.get("confidence", 0.0))

    turns.append({
        "speaker": cur_speaker,
        "text": " ".join(cur_texts),
        "start_ms": cur_start,
        "end_ms": cur_end,
        "confidence": sum(cur_confs) / len(cur_confs) if cur_confs else None,
    })
    return turns


def _normalize_utterances(raw: list[dict], words: list[dict]) -> list[dict]:
    """Normalize utterances, falling back to word-level grouping for
    degenerate single mega-turn transcripts."""
    if not raw:
        return _build_turns_from_words(words) if words else []

    speakers = {u.get("speaker") for u in raw}
    if len(raw) == 1 and len(speakers) <= 1 and words:
        return _build_turns_from_words(words)

    return [
        {
            "speaker": u.get("speaker"),
            "text": u.get("text"),
            "start_ms": u.get("start"),
            "end_ms": u.get("end"),
            "confidence": u.get("confidence"),
        }
        for u in raw
    ]


def _normalize_chapters(raw: list[dict] | None) -> list[dict]:
    if not raw:
        return []
    return [
        {
            "headline": c.get("headline"),
            "gist": c.get("gist"),
            "summary": c.get("summary"),
            "start_ms": c.get("start"),
            "end_ms": c.get("end"),
        }
        for c in raw
    ]


def _normalize_entities(raw: list[dict] | None) -> list[dict]:
    if not raw:
        return []
    return [
        {
            "entity_type": e.get("entity_type"),
            "text": e.get("text"),
            "speaker": e.get("speaker"),
            "start_ms": e.get("start"),
        }
        for e in raw
    ]


def _normalize_highlights(data: dict | None) -> list[dict]:
    if not data:
        return []
    results = data.get("results") or []
    return [
        {
            "text": h.get("text"),
            "rank": h.get("rank"),
            "count": h.get("count"),
        }
        for h in results
    ]


def _normalize_sentiment(raw: list[dict] | None) -> list[dict]:
    if not raw:
        return []
    return [
        {
            "speaker": s.get("speaker"),
            "text": s.get("text"),
            "sentiment": s.get("sentiment"),
            "confidence": s.get("confidence"),
            "start_ms": s.get("start"),
        }
        for s in raw
    ]


def load_assemblyai_json(path: Path) -> dict:
    """Load an AssemblyAI transcript JSON and return a normalized dict."""
    with open(path) as f:
        raw = json.load(f)

    words = raw.get("words") or []
    utterances = _normalize_utterances(
        raw.get("utterances") or [], words
    )
    speakers = {u["speaker"] for u in utterances if u.get("speaker")}

    return {
        "id": raw["id"],
        "filename": path.name,
        "audio_url": raw.get("audio_url"),
        "audio_duration_sec": raw.get("audio_duration"),
        "full_text": raw.get("text"),
        "utterances": utterances,
        "num_speakers": len(speakers),
        "num_utterances": len(utterances),
        "overall_confidence": raw.get("confidence"),
        "chapters": _normalize_chapters(raw.get("chapters")),
        "entities": _normalize_entities(raw.get("entities")),
        "highlights": _normalize_highlights(raw.get("auto_highlights_result")),
        "sentiment": _normalize_sentiment(raw.get("sentiment_analysis_results")),
    }
