import re

# Tokens that look like common non-client words (topics, actions, tools).
# If a token matches one of these, it's unlikely to be part of a client/brand name.
_TOPIC_INDICATORS = {
    "ad", "ads", "audit", "analysis", "amazon", "api", "automation",
    "bid", "brand", "budget", "buy", "box",
    "campaign", "case", "combining", "create", "custom",
    "dashboard", "data", "day", "deep", "dive",
    "file", "full",
    "guide",
    "how", "hour",
    "improvement", "intro",
    "keyword",
    "launch", "listing", "ltv",
    "new",
    "onboarding", "optimization", "optmization", "overview",
    "part", "ppc", "product", "program", "project",
    "report", "reporting", "review",
    "search", "setup", "sop", "sp", "sqp", "strategy",
    "targeting", "terms", "time", "tool", "tools", "top", "tutorial",
    "unpaid", "update", "use",
    "v2", "video",
    "walkthrough", "weekly",
}

# Known brand/client names that are also common words or acronyms
_KNOWN_CLIENTS = {"amc"}


def parse_filename(filename: str) -> dict:
    """Parse a transcript filename into client, topic, and stem.

    Examples:
        "22_Ventures_Vaginal_Probiotics_Analysis_transcribed.json"
        -> {"client": "22 Ventures", "topic": "Vaginal Probiotics Analysis",
            "stem": "22_Ventures_Vaginal_Probiotics_Analysis"}
    """
    # Strip directory components
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    # Strip extensions
    name = re.sub(r"\.json$", "", name)

    # Strip _transcribed suffix
    stem = re.sub(r"_transcribed$", "", name)

    tokens = stem.split("_")

    # Filter out empty tokens (from double underscores)
    tokens = [t for t in tokens if t]

    if not tokens:
        return {"client": "", "topic": "", "stem": stem}

    if len(tokens) == 1:
        return {"client": "", "topic": tokens[0], "stem": stem}

    # Heuristically determine client prefix: take leading tokens (up to 2)
    # that look like a brand/company name rather than a topic word.
    # A token qualifies as a client token if it's a known client name,
    # a number, or a short acronym (all caps, <=5 chars).
    client_end = 0
    for i, token in enumerate(tokens[:3]):
        low = token.lower()
        if low in _KNOWN_CLIENTS:
            client_end = i + 1
            continue
        if low in _TOPIC_INDICATORS:
            break
        # Numbers (e.g. "22") are likely part of a brand name
        if token.isdigit():
            client_end = i + 1
            continue
        # Short all-caps acronyms not in topic indicators (e.g. "IBM")
        if token.isupper() and len(token) <= 5:
            client_end = i + 1
            continue
        # Mixed-case capitalized word: include only if we already have
        # exactly one preceding client token and haven't reached 2 yet
        # (e.g. "22 Ventures" but stop before "Vaginal")
        if token[0].isupper() and client_end == i and client_end == 1:
            client_end = i + 1
            continue
        break

    client_tokens = tokens[:client_end]
    topic_tokens = tokens[client_end:]

    client = " ".join(client_tokens)
    topic = " ".join(topic_tokens)

    return {"client": client, "topic": topic, "stem": stem}
