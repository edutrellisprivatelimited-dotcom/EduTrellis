"""Keyword-based product lookup for the AI chat — lets it show real,
verified EduTrellis Store products (real photos/prices/links) as cards
below its reply, instead of ever trusting the model to describe products
from its own memory (which could hallucinate a name, price, or link that
doesn't exist). Same keyword-overlap idea as light_mode's knowledge-base
search, just applied to the Product catalogue and tuned for shorter,
catalog-style queries ("headphones", "bluetooth speaker under 2000").
"""
import re

from django.db.models import Q

from myapp.light_mode import MAX_KEYWORDS_FOR_QUERY, _keywords
from myapp.models import Product

MAX_PRODUCTS = 4

# "edutrellis" shows up in almost every product's brand field (and in most
# chat messages, since it's the assistant's own name) — on its own it
# doesn't distinguish one product from another, so it's excluded the same
# way light_mode excludes generic stopwords. Without this, a completely
# unrelated question like "what is EduTrellis?" would keyword-match the
# entire catalogue on the brand field alone.
_IGNORE_KEYWORDS = {'edutrellis'}


def _keyword_variants(kw):
    """icontains is plain substring matching, so a plural query keyword
    ("helicopters") never matches a singular product name ("...RC
    Helicopter") — the 's' makes it a different substring entirely. Adding
    the trailing-s-stripped form as a second variant covers the common
    case without any real NLP; short words are left alone so this can't
    turn something like "gas" into a bad 2-letter stem."""
    variants = {kw}
    if kw.endswith('s') and len(kw) > 4:
        variants.add(kw[:-1])
    return variants


def search_products(query, limit=MAX_PRODUCTS):
    """Unlike light_mode's knowledge-base search (which requires 2+ shared
    keywords because its `content` field is long free-form prose where one
    word can appear incidentally), a product's name/brand/description/tags/
    category are short, curated, specific fields — a single real keyword
    landing in any of them (once the store's own name is filtered out
    above) is already a meaningful signal for a catalog-style query like
    "show me a speaker"."""
    keywords = [kw for kw in _keywords(query) if kw not in _IGNORE_KEYWORDS][:MAX_KEYWORDS_FOR_QUERY]
    if not keywords:
        return []
    variants_by_kw = {kw: _keyword_variants(kw) for kw in keywords}
    all_variants = {v for variants in variants_by_kw.values() for v in variants}

    q = Q()
    for v in all_variants:
        q |= (
            Q(name__icontains=v) | Q(brand__icontains=v) | Q(short_description__icontains=v)
            | Q(tags__icontains=v) | Q(category__name__icontains=v)
        )
    candidates = list(Product.objects.filter(q, is_active=True).select_related('category')[:60])

    scored = []
    for p in candidates:
        haystack = f"{p.name} {p.brand} {p.short_description} {p.tags} {p.category.name}".lower()
        hits = sum(1 for kw in keywords if any(v in haystack for v in variants_by_kw[kw]))
        if hits >= 1:
            scored.append((p, hits))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [p for p, _ in scored][:limit]


# A generic "show me your products"/"what do you sell" ask has no specific
# keyword to match against name/brand/description/tags/category, so
# search_products() above correctly returns nothing for it — but the user
# still asked to browse, and the assistant was live-tested telling them to
# "take a look at the options below" with literally nothing rendered below.
# This catches that specific shape of request so the caller can fall back
# to a general product selection instead of an empty result.
_GENERAL_BROWSE_RE = re.compile(
    r"\b(show|see|list|browse)\b[^.!?]{0,25}\b(product|item|option|thing|"
    r"catalog(?:ue)?)s?\b|"
    r"\bwhat (?:do you (?:have|sell)|products? (?:do you have|(?:do )?you sell))\b|"
    r"\b(all|your|the) products?\b|\bproduct listing\b|\bwhat'?s available\b|"
    r"\b(e-?store|store) products\b",
    re.IGNORECASE,
)


def is_general_browse_request(text):
    return bool(_GENERAL_BROWSE_RE.search(text or ''))


def browse_products(limit=MAX_PRODUCTS):
    """Fallback for is_general_browse_request() — no keyword to rank by, so
    just the store's normal display order (same one the estore page itself
    uses)."""
    return list(Product.objects.filter(is_active=True).select_related('category')[:limit])
