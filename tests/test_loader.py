import glob
from pathlib import Path

import pytest

from transcripts.loader import load_assemblyai_json

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


@pytest.fixture
def sample_path():
    files = sorted(glob.glob(str(RAW_DIR / "*_transcribed.json")))
    if not files:
        pytest.skip("No transcript JSONs found in data/raw/")
    return Path(files[0])


def test_load_returns_expected_keys_and_types(sample_path):
    result = load_assemblyai_json(sample_path)

    # All expected top-level keys present
    expected_keys = {
        "id", "filename", "audio_url", "audio_duration_sec", "full_text",
        "utterances", "num_speakers", "num_utterances", "overall_confidence",
        "chapters", "entities", "highlights", "sentiment",
    }
    assert expected_keys == set(result.keys())

    # Type checks
    assert isinstance(result["id"], str) and len(result["id"]) > 0
    assert isinstance(result["filename"], str)
    assert isinstance(result["full_text"], str)
    assert isinstance(result["audio_duration_sec"], (int, float))
    assert isinstance(result["num_speakers"], int) and result["num_speakers"] >= 1
    assert isinstance(result["num_utterances"], int) and result["num_utterances"] >= 1
    assert isinstance(result["overall_confidence"], float)

    # Lists
    for key in ("utterances", "chapters", "entities", "highlights", "sentiment"):
        assert isinstance(result[key], list)

    # Utterance structure
    u = result["utterances"][0]
    assert "speaker" in u
    assert "text" in u
    assert "start_ms" in u
    assert "end_ms" in u

    # Degenerate single-turn detection: if original had 1 utterance,
    # loader should have split into multiple turns from words
    if result["num_utterances"] > 1:
        assert len(result["utterances"]) > 1
