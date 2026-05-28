import json
import numpy as np

from transcripts.config import DATA_DIR, DB_PATH
from transcripts.store.sqlite_store import connect, init_db
from transcripts.store.vector_store import get_collection

BERTOPIC_MODEL_DIR = DATA_DIR / "bertopic_model"
CLUSTER_REPS_PATH = DATA_DIR / "cluster_reps.json"
HIERARCHY_PATH = DATA_DIR / "topic_hierarchy.json"


def _load_chapter_summaries() -> tuple[list[str], list[str], list[str]]:
    """Load chapter texts and embed them for topic modeling.

    Uses chapter headline + summary as the document unit — these are
    richer and more semantically coherent than raw utterance chunks.
    Returns (chapter_keys, texts, meeting_ids).
    """
    conn = connect(DB_PATH)
    rows = conn.execute(
        """SELECT c.id AS chapter_id, c.meeting_id, c.headline, c.summary, c.gist
           FROM chapters c
           ORDER BY c.meeting_id, c.start_ms"""
    ).fetchall()
    conn.close()

    keys, texts, meeting_ids = [], [], []
    for r in rows:
        headline = r["headline"] or ""
        summary = r["summary"] or ""
        gist = r["gist"] or ""
        text = f"{headline}. {summary}" if summary else headline
        if gist and gist not in text:
            text = f"{text} ({gist})"
        text = text.strip()
        if len(text) < 20:
            continue
        keys.append(f"chapter-{r['chapter_id']}")
        texts.append(text)
        meeting_ids.append(r["meeting_id"])

    return keys, texts, meeting_ids


def _load_chunks_and_embeddings() -> tuple[list[str], list[str], np.ndarray]:
    """Pull all chunk IDs, documents, and embeddings from Chroma."""
    coll = get_collection()
    total = coll.count()
    if total == 0:
        raise ValueError("No chunks in Chroma. Run `transcripts ingest` first.")

    result = coll.get(include=["embeddings", "documents", "metadatas"])
    ids = result["ids"]
    docs = result["documents"]
    embeddings = np.array(result["embeddings"])
    return ids, docs, embeddings


def _auto_label(keywords: list[tuple[str, float]], rep_docs: list[str]) -> str:
    """Generate a readable topic label from keywords and representative docs.

    Uses heuristics to create labels like 'Amazon PPC Campaign Strategy'
    rather than '0_amazon_ppc_campaign_strategy'.
    """
    # Filter out stopwords and very short tokens
    stopwords = {
        "the", "to", "and", "that", "is", "it", "of", "in", "for", "on",
        "we", "you", "this", "are", "so", "have", "with", "not", "our",
        "they", "can", "was", "be", "do", "but", "or", "an", "if", "its",
        "as", "all", "just", "like", "going", "yeah", "okay", "right",
        "know", "think", "want", "need", "get", "got", "one", "see",
        "also", "will", "would", "could", "should", "been", "were",
        "said", "say", "says", "here", "there", "what", "which", "them",
        "then", "than", "much", "very", "well", "now", "about", "some",
        "more", "good", "new", "way", "look", "make", "thing", "things",
        "lot", "really", "actually", "basically", "mean", "going",
        "little", "bit", "bye", "thank", "thanks", "hi", "hello",
        "day", "time", "week", "month", "year", "today", "next",
    }

    meaningful = [
        w.title() for w, s in keywords
        if w.lower() not in stopwords and len(w) > 2 and s > 0.005
    ][:5]

    if not meaningful:
        meaningful = [w.title() for w, _ in keywords[:3] if len(w) > 2]

    if not meaningful:
        return "Miscellaneous"

    return " / ".join(meaningful[:4])


