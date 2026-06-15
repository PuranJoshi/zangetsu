"""Shared utilities for code-council.

Functions used by both the CLI and the daemon live here so they aren't
duplicated across entry-points.
"""

from __future__ import annotations

import re
import uuid

# Common English filler/stop words stripped from filename slugs.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "it",
        "its",
        "this",
        "that",
        "be",
        "are",
        "was",
        "were",
        "been",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "i",
        "we",
        "you",
        "they",
        "he",
        "she",
        "my",
        "our",
        "your",
        "me",
        "want",
        "need",
        "like",
        "would",
        "should",
        "could",
        "can",
        "will",
        "just",
        "also",
        "some",
        "very",
        "so",
        "up",
        "out",
        "about",
        "into",
        "over",
        "then",
        "than",
        "all",
        "let",
        "lets",
    }
)


def slugify(description: str) -> str:
    """Create a short, filesystem-safe slug from a description.

    Strips stop/filler words and keeps the first 4 meaningful content
    words (lowercased, hyphen-separated).  Falls back to ``"plan"``
    for empty descriptions.

    Examples:
        "Add user authentication"       -> "add-user-authentication"
        "Want to build a cash deposit"  -> "build-cash-deposit"
        ""                              -> "plan"
    """
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", description).strip().lower()
    words = [w for w in cleaned.split() if w not in STOP_WORDS]
    return "-".join(words[:4]) if words else "plan"


def generate_plan_id(description: str) -> str:
    """Generate a plan ID as a 12-character hex string.

    The plan ID is a unique opaque identifier (no slug).  Use
    :func:`plan_filename_stem` when you need a human-readable
    filename that includes a slug.

    Examples:
        "Add user authentication"  -> "58cf313f796a"
        ""                         -> "a1b2c3d4e5f6"
    """
    return uuid.uuid4().hex[:12]


def plan_filename_stem(plan_id: str, description: str) -> str:
    """Build a human-readable filename stem for a plan/transcript.

    Format: ``<plan_id>-<slug>``  (e.g. ``58cf313f796a-cash-deposit``).
    The slug is derived from *description* via :func:`slugify`.

    Used by storage and transcript modules for the on-disk filename
    while the internal ``plan_id`` remains the short hex string.
    """
    slug = slugify(description)
    return f"{plan_id}-{slug}"
