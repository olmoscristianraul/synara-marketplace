# -*- coding: utf-8 -*-
"""Utility helpers for fotoapp models."""
from __future__ import annotations

import re
import unicodedata


_slug_regex = re.compile(r"[^a-z0-9]+")


def slugify_text(value: str | None, fallback: str = 'item') -> str:
    """Return a URL-friendly slug.

    Parameters
    ----------
    value: str | None
        Source text. If empty, uses fallback.
    fallback: str
        Value to return when slug would be empty.
    """
    if not value:
        value = fallback or 'item'
    normalized = unicodedata.normalize('NFKD', value)
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    slug = _slug_regex.sub('-', ascii_text.lower()).strip('-')
    return slug or fallback.lower()