def fit_topics(min_topic_size: int = 10, nr_topics: str = "auto") -> dict:
    """Fit BERTopic on chapter summaries and store full hierarchy.

    Uses chapter summaries (headline + summary) as documents for cleaner
    topic clusters. Builds a hierarchical topic tree and auto-labels
    each topic with readable names.
    """
    from bertopic import BERTopic
    from sklearn.decomposition import PCA
    from hdbscan import HDBSCAN
    from transcripts.embedder import Embedder

    # Load chapter summaries and embed them
    keys, texts, meeting_ids = _load_chapter_summaries()
    if len(texts) < min_topic_size * 2:
        raise ValueError(f"Only {len(texts)} chapter summaries. Need more data.")

    print(f"Embedding {len(texts)} chapter summaries...")
    embedder = Embedder()
    embeddings = embedder.embed_documents(texts)

    pca_model = PCA(n_components=min(20, len(texts) - 1, embeddings.shape[1]))
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_topic_size,
        min_samples=3,
        prediction_data=True,
    )

    topic_model = BERTopic(
        embedding_model=None,
        umap_model=pca_model,
        hdbscan_model=hdbscan_model,
        min_topic_size=min_topic_size,
        nr_topics=nr_topics,
        verbose=True,
    )
    topics, probs = topic_model.fit_transform(texts, embeddings=embeddings)

    # Save model
    BERTOPIC_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    topic_model.save(
        str(BERTOPIC_MODEL_DIR),
        serialization="safetensors",
        save_ctfidf=True,
        save_embedding_model=False,
    )

    # Build hierarchy
    hierarchy_df = None
    try:
        hierarchy_df = topic_model.hierarchical_topics(texts)
    except Exception as e:
        print(f"Warning: could not build hierarchy: {e}")

    # Store everything in SQLite
    _store_results(topic_model, keys, topics, probs, meeting_ids, hierarchy_df)

    # Save representative docs
    _save_cluster_reps(topic_model, texts)

    # Save hierarchy as JSON for visualization
    if hierarchy_df is not None:
        _save_hierarchy_json(topic_model, hierarchy_df)

    topic_info = topic_model.get_topic_info()
    real_topics = len(topic_info[topic_info["Topic"] != -1])
    return {
        "num_topics": real_topics,
        "num_chapters": len(texts),
        "num_outliers": int((np.array(topics) == -1).sum()),
        "model_path": str(BERTOPIC_MODEL_DIR),
        "cluster_reps_path": str(CLUSTER_REPS_PATH),
    }


def _store_results(topic_model, chapter_keys, topics, probs, meeting_ids, hierarchy_df):
    """Persist topics (leaf + hierarchy nodes) and assignments to SQLite."""
    init_db(DB_PATH)
    conn = connect(DB_PATH)

    conn.execute("DELETE FROM topic_assignments")
    conn.execute("DELETE FROM topics")

    # Insert leaf topics with auto-generated labels
    topic_info = topic_model.get_topic_info()
    for _, row in topic_info.iterrows():
        tid = int(row["Topic"])
        if tid == -1:
            continue
        keywords = topic_model.get_topic(tid)
        keywords_json = json.dumps(keywords[:10]) if keywords else "[]"
        rep_docs = row.get("Representative_Docs", [])
        label = _auto_label(keywords or [], list(rep_docs or []))
        conn.execute(
            "INSERT INTO topics (id, name, parent_id, level, keywords_json) VALUES (?, ?, ?, ?, ?)",
            (tid, label, None, 0, keywords_json),
        )

    # Insert hierarchy merge nodes and set parent relationships
    if hierarchy_df is not None and not hierarchy_df.empty:
        # Collect all merge node IDs
        merge_nodes = set()
        for _, row in hierarchy_df.iterrows():
            parent_id = int(row["Parent_ID"])
            merge_nodes.add(parent_id)

        # Insert merge nodes as topics (level > 0)
        # Merge nodes get labels from their children's keywords
        for mid in sorted(merge_nodes):
            # Find children of this merge node
            children = []
            for _, row in hierarchy_df.iterrows():
                if int(row["Parent_ID"]) == mid:
                    children.extend([int(row["Child_Left_ID"]), int(row["Child_Right_ID"])])
            children = [c for c in children if c >= 0]

            # Aggregate keywords from leaf children
            child_keywords = []
            for cid in children:
                kw = topic_model.get_topic(cid)
                if kw:
                    child_keywords.extend(kw[:3])

            # Deduplicate preserving order
            seen = set()
            deduped = []
            for w, s in child_keywords:
                if w not in seen:
                    seen.add(w)
                    deduped.append((w, s))

            label = _auto_label(deduped, [])
            keywords_json = json.dumps(deduped[:10])

            # Determine level by counting ancestors
            level = 1
            current = mid
            visited = {current}
            while True:
                parent_row = hierarchy_df[hierarchy_df["Child_Left_ID"] == current]
                if parent_row.empty:
                    parent_row = hierarchy_df[hierarchy_df["Child_Right_ID"] == current]
                if parent_row.empty:
                    break
                current = int(parent_row.iloc[0]["Parent_ID"])
                if current in visited:
                    break
                visited.add(current)
                level += 1

            conn.execute(
                "INSERT OR REPLACE INTO topics (id, name, parent_id, level, keywords_json) VALUES (?, ?, ?, ?, ?)",
                (mid, label, None, level, keywords_json),
            )

        # Set parent_id on all children
        for _, row in hierarchy_df.iterrows():
            parent_id = int(row["Parent_ID"])
            for child_id in [int(row["Child_Left_ID"]), int(row["Child_Right_ID"])]:
                if child_id >= 0:
                    conn.execute(
                        "UPDATE topics SET parent_id = ? WHERE id = ?",
                        (parent_id, child_id),
                    )

    # Insert chapter-to-topic assignments
    prob_array = np.array(probs) if probs is not None else None
    assignments = []
    for i, (key, tid) in enumerate(zip(chapter_keys, topics)):
        if tid == -1:
            continue
        p = float(prob_array[i]) if prob_array is not None and prob_array.ndim == 1 else 1.0
        assignments.append((key, int(tid), p))

    conn.executemany(
        "INSERT INTO topic_assignments (chunk_id, topic_id, probability) VALUES (?, ?, ?)",
        assignments,
    )

    # Also link meetings to topics via a count of their chapters in each topic
    # (stored as chunk_id = "meeting:{meeting_id}" for easy lookup)
    from collections import Counter
    meeting_topic_counts: dict[str, Counter] = {}
    for i, (mid, tid) in enumerate(zip(meeting_ids, topics)):
        if tid == -1:
            continue
        meeting_topic_counts.setdefault(mid, Counter())[tid] += 1

    for mid, counter in meeting_topic_counts.items():
        dominant_topic = counter.most_common(1)[0][0]
        assignments.append((f"meeting:{mid}", int(dominant_topic), 1.0))

    # Re-insert with meeting links
    conn.executemany(
        "INSERT OR IGNORE INTO topic_assignments (chunk_id, topic_id, probability) VALUES (?, ?, ?)",
        [(f"meeting:{mid}", int(counter.most_common(1)[0][0]), 1.0)
         for mid, counter in meeting_topic_counts.items()],
    )

    conn.commit()
    conn.close()


