"""Shared utilities for code-council.

Functions used by both the CLI and the daemon live here so they aren't
duplicated across entry-points.
"""

from __future__ import annotations

import re
import uuid


# Common English filler/stop words stripped from plan-ID slugs.
STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "this", "that", "be",
    "are", "was", "were", "been", "do", "does", "did", "has", "have", "had",
    "i", "we", "you", "they", "he", "she", "my", "our", "your", "me",
    "want", "need", "like", "would", "should", "could", "can", "will",
    "just", "also", "some", "very", "so", "up", "out", "about", "into",
    "over", "then", "than", "all", "let", "lets",
})


def generate_plan_id(description: str) -> str:
    """Generate a plan ID in the format ``<hex>-<slug>``.

    The hex prefix is 12 characters from a UUID4 for uniqueness.
    The slug is a short, filesystem-safe summary derived from the
    description -- stop/filler words are stripped so the slug captures
    the *meaningful* terms (max 4 content words, lowercased, hyphened).

    Examples:
        "Add user authentication"    -> "58cf313f796a-add-user-authentication"
        "Want to build a cash deposit feature"
                                     -> "a1b2c3d4e5f6-cash-deposit-feature"
        "I need to implement payment webhooks for Stripe"
                                     -> "a1b2c3d4e5f6-implement-payment-webhooks-stripe"
        ""                           -> "58cf313f796a-plan"
    """
    hex_part = uuid.uuid4().hex[:12]

    # Slugify: keep only alphanumeric + spaces, collapse, strip stop words,
    # then take the first 4 meaningful words.
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", description).strip().lower()
    words = [w for w in slug.split() if w not in STOP_WORDS]
    slug = "-".join(words[:4]) if words else "plan"

    return f"{hex_part}-{slug}"
