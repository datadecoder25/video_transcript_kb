import json

from transcripts.config import DATA_DIR, DB_PATH
from transcripts.store.sqlite_store import connect
from transcripts.topics.model import CLUSTER_REPS_PATH

LABELS_PATH = DATA_DIR / "topic_labels.json"


def get_unlabeled_topics() -> list[dict]:
    """Return cluster reps for topics that still have auto-generated names."""
    if not CLUSTER_REPS_PATH.exists():
        return []

    with open(CLUSTER_REPS_PATH) as f:
        reps = json.load(f)

    return [
        {
            "topic_id": v["topic_id"],
            "current_name": v["name"],
            "keywords": v["keywords"],
            "sample_docs": [d[:300] for d in v["representative_docs"][:5]],
        }
        for v in reps.values()
    ]


def apply_labels(labels: dict[str, str]) -> int:
    """Apply human-provided topic labels to SQLite.

    Args:
        labels: Mapping of topic_id (as string) to human-readable name.

    Returns:
        Number of topics updated.
    """
    conn = connect(DB_PATH)
    updated = 0
    for tid_str, name in labels.items():
        tid = int(tid_str)
        conn.execute("UPDATE topics SET name = ? WHERE id = ?", (name, tid))
        updated += 1
    conn.commit()
    conn.close()

    # Also update cluster_reps.json
    if CLUSTER_REPS_PATH.exists():
        with open(CLUSTER_REPS_PATH) as f:
            reps = json.load(f)
        for tid_str, name in labels.items():
            if tid_str in reps:
                reps[tid_str]["name"] = name
        with open(CLUSTER_REPS_PATH, "w") as f:
            json.dump(reps, f, indent=2)

    # Save labels file for reference
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if LABELS_PATH.exists():
        with open(LABELS_PATH) as f:
            existing = json.load(f)
    existing.update(labels)
    with open(LABELS_PATH, "w") as f:
        json.dump(existing, f, indent=2)

    return updated