def _save_cluster_reps(topic_model, docs: list[str]):
    """Save representative docs per topic to JSON."""
    reps = {}
    topic_info = topic_model.get_topic_info()
    for _, row in topic_info.iterrows():
        tid = int(row["Topic"])
        if tid == -1:
            continue
        keywords = topic_model.get_topic(tid)
        label = _auto_label(keywords or [], [])
        rep_docs = row.get("Representative_Docs", [])
        reps[str(tid)] = {
            "topic_id": tid,
            "name": label,
            "keywords": ", ".join(w for w, _ in (keywords[:8] if keywords else [])),
            "representative_docs": list(rep_docs or [])[:10],
        }

    with open(CLUSTER_REPS_PATH, "w") as f:
        json.dump(reps, f, indent=2)


def _save_hierarchy_json(topic_model, hierarchy_df):
    """Save the hierarchy as a nested JSON tree for visualization."""
    topic_info = topic_model.get_topic_info()

    # Build node lookup
    nodes = {}
    for _, row in topic_info.iterrows():
        tid = int(row["Topic"])
        if tid == -1:
            continue
        keywords = topic_model.get_topic(tid)
        label = _auto_label(keywords or [], [])
        nodes[tid] = {
            "id": tid,
            "name": label,
            "count": int(row["Count"]),
            "keywords": [w for w, _ in (keywords[:5] if keywords else [])],
            "children": [],
        }

    # Build parent->children from hierarchy
    parent_children: dict[int, list[int]] = {}
    for _, row in hierarchy_df.iterrows():
        pid = int(row["Parent_ID"])
        parent_children.setdefault(pid, [])
        for cid in [int(row["Child_Left_ID"]), int(row["Child_Right_ID"])]:
            if cid >= 0:
                parent_children[pid].append(cid)

    # Create merge nodes
    for pid, children in parent_children.items():
        if pid not in nodes:
            child_keywords = []
            child_count = 0
            for cid in children:
                if cid in nodes:
                    child_keywords.extend(nodes[cid].get("keywords", []))
                    child_count += nodes[cid].get("count", 0)
            # Deduplicate
            seen = set()
            deduped = []
            for w in child_keywords:
                if w not in seen:
                    seen.add(w)
                    deduped.append(w)
            nodes[pid] = {
                "id": pid,
                "name": " / ".join(w.title() for w in deduped[:4]),
                "count": child_count,
                "keywords": deduped[:5],
                "children": [],
            }

    # Wire children
    for pid, children in parent_children.items():
        if pid in nodes:
            for cid in children:
                if cid in nodes:
                    nodes[pid]["children"].append(nodes[cid])

    # Find root(s) — nodes that are not anyone's child
    all_children = set()
    for children in parent_children.values():
        all_children.update(children)
    roots = [n for nid, n in nodes.items() if nid not in all_children]

    tree = {"name": "All Topics", "children": roots}

    with open(HIERARCHY_PATH, "w") as f:
        json.dump(tree, f, indent=2)


def load_model():
    """Load a previously saved BERTopic model."""
    from bertopic import BERTopic
    return BERTopic.load(str(BERTOPIC_MODEL_DIR))
